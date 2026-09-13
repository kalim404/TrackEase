# TrackEase — Complete Project Workflow & Development Handoff

**Project:** TrackEase  
**SIH Problem Statement:** SIH26027 — AI-Powered Automatic Block Planning to Maximize Asset Availability for Train Operations on Indian Railways  
**Local Project Root:** `C:\SIH_PROJECT`  
**Workflow status date:** 2026-09-12  
**Current milestone:** Base Automatic Block Planner V1 completed successfully  
**Next core milestone:** Unified TMS + SMMS + TDMS maintenance layer

---

# 1. Why this document exists

This file is the cumulative development record for TrackEase.

It must answer five questions at any time:

1. **What have we built?**
2. **Why does each file exist?**
3. **What data flows into and out of each stage?**
4. **What assumptions / prototype limitations have we introduced?**
5. **What exactly should be built next without breaking the existing flow?**

The goal is that any SIH teammate can open this file, understand the project architecture, run the existing pipeline, and continue development without accidentally changing the core assumptions.

This file should be updated after every meaningful milestone.

---

# 2. TrackEase problem interpretation

TrackEase is not just a timetable gap finder and not just a predictive-maintenance model.

The problem is to coordinate railway maintenance blocks across departments while protecting train operations and maximizing infrastructure / asset availability.

The final TrackEase flow should represent:

```text
TMS (Engineering) ──────┐
SMMS (S&T) ─────────────┤
TDMS (Electrical) ──────┘
                         ↓
              Unified Maintenance Layer
                         ↓
              Maintenance Prioritization
                         ↓
          Multi-Department Coordination
                         ↓
        ┌────────────────┴────────────────┐
        ↓                                 ↓
 Train Timetable                 COA / Goods Forecast
        └────────────────┬────────────────┘
                         ↓
             Section / Corridor Availability
                         ↓
              Automatic Block Optimization
                         ↓
             Train-Operation Impact Check
                         ↓
              Weekly + Monthly Plans
                         ↓
                Explainable Recommendation
                         ↓
                 Human Approval / Reject
                         ↓
                    BDMS-style Output
```

## Core design principle

Do **not** build independent TMS, SMMS and TDMS dashboards.

The central TrackEase idea is:

```text
Many departmental maintenance requirements
                     ↓
            ONE planning problem
                     ↓
       ONE coordinated block plan
```

---

# 3. Prototype system boundaries

TrackEase currently uses public / supplied datasets and controlled prototype adapters.

We do **not** claim direct production access to:

- TMS
- SMMS
- TDMS
- COA
- BDMS

Where the source datasets do not provide a required real-world field, TrackEase must:

1. clearly label any controlled synthetic / deterministic prototype value,
2. never present it as observed railway truth,
3. keep the interface ready for a real upstream system later.

---

# 4. Development rules that must not be broken

## 4.1 Raw data is immutable

Never modify files in:

```text
data/raw/
```

All transformed datasets must be written into:

```text
data/processed/
```

Models must be written into:

```text
data/models/
```

## 4.2 Maintenance `train_id` does not equal timetable `train_number`

The maintenance datasets contain their own `train_id`.

There is no verified mapping between that field and the timetable's railway `train_number`.

Therefore:

```text
maintenance.train_id ≠ timetable.train_number
```

unless a genuine mapping is introduced later.

No fake direct join should be added.

## 4.3 Section assignments in prototype work orders are simulated

The maintenance dataset does not contain real station / section locations.

Therefore the current maintenance work-order builder assigns maintenance records to real TrackEase railway sections using deterministic prototype logic.

The resulting field is explicitly marked:

```text
location_assignment_type = PROTOTYPE_DETERMINISTIC
```

This is acceptable for demonstrating the optimizer, but it must not be described as a real maintenance-location observation.

## 4.4 AI is decision support, not railway authority

TrackEase recommends blocks.

Final system behavior should remain:

```text
Recommendation
      ↓
Impact explanation
      ↓
Human review
      ↓
Approve / Reject / Reschedule
```

The prototype must not be presented as autonomously granting an official railway block.

## 4.5 Do not overstate the ML baseline

The first Random Forest model was trained successfully but has poor recall and near-random ROC-AUC.

It stays in the project as:

```text
Maintenance Model V1 — Baseline Experiment
```

It must not be used as the sole maintenance decision-maker.

The core prototype should use an explainable priority engine plus operational constraints.

---

# 5. Python environment

The working TrackEase environment is:

```text
C:\SIH_PROJECT\venv\
```

