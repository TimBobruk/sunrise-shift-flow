# SunriseFlow (v1.6)

Shift scheduling and station allocation tool built for **Sunrise River Beach Resort** (Bulgaria).

I wrote this project after working as an Acting Shift Lead managing buffet operations across 3 dining halls (**600 seats**, **~1,300 guests per 2-hour peak window**, **2.17x table turnover**). Previously, building monthly rosters and rebalancing 7 stations when someone called in sick was done on paper and took ~45 minutes per shift.

![SunriseFlow Dashboard UI](assets/dashboard_preview.png)

## What It Solves

1. **30-Day Monthly Roster (`14 S1 / 14 S2 / 2 OFF`):**
   - Generates a monthly schedule for all 16 staff members.
   - Enforces a strict cap of 2 days off (`OFF`) per person (respecting pre-requested dates in `staff_exceptions`) and splits the remaining 28 working shifts 50/50 between Morning (`S1`) and Evening (`S2`).
2. **Daily 7-Station Allocator:**
   - Assigns 7–8 active shift crew across all 7 stations (`Hot Block-Massa #1 & #2`, `Large Hall`, `Grand Terrace`, `Small Hall`, `Clean Dish Supply`, `Dirty Dish Logistics`).
   - Prevents assigning the same steward to `Dirty Dish Logistics` two days in a row and routes staff with high accumulated weekly hours to the lower-load `Small Hall` (100 seats).
3. **Tour Group Slotter & Capacity Check:**
   - Checks available seats per hourly window before booking incoming tour buses (20–100 guests) and updates 2-hour guest flow and turnover metrics in SQLite.
4. **Sick-Leave Failover (`Dual Block-Massa`):**
   - If a crew member calls in sick (`SICK_LEAVE`), the Acting Shift Lead (`dual_block_capable = 1`) covers both hot buffet lines (#1 and #2), freeing a waiter to cover the open hall station.

## Database Schema (9 Tables in SQLite)

Defined in `schema.sql` and initialized via `database.py`:
- `staff` — 16 crew records, experience tiers, `dual_block_capable` flag, and shift counters
- `stations` — 7 operational stations with capacity and difficulty weights
- `hall_metrics` — live seating capacity and 2-hour guest flow for the 3 dining halls
- `zone_time_slots` — hourly capacity buckets for tour group reservations
- `staff_exceptions` — `REQUESTED_OFF` and `SICK_LEAVE` records
- `monthly_schedule` — 30-day S1/S2/OFF matrix (480 rows per month)
- `daily_roster` — station-level assignments and rotation notes per shift
- `tour_groups` — logged group arrivals and assigned waiters
- `system_state` — active day and shift pointer (`S1` / `S2`)

## Project Governance (RACI & Risk Log)

### RACI Matrix

| Process Step | Acting Shift Lead (Dev) | Senior Shift Lead & F&B Mgr | Crew Pool (16) | Resort Director |
| :--- | :---: | :---: | :---: | :---: |
| 1. Bottleneck & capacity mapping (600 seats / 1,300 guests) | **R / A** | C | C | I |
| 2. SQLite schema (9 tables) & Python allocation engine | **R / A** | I | - | I |
| 3. Web UI & tour group slot validation | **R / A** | C | I | - |
| 4. Monthly schedule generation (14 S1 / 14 S2 / 2 OFF) | **R** | **A / C** | I | I |
| 5. Daily station rotation & sick-leave failover | **R / A** | **R / A** | **R** | I |
| 6. Daily CSV reporting (`exports/`) | **R** | C | I | **A** |

### Risk Register

| Risk | Prob (1-5) | Impact (1-5) | Score | Mitigation |
| :--- | :---: | :---: | :---: | :--- |
| **R1. Non-technical supervisor adoption** | 4 | 4 | **16** | Simple 4-action web dashboard + 1-click CSV export and text briefing. |
| **R2. Unplanned sick leave during peak window** | 3 | 5 | **15** | `dual_block_capable=1` failover merges Block-Massa #1 & #2 under Shift Lead. |
| **R3. Crew burnout on Dirty Dish station** | 4 | 3 | **12** | Daily rotation check queries yesterday's `daily_roster` before assigning Station #7. |
| **R4. Local Wi-Fi drop during service** | 2 | 5 | **10** | Zero-cloud local SQLite file (`rest1_main.db`) + automatic CSV backups. |

## Time Saved per Shift

| Workflow Step | Manual (Paper/Excel) | SunriseFlow | Saved |
| :--- | :---: | :---: | :---: |
| Checking weekly hours & fatigue across 16 staff | 12 min | 2 min | -10 min |
| Assigning 7 stations & checking yesterday's rotation | 18 min | 1 min | -17 min |
| Resolving shift balance questions & crew briefing | 10 min | 5 min | -5 min |
| Exporting daily summary for Resort Director | 10 min | 1 min | -9 min |
| **Total per shift** | **~45–50 min** | **~9–15 min** | **~36 min (-66.7%)** |

## Running Locally

Built with Python 3 standard library (`sqlite3`, `http.server`, `csv`, `unittest`) — no external pip packages required.

```bash
# Run unit tests (5 tests)
python test_shift_engine.py

# Start local web server on http://127.0.0.1:5000
python app.py
```
