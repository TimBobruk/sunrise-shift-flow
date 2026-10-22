import os
import csv
from datetime import datetime
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")


def classify_hall_status(flow_2h: int, seats: int) -> dict:
    """
    Calculate table turnover and visual status (color & badge) for a dining hall.
    - Turnover >= 2.20x -> Critical turnover (Burnt Orange / Red #FC6C26)
    - Turnover 2.05x..2.19x -> High turnover (Amber #D97706)
    - Turnover < 2.05x -> Steady flow (Green #059669)
    """
    turnover = round(flow_2h / seats, 2) if seats > 0 else 0.0
    fill_pct = min(100, max(10, int(round((flow_2h / (seats * 2.5)) * 100))))

    if turnover >= 2.20:
        return {
            "turnover": turnover,
            "fill_pct": fill_pct,
            "badge_text": "Critical turnover",
            "color_class": "status-critical",
            "hex_color": "#FC6C26",
            "note": "Needs fast reset + dual block",
        }
    elif turnover >= 2.05:
        return {
            "turnover": turnover,
            "fill_pct": fill_pct,
            "badge_text": "High turnover",
            "color_class": "status-high",
            "hex_color": "#D97706",
            "note": "Continuous table clearing",
        }
    else:
        return {
            "turnover": turnover,
            "fill_pct": fill_pct,
            "badge_text": "Steady flow",
            "color_class": "status-steady",
            "hex_color": "#059669",
            "note": "1 dedicated waiter sufficient",
        }


def export_monthly_schedule_csv(conn: sqlite3.Connection, total_days: int = 30) -> str:
    """
    Create a standalone CSV document with the full 30-day schedule for all 16 staff members.
    Saves both in the project root (Monthly_Schedule_30_Days.csv) and in exports/.
    """
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id, staff_code, name, role_title, monthly_s1_count, monthly_s2_count, days_off_taken
        FROM staff
        ORDER BY id ASC;
        """
    )
    staff_rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute(
        "SELECT staff_id, day_of_month, shift_code FROM monthly_schedule ORDER BY staff_id ASC, day_of_month ASC;"
    )
    sched_map = {}
    for r in cursor.fetchall():
        sched_map[(r["staff_id"], r["day_of_month"])] = r["shift_code"]

    header = (
        ["Staff Code", "Name", "Role"]
        + [f"Day {d}" for d in range(1, total_days + 1)]
        + ["Total S1", "Total S2", "Total OFF"]
    )
    rows_to_write = [header]

    for s in staff_rows:
        sid = s["id"]
        day_cells = [sched_map.get((sid, d), "OFF") for d in range(1, total_days + 1)]
        rows_to_write.append(
            [s["staff_code"], s["name"], s["role_title"]]
            + day_cells
            + [s["monthly_s1_count"], s["monthly_s2_count"], s["days_off_taken"]]
        )

    root_csv_path = os.path.join(BASE_DIR, "Monthly_Schedule_30_Days.csv")
    export_csv_path = os.path.join(EXPORTS_DIR, "Monthly_Schedule_30_Days.csv")

    for path in (root_csv_path, export_csv_path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows_to_write)

    return root_csv_path


def generate_monthly_roster(conn: sqlite3.Connection, total_days: int = 30) -> dict:
    """
    Button 1: Generate a 30-day schedule for 16 staff members AND save Monthly_Schedule_30_Days.csv.
    Enforces strict equity:
    - Exactly 2 days OFF per person (respecting pre-requested days in staff_exceptions)
    - Exactly 14 Shift 1 (S1) and 14 Shift 2 (S2) per person (28 active shifts)
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM monthly_schedule;")

    cursor.execute("SELECT id FROM staff ORDER BY id ASC;")
    staff_ids = [row["id"] for row in cursor.fetchall()]

    cursor.execute(
        "SELECT staff_id, day_of_month FROM staff_exceptions WHERE exception_type = 'REQUESTED_OFF';"
    )
    requested_map = {}
    for row in cursor.fetchall():
        requested_map.setdefault(row["staff_id"], set()).add(row["day_of_month"])

    for idx, sid in enumerate(staff_ids):
        req_days = sorted(list(requested_map.get(sid, set())))[:2]
        default_off_1 = (idx % 14) + 2
        default_off_2 = ((idx + 7) % 14) + 16

        off_days = set(req_days)
        for candidate in (default_off_1, default_off_2):
            if len(off_days) < 2 and candidate not in off_days:
                off_days.add(candidate)
        while len(off_days) < 2:
            for d in range(1, total_days + 1):
                if d not in off_days:
                    off_days.add(d)
                    break

        s1_count = 0
        s2_count = 0
        off_count = 0

        for day in range(1, total_days + 1):
            if day in off_days:
                shift_code = "OFF"
                off_count += 1
            else:
                prefer_s1 = ((day + idx) % 2 == 1)
                if (prefer_s1 and s1_count < 14) or (s2_count >= 14):
                    shift_code = "S1"
                    s1_count += 1
                else:
                    shift_code = "S2"
                    s2_count += 1

            cursor.execute(
                "INSERT INTO monthly_schedule (day_of_month, staff_id, shift_code) VALUES (?, ?, ?);",
                (day, sid, shift_code),
            )

        cursor.execute(
            """
            UPDATE staff
            SET monthly_s1_count = ?, monthly_s2_count = ?, days_off_taken = ?
            WHERE id = ?;
            """,
            (s1_count, s2_count, off_count, sid),
        )

    conn.commit()
    csv_file = export_monthly_schedule_csv(conn, total_days=total_days)
    return {
        "status": "ok",
        "staff_scheduled": len(staff_ids),
        "days": total_days,
        "schedule_csv": csv_file,
    }


