"""
TrackEase - Weekly Section Movement Builder

Purpose:
    Convert journey-relative section movements into a recurring
    weekly railway operating timeline using train `runs_days`.

Inputs:
    data/processed/section_movements.csv
    data/raw/schedules.jsonl

Outputs:
    data/processed/weekly_section_movements.csv
    data/processed/weekly_section_movement_report.txt

Important:
    - Train numbers are normalized so values such as 00112 and 112 match.
    - Journey Day 1 is aligned with the train's scheduled starting weekday.
    - No maintenance data is attached during this step.
"""

from pathlib import Path
import json
import re

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MOVEMENTS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "section_movements.csv"
)

SCHEDULE_FILE = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "schedules.jsonl"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_section_movements.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_section_movement_report.txt"
)


MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY


DAY_INDEX = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}

INDEX_DAY = {
    value: key
    for key, value in DAY_INDEX.items()
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_train_number(value):
    """
    Normalize train numbers so:
        00112 -> 112
        112   -> 112
        112.0 -> 112
    """

    if pd.isna(value):
        return None

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    if value.isdigit():
        return str(int(value))

    return value


def parse_run_days(value):
    """Convert runs_days text into standard weekday abbreviations."""

    if value is None:
        return []

    value = str(value).strip()

    if not value:
        return []

    if "daily" in value.lower():
        return list(DAY_INDEX.keys())

    return re.findall(
        r"Mon|Tue|Wed|Thu|Fri|Sat|Sun",
        value,
        flags=re.IGNORECASE,
    )


def standardize_day(day):
    """Normalize weekday capitalization."""

    day = day[:3].title()

    if day in DAY_INDEX:
        return day

    return None


# ---------------------------------------------------------------------------
# Schedule loader
# ---------------------------------------------------------------------------

def load_operating_days():
    """
    Read schedules.jsonl and create one row per:
        train + scheduled starting weekday
    """

    rows = []
    schedule_records = 0

    with SCHEDULE_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = line.strip()

            if not line:
                continue

            record = json.loads(line)

            schedule_records += 1

            train_key = normalize_train_number(
                record.get("number")
            )

            run_days = parse_run_days(
                record.get("runs_days")
            )

            for day in run_days:

                day = standardize_day(day)

                if day is None:
                    continue

                rows.append(
                    {
                        "train_key": train_key,
                        "origin_run_day": day,
                        "origin_day_index": DAY_INDEX[day],
                    }
                )

    operating_days = pd.DataFrame(rows)

    if operating_days.empty:
        raise ValueError(
            "No valid train operating days were found."
        )

    # Prevent repeated schedule rows from creating duplicate services.
    operating_days = operating_days.drop_duplicates(
        ["train_key", "origin_run_day"]
    )

    return operating_days, schedule_records


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_weekly_section_movements():
    """Build the recurring TrackEase weekly section timeline."""

    print("=" * 72)
    print("TrackEase - Weekly Section Movement Builder")
    print("=" * 72)

    print("\nSection movements:")
    print(f"  {MOVEMENTS_FILE}")

    if not MOVEMENTS_FILE.exists():
        raise FileNotFoundError(
            f"Section movements not found:\n{MOVEMENTS_FILE}"
        )

    print("  ✓ Found")

    print("\nOperating schedules:")
    print(f"  {SCHEDULE_FILE}")

    if not SCHEDULE_FILE.exists():
        raise FileNotFoundError(
            f"Schedule file not found:\n{SCHEDULE_FILE}"
        )

    print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load movements
    # -----------------------------------------------------------------------

    movements = pd.read_csv(
        MOVEMENTS_FILE
    )

    print(
        f"\nSection movements loaded : "
        f"{len(movements):,}"
    )

    movements["train_key"] = (
        movements["train_number"]
        .apply(normalize_train_number)
    )

    # -----------------------------------------------------------------------
    # Load train operating days
    # -----------------------------------------------------------------------

    operating_days, schedule_records = (
        load_operating_days()
    )

    print(
        f"Schedule records loaded  : "
        f"{schedule_records:,}"
    )

    print(
        f"Train-day combinations   : "
        f"{len(operating_days):,}"
    )

    # -----------------------------------------------------------------------
    # Check schedule coverage
    # -----------------------------------------------------------------------

    movement_train_keys = set(
        movements["train_key"].dropna()
    )

    schedule_train_keys = set(
        operating_days["train_key"].dropna()
    )

    matched_train_keys = (
        movement_train_keys
        & schedule_train_keys
    )

    unmatched_train_keys = (
        movement_train_keys
        - schedule_train_keys
    )

    # -----------------------------------------------------------------------
    # Expand movements by each scheduled origin day
    # -----------------------------------------------------------------------

    weekly = movements.merge(
        operating_days,
        on="train_key",
        how="inner",
        validate="many_to_many",
    )

    # -----------------------------------------------------------------------
    # Convert to weekly minute positions
    # -----------------------------------------------------------------------

    weekly["service_start_minute"] = (
        weekly["origin_day_index"]
        * MINUTES_PER_DAY
    )

    weekly["weekly_departure_minute"] = (
        (
            weekly["service_start_minute"]
            + weekly["departure_abs_minute"]
        )
        % MINUTES_PER_WEEK
    )

    weekly["weekly_arrival_minute"] = (
        (
            weekly["service_start_minute"]
            + weekly["arrival_abs_minute"]
        )
        % MINUTES_PER_WEEK
    )

    # -----------------------------------------------------------------------
    # Determine actual movement weekdays
    # -----------------------------------------------------------------------

    departure_day_index = (
        weekly["weekly_departure_minute"]
        // MINUTES_PER_DAY
    ).astype(int)

    arrival_day_index = (
        weekly["weekly_arrival_minute"]
        // MINUTES_PER_DAY
    ).astype(int)

    weekly["departure_weekday"] = (
        departure_day_index.map(INDEX_DAY)
    )

    weekly["arrival_weekday"] = (
        arrival_day_index.map(INDEX_DAY)
    )

    # -----------------------------------------------------------------------
    # Detect movement crossing Sunday -> Monday week boundary
    # -----------------------------------------------------------------------

    weekly["crosses_week_boundary"] = (
        weekly["weekly_arrival_minute"]
        < weekly["weekly_departure_minute"]
    ).astype(int)

    # -----------------------------------------------------------------------
    # Generate weekly movement IDs
    # -----------------------------------------------------------------------

    weekly = weekly.reset_index(
        drop=True
    )

    weekly["weekly_movement_id"] = [
        f"WMOV-{number:08d}"
        for number in range(
            1,
            len(weekly) + 1
        )
    ]

    # -----------------------------------------------------------------------
    # Final columns
    # -----------------------------------------------------------------------

    output_columns = [
        "weekly_movement_id",
        "movement_id",
        "train_number",
        "section_id",
        "origin_run_day",
        "departure_weekday",
        "arrival_weekday",
        "from_station_code",
        "to_station_code",
        "direction",
        "movement_departure",
        "movement_arrival",
        "travel_minutes",
        "weekly_departure_minute",
        "weekly_arrival_minute",
        "crosses_week_boundary",
    ]

    weekly = weekly[
        output_columns
    ]

    weekly = weekly.sort_values(
        [
            "section_id",
            "weekly_departure_minute",
        ]
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Save output
    # -----------------------------------------------------------------------

    weekly.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    unique_sections = (
        weekly["section_id"].nunique()
    )

    unique_trains = (
        weekly["train_number"].nunique()
    )

    boundary_crossings = int(
        weekly[
            "crosses_week_boundary"
        ].sum()
    )

    report_lines = [
        "=" * 72,
        "TrackEase Weekly Section Movement Report",
        "=" * 72,
        "",
        f"Section movement input     : {MOVEMENTS_FILE}",
        f"Operating schedule input   : {SCHEDULE_FILE}",
        f"Output file                : {OUTPUT_FILE}",
        "",
        "SCHEDULE MATCHING",
        "-" * 72,
        f"Schedule records           : {schedule_records:,}",
        f"Movement train numbers     : {len(movement_train_keys):,}",
        f"Matched train numbers      : {len(matched_train_keys):,}",
        f"Unmatched train numbers    : {len(unmatched_train_keys):,}",
        "",
        "WEEKLY TIMELINE",
        "-" * 72,
        f"Base section movements     : {len(movements):,}",
        f"Weekly movement instances  : {len(weekly):,}",
        f"Unique trains represented  : {unique_trains:,}",
        f"Unique sections represented: {unique_sections:,}",
        f"Week-boundary movements    : {boundary_crossings:,}",
        "",
        "INTERPRETATION",
        "-" * 72,
        (
            "Each row represents a train movement across a railway "
            "section on one scheduled weekly service instance."
        ),
        (
            "runs_days represents the origin departure weekday. "
            "Journey-day offsets determine the weekday at downstream sections."
        ),
        (
            "weekly_departure_minute uses Monday 00:00 as minute 0 "
            "and Sunday 23:59 as the end of the recurring week."
        ),
        "",
        "NEXT STEP",
        "-" * 72,
        (
            "Use these weekly section occupancy events to calculate "
            "train-free gaps and candidate maintenance block windows."
        ),
    ]

    if unmatched_train_keys:
        report_lines.extend(
            [
                "",
                "SAMPLE UNMATCHED TRAINS",
                "-" * 72,
            ]
        )

        for train_key in sorted(
            list(unmatched_train_keys)
        )[:20]:

            report_lines.append(
                str(train_key)
            )

    REPORT_FILE.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console output
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("WEEKLY SECTION MOVEMENT BUILD COMPLETE")
    print("=" * 72)

    print(
        f"\nMovement train numbers  : "
        f"{len(movement_train_keys):,}"
    )

    print(
        f"Matched train numbers   : "
        f"{len(matched_train_keys):,}"
    )

    print(
        f"Unmatched train numbers : "
        f"{len(unmatched_train_keys):,}"
    )

    print(
        f"\nWeekly movements       : "
        f"{len(weekly):,}"
    )

    print(
        f"Unique sections        : "
        f"{unique_sections:,}"
    )

    print(
        f"Unique trains          : "
        f"{unique_trains:,}"
    )

    print(
        f"Week boundary movements: "
        f"{boundary_crossings:,}"
    )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nTrain journey days are now aligned "
        "with their scheduled operating weekdays."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_weekly_section_movements()