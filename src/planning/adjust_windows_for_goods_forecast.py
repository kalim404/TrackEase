"""
TrackEase - Goods Forecast Window Adjustment

Purpose:
    Adjust timetable-derived maintenance block windows using the
    prototype COA goods-train forecast.

Inputs:
    data/processed/available_block_windows.csv
    data/processed/coa_goods_forecast.csv

Outputs:
    data/processed/adjusted_block_windows.csv
    data/processed/goods_window_adjustment_report.txt

Logic:
    - Existing scheduled train occupancy has already been removed.
    - COA goods forecasts are treated as additional expected occupancy.
    - Forecast intervals receive a small safety buffer.
    - Existing maintenance windows may be shortened, split or removed.
    - Fragments shorter than the minimum maintenance-block duration
      are discarded.

Important:
    The COA forecast is a prototype integration adapter and does not
    represent live Indian Railways Control Office data.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "available_block_windows.csv"
)

FORECAST_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coa_goods_forecast.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "adjusted_block_windows.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "goods_window_adjustment_report.txt"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

GOODS_SAFETY_BUFFER_MINUTES = 10

MIN_BLOCK_MINUTES = 30

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
# Time helpers
# ---------------------------------------------------------------------------

def weekly_minute_to_label(value):
    """Convert minute-of-week into weekday and HH:MM."""

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


def classify_window(duration):
    """Classify maintenance-window duration."""

    if duration >= 240:
        return "Long"

    if duration >= 120:
        return "Medium"

    return "Short"


# ---------------------------------------------------------------------------
# Interval utilities
# ---------------------------------------------------------------------------

def merge_intervals(intervals):
    """Merge overlapping forecast occupancy intervals."""

    if not intervals:
        return []

    intervals = sorted(
        intervals,
        key=lambda item: item[0],
    )

    merged = [
        list(intervals[0])
    ]

    for start, end in intervals[1:]:

        previous = merged[-1]

        if start <= previous[1]:

            previous[1] = max(
                previous[1],
                end,
            )

        else:

            merged.append(
                [start, end]
            )

    return [
        (start, end)
        for start, end in merged
    ]


def normalize_forecast_interval(start, end):
    """
    Convert a possibly week-crossing forecast interval into one or two
    intervals within [0, 10080].

    Safety clearance is included here.
    """

    start = int(start) - GOODS_SAFETY_BUFFER_MINUTES
    end = int(end) + GOODS_SAFETY_BUFFER_MINUTES

    # Handle an interval beginning just before Monday 00:00.
    if start < 0:

        return [
            (
                0,
                min(
                    end,
                    MINUTES_PER_WEEK,
                ),
            ),
            (
                MINUTES_PER_WEEK + start,
                MINUTES_PER_WEEK,
            ),
        ]

    # Handle Sunday -> Monday crossing.
    if end > MINUTES_PER_WEEK:

        return [
            (
                start,
                MINUTES_PER_WEEK,
            ),
            (
                0,
                end - MINUTES_PER_WEEK,
            ),
        ]

    return [
        (
            start,
            end,
        )
    ]


def subtract_intervals(
    window_start,
    window_end,
    blocked_intervals,
):
    """
    Remove goods-forecast occupancy from one maintenance window.

    Returns the remaining free fragments.
    """

    fragments = [
        (
            int(window_start),
            int(window_end),
        )
    ]

    for blocked_start, blocked_end in blocked_intervals:

        new_fragments = []

        for free_start, free_end in fragments:

            # No overlap.
            if (
                blocked_end <= free_start
                or blocked_start >= free_end
            ):

                new_fragments.append(
                    (
                        free_start,
                        free_end,
                    )
                )

                continue

            # Free portion before forecast occupancy.
            if blocked_start > free_start:

                new_fragments.append(
                    (
                        free_start,
                        min(
                            blocked_start,
                            free_end,
                        ),
                    )
                )

            # Free portion after forecast occupancy.
            if blocked_end < free_end:

                new_fragments.append(
                    (
                        max(
                            blocked_end,
                            free_start,
                        ),
                        free_end,
                    )
                )

        fragments = new_fragments

        if not fragments:
            break

    return fragments


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def adjust_block_windows():
    """Apply prototype COA goods occupancy to maintenance windows."""

    print("=" * 72)
    print("TrackEase - Goods Forecast Window Adjustment")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate inputs
    # -----------------------------------------------------------------------

    for file_path, label in [
        (
            WINDOWS_FILE,
            "Available block windows",
        ),
        (
            FORECAST_FILE,
            "COA goods forecast",
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
    # Load
    # -----------------------------------------------------------------------

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    forecasts = pd.read_csv(
        FORECAST_FILE
    )

    print(
        f"\nBase windows loaded     : "
        f"{len(windows):,}"
    )

    print(
        f"Goods forecasts loaded  : "
        f"{len(forecasts):,}"
    )

    print(
        f"Forecast sections       : "
        f"{forecasts['section_id'].nunique():,}"
    )

    # -----------------------------------------------------------------------
    # Create goods occupancy map by section
    # -----------------------------------------------------------------------

    forecast_map = {}

    for row in forecasts.itertuples():

        intervals = normalize_forecast_interval(
            row.expected_start_minute,
            row.expected_end_minute,
        )

        forecast_map.setdefault(
            row.section_id,
            []
        ).extend(
            intervals
        )

    # Merge goods intervals within each section.
    for section_id in forecast_map:

        forecast_map[
            section_id
        ] = merge_intervals(
            forecast_map[
                section_id
            ]
        )

    # -----------------------------------------------------------------------
    # Process maintenance windows
    # -----------------------------------------------------------------------

    adjusted_rows = []

    affected_source_windows = 0
    removed_source_windows = 0
    split_source_windows = 0

    base_minutes = int(
        windows[
            "duration_minutes"
        ].sum()
    )

    output_counter = 1

    for window in windows.itertuples():

        blocked_intervals = (
            forecast_map.get(
                window.section_id,
                [],
            )
        )

        original_start = int(
            window.window_start_minute
        )

        original_end = int(
            window.window_end_minute
        )

        # ---------------------------------------------------------------
        # No COA forecast on this section
        # ---------------------------------------------------------------

        if not blocked_intervals:

            fragments = [
                (
                    original_start,
                    original_end,
                )
            ]

            forecast_adjusted = 0

        else:

            fragments = subtract_intervals(
                original_start,
                original_end,
                blocked_intervals,
            )

            original_duration = (
                original_end
                - original_start
            )

            fragment_duration = sum(
                end - start
                for start, end in fragments
            )

            forecast_adjusted = int(
                fragment_duration
                < original_duration
            )

            if forecast_adjusted:
                affected_source_windows += 1

        # ---------------------------------------------------------------
        # Remove tiny fragments
        # ---------------------------------------------------------------

        usable_fragments = []

        for start, end in fragments:

            duration = (
                end - start
            )

            if duration >= MIN_BLOCK_MINUTES:

                usable_fragments.append(
                    (
                        start,
                        end,
                        duration,
                    )
                )

        # ---------------------------------------------------------------
        # Determine whether source window disappeared or split
        # ---------------------------------------------------------------

        if len(
            usable_fragments
        ) == 0:

            removed_source_windows += 1

        elif len(
            usable_fragments
        ) > 1:

            split_source_windows += 1

        # ---------------------------------------------------------------
        # Save resulting windows
        # ---------------------------------------------------------------

        for (
            start,
            end,
            duration,
        ) in usable_fragments:

            start_day, start_time = (
                weekly_minute_to_label(
                    start
                )
            )

            end_day, end_time = (
                weekly_minute_to_label(
                    end
                )
            )

            adjusted_rows.append(
                {
                    "adjusted_window_id":
                        f"ABLK-{output_counter:07d}",

                    "source_window_id":
                        window.window_id,

                    "section_id":
                        window.section_id,

                    "window_start_minute":
                        int(start),

                    "window_end_minute":
                        int(end),

                    "duration_minutes":
                        int(duration),

                    "start_day":
                        start_day,

                    "start_time":
                        start_time,

                    "end_day":
                        end_day,

                    "end_time":
                        end_time,

                    "window_class":
                        classify_window(
                            duration
                        ),

                    "coa_adjusted":
                        forecast_adjusted,

                    "goods_forecast_present":
                        int(
                            bool(
                                blocked_intervals
                            )
                        ),

                    "source_window_duration":
                        int(
                            original_end
                            - original_start
                        ),

                    "goods_safety_buffer_minutes":
                        GOODS_SAFETY_BUFFER_MINUTES,
                }
            )

            output_counter += 1

    adjusted = pd.DataFrame(
        adjusted_rows
    )

    if adjusted.empty:

        raise ValueError(
            "No maintenance windows remain after "
            "goods-forecast adjustment."
        )

    # -----------------------------------------------------------------------
    # Sort and save
    # -----------------------------------------------------------------------

    adjusted = adjusted.sort_values(
        [
            "section_id",
            "window_start_minute",
        ]
    ).reset_index(drop=True)

    adjusted.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    adjusted_minutes = int(
        adjusted[
            "duration_minutes"
        ].sum()
    )

    minutes_removed = (
        base_minutes
        - adjusted_minutes
    )

    reduction_percent = (
        minutes_removed
        / base_minutes
        * 100
        if base_minutes > 0
        else 0
    )

    sections_remaining = (
        adjusted[
            "section_id"
        ].nunique()
    )

    coa_adjusted_output_windows = int(
        adjusted[
            "coa_adjusted"
        ].sum()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Goods Forecast Window Adjustment Report",
        "=" * 72,
        "",
        "INPUT",
        "-" * 72,
        f"Original block windows          : {len(windows):,}",
        f"COA forecast events             : {len(forecasts):,}",
        f"Forecast sections               : {forecasts['section_id'].nunique():,}",
        "",
        "WINDOW ADJUSTMENT",
        "-" * 72,
        f"Final adjusted windows          : {len(adjusted):,}",
        f"Source windows affected         : {affected_source_windows:,}",
        f"Source windows split            : {split_source_windows:,}",
        f"Source windows removed          : {removed_source_windows:,}",
        f"Adjusted output fragments       : {coa_adjusted_output_windows:,}",
        f"Sections retaining windows      : {sections_remaining:,}",
        "",
        "AVAILABLE MAINTENANCE TIME",
        "-" * 72,
        f"Before COA adjustment           : {base_minutes:,} minutes",
        f"After COA adjustment            : {adjusted_minutes:,} minutes",
        f"Forecast occupancy removed      : {minutes_removed:,} minutes",
        f"Availability reduction          : {reduction_percent:.4f}%",
        "",
        "PROTOTYPE CONFIGURATION",
        "-" * 72,
        (
            f"Goods-train safety buffer       : "
            f"{GOODS_SAFETY_BUFFER_MINUTES} minutes"
        ),
        (
            f"Minimum retained block duration : "
            f"{MIN_BLOCK_MINUTES} minutes"
        ),
        "",
        "INTERPRETATION",
        "-" * 72,
        (
            "Maintenance windows are first derived from scheduled "
            "timetable occupancy and then adjusted using expected "
            "goods-train occupancy."
        ),
        (
            "A forecast can shorten, split or eliminate an otherwise "
            "available maintenance window."
        ),
        (
            "COA forecast records remain prototype inputs and do not "
            "represent live Control Office data."
        ),
        "",
        "NEXT STAGE",
        "-" * 72,
        (
            "Use adjusted maintenance windows together with "
            "coordinated maintenance tasks in the impact-aware "
            "weekly/monthly block optimizer."
        ),
    ]

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("GOODS FORECAST WINDOW ADJUSTMENT COMPLETE")
    print("=" * 72)

    print(
        f"\nOriginal windows : "
        f"{len(windows):,}"
    )

    print(
        f"Adjusted windows : "
        f"{len(adjusted):,}"
    )

    print(
        f"Affected windows : "
        f"{affected_source_windows:,}"
    )

    print(
        f"Split windows    : "
        f"{split_source_windows:,}"
    )

    print(
        f"Removed windows  : "
        f"{removed_source_windows:,}"
    )

    print("\nAvailable maintenance time:")

    print(
        f"  Before : "
        f"{base_minutes:,} min"
    )

    print(
        f"  After  : "
        f"{adjusted_minutes:,} min"
    )

    print(
        f"  Removed: "
        f"{minutes_removed:,} min"
    )

    print(
        f"  Change : "
        f"-{reduction_percent:.4f}%"
    )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nTrackEase maintenance availability now accounts "
        "for both timetable traffic and prototype COA goods forecasts."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    adjust_block_windows()