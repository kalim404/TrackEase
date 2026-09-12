"""
TrackEase - Railway Section Master Builder

Purpose:
    Build a railway section layer from consecutive station stops
    in the normalized timetable dataset.

Input:
    data/processed/stops_normalized.csv

Outputs:
    data/processed/railway_sections.csv
    data/processed/section_master_report.txt

Important:
    - No raw data is modified.
    - Sections are derived from actual consecutive train stops.
    - Section IDs are internal TrackEase identifiers, not official
      Indian Railways section IDs.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "stops_normalized.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "railway_sections.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "section_master_report.txt"
)


MINUTES_PER_DAY = 1440


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------

def time_to_minutes(value):
    """Convert HH:MM time into minutes from midnight."""

    if pd.isna(value):
        return None

    try:
        hours, minutes = map(int, str(value).split(":"))
        return hours * 60 + minutes
    except (ValueError, TypeError):
        return None


def absolute_minutes(day, time_value):
    """
    Convert journey day + HH:MM into absolute journey minutes.

    Day 1 begins at minute 0.
    """

    if pd.isna(day) or pd.isna(time_value):
        return None

    clock_minutes = time_to_minutes(time_value)

    if clock_minutes is None:
        return None

    try:
        journey_day = int(day)
    except (ValueError, TypeError):
        return None

    return (journey_day - 1) * MINUTES_PER_DAY + clock_minutes


# ---------------------------------------------------------------------------
# Main section builder
# ---------------------------------------------------------------------------

def build_section_master():
    """Build TrackEase railway sections from normalized timetable data."""

    print("=" * 72)
    print("TrackEase - Railway Section Master Builder")
    print("=" * 72)

    print("\nInput file:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Normalized timetable not found:\n{INPUT_FILE}"
        )

    print("  ✓ Input file found")

    # -----------------------------------------------------------------------
    # Load normalized stops
    # -----------------------------------------------------------------------

    df = pd.read_csv(INPUT_FILE)

    print(f"\nStop rows loaded : {len(df):,}")
    print(f"Trains found     : {df['train_number'].nunique():,}")

    required_columns = {
        "train_number",
        "seq",
        "station_code",
        "day",
        "arrival",
        "departure",
        "distance_km",
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            "Required columns missing:\n"
            + "\n".join(sorted(missing_columns))
        )

    # station_name is useful but not mandatory
    if "station_name" not in df.columns:
        df["station_name"] = df["station_code"]

    # -----------------------------------------------------------------------
    # Sort every train into journey order
    # -----------------------------------------------------------------------

    df = df.sort_values(
        ["train_number", "seq"]
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Previous-stop information
    # -----------------------------------------------------------------------

    grouped = df.groupby("train_number", sort=False)

    df["previous_station_code"] = grouped["station_code"].shift(1)
    df["previous_station_name"] = grouped["station_name"].shift(1)

    df["previous_day"] = grouped["day"].shift(1)
    df["previous_departure"] = grouped["departure"].shift(1)

    df["previous_distance_km"] = grouped["distance_km"].shift(1)

    # First stop of every train cannot form a section
    movements = df[df["previous_station_code"].notna()].copy()

    # Remove consecutive duplicate-station records
    same_station = (
        movements["previous_station_code"]
        == movements["station_code"]
    )

    same_station_count = int(same_station.sum())

    movements = movements[~same_station].copy()

    # -----------------------------------------------------------------------
    # Distance between adjacent stops
    # -----------------------------------------------------------------------

    movements["section_distance_km"] = (
        pd.to_numeric(
            movements["distance_km"],
            errors="coerce",
        )
        - pd.to_numeric(
            movements["previous_distance_km"],
            errors="coerce",
        )
    ).abs()

    # -----------------------------------------------------------------------
    # Calculate approximate travel time
    # -----------------------------------------------------------------------

    def calculate_travel_minutes(row):
        previous_departure = absolute_minutes(
            row["previous_day"],
            row["previous_departure"],
        )

        current_arrival = absolute_minutes(
            row["day"],
            row["arrival"],
        )

        if previous_departure is None or current_arrival is None:
            return None

        # Handle an overnight boundary when the day field does not
        # explicitly advance as expected.
        while current_arrival < previous_departure:
            current_arrival += MINUTES_PER_DAY

        difference = current_arrival - previous_departure

        # Ignore unrealistic values for aggregate travel-time statistics.
        if difference < 0 or difference > (2 * MINUTES_PER_DAY):
            return None

        return difference

    movements["travel_minutes"] = movements.apply(
        calculate_travel_minutes,
        axis=1,
    )

    # -----------------------------------------------------------------------
    # Create canonical section pair
    #
    # ABC -> XYZ and XYZ -> ABC represent the same physical section.
    # -----------------------------------------------------------------------

    def canonical_section(row):
        from_code = str(row["previous_station_code"]).strip()
        to_code = str(row["station_code"]).strip()

        from_name = str(row["previous_station_name"]).strip()
        to_name = str(row["station_name"]).strip()

        if from_code <= to_code:
            return pd.Series(
                [from_code, from_name, to_code, to_name, "A_TO_B"]
            )

        return pd.Series(
            [to_code, to_name, from_code, from_name, "B_TO_A"]
        )

    movements[
        [
            "station_a_code",
            "station_a_name",
            "station_b_code",
            "station_b_name",
            "travel_direction",
        ]
    ] = movements.apply(
        canonical_section,
        axis=1,
    )

    # -----------------------------------------------------------------------
    # Create temporary canonical key
    # -----------------------------------------------------------------------

    movements["section_key"] = (
        movements["station_a_code"]
        + "__"
        + movements["station_b_code"]
    )

    # -----------------------------------------------------------------------
    # Aggregate section statistics
    # -----------------------------------------------------------------------

    section_summary = (
    movements
    .groupby(
        [
            "section_key",
            "station_a_code",
            "station_b_code",
        ],
        as_index=False,
    )
    .agg(
        station_a_name=(
            "station_a_name",
            "first",
        ),
        station_b_name=(
            "station_b_name",
            "first",
        ),
        traversal_count=(
            "train_number",
            "size",
        ),
        unique_trains=(
            "train_number",
            "nunique",
        ),
        median_distance_km=(
            "section_distance_km",
            "median",
        ),
        average_travel_minutes=(
            "travel_minutes",
            "mean",
        ),
        median_travel_minutes=(
            "travel_minutes",
            "median",
        ),
    )
)

    # -----------------------------------------------------------------------
    # Direction counts
    # -----------------------------------------------------------------------

    direction_counts = (
        movements
        .pivot_table(
            index="section_key",
            columns="travel_direction",
            values="train_number",
            aggfunc="size",
            fill_value=0,
        )
        .reset_index()
    )

    if "A_TO_B" not in direction_counts.columns:
        direction_counts["A_TO_B"] = 0

    if "B_TO_A" not in direction_counts.columns:
        direction_counts["B_TO_A"] = 0

    direction_counts = direction_counts.rename(
        columns={
            "A_TO_B": "a_to_b_traversals",
            "B_TO_A": "b_to_a_traversals",
        }
    )

    section_summary = section_summary.merge(
        direction_counts[
            [
                "section_key",
                "a_to_b_traversals",
                "b_to_a_traversals",
            ]
        ],
        on="section_key",
        how="left",
    )

    # -----------------------------------------------------------------------
    # Generate TrackEase section IDs
    # -----------------------------------------------------------------------

    section_summary = section_summary.sort_values(
        ["station_a_code", "station_b_code"]
    ).reset_index(drop=True)

    section_summary["section_id"] = [
        f"SEC-{number:06d}"
        for number in range(1, len(section_summary) + 1)
    ]

    # -----------------------------------------------------------------------
    # Round numeric values
    # -----------------------------------------------------------------------

    section_summary["median_distance_km"] = (
        section_summary["median_distance_km"].round(2)
    )

    section_summary["average_travel_minutes"] = (
        section_summary["average_travel_minutes"].round(2)
    )

    section_summary["median_travel_minutes"] = (
        section_summary["median_travel_minutes"].round(2)
    )

    # -----------------------------------------------------------------------
    # Final column order
    # -----------------------------------------------------------------------

    output_columns = [
        "section_id",
        "station_a_code",
        "station_a_name",
        "station_b_code",
        "station_b_name",
        "median_distance_km",
        "unique_trains",
        "traversal_count",
        "a_to_b_traversals",
        "b_to_a_traversals",
        "average_travel_minutes",
        "median_travel_minutes",
    ]

    section_summary = section_summary[output_columns]

    # -----------------------------------------------------------------------
    # Save master dataset
    # -----------------------------------------------------------------------

    section_summary.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    total_sections = len(section_summary)

    total_movements = len(movements)

    busiest_sections = section_summary.nlargest(
        10,
        "unique_trains",
    )

    report_lines = [
        "=" * 72,
        "TrackEase Railway Section Master Report",
        "=" * 72,
        "",
        f"Input file                  : {INPUT_FILE}",
        f"Output file                 : {OUTPUT_FILE}",
        "",
        "DATASET SUMMARY",
        "-" * 72,
        f"Normalized stop rows        : {len(df):,}",
        f"Unique trains               : {df['train_number'].nunique():,}",
        f"Adjacent train movements    : {total_movements:,}",
        f"Unique railway sections     : {total_sections:,}",
        f"Same-station pairs removed  : {same_station_count:,}",
        "",
        "TOP 10 SECTIONS BY UNIQUE TRAINS",
        "-" * 72,
    ]

    for _, row in busiest_sections.iterrows():
        report_lines.append(
            f"{row['station_a_code']} -> "
            f"{row['station_b_code']:<10} "
            f"{int(row['unique_trains']):>6,} trains"
        )

    report_lines.extend(
        [
            "",
            "NOTES",
            "-" * 72,
            (
                "Sections were derived from consecutive station stops "
                "in the normalized railway timetable."
            ),
            (
                "Both directions between the same station pair are represented "
                "by one TrackEase section."
            ),
            (
                "section_id values are internal TrackEase identifiers and "
                "are not official Indian Railways section codes."
            ),
            (
                "No maintenance records were assigned to sections during "
                "this step."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console result
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("SECTION MASTER BUILD COMPLETE")
    print("=" * 72)

    print(f"\nAdjacent movements : {total_movements:,}")
    print(f"Unique sections    : {total_sections:,}")
    print(f"Same-station pairs : {same_station_count:,}")

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print("\nNo maintenance data was artificially linked to railway sections.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_section_master()