Activate in PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& .\venv\Scripts\Activate.ps1
```

The prompt should show:

```text
(venv) PS C:\SIH_PROJECT>
```

A second environment named `.venv` has appeared during development.

Do not accidentally use:

```text
C:\SIH_PROJECT\.venv\
```

unless the project is intentionally migrated to it.

The working `venv` was confirmed to contain pandas and later received scikit-learn and joblib.

Scikit-learn installed version:

```text
1.7.2
```

Joblib installed version:

```text
1.6.0
```

Recommended `requirements.txt` entries include:

```text
pandas
scikit-learn==1.7.2
joblib==1.6.0
```

---

# 6. Current important project structure

```text
C:\SIH_PROJECT
│
├── app.py
├── optimizer.py
├── requirements.txt
├── setup_data.py
│
├── data
│   ├── raw
│   │   ├── trains.csv
│   │   ├── stations.csv
│   │   ├── stops.csv
│   │   ├── schedules.jsonl
│   │   └── maintenance
│   │       ├── indian_railway_failure_detection_maintenance_v2.csv
│   │       └── indian_railway_predictive_maintenance_100k.csv
│   │
│   ├── processed
│   │   ├── stops_normalized.csv
│   │   ├── timeline_normalization_report.txt
│   │   ├── maintenance_prepared.csv
│   │   ├── maintenance_preparation_report.txt
│   │   ├── block_maintenance_candidates.csv
│   │   ├── block_candidate_report.txt
│   │   ├── railway_sections.csv
│   │   ├── section_master_report.txt
│   │   ├── section_movements.csv
│   │   ├── section_movement_report.txt
│   │   ├── weekly_section_movements.csv
│   │   ├── weekly_section_movement_report.txt
│   │   ├── available_block_windows.csv
│   │   ├── block_window_report.txt
│   │   ├── maintenance_model_metrics.txt
│   │   ├── maintenance_work_orders.csv
│   │   ├── maintenance_work_order_report.txt
│   │   ├── planned_blocks.csv
│   │   ├── unscheduled_work_orders.csv
│   │   └── block_planning_report.txt
│   │
│   └── models
│       ├── maintenance_requirement_model.joblib
│       └── maintenance_model_metadata.joblib
│
├── docs
│   ├── PROJECT_WORKFLOW.md
│   └── TRACKEASE_FULL_PLANNING.md
│
└── src
    ├── data
    │   ├── inspect_dataset.py
    │   ├── profile_dataset.py
    │   ├── analyze_relationships.py
    │   ├── analyze_schedule.py
    │   ├── validate_schedule.py
    │   ├── investigate_halts.py
    │   ├── verify_halt_pattern.py
    │   ├── validate_timeline.py
    │   ├── validate_timeline_v2.py
    │   ├── validate_timeline_v3.py
    │   ├── investigate_timeline_issues.py
    │   ├── normalize_timeline.py
    │   ├── inspect_maintenance.py
    │   ├── prepare_maintenance_data.py
    │   ├── build_block_candidates.py
    │   ├── build_section_master.py
    │   ├── build_section_movements.py
    │   └── build_weekly_section_movements.py
    │
    ├── ml
    │   └── train_maintenance_model.py
    │
    └── planning
        ├── find_block_windows.py
        ├── build_maintenance_work_orders.py
        └── plan_blocks.py
