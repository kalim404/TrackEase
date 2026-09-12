"""
TrackEase - Optimizer V2 Validation

Purpose:
    Independently validate the recommendations produced by the
    Impact-Aware Weekly Block Optimizer V2 before weekly/monthly
    presentation layers are built.

Inputs:
    data/processed/coordinated_planning_tasks.csv
    data/processed/optimized_weekly_blocks.csv
    data/processed/optimizer_v2_unscheduled.csv
    data/processed/scored_block_windows.csv
    data/processed/weekly_section_movements.csv
    data/processed/coa_goods_forecast.csv

Output:
    data/processed/optimizer_v2_validation_report.txt

Checks:
    - Every planning unit is accounted for exactly once.
    - Scheduled and unscheduled task IDs are unique and disjoint.
    - Scheduled task section matches the original planning task.
    - Scheduled duration matches required maintenance duration.
    - Every recommendation lies fully inside its selected safe window.
    - Selected-window section and impact metadata match.
    - Maintenance recommendations do not overlap one another.
    - Recommendations do not overlap scheduled train movement.
    - Recommendations do not overlap buffered prototype COA goods occupancy.
    - Unscheduled reason codes are consistent with source window availability.

Important:
    This validator does not modify planning outputs.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths / configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TASKS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coordinated_planning_tasks.csv"
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

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "scored_block_windows.csv"
)

MOVEMENTS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_section_movements.csv"
)

FORECAST_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coa_goods_forecast.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "optimizer_v2_validation_report.txt"
)

MINUTES_PER_WEEK = 10080
GOODS_BUFFER_MINUTES = 10


# ---------------------------------------------------------------------------
# Validation collector
# ---------------------------------------------------------------------------

class ValidationResults:
    """Collect PASS / WARNING / ERROR results."""

    def __init__(self):
        self.records = []

    def passed(self, name, detail):
        self.records.append(
            ("PASS", name, detail)
        )

    def warning(self, name, detail):
        self.records.append(
            ("WARNING", name, detail)
        )

    def error(self, name, detail):
        self.records.append(
            ("ERROR", name, detail)
        )

    @property
    def pass_count(self):
        return sum(
            level == "PASS"
            for level, _, _ in self.records
        )

    @property
    def warning_count(self):
        return sum(
            level == "WARNING"
            for level, _, _ in self.records
        )

    @property
    def error_count(self):
        return sum(
            level == "ERROR"
            for level, _, _ in self.records
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_columns(
    df,
    required,
    dataset_name,
):
    """Raise a clear error if an input schema is incomplete."""

    missing = (
        set(required)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(
                sorted(missing)
            )
        )


def cyclic_intervals(start, end):
    """
    Convert a possibly week-crossing interval into one or two intervals
    inside [0, MINUTES_PER_WEEK].
    """

    start = int(start)
    end = int(end)

    if end < start:
        end += MINUTES_PER_WEEK

    intervals = []

    for shift in (
        -MINUTES_PER_WEEK,
        0,
        MINUTES_PER_WEEK,
    ):
        shifted_start = start + shift
        shifted_end = end + shift

        if (
            shifted_end <= 0
            or shifted_start >= MINUTES_PER_WEEK
        ):
            continue

        clipped_start = max(
            0,
            shifted_start,
        )

        clipped_end = min(
            MINUTES_PER_WEEK,
            shifted_end,
        )

        if clipped_end > clipped_start:
            intervals.append(
                (
                    int(clipped_start),
                    int(clipped_end),
                )
            )

    return intervals


def intervals_overlap(
    a_start,
    a_end,
    b_start,
    b_end,
):
    """Return True when half-open intervals overlap."""

    return (
        a_start < b_end
        and b_start < a_end
    )


def count_maintenance_overlaps(scheduled):
    """Count maintenance allocations overlapping on the same section."""

    overlap_count = 0

    for _, group in scheduled.groupby(
        "section_id",
        sort=False,
    ):

        ordered = group.sort_values(
            "scheduled_start_minute"
        )

        previous_end = None

        for row in ordered.itertuples():

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
                overlap_count += 1

            previous_end = max(
                previous_end or end,
                end,
            )

    return overlap_count


def build_train_interval_map(movements):
    """Build recurring weekly train-occupancy intervals by section."""

    result = {}

    for row in movements.itertuples():

        start = pd.to_numeric(
            row.weekly_departure_minute,
            errors="coerce",
        )

        end = pd.to_numeric(
            row.weekly_arrival_minute,
            errors="coerce",
        )

        if pd.isna(start) or pd.isna(end):
            continue

        result.setdefault(
            row.section_id,
            []
        ).extend(
            cyclic_intervals(
                int(start),
                int(end),
            )
        )

    return result


def build_goods_interval_map(forecasts):
    """Build buffered recurring COA forecast occupancy by section."""

    result = {}

    for row in forecasts.itertuples():

        start = (
            int(row.expected_start_minute)
            - GOODS_BUFFER_MINUTES
        )

        end = (
            int(row.expected_end_minute)
            + GOODS_BUFFER_MINUTES
        )

        result.setdefault(
            row.section_id,
            []
        ).extend(
            cyclic_intervals(
                start,
                end,
            )
        )

    return result


def count_external_conflicts(
    scheduled,
    interval_map,
):
    """Count scheduled recommendations overlapping an external occupancy map."""

    conflicts = 0

    for row in scheduled.itertuples():

        start = int(
            row.scheduled_start_minute
        )

        end = int(
            row.scheduled_end_minute
        )

        blocked = interval_map.get(
            row.section_id,
            [],
        )

        for blocked_start, blocked_end in blocked:

            if intervals_overlap(
                start,
                end,
                blocked_start,
                blocked_end,
            ):
                conflicts += 1
                break

    return conflicts


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate_optimizer_v2():
    """Validate Optimizer V2 outputs independently."""

    print("=" * 72)
    print("TrackEase - Optimizer V2 Validation")
    print("=" * 72)

    results = ValidationResults()

    required_files = [
        (
            TASKS_FILE,
            "Planning tasks",
        ),
        (
            SCHEDULED_FILE,
            "Optimized weekly blocks",
        ),
        (
            UNSCHEDULED_FILE,
            "Optimizer unscheduled tasks",
        ),
        (
            WINDOWS_FILE,
            "Scored safe windows",
        ),
        (
            MOVEMENTS_FILE,
            "Weekly movements",
        ),
        (
            FORECAST_FILE,
            "COA goods forecast",
        ),
    ]

    for file_path, label in required_files:

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

    scheduled = pd.read_csv(
        SCHEDULED_FILE
    )

    unscheduled = pd.read_csv(
        UNSCHEDULED_FILE
    )

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    movements = pd.read_csv(
        MOVEMENTS_FILE
    )

    forecasts = pd.read_csv(
        FORECAST_FILE
    )

    print("\nLoaded:")
    print(
        f"  Planning units     : {len(tasks):,}"
    )
    print(
        f"  Scheduled          : {len(scheduled):,}"
    )
    print(
        f"  Unscheduled        : {len(unscheduled):,}"
    )
    print(
        f"  Scored windows     : {len(windows):,}"
    )
    print(
        f"  Weekly movements   : {len(movements):,}"
    )
    print(
        f"  COA forecasts      : {len(forecasts):,}"
    )

    require_columns(
        tasks,
        {
            "planning_task_id",
            "section_id",
            "required_minutes",
            "trackease_priority_score",
            "trackease_priority_level",
        },
        "Planning tasks",
    )

    require_columns(
        scheduled,
        {
            "recommendation_id",
            "planning_task_id",
            "section_id",
            "required_minutes",
            "adjusted_window_id",
            "scheduled_start_minute",
            "scheduled_end_minute",
            "operational_impact_score",
            "approval_status",
        },
        "Optimized weekly blocks",
    )

    require_columns(
        unscheduled,
        {
            "planning_task_id",
            "section_id",
            "required_minutes",
            "unscheduled_reason_code",
        },
        "Optimizer unscheduled tasks",
    )

    require_columns(
        windows,
        {
            "adjusted_window_id",
            "section_id",
            "window_start_minute",
            "window_end_minute",
            "duration_minutes",
            "operational_impact_score",
        },
        "Scored safe windows",
    )

    require_columns(
        movements,
        {
            "section_id",
            "weekly_departure_minute",
            "weekly_arrival_minute",
        },
        "Weekly movements",
    )

    require_columns(
        forecasts,
        {
            "section_id",
            "expected_start_minute",
            "expected_end_minute",
        },
        "COA goods forecast",
    )

    # -----------------------------------------------------------------------
    # 1. Task accounting.
    # -----------------------------------------------------------------------

    task_ids = set(
        tasks[
            "planning_task_id"
        ].astype(str)
    )

    scheduled_ids = (
        scheduled[
            "planning_task_id"
        ]
        .astype(str)
    )

    unscheduled_ids = (
        unscheduled[
            "planning_task_id"
        ]
        .astype(str)
    )

    duplicate_scheduled = int(
        scheduled_ids.duplicated().sum()
    )

    duplicate_unscheduled = int(
        unscheduled_ids.duplicated().sum()
    )

    overlap_outputs = (
        set(scheduled_ids)
        & set(unscheduled_ids)
    )

    output_ids = (
        set(scheduled_ids)
        | set(unscheduled_ids)
    )

    missing_task_ids = (
        task_ids
        - output_ids
    )

    unknown_output_ids = (
        output_ids
        - task_ids
    )

    if duplicate_scheduled == 0:
        results.passed(
            "Scheduled task uniqueness",
            "No planning task is scheduled twice.",
        )
    else:
        results.error(
            "Scheduled task uniqueness",
            f"{duplicate_scheduled:,} duplicate scheduled task IDs found.",
        )

    if duplicate_unscheduled == 0:
        results.passed(
            "Unscheduled task uniqueness",
            "No planning task appears twice in the unscheduled output.",
        )
    else:
        results.error(
            "Unscheduled task uniqueness",
            f"{duplicate_unscheduled:,} duplicate unscheduled task IDs found.",
        )

    if not overlap_outputs:
        results.passed(
            "Scheduled/unscheduled separation",
            "No task appears in both outputs.",
        )
    else:
        results.error(
            "Scheduled/unscheduled separation",
            f"{len(overlap_outputs):,} tasks appear in both outputs.",
        )

    if (
        not missing_task_ids
        and not unknown_output_ids
    ):
        results.passed(
            "Planning-unit accounting",
            f"All {len(tasks):,} input planning units are accounted for exactly once.",
        )
    else:
        results.error(
            "Planning-unit accounting",
            (
                f"Missing input tasks: {len(missing_task_ids):,}; "
                f"unknown output tasks: {len(unknown_output_ids):,}."
            ),
        )

    # -----------------------------------------------------------------------
    # 2. Match recommendations back to original tasks.
    # -----------------------------------------------------------------------

    task_reference = tasks[
        [
            "planning_task_id",
            "section_id",
            "required_minutes",
            "trackease_priority_score",
            "trackease_priority_level",
        ]
    ].rename(
        columns={
            "section_id":
                "task_section_id",
            "required_minutes":
                "task_required_minutes",
            "trackease_priority_score":
                "task_priority_score",
            "trackease_priority_level":
                "task_priority_level",
        }
    )

    checked = scheduled.merge(
        task_reference,
        on="planning_task_id",
        how="left",
        validate="one_to_one",
    )

    missing_task_reference = int(
        checked[
            "task_section_id"
        ].isna().sum()
    )

    if missing_task_reference == 0:
        results.passed(
            "Scheduled task references",
            "Every recommendation maps back to an original planning unit.",
        )
    else:
        results.error(
            "Scheduled task references",
            f"{missing_task_reference:,} recommendations lack a source planning task.",
        )

    section_mismatch = int(
        (
            checked[
                "section_id"
            ].astype(str)
            != checked[
                "task_section_id"
            ].astype(str)
        ).sum()
    )

    if section_mismatch == 0:
        results.passed(
            "Scheduled section mapping",
            "Every recommendation remains on the task's railway section.",
        )
    else:
        results.error(
            "Scheduled section mapping",
            f"{section_mismatch:,} recommendations use the wrong section.",
        )

    stored_required = pd.to_numeric(
        checked[
            "required_minutes"
        ],
        errors="coerce",
    )

    original_required = pd.to_numeric(
        checked[
            "task_required_minutes"
        ],
        errors="coerce",
    )

    required_mismatch = int(
        (
            stored_required
            != original_required
        ).sum()
    )

    if required_mismatch == 0:
        results.passed(
            "Required-duration preservation",
            "Optimizer preserved every task's required maintenance duration.",
        )
    else:
        results.error(
            "Required-duration preservation",
            f"{required_mismatch:,} task durations changed during optimization.",
        )

    allocation_duration = (
        pd.to_numeric(
            checked[
                "scheduled_end_minute"
            ],
            errors="coerce",
        )
        - pd.to_numeric(
            checked[
                "scheduled_start_minute"
            ],
            errors="coerce",
        )
    )

    duration_mismatch = int(
        (
            allocation_duration
            != stored_required
        ).sum()
    )

    if duration_mismatch == 0:
        results.passed(
            "Allocation duration",
            "Every scheduled block duration equals its task requirement.",
        )
    else:
        results.error(
            "Allocation duration",
            f"{duration_mismatch:,} scheduled durations are incorrect.",
        )

    # -----------------------------------------------------------------------
    # 3. Validate selected source windows.
    # -----------------------------------------------------------------------

    window_reference = windows[
        [
            "adjusted_window_id",
            "section_id",
            "window_start_minute",
            "window_end_minute",
            "operational_impact_score",
        ]
    ].rename(
        columns={
            "section_id":
                "window_section_id",
            "operational_impact_score":
                "window_impact_score",
        }
    )

    checked = checked.merge(
        window_reference,
        on="adjusted_window_id",
        how="left",
        validate="many_to_one",
    )

    missing_window_reference = int(
        checked[
            "window_section_id"
        ].isna().sum()
    )

    if missing_window_reference == 0:
        results.passed(
            "Selected-window references",
            "Every recommendation references a valid scored safe window.",
        )
    else:
        results.error(
            "Selected-window references",
            f"{missing_window_reference:,} recommendations reference missing windows.",
        )

    window_section_mismatch = int(
        (
            checked[
                "section_id"
            ].astype(str)
            != checked[
                "window_section_id"
            ].astype(str)
        ).sum()
    )

    if window_section_mismatch == 0:
        results.passed(
            "Window section consistency",
            "Every selected window belongs to the same section as the task.",
        )
    else:
        results.error(
            "Window section consistency",
            f"{window_section_mismatch:,} selected windows are on the wrong section.",
        )

    starts = pd.to_numeric(
        checked[
            "scheduled_start_minute"
        ],
        errors="coerce",
    )

    ends = pd.to_numeric(
        checked[
            "scheduled_end_minute"
        ],
        errors="coerce",
    )

    window_starts = pd.to_numeric(
        checked[
            "window_start_minute"
        ],
        errors="coerce",
    )

    window_ends = pd.to_numeric(
        checked[
            "window_end_minute"
        ],
        errors="coerce",
    )

    outside_window = int(
        (
            (starts < window_starts)
            | (ends > window_ends)
            | (ends <= starts)
        ).sum()
    )

    if outside_window == 0:
        results.passed(
            "Recommendation boundaries",
            "Every scheduled allocation lies fully inside its selected safe window.",
        )
    else:
        results.error(
            "Recommendation boundaries",
            f"{outside_window:,} recommendations exceed selected window boundaries.",
        )

    recommendation_impact = pd.to_numeric(
        checked[
            "operational_impact_score"
        ],
        errors="coerce",
    )

    source_impact = pd.to_numeric(
        checked[
            "window_impact_score"
        ],
        errors="coerce",
    )

    impact_mismatch = int(
        (
            (recommendation_impact - source_impact).abs()
            > 0.01
        ).sum()
    )

    if impact_mismatch == 0:
        results.passed(
            "Operational-impact traceability",
            "Recommendation impact values match their source windows.",
        )
    else:
        results.error(
            "Operational-impact traceability",
            f"{impact_mismatch:,} recommendations have mismatched impact scores.",
        )

    # -----------------------------------------------------------------------
    # 4. Maintenance-to-maintenance overlap.
    # -----------------------------------------------------------------------

    maintenance_overlaps = (
        count_maintenance_overlaps(
            scheduled
        )
    )

    if maintenance_overlaps == 0:
        results.passed(
            "Maintenance allocation conflicts",
            "No optimized maintenance recommendations overlap on a section.",
        )
    else:
        results.error(
            "Maintenance allocation conflicts",
            f"{maintenance_overlaps:,} maintenance overlaps found.",
        )

    # -----------------------------------------------------------------------
    # 5. Direct scheduled-train conflict validation.
    # -----------------------------------------------------------------------

    print(
        "\nChecking optimized blocks directly against scheduled train movements..."
    )

    train_interval_map = (
        build_train_interval_map(
            movements
        )
    )

    train_conflicts = (
        count_external_conflicts(
            scheduled,
            train_interval_map,
        )
    )

    if train_conflicts == 0:
        results.passed(
            "Scheduled-train conflict validation",
            "No optimized block overlaps scheduled section movement.",
        )
    else:
        results.error(
            "Scheduled-train conflict validation",
            f"{train_conflicts:,} optimized blocks overlap scheduled train movement.",
        )

    # -----------------------------------------------------------------------
    # 6. Direct COA goods conflict validation.
    # -----------------------------------------------------------------------

    print(
        "Checking optimized blocks directly against buffered COA goods forecasts..."
    )

    goods_interval_map = (
        build_goods_interval_map(
            forecasts
        )
    )

    goods_conflicts = (
        count_external_conflicts(
            scheduled,
            goods_interval_map,
        )
    )

    if goods_conflicts == 0:
        results.passed(
            "COA goods conflict validation",
            "No optimized block overlaps buffered prototype goods occupancy.",
        )
    else:
        results.error(
            "COA goods conflict validation",
            f"{goods_conflicts:,} optimized blocks overlap buffered goods occupancy.",
        )

    # -----------------------------------------------------------------------
    # 7. Approval state.
    # -----------------------------------------------------------------------

    non_pending = int(
        (
            scheduled[
                "approval_status"
            ].astype(str)
            != "PENDING"
        ).sum()
    )

    if non_pending == 0:
        results.passed(
            "Human approval state",
            "All recommendations remain PENDING for human review.",
        )
    else:
        results.warning(
            "Human approval state",
            f"{non_pending:,} recommendations are not in PENDING state.",
        )

    # -----------------------------------------------------------------------
    # 8. Validate unscheduled reason semantics.
    # -----------------------------------------------------------------------

    windows_by_section = {
        section_id: group
        for section_id, group
        in windows.groupby(
            "section_id",
            sort=False,
        )
    }

    reason_errors = 0

    for row in unscheduled.itertuples():

        section_windows = windows_by_section.get(
            row.section_id
        )

        required = int(
            row.required_minutes
        )

        reason = str(
            row.unscheduled_reason_code
        )

        if reason == "NO_SAFE_WINDOW_ON_SECTION":

            if (
                section_windows is not None
                and len(section_windows) > 0
            ):
                reason_errors += 1

        elif reason == "NO_WINDOW_LONG_ENOUGH":

            if section_windows is None:
                reason_errors += 1
                continue

            maximum = int(
                section_windows[
                    "duration_minutes"
                ].max()
            )

            if maximum >= required:
                reason_errors += 1

        elif reason == "CAPACITY_USED_BY_HIGHER_PRIORITY_TASKS":

            # This reason is allocation-state dependent. We only verify
            # that at least one source window could originally fit the task.
            if section_windows is None:
                reason_errors += 1
                continue

            maximum = int(
                section_windows[
                    "duration_minutes"
                ].max()
            )

            if maximum < required:
                reason_errors += 1

        else:
            reason_errors += 1

    if reason_errors == 0:
        results.passed(
            "Unscheduled reason consistency",
            "All unscheduled reason codes agree with source-window feasibility.",
        )
    else:
        results.error(
            "Unscheduled reason consistency",
            f"{reason_errors:,} unscheduled reason records are inconsistent.",
        )

    # -----------------------------------------------------------------------
    # 9. Surface high-priority unscheduled tasks as a planning warning.
    # -----------------------------------------------------------------------

    high_priority_unscheduled = int(
        unscheduled[
            "trackease_priority_level"
        ]
        .isin(
            [
                "Critical",
                "High",
            ]
        )
        .sum()
    )

    critical_unscheduled = int(
        (
            unscheduled[
                "trackease_priority_level"
            ]
            == "Critical"
        ).sum()
    )

    if high_priority_unscheduled == 0:
        results.passed(
            "High-priority feasibility",
            "All Critical and High planning units received a safe recommendation.",
        )
    else:
        results.warning(
            "High-priority feasibility",
            (
                f"{high_priority_unscheduled:,} Critical/High units remain "
                f"unscheduled, including {critical_unscheduled:,} Critical. "
                "These should be escalated or moved into alternate/monthly planning."
            ),
        )

    # -----------------------------------------------------------------------
    # Final status.
    # -----------------------------------------------------------------------

    ready = (
        results.error_count
        == 0
    )

    status = (
        "OPTIMIZER V2 VALIDATED"
        if ready
        else "OPTIMIZER V2 VALIDATION FAILED"
    )

    report = [
        "=" * 72,
        "TrackEase Optimizer V2 Validation Report",
        "=" * 72,
        "",
        f"Planning units             : {len(tasks):,}",
        f"Scheduled recommendations  : {len(scheduled):,}",
        f"Unscheduled planning units : {len(unscheduled):,}",
        "",
        "VALIDATION RESULTS",
        "-" * 72,
    ]

    for level, name, detail in results.records:

        report.append(
            f"[{level}] {name}"
        )

        report.append(
            f"    {detail}"
        )

    report.extend(
        [
            "",
            "DIRECT CONFLICT CHECKS",
            "-" * 72,
            f"Maintenance overlaps       : {maintenance_overlaps:,}",
            f"Scheduled-train conflicts  : {train_conflicts:,}",
            f"COA goods conflicts        : {goods_conflicts:,}",
            "",
            "UNSCHEDULED ESCALATION",
            "-" * 72,
            f"Critical unscheduled       : {critical_unscheduled:,}",
            f"Critical/High unscheduled  : {high_priority_unscheduled:,}",
            "",
            "SUMMARY",
            "-" * 72,
            f"Passed checks              : {results.pass_count}",
            f"Warnings                   : {results.warning_count}",
            f"Errors                     : {results.error_count}",
            "",
            status,
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("OPTIMIZER V2 VALIDATION COMPLETE")
    print("=" * 72)

    print(
        f"\nPassed checks : {results.pass_count}"
    )

    print(
        f"Warnings      : {results.warning_count}"
    )

    print(
        f"Errors        : {results.error_count}"
    )

    print("\nDirect conflicts:")
    print(
        f"  Maintenance overlaps : {maintenance_overlaps:,}"
    )
    print(
        f"  Train conflicts       : {train_conflicts:,}"
    )
    print(
        f"  Goods conflicts       : {goods_conflicts:,}"
    )

    print("\nUnscheduled escalation:")
    print(
        f"  Critical             : {critical_unscheduled:,}"
    )
    print(
        f"  Critical + High      : {high_priority_unscheduled:,}"
    )

    print("\nStatus:")
    print(
        f"  {status}"
    )

    print("\nReport:")
    print(
        f"  {REPORT_FILE}"
    )

    if ready:
        print(
            "\nOptimizer V2 recommendations are internally consistent "
            "and safe against the current timetable/COA prototype inputs."
        )
    else:
        print(
            "\nDo not build the final weekly/monthly presentation layer "
            "until all validation errors are resolved."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    validate_optimizer_v2()
