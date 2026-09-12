"""
TrackEase - Halt Duration Anomaly Investigation

Purpose:
    Investigate unusually large halt durations and compare them with
    arrival, departure, and journey-day information.

This script is READ-ONLY.
It does not modify the raw dataset.
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

def time_to_minutes(time_value):
    """
    Convert HH:MM into minutes after midnight.

    Returns None for missing or invalid values.
    """

    if pd.isna(time_value):
        return None

    try:
        hours, minutes = map(int, str(time_value).split(":"))
        return hours * 60 + minutes
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Halt Investigation
# ---------------------------------------------------------------------------

def investigate_halts(stops: pd.DataFrame) -> None:
    """Investigate records with unusually large halt durations."""

    suspicious = stops[stops["halt_min"] > 60].copy()

    print("\n" + "=" * 80)
    print("TrackEase - Halt Duration Anomaly Investigation")
    print("=" * 80)

    print(f"\nSuspicious halt records: {len(suspicious):,}")

    # -----------------------------------------------------------------------
    # Calculate simple clock-time difference
    # -----------------------------------------------------------------------

    suspicious["arrival_minutes"] = suspicious["arrival"].apply(
        time_to_minutes
    )

    suspicious["departure_minutes"] = suspicious["departure"].apply(
        time_to_minutes
    )

    suspicious["clock_difference"] = (
        suspicious["departure_minutes"]
        - suspicious["arrival_minutes"]
    )

    # -----------------------------------------------------------------------
    # Display suspicious records
    # -----------------------------------------------------------------------

    print("\n[1] SUSPICIOUS HALT RECORDS")
    print("-" * 80)

    columns = [
        "train_number",
        "seq",
        "station_code",
        "station_name",
        "day",
        "arrival",
        "departure",
        "halt_min",
        "clock_difference",
    ]

    print(
        suspicious.sort_values("halt_min", ascending=False)[columns]
        .head(30)
        .to_string(index=False)
    )

    # -----------------------------------------------------------------------
    # Compare halt duration with clock difference
    # -----------------------------------------------------------------------

    print("\n[2] HALT VS CLOCK DIFFERENCE")
    print("-" * 80)

    valid_comparison = suspicious.dropna(
        subset=["arrival_minutes", "departure_minutes"]
    ).copy()

    valid_comparison["difference_from_halt"] = (
        valid_comparison["halt_min"]
        - valid_comparison["clock_difference"]
    )

    print(
        valid_comparison[
            [
                "train_number",
                "station_code",
                "day",
                "arrival",
                "departure",
                "halt_min",
                "clock_difference",
                "difference_from_halt",
            ]
        ]
        .sort_values("halt_min", ascending=False)
        .head(30)
        .to_string(index=False)
    )

    # -----------------------------------------------------------------------
    # Inspect one complete train journey for the largest anomaly
    # -----------------------------------------------------------------------

    largest_anomaly = suspicious.loc[
        suspicious["halt_min"].idxmax()
    ]

    train_number = largest_anomaly["train_number"]

    print("\n[3] COMPLETE JOURNEY OF LARGEST ANOMALY")
    print("-" * 80)

    print(f"Train number: {train_number}")

    journey = (
        stops[stops["train_number"] == train_number]
        .sort_values(["day", "seq"])
    )

    print(
        journey[
            [
                "seq",
                "station_code",
                "station_name",
                "day",
                "arrival",
                "departure",
                "halt_min",
                "distance_km",
            ]
        ].to_string(index=False)
    )

    print("\n" + "=" * 80)
    print("Halt anomaly investigation completed.")
    print("=" * 80)


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the halt anomaly investigation."""

    stops = load_stops()
    investigate_halts(stops)


if __name__ == "__main__":
    main()