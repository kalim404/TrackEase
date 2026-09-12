"""
TrackEase - Halt Duration Pattern Verification

Purpose:
    Verify whether unusually large halt durations are caused by
    whole-day offsets in the source dataset.

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
# Helper Functions
# ---------------------------------------------------------------------------

def time_to_minutes(time_value):
    """Convert an HH:MM time value into minutes after midnight."""

    if pd.isna(time_value):
        return None

    try:
        hours, minutes = map(int, str(time_value).split(":"))
        return hours * 60 + minutes
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Main Analysis
# ---------------------------------------------------------------------------

def main() -> None:
    """Verify the pattern behind unusually large halt durations."""

    stops = pd.read_csv(RAW_DATA_DIR / "stops.csv")

    # Keep only records where both arrival and departure are available.
    valid = stops.dropna(subset=["arrival", "departure"]).copy()

    valid["arrival_minutes"] = valid["arrival"].apply(time_to_minutes)
    valid["departure_minutes"] = valid["departure"].apply(time_to_minutes)

    # Calculate the difference using only the displayed clock times.
    valid["clock_difference"] = (
        valid["departure_minutes"]
        - valid["arrival_minutes"]
    )

    # If departure is after midnight, account for one day.
    valid["clock_difference_adjusted"] = valid["clock_difference"]

    overnight = valid["clock_difference_adjusted"] < 0

    valid.loc[overnight, "clock_difference_adjusted"] += 1440

    # Compare source halt with the adjusted clock difference.
    valid["difference"] = (
        valid["halt_min"]
        - valid["clock_difference_adjusted"]
    )

    # Determine whether the difference is an exact number of days.
    valid["day_offset"] = valid["difference"] / 1440

    suspicious = valid[valid["halt_min"] > 60].copy()

    print("\n" + "=" * 80)
    print("TrackEase - Halt Duration Pattern Verification")
    print("=" * 80)

    print(f"\nTotal stop records              : {len(stops):,}")
    print(f"Records with arrival + departure: {len(valid):,}")
    print(f"Suspicious halt records         : {len(suspicious):,}")

    # -----------------------------------------------------------------------
    # Pattern classification
    # -----------------------------------------------------------------------

    exact_one_day = suspicious[
        suspicious["difference"] == 1440
    ]

    exact_two_days = suspicious[
        suspicious["difference"] == 2880
    ]

    exact_zero = suspicious[
        suspicious["difference"] == 0
    ]

    other = suspicious[
        ~suspicious["difference"].isin([0, 1440, 2880])
    ]

    print("\n[1] PATTERN CLASSIFICATION")
    print("-" * 80)

    print(f"Exact clock difference       : {len(exact_zero):,}")
    print(f"Clock difference + 1 day     : {len(exact_one_day):,}")
    print(f"Clock difference + 2 days    : {len(exact_two_days):,}")
    print(f"Other differences            : {len(other):,}")

    # -----------------------------------------------------------------------
    # Show other unexplained records
    # -----------------------------------------------------------------------

    print("\n[2] UNEXPLAINED SUSPICIOUS RECORDS")
    print("-" * 80)

    if other.empty:
        print("No unexplained suspicious records found.")
    else:
        columns = [
            "train_number",
            "seq",
            "station_code",
            "day",
            "arrival",
            "departure",
            "halt_min",
            "clock_difference_adjusted",
            "difference",
            "day_offset",
        ]

        print(
            other.sort_values(
                "halt_min",
                ascending=False
            )[columns].to_string(index=False)
        )

    # -----------------------------------------------------------------------
    # Show the calculated pattern
    # -----------------------------------------------------------------------

    print("\n[3] EXAMPLES OF DAY OFFSETS")
    print("-" * 80)

    examples = suspicious[
        suspicious["difference"].isin([1440, 2880])
    ].copy()

    examples["offset_description"] = examples["difference"].map(
        {
            1440: "1 extra day",
            2880: "2 extra days",
        }
    )

    print(
        examples[
            [
                "train_number",
                "station_code",
                "arrival",
                "departure",
                "halt_min",
                "clock_difference_adjusted",
                "offset_description",
            ]
        ]
        .sort_values("halt_min", ascending=False)
        .head(20)
        .to_string(index=False)
    )

    print("\n" + "=" * 80)
    print("Halt duration pattern verification completed.")
    print("=" * 80)


if __name__ == "__main__":
    main()