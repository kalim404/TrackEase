"""
TrackEase - Timeline Validation V3

Validates train schedules using the dataset's `day` field as the
primary calendar reference while correctly handling overnight
arrival/departure times within a stop.

This script only analyzes the raw dataset.
It does NOT modify any raw files.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STOPS_FILE = PROJECT_ROOT / "data" / "raw" / "stops.csv"


MINUTES_PER_DAY = 1440


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def time_to_minutes(time_value):
    """Convert HH:MM into minutes from midnight."""

    if pd.isna(time_value):
        return None

    hours, minutes = map(int, str(time_value).split(":"))

    return hours * 60 + minutes


def day_time_to_minutes(day, time_value):
    """
    Convert dataset day + HH:MM into an absolute minute value.

    Day 1 starts at minute 0.
    """

    minutes = time_to_minutes(time_value)

    if minutes is None:
        return None

    return (int(day) - 1) * MINUTES_PER_DAY + minutes


# ---------------------------------------------------------------------------
# Train validation
# ---------------------------------------------------------------------------

def validate_train(train):
    """
    Validate the timeline of one train.

    Rules:
    1. The dataset's `day` column is the primary calendar reference.
    2. Arrival and departure at the same stop may cross midnight.
    3. A later stop must not occur before the previous departure.
    """

    train = train.sort_values("seq")

    previous_departure = None
    previous_seq = None
    previous_station = None

    issues = []

    for _, row in train.iterrows():

        arrival = day_time_to_minutes(
            row["day"],
            row["arrival"]
        )

        departure = day_time_to_minutes(
            row["day"],
            row["departure"]
        )

        # ---------------------------------------------------------------
        # Handle arrival -> departure at the same stop.
        #
        # Example:
        # Day 3: 23:10 -> 01:45
        #
        # The departure belongs to the following calendar day.
        # ---------------------------------------------------------------

        if (
            arrival is not None
            and departure is not None
            and departure < arrival
        ):
            departure += MINUTES_PER_DAY

        # ---------------------------------------------------------------
        # Check current arrival against previous departure.
        # ---------------------------------------------------------------

        if (
            previous_departure is not None
            and arrival is not None
            and arrival < previous_departure
        ):

            issues.append(
                {
                    "train": row["train_number"],
                    "previous_seq": previous_seq,
                    "previous_station": previous_station,
                    "current_seq": row["seq"],
                    "current_station": row["station_code"],
                    "current_day": row["day"],
                    "current_arrival": row["arrival"],
                    "previous_departure_minutes":
                        previous_departure,
                    "current_arrival_minutes":
                        arrival,
                    "difference_minutes":
                        previous_departure - arrival,
                }
            )

        # ---------------------------------------------------------------
        # Store current departure.
        # ---------------------------------------------------------------

        if departure is not None:

            previous_departure = departure
            previous_seq = row["seq"]
            previous_station = row["station_code"]

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Validate all train timelines."""

    stops = pd.read_csv(STOPS_FILE)

    stops = stops.sort_values(
        ["train_number", "seq"]
    ).reset_index(drop=True)

    total_trains = stops["train_number"].nunique()

    all_issues = []

    for _, train in stops.groupby(
        "train_number",
        sort=False
    ):

        issues = validate_train(train)
        all_issues.extend(issues)

    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------

    print("\n" + "=" * 70)
    print("TrackEase - Timeline Validation V3")
    print("=" * 70)

    print(f"\nTotal trains checked : {total_trains:,}")
    print(f"Timeline issues      : {len(all_issues):,}")

    print("\n" + "-" * 70)
    print("RESULT")
    print("-" * 70)

    if not all_issues:

        print("Timeline validation passed.")
        print(
            "No train was found to move backwards in time "
            "after accounting for overnight stop transitions."
        )

    else:

        print("Timeline issues detected.")

        print("\nExamples:")

        for issue in all_issues[:20]:
            print(issue)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()