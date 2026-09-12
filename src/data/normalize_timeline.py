"""
TrackEase - Railway Timeline Normalization
==========================================

Purpose
-------
Normalize the raw railway stop/timetable dataset into a clean,
consistent timeline that can safely be used by TrackEase's
validation, scheduling, and optimization layers.

Input
-----
C:\\SIH_PROJECT\\data\\raw\\stops.csv

Expected raw columns
--------------------
train_number
seq
station_code
station_name
day
arrival
departure
halt_min
distance_km

Outputs
-------
data/processed/stops_normalized.csv
data/processed/timeline_normalization_report.txt

Important
---------
The original raw dataset is NEVER modified.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import pandas as pd


# ============================================================================
# PROJECT PATHS
# ============================================================================

# normalize_timeline.py is expected to be:
#
# C:\SIH_PROJECT\src\data\normalize_timeline.py
#
# Therefore:
#   parent      = data
#   parent[1]   = src
#   parent[2]   = project root

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

INPUT_FILE = RAW_DIR / "stops.csv"
OUTPUT_FILE = PROCESSED_DIR / "stops_normalized.csv"
REPORT_FILE = PROCESSED_DIR / "timeline_normalization_report.txt"


# ============================================================================
# EXPECTED SCHEMA
# ============================================================================

EXPECTED_COLUMNS = [
    "train_number",
    "seq",
    "station_code",
    "station_name",
    "day",
    "arrival",
    "departure",
    "halt_min",
    "distance_km",
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def normalize_column_name(column: object) -> str:
    """
    Convert a raw column name into a predictable snake_case name.

    Examples:
        'Train Number' -> 'train_number'
        'station-code' -> 'station_code'
        ' Arrival '   -> 'arrival'
    """
    value = str(column).strip().lower()

    value = re.sub(r"[\s\-\/]+", "_", value)
    value = re.sub(r"[^a-z0-9_]", "", value)
    value = re.sub(r"_+", "_", value)

    return value.strip("_")


def clean_string(value: object) -> str:
    """Return a safely stripped string."""
    if pd.isna(value):
        return ""

    return str(value).strip()


def normalize_train_number(value: object) -> Optional[str]:
    """
    Normalize train number while preserving leading zeroes when present.

    Examples:
        12345       -> '12345'
        ' 12345 '   -> '12345'
        12345.0     -> '12345'
    """
    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    # Handle values such as 12345.0 created by pandas.
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]

    # Keep only a clean train-number representation.
    text = re.sub(r"\s+", "", text)

    return text if text else None


def normalize_station_code(value: object) -> Optional[str]:
    """Normalize station code to uppercase."""
    if pd.isna(value):
        return None

    text = str(value).strip().upper()

    if not text:
        return None

    return text


def normalize_station_name(value: object) -> Optional[str]:
    """Normalize station name whitespace without changing its meaning."""
    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    text = re.sub(r"\s+", " ", text)

    return text


def normalize_day(value: object) -> Optional[int]:
    """
    Normalize day values.

    Accepted examples:
        1
        '1'
        'Day 1'
        'day1'
        2.0

    Returns:
        Integer day number or None.
    """
    if pd.isna(value):
        return None

    text = str(value).strip().lower()

    if not text:
        return None

    match = re.search(r"-?\d+", text)

    if not match:
        return None

    try:
        return int(match.group())
    except ValueError:
        return None


def parse_time_to_minutes(value: object) -> Optional[int]:
    """
    Convert a time value into minutes after midnight.

    Supported examples:
        00:00
        05:30
        23:59
        5:30 AM
        11:45 PM
        530
        0530

    Returns:
        Minutes after midnight, or None if invalid/missing.
    """
    if pd.isna(value):
        return None

    # Handle pandas time-like values.
    if hasattr(value, "hour") and hasattr(value, "minute"):
        try:
            return int(value.hour) * 60 + int(value.minute)
        except (TypeError, ValueError):
            pass

    text = str(value).strip()

    if not text:
        return None

    text_lower = text.lower()

    # Remove unnecessary whitespace.
    text_lower = re.sub(r"\s+", " ", text_lower)

    # ------------------------------------------------------------------------
    # AM / PM format
    # ------------------------------------------------------------------------

    am_pm_match = re.fullmatch(
        r"(\d{1,2})(?::(\d{1,2}))?(?::(\d{1,2}))?\s*(am|pm)",
        text_lower,
    )

    if am_pm_match:
        hour = int(am_pm_match.group(1))
        minute = int(am_pm_match.group(2) or 0)
        period = am_pm_match.group(4)

        if hour < 1 or hour > 12 or minute > 59:
            return None

        if period == "am":
            if hour == 12:
                hour = 0
        else:
            if hour != 12:
                hour += 12

        return hour * 60 + minute

    # ------------------------------------------------------------------------
    # HH:MM[:SS]
    # ------------------------------------------------------------------------

    colon_match = re.fullmatch(
        r"(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?",
        text_lower,
    )

    if colon_match:
        hour = int(colon_match.group(1))
        minute = int(colon_match.group(2))

        if hour > 23 or minute > 59:
            return None

        return hour * 60 + minute

    # ------------------------------------------------------------------------
    # Compact numeric time
    #
    # 530  -> 05:30
    # 0530 -> 05:30
    # 1530 -> 15:30
    # ------------------------------------------------------------------------

    numeric_match = re.fullmatch(r"\d{3,4}", text_lower)

    if numeric_match:
        digits = text_lower

        if len(digits) == 3:
            hour = int(digits[0])
            minute = int(digits[1:])
        else:
            hour = int(digits[:2])
            minute = int(digits[2:])

        if hour > 23 or minute > 59:
            return None

        return hour * 60 + minute

    return None


def minutes_to_hhmm(value: object) -> Optional[str]:
    """Convert minutes after midnight back into HH:MM."""
    if pd.isna(value):
        return None

    try:
        value = int(value)
    except (TypeError, ValueError):
        return None

    if value < 0 or value >= 24 * 60:
        return None

    hour = value // 60
    minute = value % 60

    return f"{hour:02d}:{minute:02d}"


def normalize_distance(value: object) -> Optional[float]:
    """
    Normalize distance values to kilometres.

    Commas are removed.

    Examples:
        '120.5'     -> 120.5
        '1,205.4'   -> 1205.4
    """
    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace(",", "")

    try:
        number = float(text)

        if number < 0:
            return None

        return number

    except ValueError:
        return None


def calculate_halt_minutes(
    arrival_minutes: Optional[int],
    departure_minutes: Optional[int],
) -> Optional[int]:
    """
    Calculate halt duration from arrival and departure.

    If departure is earlier than arrival, assume the departure
    is after midnight and therefore add 24 hours.

    Example:
        arrival   = 23:50
        departure = 00:10

        halt = 20 minutes
    """
    if arrival_minutes is None or departure_minutes is None:
        return None

    duration = departure_minutes - arrival_minutes

    if duration < 0:
        duration += 24 * 60

    return duration


def normalize_halt(value: object) -> Optional[float]:
    """Normalize an explicitly supplied halt duration."""
    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text:
        return None

    text = text.replace(",", "")

    try:
        number = float(text)

        if number < 0:
            return None

        return number

    except ValueError:
        return None


# ============================================================================
# INPUT LOADING
# ============================================================================

def load_input_file() -> pd.DataFrame:
    """Load the raw stops dataset."""
    print("=" * 72)
    print("TrackEase Timeline Normalization")
    print("=" * 72)

    print()
    print(f"Project root:")
    print(f"  {PROJECT_ROOT}")

    print()
    print(f"Input file:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"\nInput file was not found:\n{INPUT_FILE}\n\n"
            "Expected location:\n"
            f"{RAW_DIR}\\stops.csv"
        )

    print("  ✓ Input file found")

    try:
        df = pd.read_csv(
            INPUT_FILE,
            low_memory=False,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not read CSV file:\n{INPUT_FILE}\n\n"
            f"Original error: {exc}"
        ) from exc

    print()
    print(f"Rows loaded: {len(df):,}")
    print(f"Columns found: {list(df.columns)}")

    return df


# ============================================================================
# COLUMN STANDARDIZATION
# ============================================================================

def standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize all column names."""
    df = df.copy()

    df.columns = [
        normalize_column_name(column)
        for column in df.columns
    ]

    # Common alternative names.
    aliases = {
        "train_no": "train_number",
        "train_num": "train_number",
        "train": "train_number",

        "sequence": "seq",
        "sequence_no": "seq",
        "stop_sequence": "seq",

        "station": "station_code",
        "station_id": "station_code",
        "stn_code": "station_code",

        "stationname": "station_name",
        "stn_name": "station_name",

        "arrival_time": "arrival",
        "arr": "arrival",

        "departure_time": "departure",
        "dep": "departure",

        "halt": "halt_min",
        "halt_minutes": "halt_min",
        "halt_mins": "halt_min",

        "distance": "distance_km",
        "distance_km_from_origin": "distance_km",
    }

    rename_map = {
        column: aliases[column]
        for column in df.columns
        if column in aliases
    }

    if rename_map:
        df = df.rename(columns=rename_map)

    print()
    print("Standardized columns:")
    print(f"  {list(df.columns)}")

    missing = [
        column
        for column in EXPECTED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            "\nRequired columns are missing after standardization:\n"
            + "\n".join(f"  - {column}" for column in missing)
            + "\n\nExpected schema:\n"
            + ", ".join(EXPECTED_COLUMNS)
        )

    return df


