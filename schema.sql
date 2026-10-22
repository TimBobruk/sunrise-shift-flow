DROP TABLE IF EXISTS system_state;
-- Sunrise-Shift-Flow v1.6 Relational Database Schema (SQLite)
-- Standalone Multi-Restaurant Architecture (600 Seats / 1,300 Guests per 2h Service)

DROP TABLE IF EXISTS tour_groups;
DROP TABLE IF EXISTS daily_roster;
DROP TABLE IF EXISTS staff_exceptions;
DROP TABLE IF EXISTS monthly_schedule;
DROP TABLE IF EXISTS zone_time_slots;
DROP TABLE IF EXISTS hall_metrics;
DROP TABLE IF EXISTS stations;
DROP TABLE IF EXISTS staff;

CREATE TABLE staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_code TEXT NOT NULL,
    name TEXT NOT NULL,
    role_title TEXT NOT NULL,           -- 'Acting Shift Lead', 'Wait Staff', 'Dish Steward'
    experience_tier INTEGER NOT NULL CHECK(experience_tier BETWEEN 1 AND 3),
    dual_block_capable INTEGER DEFAULT 0 CHECK(dual_block_capable IN (0, 1)),
    weekly_hours REAL DEFAULT 0.0,
    monthly_s1_count INTEGER DEFAULT 0,
    monthly_s2_count INTEGER DEFAULT 0,
    days_off_taken INTEGER DEFAULT 0 CHECK(days_off_taken <= 2)
);

CREATE TABLE stations (
    station_id INTEGER PRIMARY KEY,
    station_name TEXT NOT NULL,
    zone_category TEXT NOT NULL,
    seating_capacity INTEGER DEFAULT 0,
    difficulty_weight INTEGER NOT NULL CHECK(difficulty_weight BETWEEN 1 AND 3)
);

CREATE TABLE hall_metrics (
    zone_name TEXT PRIMARY KEY,
    seating_capacity INTEGER NOT NULL,
    current_2h_flow INTEGER NOT NULL
);

CREATE TABLE zone_time_slots (
    slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    time_window TEXT NOT NULL,          -- e.g. '17:00-18:00'
    zone_name TEXT NOT NULL,            -- 'Large Hall', 'Grand Terrace', 'Small Hall'
    max_capacity INTEGER NOT NULL,      -- 300, 200, 100
    booked_guests INTEGER DEFAULT 0 CHECK(booked_guests >= 0)
);

CREATE TABLE staff_exceptions (
    exception_id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL,
    day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 1 AND 30),
    exception_type TEXT NOT NULL CHECK(exception_type IN ('REQUESTED_OFF', 'SICK_LEAVE')),
    FOREIGN KEY (staff_id) REFERENCES staff(id)
);

CREATE TABLE monthly_schedule (
    schedule_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 1 AND 30),
    staff_id INTEGER NOT NULL,
    shift_code TEXT NOT NULL CHECK(shift_code IN ('S1', 'S2', 'OFF')),
    FOREIGN KEY (staff_id) REFERENCES staff(id)
);

CREATE TABLE daily_roster (
    roster_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_month INTEGER NOT NULL,
    shift_code TEXT NOT NULL,
    station_id INTEGER NOT NULL,
    staff_id INTEGER NOT NULL,
    skill_note TEXT,
    rotation_badge TEXT,
    FOREIGN KEY (station_id) REFERENCES stations(station_id),
    FOREIGN KEY (staff_id) REFERENCES staff(id)
);

CREATE TABLE tour_groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_name TEXT NOT NULL,
    group_size INTEGER NOT NULL CHECK(group_size BETWEEN 1 AND 200),
    time_window TEXT NOT NULL,
    assigned_zone TEXT NOT NULL,
    assigned_waiter_name TEXT NOT NULL
);

CREATE TABLE system_state (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    active_day INTEGER NOT NULL DEFAULT 1,
    active_shift TEXT NOT NULL DEFAULT 'S1'
);
INSERT INTO system_state (id, active_day, active_shift) VALUES (1, 1, 'S1');