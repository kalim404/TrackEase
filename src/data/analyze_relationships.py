"""
TrackEase - Dataset Relationship Analysis

Purpose:
    Verify the relationships between trains, stops, and stations.

This script is read-only. It does not modify the raw datasets.
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

def load_datasets() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the train, station, and stop datasets."""

    trains = pd.read_csv(RAW_DATA_DIR / "trains.csv")
    stations = pd.read_csv(RAW_DATA_DIR / "stations.csv")
    stops = pd.read_csv(RAW_DATA_DIR / "stops.csv")

    return trains, stations, stops


# ---------------------------------------------------------------------------
# Relationship Analysis
# ---------------------------------------------------------------------------

def analyze_relationships() -> None:
    """Analyze how trains, stops, and stations are connected."""

    trains, stations, stops = load_datasets()

    print("\n" + "=" * 70)
    print("TrackEase - Dataset Relationship Analysis")
    print("=" * 70)

    # -----------------------------------------------------------------------
    # 1. Train number relationship
    # -----------------------------------------------------------------------

    train_numbers = set(trains["number"])
    stop_train_numbers = set(stops["train_number"])

    stops_without_train = stop_train_numbers - train_numbers

    print("\n[1] TRAIN ↔ STOPS")
    print("-" * 70)

    print(f"Unique trains in trains.csv      : {len(train_numbers):,}")
    print(f"Unique trains in stops.csv       : {len(stop_train_numbers):,}")
    print(f"Stop records without train match : {len(stops_without_train):,}")

    # -----------------------------------------------------------------------
    # 2. Station code relationship
    # -----------------------------------------------------------------------

    station_codes = set(stations["code"])
    stop_station_codes = set(stops["station_code"])

    stops_without_station = stop_station_codes - station_codes

    print("\n[2] STATIONS ↔ STOPS")
    print("-" * 70)

    print(f"Unique stations in stations.csv       : {len(station_codes):,}")
    print(f"Unique stations in stops.csv          : {len(stop_station_codes):,}")
    print(
        f"Stop station codes without station match: "
        f"{len(stops_without_station):,}"
    )

    # -----------------------------------------------------------------------
    # 3. Train coverage
    # -----------------------------------------------------------------------

    trains_without_stops = train_numbers - stop_train_numbers

    print("\n[3] TRAIN COVERAGE")
    print("-" * 70)

    print(f"Trains with at least one stop : {len(train_numbers & stop_train_numbers):,}")
    print(f"Trains without any stop       : {len(trains_without_stops):,}")

    # -----------------------------------------------------------------------
    # 4. Stops per train
    # -----------------------------------------------------------------------

    stops_per_train = stops.groupby("train_number").size()

    print("\n[4] STOPS PER TRAIN")
    print("-" * 70)

    print(f"Average stops per train : {stops_per_train.mean():.2f}")
    print(f"Minimum stops per train : {stops_per_train.min():,}")
    print(f"Maximum stops per train : {stops_per_train.max():,}")

    # -----------------------------------------------------------------------
    # 5. Station usage
    # -----------------------------------------------------------------------

    station_usage = stops.groupby("station_code").size()

    print("\n[5] STATION USAGE")
    print("-" * 70)

    print(f"Stations appearing in stops : {len(station_usage):,}")
    print(f"Average stop records/station: {station_usage.mean():.2f}")
    print(f"Maximum stop records/station: {station_usage.max():,}")

    print("\n" + "=" * 70)
    print("Relationship analysis completed.")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    analyze_relationships()