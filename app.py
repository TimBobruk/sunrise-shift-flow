"""
app.py — Zero-Dependency Web Server & REST API (Built-in Python Standard Library)
Connects the Figma UI (templates/dashboard.html) to SQLite and engine.py.

Run locally on MacBook (Zero pip packages required!):
    python3 app.py
Then open http://127.0.0.1:5000 in Safari or Chrome.
"""
import os
import json
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
    """Support dashboard.html in either templates/dashboard.html or root directory."""
    candidate_1 = os.path.join(BASE_DIR, "templates", "dashboard.html")
    candidate_2 = os.path.join(BASE_DIR, "dashboard.html")
    if os.path.exists(candidate_1):
        return candidate_1
    if os.path.exists(candidate_2):
        return candidate_2
    return candidate_1


def ensure_initialized():
    """
    Initialize SQLite database automatically on launch, or repair if tables/rosters are empty.
    Also generates Monthly_Schedule_30_Days.csv and Day 1 station assignments immediately.
    """
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
        export_director_csv(conn, day=1, shift_code="S1")
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
        if parsed.path == "/" or parsed.path == "/index.html":
            tpl_path = resolve_template_path()
            with open(tpl_path, "r", encoding="utf-8") as f:
                html_bytes = f.read().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)

        elif parsed.path == "/api/state":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            state = get_dashboard_state(conn, day=day, shift_code=shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/export-csv":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            csv_path = export_director_csv(conn, day=day, shift_code=shift_code)
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
            export_director_csv(conn, day=day, shift_code=shift_code)
            state = get_dashboard_state(conn, day=day, shift_code=shift_code)
            state.update(roster_meta)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/assign-stations":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            assign_daily_stations(conn, day=day, shift_code=shift_code)
            export_director_csv(conn, day=day, shift_code=shift_code)
            state = get_dashboard_state(conn, day=day, shift_code=shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/switch-shift":
            conn = get_connection()
            cur_day, cur_shift = get_active_context(conn)
            target_day = int(data.get("day", cur_day))
            target_shift = data.get("shift_code", cur_shift)
            state = switch_shift_context(conn, day=target_day, shift_code=target_shift)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/complete-shift":
            conn = get_connection()
            state = complete_shift_and_advance(conn, shift_hours=6.0)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/update-slider":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            zone_name = data.get("zone_name", "Large Hall")
            new_flow = int(data.get("new_flow", 680))
            state = update_hall_flow(conn, zone_name, new_flow, day=day, shift_code=shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/book-tour-slot":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            slot_id = int(data.get("slot_id", 1))
            group_size = int(data.get("group_size", 60))
            result = book_tour_group_slot(conn, slot_id=slot_id, group_size=group_size, day=day, shift_code=shift_code)
            conn.close()
            status = 400 if "error" in result else 200
            self._send_json(result, status_code=status)

        elif parsed.path == "/api/mark-sick":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            staff_id = int(data.get("staff_id", 2))
            state = trigger_sick_leave_failover(conn, staff_id=staff_id, day=day, shift_code=shift_code)
            conn.close()
            self._send_json(state)

        elif parsed.path == "/api/reset-sick":
            conn = get_connection()
            day, shift_code = get_active_context(conn)
            state = reset_sick_leaves(conn, day=day, shift_code=shift_code)
            conn.close()
            self._send_json(state)

        else:
            self._send_json({"error": "Endpoint not found"}, 404)


if __name__ == "__main__":
    ensure_initialized()
    port = 5000
    server = HTTPServer(("127.0.0.1", port), SunriseRequestHandler)
    print(f"🌅 SunriseFlow v1.6 running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop the server.")
    server.serve_forever()
