"""
TrackEase - Maintenance Data Preparation

Purpose:
    Prepare the primary predictive-maintenance dataset for use by
    the TrackEase block-planning pipeline.

Input:
    data/raw/maintenance/indian_railway_predictive_maintenance_100k.csv

Outputs:
    data/processed/maintenance_prepared.csv
    data/processed/maintenance_preparation_report.txt

Important:
    - Raw data is never modified.
    - Missing values are handled conservatively.
    - Failure labels are standardized.
    - Invalid duplicate rows are removed.
    - The output becomes the clean maintenance-data layer for TrackEase.
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
    / "raw"
    / "maintenance"
    / "indian_railway_predictive_maintenance_100k.csv"
)

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

OUTPUT_FILE = PROCESSED_DIR / "maintenance_prepared.csv"

REPORT_FILE = PROCESSED_DIR / "maintenance_preparation_report.txt"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CATEGORICAL_COLUMNS = [
    "region",
    "season",
    "train_type",
    "ballast_condition",
    "signal_system_status",
]

FAILURE_COLUMNS = [
    "failure_type",
    "failure_severity",
]

NUMERIC_COLUMNS_TO_FILL = [
    "track_vibration_level",
    "ambient_temperature_c",
    "humidity_percent",
    "rainfall_mm",
    "wind_speed_kmph",
    "wheel_wear_percent",
    "axle_temperature_c",
    "brake_pad_wear_percent",
    "bearing_temperature_c",
    "battery_voltage",
    "traction_motor_temp_c",
    "load_factor_percent",
    "delay_minutes",
    "last_maintenance_days",
]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def print_header(title: str) -> None:
    """Print a formatted console section heading."""

    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def standardize_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove unnecessary spaces from categorical text columns.

    Existing category names are preserved.
    """

    columns = CATEGORICAL_COLUMNS + FAILURE_COLUMNS

    for column in columns:
        if column in df.columns:
            df[column] = df[column].astype("string").str.strip()

    return df


def handle_failure_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace missing failure labels with 'None'.

    Missing failure_type/failure_severity largely represents records
    where maintenance was not required, so keeping an explicit label
    is clearer than leaving them as NaN.
    """

    for column in FAILURE_COLUMNS:
        if column in df.columns:
            df[column] = df[column].fillna("None")

    return df


def fill_numeric_missing_values(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Fill missing numeric sensor values using the median.

    Median imputation is used because it is less sensitive to outliers
    than the mean and is appropriate for this prototype preparation layer.
    """

    filled_values = {}

    for column in NUMERIC_COLUMNS_TO_FILL:
        if column not in df.columns:
            continue

        missing_count = df[column].isna().sum()

        if missing_count == 0:
            continue

        median_value = df[column].median()

        df[column] = df[column].fillna(median_value)

        filled_values[column] = {
            "missing_count": int(missing_count),
            "median": float(median_value),
        }

    return df, filled_values


