# TrackEase — Full System Planning & Technical Blueprint

> AI-Assisted Railway Maintenance Block Planning System

## 1. Vision

TrackEase is a decision-support platform for railway maintenance block planning.

The system combines railway schedules, maintenance work, infrastructure, resources, constraints, and operational movement data to generate and compare maintenance plans.

The central idea is:

**Predict → Detect conflicts → Group compatible work → Optimize → Explain → Human approval → Monitor → Replan**

TrackEase should not present itself as an autonomous railway controller. It is a decision-support prototype where the human railway official remains responsible for final approval.

---

## 2. The Problem

Railway maintenance must be performed on infrastructure that may simultaneously be required for train operations.

A maintenance planner therefore has to balance:

- Safety and operational constraints
- Maintenance requirements
- Train schedules
- Track/block availability
- Maintenance windows
- Available teams and equipment
- Expected task duration
- Train disruption
- Changes in actual train movement

Manual planning can become difficult as the number of trains, tasks, resources, and constraints increases.

The project therefore asks:

> How can an intelligent system automatically assist an official in finding a feasible and efficient maintenance block plan?

---

## 3. What the Prototype Will Demonstrate

The SIH prototype should demonstrate one complete, understandable scenario rather than trying to model the entire Indian Railways network.

Example:

1. TrackEase receives several maintenance requests.
2. The system knows the affected locations and required resources.
3. Train schedules are loaded.
4. The timeline engine produces normalized train movements.
5. The system identifies trains that would conflict with proposed maintenance blocks.
6. ML predicts maintenance priority/duration where appropriate.
7. Compatible maintenance tasks are grouped.
8. OR-Tools generates feasible and optimized block plans.
9. TrackEase produces a recommended plan plus alternatives.
10. The dashboard explains the recommendation.
11. The official approves or rejects it.
12. A simulated live train movement changes the situation.
13. TrackEase detects the changed conflict and proposes a revised plan.

This gives the judges a clear end-to-end story.

---

## 4. Technology Architecture

### Frontend

**React + Vite**

Used for:

- Dashboard
- Tables
- Forms
- Plan comparison
- Alerts
- Charts
- Interactive map

**Tailwind CSS**

Used for consistent dashboard styling.

**Recharts**

Used for:

- Train delay charts
- Resource utilization
- Maintenance statistics
- Plan comparison

**Leaflet + OpenStreetMap**

Used for:

- Railway map visualization
- Train markers
- Station markers
- Maintenance locations
- Block visualization

### Backend

**Python + FastAPI**

Responsibilities:

- API endpoints
- Database access
- Validation results
- Plan generation requests
- ML inference
- Optimization requests
- Live/simulated train-state ingestion

### Database

**PostgreSQL**

Main structured storage.

**PostGIS**

Optional spatial extension for geographic queries.

### ML

**scikit-learn**

Initial models for:

- Maintenance priority
- Maintenance duration

Use more advanced models only when the dataset and evaluation justify them.

### Optimization

**Google OR-Tools**

Used for:

- Scheduling
- Resource constraints
- Time windows
- Conflict avoidance
- Objective optimization

---

## 5. Data Flow

```text
RAW RAILWAY DATA
       |
       v
Data validation
       |
       v
Timeline normalization
       |
       v
Processed railway data
       |
       +-------------------+
       |                   |
       v                   v
Maintenance data      Infrastructure data
       |                   |
       +---------+---------+
                 |
                 v
             Database
                 |
       +---------+---------+
       |                   |
       v                   v
     ML models       Rule/constraint engine
       |                   |
       +---------+---------+
                 |
                 v
           Task grouping
                 |
                 v
            Optimizer
                 |
                 v
        Multiple feasible plans
                 |
                 v
        Plan evaluation
                 |
                 v
    Recommendation + explanation
                 |
                 v
          Human approval
                 |
                 v
      Execution / monitoring
                 |
                 v
          Live state change
                 |
                 v
             Replanning
```

---

## 6. Data Layers

### Raw

Original files supplied by the railway dataset.

Never overwrite them.

### Processed

Cleaned and normalized data ready for application use.

Examples:

- normalized train timelines
- validated station data
- standardized maintenance records

### Synthetic

Data created for prototype features that are not available in the original dataset.

Examples:

- maintenance requests
- asset condition
- resource availability
- maintenance history

### Models

Saved ML models and metadata.

---

## 7. Train Timeline Engine

This is the immediate engineering task.

The raw schedule can contain overnight movements such as:

```text
Day 2 23:20
       |
Day 3 00:05
       |
Day 3 01:10
```

but the source may store the later stop with the earlier `day` value.