```

Planned next file:

```text
src/data/build_unified_maintenance_layer.py
```

The code has been designed in discussion, but this workflow only marks it complete after its successful terminal execution is confirmed.

---

# 7. File-by-file explanation

This section explains what each important file does and why it exists.

## 7.1 Root files

### `app.py`

**Purpose:** Final application / dashboard entry point.

**Why it exists:**  
This will eventually expose TrackEase results to the SIH judges in an interactive UI.

It should later show:

- maintenance tasks,
- priority,
- sections,
- block recommendations,
- alternatives,
- train-operation impact,
- weekly plan,
- monthly plan,
- approval / rejection controls,
- BDMS-style export.

**Current status:** Existing file, but final dashboard integration has not yet been completed.

### `optimizer.py`

**Purpose:** Earlier / root-level optimization experimentation.

**Why it exists:**  
It belongs to the early prototype structure.

**Current status:** Keep it for reference. The active planning logic is now being developed under `src/planning/`.

Do not delete the root file until the new optimizer architecture is fully finalized.

### `setup_data.py`

**Purpose:** Earlier project setup / data utility.

**Current status:** Reference / setup history. Keep for now.

### `requirements.txt`

**Purpose:** Reproducible Python dependencies.

Must include the packages required by all TrackEase scripts.

---

# 8. Original railway data understanding

Before planning, the timetable dataset was inspected and profiled.

## Confirmed dataset scale

```text
Unique trains:   10,535
Unique stations: 8,591
Stop records:    209,256
```

Stops per train:

```text
Average: 19.86
Minimum: 2
Maximum: 122
```

All 10,535 trains have stop data.

No unmatched stop train numbers were found.

No unmatched station codes were found.

---

# 9. Historical / diagnostic railway scripts

These scripts were important for understanding the dataset and should generally be kept as development evidence.

### `src/data/inspect_dataset.py`

**Purpose:** Basic inspection of railway source datasets.

**Why it was created:** To discover real columns, identifiers, row counts and relationships before designing the pipeline.

**Status:** Historical / diagnostic.

### `src/data/profile_dataset.py`

**Purpose:** Dataset profiling and summary statistics.

**Why it was created:** To understand size, distributions and ranges before transformation.

**Status:** Historical / diagnostic.

### `src/data/analyze_relationships.py`

**Purpose:** Verify relationships among trains, stations and stops.

**Why it was created:** To make sure the timetable data could be connected safely through train numbers and station codes.

**Status:** Historical / diagnostic.

### `src/data/analyze_schedule.py`

**Purpose:** Analyse stop counts, journey-day distribution, timing format, halt duration, distance and example train journeys.

**Why it was created:** The planner needs correct timetable time interpretation.

Important finding:

```text
day = relative journey day
```

not weekday.

**Status:** Useful reference script.

### `src/data/validate_schedule.py`

**Purpose:** General schedule quality checks.

**Why it exists:** To catch malformed or inconsistent schedule records before planning.

**Status:** Reference / validation.

---

# 10. Halt investigation

### `src/data/investigate_halts.py`

**Purpose:** Investigate apparently abnormal halt durations.

**Why it was created:** Initial validation found suspicious cases where stored halt duration and simple clock difference seemed inconsistent.

Result:

```text
52 suspicious records initially examined
```

### `src/data/verify_halt_pattern.py`

**Purpose:** Classify the 52 suspicious halt records by overnight offset.

Result:

```text
44 → exact clock difference
6  → clock difference +1 day
2  → clock difference +2 days
0  → unexplained
```

**Decision:** No raw data was changed. The cases were explainable using overnight / multi-day timing.

---

# 11. Timeline validation history

### `src/data/validate_timeline.py`

Initial timeline validator. Historical.

### `src/data/validate_timeline_v2.py`

Second validator iteration. Historical.

### `src/data/validate_timeline_v3.py`

Final active validator from the investigation phase.

Result:

```text
Total trains checked: 10,535
Timeline issues: 94
```

Examples included train numbers such as 290, 391 and 902.

**Why it remains in the repository:** It documents the final timeline validation logic and the remaining unresolved cases.

**Decision:** The 94 issues were documented and deferred so they would not block the SIH prototype.

Do not create unnecessary `validate_timeline_v4/v5/...` scripts unless a genuine new requirement appears.

### `src/data/investigate_timeline_issues.py`

**Purpose:** Investigate timeline issues discovered by the validators.

**Status:** Historical / diagnostic.

---

# 12. Timeline normalization layer — COMPLETE

## `src/data/normalize_timeline.py`

**Input:**

```text
data/raw/stops.csv
```

**Outputs:**

```text
data/processed/stops_normalized.csv
data/processed/timeline_normalization_report.txt
```

**Why this file exists:** The planning engine should not repeatedly reason over raw schedule inconsistencies. This script creates the standardized timetable layer used by every later operational component.

Result:

```text
Original rows: 209,256
Final rows: 209,256
Duplicates removed: 0
Unique trains: 10,535
Unique stations: 8,591
Train timelines: 10,535
```

This output became the authoritative operational timetable layer for the prototype.

---

# 13. Maintenance dataset inspection — COMPLETE

## `src/data/inspect_maintenance.py`

**Purpose:** Inspect the available maintenance datasets without modifying them.

Two files were inspected:

```text
indian_railway_failure_detection_maintenance_v2.csv
indian_railway_predictive_maintenance_100k.csv
```

Decision: use `indian_railway_predictive_maintenance_100k.csv` as the primary TrackEase maintenance dataset because it contains broader infrastructure / condition information including ballast, signalling, track and traction-related features.

The other dataset remains as reference and must not be deleted.

---

# 14. Maintenance data preparation — COMPLETE

## `src/data/prepare_maintenance_data.py`

**Input:**

```text
data/raw/maintenance/indian_railway_predictive_maintenance_100k.csv
```

**Outputs:**

```text
data/processed/maintenance_prepared.csv
data/processed/maintenance_preparation_report.txt
```

**Why this file exists:** The source maintenance dataset contains duplicates, missing sensor values and labels that need to be standardized before downstream planning.

The script preserves raw data, removes exact duplicates, standardizes text, handles missing failure labels, median-fills selected numeric values, and adds TrackEase planning helper fields.

Result:

```text
Original rows: 100,300
Final rows: 100,000
Duplicates removed: 300
Original columns: 35
Final columns: 39
```

Added fields:

```text
maintenance_needed
severity_priority
infrastructure_warning
high_risk_flag
```

---

# 15. Block-maintenance candidate builder — COMPLETE

## `src/data/build_block_candidates.py`

**Input:** `maintenance_prepared.csv`

**Outputs:**

```text
block_maintenance_candidates.csv
block_candidate_report.txt
```

**Why this file exists:** Not every maintenance record needs an infrastructure block. Rolling-stock-only problems such as wheel defects, brake failures and bearing failures should not automatically become track-block jobs.

The script focuses on track defects, ballast problems, signal failures and signal warnings / faults.

It classifies responsibility as:

```text
Engineering
S&T
Engineering + S&T
```

Result:

```text
Candidates created: 28,633
```

Department distribution:

```text
Engineering:              20,267
S&T:                       4,569
Engineering + S&T:         3,797
```

Priority distribution:

```text
Critical:  1,086
High:      6,508
Medium:   15,544
Low:       5,495
```

Important decision: Electrical / TDMS tasks were not invented from these labels because the source dataset does not provide a defensible electrical-maintenance target. TDMS support will be added as a transparent prototype adapter later.

---

# 16. Railway section master — COMPLETE

## `src/data/build_section_master.py`

**Input:** `stops_normalized.csv`

**Outputs:**

```text
railway_sections.csv
section_master_report.txt
```

**Why this file exists:** A maintenance block occurs on a physical corridor / section. The planner therefore needs physical station-pair sections rather than only train-stop records.

Concept:

```text
ABC → XYZ
XYZ → ABC
```

represent the same physical section.

## Bug found and fixed

The first implementation grouped using station codes and station names. Small station-name variations caused duplicate physical sections.

Initial result:

```text
16,315 sections
```

The grouping was corrected so physical identity depends on station codes while names are descriptive only.

Final result:

```text
Adjacent movements: 198,721
Unique sections: 16,063
Same-station pairs: 0
```

This corrected implementation must be retained.

---

# 17. Section movement timeline — COMPLETE

## `src/data/build_section_movements.py`

**Inputs:**

```text
stops_normalized.csv
railway_sections.csv
```

**Outputs:**

```text
section_movements.csv
section_movement_report.txt
```

**Why this file exists:** TrackEase needs to know which train crosses which section at what time.

Result:

```text
Initial movements: 198,721
Usable movements: 198,458
Unique sections used: 15,967
Unique trains represented: 10,531
```

Quality checks:

```text
Same-station removed: 0
Unmapped sections: 0
Missing times: 142
Overnight adjusted: 0
Invalid durations: 121
```

Only 263 movements were excluded from the timed operational layer.

---

# 18. Schedule operating-day interpretation

The first records of `data/raw/schedules.jsonl` confirmed fields such as:

```text
"runs_days": "Tue"
"runs_days": "Thu,Sun"
```

Key interpretation:

```text
runs_days = weekday on which the train begins its journey
day       = relative journey day at each stop
```

Example:

```text
runs_days = Tue
stop day = 2
```

means that stop occurs on Wednesday.

This prevented TrackEase from incorrectly treating every Journey Day 1 as the same calendar day.

---

# 19. Weekly section movement builder — COMPLETE

## `src/data/build_weekly_section_movements.py`

**Inputs:**

```text
section_movements.csv
schedules.jsonl
```

**Outputs:**

```text
weekly_section_movements.csv
weekly_section_movement_report.txt
```

**Why this file exists:** Relative journey times cannot be used to find recurring weekly block opportunities until each train is aligned with its operating weekdays.

Result:

```text
Section movements loaded: 198,458
Schedule records loaded: 10,535
Train-day combinations: 58,216
```

Matching:

```text
Movement train numbers: 10,531
Matched train numbers: 10,531
Unmatched train numbers: 0
```

Final weekly layer:

```text
Weekly movement instances: 1,059,040
Unique sections: 15,967
Unique trains: 10,531
Week-boundary movements: 1,854
```

This is one of the core operational datasets of TrackEase.

---

# 20. Available maintenance block windows — COMPLETE

## `src/planning/find_block_windows.py`

**Input:** `weekly_section_movements.csv`

**Outputs:**

```text
available_block_windows.csv
block_window_report.txt
```

**Why this file exists:** The planner needs train-free intervals rather than raw train movement events.

The script groups section occupancy, applies a prototype 10-minute safety buffer, merges overlapping occupied periods, finds free gaps and keeps gaps of at least 30 minutes.

Result:

```text
Weekly movements: 1,059,040
Sections analysed: 15,967
Available windows: 467,769
Sections with windows: 15,965
Average duration: 275.64 minutes
Longest window: 10,060 minutes
```

Window classes:

```text
Short:  197,433
Medium: 106,496
Long:   163,840
```

Important note: a 10,060-minute window is nearly an entire week and can occur on extremely sparse sections. The final optimizer must not blindly prefer the longest window; it must consider traffic density, job duration, goods-train forecast and operational impact.

---

# 21. Maintenance ML baseline — COMPLETE

## `src/ml/train_maintenance_model.py`

**Input:** `maintenance_prepared.csv`

**Outputs:**

```text
data/models/maintenance_requirement_model.joblib
data/models/maintenance_model_metadata.joblib
data/processed/maintenance_model_metrics.txt
```

**Why this file exists:** The SIH problem asks for AI-assisted prioritization. This first experiment checks whether maintenance requirement can be learned from condition, sensor and operational variables.

Algorithm:

```text
RandomForestClassifier
```

Training split:

```text
Training rows: 80,000
Testing rows: 20,000
```

Target distribution:

```text
0 = 79,804
1 = 20,196
```

Target-derived / leakage-prone fields were deliberately excluded.

## Model V1 result

```text
Accuracy:  0.8180
Precision: 0.9694
Recall:    0.1020
F1 Score:  0.1846
ROC-AUC:   0.5421
```

Confusion matrix:

```text
[[15948    13]
 [ 3627   412]]
