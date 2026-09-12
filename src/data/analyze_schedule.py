"""
TrackEase - Schedule and Timing Analysis

Purpose:
    Analyze how train schedules are represented in the raw stop data.

This script is read-only and does not modify the raw datasets.
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
    """Load the raw train stop dataset."""

    return pd.read_csv(RAW_DATA_DIR / "stops.csv")


# ---------------------------------------------------------------------------
# Schedule Analysis
# ---------------------------------------------------------------------------

def analyze_schedule(stops: pd.DataFrame) -> None:
    """Analyze sequence, day, timing, and distance information."""

    print("\n" + "=" * 70)
    print("TrackEase - Schedule & Timing Analysis")
    print("=" * 70)

    # -----------------------------------------------------------------------
    # 1. Sequence analysis
    # -----------------------------------------------------------------------

    print("\n[1] STOP SEQUENCE")
    print("-" * 70)

    sequence_per_train = stops.groupby("train_number")["seq"].agg(
        ["min", "max", "count"]
    )

    print(f"Average number of stops : {sequence_per_train['count'].mean():.2f}")
    print(f"Minimum number of stops : {sequence_per_train['count'].min():,}")
    print(f"Maximum number of stops : {sequence_per_train['count'].max():,}")

    # -----------------------------------------------------------------------
    # 2. Day analysis
    # -----------------------------------------------------------------------

    print("\n[2] JOURNEY DAY")
    print("-" * 70)

    print("Unique day values:")

    for day in sorted(stops["day"].unique()):
        count = (stops["day"] == day).sum()
        print(f"  Day {day}: {count:,} stop records")

    # -----------------------------------------------------------------------
    # 3. Arrival and departure timing
    # -----------------------------------------------------------------------

    print("\n[3] TIMING FORMAT")
    print("-" * 70)

    print("Sample arrival times:")
    print(stops["arrival"].dropna().head(10).to_string(index=False))

    print("\nSample departure times:")
    print(stops["departure"].dropna().head(10).to_string(index=False))

    # -----------------------------------------------------------------------
    # 4. Halt duration
    # -----------------------------------------------------------------------

    print("\n[4] HALT DURATION")
    print("-" * 70)

    print(f"Minimum halt : {stops['halt_min'].min()} minutes")
    print(f"Maximum halt : {stops['halt_min'].max()} minutes")
    print(f"Average halt: {stops['halt_min'].mean():.2f} minutes")

    # -----------------------------------------------------------------------
    # 5. Distance progression
    # -----------------------------------------------------------------------

    print("\n[5] DISTANCE")
    print("-" * 70)

    print(f"Minimum distance : {stops['distance_km'].min()} km")
    print(f"Maximum distance : {stops['distance_km'].max()} km")

    # -----------------------------------------------------------------------
    # 6. Example complete train journey
    # -----------------------------------------------------------------------

    print("\n[6] EXAMPLE TRAIN JOURNEY")
    print("-" * 70)

    example_train = stops["train_number"].iloc[0]

    journey = (
        stops[stops["train_number"] == example_train]
        .sort_values(["day", "seq"])
    )

    print(f"Train number: {example_train}\n")

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

    print("\n" + "=" * 70)
    print("Schedule analysis completed.")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the schedule analysis."""

    stops = load_stops()
    analyze_schedule(stops)


if __name__ == "__main__":
    main()