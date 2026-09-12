"""
TrackEase - Maintenance Dataset Inspection

Purpose:
    Inspect the available maintenance datasets before integrating them
    into the TrackEase pipeline.

This script does NOT modify any dataset.
"""

from pathlib import Path
import pandas as pd


# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MAINTENANCE_DIR = PROJECT_ROOT / "data" / "raw" / "maintenance"


DATASETS = [
    "indian_railway_failure_detection_maintenance_v2.csv",
    "indian_railway_predictive_maintenance_100k.csv",
]


# ---------------------------------------------------------
# Inspection function
# ---------------------------------------------------------

def inspect_dataset(file_path: Path) -> None:
    print("\n" + "=" * 80)
    print(f"DATASET: {file_path.name}")
    print("=" * 80)

    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}")
        return

    df = pd.read_csv(file_path)

    print(f"\nRows        : {len(df):,}")
    print(f"Columns     : {len(df.columns)}")
    print(f"File size   : {file_path.stat().st_size / (1024 * 1024):.2f} MB")

    print("\n" + "-" * 80)
    print("COLUMNS")
    print("-" * 80)

    for i, column in enumerate(df.columns, start=1):
        print(f"{i:2}. {column}")

    print("\n" + "-" * 80)
    print("DATA TYPES")
    print("-" * 80)

    print(df.dtypes.to_string())

    print("\n" + "-" * 80)
    print("MISSING VALUES")
    print("-" * 80)

    missing = df.isnull().sum()
    missing = missing[missing > 0].sort_values(ascending=False)

    if missing.empty:
        print("No missing values.")
    else:
        for column, count in missing.items():
            percentage = (count / len(df)) * 100
            print(f"{column:<35} {count:>8,} ({percentage:6.2f}%)")

    print("\n" + "-" * 80)
    print("SAMPLE RECORDS")
    print("-" * 80)

    print(df.head(3).to_string(index=False))

    print("\n" + "-" * 80)
    print("UNIQUE VALUES FOR LOW-CARDINALITY COLUMNS")
    print("-" * 80)

    for column in df.columns:
        unique_count = df[column].nunique(dropna=True)

        if unique_count <= 15:
            print(f"\n{column} ({unique_count} unique values):")
            print(df[column].value_counts(dropna=False).to_string())


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main() -> None:
    print("=" * 80)
    print("TrackEase - Maintenance Dataset Inspection")
    print("=" * 80)

    print(f"\nMaintenance directory:")
    print(MAINTENANCE_DIR)

    for dataset_name in DATASETS:
        dataset_path = MAINTENANCE_DIR / dataset_name
        inspect_dataset(dataset_path)

    print("\n" + "=" * 80)
    print("INSPECTION COMPLETE")
    print("=" * 80)
    print("\nNo files were modified.")


if __name__ == "__main__":
    main()