```

Interpretation: the model has high precision when it predicts maintenance, but misses most actual positive cases. It is not strong enough to be the core decision-maker.

It remains a baseline AI component.

---

# 22. Risk-score sanity check — COMPLETE

The source `risk_score` was checked against `maintenance_required`.

Result:

```text
maintenance_required = 0
mean risk ≈ 57.7159

maintenance_required = 1
mean risk ≈ 58.0187

Correlation ≈ 0.0158
```

Interpretation: source `risk_score` has essentially no useful linear relationship with the maintenance-required label in this dataset.

Decision: do not make it the core TrackEase decision signal.

---

# 23. Prototype maintenance work-order builder — COMPLETE

## `src/planning/build_maintenance_work_orders.py`

**Inputs:**

```text
block_maintenance_candidates.csv
railway_sections.csv
available_block_windows.csv
```

**Outputs:**

```text
maintenance_work_orders.csv
maintenance_work_order_report.txt
```

**Why this file exists:** The planner cannot schedule a generic maintenance candidate. It needs a practical work order containing section, department, task type, priority and required duration.

Because the source dataset has no genuine location or duration target, the script adds two transparent prototype mechanisms:

1. deterministic section assignment,
2. rule-based maintenance durations.

The location assignment is labelled:

```text
PROTOTYPE_DETERMINISTIC
```

Result:

```text
Maintenance candidates: 28,633
Railway sections: 16,063
Available windows: 467,769
Eligible planning sections: 15,485
Work orders created: 1,000
Sections assigned: 969
```

Priority distribution:

```text
Critical: 200
High:     300
Medium:   350
Low:      150
```

Department distribution:

```text
Engineering:              642
S&T:                      197
Engineering + S&T:        161
```

---

# 24. Automatic Block Planner V1 — COMPLETE

## `src/planning/plan_blocks.py`

**Inputs:**

```text
maintenance_work_orders.csv
available_block_windows.csv
```

**Outputs:**

```text
planned_blocks.csv
unscheduled_work_orders.csv
block_planning_report.txt
```

**Why this file exists:** This is the first actual automatic block-planning engine in TrackEase.

It converts maintenance requirement + duration + section + train-free window into a recommended maintenance block.

## Planner V1 strategy

1. Prioritize `Critical → High → Medium → Low`.
2. Only use windows on the same physical section.
3. Require the window to be long enough for the job.
4. Prefer the smallest feasible remaining window to preserve larger windows.
5. Reserve allocated maintenance time so later jobs do not overlap that reserved period.

## V1 result

```text
Work orders: 1,000
Scheduled: 980
Unscheduled: 20
Success rate: 98.00%
Sections used: 949
Maintenance minutes scheduled: 134,805
```

Scheduled priorities:

```text
Critical: 194 / 200
High:     294 / 300
Medium:   347 / 350
Low:      145 / 150
```

This is a major milestone: TrackEase now has a working end-to-end Base Planner V1.

Important interpretation: `98%` is scheduling feasibility for these prototype work orders. It is not predictive accuracy and it is not a claim of production railway correctness.

---

# 25. Current end-to-end pipeline

```text
RAW TIMETABLE
    ↓
