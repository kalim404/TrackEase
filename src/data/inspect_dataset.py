"""
TrackEase - Train Dataset Inspection

Purpose:
    Perform an initial inspection of the raw railway train datasets.

This module does not modify the original data. It only loads the datasets
and displays basic information required for the data-understanding phase.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Project Paths
# ---------------------------------------------------------------------------

# Resolve the project root from this file's location.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Location of the untouched source datasets.
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


# ---------------------------------------------------------------------------
# Dataset Loading
# ---------------------------------------------------------------------------

def load_train_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Load the primary TrackEase train datasets.

    Returns:
        tuple:
            trains: Train-level information.
            stations: Station and geographic information.
            stops: Train stopping and timing information.
    """

    trains = pd.read_csv(RAW_DATA_DIR / "trains.csv")
    stations = pd.read_csv(RAW_DATA_DIR / "stations.csv")
    stops = pd.read_csv(RAW_DATA_DIR / "stops.csv")

    return trains, stations, stops


# ---------------------------------------------------------------------------
# Dataset Inspection
# ---------------------------------------------------------------------------

def inspect_dataset() -> None:
    """Display basic information about the available train datasets."""

    trains, stations, stops = load_train_data()

    print("\n" + "=" * 70)
    print("TrackEase - Train Dataset Overview")
    print("=" * 70)

    print(f"\nTrains   : {len(trains):,}")
    print(f"Stations : {len(stations):,}")
    print(f"Stops    : {len(stops):,}")

    print("\nTrain columns:")
    print(trains.columns.tolist())

    print("\nStation columns:")
    print(stations.columns.tolist())

    print("\nStop columns:")
    print(stops.columns.tolist())


# ---------------------------------------------------------------------------
# Script Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    inspect_dataset()