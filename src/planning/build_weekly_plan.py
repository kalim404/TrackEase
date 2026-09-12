"""
TrackEase - Weekly Block Plan Builder

Purpose:
    Convert validated Optimizer V2 recommendations into clean weekly
    planning outputs suitable for dashboard presentation, review and
    downstream monthly planning.

Inputs:
    data/processed/optimized_weekly_blocks.csv
    data/processed/optimizer_v2_unscheduled.csv

Outputs:
    data/processed/weekly_block_plan.csv
    data/processed/weekly_plan_day_summary.csv
    data/processed/weekly_escalation_queue.csv
    data/processed/weekly_plan_report.txt

Important:
    - This script does not change optimizer decisions.
    - All scheduled recommendations remain subject to human approval.
    - Unscheduled Critical/High tasks are explicitly surfaced for escalation.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCHEDULED_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "optimized_weekly_blocks.csv"
)

UNSCHEDULED_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "optimizer_v2_unscheduled.csv"
)

WEEKLY_PLAN_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_block_plan.csv"
)

DAY_SUMMARY_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_plan_day_summary.csv"
)

ESCALATION_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_escalation_queue.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_plan_report.txt"
)


DAY_ORDER = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_columns(df, required_columns, dataset_name):
    """Raise a clear error when an input schema is incomplete."""

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(sorted(missing))
        )


def escalation_level(priority):
    """Assign an explicit review level to an unscheduled task."""

    priority = str(priority)

    if priority == "Critical":
        return "IMMEDIATE_ESCALATION"

    if priority == "High":
        return "HIGH_PRIORITY_REVIEW"

    if priority == "Medium":
        return "MONTHLY_REPLAN"

    return "BACKLOG_REVIEW"


def approval_queue_rank(priority):
    """Rank scheduled recommendations for human review."""

    ranks = {
        "Critical": 1,
        "High": 2,
        "Medium": 3,
        "Low": 4,
    }

    return ranks.get(str(priority), 5)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_weekly_plan():
    """Build dashboard-ready weekly planning outputs."""

    print("=" * 72)
    print("TrackEase - Weekly Block Plan Builder")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate inputs
    # -----------------------------------------------------------------------

    for file_path, label in [
        (
            SCHEDULED_FILE,
            "Optimized weekly blocks",
        ),
        (
            UNSCHEDULED_FILE,
            "Optimizer unscheduled tasks",
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

    scheduled = pd.read_csv(
        SCHEDULED_FILE
    )

    unscheduled = pd.read_csv(
        UNSCHEDULED_FILE
    )

    print(
        f"\nScheduled recommendations : {len(scheduled):,}"
    )

    print(
        f"Unscheduled tasks         : {len(unscheduled):,}"
    )

    # -----------------------------------------------------------------------
    # Schema validation
    # -----------------------------------------------------------------------

    require_columns(
        scheduled,
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
        "Optimized weekly blocks",
    )

    require_columns(
        unscheduled,
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
        },
        "Optimizer unscheduled tasks",
    )

    # -----------------------------------------------------------------------
    # Build weekly block plan
    # -----------------------------------------------------------------------

    weekly = scheduled.copy()

    weekly["day_index"] = (
        weekly["scheduled_start_day"]
        .map(DAY_ORDER)
    )

    if weekly["day_index"].isna().any():
        raise ValueError(
            "Unknown weekday label found in scheduled_start_day."
        )

    weekly["crosses_day_boundary"] = (
        weekly["scheduled_start_day"]
        != weekly["scheduled_end_day"]
    ).astype(int)

    weekly["approval_queue_rank"] = (
        weekly["trackease_priority_level"]
        .apply(approval_queue_rank)
    )

    weekly["weekly_plan_status"] = (
        "RECOMMENDED_PENDING_APPROVAL"
    )

    # Human-readable dashboard block label.
    weekly["block_display"] = (
        weekly["scheduled_start_day"].astype(str)
        + " "
        + weekly["scheduled_start_time"].astype(str)
        + " → "
        + weekly["scheduled_end_day"].astype(str)
        + " "
        + weekly["scheduled_end_time"].astype(str)
    )

    # Order recommendations by day/time.
    weekly = weekly.sort_values(
        [
            "day_index",
            "scheduled_start_minute",
            "approval_queue_rank",
            "section_id",
            "recommendation_id",
        ],
        ascending=[
            True,
            True,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)

    weekly.to_csv(
        WEEKLY_PLAN_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Build daily dashboard summary
    # -----------------------------------------------------------------------

    summary_rows = []

    for day_name, day_index in DAY_ORDER.items():

        day_blocks = weekly[
            weekly["scheduled_start_day"]
            == day_name
        ]

        if day_blocks.empty:

            summary_rows.append(
                {
                    "day": day_name,
                    "day_index": day_index,
                    "recommended_blocks": 0,
                    "maintenance_minutes": 0,
                    "critical_blocks": 0,
                    "high_blocks": 0,
                    "coordinated_blocks": 0,
                    "coordination_minutes_saved": 0,
                    "average_operational_impact": 0.0,
                    "low_impact_blocks": 0,
                    "moderate_impact_blocks": 0,
                    "high_impact_blocks": 0,
                    "very_high_impact_blocks": 0,
                }
            )

            continue

        summary_rows.append(
            {
                "day":
                    day_name,

                "day_index":
                    day_index,

                "recommended_blocks":
                    len(day_blocks),

                "maintenance_minutes":
                    int(
                        day_blocks[
                            "required_minutes"
                        ].sum()
                    ),

                "critical_blocks":
                    int(
                        (
                            day_blocks[
                                "trackease_priority_level"
                            ]
                            == "Critical"
                        ).sum()
                    ),

                "high_blocks":
                    int(
                        (
                            day_blocks[
                                "trackease_priority_level"
                            ]
                            == "High"
                        ).sum()
                    ),

                "coordinated_blocks":
                    int(
                        (
                            day_blocks[
                                "planning_task_type"
                            ]
                            == "COORDINATED"
                        ).sum()
                    ),

                "coordination_minutes_saved":
                    int(
                        day_blocks[
                            "estimated_minutes_saved"
                        ].sum()
                    ),

                "average_operational_impact":
                    round(
                        float(
                            day_blocks[
                                "operational_impact_score"
                            ].mean()
                        ),
                        2,
                    ),

                "low_impact_blocks":
                    int(
                        (
                            day_blocks[
                                "operational_impact_level"
                            ]
                            == "Low"
                        ).sum()
                    ),

                "moderate_impact_blocks":
                    int(
                        (
                            day_blocks[
                                "operational_impact_level"
                            ]
                            == "Moderate"
                        ).sum()
                    ),

                "high_impact_blocks":
                    int(
                        (
                            day_blocks[
                                "operational_impact_level"
                            ]
                            == "High"
                        ).sum()
                    ),

                "very_high_impact_blocks":
                    int(
                        (
                            day_blocks[
                                "operational_impact_level"
                            ]
                            == "Very High"
                        ).sum()
                    ),
            }
        )

    day_summary = pd.DataFrame(
        summary_rows
    ).sort_values(
        "day_index"
    )

    day_summary.to_csv(
        DAY_SUMMARY_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Build escalation queue
    # -----------------------------------------------------------------------

    escalation = unscheduled.copy()

    escalation["escalation_level"] = (
        escalation[
            "trackease_priority_level"
        ]
        .apply(escalation_level)
    )

    escalation["requires_human_review"] = 1

    escalation["recommended_next_action"] = (
        escalation[
            "trackease_priority_level"
        ]
        .map(
            {
                "Critical":
                    (
                        "Escalate immediately; seek longer/alternate "
                        "block or controlled operational intervention."
                    ),

                "High":
                    (
                        "Review alternate weekly/monthly opportunity "
                        "and operational trade-offs."
                    ),

                "Medium":
                    (
                        "Carry forward into monthly replanning unless "
                        "urgency changes."
                    ),

                "Low":
                    (
                        "Retain in maintenance backlog for later "
                        "feasible window."
                    ),
            }
        )
        .fillna(
            "Human planner review required."
        )
    )

    escalation["_priority_rank"] = (
        escalation[
            "trackease_priority_level"
        ]
        .map(
            {
                "Critical": 4,
                "High": 3,
                "Medium": 2,
                "Low": 1,
            }
        )
        .fillna(0)
    )

    escalation = escalation.sort_values(
        [
            "_priority_rank",
            "trackease_priority_score",
            "required_minutes",
            "planning_task_id",
        ],
        ascending=[
            False,
            False,
            False,
            True,
        ],
    ).drop(
        columns=["_priority_rank"]
    ).reset_index(drop=True)

    escalation.to_csv(
        ESCALATION_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    total_maintenance_minutes = int(
        weekly["required_minutes"].sum()
    )

    coordinated_blocks = int(
        (
            weekly["planning_task_type"]
            == "COORDINATED"
        ).sum()
    )

    coordination_saved = int(
        weekly[
            "estimated_minutes_saved"
        ].sum()
    )

    pending_approval = int(
        (
            weekly["approval_status"]
            == "PENDING"
        ).sum()
    )

    critical_scheduled = int(
        (
            weekly["trackease_priority_level"]
            == "Critical"
        ).sum()
    )

    high_scheduled = int(
        (
            weekly["trackease_priority_level"]
            == "High"
        ).sum()
    )

    critical_unscheduled = int(
        (
            escalation[
                "trackease_priority_level"
            ]
            == "Critical"
        ).sum()
    )

    high_unscheduled = int(
        (
            escalation[
                "trackease_priority_level"
            ]
            == "High"
        ).sum()
    )

    cross_day_blocks = int(
        weekly[
            "crosses_day_boundary"
        ].sum()
    )

    average_impact = float(
        weekly[
            "operational_impact_score"
        ].mean()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Weekly Block Plan Report",
        "=" * 72,
        "",
        "WEEKLY PLAN",
        "-" * 72,
        f"Recommended blocks            : {len(weekly):,}",
        f"Maintenance minutes           : {total_maintenance_minutes:,}",
        f"Critical blocks scheduled     : {critical_scheduled:,}",
        f"High blocks scheduled         : {high_scheduled:,}",
        f"Coordinated blocks            : {coordinated_blocks:,}",
        f"Coordination minutes saved    : {coordination_saved:,}",
        f"Cross-day blocks              : {cross_day_blocks:,}",
        f"Average operational impact    : {average_impact:.2f}/100",
        f"Pending human approval        : {pending_approval:,}",
        "",
        "UNSCHEDULED / ESCALATION",
        "-" * 72,
        f"Total unscheduled             : {len(escalation):,}",
        f"Critical escalation           : {critical_unscheduled:,}",
        f"High-priority review          : {high_unscheduled:,}",
        "",
        "DAY SUMMARY",
        "-" * 72,
    ]

    for row in day_summary.itertuples():

        report.append(
            (
                f"{row.day}: "
                f"{int(row.recommended_blocks):,} blocks, "
                f"{int(row.maintenance_minutes):,} min, "
                f"{int(row.critical_blocks):,} Critical, "
                f"{int(row.coordinated_blocks):,} coordinated, "
                f"avg impact "
                f"{float(row.average_operational_impact):.2f}"
            )
        )

    report.extend(
        [
            "",
            "HUMAN-IN-THE-LOOP",
            "-" * 72,
            (
                "All weekly blocks remain recommendations with "
                "PENDING approval status."
            ),
            (
                "Critical/High unscheduled tasks are surfaced "
                "separately rather than forced into unsafe windows."
            ),
            "",
            "NEXT STAGE",
            "-" * 72,
            (
                "Build the monthly planning layer using weekly "
                "recommendations plus the unscheduled "
                "escalation/carry-forward queue."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("WEEKLY BLOCK PLAN BUILD COMPLETE")
    print("=" * 72)

    print(
        f"\nRecommended blocks : "
        f"{len(weekly):,}"
    )

    print(
        f"Maintenance minutes: "
        f"{total_maintenance_minutes:,}"
    )

    print(
        f"Coordinated blocks : "
        f"{coordinated_blocks:,}"
    )

    print(
        f"Minutes saved      : "
        f"{coordination_saved:,}"
    )

    print(
        f"Average impact     : "
        f"{average_impact:.2f}/100"
    )

    print("\nEscalation queue:")

    print(
        f"  Total unscheduled : "
        f"{len(escalation):,}"
    )

    print(
        f"  Critical          : "
        f"{critical_unscheduled:,}"
    )

    print(
        f"  High              : "
        f"{high_unscheduled:,}"
    )

    print("\nOutputs:")

    print(
        f"  {WEEKLY_PLAN_FILE}"
    )

    print(
        f"  {DAY_SUMMARY_FILE}"
    )

    print(
        f"  {ESCALATION_FILE}"
    )

    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nTrackEase now has a dashboard-ready weekly plan "
        "plus an explicit unscheduled escalation queue."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_weekly_plan()