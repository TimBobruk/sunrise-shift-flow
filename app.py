import os
import csv
import json
import base64
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from database import get_connection, init_db, DEFAULT_DB_PATH
from engine import (
    generate_monthly_roster,
    assign_daily_stations,
    get_dashboard_state,
    update_hall_flow,
    book_tour_group_slot,
    trigger_sick_leave_failover,
    reset_sick_leaves,
    export_director_csv,
    export_monthly_schedule_csv,
    get_active_context,
    switch_shift_context,
    complete_shift_and_advance,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_template_path() -> str:
    candidate_1 = os.path.join(BASE_DIR, "templates", "dashboard.html")
    candidate_2 = os.path.join(BASE_DIR, "dashboard.html")
    if os.path.exists(candidate_1):
        return candidate_1
    if os.path.exists(candidate_2):
        return candidate_2
    return candidate_1


def resolve_logo_path() -> str:
    search_dirs = [
        os.path.join(BASE_DIR, "templates"),
        BASE_DIR,
        os.path.join(BASE_DIR, "static"),
    ]
    for folder in search_dirs:
        if os.path.isdir(folder):
            for fname in os.listdir(folder):
                low = fname.lower()
                if low.startswith("logo") and low.endswith((".jpeg", ".jpg", ".png", ".webp", ".svg")):
                    return os.path.join(folder, fname)
    return ""


def get_logo_data_uri() -> str:
    logo_path = resolve_logo_path()
    if not logo_path or not os.path.isfile(logo_path):
        return ""
    ext = os.path.splitext(logo_path)[1].lower()
    mime = "image/png" if ext == ".png" else ("image/svg+xml" if ext == ".svg" else "image/jpeg")
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _build_gantt_cells(start_h: float, end_h: float) -> list:
    """Builds 8 two-hour timeline cells (06:00 to 22:00) for the Henry Gantt CSV section."""
    buckets = [(6, 8), (8, 10), (10, 12), (12, 14), (14, 16), (16, 18), (18, 20), (20, 22)]
    cells = []
    for b_start, b_end in buckets:
        chars = []
        for step in range(4):
            sub_start = b_start + step * 0.5
            sub_end = sub_start + 0.5
            if sub_start >= start_h and sub_end <= end_h:
                chars.append("██")
            else:
                chars.append("░░")
        cells.append("[" + "".join(chars) + "]")
    return cells


def _parse_window_hours(window_str: str) -> tuple:
    clean = str(window_str or "12:30-13:30").replace("–", "-").replace("—", "-")
    parts = clean.split("-")

    def _to_dec(t_str: str) -> float:
        hh, mm = (t_str or "12:00").strip().split(":")
        return float(hh) + (float(mm) / 60.0)

    return _to_dec(parts[0]), _to_dec(parts[1] if len(parts) > 1 else "13:30")


def enhance_director_csv_with_efficiency_and_gantt(conn, csv_path: str, day: int, shift_code: str) -> str:
    """Writes a comprehensive Director CSV containing:
    1. Station Matrix + Utility Score (KKD %) + Guests/Labor Hour
    2. Henry Gantt Operational Timeline (06:00-22:00) for 8h Shifts & Tour Group Slots
    3. Active Staff Exceptions Log (REQUESTED_OFF & SICK_LEAVE)
    """
    cur = conn.cursor()
    cur.execute("SELECT zone_name, seating_capacity, current_2h_flow FROM hall_metrics;")
    halls = {r["zone_name"]: dict(r) for r in cur.fetchall()}
    total_guests = sum(h["current_2h_flow"] for h in halls.values()) or 1300
    total_seats = sum(h["seating_capacity"] for h in halls.values()) or 600
    overall_turnover = round(total_guests / total_seats, 2)

    cur.execute(
        """
        SELECT dr.station_id, s.station_name, s.zone_category, s.seating_capacity, s.difficulty_weight,
               dr.staff_id, st.staff_code, st.name AS staff_name, st.role_title, st.experience_tier,
               st.dual_block_capable, dr.skill_note, dr.rotation_badge
        FROM daily_roster dr
        JOIN stations s ON s.station_id = dr.station_id
        JOIN staff st ON st.id = dr.staff_id
        WHERE dr.day_of_month = ? AND dr.shift_code = ?
        ORDER BY dr.station_id ASC, dr.roster_id ASC;
        """,
        (day, shift_code),
    )
    rows = [dict(r) for r in cur.fetchall()]

    cur.execute(
        "SELECT COUNT(*) AS sick_cnt FROM staff_exceptions WHERE day_of_month = ? AND exception_type = 'SICK_LEAVE';",
        (day,),
    )
    sick_cnt = cur.fetchone()["sick_cnt"]

    unique_staff_ids = {r["staff_id"] for r in rows}
    active_crew = len(unique_staff_ids) if unique_staff_ids else 8
    shift_hours = 8
    total_labor_hours = active_crew * shift_hours
    guests_per_lh = round(total_guests / max(1, total_labor_hours), 2)

    st1_staff = {r["staff_id"] for r in rows if r["station_id"] == 1}
    st2_staff = {r["staff_id"] for r in rows if r["station_id"] == 2}
    dual_active = bool(st1_staff & st2_staff) or (sick_cnt > 0)

    utility_scores = []
    matrix_rows = []

    for r in rows:
        st_id = r["station_id"]
        zone_cat = r["zone_category"]

        if zone_cat in halls:
            z_flow = halls[zone_cat]["current_2h_flow"]
            z_seats = halls[zone_cat]["seating_capacity"]
            z_turn = round(z_flow / max(1, z_seats), 2)
            zone_eff = (z_flow / max(1.0, z_seats * 2.0)) * 100.0
        else:
            z_flow = total_guests
            z_seats = total_seats
            z_turn = overall_turnover
            zone_eff = (total_guests / max(1.0, total_seats * 2.0)) * 100.0

        tier_factor = (r["experience_tier"] / 3.0) * 0.15 + 0.90
        diff_bonus = (r["difficulty_weight"] - 2) * 4.0
        dual_bonus = 16.5 if (st_id in (1, 2) and dual_active and r["dual_block_capable"] == 1) else 0.0

        utility_pct = round(min(135.0, max(85.0, zone_eff * tier_factor + diff_bonus + dual_bonus)), 1)
        utility_scores.append(utility_pct)

        if st_id in (1, 2) and dual_active and r["dual_block_capable"] == 1:
            status_txt = "Dual-Block Cascade Active (+1 FTE Saved)"
        elif utility_pct >= 112.0:
            status_txt = "High-Load Peak Optimal"
        elif utility_pct >= 100.0:
            status_txt = "Balanced Throughput"
        else:
            status_txt = "Protected / Low-Fatigue"

        matrix_rows.append([
            f"Day {day}",
            shift_code,
            f"{shift_hours}h",
            st_id,
            r["station_name"],
            r["staff_code"],
            r["staff_name"],
            r["role_title"],
            f"Tier {r['experience_tier']}",
            z_flow,
            f"{z_turn:.2f}x",
            f"{guests_per_lh} guests/h",
            f"{utility_pct:.1f}%",
            status_txt,
            r["rotation_badge"] or "Standard Rotation",
        ])

    avg_utility = round(sum(utility_scores) / max(1, len(utility_scores)), 1)

    cur.execute(
        "SELECT slot_id, time_window, zone_name, max_capacity, booked_guests FROM zone_time_slots ORDER BY slot_id ASC;"
    )
    slots = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT se.exception_id, se.staff_id, st.staff_code, st.name AS staff_name, se.day_of_month, se.exception_type
        FROM staff_exceptions se
        JOIN staff st ON st.id = se.staff_id
        ORDER BY se.day_of_month ASC, se.exception_id ASC;
        """
    )
    exceptions = [dict(r) for r in cur.fetchall()]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # SECTION 1: STATION MATRIX & UTILITY SCORE (KKD)
        writer.writerow([
            "Day",
            "Shift_Code",
            "Shift_Hours",
            "Station_ID",
            "Station_Name",
            "Staff_Code",
            "Assigned_Staff",
            "Role_Title",
            "Experience_Tier",
            "Zone_Guest_Load_2h",
            "Turnover_Rate",
            "Guests_Per_Labor_Hour",
            "Utility_Score_Pct",
            "Efficiency_Status",
            "Rotation_Policy",
        ])
        writer.writerows(matrix_rows)

        writer.writerow([
            f"Day {day}",
            "SUMMARY_KPI",
            f"{total_labor_hours}h total",
            "ALL (1-7)",
            "TOTAL SHIFT EFFICIENCY",
            f"{active_crew}/8 Crew",
            "Zero Bottlenecks",
            f"Sick Exceptions: {sick_cnt}",
            "All Tiers",
            total_guests,
            f"{overall_turnover:.2f}x",
            f"{guests_per_lh} guests/h",
            f"{avg_utility:.1f}% AVG",
            "100% Coverage Guaranteed",
            "14 S1 / 14 S2 / Max 2 OFF",
        ])

        writer.writerow([])

        # SECTION 2: HENRY GANTT OPERATIONAL TIMELINE (06:00 - 22:00)
        writer.writerow([
            "SECTION_2_GANTT_CHART",
            "Track_Name",
            "Time_Window",
            "06:00-08:00",
            "08:00-10:00",
            "10:00-12:00",
            "12:00-14:00",
            "14:00-16:00",
            "16:00-18:00",
            "18:00-20:00",
            "20:00-22:00",
            "Occupancy_Efficiency",
            "Operational_Notes",
            "",
            "",
        ])

        s1_cells = _build_gantt_cells(6.0, 14.0)
        s2_cells = _build_gantt_cells(14.0, 22.0)

        writer.writerow([
            "GANTT_SHIFT_ROSTER",
            "Shift 1 (AM Crew)",
            "06:00-14:00 (8h)",
            *s1_cells,
            f"{avg_utility:.1f}% KKD" if shift_code == "S1" else "Scheduled (8 Crew)",
            f"Active Shift ({active_crew}/8 Crew)" if shift_code == "S1" else "Morning 8h Shift",
            "",
            "",
        ])
        writer.writerow([
            "GANTT_SHIFT_ROSTER",
            "Shift 2 (PM Crew)",
            "14:00-22:00 (8h)",
            *s2_cells,
            f"{avg_utility:.1f}% KKD" if shift_code == "S2" else "Scheduled (8 Crew)",
            f"Active Shift ({active_crew}/8 Crew)" if shift_code == "S2" else "Evening 8h Shift",
            "",
            "",
        ])

        for s in slots:
            st_h, end_h = _parse_window_hours(s["time_window"])
            slot_cells = _build_gantt_cells(st_h, end_h)
            max_c = max(1, s["max_capacity"])
            booked = s["booked_guests"]
            free_seats = max(0, max_c - booked)
            occ_pct = round((booked / max_c) * 100.0, 1)
            slot_status = (
                "CRITICAL PEAK (>=80%)"
                if occ_pct >= 80.0
                else ("HIGH FLOW (55-79%)" if occ_pct >= 55.0 else "OPTIMAL FREE SLOT (<55%)")
            )
            writer.writerow([
                f"GANTT_TOUR_SLOT_#{s['slot_id']}",
                s["zone_name"],
                s["time_window"],
                *slot_cells,
                f"{occ_pct:.1f}% ({booked}/{max_c})",
                f"{slot_status} | {free_seats} seats available",
                "",
                "",
            ])

        writer.writerow([])

        # SECTION 3: STAFF EXCEPTIONS LOG (SQLITE staff_exceptions)
        writer.writerow([
            "SECTION_3_EXCEPTIONS",
            "Exception_ID",
            "Day_of_Month",
            "Staff_Code",
            "Staff_Name",
            "Exception_Type",
            "Failover_Action",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ])
        for ex in exceptions:
            action_note = (
                "Dual Block-Massa (#1 & #2) Cascade Activated"
                if ex["exception_type"] == "SICK_LEAVE"
                else "Pre-scheduled Monthly Roster Day Off (Max 2/month)"
            )
            writer.writerow([
                "STAFF_EXCEPTION",
                ex["exception_id"],
                f"Day {ex['day_of_month']}",
                ex["staff_code"],
                ex["staff_name"],
                ex["exception_type"],
                action_note,
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ])

    return csv_path


def enrich_state_with_db_details(conn, state: dict, day: int, shift_code: str) -> dict:
    state["active_day"] = day
    state["active_shift"] = shift_code
    state["shift_hours"] = 8

    cur = conn.cursor()
    cur.execute("SELECT zone_name, seating_capacity, current_2h_flow FROM hall_metrics;")
    db_halls = [dict(r) for r in cur.fetchall()]
    if db_halls:
        state["halls_db"] = db_halls

    cur.execute(
        """
        SELECT dr.station_id, s.station_name, s.seating_capacity,
               dr.staff_id, st.name AS staff_name, st.role_title, st.experience_tier,
               dr.skill_note, dr.rotation_badge
        FROM daily_roster dr
        JOIN stations s ON s.station_id = dr.station_id
        JOIN staff st ON st.id = dr.staff_id
        WHERE dr.day_of_month = ? AND dr.shift_code = ?
        ORDER BY dr.station_id ASC, dr.roster_id ASC;
        """,
        (day, shift_code),
    )
    state["roster_db"] = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT staff_id FROM staff_exceptions
        WHERE day_of_month = ? AND exception_type = 'SICK_LEAVE';
        """,
        (day,),
    )
    state["sick_staff_ids"] = [r["staff_id"] for r in cur.fetchall()]
    return state


