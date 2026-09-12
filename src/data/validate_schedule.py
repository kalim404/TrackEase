"""
TrackEase - Schedule Data Quality Validation

Purpose:
    Identify suspicious or potentially invalid records in the raw
    railway schedule dataset.

This script is READ-ONLY.
It does not modify the original files in data/raw/.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Project Configuration
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


# ---------------------------------------------------------------------------
# Dataset Loading
# ---------------------------------------------------------------------------

def load_stops() -> pd.DataFrame:
    """Load the raw stops dataset."""

    return pd.read_csv(RAW_DATA_DIR / "stops.csv")


# ---------------------------------------------------------------------------
# Time Conversion
# ---------------------------------------------------------------------------

def convert_time_to_minutes(time_value):
    """
    Convert HH:MM time into minutes after midnight.

    Returns:
        Integer minutes, or None when the value is missing/invalid.
    """

    if pd.isna(time_value):
        return None

    try:
        hours, minutes = map(int, str(time_value).split(":"))
        return hours * 60 + minutes
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Validation Functions
# ---------------------------------------------------------------------------

def validate_missing_times(stops: pd.DataFrame) -> None:
    """Identify records with missing arrival or departure times."""

    missing_arrival = stops[stops["arrival"].isna()]
    missing_departure = stops[stops["departure"].isna()]

    print("\n[1] MISSING ARRIVAL / DEPARTURE TIMES")
    print("-" * 70)

    print(f"Missing arrival records   : {len(missing_arrival):,}")
    print(f"Missing departure records : {len(missing_departure):,}")

    print("\nExamples with missing arrival:")

    print(
        missing_arrival[
            [
                "train_number",
                "seq",
                "station_code",
                "station_name",
                "day",
                "arrival",
                "departure",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )

    print("\nExamples with missing departure:")

    print(
        missing_departure[
            [
                "train_number",
                "seq",
                "station_code",
                "station_name",
                "day",
                "arrival",
                "departure",
            ]
        ]
        .head(10)
        .to_string(index=False)
    )


def validate_halt_duration(stops: pd.DataFrame) -> None:
    """Identify unusually large or suspicious halt durations."""

    suspicious = stops[stops["halt_min"] > 60]

    print("\n[2] SUSPICIOUS HALT DURATIONS")
    print("-" * 70)

    print(f"Halt values greater than 60 minutes: {len(suspicious):,}")

    if not suspicious.empty:
        print("\nLargest halt durations:")

        print(
            suspicious[
                [
                    "train_number",
                    "seq",
                    "station_code",
                    "station_name",
                    "day",
                    "arrival",
                    "departure",
                    "halt_min",
                ]
            ]
            .sort_values("halt_min", ascending=False)
            .head(15)
            .to_string(index=False)
        )


def validate_sequence(stops: pd.DataFrame) -> None:
    """Check whether stop sequences are continuous for each train."""

    invalid_trains = []

    for train_number, group in stops.groupby("train_number"):
        sequence = sorted(group["seq"].dropna().astype(int).tolist())

        expected = list(range(1, len(sequence) + 1))

        if sequence != expected:
            invalid_trains.append(train_number)

    print("\n[3] STOP SEQUENCE VALIDATION")
    print("-" * 70)

    print(f"Trains with invalid sequences: {len(invalid_trains):,}")

    if invalid_trains:
        print("Example invalid train numbers:")
        print(invalid_trains[:10])


def validate_distance(stops: pd.DataFrame) -> None:
    """Check whether distance generally increases along each train route."""

    invalid_trains = []

    for train_number, group in stops.groupby("train_number"):
        route = group.sort_values("seq")

        distances = route["distance_km"].tolist()

        for previous, current in zip(distances, distances[1:]):
            if current < previous:
                invalid_trains.append(train_number)
                break

    print("\n[4] DISTANCE PROGRESSION")
    print("-" * 70)

    print(f"Trains with decreasing distance: {len(invalid_trains):,}")

    if invalid_trains:
        print("Example train numbers:")
        print(invalid_trains[:10])


def validate_time_format(stops: pd.DataFrame) -> None:
    """Check whether arrival and departure values follow HH:MM format."""

    invalid_arrival = []
    invalid_departure = []

    for value in stops["arrival"].dropna():
        if convert_time_to_minutes(value) is None:
            invalid_arrival.append(value)

    for value in stops["departure"].dropna():
        if convert_time_to_minutes(value) is None:
            invalid_departure.append(value)

    print("\n[5] TIME FORMAT")
    print("-" * 70)

    print(f"Invalid arrival times   : {len(invalid_arrival):,}")
    print(f"Invalid departure times : {len(invalid_departure):,}")

    if invalid_arrival:
        print("Example invalid arrival values:")
        print(invalid_arrival[:10])

    if invalid_departure:
        print("Example invalid departure values:")
        print(invalid_departure[:10])


def validate_station_names(stops: pd.DataFrame) -> None:
    """Identify missing station names in stop records."""

    missing_names = stops[stops["station_name"].isna()]

    print("\n[6] MISSING STATION NAMES")
    print("-" * 70)

    print(f"Missing station names: {len(missing_names):,}")

    if not missing_names.empty:
        print("\nExamples:")

        print(
            missing_names[
                [
                    "train_number",
                    "seq",
                    "station_code",
                    "station_name",
                ]
            ]
            .head(10)
            .to_string(index=False)
        )


# ---------------------------------------------------------------------------
# Main Validation Process
# ---------------------------------------------------------------------------

def main() -> None:
    """Run all schedule data-quality checks."""

    stops = load_stops()

    print("\n" + "=" * 70)
    print("TrackEase - Detailed Schedule Data Quality Validation")
    print("=" * 70)

    validate_missing_times(stops)
    validate_halt_duration(stops)
    validate_sequence(stops)
    validate_distance(stops)
    validate_time_format(stops)
    validate_station_names(stops)

    print("\n" + "=" * 70)
    print("Data quality validation completed.")
    print("=" * 70)


if __name__ == "__main__":
    main()