def assign_daily_stations(conn: sqlite3.Connection, day: int = 1, shift_code: str = "S1") -> list:
    """
    Button 2: Auto-assign active shift crew (7-8 staff) across all 7 operational stations.
    Respects role specialization (Shift Lead / Hot Line, Dish Stewards, Terrace & Hall Waiters),
    yesterday's Dirty Dish rotation protection, and Small Hall protection for highest weekly_hours staff.
    """
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS cnt FROM monthly_schedule;")
    if cursor.fetchone()["cnt"] == 0:
        generate_monthly_roster(conn)

    cursor.execute(
        "DELETE FROM daily_roster WHERE day_of_month = ? AND shift_code = ?;",
        (day, shift_code),
    )

    cursor.execute(
        """
        SELECT s.id, s.staff_code, s.name, s.role_title, s.experience_tier,
               s.dual_block_capable, s.weekly_hours
        FROM staff s
        JOIN monthly_schedule m ON s.id = m.staff_id
        WHERE m.day_of_month = ? AND m.shift_code = ?
          AND s.id NOT IN (
              SELECT staff_id FROM staff_exceptions
              WHERE day_of_month = ? AND exception_type = 'SICK_LEAVE'
          )
        ORDER BY s.dual_block_capable DESC, s.experience_tier DESC, s.weekly_hours ASC;
        """,
        (day, shift_code, day),
    )
    crew = [dict(r) for r in cursor.fetchall()]

    if len(crew) < 7:
        existing_ids = {c["id"] for c in crew}
        cursor.execute(
            """
            SELECT id, staff_code, name, role_title, experience_tier, dual_block_capable, weekly_hours
            FROM staff
            WHERE id NOT IN (
                SELECT staff_id FROM staff_exceptions
                WHERE day_of_month = ? AND exception_type = 'SICK_LEAVE'
            )
            ORDER BY weekly_hours ASC;
            """,
            (day,),
        )
        for r in cursor.fetchall():
            if r["id"] not in existing_ids and len(crew) < 7:
                crew.append(dict(r))
                existing_ids.add(r["id"])

    crew = crew[:8]
    used_ids = set()

    cursor.execute(
        "SELECT staff_id FROM daily_roster WHERE day_of_month = ? AND station_id = 7;",
        (max(1, day - 1),),
    )
    yesterday_dirty_ids = {r["staff_id"] for r in cursor.fetchall()}

    def pick_next(condition_fn=lambda c: True):
        for c in crew:
            if c["id"] not in used_ids and condition_fn(c):
                used_ids.add(c["id"])
                return c
        for c in crew:
            if c["id"] not in used_ids:
                used_ids.add(c["id"])
                return c
        return None

    assignments = []

    # 1. Station 1: Hot Block-Massa #1 (Prioritize Acting Shift Lead, then dual_block_capable / Hot Line)
    lead = pick_next(lambda c: c["role_title"] == "Acting Shift Lead") or pick_next(
        lambda c: c["dual_block_capable"] == 1 or "Hot Line" in c["role_title"]
    )
    if lead:
        assignments.append((
            1,
            lead["id"],
            "Tier 3 • Acting Lead covers BOTH Block #1 & #2 on peak",
            "50% Shift 1 / 50% Shift 2",
        ))

    # 2. Station 5: Small Hall (100 seats) -> Protected station for highest weekly_hours waiter/staff
    remaining_non_dish = [
        c for c in crew if c["id"] not in used_ids and "Dish" not in c["role_title"] and "Hot Line" not in c["role_title"]
    ]
    pool_for_small_hall = remaining_non_dish if remaining_non_dish else [c for c in crew if c["id"] not in used_ids]
    if pool_for_small_hall:
        most_tired = max(pool_for_small_hall, key=lambda c: c["weekly_hours"])
        used_ids.add(most_tired["id"])
        assignments.append((
            5,
            most_tired["id"],
            f"Tier {most_tired['experience_tier']} • Protected station (after heavy shift / {most_tired['weekly_hours']}h)",
            "Protected (Easy station today)",
        ))

    # 3. Station 7: Dirty Dish Logistics -> Prefer Dish Steward who didn't work station 7 yesterday
    dirty_steward = (
        pick_next(lambda c: "Dish" in c["role_title"] and c["id"] not in yesterday_dirty_ids)
        or pick_next(lambda c: c["id"] not in yesterday_dirty_ids)
    )
    if dirty_steward:
        assignments.append((
            7,
            dirty_steward["id"],
            f"Tier {dirty_steward['experience_tier']} • High-load dish clearing & trolley flow",
            "Rotated station daily",
        ))

    # 4. Station 6: Clean Dish Supply -> Prefer remaining Dish Steward
    clean_steward = pick_next(lambda c: "Dish" in c["role_title"])
    if clean_steward:
        assignments.append((
            6,
            clean_steward["id"],
            f"Tier {clean_steward['experience_tier']} • Non-stop plate restocking for 1,300 guests",
            "50% AM / 50% PM",
        ))

    # 5. Station 4: Grand Terrace (200 seats) -> Prefer Terrace Specialist
    terrace_waiter = pick_next(lambda c: "Terrace" in c["role_title"])
    if terrace_waiter:
        assignments.append((
            4,
            terrace_waiter["id"],
            f"Tier {terrace_waiter['experience_tier']} • Fast outdoor table turnover (2.10x)",
            "Balanced monthly hours",
        ))

    # 6. Station 3: Large Hall (300 seats) -> Prefer Senior Hall Waiter / Hall Waiter
    lh_waiter_1 = pick_next(lambda c: "Hall Waiter" in c["role_title"])
    if lh_waiter_1:
        assignments.append((
            3,
            lh_waiter_1["id"],
            f"Tier {lh_waiter_1['experience_tier']} • High-speed table reset (2.26x turnover)",
            "Rotated from Shift 1",
        ))

    # 7. Station 2: Hot Block-Massa #2 -> Prefer Hot Line Specialist / dual_block_capable
    sixth_or_seventh = pick_next(lambda c: "Hot Line" in c["role_title"] or c["dual_block_capable"] == 1)
    if sixth_or_seventh:
        assignments.append((
            2,
            sixth_or_seventh["id"],
            f"Tier {sixth_or_seventh['experience_tier']} • Hot Block-Massa #2 + Large Hall peak assist",
            "50% Shift 1 / 50% Shift 2",
        ))

    # 8. 2nd Waiter on Station 3: Large Hall (300 seats peak)
    eighth_crew = pick_next()
    if eighth_crew:
        assignments.append((
            3,
            eighth_crew["id"],
            f"Tier {eighth_crew['experience_tier']} • Co-assigned to Large Hall (300 seats peak)",
            "Rotated from Shift 1",
        ))

    for st_id, staff_id, skill_note, rot_badge in assignments:
        cursor.execute(
            """
            INSERT INTO daily_roster (day_of_month, shift_code, station_id, staff_id, skill_note, rotation_badge)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (day, shift_code, st_id, staff_id, skill_note, rot_badge),
        )

    conn.commit()
    return assignments


def update_hall_flow(
    conn: sqlite3.Connection, zone_name: str, new_flow: int, day: int = 1, shift_code: str = "S1"
) -> dict:
    """Update 2h guest flow for a dining hall when its slider moves and recalculate KPIs."""
    clamped_flow = max(20, min(1200, int(new_flow)))
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE hall_metrics SET current_2h_flow = ? WHERE zone_name = ?;",
        (clamped_flow, zone_name),
    )
    conn.commit()
    return get_dashboard_state(conn, day, shift_code)


def book_tour_group_slot(
    conn: sqlite3.Connection,
    slot_id: int,
    group_size: int,
    operator_name: str = "Tour Operator #4",
    day: int = 1,
    shift_code: str = "S1",
) -> dict:
    """Interactive Popup Action for Tour Group Booking."""
    group_size = int(group_size)
    if group_size < 1 or group_size > 200:
        return {"error": "Group size must be between 1 and 200 guests."}

    cursor = conn.cursor()
    cursor.execute(
        "SELECT slot_id, time_window, zone_name, max_capacity, booked_guests FROM zone_time_slots WHERE slot_id = ?;",
        (slot_id,),
    )
    slot = cursor.fetchone()
    if not slot:
        return {"error": "Selected time slot not found."}

    free_seats = slot["max_capacity"] - slot["booked_guests"]
    if group_size > free_seats:
        return {
            "error": f"Overbooking prevented! Only {free_seats} seats free in {slot['zone_name']} at {slot['time_window']}."
        }

    cursor.execute(
        "UPDATE zone_time_slots SET booked_guests = booked_guests + ? WHERE slot_id = ?;",
        (group_size, slot_id),
    )

    cursor.execute(
        "UPDATE hall_metrics SET current_2h_flow = current_2h_flow + ? WHERE zone_name = ?;",
        (group_size, slot["zone_name"]),
    )

    zone_station_map = {"Large Hall": 3, "Grand Terrace": 4, "Small Hall": 5}
    st_id = zone_station_map.get(slot["zone_name"], 4)
    cursor.execute(
        """
        SELECT s.name FROM daily_roster r
        JOIN staff s ON r.staff_id = s.id
        WHERE r.day_of_month = ? AND r.shift_code = ? AND r.station_id = ?
        LIMIT 1;
        """,
        (day, shift_code, st_id),
    )
    waiter_row = cursor.fetchone()
    waiter_name = waiter_row["name"] if waiter_row else "Acting Shift Lead"

    cursor.execute(
        """
        INSERT INTO tour_groups (operator_name, group_size, time_window, assigned_zone, assigned_waiter_name)
        VALUES (?, ?, ?, ?, ?);
        """,
        (operator_name, group_size, slot["time_window"], slot["zone_name"], waiter_name),
    )
    conn.commit()

    state = get_dashboard_state(conn, day, shift_code)
    state["last_booking_alert"] = {
        "group_size": group_size,
        "time_window": slot["time_window"],
        "zone_name": slot["zone_name"],
        "waiter_name": waiter_name,
        "kitchen_alert": f"Hot Block-Massa #2 notified to prep +{group_size} portions.",
    }
    return state


def trigger_sick_leave_failover(
    conn: sqlite3.Connection, staff_id: int, day: int = 1, shift_code: str = "S1"
) -> dict:
    """Emergency Failover: Marks a staff member as SICK_LEAVE for today and re-allocates stations."""
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO staff_exceptions (staff_id, day_of_month, exception_type)
        VALUES (?, ?, 'SICK_LEAVE');
        """,
        (staff_id, day),
    )
    conn.commit()
    assign_daily_stations(conn, day, shift_code)

    cursor.execute(
        """
        SELECT name, weekly_hours FROM staff
        WHERE id NOT IN (
            SELECT staff_id FROM daily_roster WHERE day_of_month = ? AND shift_code = ?
        )
        AND id NOT IN (
            SELECT staff_id FROM staff_exceptions WHERE day_of_month = ? AND exception_type = 'SICK_LEAVE'
        )
        ORDER BY weekly_hours ASC LIMIT 1;
        """,
        (day, shift_code, day),
    )
    backup = cursor.fetchone()
    state = get_dashboard_state(conn, day, shift_code)
    state["failover_notice"] = (
        f"Emergency Failover Active: Acting Shift Lead switched to Dual Block-Massa (#1 & #2). "
        f"Standby backup with lowest hours: {backup['name']} ({backup['weekly_hours']}h)."
        if backup
        else "Emergency Failover Active: All 7 stations rebalanced."
    )
    return state


