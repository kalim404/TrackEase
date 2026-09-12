"""
TrackEase - Monthly Maintenance Plan Builder

Purpose:
    Convert the validated weekly TrackEase recommendations into a
    four-week maintenance programme while preserving each recommendation's
    safe weekday/time window.

Inputs:
    data/processed/weekly_block_plan.csv
    data/processed/weekly_escalation_queue.csv

Outputs:
    data/processed/monthly_block_plan.csv
    data/processed/monthly_week_summary.csv
    data/processed/monthly_carry_forward_queue.csv
    data/processed/monthly_plan_report.txt

Planning approach:
    - Maintenance tasks are treated as one-time requirements for the
      prototype month, not repeated every week.
    - Critical work is targeted earliest.
    - High-priority work is concentrated in Weeks 1-2.
    - Medium work is concentrated in Weeks 2-3.
    - Low work is concentrated in Weeks 3-4.
    - Within the allowed week range, tasks are assigned to the currently
      least-loaded week to avoid an unnecessarily concentrated programme.
    - The Optimizer V2 weekday/time recommendation is preserved.
    - Unscheduled tasks are not forced into the monthly plan. They remain
      in an explicit carry-forward/escalation queue.

Important:
    This is a prototype planning horizon, not an official railway calendar.
    Final blocks remain subject to human approval and railway operating rules.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WEEKLY_PLAN_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_block_plan.csv"
)

WEEKLY_ESCALATION_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_escalation_queue.csv"
)

MONTHLY_PLAN_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "monthly_block_plan.csv"
)

MONTHLY_SUMMARY_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "monthly_week_summary.csv"
)

MONTHLY_CARRY_FORWARD_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "monthly_carry_forward_queue.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "monthly_plan_report.txt"
)


MINUTES_PER_WEEK = 10080
WEEKS_IN_PLAN = 4


# ---------------------------------------------------------------------------
# Planning policy
# ---------------------------------------------------------------------------

PRIORITY_WEEK_OPTIONS = {
    "Critical": [1],
    "High": [1, 2],
    "Medium": [2, 3],
    "Low": [3, 4],
}

PRIORITY_RANK = {
    "Critical": 4,
    "High": 3,
    "Medium": 2,
    "Low": 1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_columns(df, required_columns, dataset_name):
    """Raise a clear error if an input schema is incomplete."""

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(sorted(missing))
        )


def choose_month_week(row, week_load_minutes, week_task_counts):
    """
    Select a target month week.

    Priority determines the allowed week range. Within that range,
    choose the week with the least maintenance load. Task count and
    earlier week number are deterministic tie-breakers.
    """

    priority = str(
        row.trackease_priority_level
    )

    allowed_weeks = (
        PRIORITY_WEEK_OPTIONS.get(
            priority,
            [4],
        )
    )

    selected_week = min(
        allowed_weeks,
        key=lambda week: (
            week_load_minutes[week],
            week_task_counts[week],
            week,
        ),
    )

    return selected_week


def monthly_escalation_action(priority, reason_code):
    """Create a transparent carry-forward action for unscheduled work."""

    priority = str(priority)
    reason_code = str(reason_code)

    if reason_code == "NO_SAFE_WINDOW_ON_SECTION":

        if priority == "Critical":
            return (
                "Immediate control/engineering escalation: no safe timetable "
                "window exists on the section. Seek special block strategy."
            )

        return (
            "Human planner review required because no safe recurring timetable "
            "window exists on the section."
        )

    if reason_code == "NO_WINDOW_LONG_ENOUGH":

        if priority == "Critical":
            return (
                "Immediate escalation: investigate special longer block, "
                "approved task decomposition, or controlled traffic intervention."
            )

        if priority == "High":
            return (
                "Seek alternate longer block or engineering-approved task "
                "decomposition during monthly review."
            )

        return (
            "Carry forward until a sufficiently long approved block opportunity "
            "is available."
        )

    if reason_code == "CAPACITY_USED_BY_HIGHER_PRIORITY_TASKS":
        return (
            "Re-evaluate in a later month week after higher-priority allocations."
        )

    return (
        "Human planner review required before future scheduling."
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_monthly_plan():
    """Build a balanced four-week TrackEase maintenance programme."""

    print("=" * 72)
    print("TrackEase - Monthly Maintenance Plan Builder")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate files
    # -----------------------------------------------------------------------

    for file_path, label in [
        (
            WEEKLY_PLAN_FILE,
            "Weekly block plan",
        ),
        (
            WEEKLY_ESCALATION_FILE,
            "Weekly escalation queue",
        ),
    ]:

        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n{file_path}"
            )

        print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    weekly = pd.read_csv(
        WEEKLY_PLAN_FILE
    )

    escalation = pd.read_csv(
        WEEKLY_ESCALATION_FILE
    )

    print(
        f"\nWeekly recommendations loaded : {len(weekly):,}"
    )

    print(
        f"Escalation tasks loaded       : {len(escalation):,}"
    )

    # -----------------------------------------------------------------------
    # Schema validation
    # -----------------------------------------------------------------------

    require_columns(
        weekly,
        {
            "recommendation_id",
            "planning_task_id",
            "planning_task_type",
            "section_id",
            "departments_involved",
            "trackease_priority_score",
            "trackease_priority_level",
            "required_minutes",
            "scheduled_start_minute",
            "scheduled_end_minute",
            "scheduled_start_day",
            "scheduled_start_time",
            "scheduled_end_day",
            "scheduled_end_time",
            "operational_impact_score",
            "operational_impact_level",
            "estimated_minutes_saved",
            "approval_status",
            "recommendation_explanation",
        },
        "Weekly block plan",
    )

    require_columns(
        escalation,
        {
            "planning_task_id",
            "planning_task_type",
            "section_id",
            "departments_involved",
            "trackease_priority_score",
            "trackease_priority_level",
            "required_minutes",
            "unscheduled_reason_code",
            "unscheduled_reason",
            "escalation_level",
        },
        "Weekly escalation queue",
    )

    # -----------------------------------------------------------------------
    # Numeric integrity
    # -----------------------------------------------------------------------

    weekly["required_minutes"] = pd.to_numeric(
        weekly["required_minutes"],
        errors="coerce",
    )

    weekly["trackease_priority_score"] = pd.to_numeric(
        weekly["trackease_priority_score"],
        errors="coerce",
    )

    weekly["scheduled_start_minute"] = pd.to_numeric(
        weekly["scheduled_start_minute"],
        errors="coerce",
    )

    weekly["scheduled_end_minute"] = pd.to_numeric(
        weekly["scheduled_end_minute"],
        errors="coerce",
    )

    if (
        weekly[
            [
                "required_minutes",
                "trackease_priority_score",
                "scheduled_start_minute",
                "scheduled_end_minute",
            ]
        ]
        .isna()
        .any()
        .any()
    ):
        raise ValueError(
            "Weekly plan contains invalid numeric planning values."
        )

    # -----------------------------------------------------------------------
    # Order one-time monthly maintenance requirements.
    # -----------------------------------------------------------------------

    monthly_source = weekly.copy()

    monthly_source["_priority_rank"] = (
        monthly_source[
            "trackease_priority_level"
        ]
        .map(PRIORITY_RANK)
        .fillna(0)
    )

    monthly_source["_coordination_rank"] = (
        monthly_source[
            "planning_task_type"
        ]
        .map(
            {
                "COORDINATED": 2,
                "PRECOORDINATED_SOURCE": 1,
                "SINGLE": 0,
            }
        )
        .fillna(0)
    )

    monthly_source = monthly_source.sort_values(
        [
            "_priority_rank",
            "trackease_priority_score",
            "_coordination_rank",
            "required_minutes",
            "planning_task_id",
        ],
        ascending=[
            False,
            False,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Assign each one-time task to one month week.
    # -----------------------------------------------------------------------

    week_load_minutes = {
        week: 0
        for week in range(
            1,
            WEEKS_IN_PLAN + 1
        )
    }

    week_task_counts = {
        week: 0
        for week in range(
            1,
            WEEKS_IN_PLAN + 1
        )
    }

    month_rows = []

    for index, row in enumerate(
        monthly_source.itertuples(),
        start=1,
    ):

        month_week = choose_month_week(
            row,
            week_load_minutes,
            week_task_counts,
        )

        required = int(
            row.required_minutes
        )

        week_load_minutes[
            month_week
        ] += required

        week_task_counts[
            month_week
        ] += 1

        monthly_start = (
            (month_week - 1)
            * MINUTES_PER_WEEK
            + int(
                row.scheduled_start_minute
            )
        )

        monthly_end = (
            (month_week - 1)
            * MINUTES_PER_WEEK
            + int(
                row.scheduled_end_minute
            )
        )

        month_rows.append(
            {
                "monthly_plan_id":
                    f"MBP-{index:06d}",

                "month_week":
                    month_week,

                "month_week_label":
                    f"Week {month_week}",

                "recommendation_id":
                    row.recommendation_id,

                "planning_task_id":
                    row.planning_task_id,

                "planning_task_type":
                    row.planning_task_type,

                "coordination_group":
                    getattr(
                        row,
                        "coordination_group",
                        "",
                    ),

                "section_id":
                    row.section_id,

                "station_a_code":
                    getattr(
                        row,
                        "station_a_code",
                        None,
                    ),

                "station_a_name":
                    getattr(
                        row,
                        "station_a_name",
                        None,
                    ),

                "station_b_code":
                    getattr(
                        row,
                        "station_b_code",
                        None,
                    ),

                "station_b_name":
                    getattr(
                        row,
                        "station_b_name",
                        None,
                    ),

                "departments_involved":
                    row.departments_involved,

                "source_systems":
                    getattr(
                        row,
                        "source_systems",
                        "",
                    ),

                "source_task_ids":
                    getattr(
                        row,
                        "source_task_ids",
                        "",
                    ),

                "trackease_priority_score":
                    float(
                        row.trackease_priority_score
                    ),

                "trackease_priority_level":
                    row.trackease_priority_level,

                "required_minutes":
                    required,

                "estimated_minutes_saved":
                    int(
                        getattr(
                            row,
                            "estimated_minutes_saved",
                            0,
                        )
                    ),

                "scheduled_day":
                    row.scheduled_start_day,

                "scheduled_start_time":
                    row.scheduled_start_time,

                "scheduled_end_day":
                    row.scheduled_end_day,

                "scheduled_end_time":
                    row.scheduled_end_time,

                "weekly_start_minute":
                    int(
                        row.scheduled_start_minute
                    ),

                "weekly_end_minute":
                    int(
                        row.scheduled_end_minute
                    ),

                "monthly_start_minute":
                    int(
                        monthly_start
                    ),

                "monthly_end_minute":
                    int(
                        monthly_end
                    ),

                "operational_impact_score":
                    float(
                        row.operational_impact_score
                    ),

                "operational_impact_level":
                    row.operational_impact_level,

                "recommendation_explanation":
                    row.recommendation_explanation,

                "approval_status":
                    row.approval_status,

                "monthly_plan_status":
                    "RECOMMENDED_PENDING_APPROVAL",
            }
        )

    monthly = pd.DataFrame(
        month_rows
    )

    # -----------------------------------------------------------------------
    # Internal monthly integrity checks.
    # -----------------------------------------------------------------------

    duplicate_tasks = int(
        monthly[
            "planning_task_id"
        ].duplicated().sum()
    )

    if duplicate_tasks > 0:
        raise RuntimeError(
            f"{duplicate_tasks:,} planning tasks were assigned more than once."
        )

    if len(monthly) != len(weekly):
        raise RuntimeError(
            "Monthly assignment accounting failed."
        )

    invalid_week = int(
        (
            ~monthly[
                "month_week"
            ].between(
                1,
                WEEKS_IN_PLAN,
            )
        ).sum()
    )

    if invalid_week > 0:
        raise RuntimeError(
            f"{invalid_week:,} monthly tasks have an invalid week assignment."
        )

    # Because Optimizer V2 safely fit all 1,099 recommendations into one
    # recurring week, separating them across different month weeks cannot
    # introduce a new same-week maintenance overlap. We still verify each
    # month-week/section directly.
    monthly_overlap_count = 0

    for (
        month_week,
        section_id,
    ), group in monthly.groupby(
        [
            "month_week",
            "section_id",
        ],
        sort=False,
    ):

        group = group.sort_values(
            "monthly_start_minute"
        )

        previous_end = None

        for row in group.itertuples():

            start = int(
                row.monthly_start_minute
            )

            end = int(
                row.monthly_end_minute
            )

            if (
                previous_end is not None
                and start < previous_end
            ):
                monthly_overlap_count += 1

            previous_end = max(
                previous_end or end,
                end,
            )

    if monthly_overlap_count > 0:
        raise RuntimeError(
            f"{monthly_overlap_count:,} monthly maintenance overlaps detected."
        )

    # -----------------------------------------------------------------------
    # Sort and save monthly plan.
    # -----------------------------------------------------------------------

    monthly = monthly.sort_values(
        [
            "month_week",
            "monthly_start_minute",
            "trackease_priority_score",
            "section_id",
            "monthly_plan_id",
        ],
        ascending=[
            True,
            True,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)

    monthly.to_csv(
        MONTHLY_PLAN_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Week-level dashboard summary.
    # -----------------------------------------------------------------------

    summary_rows = []

    for week in range(
        1,
        WEEKS_IN_PLAN + 1,
    ):

        group = monthly[
            monthly[
                "month_week"
            ]
            == week
        ]

        summary_rows.append(
            {
                "month_week":
                    week,

                "month_week_label":
                    f"Week {week}",

                "recommended_blocks":
                    len(group),

                "maintenance_minutes":
                    int(
                        group[
                            "required_minutes"
                        ].sum()
                    ),

                "critical_blocks":
                    int(
                        (
                            group[
                                "trackease_priority_level"
                            ]
                            == "Critical"
                        ).sum()
                    ),

                "high_blocks":
                    int(
                        (
                            group[
                                "trackease_priority_level"
                            ]
                            == "High"
                        ).sum()
                    ),

                "medium_blocks":
                    int(
                        (
                            group[
                                "trackease_priority_level"
                            ]
                            == "Medium"
                        ).sum()
                    ),

                "low_blocks":
                    int(
                        (
                            group[
                                "trackease_priority_level"
                            ]
                            == "Low"
                        ).sum()
                    ),

                "coordinated_blocks":
                    int(
                        (
                            group[
                                "planning_task_type"
                            ]
                            == "COORDINATED"
                        ).sum()
                    ),

                "coordination_minutes_saved":
                    int(
                        group[
                            "estimated_minutes_saved"
                        ].sum()
                    ),

                "average_operational_impact":
                    round(
                        float(
                            group[
                                "operational_impact_score"
                            ].mean()
                        )
                        if not group.empty
                        else 0.0,
                        2,
                    ),
            }
        )

    month_summary = pd.DataFrame(
        summary_rows
    )

    month_summary.to_csv(
        MONTHLY_SUMMARY_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Carry-forward / escalation queue.
    # -----------------------------------------------------------------------

    carry_forward = escalation.copy()

    carry_forward[
        "monthly_queue_status"
    ] = "UNSCHEDULED_REQUIRES_REVIEW"

    carry_forward[
        "monthly_target"
    ] = carry_forward[
        "trackease_priority_level"
    ].map(
        {
            "Critical":
                "Week 1 immediate escalation",

            "High":
                "Weeks 1-2 review",

            "Medium":
                "Weeks 2-4 replanning",

            "Low":
                "Backlog / future month",
        }
    ).fillna(
        "Human planner review"
    )

    carry_forward[
        "monthly_recommended_action"
    ] = carry_forward.apply(
        lambda row: monthly_escalation_action(
            row[
                "trackease_priority_level"
            ],
            row[
                "unscheduled_reason_code"
            ],
        ),
        axis=1,
    )

    carry_forward.to_csv(
        MONTHLY_CARRY_FORWARD_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Metrics.
    # -----------------------------------------------------------------------

    total_minutes = int(
        monthly[
            "required_minutes"
        ].sum()
    )

    coordinated_count = int(
        (
            monthly[
                "planning_task_type"
            ]
            == "COORDINATED"
        ).sum()
    )

    saved_minutes = int(
        monthly[
            "estimated_minutes_saved"
        ].sum()
    )

    pending_approval = int(
        (
            monthly[
                "approval_status"
            ]
            == "PENDING"
        ).sum()
    )

    critical_carry_forward = int(
        (
            carry_forward[
                "trackease_priority_level"
            ]
            == "Critical"
        ).sum()
    )

    high_carry_forward = int(
        (
            carry_forward[
                "trackease_priority_level"
            ]
            == "High"
        ).sum()
    )

    # -----------------------------------------------------------------------
    # Report.
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Monthly Maintenance Plan Report",
        "=" * 72,
        "",
        "MONTHLY PROGRAMME",
        "-" * 72,
        f"Planning horizon               : {WEEKS_IN_PLAN} weeks",
        f"One-time tasks assigned        : {len(monthly):,}",
        f"Maintenance minutes            : {total_minutes:,}",
        f"Coordinated blocks             : {coordinated_count:,}",
        f"Coordination minutes saved     : {saved_minutes:,}",
        f"Pending human approval         : {pending_approval:,}",
        f"Monthly allocation overlaps    : {monthly_overlap_count:,}",
        "",
        "WEEK DISTRIBUTION",
        "-" * 72,
    ]

    for row in month_summary.itertuples():

        report.append(
            (
                f"Week {int(row.month_week)}: "
                f"{int(row.recommended_blocks):,} blocks, "
                f"{int(row.maintenance_minutes):,} min, "
                f"{int(row.critical_blocks):,} Critical, "
                f"{int(row.high_blocks):,} High, "
                f"{int(row.coordinated_blocks):,} coordinated, "
                f"avg impact {float(row.average_operational_impact):.2f}"
            )
        )

    report.extend(
        [
            "",
            "CARRY-FORWARD / ESCALATION",
            "-" * 72,
            f"Unscheduled tasks              : {len(carry_forward):,}",
            f"Critical immediate escalation  : {critical_carry_forward:,}",
            f"High-priority monthly review   : {high_carry_forward:,}",
            "",
            "PLANNING POLICY",
            "-" * 72,
            "Critical : Week 1",
            "High     : Weeks 1-2",
            "Medium   : Weeks 2-3",
            "Low      : Weeks 3-4",
            (
                "Within the allowed range, tasks are assigned to the "
                "least-loaded week."
            ),
            (
                "The validated weekly weekday/time recommendation is "
                "preserved for the selected month week."
            ),
            "",
            "IMPORTANT LIMITATION",
            "-" * 72,
            (
                "The prototype month is represented as four recurring "
                "planning weeks rather than a specific calendar month."
            ),
            (
                "A real deployment would map these relative weeks to actual "
                "dates and update them using live traffic/maintenance inputs."
            ),
            "",
            "NEXT STAGE",
            "-" * 72,
            (
                "Add approval/reject/reschedule workflow and BDMS-style "
                "planning export before frontend integration."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console.
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("MONTHLY MAINTENANCE PLAN BUILD COMPLETE")
    print("=" * 72)

    print(
        f"\nMonthly tasks assigned : {len(monthly):,}"
    )

    print(
        f"Maintenance minutes    : {total_minutes:,}"
    )

    print(
        f"Coordinated blocks     : {coordinated_count:,}"
    )

    print(
        f"Minutes saved          : {saved_minutes:,}"
    )

    print(
        f"Monthly overlaps       : {monthly_overlap_count:,}"
    )

    print("\nWeek distribution:")

    for row in month_summary.itertuples():

        print(
            f"  Week {int(row.month_week)} : "
            f"{int(row.recommended_blocks):>4,} blocks | "
            f"{int(row.maintenance_minutes):>7,} min"
        )

    print("\nCarry-forward queue:")

    print(
        f"  Total    : {len(carry_forward):,}"
    )

    print(
        f"  Critical : {critical_carry_forward:,}"
    )

    print(
        f"  High     : {high_carry_forward:,}"
    )

    print("\nOutputs:")
    print(
        f"  {MONTHLY_PLAN_FILE}"
    )
    print(
        f"  {MONTHLY_SUMMARY_FILE}"
    )
    print(
        f"  {MONTHLY_CARRY_FORWARD_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nTrackEase now has both explicit weekly and monthly "
        "maintenance planning horizons."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_monthly_plan()
