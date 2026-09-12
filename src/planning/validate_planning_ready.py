"""
TrackEase - Final Planning Readiness Validation

Purpose:
    Validate all major planning datasets before Optimizer V2 is allowed
    to generate final weekly/monthly block recommendations.

Inputs:
    data/processed/coordinated_planning_tasks.csv
    data/processed/adjusted_block_windows.csv
    data/processed/railway_sections.csv
    data/processed/weekly_section_movements.csv
    data/processed/coa_goods_forecast.csv

Output:
    data/processed/planning_readiness_report.txt

Checks:
    - Required schemas
    - Unique IDs
    - Valid section references
    - Valid durations
    - Valid priority scores
    - Valid weekly-minute boundaries
    - Tasks with available planning windows
    - No overlap with scheduled train movements
    - No overlap with buffered prototype goods forecasts

This script does NOT modify planning data.
"""

from pathlib import Path

import numpy as np
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
    / "adjusted_block_windows.csv"
)

SECTIONS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "railway_sections.csv"
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
    / "planning_readiness_report.txt"
)


MINUTES_PER_WEEK = 10080
MIN_BLOCK_MINUTES = 30
GOODS_BUFFER_MINUTES = 10


# ---------------------------------------------------------------------------
# Validation collector
# ---------------------------------------------------------------------------

class ValidationResults:
    """Collect PASS / WARNING / ERROR validation results."""

    def __init__(self):
        self.records = []

    def pass_check(self, name, detail):
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
    def errors(self):
        return sum(
            level == "ERROR"
            for level, _, _ in self.records
        )

    @property
    def warnings(self):
        return sum(
            level == "WARNING"
            for level, _, _ in self.records
        )

    @property
    def passes(self):
        return sum(
            level == "PASS"
            for level, _, _ in self.records
        )


# ---------------------------------------------------------------------------
# Schema helper
# ---------------------------------------------------------------------------

def check_required_columns(
    df,
    required_columns,
    dataset_name,
    results,
):
    """Validate dataset schema."""

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:

        results.error(
            f"{dataset_name} schema",
            "Missing columns: "
            + ", ".join(
                sorted(missing)
            ),
        )

        return False

    results.pass_check(
        f"{dataset_name} schema",
        "All required columns present.",
    )

    return True


# ---------------------------------------------------------------------------
# Weekly movement overlap check
# ---------------------------------------------------------------------------

def count_train_overlaps(
    windows,
    movements,
):
    """
    Count adjusted maintenance windows that overlap scheduled
    section movements.

    The search is performed section-by-section using sorted arrays.
    """

    overlap_count = 0

    movement_groups = {
        section_id: group
        for section_id, group
        in movements.groupby(
            "section_id",
            sort=False,
        )
    }

    for section_id, window_group in windows.groupby(
        "section_id",
        sort=False,
    ):

        movement_group = movement_groups.get(
            section_id
        )

        if movement_group is None:
            continue

        starts = pd.to_numeric(
            movement_group[
                "weekly_departure_minute"
            ],
            errors="coerce",
        ).to_numpy()

        ends = pd.to_numeric(
            movement_group[
                "weekly_arrival_minute"
            ],
            errors="coerce",
        ).to_numpy()

        valid = (
            ~np.isnan(starts)
            & ~np.isnan(ends)
        )

        starts = starts[valid].astype(int)
        ends = ends[valid].astype(int)

        if len(starts) == 0:
            continue

        # ---------------------------------------------------------------
        # Expand Sunday -> Monday crossing movements
        # ---------------------------------------------------------------

        crossing = ends < starts

        interval_starts = []
        interval_ends = []

        # Normal / first part of crossing movement.
        first_ends = np.where(
            crossing,
            MINUTES_PER_WEEK,
            ends,
        )

        interval_starts.append(
            starts
        )

        interval_ends.append(
            first_ends
        )

        # Second portion after Monday 00:00.
        if crossing.any():

            interval_starts.append(
                np.zeros(
                    int(crossing.sum()),
                    dtype=int,
                )
            )

            interval_ends.append(
                ends[crossing]
            )

        starts_all = np.concatenate(
            interval_starts
        )

        ends_all = np.concatenate(
            interval_ends
        )

        order = np.argsort(
            starts_all
        )

        starts_all = starts_all[order]
        ends_all = ends_all[order]

        # Prefix maximum end allows quick overlap checks.
        prefix_max_end = (
            np.maximum.accumulate(
                ends_all
            )
        )

        window_starts = pd.to_numeric(
            window_group[
                "window_start_minute"
            ],
            errors="coerce",
        ).to_numpy(dtype=int)

        window_ends = pd.to_numeric(
            window_group[
                "window_end_minute"
            ],
            errors="coerce",
        ).to_numpy(dtype=int)

        indices = (
            np.searchsorted(
                starts_all,
                window_ends,
                side="left",
            )
            - 1
        )

        candidate = indices >= 0

        overlaps = np.zeros(
            len(window_starts),
            dtype=bool,
        )

        overlaps[candidate] = (
            prefix_max_end[
                indices[candidate]
            ]
            > window_starts[candidate]
        )

        overlap_count += int(
            overlaps.sum()
        )

    return overlap_count


