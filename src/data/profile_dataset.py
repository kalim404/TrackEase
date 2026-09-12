"""
TrackEase - Dataset Profiling

Purpose:
    Generate a detailed first-level profile of the raw railway datasets.

This module is read-only. It does not modify or overwrite the original
datasets stored inside data/raw/.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Project Configuration
# ---------------------------------------------------------------------------

# Identify the root directory of the TrackEase project.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Location of the untouched source datasets.
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"


# ---------------------------------------------------------------------------
# Dataset Loading
# ---------------------------------------------------------------------------

def load_datasets() -> dict[str, pd.DataFrame]:
    """
    Load the primary TrackEase CSV datasets.

    Returns:
        A dictionary containing the train, station, and stop DataFrames.
    """

    return {
        "trains": pd.read_csv(RAW_DATA_DIR / "trains.csv"),
        "stations": pd.read_csv(RAW_DATA_DIR / "stations.csv"),
        "stops": pd.read_csv(RAW_DATA_DIR / "stops.csv"),
    }


# ---------------------------------------------------------------------------
# Dataset Profiling
# ---------------------------------------------------------------------------

def profile_dataset(name: str, dataframe: pd.DataFrame) -> None:
    """
    Display structural and data-quality information for one dataset.

    Args:
        name: Human-readable name of the dataset.
        dataframe: Pandas DataFrame to inspect.
    """

    print("\n" + "=" * 80)
    print(f"DATASET: {name.upper()}")
    print("=" * 80)

    # Basic dimensions.
    print(f"\nRows    : {len(dataframe):,}")
    print(f"Columns : {len(dataframe.columns):,}")

    # Column names.
    print("\nColumns:")
    for column in dataframe.columns:
        print(f"  - {column}")

    # Data types.
    print("\nData Types:")
    print(dataframe.dtypes.to_string())

    # Missing-value analysis.
    print("\nMissing Values:")
    missing_values = dataframe.isna().sum()

    for column, count in missing_values.items():
        print(f"  - {column}: {count:,}")

    # Duplicate-row analysis.
    duplicate_count = dataframe.duplicated().sum()

    print(f"\nDuplicate Rows: {duplicate_count:,}")


# ---------------------------------------------------------------------------
# Application Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the TrackEase dataset profiling process."""

    datasets = load_datasets()

    for name, dataframe in datasets.items():
        profile_dataset(name, dataframe)


if __name__ == "__main__":
    main()