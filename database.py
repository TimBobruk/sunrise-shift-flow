"""
database.py — SQLite Database Connection & Initial Seeder
Part of Sunrise-Shift-Flow v1.6
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "rest1_main.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create a SQLite connection with Row factory and Foreign Keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Initialize all 8 tables from schema.sql and seed baseline resort data."""
    conn = get_connection(db_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())

    cursor = conn.cursor()

    # 1. Seed 16 Staff Members (Role-based: Acting Shift Lead has dual_block_capable = 1)
    staff_seed = [
        ("ST-01", "Acting Shift Lead", "Acting Shift Lead", 3, 1, 26.0),
        ("ST-02", "Georgi K.", "Hot Line Specialist", 3, 0, 24.5),
        ("ST-03", "Elena M.", "Senior Hall Waiter", 3, 0, 25.0),
        ("ST-04", "Ivan P.", "Hall Waiter", 2, 0, 22.0),
        ("ST-05", "Dimitar V.", "Terrace Specialist", 2, 0, 26.0),
        ("ST-06", "Anna L.", "Small Hall Waiter", 2, 0, 30.5),
        ("ST-07", "Nikolai K.", "Clean Dish Steward", 2, 0, 24.0),
        ("ST-08", "Stefan R.", "Dirty Dish Steward", 2, 0, 25.5),
        ("ST-09", "Maria S.", "Hot Line Specialist", 3, 1, 24.0),
        ("ST-10", "Petar D.", "Senior Hall Waiter", 3, 0, 23.5),
        ("ST-11", "Kaloyan T.", "Hall Waiter", 2, 0, 22.5),
        ("ST-12", "Viktoria T.", "Terrace Specialist", 2, 0, 25.0),
        ("ST-13", "Hristo B.", "Small Hall Waiter", 1, 0, 29.0),
        ("ST-14", "Desislava N.", "Clean Dish Steward", 2, 0, 24.0),
        ("ST-15", "Yordan M.", "Dirty Dish Steward", 2, 0, 26.5),
        ("ST-16", "Milena G.", "Relief Floater", 2, 0, 20.0),
    ]
    cursor.executemany(
        """
        INSERT INTO staff (staff_code, name, role_title, experience_tier, dual_block_capable, weekly_hours)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        staff_seed,
    )

    # 2. Seed 7 Core Operational Stations
    stations_seed = [
        (1, "Hot Block-Massa #1", "Food Line", 0, 3),
        (2, "Hot Block-Massa #2", "Food Line", 0, 3),
        (3, "Large Hall (Великий Зал — 300 seats)", "Large Hall", 300, 3),
        (4, "Grand Terrace (Тераса — 200 seats)", "Grand Terrace", 200, 2),
        (5, "Small Hall (Малий Зал — 100 seats)", "Small Hall", 100, 1),
        (6, "Clean Dish Supply (Чиста посуда)", "Dish Logistics", 0, 2),
        (7, "Dirty Dish Logistics (Брудна посуда)", "Dish Logistics", 0, 3),
    ]
    cursor.executemany(
        """
        INSERT INTO stations (station_id, station_name, zone_category, seating_capacity, difficulty_weight)
        VALUES (?, ?, ?, ?, ?);
        """,
        stations_seed,
    )

    # 3. Seed 3 Dining Halls (600 total seats -> 1,300 default 2h guest flow)
    halls_seed = [
        ("Large Hall", 300, 680),
        ("Grand Terrace", 200, 420),
        ("Small Hall", 100, 200),
    ]
    cursor.executemany(
        "INSERT INTO hall_metrics (zone_name, seating_capacity, current_2h_flow) VALUES (?, ?, ?);",
        halls_seed,
    )

    # 4. Seed Hourly Time Slots for Tour Group Quick-Booking (Popup)
    time_slots_seed = [
        ("12:30–13:30", "Large Hall", 300, 255),     # 45 seats free
        ("13:30–14:30", "Grand Terrace", 200, 110),  # 90 seats free
        ("17:00–18:00", "Grand Terrace", 200, 110),  # 90 seats free (Matches Figma preview!)
        ("17:00–18:00", "Large Hall", 300, 190),     # 110 seats free
        ("18:00–19:00", "Small Hall", 100, 45),      # 55 seats free
        ("19:00–20:00", "Large Hall", 300, 205),     # 95 seats free
    ]
    cursor.executemany(
        """
        INSERT INTO zone_time_slots (time_window, zone_name, max_capacity, booked_guests)
        VALUES (?, ?, ?, ?);
        """,
        time_slots_seed,
    )

    # 5. Seed sample pre-requested day off (Staff #4 requested Day 12 off)
    cursor.execute(
        "INSERT INTO staff_exceptions (staff_id, day_of_month, exception_type) VALUES (4, 12, 'REQUESTED_OFF');"
    )

    conn.commit()
    return conn