# ---------------------------------------------------------------------------
# COA forecast overlap check
# ---------------------------------------------------------------------------

def build_forecast_intervals(forecasts):
    """
    Build buffered forecast occupancy intervals by railway section.
    """

    forecast_map = {}

    for row in forecasts.itertuples():

        start = (
            int(row.expected_start_minute)
            - GOODS_BUFFER_MINUTES
        )

        end = (
            int(row.expected_end_minute)
            + GOODS_BUFFER_MINUTES
        )

        intervals = []

        # ---------------------------------------------------------------
        # Handle previous-week overlap
        # ---------------------------------------------------------------

        if start < 0:

            intervals.append(
                (
                    0,
                    min(
                        end,
                        MINUTES_PER_WEEK,
                    ),
                )
            )

            intervals.append(
                (
                    MINUTES_PER_WEEK
                    + start,
                    MINUTES_PER_WEEK,
                )
            )

        # ---------------------------------------------------------------
        # Sunday -> Monday crossing
        # ---------------------------------------------------------------

        elif end > MINUTES_PER_WEEK:

            intervals.append(
                (
                    start,
                    MINUTES_PER_WEEK,
                )
            )

            intervals.append(
                (
                    0,
                    end
                    - MINUTES_PER_WEEK,
                )
            )

        else:

            intervals.append(
                (
                    start,
                    end,
                )
            )

        forecast_map.setdefault(
            row.section_id,
            []
        ).extend(
            intervals
        )

    return forecast_map