normalize_timeline.py
    ↓
stops_normalized.csv
    ↓
build_section_master.py
    ↓
railway_sections.csv
    ↓
build_section_movements.py
    ↓
section_movements.csv
    ↓
build_weekly_section_movements.py
    ↓
weekly_section_movements.csv
    ↓
find_block_windows.py
    ↓
available_block_windows.csv
                     │
                     │
RAW MAINTENANCE      │
    ↓                │
prepare_maintenance_data.py
    ↓
maintenance_prepared.csv
    ↓
build_block_candidates.py
    ↓
block_maintenance_candidates.csv
    ↓
build_maintenance_work_orders.py
    ↓
maintenance_work_orders.csv
                     │
                     └─────────────┐
                                   ↓
                            plan_blocks.py
                                   ↓
                           planned_blocks.csv
                                   ↓
                           980 planned blocks
```

Parallel experimental ML branch:

```text
maintenance_prepared.csv
        ↓
train_maintenance_model.py
        ↓
maintenance_requirement_model.joblib
        ↓
Baseline ML Model V1
```

---

# 26. What has NOT been implemented yet

These are part of the agreed master architecture and must not be forgotten.

## 26.1 Unified TMS + SMMS + TDMS maintenance schema

**Status:** NEXT.

Planned file:

```text
src/data/build_unified_maintenance_layer.py
```

Goal:

```text
TMS  → Engineering
SMMS → S&T
TDMS → Electrical / Traction
```

into one common dataset such as:

```text
unified_maintenance_tasks.csv
```

The common schema should contain identifiers, source system, department, asset category, task type, section, priority, required duration, status, coordination group, planning horizon and integration metadata.

Current Engineering and S&T work orders can seed this layer.

## 26.2 TDMS / Electrical task adapter

**Status:** Missing and required.

Current maintenance data does not provide reliable TDMS maintenance tasks.

We should create a transparent controlled prototype adapter for tasks such as OHE inspection, traction power maintenance, electrical isolation and power-equipment defects.

Every such record must be labelled as prototype input unless real TDMS data is supplied.

The point is to demonstrate three-department coordination, not to fabricate source truth.

## 26.3 Explainable maintenance priority engine

**Status:** Not yet implemented.

This should become more important than Model V1.

Suggested score components:

```text
criticality
+ urgency / overdue condition
+ asset condition
+ operational section importance
+ coordination opportunity
+ optional ML supporting signal
```

The engine should explain why a task received its priority.

## 26.4 Multi-department coordination / task bundling

**Status:** Not implemented.

This is one of the most important remaining SIH features.

If the same section has Engineering, S&T and Electrical needs, TrackEase should detect whether they can share a coordinated block.

Future output should include:

```text
coordination_group
departments_involved
individual_duration_sum
joint_required_duration
minutes_saved
```

This is how TrackEase can demonstrate reduced infrastructure downtime.

## 26.5 COA / goods-train forecast layer

**Status:** Missing.

Current block windows use the scheduled weekly timetable.

The final architecture must also include a goods-train forecast / Control Office input.

Prototype schema can include:

```text
forecast_id
section_id
forecast_day
expected_start_minute
expected_end_minute
confidence
train_type = GOODS
source = PROTOTYPE_COA_FORECAST
```

Then:

```text
Scheduled timetable
        +