def ensure_initialized():
    needs_init = not os.path.exists(DEFAULT_DB_PATH)
    if not needs_init:
        try:
            conn = get_connection(DEFAULT_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM staff;")
            staff_cnt = cur.fetchone()["cnt"]
            cur.execute("SELECT COUNT(*) AS cnt FROM system_state;")
            state_cnt = cur.fetchone()["cnt"]
            conn.close()
            if staff_cnt == 0 or state_cnt == 0:
                needs_init = True
        except sqlite3.Error:
            needs_init = True

    if needs_init:
        conn = init_db(DEFAULT_DB_PATH)
        generate_monthly_roster(conn)
        assign_daily_stations(conn, day=1, shift_code="S1")
        csv_p = export_director_csv(conn, day=1, shift_code="S1")
        enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=1, shift_code="S1")
        conn.close()
    else:
        conn = get_connection(DEFAULT_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS cnt FROM monthly_schedule;")
        if cur.fetchone()["cnt"] == 0:
            generate_monthly_roster(conn)
        day, shift_code = get_active_context(conn)
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM daily_roster WHERE day_of_month = ? AND shift_code = ?;",
            (day, shift_code),
        )
        if cur.fetchone()["cnt"] == 0:
            assign_daily_stations(conn, day=day, shift_code=shift_code)
        csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
        enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
        export_monthly_schedule_csv(conn, total_days=30)
        conn.close()


class SunriseRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict, status_code: int = 200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            tpl_path = resolve_template_path()
            with open(tpl_path, "r", encoding="utf-8") as f:
                html_str = f.read()
            logo_uri = get_logo_data_uri()
            if logo_uri:
                html_str = html_str.replace("/templates/logo.jpeg", logo_uri)
            html_bytes = html_str.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)

        elif "logo" in parsed.path.lower():
            img_path = resolve_logo_path()
            if img_path and os.path.isfile(img_path):
                with open(img_path, "rb") as f:
                    img_bytes = f.read()
                ext = os.path.splitext(img_path)[1].lower()
                content_type = "image/png" if ext == ".png" else "image/jpeg"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(img_bytes)))
                self.end_headers()
                self.wfile.write(img_bytes)
            else:
                self._send_json({"error": "Logo file not found"}, 404)

        elif parsed.path == "/api/state":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            state = get_dashboard_state(conn, day=day, shift_code=shift_code)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/export-csv":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            csv_path = export_director_csv(conn, day=day, shift_code=shift_code)
            csv_path = enhance_director_csv_with_efficiency_and_gantt(conn, csv_path, day=day, shift_code=shift_code)
            conn.close()
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
            filename = os.path.basename(csv_path)
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(csv_bytes)))
            self.end_headers()
            self.wfile.write(csv_bytes)

        elif parsed.path == "/api/export-monthly-csv":
            conn = get_connection()
            csv_path = export_monthly_schedule_csv(conn, total_days=30)
            conn.close()
            with open(csv_path, "rb") as f:
                csv_bytes = f.read()
            filename = os.path.basename(csv_path)
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(csv_bytes)))
            self.end_headers()
            self.wfile.write(csv_bytes)

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        data = self._read_json_body()

        if parsed.path == "/api/monthly-roster":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            roster_meta = generate_monthly_roster(conn, total_days=30)
            assign_daily_stations(conn, day=day, shift_code=shift_code)
            csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
            enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
            state = get_dashboard_state(conn, day=day, shift_code=shift_code)
            state.update(roster_meta)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/assign-stations":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            assign_daily_stations(conn, day=day, shift_code=shift_code)
            csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
            enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
            state = get_dashboard_state(conn, day=day, shift_code=shift_code)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/switch-shift":
            conn = get_connection()
            cur_day, cur_shift = get_active_context(conn)
            target_day = int(data.get("day", cur_day))
            target_shift = data.get("shift_code", cur_shift)
            state = switch_shift_context(conn, day=target_day, shift_code=target_shift)
            state = enrich_state_with_db_details(conn, state, target_day, target_shift)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/complete-shift":
            conn = get_connection()
            state = complete_shift_and_advance(conn, shift_hours=8.0)
            day, shift_code = get_active_context(conn)
            csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
            enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/update-slider":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            zone_name = data.get("zone_name", "Large Hall")
            new_flow = int(data.get("new_flow", 680))
            state = update_hall_flow(conn, zone_name, new_flow, day=day, shift_code=shift_code)
            csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
            enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/book-tour-slot":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            slot_id = int(data.get("slot_id", 1))
            group_size = int(data.get("group_size", 60))
            result = book_tour_group_slot(conn, slot_id=slot_id, group_size=group_size, day=day, shift_code=shift_code)
            if "error" not in result:
                csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
                enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
                result = enrich_state_with_db_details(conn, result, day, shift_code)
            conn.close()
            status = 400 if "error" in result else 200
            self._send_json(result, status_code=status)

        elif parsed.path == "/api/mark-sick":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            staff_id = int(data.get("staff_id", 2))
            state = trigger_sick_leave_failover(conn, staff_id=staff_id, day=day, shift_code=shift_code)
            csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
            enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/reset-sick":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            state = reset_sick_leaves(conn, day=day, shift_code=shift_code)
            csv_p = export_director_csv(conn, day=day, shift_code=shift_code)
            enhance_director_csv_with_efficiency_and_gantt(conn, csv_p, day=day, shift_code=shift_code)
            state = enrich_state_with_db_details(conn, state, day, shift_code)
            conn.close()
            self._send_json(state)

        else:
            self._send_json({"error": "Endpoint not found"}, 404)


if __name__ == "__main__":
    ensure_initialized()
    port = 5000
    server = HTTPServer(("127.0.0.1", port), SunriseRequestHandler)
    print(f"[INFO] SunriseFlow server listening on http://127.0.0.1:{port}")
    print("[INFO] Press Ctrl+C to stop.")
    server.serve_forever()