def reset_sick_leaves(conn: sqlite3.Connection, day: int = 1, shift_code: str = "S1") -> dict:
    """Restore full 8-person shift crew."""
    conn.execute("DELETE FROM staff_exceptions WHERE exception_type = 'SICK_LEAVE';")
    conn.commit()
    assign_daily_stations(conn, day, shift_code)
    return get_dashboard_state(conn, day, shift_code)


def get_dashboard_state(conn: sqlite3.Connection, day: int = 1, shift_code: str = "S1") -> dict:
    """Return full JSON state for the Figma UI dashboard."""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) AS cnt FROM daily_roster WHERE day_of_month = ? AND shift_code = ?;",
        (day, shift_code),
    )
    if cursor.fetchone()["cnt"] == 0:
        assign_daily_stations(conn, day, shift_code)

    # 1. Hall metrics & KPI totals
    cursor.execute("SELECT zone_name, seating_capacity, current_2h_flow FROM hall_metrics;")
    halls_raw = cursor.fetchall()
    total_seats = sum(r["seating_capacity"] for r in halls_raw)
    total_guests = sum(r["current_2h_flow"] for r in halls_raw)
    overall_turnover = round(total_guests / total_seats, 2) if total_seats else 0.0

    halls = []
    for r in halls_raw:
        meta = classify_hall_status(r["current_2h_flow"], r["seating_capacity"])
        halls.append({
            "zone_name": r["zone_name"],
            "seats": r["seating_capacity"],
            "flow_2h": r["current_2h_flow"],
            **meta,
        })

    # 2. Active station matrix (grouped into the exact 6 visual rows from Figma: 1-2 combined + 3..7)
    cursor.execute(
        """
        SELECT r.station_id, st.station_name, s.id AS staff_id, s.name AS staff_name,
               s.role_title, s.experience_tier, s.dual_block_capable,
               r.skill_note, r.rotation_badge
        FROM daily_roster r
        JOIN stations st ON r.station_id = st.station_id
        JOIN staff s ON r.staff_id = s.id
        WHERE r.day_of_month = ? AND r.shift_code = ?
        ORDER BY r.station_id ASC, s.experience_tier DESC;
        """,
        (day, shift_code),
    )
    roster_rows = [dict(r) for r in cursor.fetchall()]
    active_staff_ids = {r["staff_id"] for r in roster_rows}

    matrix_rows = []
    block_staff = [r for r in roster_rows if r["station_id"] in (1, 2)]
    if block_staff:
        staff_objs = [
            {
                "id": b["staff_id"],
                "name": b["staff_name"],
                "role": b["role_title"],
                "initials": "".join([p[0] for p in b["staff_name"].split()[:2]]).upper(),
            }
            for b in block_staff
        ]
        matrix_rows.append({
            "row_num": "1–2",
            "station_title": "Hot Block-Massa #1 & #2",
            "station_sub": "Dual hot buffet lines • Continuous tray replenish",
            "staff_list": staff_objs,
            "crew": staff_objs,
            "assigned_crew": ", ".join([s["name"] for s in staff_objs]),
            "skill_logic": block_staff[0]["skill_note"],
            "rotation_badge": block_staff[0]["rotation_badge"],
        })

    station_subtitles = {
        3: ("Large Hall", "Main buffet hall • 300 seats"),
        4: ("Grand Terrace", "Outdoor dining terrace • 200 seats"),
        5: ("Small Hall", "Quiet dining zone • 100 seats"),
        6: ("Clean Dish Supply", "Plate & cutlery restocking"),
        7: ("Dirty Dish Logistics", "High-load clearing & dishwashing feed"),
    }
    for st_id in (3, 4, 5, 6, 7):
        st_staff = [r for r in roster_rows if r["station_id"] == st_id]
        if st_staff:
            title, sub = station_subtitles[st_id]
            staff_objs = [
                {
                    "id": b["staff_id"],
                    "name": b["staff_name"],
                    "role": b["role_title"],
                    "initials": "".join([p[0] for p in b["staff_name"].split()[:2]]).upper(),
                }
                for b in st_staff
            ]
            matrix_rows.append({
                "row_num": str(st_id),
                "station_title": title,
                "station_sub": sub,
                "staff_list": staff_objs,
                "crew": staff_objs,
                "assigned_crew": ", ".join([s["name"] for s in staff_objs]),
                "skill_logic": st_staff[0]["skill_note"],
                "rotation_badge": st_staff[0]["rotation_badge"],
            })

    # 3. Time slots for Tour Group popup
    cursor.execute(
        """
        SELECT slot_id, time_window, zone_name, max_capacity, booked_guests,
               (max_capacity - booked_guests) AS free_seats
        FROM zone_time_slots
        ORDER BY time_window ASC, free_seats DESC;
        """
    )
    time_slots = [dict(r) for r in cursor.fetchall()]

    # 4. Recent booked tour groups
    cursor.execute(
        "SELECT group_id, operator_name, group_size, time_window, assigned_zone, assigned_waiter_name FROM tour_groups ORDER BY group_id DESC LIMIT 5;"
    )
    booked_groups = [dict(r) for r in cursor.fetchall()]

    return {
        "status": "ok",
        "kpi": {
            "total_seats": total_seats,
            "total_guests_2h": total_guests,
            "overall_turnover": overall_turnover,
            "active_crew_count": len(active_staff_ids),
            "monthly_pool_size": 16,
            "active_day": day,
            "active_shift": shift_code,
        },
        "halls": halls,
        "matrix_rows": matrix_rows,
        "time_slots": time_slots,
        "booked_groups": booked_groups,
        "briefing_text": format_crew_briefing(conn, day, shift_code),
    }