def count_goods_overlaps(
    windows,
    forecasts,
):
    """Count adjusted windows still overlapping COA forecast occupancy."""

    forecast_map = (
        build_forecast_intervals(
            forecasts
        )
    )

    overlap_count = 0

    for section_id, window_group in windows.groupby(
        "section_id",
        sort=False,
    ):

        intervals = forecast_map.get(
            section_id
        )

        if not intervals:
            continue

        for window in window_group.itertuples():

            start = int(
                window.window_start_minute
            )

            end = int(
                window.window_end_minute
            )

            for blocked_start, blocked_end in intervals:

                if (
                    blocked_start < end
                    and blocked_end > start
                ):

                    overlap_count += 1
                    break

    return overlap_count


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate_planning_ready():
    """Validate the complete TrackEase planning layer."""

    print("=" * 72)
    print("TrackEase - Planning Readiness Validation")
    print("=" * 72)

    results = ValidationResults()

    # -----------------------------------------------------------------------
    # Check files
    # -----------------------------------------------------------------------

    required_files = [
        (
            TASKS_FILE,
            "Coordinated planning tasks",
        ),
        (
            WINDOWS_FILE,
            "Adjusted block windows",
        ),
        (
            SECTIONS_FILE,
            "Railway sections",
        ),
        (
            MOVEMENTS_FILE,
            "Weekly section movements",
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

            results.error(
                f"{label} file",
                f"File missing: {file_path}",
            )

            print("  ✗ Missing")

        else:

            results.pass_check(
                f"{label} file",
                "File found.",
            )

            print("  ✓ Found")

    if results.errors:

        raise FileNotFoundError(
            "Required planning files are missing."
        )

    # -----------------------------------------------------------------------
    # Load datasets
    # -----------------------------------------------------------------------

    tasks = pd.read_csv(
        TASKS_FILE
    )

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    sections = pd.read_csv(
        SECTIONS_FILE
    )

    movements = pd.read_csv(
        MOVEMENTS_FILE
    )

    forecasts = pd.read_csv(
        FORECAST_FILE
    )

    print("\nLoaded:")
    print(
        f"  Planning units  : {len(tasks):,}"
    )
    print(
        f"  Adjusted windows: {len(windows):,}"
    )
    print(
        f"  Railway sections: {len(sections):,}"
    )
    print(
        f"  Weekly movements: {len(movements):,}"
    )
    print(
        f"  COA forecasts   : {len(forecasts):,}"
    )

    # -----------------------------------------------------------------------
    # Schema checks
    # -----------------------------------------------------------------------

    check_required_columns(
        tasks,
        {
            "planning_task_id",
            "section_id",
            "required_minutes",
            "trackease_priority_score",
            "trackease_priority_level",
            "planning_task_type",
        },
        "Planning tasks",
        results,
    )

    check_required_columns(
        windows,
        {
            "adjusted_window_id",
            "section_id",
            "window_start_minute",
            "window_end_minute",
            "duration_minutes",
        },
        "Adjusted windows",
        results,
    )

    check_required_columns(
        sections,
        {
            "section_id",
        },
        "Railway sections",
        results,
    )

    check_required_columns(
        movements,
        {
            "section_id",
            "weekly_departure_minute",
            "weekly_arrival_minute",
        },
        "Weekly movements",
        results,
    )

    check_required_columns(
        forecasts,
        {
            "forecast_id",
            "section_id",
            "expected_start_minute",
            "expected_end_minute",
        },
        "COA forecast",
        results,
    )

    # -----------------------------------------------------------------------
    # Unique ID checks
    # -----------------------------------------------------------------------

    duplicate_tasks = int(
        tasks[
            "planning_task_id"
        ].duplicated().sum()
    )

    if duplicate_tasks == 0:

        results.pass_check(
            "Planning-task IDs",
            "No duplicate planning_task_id values.",
        )

    else:

        results.error(
            "Planning-task IDs",
            f"{duplicate_tasks:,} duplicate IDs found.",
        )

    duplicate_windows = int(
        windows[
            "adjusted_window_id"
        ].duplicated().sum()
    )

    if duplicate_windows == 0:

        results.pass_check(
            "Adjusted-window IDs",
            "No duplicate adjusted_window_id values.",
        )

    else:

        results.error(
            "Adjusted-window IDs",
            f"{duplicate_windows:,} duplicate IDs found.",
        )

    # -----------------------------------------------------------------------
    # Section-reference checks
    # -----------------------------------------------------------------------

    section_ids = set(
        sections[
            "section_id"
        ].dropna()
    )

    invalid_task_sections = (
        ~tasks[
            "section_id"
        ].isin(
            section_ids
        )
    ).sum()

    if invalid_task_sections == 0:

        results.pass_check(
            "Planning-task section mapping",
            "Every planning task references a valid railway section.",
        )

    else:

        results.error(
            "Planning-task section mapping",
            f"{int(invalid_task_sections):,} invalid section references.",
        )

    invalid_window_sections = (
        ~windows[
            "section_id"
        ].isin(
            section_ids
        )
    ).sum()

    if invalid_window_sections == 0:

        results.pass_check(
            "Block-window section mapping",
            "Every adjusted window references a valid railway section.",
        )

    else:

        results.error(
            "Block-window section mapping",
            f"{int(invalid_window_sections):,} invalid section references.",
        )

    # -----------------------------------------------------------------------
    # Task duration checks
    # -----------------------------------------------------------------------

    required_minutes = pd.to_numeric(
        tasks[
            "required_minutes"
        ],
        errors="coerce",
    )

    invalid_task_duration = (
        required_minutes.isna()
        | (
            required_minutes <= 0
        )
    ).sum()

    if invalid_task_duration == 0:

        results.pass_check(
            "Maintenance durations",
            "All planning tasks have positive required duration.",
        )

    else:

        results.error(
            "Maintenance durations",
            f"{int(invalid_task_duration):,} invalid task durations.",
        )

    # -----------------------------------------------------------------------
    # Priority checks
    # -----------------------------------------------------------------------

    priority_score = pd.to_numeric(
        tasks[
            "trackease_priority_score"
        ],
        errors="coerce",
    )

    invalid_scores = (
        priority_score.isna()
        | (
            priority_score < 0
        )
        | (
            priority_score > 100
        )
    ).sum()

    if invalid_scores == 0:

        results.pass_check(
            "TrackEase priority scores",
            "All scores are within 0–100.",
        )

    else:

        results.error(
            "TrackEase priority scores",
            f"{int(invalid_scores):,} invalid priority scores.",
        )

    # -----------------------------------------------------------------------
    # Window integrity
    # -----------------------------------------------------------------------

    starts = pd.to_numeric(
        windows[
            "window_start_minute"
        ],
        errors="coerce",
    )

    ends = pd.to_numeric(
        windows[
            "window_end_minute"
        ],
        errors="coerce",
    )

    durations = pd.to_numeric(
        windows[
            "duration_minutes"
        ],
        errors="coerce",
    )

    invalid_boundaries = (
        starts.isna()
        | ends.isna()
        | (
            starts < 0
        )
        | (
            ends > MINUTES_PER_WEEK
        )
        | (
            ends <= starts
        )
    ).sum()

    if invalid_boundaries == 0:

        results.pass_check(
            "Weekly block boundaries",
            "All windows are inside the recurring weekly timeline.",
        )

    else:

        results.error(
            "Weekly block boundaries",
            f"{int(invalid_boundaries):,} invalid windows.",
        )

    duration_mismatch = (
        (
            ends
            - starts
        )
        != durations
    ).sum()

    if duration_mismatch == 0:

        results.pass_check(
            "Block-window durations",
            "Stored durations match start/end boundaries.",
        )

    else:

        results.error(
            "Block-window durations",
            f"{int(duration_mismatch):,} duration mismatches.",
        )

    too_short = (
        durations
        < MIN_BLOCK_MINUTES
    ).sum()

    if too_short == 0:

        results.pass_check(
            "Minimum block duration",
            (
                f"All windows are at least "
                f"{MIN_BLOCK_MINUTES} minutes."
            ),
        )

    else:

        results.error(
            "Minimum block duration",
            f"{int(too_short):,} undersized windows found.",
        )

    # -----------------------------------------------------------------------
    # Tasks that have no remaining window
    # -----------------------------------------------------------------------

    sections_with_windows = set(
        windows[
            "section_id"
        ].dropna()
    )

    task_without_window = (
        ~tasks[
            "section_id"
        ].isin(
            sections_with_windows
        )
    )

    no_window_count = int(
        task_without_window.sum()
    )

    if no_window_count == 0:

        results.pass_check(
            "Planning-window availability",
            "Every planning task section has at least one adjusted window.",
        )

    else:

        results.warning(
            "Planning-window availability",
            (
                f"{no_window_count:,} planning units have no remaining "
                "window and may be unschedulable."
            ),
        )

    # -----------------------------------------------------------------------
    # Scheduled-train conflict validation
    # -----------------------------------------------------------------------

    print(
        "\nChecking adjusted windows against "
        "scheduled train movements..."
    )

    train_overlap_count = count_train_overlaps(
        windows,
        movements,
    )

    if train_overlap_count == 0:

        results.pass_check(
            "Scheduled-train conflict check",
            "No adjusted windows overlap known section movements.",
        )

    else:

        results.error(
            "Scheduled-train conflict check",
            (
                f"{train_overlap_count:,} adjusted windows still "
                "overlap scheduled train movement."
            ),
        )

    # -----------------------------------------------------------------------
    # Goods forecast conflict validation
    # -----------------------------------------------------------------------

    print(
        "Checking adjusted windows against "
        "buffered COA goods forecasts..."
    )

    goods_overlap_count = (
        count_goods_overlaps(
            windows,
            forecasts,
        )
    )

    if goods_overlap_count == 0:

        results.pass_check(
            "COA goods-forecast conflict check",
            "No adjusted windows overlap buffered goods forecasts.",
        )

    else:

        results.error(
            "COA goods-forecast conflict check",
            (
                f"{goods_overlap_count:,} adjusted windows still "
                "overlap prototype goods occupancy."
            ),
        )

    # -----------------------------------------------------------------------
    # Final readiness
    # -----------------------------------------------------------------------

    ready = (
        results.errors
        == 0
    )

    readiness_text = (
        "READY FOR OPTIMIZER V2"
        if ready
        else "NOT READY FOR OPTIMIZER V2"
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Planning Readiness Validation Report",
        "=" * 72,
        "",
        f"Planning units       : {len(tasks):,}",
        f"Adjusted windows     : {len(windows):,}",
        f"Railway sections     : {len(sections):,}",
        f"Weekly movements     : {len(movements):,}",
        f"COA forecast events  : {len(forecasts):,}",
        "",
        "VALIDATION RESULTS",
        "-" * 72,
    ]

    for (
        level,
        name,
        detail,
    ) in results.records:

        report.append(
            f"[{level}] {name}"
        )

        report.append(
            f"    {detail}"
        )

    report.extend(
        [
            "",
            "SUMMARY",
            "-" * 72,
            f"Passed checks : {results.passes}",
            f"Warnings      : {results.warnings}",
            f"Errors        : {results.errors}",
            "",
            readiness_text,
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
    print("PLANNING READINESS VALIDATION COMPLETE")
    print("=" * 72)

    print(
        f"\nPassed checks : {results.passes}"
    )

    print(
        f"Warnings      : {results.warnings}"
    )

    print(
        f"Errors        : {results.errors}"
    )

    print(
        f"\nTrain conflicts : "
        f"{train_overlap_count:,}"
    )

    print(
        f"Goods conflicts : "
        f"{goods_overlap_count:,}"
    )

    print(
        f"Tasks without windows : "
        f"{no_window_count:,}"
    )

    print("\nStatus:")
    print(
        f"  {readiness_text}"
    )

    print("\nReport:")
    print(
        f"  {REPORT_FILE}"
    )

    if not ready:

        print(
            "\nDo NOT run Optimizer V2 until "
            "the validation errors are resolved."
        )

    else:

        print(
            "\nThe TrackEase planning data layer is "
            "internally consistent and ready for "
            "impact-aware optimization."
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    validate_planning_ready()