# ============================================================================
# DATA NORMALIZATION
# ============================================================================

def normalize_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Normalize all timeline fields and collect statistics.
    """
    df = df.copy()

    original_row_count = len(df)

    stats = {
        "original_rows": original_row_count,
        "duplicate_rows_removed": 0,
        "missing_train_number": 0,
        "missing_station_code": 0,
        "missing_station_name": 0,
        "invalid_seq": 0,
        "invalid_day": 0,
        "invalid_arrival": 0,
        "invalid_departure": 0,
        "halt_filled_from_times": 0,
        "invalid_halt": 0,
        "invalid_distance": 0,
        "negative_distance": 0,
        "timeline_cross_midnight": 0,
        "invalid_timeline_rows": 0,
    }

    # ------------------------------------------------------------------------
    # Basic fields
    # ------------------------------------------------------------------------

    df["train_number"] = df["train_number"].apply(
        normalize_train_number
    )

    df["station_code"] = df["station_code"].apply(
        normalize_station_code
    )

    df["station_name"] = df["station_name"].apply(
        normalize_station_name
    )

    # ------------------------------------------------------------------------
    # Sequence
    # ------------------------------------------------------------------------

    df["seq"] = pd.to_numeric(
        df["seq"],
        errors="coerce",
    )

    invalid_seq_mask = (
        df["seq"].isna()
        | (df["seq"] <= 0)
    )

    stats["invalid_seq"] = int(invalid_seq_mask.sum())

    # Sequence numbers should be integer-like.
    df["seq"] = df["seq"].round().astype("Int64")

    # ------------------------------------------------------------------------
    # Day
    # ------------------------------------------------------------------------

    df["day"] = df["day"].apply(normalize_day)

    invalid_day_mask = (
        df["day"].isna()
        | (df["day"] <= 0)
    )

    stats["invalid_day"] = int(invalid_day_mask.sum())

    df["day"] = df["day"].astype("Int64")

    # ------------------------------------------------------------------------
    # Arrival/departure
    # ------------------------------------------------------------------------

    df["_arrival_minutes"] = df["arrival"].apply(
        parse_time_to_minutes
    )

    df["_departure_minutes"] = df["departure"].apply(
        parse_time_to_minutes
    )

    stats["invalid_arrival"] = int(
        df["_arrival_minutes"].isna().sum()
    )

    stats["invalid_departure"] = int(
        df["_departure_minutes"].isna().sum()
    )

    df["arrival"] = df["_arrival_minutes"].apply(
        minutes_to_hhmm
    )

    df["departure"] = df["_departure_minutes"].apply(
        minutes_to_hhmm
    )

    # ------------------------------------------------------------------------
    # Halt duration
    # ------------------------------------------------------------------------

    supplied_halt = df["halt_min"].apply(normalize_halt)

    calculated_halt = df.apply(
        lambda row: calculate_halt_minutes(
            row["_arrival_minutes"],
            row["_departure_minutes"],
        ),
        axis=1,
    )

    fill_halt_mask = (
        supplied_halt.isna()
        & calculated_halt.notna()
    )

    stats["halt_filled_from_times"] = int(
        fill_halt_mask.sum()
    )

    # Prefer supplied halt when valid.
    df["halt_min"] = supplied_halt

    df.loc[fill_halt_mask, "halt_min"] = calculated_halt[
        fill_halt_mask
    ]

    invalid_halt_mask = (
        df["halt_min"].isna()
        | (df["halt_min"] < 0)
    )

    stats["invalid_halt"] = int(
        invalid_halt_mask.sum()
    )

    df["halt_min"] = df["halt_min"].round(2)

    # ------------------------------------------------------------------------
    # Distance
    # ------------------------------------------------------------------------

    raw_distance = df["distance_km"].copy()

    df["distance_km"] = df["distance_km"].apply(
        normalize_distance
    )

    stats["invalid_distance"] = int(
        df["distance_km"].isna().sum()
    )

    stats["negative_distance"] = int(
        pd.to_numeric(
            raw_distance.astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        ).lt(0).sum()
    )

    df["distance_km"] = df["distance_km"].round(3)

    # ------------------------------------------------------------------------
    # Detect overnight stops
    # ------------------------------------------------------------------------

    overnight_mask = (
        df["_arrival_minutes"].notna()
        & df["_departure_minutes"].notna()
        & (
            df["_departure_minutes"]
            < df["_arrival_minutes"]
        )
    )

    stats["timeline_cross_midnight"] = int(
        overnight_mask.sum()
    )

    # ------------------------------------------------------------------------
    # Missing basic fields
    # ------------------------------------------------------------------------

    stats["missing_train_number"] = int(
        df["train_number"].isna().sum()
    )

    stats["missing_station_code"] = int(
        df["station_code"].isna().sum()
    )

    stats["missing_station_name"] = int(
        df["station_name"].isna().sum()
    )

    # ------------------------------------------------------------------------
    # Timeline validation flag
    # ------------------------------------------------------------------------

    invalid_timeline_mask = (
        df["train_number"].isna()
        | df["seq"].isna()
        | df["day"].isna()
        | df["station_code"].isna()
        | df["_arrival_minutes"].isna()
        | df["_departure_minutes"].isna()
    )

    stats["invalid_timeline_rows"] = int(
        invalid_timeline_mask.sum()
    )

    df["_timeline_valid"] = ~invalid_timeline_mask

    return df, stats


# ============================================================================
# TRAIN TIMELINE ORDERING
# ============================================================================

def sort_timeline(df: pd.DataFrame) -> pd.DataFrame:
    """
    Sort stops in logical railway timeline order.

    Primary order:
        train_number
        day
        sequence

    This is preferable to sorting only by clock time because
    railway journeys can cross midnight.
    """
    df = df.copy()

    df = df.sort_values(
        by=[
            "train_number",
            "day",
            "seq",
        ],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)

    return df


# ============================================================================
# DUPLICATE REMOVAL
# ============================================================================

def remove_exact_duplicates(
    df: pd.DataFrame,
    stats: dict,
) -> pd.DataFrame:
    """Remove exact duplicate rows without modifying the source file."""

    before = len(df)

    df = df.drop_duplicates(
        keep="first"
    ).reset_index(drop=True)

    removed = before - len(df)

    stats["duplicate_rows_removed"] = removed

    return df


# ============================================================================
# FINAL DATA TYPES
# ============================================================================

def finalize_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare the final output schema."""

    df = df.copy()

    # Remove internal helper columns.
    internal_columns = [
        "_arrival_minutes",
        "_departure_minutes",
        "_timeline_valid",
    ]

    df = df.drop(
        columns=[
            column
            for column in internal_columns
            if column in df.columns
        ]
    )

    # Keep only the intended normalized schema.
    df = df[
        EXPECTED_COLUMNS
    ]

    # Final data types.
    df["train_number"] = df["train_number"].astype("string")
    df["station_code"] = df["station_code"].astype("string")
    df["station_name"] = df["station_name"].astype("string")

    df["seq"] = pd.to_numeric(
        df["seq"],
        errors="coerce",
    ).astype("Int64")

    df["day"] = pd.to_numeric(
        df["day"],
        errors="coerce",
    ).astype("Int64")

    df["halt_min"] = pd.to_numeric(
        df["halt_min"],
        errors="coerce",
    )

    df["distance_km"] = pd.to_numeric(
        df["distance_km"],
        errors="coerce",
    )

    return df