The timeline engine should:

1. Read the raw day/time.
2. Convert time to minutes.
3. Preserve the original day/time.
4. Walk through stops in sequence.
5. Detect when the next time would move backwards.
6. Roll the internal timestamp forward by 24 hours when appropriate.
7. Keep the normalized timeline separate from raw data.
8. Flag cases that cannot be explained by a normal overnight rollover.

This provides a trustworthy internal time representation for later planning.

---

## 8. Maintenance Data

The original train dataset does not provide every field required for maintenance planning.

We will therefore create a synthetic maintenance dataset after schedule validation.

Possible fields:

| Field | Example |
|---|---|
| maintenance_id | MNT_001 |
| asset_id | TRK_102 |
| asset_type | Track |
| station/location | MAU |
| task_type | Rail inspection |
| priority | High |
| estimated_duration_min | 90 |
| preferred_start | 02:00 |
| preferred_end | 05:00 |
| required_team | Track Team A |
| required_equipment | Trolley |
| deadline | 2026-09-10 |
| status | Pending |

Synthetic data must be clearly identified as synthetic.

---

## 9. Infrastructure Model

Potential entities:

### Station

- station_id
- code
- name
- latitude
- longitude

### Track segment

- track_id
- start_station
- end_station
- distance
- track type
- availability

### Asset

- asset_id
- asset_type
- location
- track_id
- condition
- last_maintenance

### Block

- block_id
- location/track
- start_time
- end_time
- status

---

## 10. Resource Model

Resources can include:

- Maintenance teams
- Equipment
- Machines
- Inspection teams
- Specialized staff

Example:

```text
Team T01
  Capacity: 1 task at a time
  Location: MAU
  Skill: Track maintenance
```

The optimizer can then prevent the same team from being assigned to overlapping jobs.

---

## 11. ML Design

ML should solve prediction problems, not the complete planning problem.

### Model 1 — Maintenance priority

Possible inputs:

- Asset type
- Asset age
- Previous maintenance interval
- Condition indicators
- Failure/inspection history
- Task type
- Operational importance

Output:

```text
Priority score
```

### Model 2 — Maintenance duration

Possible inputs:

- Task type
- Asset type
- Team type
- Historical duration
- Location
- Equipment

Output:

```text
Predicted duration
```

The optimizer then uses the predicted duration as an input.

---

## 12. Optimization Design

The optimizer receives:

- Train timelines
- Maintenance tasks
- Predicted duration
- Locations
- Resource availability
- Time windows
- Operational constraints

### Hard constraints

These must not be violated.

Examples:

- Maintenance cannot overlap an unavailable track.
- A resource cannot perform two overlapping tasks.
- Required maintenance windows must be respected.
- A block cannot conflict with protected train movement.
- Required resources must be available.

### Soft objectives

These are optimized.

Examples:

- Minimize train delay
- Minimize total block duration
- Minimize number of affected trains
- Maximize completed maintenance
- Minimize resource idle time

The exact objective weights should be configurable rather than hidden.

---

## 13. Alternative Plans

TrackEase should generate multiple feasible options when possible.

Example:

### Plan A — Balanced

- 7 minutes predicted train disruption
- Maintenance completed on time
- 0 resource conflicts

### Plan B — Train-first

- 0 predicted train disruption
- Maintenance delayed by 30 minutes

### Plan C — Maintenance-first

- Maintenance completed earliest
- 15 minutes predicted train disruption

The dashboard can explain the trade-offs.

---

## 14. Explainability

The system should answer:

> Why was this plan recommended?

Possible explanation:

- Required maintenance completed
- No hard operational constraints violated
- 3 fewer affected trains than Plan B
- Required team available
- Shorter total block duration
- Maintenance deadline satisfied

This is more useful than simply displaying an AI score.

---

## 15. GPS / Live Movement

GPS is a future operational input.

### Prototype stage

Simulate train position using:

- normalized schedule
- current simulated time
- route distance

Example:

```text
MAU ---------------- ARJ ---------------- BNRS
          🚆
         62%
```

### Real integration stage

If a suitable permitted live train-location API/source is available:

```text
GPS/API
   |
   v
FastAPI ingestion
   |
   v
Current train state
   |
   v
Conflict detector
   |
   v
Optimizer
```

The system should also handle:

- stale position
- missing location
- API outage
- inconsistent updates

The dashboard should clearly distinguish simulated and live data.

---

## 16. Dynamic Replanning

This is one of the strongest future features.

Example:

```text
Planned block: 02:00–04:00

Expected train:
01:50

Actual/simulated train:
02:20
```

TrackEase detects:

```text
NEW CONFLICT
```

