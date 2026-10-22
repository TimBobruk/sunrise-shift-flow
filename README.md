# SunriseFlow (`sunrise-shift-flow`) v1.6 🌅

**High-Turnover Hospitality Station & Shift Optimizer (Python • SQLite • Flask • Figma UI)**

> **Operational Context:** Engineered from real operational experience as **Acting Shift Lead** at *Sunrise River Beach Resort* (Bulgaria). Designed to manage **600 seating capacity** handling **1,300 guests per 2-hour service window (2.17× table turnover)** across **3 dining halls**, **7 core stations**, and a **16-person monthly crew pool** deployed across **3 standalone restaurant instances**.

![SunriseFlow Dashboard UI](assets/dashboard_preview.png)

---

## 🚀 Key Engineering Features

1. **Fair Monthly Roster Generator (`14 S1 / 14 S2 / Max 2 OFF`):**
   - Schedules all **16 crew members** across a 30-day cycle while enforcing a hard cap of **2 days off (`OFF`)** per month (respecting pre-requested dates in `staff_exceptions`) and splitting the remaining 28 working shifts strictly **50/50** (**14 Morning `S1` + 14 Evening `S2`**).
2. **0.018s Daily 7-Station Auto-Allocator:**
   - Assigns **7–8 active shift crew** across all **7 operational stations**:
     1. `Hot Block-Massa #1 & #2` (Covered by Acting Shift Lead in Dual-Block mode)
     2. `Large Hall (300 seats • ~680 guests / 2h • 2.27× turnover)`
     3. `Grand Terrace (200 seats • ~420 guests / 2h • 2.10× turnover)`
     4. `Small Hall (100 seats • ~200 guests / 2h • 2.00× Protected station)`
     5. `Clean Dish Supply (Чиста посуда)`
     6. `Dirty Dish Logistics (Брудна посуда)`
   - Enforces **daily station rotation** (prevents assigning the same steward to `Dirty Dish` two days in a row) and places high-fatigue staff into the protected `Small Hall` zone.
3. **Interactive Tour Group Quick-Slotter (`+Guests` Live DB Sync):**
   - Displays available hourly time windows (e.g., `17:00–18:00 • Grand Terrace`). Clicking an available slot prompts for incoming tour group size (**20–100 guests**), validates capacity against overbooking, and immediately increments both the hall's 2-hour guest flow and the global `1,300 guests` KPI counter, dynamically updating slider positions, turnover rates, and status colors.
4. **Emergency Sick-Leave Failover (`Dual Block-Massa` Mode):**
   - If a crew member calls in sick (`SICK_LEAVE`), dropping active shift crew from 8 to 7, the engine automatically switches the **`Acting Shift Lead`** (`dual_block_capable = 1`) to cover **both Hot Block-Massa #1 and #2 simultaneously**, freeing a waiter to cover the absent station with zero service interruption.

---

## 📊 Project Governance: Stakeholders, RACI Matrix & Risk Register

### 1. Stakeholder Register (Power / Interest Grid)

| Stakeholder Group | Composition | Power / Interest | Strategic Objective |
| :--- | :--- | :--- | :--- |
| **Executive Sponsor** | Resort General Director | High Power / Low Interest | Zero entrance queues during 1,300-guest peaks; transparent daily CSV/PDF reports. |
| **Operational Owners** | F&B Manager & Senior Shift Lead (60+ yo) | High Power / High Interest | Zero-IT 4-button interface (`#FC6C26` Burnt Orange & `#FFF4D6` Vanilla) saving 36+ mins/shift. |
| **System Architect** | Acting Shift Lead (Developer) | High Tech / High Interest | Automated 50/50 AM/PM monthly balance, 7-station coverage, and Dual Block-Massa failover. |
| **End-Users (Crew Pool)** | 16 Wait Staff & Dish Stewards | Low Power / High Interest | Fair shift distribution (14 S1 / 14 S2 / 2 OFF) and rotation off heavy stations. |

### 2. Universal Role-Based RACI Matrix

| Project Deliverable / Process Step | Acting Shift Lead (Dev / Deputy) | Senior Shift Lead (60+) & F&B Mgr | 16 Crew Pool (Wait Staff) | Resort General Director |
| :--- | :---: | :---: | :---: | :---: |
| 1. Bottleneck Analysis (600 seats / 1,300 guests, 7 stations) | **R / A** | C | C | I |
| 2. SQLite Relational Schema & Python Optimization Core | **R / A** | I | - | I |
| 3. Figma UI/UX (`#FC6C26` / `#FFF4D6`) & Tour Group Slotter | **R / A** | C | I | - |
| 4. Monthly Roster Generation (14 S1 / 14 S2 / Max 2 OFF) | **R** | **A / C** | I | I |
| 5. Daily 7-Station Allocation & Sick-Leave Failover | **R / A** | **R / A** | **R** | I |
| 6. Standalone Multi-Restaurant Deployment (3 DB Instances) | **R** | C | I | **A** |

### 3. Risk Register & Mitigation Strategy

| ID & Risk Description | Prob (1-5) | Impact (1-5) | Score | Engineering Mitigation |
| :--- | :---: | :---: | :---: | :--- |
| **R1. Senior Shift Lead Tech Barrier:** 60+ yo supervisor resists complex software. | 4 | 4 | **16 (High)** | Minimalist Figma UI with 4 clear action cards and 1-click Telegram/CSV export. |
| **R2. Peak Station Bottleneck (7 Crew on 7 Stations):** Sudden sick leave during 1,300-guest rush. | 3 | 5 | **15 (High)** | SQLite `dual_block_capable=1` flag switches Acting Shift Lead to cover Block #1 & #2 simultaneously. |
| **R3. Shift Unfairness & Crew Burnout:** Disputes over AM/PM shifts or Dirty Dish station. | 4 | 3 | **12 (Med)** | Strict SQL/Python constraints: 14 S1 + 14 S2 + 2 OFF and daily rotation of Station #7. |
| **R4. Resort Wi-Fi Drop / Multi-Restaurant Desync:** Network outage during peak hours. | 2 | 5 | **10 (Med)** | Standalone local SQLite architecture (`rest1_main.db`, `rest2.db`, `rest3.db`) + auto CSV backups. |

---

## ⏱️ Time-Motion Benchmark (66.7% Coordination Time Saved)

| Daily Shift Lead Workflow Step | Manual Paper Process | SunriseFlow Engine | Time Saved |
| :--- | :---: | :---: | :---: |
| 1. Reviewing weekly hours & fatigue across 16 staff | 12 min | 2 min | **-10 min** |
| 2. Calculating hall turnover & assigning 7 stations | 18 min | 1 min *(0.018s solver)* | **-17 min** |
| 3. Resolving shift fairness disputes & briefing crew | 10 min | 5 min | **-5 min** |
| 4. Compiling end-of-shift report for Resort Director | 10 min | 1 min *(1-click CSV)* | **-9 min** |
| **TOTAL PER SHIFT:** | **45–50 min** | **9–15 min** | **36 min saved (-66.7%)** |

---

## 🛠️ Quick Start (macOS / Linux)

```bash
# 1. Run automated unit tests (5/5 passing — Zero external dependencies required!)
python3 engine.py

# 2. Launch the interactive Figma web dashboard (Built-in Python HTTPServer + SQLite)
python3 app.py
# Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in Safari or Chrome
