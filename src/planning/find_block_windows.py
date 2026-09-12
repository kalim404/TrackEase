"""
TrackEase - Maintenance Block Window Finder

Purpose:
    Analyse the recurring weekly train-movement timeline and find
    train-free maintenance windows on every railway section.

Input:
    data/processed/weekly_section_movements.csv

Outputs:
    data/processed/available_block_windows.csv
    data/processed/block_window_report.txt

Prototype assumptions:
    - A 10-minute safety clearance is kept around train movements.
    - Only gaps >= 30 minutes are retained.
    - The weekly timetable is treated as cyclic, so Sunday -> Monday
      movements and safety-buffer spillovers are handled correctly.
    - These are planning candidates, not official railway block authorities.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_section_movements.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "available_block_windows.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_window_report.txt"
)

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

SAFETY_BUFFER_MINUTES = 10
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
    """Convert a minute on the recurring week into weekday and HH:MM."""

    value = int(value)

    # 10080 is the end of Sunday / start of the next recurring Monday.
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


# ---------------------------------------------------------------------------
# Interval processing
# ---------------------------------------------------------------------------

def merge_intervals(intervals):
    """Merge overlapping or touching train-occupancy intervals."""

    if not intervals:
        return []

    intervals = sorted(
        intervals,
        key=lambda item: item[0],
    )

    merged = [
        intervals[0]
    ]

    for start, end in intervals[1:]:

        previous_start, previous_end = merged[-1]

        if start <= previous_end:
            merged[-1] = (
                previous_start,
                max(previous_end, end),
            )
        else:
            merged.append(
                (start, end)
            )

    return merged


def normalize_cyclic_interval(start, end):
    """
    Project one continuous occupancy interval into the recurring weekly
    range [0, MINUTES_PER_WEEK].

    The interval may extend before Monday 00:00 or beyond Sunday 24:00
    because of a Sunday -> Monday movement or the safety buffer.
    """

    normalized = []

    # Looking one week backward/current/forward is enough because train
    # section-occupancy intervals are much shorter than one week.
    for shift in (
        -MINUTES_PER_WEEK,
        0,
        MINUTES_PER_WEEK,
    ):

        shifted_start = start + shift
        shifted_end = end + shift

        # No intersection with the current recurring-week representation.
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
            normalized.append(
                (
                    int(clipped_start),
                    int(clipped_end),
                )
            )

    return normalized


def find_section_gaps(section_df):
    """
    Find train-free maintenance windows for one railway section.

    Scheduled train occupancy is expanded by the safety buffer and then
    projected cyclically into the recurring week. This prevents false
    Monday windows when a train movement crosses Sunday -> Monday.
    """

    occupied_intervals = []

    for row in section_df.itertuples():

        start = pd.to_numeric(
            row.weekly_departure_minute,
            errors="coerce",
        )

        end = pd.to_numeric(
            row.weekly_arrival_minute,
            errors="coerce",
        )

        # Keep the planner defensive if unusable records appear.
        if pd.isna(start) or pd.isna(end):
            continue

        start = int(start)
        end = int(end)

        # Example:
        # Sunday 23:55 (10075) -> Monday 00:15 (15)
        # becomes 10075 -> 10095 before cyclic normalization.
        if end < start:
            end += MINUTES_PER_WEEK

        # Apply planning safety clearance.
        start -= SAFETY_BUFFER_MINUTES
        end += SAFETY_BUFFER_MINUTES

        occupied_intervals.extend(
            normalize_cyclic_interval(
                start,
                end,
            )
        )

    occupied_intervals = merge_intervals(
        occupied_intervals
    )

    # -----------------------------------------------------------------------
    # Find the complement of occupied intervals inside one recurring week.
    # -----------------------------------------------------------------------

    gaps = []
    current = 0

    for start, end in occupied_intervals:

        if start > current:

            duration = (
                start - current
            )

            if duration >= MIN_BLOCK_MINUTES:
                gaps.append(
                    (
                        current,
                        start,
                        duration,
                    )
                )

        current = max(
            current,
            end,
        )

    if current < MINUTES_PER_WEEK:

        duration = (
            MINUTES_PER_WEEK
            - current
        )

        if duration >= MIN_BLOCK_MINUTES:
            gaps.append(
                (
                    current,
                    MINUTES_PER_WEEK,
                    duration,
                )
            )

    return gaps


def classify_window(duration):
    """Classify a candidate maintenance window by duration."""

    if duration >= 240:
        return "Long"

    if duration >= 120:
        return "Medium"

    return "Short"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_block_windows():
    """Build timetable-based maintenance block-window candidates."""

    print("=" * 72)
    print("TrackEase - Maintenance Block Window Finder")
    print("=" * 72)

    print("\nInput:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Weekly movement file not found:\n{INPUT_FILE}"
        )

    print("  ✓ Found")

    movements = pd.read_csv(
        INPUT_FILE
    )

    # -----------------------------------------------------------------------
    # Validate the columns required by this planning stage.
    # -----------------------------------------------------------------------

    required_columns = {
        "section_id",
        "weekly_departure_minute",
        "weekly_arrival_minute",
    }

    missing_columns = (
        required_columns
        - set(movements.columns)
    )

    if missing_columns:
        raise ValueError(
            "Weekly movement dataset is missing required columns:\n"
            + ", ".join(
                sorted(missing_columns)
            )
        )

    print(
        f"\nWeekly movements : {len(movements):,}"
    )

    print(
        f"Sections         : "
        f"{movements['section_id'].nunique():,}"
    )

    block_rows = []

    # -----------------------------------------------------------------------
    # Process section by section.
    # -----------------------------------------------------------------------

    for section_id, section_df in movements.groupby(
        "section_id",
        sort=False,
    ):

        gaps = find_section_gaps(
            section_df
        )

        for start, end, duration in gaps:

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

            block_rows.append(
                {
                    "section_id":
                        section_id,

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
                }
            )

    windows = pd.DataFrame(
        block_rows
    )

    if windows.empty:
        raise ValueError(
            "No available block windows were found."
        )

    # -----------------------------------------------------------------------
    # Sort and generate stable IDs.
    # -----------------------------------------------------------------------

    windows = windows.sort_values(
        [
            "section_id",
            "window_start_minute",
        ]
    ).reset_index(
        drop=True
    )

    windows.insert(
        0,
        "window_id",
        [
            f"BLK-{number:07d}"
            for number in range(
                1,
                len(windows) + 1
            )
        ],
    )

    # -----------------------------------------------------------------------
    # Window categories.
    # -----------------------------------------------------------------------

    windows["window_class"] = (
        windows[
            "duration_minutes"
        ]
        .apply(
            classify_window
        )
    )

    # -----------------------------------------------------------------------
    # Save.
    # -----------------------------------------------------------------------

    windows.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Statistics.
    # -----------------------------------------------------------------------

    sections_with_windows = (
        windows[
            "section_id"
        ].nunique()
    )

    average_duration = (
        windows[
            "duration_minutes"
        ].mean()
    )

    longest_duration = int(
        windows[
            "duration_minutes"
        ].max()
    )

    class_counts = (
        windows[
            "window_class"
        ]
        .value_counts()
    )

    # -----------------------------------------------------------------------
    # Report.
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Available Block Window Report",
        "=" * 72,
        "",
        f"Input file               : {INPUT_FILE}",
        f"Output file              : {OUTPUT_FILE}",
        "",
        "SUMMARY",
        "-" * 72,
        f"Weekly movements         : {len(movements):,}",
        (
            f"Sections analysed        : "
            f"{movements['section_id'].nunique():,}"
        ),
        f"Sections with windows    : {sections_with_windows:,}",
        f"Block windows discovered : {len(windows):,}",
        f"Average window duration  : {average_duration:.2f} minutes",
        f"Longest window duration  : {longest_duration:,} minutes",
        "",
        "WINDOW CLASSIFICATION",
        "-" * 72,
    ]

    for name, count in class_counts.items():
        report.append(
            f"{name:<20} {count:>10,}"
        )

    report.extend(
        [
            "",
            "PROTOTYPE ASSUMPTIONS",
            "-" * 72,
            (
                f"Safety buffer             : "
                f"{SAFETY_BUFFER_MINUTES} minutes"
            ),
            (
                f"Minimum retained window   : "
                f"{MIN_BLOCK_MINUTES} minutes"
            ),
            "Weekly timetable treatment : CYCLIC",
            "",
            (
                "These windows represent timetable-based planning "
                "opportunities and are not official railway block authorities."
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
    print("BLOCK WINDOW BUILD COMPLETE")
    print("=" * 72)

    print(
        f"\nAvailable windows : "
        f"{len(windows):,}"
    )

    print(
        f"Sections covered  : "
        f"{sections_with_windows:,}"
    )

    print(
        f"Average duration  : "
        f"{average_duration:.2f} min"
    )

    print(
        f"Longest window    : "
        f"{longest_duration:,} min"
    )

    print("\nWindow classes:")

    for name, count in class_counts.items():
        print(
            f"  {name:<10} "
            f"{count:>10,}"
        )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nWeekly block windows rebuilt with "
        "Sunday -> Monday cyclic occupancy handled correctly."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_block_windows()