Goods-train forecast
        ↓
Expected occupancy
        ↓
Adjusted feasible maintenance windows
```

## 26.6 Train-operation impact scoring

**Status:** Not explicitly implemented.

Current windows are train-free, but the final recommendation should explicitly score operational impact using traffic density, nearby movements, section importance, duration, forecast risk and coordination benefit.

## 26.7 Weekly planning output

**Status:** Operational foundation complete; final weekly plan view not yet built.

The weekly section timeline already exists. The final planner should output planned blocks grouped Monday through Sunday.

## 26.8 Monthly planning output

**Status:** Required and not yet implemented.

TrackEase must support both:

```text
planning_horizon = WEEKLY
```

and:

```text
planning_horizon = MONTHLY
```

Monthly planning should distribute tasks across roughly four weeks according to criticality, urgency, due / overdue state, available windows, coordination and section traffic.

## 26.9 Optimizer V2

**Status:** Base heuristic V1 complete; V2 pending.

V2 should maximize high-value maintenance and coordination while minimizing downtime, operational impact and urgent unscheduled work.

Do not replace V1 until V2 can be measured against it.

## 26.10 Recommendation explanation + human approval

**Status:** Pending.

Every planned block should answer:

```text
Why this task?
Why this section?
Why this time?
Why this duration?
Why not the alternative?
Which departments are coordinated?
What operational impact was avoided?
```

Future controls:

```text
Approve
Reject
Reschedule
Show Alternative
```

## 26.11 Dashboard integration

**Status:** Pending.

The dashboard should consume backend results rather than recreate pipeline logic in the UI.

Suggested views:

- Overview
- Maintenance Tasks
- Block Recommendations
- Weekly Plan
- Monthly Plan
- Human Approval
- Data Integration status

Do not create separate dashboards for TMS, SMMS and TDMS.

## 26.12 BDMS-style export

**Status:** Pending.

Final approved recommendations should be exportable through a BDMS-compatible / request-like schema.

Do not claim production BDMS access.

## 26.13 Track image defect detection

**Status:** Explicitly postponed.

The uploaded track-fault notebook can later provide another maintenance source:

```text
Track Image
     ↓
