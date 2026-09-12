"""
TrackEase - Automatic Block Planner

Purpose:
    Automatically assign TrackEase maintenance work orders to feasible
    train-free railway block windows.

Inputs:
    data/processed/maintenance_work_orders.csv
    data/processed/available_block_windows.csv

Outputs:
    data/processed/planned_blocks.csv
    data/processed/unscheduled_work_orders.csv
    data/processed/block_planning_report.txt

Planning strategy:
    1. Critical maintenance first.
    2. Then High, Medium and Low priorities.
    3. A work order can only use a window on the same railway section.
    4. Window duration must satisfy required maintenance duration.
    5. Best-fit allocation is preferred to preserve larger windows.
    6. Previously allocated maintenance time cannot overlap.

Important:
    This is the first TrackEase heuristic planning engine.
    It is a prototype decision-support system, not an official railway
    block authorization system.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WORK_ORDERS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_work_orders.csv"
)

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "available_block_windows.csv"
)

PLANNED_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "planned_blocks.csv"
)

UNSCHEDULED_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "unscheduled_work_orders.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_planning_report.txt"
)


MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

DAY_NAMES = [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
]


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------

def weekly_minute_to_day_time(value):
    """
    Convert minute-of-week into weekday and HH:MM.

    Monday 00:00 = minute 0.
    """

    value = int(value)

    # 10080 means next Monday 00:00.
    if value == MINUTES_PER_WEEK:
        return "Mon", "00:00"

    value %= MINUTES_PER_WEEK

    day_index = value // MINUTES_PER_DAY

    minute_of_day = value % MINUTES_PER_DAY

    hours = minute_of_day // 60
    minutes = minute_of_day % 60

    return (
        DAY_NAMES[day_index],
        f"{hours:02d}:{minutes:02d}",
    )


# ---------------------------------------------------------------------------
# Prepare mutable window state
# ---------------------------------------------------------------------------

def prepare_window_state(windows):
    """
    Convert available windows into an in-memory structure whose
    remaining start position can be updated after each allocation.
    """

    window_state = {}

    windows = windows.sort_values(
        [
            "section_id",
            "window_start_minute",
        ]
    )

    for row in windows.itertuples():

        section_windows = window_state.setdefault(
            row.section_id,
            [],
        )

        section_windows.append(
            {
                "window_id": row.window_id,

                "original_start": int(
                    row.window_start_minute
                ),

                "available_start": int(
                    row.window_start_minute
                ),

                "window_end": int(
                    row.window_end_minute
                ),

                "original_duration": int(
                    row.duration_minutes
                ),

                "window_class": row.window_class,
            }
        )

    return window_state


# ---------------------------------------------------------------------------
# Find best window
# ---------------------------------------------------------------------------

def select_best_window(
    section_windows,
    required_minutes,
):
    """
    Find the best currently available window.

    Best-fit rule:
        Prefer the window with the least unused time after allocation.

    This preserves longer windows for maintenance jobs that genuinely
    require them.
    """

    feasible = []

    for window in section_windows:

        remaining_minutes = (
            window["window_end"]
            - window["available_start"]
        )

        if remaining_minutes < required_minutes:
            continue

        slack_after = (
            remaining_minutes
            - required_minutes
        )

        feasible.append(
            (
                slack_after,
                window["available_start"],
                window,
            )
        )

    if not feasible:
        return None

    feasible.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    return feasible[0][2]


# ---------------------------------------------------------------------------
# Automatic planner
# ---------------------------------------------------------------------------

def plan_blocks():
    """Run the TrackEase automatic block planning engine."""

    print("=" * 72)
    print("TrackEase - Automatic Block Planner")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate files
    # -----------------------------------------------------------------------

    for file_path, label in [
        (
            WORK_ORDERS_FILE,
            "Maintenance work orders",
        ),
        (
            WINDOWS_FILE,
            "Available block windows",
        ),
    ]:

        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n"
                f"{file_path}"
            )

        print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------

    work_orders = pd.read_csv(
        WORK_ORDERS_FILE
    )

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    print(
        f"\nWork orders loaded : "
        f"{len(work_orders):,}"
    )

    print(
        f"Windows loaded     : "
        f"{len(windows):,}"
    )

    print(
        f"Sections in jobs   : "
        f"{work_orders['section_id'].nunique():,}"
    )

    # -----------------------------------------------------------------------
    # Prioritize work orders
    # -----------------------------------------------------------------------

    work_orders = work_orders.sort_values(
        [
            "priority_rank",
            "section_unique_trains",
            "required_minutes",
            "work_order_id",
        ],
        ascending=[
            False,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Prepare windows
    # -----------------------------------------------------------------------

    window_state = prepare_window_state(
        windows
    )

    planned_rows = []
    unscheduled_rows = []

    # -----------------------------------------------------------------------
    # Allocate every work order
    # -----------------------------------------------------------------------

    for work_order in work_orders.itertuples():

        section_windows = window_state.get(
            work_order.section_id,
            [],
        )

        required_minutes = int(
            work_order.required_minutes
        )

        selected_window = select_best_window(
            section_windows,
            required_minutes,
        )

        # -------------------------------------------------------------------
        # No feasible window
        # -------------------------------------------------------------------

        if selected_window is None:

            row = work_order._asdict()

            row["planning_status"] = (
                "UNSCHEDULED"
            )

            row["unscheduled_reason"] = (
                "No remaining block window "
                "long enough on section"
            )

            unscheduled_rows.append(
                row
            )

            continue

        # -------------------------------------------------------------------
        # Allocate contiguous maintenance period
        # -------------------------------------------------------------------

        scheduled_start = (
            selected_window[
                "available_start"
            ]
        )

        scheduled_end = (
            scheduled_start
            + required_minutes
        )

        # Move the available start forward so another maintenance job
        # cannot overlap this allocation.
        selected_window[
            "available_start"
        ] = scheduled_end

        # -------------------------------------------------------------------
        # Human-readable times
        # -------------------------------------------------------------------

        start_day, start_time = (
            weekly_minute_to_day_time(
                scheduled_start
            )
        )

        end_day, end_time = (
            weekly_minute_to_day_time(
                scheduled_end
            )
        )

        remaining_after = (
            selected_window["window_end"]
            - scheduled_end
        )

        # -------------------------------------------------------------------
        # Successful plan
        # -------------------------------------------------------------------

        planned_rows.append(
            {
                "work_order_id":
                    work_order.work_order_id,

                "task_id":
                    work_order.task_id,

                "section_id":
                    work_order.section_id,

                "station_a_code":
                    work_order.station_a_code,

                "station_a_name":
                    work_order.station_a_name,

                "station_b_code":
                    work_order.station_b_code,

                "station_b_name":
                    work_order.station_b_name,

                "department":
                    work_order.department,

                "task_type":
                    work_order.task_type,

                "priority_level":
                    work_order.priority_level,

                "priority_rank":
                    work_order.priority_rank,

                "required_minutes":
                    required_minutes,

                "window_id":
                    selected_window[
                        "window_id"
                    ],

                "scheduled_start_minute":
                    scheduled_start,

                "scheduled_end_minute":
                    scheduled_end,

                "scheduled_start_day":
                    start_day,

                "scheduled_start_time":
                    start_time,

                "scheduled_end_day":
                    end_day,

                "scheduled_end_time":
                    end_time,

                "source_window_start":
                    selected_window[
                        "original_start"
                    ],

                "source_window_end":
                    selected_window[
                        "window_end"
                    ],

                "source_window_duration":
                    selected_window[
                        "original_duration"
                    ],

                "unused_minutes_after":
                    remaining_after,

                "window_class":
                    selected_window[
                        "window_class"
                    ],

                "planning_status":
                    "SCHEDULED",

                "location_assignment_type":
                    work_order.location_assignment_type,
            }
        )

    # -----------------------------------------------------------------------
    # DataFrames
    # -----------------------------------------------------------------------

    planned = pd.DataFrame(
        planned_rows
    )

    unscheduled = pd.DataFrame(
        unscheduled_rows
    )

    # -----------------------------------------------------------------------
    # Generate TrackEase plan IDs
    # -----------------------------------------------------------------------

    if not planned.empty:

        planned.insert(
            0,
            "plan_id",
            [
                f"PLAN-{number:06d}"
                for number in range(
                    1,
                    len(planned) + 1
                )
            ],
        )

    # -----------------------------------------------------------------------
    # Save outputs
    # -----------------------------------------------------------------------

    planned.to_csv(
        PLANNED_FILE,
        index=False,
    )

    unscheduled.to_csv(
        UNSCHEDULED_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    total_jobs = len(
        work_orders
    )

    scheduled_jobs = len(
        planned
    )

    unscheduled_jobs = len(
        unscheduled
    )

    scheduling_rate = (
        scheduled_jobs
        / total_jobs
        * 100
        if total_jobs
        else 0
    )

    # -----------------------------------------------------------------------
    # Priority results
    # -----------------------------------------------------------------------

    if not planned.empty:

        scheduled_priority = (
            planned[
                "priority_level"
            ]
            .value_counts()
        )

        total_block_minutes = int(
            planned[
                "required_minutes"
            ]
            .sum()
        )

        sections_used = (
            planned[
                "section_id"
            ]
            .nunique()
        )

    else:

        scheduled_priority = (
            pd.Series(
                dtype=int
            )
        )

        total_block_minutes = 0
        sections_used = 0

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Automatic Block Planning Report",
        "=" * 72,
        "",
        "PLANNING SUMMARY",
        "-" * 72,
        f"Maintenance work orders : {total_jobs:,}",
        f"Successfully scheduled  : {scheduled_jobs:,}",
        f"Unscheduled             : {unscheduled_jobs:,}",
        f"Scheduling success rate : {scheduling_rate:.2f}%",
        f"Railway sections used   : {sections_used:,}",
        f"Maintenance block time  : {total_block_minutes:,} minutes",
        "",
        "SCHEDULED BY PRIORITY",
        "-" * 72,
    ]

    for priority in [
        "Critical",
        "High",
        "Medium",
        "Low",
    ]:

        count = int(
            scheduled_priority.get(
                priority,
                0,
            )
        )

        report.append(
            f"{priority:<20} {count:>8,}"
        )

    report.extend(
        [
            "",
            "PLANNING STRATEGY",
            "-" * 72,
            (
                "Critical maintenance is planned before "
                "High, Medium and Low priority maintenance."
            ),
            (
                "Maintenance is assigned only to train-free "
                "windows on the same railway section."
            ),
            (
                "A best-fit strategy prefers the smallest "
                "remaining window capable of completing the job."
            ),
            (
                "Allocated maintenance periods are reserved so "
                "multiple work orders cannot overlap."
            ),
            "",
            "IMPORTANT PROTOTYPE LIMITATION",
            "-" * 72,
            (
                "Maintenance section locations are controlled "
                "prototype assignments because the source maintenance "
                "dataset does not contain genuine section locations."
            ),
            (
                "The produced schedule is decision-support output "
                "and does not represent an official railway block authority."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console output
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("AUTOMATIC BLOCK PLANNING COMPLETE")
    print("=" * 72)

    print(
        f"\nWork orders        : "
        f"{total_jobs:,}"
    )

    print(
        f"Scheduled          : "
        f"{scheduled_jobs:,}"
    )

    print(
        f"Unscheduled        : "
        f"{unscheduled_jobs:,}"
    )

    print(
        f"Success rate       : "
        f"{scheduling_rate:.2f}%"
    )

    print(
        f"Sections used      : "
        f"{sections_used:,}"
    )

    print(
        f"Maintenance minutes: "
        f"{total_block_minutes:,}"
    )

    print("\nScheduled priorities:")

    for priority in [
        "Critical",
        "High",
        "Medium",
        "Low",
    ]:

        print(
            f"  {priority:<10} "
            f"{int(scheduled_priority.get(priority, 0)):>6,}"
        )

    print("\nOutputs:")
    print(f"  {PLANNED_FILE}")
    print(f"  {UNSCHEDULED_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nTrackEase has generated automatic "
        "maintenance block recommendations."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    plan_blocks()