Then:

```text
Current state
     |
     v
Conflict detection
     |
     v
Re-run optimization
     |
     v
Alternative plans
     |
     v
Operator approval
```

---

## 17. Dashboard Structure

### 1. Overview

Cards:

- Active trains
- Pending maintenance
- Active blocks
- Current conflicts
- Recommended plan

### 2. Live Map

Display:

- Trains
- Stations
- Maintenance sites
- Blocks
- Conflicts

### 3. Trains

Columns:

- Train number
- Current location
- Next station
- Scheduled time
- Estimated delay
- Status

### 4. Maintenance

Columns:

- Task
- Asset
- Location
- Priority
- Duration
- Required resources
- Status

### 5. Planning

Show:

- Recommended plan
- Alternative plans
- Affected trains
- Resources
- Block windows

### 6. Explanation

Show the reasons behind the recommendation.

### 7. Approval

Buttons:

- Approve
- Reject
- Generate alternative

### 8. Monitoring

Show:

- Current plan
- Actual/simulated movement
- New conflicts
- Replanning status

---

## 18. End-to-End Demonstration

A strong SIH demonstration can use:

### Scenario

Three maintenance requests:

- Track inspection at Location A
- Rail replacement at Location B
- Signal maintenance at Location C

Five trains operate through the region.

TrackEase:

1. Loads train schedules.
2. Normalizes overnight times.
3. Loads maintenance requests.
4. Predicts maintenance priority/duration.
5. Detects conflicts.
6. Groups compatible tasks.
7. Generates three plans.
8. Selects the best plan according to configured objectives.
9. Explains the recommendation.
10. Operator approves.
11. Simulated GPS moves a train later than expected.
12. A conflict appears.
13. TrackEase generates a revised plan.
14. Operator approves the revised plan.

This demonstrates the complete intelligence loop.

---

## 19. What We Should NOT Build Prematurely

Do not build these before the data foundation is ready:

- ML training
- Complex neural networks
- Real GPS integration
- Full database migration
- Large dashboard
- Advanced optimization
- Real railway control integration

The project should grow in dependency order.

---

## 20. Current Position

We are currently at:

```text
Project setup
     |
     v
Dataset understanding
     |
     v
Timeline validation V3
     |
     v
94 reported issues
     |
     v
Overnight rollover identified
     |
     v
>>> CURRENT: Timeline normalization <<<
```

The immediate objective is to produce a reliable normalized train timeline without modifying the raw dataset.

After that:

```text
Schedule validation
        ↓
Processed data
        ↓
Maintenance/infrastructure data
        ↓
Database
        ↓
Backend
        ↓
Baseline planner
        ↓
ML
        ↓
Optimization
        ↓
Alternatives + explanation
        ↓
GPS/live simulation
        ↓
Dashboard
        ↓
End-to-end SIH demo
```

---

## 21. Engineering Principles

1. Preserve raw data.
2. Validate before modeling.
3. Do not use ML for deterministic data errors.
4. Build the simplest working version first.
5. Add complexity only when required.
6. Keep ML and optimization separate.
7. Make constraints explicit.
8. Keep human approval in the loop.
9. Make recommendations explainable.
10. Test every major component independently.
11. Record meaningful project milestones in `PROJECT_WORKFLOW.md`.
12. Never silently modify source data.
13. Clearly label synthetic and simulated data.
14. Treat live data as potentially incomplete or stale.
15. Prefer reproducible processing and validation.

---

## 22. Final Target

TrackEase should ultimately behave like this:

```text
                 RAILWAY DATA
                      |
        +-------------+-------------+
        |             |             |
      Trains      Maintenance   Infrastructure
        |             |             |
        +-------------+-------------+
                      |
                DATA PROCESSING
                      |
              TIMELINE ENGINE
                      |
                  VALIDATION
                      |
                  DATABASE
                      |
             +--------+--------+
             |                 |
             v                 v
            ML          CONSTRAINT ENGINE
             |                 |
             +--------+--------+
                      |
                TASK GROUPING
                      |
                 OPTIMIZATION
                      |
          +-----------+-----------+
          |           |           |
        PLAN A      PLAN B      PLAN C
          |           |           |
          +-----------+-----------+
                      |
                PLAN EVALUATION
                      |
            RECOMMENDATION
                      |
                 EXPLANATION
                      |
              HUMAN APPROVAL
                 /       \
              YES         NO
               |           |
            EXECUTE     ALTERNATIVE
               |
             MONITOR
               |
          LIVE/SIMULATED
           TRAIN STATE
               |
          CONFLICT?
            /    \
          NO      YES
          |        |
       Continue   REPLAN
```