Defect Detection
     ↓
Maintenance Task
     ↓
Unified Maintenance Layer
```

It is optional until the core SIH26027 architecture is complete.

---

# 27. Recommended next implementation order

Do not skip directly to dashboard.

```text
COMPLETED
─────────────────────────────────────────────
Railway dataset understanding                 ✅
Schedule analysis                             ✅
Halt investigation                            ✅
Timeline validation                           ✅
Timeline normalization                        ✅
Maintenance dataset inspection                ✅
Maintenance preparation                       ✅
Block maintenance candidates                  ✅
Railway section master                        ✅
Section movements                             ✅
Weekly operating alignment                    ✅
Train-free block windows                      ✅
Maintenance ML Baseline V1                    ✅
Prototype maintenance work orders             ✅
Automatic Block Planner V1                    ✅

NEXT CORE IMPLEMENTATION
─────────────────────────────────────────────
1. Unified TMS + SMMS + TDMS schema            ← NEXT
2. TDMS / Electrical prototype adapter
3. Explainable maintenance priority engine
4. Multi-department coordination / bundling
5. COA goods-train forecast adapter
6. Adjusted section occupancy / feasible windows
7. Train-operation impact scoring
8. Weekly optimized plan
9. Monthly optimized plan
10. Baseline-vs-optimized evaluation metrics
11. Recommendation explanations
12. Human approval / reject / reschedule flow
13. Dashboard / app.py integration
14. BDMS-style export

OPTIONAL AFTER CORE
─────────────────────────────────────────────
Track image defect detection
GPS / live train location
Advanced ML
External production integrations
```

---

# 28. Metrics that should eventually be shown to SIH judges

Do not show only model accuracy.

More valuable TrackEase metrics include:

```text
Number of maintenance requirements
Critical tasks scheduled
High-priority tasks scheduled
Unscheduled urgent tasks

Available block windows
Blocks selected

Departments coordinated
Separate blocks avoided
Maintenance downtime before coordination
Maintenance downtime after coordination
Estimated minutes saved

Train conflicts avoided
Operational impact score
Sections affected

Weekly plan completion
Monthly plan completion

