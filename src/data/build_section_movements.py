"""
TrackEase - Section Movement Timeline Builder

Purpose:
    Convert normalized train stops into timed movements across the
    TrackEase railway section master.

Inputs:
    data/processed/stops_normalized.csv
    data/processed/railway_sections.csv

Outputs:
    data/processed/section_movements.csv
    data/processed/section_movement_report.txt

Important:
    - No raw data is modified.
    - Journey-day values are retained as relative train journey days.
    - No assumption is made yet about calendar weekdays.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

STOPS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "stops_normalized.csv"
)

SECTIONS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "railway_sections.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "section_movements.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "section_movement_report.txt"
)

MINUTES_PER_DAY = 1440


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------

def time_series_to_minutes(series: pd.Series) -> pd.Series:
    """
    Convert a pandas Series containing HH:MM values into minutes
    after midnight.

    Invalid values become NaN.
    """

    values = series.astype("string").str.strip()

    parts = values.str.extract(
        r"^(\d{1,2}):(\d{2})$"
    )

    hours = pd.to_numeric(
        parts[0],
        errors="coerce",
    )

    minutes = pd.to_numeric(
        parts[1],
        errors="coerce",
    )

    valid = (
        hours.between(0, 23)
        & minutes.between(0, 59)
    )

    result = hours * 60 + minutes

    return result.where(valid)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_section_movements() -> None:
    """Build timed train movements across TrackEase railway sections."""

    print("=" * 72)
    print("TrackEase - Section Movement Timeline Builder")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate files
    # -----------------------------------------------------------------------

    print("\nNormalized stops:")
    print(f"  {STOPS_FILE}")

    if not STOPS_FILE.exists():
        raise FileNotFoundError(
            f"Normalized stops file not found:\n{STOPS_FILE}"
        )

    print("  ✓ Found")

    print("\nRailway section master:")
    print(f"  {SECTIONS_FILE}")

    if not SECTIONS_FILE.exists():
        raise FileNotFoundError(
            f"Railway section master not found:\n{SECTIONS_FILE}"
        )

    print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------

    stops = pd.read_csv(STOPS_FILE)

    sections = pd.read_csv(SECTIONS_FILE)

    print(f"\nStop rows loaded     : {len(stops):,}")
    print(f"Sections loaded      : {len(sections):,}")
    print(
        f"Unique trains        : "
        f"{stops['train_number'].nunique():,}"
    )

    # -----------------------------------------------------------------------
    # Required columns
    # -----------------------------------------------------------------------

    required_stop_columns = {
        "train_number",
        "seq",
        "station_code",
        "day",
        "arrival",
        "departure",
    }

    missing_stop_columns = (
        required_stop_columns
        - set(stops.columns)
    )

    if missing_stop_columns:
        raise ValueError(
            "Required stop columns are missing:\n"
            + "\n".join(
                sorted(missing_stop_columns)
            )
        )

    required_section_columns = {
        "section_id",
        "station_a_code",
        "station_b_code",
    }

    missing_section_columns = (
        required_section_columns
        - set(sections.columns)
    )

    if missing_section_columns:
        raise ValueError(
            "Required railway-section columns are missing:\n"
            + "\n".join(
                sorted(missing_section_columns)
            )
        )

    # -----------------------------------------------------------------------
    # Ensure proper train journey order
    # -----------------------------------------------------------------------

    stops = stops.sort_values(
        ["train_number", "seq"]
    ).reset_index(drop=True)

    grouped = stops.groupby(
        "train_number",
        sort=False,
    )

    # -----------------------------------------------------------------------
    # Build previous-stop information
    #
    # Previous station departure -> current station arrival
    # represents one movement across a section.
    # -----------------------------------------------------------------------

    stops["from_station_code"] = (
        grouped["station_code"].shift(1)
    )

    stops["departure_journey_day"] = (
        grouped["day"].shift(1)
    )

    stops["movement_departure"] = (
        grouped["departure"].shift(1)
    )

    stops["from_seq"] = (
        grouped["seq"].shift(1)
    )

    stops["to_station_code"] = (
        stops["station_code"]
    )

    stops["arrival_journey_day"] = (
        stops["day"]
    )

    stops["movement_arrival"] = (
        stops["arrival"]
    )

    stops["to_seq"] = (
        stops["seq"]
    )

    # First stop of each train cannot create a section movement.
    movements = stops[
        stops["from_station_code"].notna()
    ].copy()

    initial_movements = len(movements)

    # -----------------------------------------------------------------------
    # Remove same-station movements
    # -----------------------------------------------------------------------

    same_station_mask = (
        movements["from_station_code"].astype(str)
        ==
        movements["to_station_code"].astype(str)
    )

    same_station_count = int(
        same_station_mask.sum()
    )

    movements = movements[
        ~same_station_mask
    ].copy()

    # -----------------------------------------------------------------------
    # Create canonical section station pair
    #
    # Example:
    #   ABC -> XYZ
    #   XYZ -> ABC
    #
    # both map to the same railway section.
    # -----------------------------------------------------------------------

    from_code = (
        movements["from_station_code"]
        .astype(str)
        .str.strip()
    )

    to_code = (
        movements["to_station_code"]
        .astype(str)
        .str.strip()
    )

    forward_order = from_code <= to_code

    movements["station_a_code"] = (
        from_code.where(
            forward_order,
            to_code,
        )
    )

    movements["station_b_code"] = (
        to_code.where(
            forward_order,
            from_code,
        )
    )

    movements["direction"] = (
        forward_order.map(
            {
                True: "A_TO_B",
                False: "B_TO_A",
            }
        )
    )

    # -----------------------------------------------------------------------
    # Attach TrackEase section IDs
    # -----------------------------------------------------------------------

    movements = movements.merge(
        sections[
            [
                "section_id",
                "station_a_code",
                "station_b_code",
            ]
        ],
        on=[
            "station_a_code",
            "station_b_code",
        ],
        how="left",
        validate="many_to_one",
    )

    unmapped_count = int(
        movements["section_id"].isna().sum()
    )

    # -----------------------------------------------------------------------
    # Convert times into absolute journey minutes
    # -----------------------------------------------------------------------

    departure_clock = time_series_to_minutes(
        movements["movement_departure"]
    )

    arrival_clock = time_series_to_minutes(
        movements["movement_arrival"]
    )

    departure_day = pd.to_numeric(
        movements["departure_journey_day"],
        errors="coerce",
    )

    arrival_day = pd.to_numeric(
        movements["arrival_journey_day"],
        errors="coerce",
    )

    movements["departure_abs_minute"] = (
        (departure_day - 1)
        * MINUTES_PER_DAY
        + departure_clock
    )

    movements["arrival_abs_minute"] = (
        (arrival_day - 1)
        * MINUTES_PER_DAY
        + arrival_clock
    )

    # -----------------------------------------------------------------------
    # Handle overnight movement
    # -----------------------------------------------------------------------

    overnight_mask = (
        movements["departure_abs_minute"].notna()
        & movements["arrival_abs_minute"].notna()
        & (
            movements["arrival_abs_minute"]
            < movements["departure_abs_minute"]
        )
    )

    overnight_adjusted_count = int(
        overnight_mask.sum()
    )

    movements.loc[
        overnight_mask,
        "arrival_abs_minute",
    ] += MINUTES_PER_DAY

    # -----------------------------------------------------------------------
    # Calculate travel time
    # -----------------------------------------------------------------------

    movements["travel_minutes"] = (
        movements["arrival_abs_minute"]
        - movements["departure_abs_minute"]
    )

    # -----------------------------------------------------------------------
    # Determine usable movements
    # -----------------------------------------------------------------------

    missing_time_mask = (
        movements["departure_abs_minute"].isna()
        | movements["arrival_abs_minute"].isna()
    )

    missing_time_count = int(
        missing_time_mask.sum()
    )

    invalid_duration_mask = (
        movements["travel_minutes"].notna()
        & (
            (movements["travel_minutes"] < 0)
            | (movements["travel_minutes"] > MINUTES_PER_DAY)
        )
    )

    invalid_duration_count = int(
        invalid_duration_mask.sum()
    )

    valid_mask = (
        movements["section_id"].notna()
        & ~missing_time_mask
        & ~invalid_duration_mask
    )

    usable = movements[
        valid_mask
    ].copy()

    # -----------------------------------------------------------------------
    # Generate TrackEase movement IDs
    # -----------------------------------------------------------------------

    usable = usable.reset_index(drop=True)

    usable["movement_id"] = [
        f"MOV-{number:07d}"
        for number in range(
            1,
            len(usable) + 1
        )
    ]

    # -----------------------------------------------------------------------
    # Convert absolute times to integers
    # -----------------------------------------------------------------------

    usable["departure_abs_minute"] = (
        usable["departure_abs_minute"]
        .round()
        .astype(int)
    )

    usable["arrival_abs_minute"] = (
        usable["arrival_abs_minute"]
        .round()
        .astype(int)
    )

    usable["travel_minutes"] = (
        usable["travel_minutes"]
        .round()
        .astype(int)
    )

    # -----------------------------------------------------------------------
    # Final output columns
    # -----------------------------------------------------------------------

    output_columns = [
        "movement_id",
        "train_number",
        "section_id",
        "from_seq",
        "to_seq",
        "from_station_code",
        "to_station_code",
        "direction",
        "departure_journey_day",
        "movement_departure",
        "arrival_journey_day",
        "movement_arrival",
        "departure_abs_minute",
        "arrival_abs_minute",
        "travel_minutes",
    ]

    usable = usable[
        output_columns
    ]

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    usable.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Generate report
    # -----------------------------------------------------------------------

    unique_sections_used = (
        usable["section_id"].nunique()
    )

    unique_trains_used = (
        usable["train_number"].nunique()
    )

    report_lines = [
        "=" * 72,
        "TrackEase Section Movement Timeline Report",
        "=" * 72,
        "",
        f"Stops input              : {STOPS_FILE}",
        f"Section master           : {SECTIONS_FILE}",
        f"Movement output          : {OUTPUT_FILE}",
        "",
        "SUMMARY",
        "-" * 72,
        f"Normalized stop rows     : {len(stops):,}",
        f"Initial movements        : {initial_movements:,}",
        f"Usable timed movements   : {len(usable):,}",
        f"Unique trains represented: {unique_trains_used:,}",
        f"Unique sections used     : {unique_sections_used:,}",
        "",
        "QUALITY CHECKS",
        "-" * 72,
        f"Same-station removed     : {same_station_count:,}",
        f"Unmapped sections        : {unmapped_count:,}",
        f"Missing-time movements   : {missing_time_count:,}",
        f"Overnight adjustments    : {overnight_adjusted_count:,}",
        f"Invalid durations        : {invalid_duration_count:,}",
        "",
        "IMPORTANT INTERPRETATION",
        "-" * 72,
        (
            "departure_abs_minute and arrival_abs_minute are relative "
            "to each train's journey start."
        ),
        (
            "Journey Day 1 must NOT yet be interpreted as Monday or as "
            "the same calendar day for all trains."
        ),
        (
            "Calendar operating days must be aligned before exact "
            "maintenance block windows are calculated."
        ),
        "",
        "NEXT PIPELINE STAGE",
        "-" * 72,
        (
            "Align train movements with train operating-day information, "
            "then calculate real section occupancy and train-free block windows."
        ),
    ]

    REPORT_FILE.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console result
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("SECTION MOVEMENT BUILD COMPLETE")
    print("=" * 72)

    print(f"\nInitial movements      : {initial_movements:,}")
    print(f"Usable movements       : {len(usable):,}")
    print(f"Unique sections used   : {unique_sections_used:,}")
    print(f"Unique trains          : {unique_trains_used:,}")

    print("\nQuality checks:")
    print(f"  Same-station removed : {same_station_count:,}")
    print(f"  Unmapped sections    : {unmapped_count:,}")
    print(f"  Missing times        : {missing_time_count:,}")
    print(f"  Overnight adjusted   : {overnight_adjusted_count:,}")
    print(f"  Invalid durations    : {invalid_duration_count:,}")

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nCalendar weekdays have NOT been assumed."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_section_movements()