# ============================================================================
# REPORT GENERATION
# ============================================================================

def create_report(
    df: pd.DataFrame,
    stats: dict,
) -> str:
    """Create a human-readable normalization report."""

    train_count = df["train_number"].nunique(
        dropna=True
    )

    station_count = df["station_code"].nunique(
        dropna=True
    )

    route_count = (
        df.groupby("train_number", dropna=True)
        .ngroups
    )

    missing_values = {
        column: int(df[column].isna().sum())
        for column in EXPECTED_COLUMNS
    }

    report_lines = [
        "=" * 72,
        "TrackEase Timeline Normalization Report",
        "=" * 72,
        "",
        f"Project root              : {PROJECT_ROOT}",
        f"Input file                : {INPUT_FILE}",
        f"Output file               : {OUTPUT_FILE}",
        "",
        "DATASET SUMMARY",
        "-" * 72,
        f"Original rows             : {stats['original_rows']:,}",
        f"Final rows                : {len(df):,}",
        f"Duplicate rows removed    : {stats['duplicate_rows_removed']:,}",
        f"Unique trains             : {train_count:,}",
        f"Unique stations           : {station_count:,}",
        f"Train timelines           : {route_count:,}",
        "",
        "NORMALIZATION",
        "-" * 72,
        f"Invalid sequence values   : {stats['invalid_seq']:,}",
        f"Invalid day values        : {stats['invalid_day']:,}",
        f"Invalid arrival times     : {stats['invalid_arrival']:,}",
        f"Invalid departure times   : {stats['invalid_departure']:,}",
        f"Halt values calculated    : {stats['halt_filled_from_times']:,}",
        f"Invalid halt values       : {stats['invalid_halt']:,}",
        f"Invalid distance values   : {stats['invalid_distance']:,}",
        f"Negative distances        : {stats['negative_distance']:,}",
        f"Overnight timeline stops  : {stats['timeline_cross_midnight']:,}",
        f"Invalid timeline rows     : {stats['invalid_timeline_rows']:,}",
        "",
        "MISSING VALUES AFTER NORMALIZATION",
        "-" * 72,
    ]

    for column, count in missing_values.items():
        report_lines.append(
            f"{column:<25}: {count:,}"
        )

    report_lines.extend(
        [
            "",
            "FINAL SCHEMA",
            "-" * 72,
        ]
    )

    for column in df.columns:
        report_lines.append(
            f"{column:<25}: {df[column].dtype}"
        )

    report_lines.extend(
        [
            "",
            "STATUS",
            "-" * 72,
        ]
    )

    if stats["invalid_timeline_rows"] == 0:
        report_lines.append(
            "✓ All rows have the required timeline fields."
        )
    else:
        report_lines.append(
            "⚠ Some rows contain invalid or missing timeline fields."
        )

    if stats["duplicate_rows_removed"] > 0:
        report_lines.append(
            "✓ Exact duplicate rows were removed from the normalized output."
        )
    else:
        report_lines.append(
            "✓ No exact duplicate rows were found."
        )

    report_lines.extend(
        [
            "",
            "NOTE",
            "-" * 72,
            "The original raw CSV was not modified.",
            "The normalized dataset is intended for the next TrackEase",
            "timeline validation and scheduling stages.",
            "",
            "=" * 72,
        ]
    )

    return "\n".join(report_lines)