Asset availability improvement estimate
```

---

# 29. Baseline metrics currently available

Current Base Planner V1 provides:

```text
1,000 maintenance work orders
980 successfully scheduled
20 unscheduled
98.00% scheduling feasibility
949 sections used
134,805 maintenance minutes scheduled
```

These values are useful as the baseline planning result.

Later Optimizer V2 should be compared against this baseline.

---

# 30. Active vs historical files

Do not delete historical analysis scripts yet.

## Active pipeline

```text
normalize_timeline.py
prepare_maintenance_data.py
build_block_candidates.py
build_section_master.py
build_section_movements.py
build_weekly_section_movements.py
train_maintenance_model.py
find_block_windows.py
build_maintenance_work_orders.py
plan_blocks.py
```

## Historical / diagnostic / reference

```text
inspect_dataset.py
profile_dataset.py
analyze_relationships.py
analyze_schedule.py
validate_schedule.py
investigate_halts.py
verify_halt_pattern.py
validate_timeline.py
validate_timeline_v2.py
validate_timeline_v3.py
investigate_timeline_issues.py
inspect_maintenance.py
```

Historical files are useful because they document how the project reached its current data assumptions.

---

# 31. Full current pipeline run order

Activate the correct environment first:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
& .\venv\Scripts\Activate.ps1
```

Then rebuild current outputs in this order:

```powershell
python src\data\normalize_timeline.py
python src\data\prepare_maintenance_data.py
python src\data\build_block_candidates.py
python src\data\build_section_master.py
python src\data\build_section_movements.py
python src\data\build_weekly_section_movements.py
python src\planning\find_block_windows.py
python src\ml\train_maintenance_model.py
python src\planning\build_maintenance_work_orders.py
python src\planning\plan_blocks.py
```

The ML model does not need to be retrained every time the planner runs.

Once saved, the `.joblib` model can be loaded for inference.

---

# 32. Real-time / near-real-time future behavior

The backend can later support a real-time simulation without retraining the model for every event.

Future runtime flow:

```text
New TMS / SMMS / TDMS event
            ↓
Unified maintenance adapter
            ↓
Priority calculation / optional ML inference
            ↓
Affected section identified
            ↓
Current timetable + COA forecast
            ↓
Recalculate affected section windows
            ↓
Check existing planned blocks
            ↓
Generate candidate block
            ↓
Operational impact score
            ↓
Recommendation
            ↓
Human approval
```

Training is offline; new records normally use model inference rather than retraining.

---

# 33. Final prototype demo vision

A strong SIH demo should eventually show:

```text
TMS Engineering requirement
+ SMMS signalling requirement
+ TDMS electrical requirement
             ↓
Same section detected
             ↓
Joint maintenance opportunity
             ↓
Timetable + COA forecast checked
             ↓
Multiple candidate windows
             ↓
Operational impact comparison
             ↓
Recommended joint block
             ↓
Estimated downtime saved
             ↓
Human approval
             ↓
Weekly / Monthly Plan
```

Example final recommendation:

```text
Section: SEC-004281
Departments: Engineering + S&T + Electrical
Priority: Critical
Required coordinated block: 150 min
Recommended: Tue 23:40–02:10
Reason:
- enough uninterrupted time
- lower traffic period
- critical infrastructure requirement
- three departmental tasks coordinated
- lower operational impact than alternate window
```

---

# 34. Exact next action

The Base Automatic Block Planner V1 is complete.

The exact next development task is:

```text
src/data/build_unified_maintenance_layer.py
```

Its purpose is to create one common task schema representing:

```text
TMS
SMMS
TDMS
```

Current Engineering and S&T tasks will be mapped first.

Then a transparent TDMS / Electrical prototype adapter will be added.

After that:

```text
Priority Engine
        ↓
Multi-Department Coordinator
        ↓
COA Forecast Layer
        ↓
Impact-Aware Weekly / Monthly Optimizer
```

Do not jump directly to final UI before these backend requirements exist.

---

# 35. Milestone summary

As of this update, TrackEase has achieved:

```text
✅ Clean train timetable layer
✅ 10,535 train dataset understood
✅ 8,591 station dataset understood
✅ 209,256 stop records normalized
✅ 16,063 physical railway sections
✅ 198,458 usable timed section movements
✅ 1,059,040 weekly section movements
✅ 467,769 available train-free windows
✅ 100,000 cleaned maintenance records
✅ 28,633 infrastructure block candidates
✅ Maintenance ML Baseline V1
✅ 1,000 prototype maintenance work orders
✅ Base Automatic Block Planner V1
✅ 980 / 1,000 work orders automatically scheduled
```

The project has moved beyond simple data preparation.

TrackEase now has a working planning backbone.

The remaining work is about making that backbone match the full SIH26027 operational architecture:

```text
unified departments
+ coordination
+ goods forecast
+ impact
+ weekly/monthly optimization
+ explanation
+ human approval
+ dashboard
```

---

**End of current workflow handoff.**
