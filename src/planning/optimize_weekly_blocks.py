"""
TrackEase - Impact-Aware Weekly Block Optimizer V2

Purpose:
    Allocate coordinated TrackEase maintenance planning units into safe,
    goods-adjusted, operationally scored weekly block windows.

Inputs:
    data/processed/coordinated_planning_tasks.csv
    data/processed/scored_block_windows.csv

Outputs:
    data/processed/optimized_weekly_blocks.csv
    data/processed/optimizer_v2_unscheduled.csv
    data/processed/optimizer_v2_report.txt

Core strategy:
    1. Process higher-priority maintenance first.
    2. Preserve multi-department coordination benefits.
    3. Consider only windows on the correct railway section.
    4. Require sufficient remaining duration.
    5. Prefer lower operational-impact windows.
    6. Prefer tighter-fitting windows when impact is comparable.
    7. Reserve allocated time so maintenance recommendations never overlap
       one another inside the same available window.
    8. Explicitly retain unscheduled tasks with a reason.

Important:
    This is a prototype decision-support optimizer. It does not represent
    official Indian Railways block sanctioning or dispatch authority.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TASKS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coordinated_planning_tasks.csv"
)

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "scored_block_windows.csv"
)

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

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "optimizer_v2_report.txt"
)


MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

# Candidate-selection weights.
#
# Lower candidate cost is better:
#   operational impact = 75%
#   fit / unused-slack penalty = 25%
IMPACT_WEIGHT = 0.75
FIT_WEIGHT = 0.25

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
# Helpers
# ---------------------------------------------------------------------------

def weekly_minute_to_label(value):
    """Convert a recurring-week minute into weekday and HH:MM."""

    value = int(value)

    if value == MINUTES_PER_WEEK:
        return "Mon", "00:00"

    value %= MINUTES_PER_WEEK

    day_index = value // MINUTES_PER_DAY
    minute_of_day = value % MINUTES_PER_DAY

    hour = minute_of_day // 60
    minute = minute_of_day % 60

    return (
        DAY_NAMES[day_index],
        f"{hour:02d}:{minute:02d}",
    )


def planning_type_rank(value):
    """Use coordination status only as a tie-breaker after priority."""

    ranks = {
        "COORDINATED": 2,
        "PRECOORDINATED_SOURCE": 1,
        "SINGLE": 0,
    }

    return ranks.get(
        str(value),
        0,
    )


def validate_required_columns(
    df,
    required_columns,
    dataset_name,
):
    """Raise a clear error if an input schema is incomplete."""

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(
                sorted(missing)
            )
        )


def build_recommendation_explanation(
    task,
    candidate,
    remaining_after,
):
    """Create a concise human-readable reason for the recommendation."""

    parts = [
        (
            f"Priority {float(task.trackease_priority_score):.2f}/100"
        ),
        (
            f"operational impact "
            f"{float(candidate['operational_impact_score']):.2f}/100 "
            f"({candidate['operational_impact_level']})"
        ),
        (
            f"{int(remaining_after)} min window capacity remains"
        ),
    ]

    if str(task.planning_task_type) == "COORDINATED":
        parts.append(
            (
                f"coordinates {int(task.department_count)} departments "
                f"and retains estimated saving of "
                f"{int(task.estimated_minutes_saved)} min"
            )
        )

    elif str(task.planning_task_type) == "PRECOORDINATED_SOURCE":
        parts.append(
            "preserves an existing joint departmental requirement"
        )

    if int(candidate.get("goods_forecast_present", 0)) == 1:
        parts.append(
            "selected only from the safe remainder after COA forecast adjustment"
        )
    else:
        parts.append(
            "no prototype COA goods exposure on this window"
        )

    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Post-allocation checks
# ---------------------------------------------------------------------------

def count_scheduled_overlaps(scheduled):
    """Count any maintenance-to-maintenance overlaps in the same source window."""

    if scheduled.empty:
        return 0

    overlaps = 0

    for _, group in scheduled.groupby(
        "adjusted_window_id",
        sort=False,
    ):

        group = group.sort_values(
            "scheduled_start_minute"
        )

        previous_end = None

        for row in group.itertuples():

            start = int(
                row.scheduled_start_minute
            )

            end = int(
                row.scheduled_end_minute
            )

            if (
                previous_end is not None
                and start < previous_end
            ):
                overlaps += 1

            previous_end = max(
                previous_end or end,
                end,
            )

    return overlaps


# ---------------------------------------------------------------------------
# Main optimizer
# ---------------------------------------------------------------------------

def optimize_weekly_blocks():
    """Generate impact-aware weekly block recommendations."""

    print("=" * 72)
    print("TrackEase - Impact-Aware Weekly Block Optimizer V2")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Input validation
    # -----------------------------------------------------------------------

    for file_path, label in [
        (
            TASKS_FILE,
            "Coordinated planning tasks",
        ),
        (
            WINDOWS_FILE,
            "Scored block windows",
        ),
    ]:

        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n{file_path}"
            )

        print("  ✓ Found")

    tasks = pd.read_csv(
        TASKS_FILE
    )

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    print(
        f"\nPlanning units loaded : {len(tasks):,}"
    )

    print(
        f"Scored windows loaded : {len(windows):,}"
    )

    validate_required_columns(
        tasks,
        {
            "planning_task_id",
            "planning_task_type",
            "section_id",
            "trackease_priority_score",
            "trackease_priority_level",
            "required_minutes",
            "estimated_minutes_saved",
            "department_count",
            "departments_involved",
            "source_systems",
            "source_task_ids",
        },
        "Coordinated planning tasks",
    )

    validate_required_columns(
        windows,
        {
            "adjusted_window_id",
            "source_window_id",
            "section_id",
            "window_start_minute",
            "window_end_minute",
            "duration_minutes",
            "start_day",
            "start_time",
            "end_day",
            "end_time",
            "operational_impact_score",
            "operational_impact_level",
            "goods_forecast_present",
            "coa_adjusted",
            "weekly_train_movements",
        },
        "Scored block windows",
    )

    # -----------------------------------------------------------------------
    # Numeric integrity
    # -----------------------------------------------------------------------

    tasks["required_minutes"] = pd.to_numeric(
        tasks["required_minutes"],
        errors="coerce",
    )

    tasks["trackease_priority_score"] = pd.to_numeric(
        tasks["trackease_priority_score"],
        errors="coerce",
    )

    windows["window_start_minute"] = pd.to_numeric(
        windows["window_start_minute"],
        errors="coerce",
    )

    windows["window_end_minute"] = pd.to_numeric(
        windows["window_end_minute"],
        errors="coerce",
    )

    windows["duration_minutes"] = pd.to_numeric(
        windows["duration_minutes"],
        errors="coerce",
    )

    windows["operational_impact_score"] = pd.to_numeric(
        windows["operational_impact_score"],
        errors="coerce",
    )

    invalid_tasks = (
        tasks["required_minutes"].isna()
        | (tasks["required_minutes"] <= 0)
        | tasks["trackease_priority_score"].isna()
    )

    if invalid_tasks.any():
        raise ValueError(
            f"{int(invalid_tasks.sum()):,} planning tasks contain "
            "invalid duration or priority values."
        )

    invalid_windows = (
        windows["window_start_minute"].isna()
        | windows["window_end_minute"].isna()
        | windows["duration_minutes"].isna()
        | windows["operational_impact_score"].isna()
        | (
            windows["window_end_minute"]
            <= windows["window_start_minute"]
        )
    )

    if invalid_windows.any():
        raise ValueError(
            f"{int(invalid_windows.sum()):,} scored windows contain "
            "invalid timing or impact values."
        )

    # -----------------------------------------------------------------------
    # Prepare deterministic task order.
    #
    # Priority dominates. Coordination and duration are tie-breakers.
    # -----------------------------------------------------------------------

    tasks["_planning_type_rank"] = (
        tasks["planning_task_type"]
        .apply(planning_type_rank)
    )

    tasks["_estimated_saved_numeric"] = pd.to_numeric(
        tasks["estimated_minutes_saved"],
        errors="coerce",
    ).fillna(0)

    tasks = tasks.sort_values(
        [
            "trackease_priority_score",
            "_planning_type_rank",
            "_estimated_saved_numeric",
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
    ).reset_index(
        drop=True
    )

    # -----------------------------------------------------------------------
    # Build mutable window state.
    # -----------------------------------------------------------------------

    windows_by_section = {}

    section_original_max = (
        windows
        .groupby("section_id")["duration_minutes"]
        .max()
        .to_dict()
    )

    for row in windows.itertuples():

        window_state = {
            "adjusted_window_id":
                row.adjusted_window_id,

            "source_window_id":
                row.source_window_id,

            "section_id":
                row.section_id,

            "original_start":
                int(row.window_start_minute),

            "available_start":
                int(row.window_start_minute),

            "window_end":
                int(row.window_end_minute),

            "original_duration":
                int(row.duration_minutes),

            "operational_impact_score":
                float(row.operational_impact_score),

            "operational_impact_level":
                row.operational_impact_level,

            "goods_forecast_present":
                int(row.goods_forecast_present),

            "coa_adjusted":
                int(row.coa_adjusted),

            "weekly_train_movements":
                int(row.weekly_train_movements),
        }

        windows_by_section.setdefault(
            row.section_id,
            []
        ).append(
            window_state
        )

    # Keep state order deterministic.
    for section_id in windows_by_section:

        windows_by_section[
            section_id
        ].sort(
            key=lambda item: (
                item["operational_impact_score"],
                item["original_duration"],
                item["original_start"],
                item["adjusted_window_id"],
            )
        )

    # -----------------------------------------------------------------------
    # Allocate tasks.
    # -----------------------------------------------------------------------

    scheduled_rows = []
    unscheduled_rows = []

    recommendation_counter = 1

    for task in tasks.itertuples():

        section_windows = (
            windows_by_section.get(
                task.section_id,
                []
            )
        )

        required = int(
            task.required_minutes
        )

        candidates = []

        for window in section_windows:

            remaining = (
                window["window_end"]
                - window["available_start"]
            )

            if remaining < required:
                continue

            slack_after = (
                remaining
                - required
            )

            # 0 = perfect fit, approaching 100 = large amount unused.
            fit_penalty = (
                slack_after
                / remaining
                * 100
                if remaining > 0
                else 100
            )

            candidate_cost = (
                IMPACT_WEIGHT
                * window[
                    "operational_impact_score"
                ]
                + FIT_WEIGHT
                * fit_penalty
            )

            candidates.append(
                {
                    "window":
                        window,

                    "remaining_before":
                        remaining,

                    "slack_after":
                        slack_after,

                    "fit_penalty":
                        fit_penalty,

                    "candidate_cost":
                        candidate_cost,
                }
            )

        # -------------------------------------------------------------------
        # No feasible candidate.
        # -------------------------------------------------------------------

        if not candidates:

            if not section_windows:

                reason_code = (
                    "NO_SAFE_WINDOW_ON_SECTION"
                )

                reason_text = (
                    "No adjusted maintenance window exists on this section."
                )

                max_remaining = 0

            else:

                max_remaining = max(
                    (
                        window["window_end"]
                        - window["available_start"]
                    )
                    for window in section_windows
                )

                original_max = int(
                    section_original_max.get(
                        task.section_id,
                        0,
                    )
                )

                if original_max < required:

                    reason_code = (
                        "NO_WINDOW_LONG_ENOUGH"
                    )

                    reason_text = (
                        f"Longest safe source window is "
                        f"{original_max} min but task requires "
                        f"{required} min."
                    )

                else:

                    reason_code = (
                        "CAPACITY_USED_BY_HIGHER_PRIORITY_TASKS"
                    )

                    reason_text = (
                        f"Safe windows existed initially, but only "
                        f"{max_remaining} min remains after higher-priority "
                        f"allocations; task requires {required} min."
                    )

            unscheduled_rows.append(
                {
                    "planning_task_id":
                        task.planning_task_id,

                    "planning_task_type":
                        task.planning_task_type,

                    "coordination_group":
                        getattr(
                            task,
                            "coordination_group",
                            "",
                        ),

                    "section_id":
                        task.section_id,

                    "departments_involved":
                        task.departments_involved,

                    "source_systems":
                        task.source_systems,

                    "source_task_ids":
                        task.source_task_ids,

                    "trackease_priority_score":
                        float(
                            task.trackease_priority_score
                        ),

                    "trackease_priority_level":
                        task.trackease_priority_level,

                    "required_minutes":
                        required,

                    "max_remaining_window_minutes":
                        int(
                            max_remaining
                        ),

                    "unscheduled_reason_code":
                        reason_code,

                    "unscheduled_reason":
                        reason_text,

                    "planning_status":
                        "UNSCHEDULED",
                }
            )

            continue

        # -------------------------------------------------------------------
        # Select best feasible candidate.
        # -------------------------------------------------------------------

        candidates.sort(
            key=lambda candidate: (
                candidate["candidate_cost"],
                candidate["window"][
                    "operational_impact_score"
                ],
                candidate["slack_after"],
                candidate["window"][
                    "available_start"
                ],
                candidate["window"][
                    "adjusted_window_id"
                ],
            )
        )

        selected = candidates[0]

        window = selected[
            "window"
        ]

        scheduled_start = int(
            window["available_start"]
        )

        scheduled_end = (
            scheduled_start
            + required
        )

        remaining_after = (
            window["window_end"]
            - scheduled_end
        )

        # Reserve the selected interval.
        window[
            "available_start"
        ] = scheduled_end

        start_day, start_time = (
            weekly_minute_to_label(
                scheduled_start
            )
        )

        end_day, end_time = (
            weekly_minute_to_label(
                scheduled_end
            )
        )

        recommendation_score = max(
            0.0,
            min(
                100.0,
                100.0
                - float(
                    selected[
                        "candidate_cost"
                    ]
                ),
            ),
        )

        scheduled_rows.append(
            {
                "recommendation_id":
                    f"REC-{recommendation_counter:06d}",

                "planning_task_id":
                    task.planning_task_id,

                "planning_task_type":
                    task.planning_task_type,

                "coordination_group":
                    getattr(
                        task,
                        "coordination_group",
                        "",
                    ),

                "section_id":
                    task.section_id,

                "station_a_code":
                    getattr(
                        task,
                        "station_a_code",
                        None,
                    ),

                "station_a_name":
                    getattr(
                        task,
                        "station_a_name",
                        None,
                    ),

                "station_b_code":
                    getattr(
                        task,
                        "station_b_code",
                        None,
                    ),

                "station_b_name":
                    getattr(
                        task,
                        "station_b_name",
                        None,
                    ),

                "departments_involved":
                    task.departments_involved,

                "source_systems":
                    task.source_systems,

                "source_task_ids":
                    task.source_task_ids,

                "task_count":
                    int(
                        getattr(
                            task,
                            "task_count",
                            1,
                        )
                    ),

                "department_count":
                    int(
                        task.department_count
                    ),

                "trackease_priority_score":
                    float(
                        task.trackease_priority_score
                    ),

                "trackease_priority_level":
                    task.trackease_priority_level,

                "required_minutes":
                    required,

                "separate_minutes_total":
                    int(
                        getattr(
                            task,
                            "separate_minutes_total",
                            required,
                        )
                    ),

                "estimated_minutes_saved":
                    int(
                        task.estimated_minutes_saved
                    ),

                "adjusted_window_id":
                    window[
                        "adjusted_window_id"
                    ],

                "source_window_id":
                    window[
                        "source_window_id"
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

                "window_remaining_before":
                    int(
                        selected[
                            "remaining_before"
                        ]
                    ),

                "window_remaining_after":
                    int(
                        remaining_after
                    ),

                "operational_impact_score":
                    round(
                        window[
                            "operational_impact_score"
                        ],
                        2,
                    ),

                "operational_impact_level":
                    window[
                        "operational_impact_level"
                    ],

                "weekly_train_movements":
                    int(
                        window[
                            "weekly_train_movements"
                        ]
                    ),

                "goods_forecast_present":
                    int(
                        window[
                            "goods_forecast_present"
                        ]
                    ),

                "coa_adjusted_window":
                    int(
                        window[
                            "coa_adjusted"
                        ]
                    ),

                "fit_penalty":
                    round(
                        float(
                            selected[
                                "fit_penalty"
                            ]
                        ),
                        2,
                    ),

                "optimizer_selection_cost":
                    round(
                        float(
                            selected[
                                "candidate_cost"
                            ]
                        ),
                        2,
                    ),

                "recommendation_score":
                    round(
                        recommendation_score,
                        2,
                    ),

                "recommendation_explanation":
                    build_recommendation_explanation(
                        task,
                        window,
                        remaining_after,
                    ),

                "approval_status":
                    "PENDING",

                "planning_status":
                    "SCHEDULED",
            }
        )

        recommendation_counter += 1

    # -----------------------------------------------------------------------
    # Build result frames.
    # -----------------------------------------------------------------------

    scheduled = pd.DataFrame(
        scheduled_rows
    )

    unscheduled = pd.DataFrame(
        unscheduled_rows
    )

    # -----------------------------------------------------------------------
    # Post-optimizer quality checks.
    # -----------------------------------------------------------------------

    if not scheduled.empty:

        duplicate_scheduled_tasks = int(
            scheduled[
                "planning_task_id"
            ].duplicated().sum()
        )

        maintenance_overlap_count = (
            count_scheduled_overlaps(
                scheduled
            )
        )

        outside_window_count = int(
            (
                scheduled[
                    "scheduled_end_minute"
                ]
                < scheduled[
                    "scheduled_start_minute"
                ]
            ).sum()
        )

    else:

        duplicate_scheduled_tasks = 0
        maintenance_overlap_count = 0
        outside_window_count = 0

    scheduled_task_ids = set(
        scheduled[
            "planning_task_id"
        ]
        if not scheduled.empty
        else []
    )

    unscheduled_task_ids = set(
        unscheduled[
            "planning_task_id"
        ]
        if not unscheduled.empty
        else []
    )

    duplicated_between_outputs = len(
        scheduled_task_ids
        & unscheduled_task_ids
    )

    accounted_for = (
        len(scheduled)
        + len(unscheduled)
    )

    if accounted_for != len(tasks):
        raise RuntimeError(
            "Optimizer accounting failed: scheduled + unscheduled "
            "does not equal input planning units."
        )

    if (
        duplicate_scheduled_tasks > 0
        or maintenance_overlap_count > 0
        or duplicated_between_outputs > 0
        or outside_window_count > 0
    ):
        raise RuntimeError(
            "Optimizer post-allocation safety checks failed. "
            "Inspect the generated allocations before proceeding."
        )

    # -----------------------------------------------------------------------
    # Sort outputs.
    # -----------------------------------------------------------------------

    if not scheduled.empty:

        scheduled = scheduled.sort_values(
            [
                "scheduled_start_minute",
                "section_id",
                "trackease_priority_score",
                "recommendation_id",
            ],
            ascending=[
                True,
                True,
                False,
                True,
            ],
        ).reset_index(
            drop=True
        )

    if not unscheduled.empty:

        unscheduled = unscheduled.sort_values(
            [
                "trackease_priority_score",
                "required_minutes",
                "planning_task_id",
            ],
            ascending=[
                False,
                False,
                True,
            ],
        ).reset_index(
            drop=True
        )

    # -----------------------------------------------------------------------
    # Save.
    # -----------------------------------------------------------------------

    scheduled.to_csv(
        SCHEDULED_FILE,
        index=False,
    )

    unscheduled.to_csv(
        UNSCHEDULED_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Metrics.
    # -----------------------------------------------------------------------

    scheduled_count = len(
        scheduled
    )

    unscheduled_count = len(
        unscheduled
    )

    scheduling_rate = (
        scheduled_count
        / len(tasks)
        * 100
        if len(tasks) > 0
        else 0
    )

    scheduled_minutes = int(
        scheduled[
            "required_minutes"
        ].sum()
        if not scheduled.empty
        else 0
    )

    coordination_minutes_saved = int(
        scheduled[
            "estimated_minutes_saved"
        ].sum()
        if not scheduled.empty
        else 0
    )

    average_selected_impact = (
        scheduled[
            "operational_impact_score"
        ].mean()
        if not scheduled.empty
        else 0
    )

    average_recommendation_score = (
        scheduled[
            "recommendation_score"
        ].mean()
        if not scheduled.empty
        else 0
    )

    priority_counts = (
        scheduled[
            "trackease_priority_level"
        ]
        .value_counts()
        if not scheduled.empty
        else pd.Series(dtype=int)
    )

    impact_counts = (
        scheduled[
            "operational_impact_level"
        ]
        .value_counts()
        if not scheduled.empty
        else pd.Series(dtype=int)
    )

    reason_counts = (
        unscheduled[
            "unscheduled_reason_code"
        ]
        .value_counts()
        if not unscheduled.empty
        else pd.Series(dtype=int)
    )

    coordinated_scheduled = int(
        (
            scheduled[
                "planning_task_type"
            ]
            == "COORDINATED"
        ).sum()
        if not scheduled.empty
        else 0
    )

    # -----------------------------------------------------------------------
    # Report.
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Impact-Aware Weekly Block Optimizer V2 Report",
        "=" * 72,
        "",
        "INPUT",
        "-" * 72,
        f"Planning units                  : {len(tasks):,}",
        f"Scored safe windows             : {len(windows):,}",
        "",
        "OPTIMIZATION RESULT",
        "-" * 72,
        f"Scheduled planning units        : {scheduled_count:,}",
        f"Unscheduled planning units      : {unscheduled_count:,}",
        f"Scheduling feasibility          : {scheduling_rate:.2f}%",
        f"Scheduled maintenance minutes   : {scheduled_minutes:,}",
        f"Coordinated units scheduled     : {coordinated_scheduled:,}",
        f"Coordination minutes preserved  : {coordination_minutes_saved:,}",
        f"Average selected impact         : {average_selected_impact:.2f}/100",
        f"Average recommendation score    : {average_recommendation_score:.2f}/100",
        "",
        "SCHEDULED PRIORITIES",
        "-" * 72,
    ]

    for level in [
        "Critical",
        "High",
        "Medium",
        "Low",
    ]:

        report.append(
            f"{level:<20} "
            f"{int(priority_counts.get(level, 0)):>10,}"
        )

    report.extend(
        [
            "",
            "SELECTED OPERATIONAL IMPACT",
            "-" * 72,
        ]
    )

    for level in [
        "Low",
        "Moderate",
        "High",
        "Very High",
    ]:

        report.append(
            f"{level:<20} "
            f"{int(impact_counts.get(level, 0)):>10,}"
        )

    report.extend(
        [
            "",
            "UNSCHEDULED REASONS",
            "-" * 72,
        ]
    )

    if reason_counts.empty:
        report.append(
            "None"
        )
    else:
        for reason, count in reason_counts.items():
            report.append(
                f"{reason:<42} {count:>8,}"
            )

    report.extend(
        [
            "",
            "SAFETY / CONSISTENCY CHECKS",
            "-" * 72,
            f"Duplicate scheduled task IDs    : {duplicate_scheduled_tasks:,}",
            f"Maintenance allocation overlaps : {maintenance_overlap_count:,}",
            f"Task in both outputs             : {duplicated_between_outputs:,}",
            f"Invalid allocation boundaries    : {outside_window_count:,}",
            f"Tasks accounted for              : {accounted_for:,}/{len(tasks):,}",
            "",
            "SELECTION STRATEGY",
            "-" * 72,
            (
                "Task ordering: higher TrackEase maintenance priority first; "
                "coordination benefit and required duration are tie-breakers."
            ),
            (
                f"Candidate cost: {IMPACT_WEIGHT:.0%} operational impact + "
                f"{FIT_WEIGHT:.0%} fit/slack penalty."
            ),
            (
                "Lower candidate cost is preferred. Allocated maintenance time "
                "is reserved immediately so later recommendations cannot overlap."
            ),
            "",
            "IMPORTANT LIMITATION",
            "-" * 72,
            (
                "This output is an AI-assisted/prototype planning recommendation. "
                "It does not constitute an official railway block sanction."
            ),
            (
                "Final recommendations remain subject to railway operating rules, "
                "engineering validation and human approval."
            ),
            "",
            "NEXT STAGE",
            "-" * 72,
            (
                "Validate Optimizer V2 allocations, then build explicit weekly "
                "and monthly plan views plus approval/explanation workflow."
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
    print("WEEKLY BLOCK OPTIMIZATION V2 COMPLETE")
    print("=" * 72)

    print(
        f"\nPlanning units : {len(tasks):,}"
    )

    print(
        f"Scheduled      : {scheduled_count:,}"
    )

    print(
        f"Unscheduled    : {unscheduled_count:,}"
    )

    print(
        f"Feasibility    : {scheduling_rate:.2f}%"
    )

    print(
        f"\nScheduled maintenance : {scheduled_minutes:,} min"
    )

    print(
        f"Coordination saving   : {coordination_minutes_saved:,} min"
    )

    print(
        f"Average block impact  : {average_selected_impact:.2f}/100"
    )

    print(
        f"Recommendation score  : {average_recommendation_score:.2f}/100"
    )

    print("\nSelected impact levels:")

    for level in [
        "Low",
        "Moderate",
        "High",
        "Very High",
    ]:

        print(
            f"  {level:<10} "
            f"{int(impact_counts.get(level, 0)):>8,}"
        )

    print("\nQuality checks:")
    print(
        f"  Maintenance overlaps : {maintenance_overlap_count:,}"
    )
    print(
        f"  Duplicate task IDs   : {duplicate_scheduled_tasks:,}"
    )
    print(
        f"  Tasks accounted for  : {accounted_for:,}/{len(tasks):,}"
    )

    if not unscheduled.empty:

        print("\nUnscheduled reasons:")

        for reason, count in reason_counts.items():

            print(
                f"  {reason:<40} "
                f"{count:>6,}"
            )

    print("\nOutputs:")
    print(
        f"  {SCHEDULED_FILE}"
    )
    print(
        f"  {UNSCHEDULED_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nTrackEase now produces priority-aware, coordination-aware, "
        "operational-impact-aware weekly block recommendations."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    optimize_weekly_blocks()