# ============================================================================
# SAVE OUTPUT
# ============================================================================

def save_outputs(
    df: pd.DataFrame,
    report: str,
) -> None:
    """Save normalized CSV and report."""

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    REPORT_FILE.write_text(
        report,
        encoding="utf-8",
    )

    print()
    print("Output files:")
    print(f"  ✓ {OUTPUT_FILE}")
    print(f"  ✓ {REPORT_FILE}")


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main() -> int:
    """Run the complete normalization pipeline."""

    try:
        # 1. Load
        df = load_input_file()

        # 2. Standardize schema
        df = standardize_columns(df)

        # 3. Normalize values
        df, stats = normalize_data(df)

        # 4. Remove exact duplicates
        df = remove_exact_duplicates(
            df,
            stats,
        )

        # 5. Sort timeline
        df = sort_timeline(df)

        # 6. Finalize schema
        df = finalize_schema(df)

        # 7. Create report
        report = create_report(
            df,
            stats,
        )

        # 8. Save
        save_outputs(
            df,
            report,
        )

        # --------------------------------------------------------------------
        # Console summary
        # --------------------------------------------------------------------

        print()
        print("=" * 72)
        print("NORMALIZATION COMPLETE")
        print("=" * 72)

        print()
        print(f"Input rows : {stats['original_rows']:,}")
        print(f"Output rows: {len(df):,}")
        print(
            f"Duplicates : {stats['duplicate_rows_removed']:,}"
        )

        print()
        print("Final columns:")
        print(
            "  "
            + ", ".join(df.columns)
        )

        print()
        print("Next step:")
        print(
            "Run the TrackEase timeline validator against "
            "stops_normalized.csv."
        )

        print()
        print("=" * 72)

        return 0

    except FileNotFoundError as exc:
        print()
        print("ERROR: INPUT FILE NOT FOUND")
        print("-" * 72)
        print(str(exc))
        return 1

    except ValueError as exc:
        print()
        print("ERROR: DATA/SCHEMA PROBLEM")
        print("-" * 72)
        print(str(exc))
        return 1

    except Exception as exc:
        print()
        print("ERROR: NORMALIZATION FAILED")
        print("-" * 72)
        print(f"{type(exc).__name__}: {exc}")
        return 1


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    sys.exit(main())