def create_planning_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create simple TrackEase-specific maintenance planning features.

    These features do not perform ML prediction. They organize existing
    information into fields that the future block planner can consume.
    """

    # ---------------------------------------------------------------
    # Maintenance need
    # ---------------------------------------------------------------

    df["maintenance_needed"] = (
        pd.to_numeric(df["maintenance_required"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    # ---------------------------------------------------------------
    # Severity priority
    # ---------------------------------------------------------------

    severity_priority = {
        "None": 0,
        "Low": 1,
        "Medium": 2,
        "High": 3,
        "Critical": 4,
    }

    df["severity_priority"] = (
        df["failure_severity"]
        .map(severity_priority)
        .fillna(0)
        .astype(int)
    )

    # ---------------------------------------------------------------
    # Infrastructure warning indicator
    # ---------------------------------------------------------------

    df["infrastructure_warning"] = (
        (df["ballast_condition"].isin(["Fair", "Poor"]))
        | (df["signal_system_status"].isin(["Warning", "Fault"]))
    ).astype(int)

    # ---------------------------------------------------------------
    # High-risk flag
    # ---------------------------------------------------------------

    risk_threshold = df["risk_score"].quantile(0.75)

    df["high_risk_flag"] = (
        df["risk_score"] >= risk_threshold
    ).astype(int)

    return df


def prepare_maintenance_data() -> None:
    """Run the complete maintenance-data preparation workflow."""

    print_header("TrackEase - Maintenance Data Preparation")

    print(f"\nProject root:")
    print(f"  {PROJECT_ROOT}")

    print(f"\nInput file:")
    print(f"  {INPUT_FILE}")

    # ---------------------------------------------------------------
    # Validate input
    # ---------------------------------------------------------------

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Maintenance dataset not found:\n{INPUT_FILE}"
        )

    print("  ✓ Input file found")

    # ---------------------------------------------------------------
    # Load dataset
    # ---------------------------------------------------------------

    df = pd.read_csv(INPUT_FILE)

    original_rows = len(df)
    original_columns = len(df.columns)

    print(f"\nRows loaded    : {original_rows:,}")
    print(f"Columns loaded : {original_columns}")

    # ---------------------------------------------------------------
    # Remove exact duplicate rows
    # ---------------------------------------------------------------

    duplicate_count = int(df.duplicated().sum())

    if duplicate_count > 0:
        df = df.drop_duplicates().copy()

    # ---------------------------------------------------------------
    # Standardize textual values
    # ---------------------------------------------------------------

    df = standardize_text_columns(df)

    # ---------------------------------------------------------------
    # Handle failure labels
    # ---------------------------------------------------------------

    df = handle_failure_labels(df)

    # ---------------------------------------------------------------
    # Fill numeric missing values
    # ---------------------------------------------------------------

    df, filled_values = fill_numeric_missing_values(df)

    # ---------------------------------------------------------------
    # Create TrackEase planning features
    # ---------------------------------------------------------------

    df = create_planning_features(df)

    # ---------------------------------------------------------------
    # Create output directory
    # ---------------------------------------------------------------

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------
    # Save prepared dataset
    # ---------------------------------------------------------------

    df.to_csv(OUTPUT_FILE, index=False)

    # ---------------------------------------------------------------
    # Generate preparation report
    # ---------------------------------------------------------------

    remaining_missing = df.isna().sum()
    remaining_missing = remaining_missing[remaining_missing > 0]

    maintenance_required_count = int(df["maintenance_needed"].sum())

    high_risk_count = int(df["high_risk_flag"].sum())

    infrastructure_warning_count = int(
        df["infrastructure_warning"].sum()
    )

    report_lines = [
        "=" * 72,
        "TrackEase Maintenance Data Preparation Report",
        "=" * 72,
        "",
        f"Project root             : {PROJECT_ROOT}",
        f"Input file               : {INPUT_FILE}",
        f"Output file              : {OUTPUT_FILE}",
        "",
        "DATASET SUMMARY",
        "-" * 72,
        f"Original rows            : {original_rows:,}",
        f"Final rows               : {len(df):,}",
        f"Original columns         : {original_columns}",
        f"Final columns            : {len(df.columns)}",
        f"Duplicate rows removed   : {duplicate_count:,}",
        "",
        "PLANNING FEATURES",
        "-" * 72,
        f"Maintenance-needed rows  : {maintenance_required_count:,}",
        f"High-risk rows           : {high_risk_count:,}",
        f"Infrastructure warnings  : {infrastructure_warning_count:,}",
        "",
        "NUMERIC MISSING-VALUE HANDLING",
        "-" * 72,
    ]

    if filled_values:
        for column, info in filled_values.items():
            report_lines.append(
                f"{column:<32} "
                f"{info['missing_count']:>8,} values "
                f"filled with median {info['median']:.4f}"
            )
    else:
        report_lines.append("No numeric missing values required filling.")

    report_lines.extend(
        [
            "",
            "REMAINING MISSING VALUES",
            "-" * 72,
        ]
    )

    if remaining_missing.empty:
        report_lines.append("No remaining missing values.")
    else:
        for column, count in remaining_missing.items():
            report_lines.append(
                f"{column:<32} {int(count):>8,}"
            )

    report_lines.extend(
        [
            "",
            "NEW TRACKEASE COLUMNS",
            "-" * 72,
            "maintenance_needed",
            "severity_priority",
            "infrastructure_warning",
            "high_risk_flag",
            "",
            "NOTES",
            "-" * 72,
            (
                "Maintenance train_id values are retained from the source "
                "dataset but are NOT assumed to match the railway schedule "
                "train_number values."
            ),
            (
                "The raw maintenance dataset was not modified."
            ),
            (
                "This prepared dataset is intended for future maintenance "
                "priority analysis and block-planning integration."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    # ---------------------------------------------------------------
    # Console summary
    # ---------------------------------------------------------------

    print_header("PREPARATION COMPLETE")

    print(f"\nOriginal rows        : {original_rows:,}")
    print(f"Final rows           : {len(df):,}")
    print(f"Duplicates removed   : {duplicate_count:,}")
    print(f"Final columns        : {len(df.columns)}")

    print("\nCreated TrackEase features:")
    print("  ✓ maintenance_needed")
    print("  ✓ severity_priority")
    print("  ✓ infrastructure_warning")
    print("  ✓ high_risk_flag")

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print("\nRaw maintenance data was NOT modified.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    prepare_maintenance_data()