def format_crew_briefing(conn: sqlite3.Connection, day: int = 1, shift_code: str = "S1") -> str:
    """Button 4: One-click Telegram / WhatsApp crew briefing text."""
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(current_2h_flow) AS total_g FROM hall_metrics;")
    total_g = cursor.fetchone()["total_g"] or 1300

    cursor.execute(
        """
        SELECT st.station_name, GROUP_CONCAT(s.name, ', ') AS crew_names
        FROM daily_roster r
        JOIN stations st ON r.station_id = st.station_id
        JOIN staff s ON r.staff_id = s.id
        WHERE r.day_of_month = ? AND r.shift_code = ?
        GROUP BY r.station_id
        ORDER BY r.station_id ASC;
        """,
        (day, shift_code),
    )
    lines = [f"🌅 SUNRISE FLOW — SHIFT {shift_code} BRIEFING (Day {day} | Expected: {total_g} Guests / 2h)"]
    for r in cursor.fetchall():
        lines.append(f"• {r['station_name']}: {r['crew_names']}")
    lines.append("✅ Please check your stations 10 mins before opening!")
    return "\n".join(lines)


def export_director_csv(conn: sqlite3.Connection, day: int = 1, shift_code: str = "S1") -> str:
    """
    Button 3: Export Director CSV Report (including active shift stations AND 30-day monthly roster)
    & create automatic DB snapshot in backups/ and root folder.
    """
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)

    # Also ensure the standalone 30-day monthly schedule CSV is up to date
    export_monthly_schedule_csv(conn, total_days=30)

    state = get_dashboard_state(conn, day, shift_code)
    filename = f"Director_Shift_Report_Day{day}_{shift_code}.csv"
    export_path = os.path.join(EXPORTS_DIR, filename)
    root_report_path = os.path.join(BASE_DIR, filename)
    backup_path = os.path.join(BACKUPS_DIR, f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    rows_to_write = [
        ["SUNRISE RESORT — DIRECTOR SHIFT OPERATIONS REPORT"],
        ["Generated At", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["Shift", f"Day {day} ({shift_code})"],
        ["Total Seating Capacity", state["kpi"]["total_seats"]],
        ["2-Hour Guest Volume", state["kpi"]["total_guests_2h"]],
        ["Table Turnover Rate", f"{state['kpi']['overall_turnover']}x"],
        ["Active Shift Crew", f"{state['kpi']['active_crew_count']} / {state['kpi']['monthly_pool_size']}"],
        ["Management Time Saved", "36 minutes (-66.7% vs manual paper scheduling)"],
        [],
        ["Station #", "Position / Hall", "Assigned Crew", "Skill & Bottleneck Logic", "Rotation Status"],
    ]
    for r in state["matrix_rows"]:
        names = ", ".join([s["name"] for s in r["staff_list"]])
        rows_to_write.append([r["row_num"], r["station_title"], names, r["skill_logic"], r["rotation_badge"]])

    # Append 30-Day Monthly Schedule section at the bottom of the Director Report
    cursor = conn.cursor()
    cursor.execute("SELECT id, staff_code, name, role_title, monthly_s1_count, monthly_s2_count, days_off_taken FROM staff ORDER BY id ASC;")
    staff_rows = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT staff_id, day_of_month, shift_code FROM monthly_schedule;")
    sched_map = {(r["staff_id"], r["day_of_month"]): r["shift_code"] for r in cursor.fetchall()}

    rows_to_write.append([])
    rows_to_write.append(["30-DAY MONTHLY SCHEDULE MATRIX (14 S1 / 14 S2 / 2 OFF)"])
    rows_to_write.append(
        ["Staff Code", "Name", "Role"] + [f"D{d}" for d in range(1, 31)] + ["S1", "S2", "OFF"]
    )
    for s in staff_rows:
        sid = s["id"]
        rows_to_write.append(
            [s["staff_code"], s["name"], s["role_title"]]
            + [sched_map.get((sid, d), "OFF") for d in range(1, 31)]
            + [s["monthly_s1_count"], s["monthly_s2_count"], s["days_off_taken"]]
        )

    for path in (export_path, root_report_path, backup_path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows_to_write)

    return export_path


def get_active_context(conn: sqlite3.Connection) -> tuple:
    """Read current active_day and active_shift from system_state table."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT active_day, active_shift FROM system_state WHERE id = 1;")
        row = cur.fetchone()
        if row:
            return (row["active_day"], row["active_shift"])
    except sqlite3.OperationalError:
        pass
    return (1, "S1")


def switch_shift_context(conn: sqlite3.Connection, day: int, shift_code: str) -> dict:
    """Switch active dashboard view to a specific day (1..30) and shift ('S1' or 'S2')."""
    day = max(1, min(30, int(day)))
    shift_code = "S2" if shift_code == "S2" else "S1"
    cur = conn.cursor()
    cur.execute("UPDATE system_state SET active_day = ?, active_shift = ? WHERE id = 1;", (day, shift_code))
    conn.commit()
    return get_dashboard_state(conn, day=day, shift_code=shift_code)


def complete_shift_and_advance(conn: sqlite3.Connection, shift_hours: float = 6.0) -> dict:
    """Complete the current shift, add hours, and advance to next shift."""
    day, shift_code = get_active_context(conn)
    cur = conn.cursor()

    cur.execute(
        "SELECT DISTINCT staff_id FROM daily_roster WHERE day_of_month = ? AND shift_code = ?;",
        (day, shift_code),
    )
    worked_ids = [r["staff_id"] for r in cur.fetchall()]
    if not worked_ids:
        assign_daily_stations(conn, day=day, shift_code=shift_code)
        cur.execute(
            "SELECT DISTINCT staff_id FROM daily_roster WHERE day_of_month = ? AND shift_code = ?;",
            (day, shift_code),
        )
        worked_ids = [r["staff_id"] for r in cur.fetchall()]

    for sid in worked_ids:
        cur.execute(
            "UPDATE staff SET weekly_hours = ROUND(weekly_hours + ?, 1) WHERE id = ?;",
            (shift_hours, sid),
        )

    if shift_code == "S1":
        next_day, next_shift = day, "S2"
    else:
        next_day = 1 if day >= 30 else day + 1
        next_shift = "S1"

    cur.execute(
        "UPDATE system_state SET active_day = ?, active_shift = ? WHERE id = 1;",
        (next_day, next_shift),
    )
    conn.commit()

    assign_daily_stations(conn, day=next_day, shift_code=next_shift)
    state = get_dashboard_state(conn, day=next_day, shift_code=next_shift)
    state["shift_completed_notice"] = (
        f"Closed Day {day} ({shift_code}): +{shift_hours}h added to {len(worked_ids)} crew. "
        f"Now viewing Day {next_day} ({next_shift}) — station history & Dirty Dish rotation applied!"
    )
    return state
