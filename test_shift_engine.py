"""
test_shift_engine.py — Automated Unit Test Suite (Compatible with both `python3 test_shift_engine.py` and `pytest`)
"""
import os
import tempfile
import unittest
from database import init_db
from engine import (
    generate_monthly_roster,
    assign_daily_stations,
    get_dashboard_state,
    update_hall_flow,
    book_tour_group_slot,
    trigger_sick_leave_failover,
    export_director_csv,
)


class TestSunriseShiftFlow(unittest.TestCase):
    def setUp(self):
        fd, self.temp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = init_db(self.temp_path)

    def tearDown(self):
        self.conn.close()
        if os.path.exists(self.temp_path):
            os.remove(self.temp_path)

    def test_1_monthly_roster_fairness(self):
        """Verify all 16 staff get exactly 14 S1, 14 S2, and 2 OFF days across 30 days."""
        res = generate_monthly_roster(self.conn, total_days=30)
        self.assertEqual(res["staff_scheduled"], 16)

        cur = self.conn.cursor()
        cur.execute("SELECT monthly_s1_count, monthly_s2_count, days_off_taken FROM staff;")
        for row in cur.fetchall():
            self.assertEqual(row["monthly_s1_count"], 14)
            self.assertEqual(row["monthly_s2_count"], 14)
            self.assertEqual(row["days_off_taken"], 2)

    def test_2_daily_stations_all_covered(self):
        """Verify all 7 core stations are covered without duplicate staff assignments."""
        generate_monthly_roster(self.conn)
        assignments = assign_daily_stations(self.conn, day=1, shift_code="S1")
        station_ids = {a[0] for a in assignments}
        staff_ids = [a[1] for a in assignments]

        self.assertEqual(station_ids, {1, 2, 3, 4, 5, 6, 7})
        self.assertEqual(len(staff_ids), len(set(staff_ids)))

    def test_3_tour_group_booking_updates_kpis_and_hall(self):
        """Verify clicking a free time slot adds +guests to both the hall flow and total KPI."""
        generate_monthly_roster(self.conn)
        assign_daily_stations(self.conn, day=1, shift_code="S1")
        initial_state = get_dashboard_state(self.conn, day=1, shift_code="S1")
        initial_total = initial_state["kpi"]["total_guests_2h"]

        # Book 60 guests into slot_id = 3 (17:00-18:00 Grand Terrace, 90 seats free)
        updated_state = book_tour_group_slot(self.conn, slot_id=3, group_size=60, day=1, shift_code="S1")
        self.assertNotIn("error", updated_state)
        self.assertEqual(updated_state["kpi"]["total_guests_2h"], initial_total + 60)

    def test_4_sick_leave_failover_keeps_7_stations_covered(self):
        """Verify marking a crew member SICK triggers failover while keeping all 7 stations covered."""
        generate_monthly_roster(self.conn)
        assign_daily_stations(self.conn, day=1, shift_code="S1")
        state_after = trigger_sick_leave_failover(self.conn, staff_id=2, day=1, shift_code="S1")

        self.assertGreaterEqual(state_after["kpi"]["active_crew_count"], 7)
        self.assertIn("failover_notice", state_after)

    def test_5_slider_update_and_csv_export(self):
        """Verify slider update recalculates turnover & CSV export generates file."""
        generate_monthly_roster(self.conn)
        assign_daily_stations(self.conn, day=1, shift_code="S1")
        state = update_hall_flow(self.conn, "Large Hall", 720, day=1, shift_code="S1")
        self.assertEqual(state["kpi"]["total_guests_2h"], 720 + 420 + 200)

        csv_path = export_director_csv(self.conn, day=1, shift_code="S1")
        self.assertTrue(os.path.exists(csv_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
