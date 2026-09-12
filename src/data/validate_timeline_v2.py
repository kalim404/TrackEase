"""
TrackEase - Timeline Validation V2

Validates train schedules using stop sequence and clock time.

Unlike the first validator, this version does not assume that the
dataset's `day` field changes exactly when the clock crosses midnight.

The validator builds a continuous timeline from the sequence of stops
and detects genuine backwards movements in time.

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


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def time_to_minutes(time_value):
    """Convert HH:MM into minutes from midnight."""

    if pd.isna(time_value):
        return None

    hours, minutes = map(int, str(time_value).split(":"))

    return hours * 60 + minutes


# ---------------------------------------------------------------------------
# Timeline validation
# ---------------------------------------------------------------------------

def validate_train_timeline(train):
    """
    Validate the chronological order of one train's stops.

    The source `day` field is not used to force chronological order.
    Instead, clock times are converted into a continuous timeline.

    When the next time is earlier than the previous time, one day
    (1440 minutes) is added to represent an overnight transition.
    """

    train = train.sort_values("seq")

    previous_departure = None
    previous_seq = None
    previous_station = None

    issues = []

    for _, row in train.iterrows():

        arrival = time_to_minutes(row["arrival"])
        departure = time_to_minutes(row["departure"])

        # ---------------------------------------------------------------
        # Establish arrival time on the continuous timeline.
        # ---------------------------------------------------------------

        if arrival is not None:

            current_arrival = arrival

            if (
                previous_departure is not None
                and current_arrival < previous_departure
            ):
                current_arrival += 1440

            # If the arrival is still earlier, the schedule is suspicious.
            if (
                previous_departure is not None
                and current_arrival < previous_departure
            ):
                issues.append(
                    {
                        "seq": row["seq"],
                        "station": row["station_code"],
                        "issue": "Arrival occurs before previous departure",
                    }
                )

        else:
            current_arrival = None

        # ---------------------------------------------------------------
        # Establish departure time.
        # ---------------------------------------------------------------

        if departure is not None:

            current_departure = departure

            if (
                current_arrival is not None
                and current_departure < current_arrival
            ):
                current_departure += 1440

            # Departure must not be before arrival.
            if (
                current_arrival is not None
                and current_departure < current_arrival
            ):
                issues.append(
                    {
                        "seq": row["seq"],
                        "station": row["station_code"],
                        "issue": "Departure occurs before arrival",
                    }
                )

        else:
            current_departure = None

        # ---------------------------------------------------------------
        # Store departure for comparison with the next stop.
        # ---------------------------------------------------------------

        if current_departure is not None:

            previous_departure = current_departure
            previous_seq = row["seq"]
            previous_station = row["station_code"]

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Validate timelines for all trains."""

    stops = pd.read_csv(STOPS_FILE)

    stops = stops.sort_values(
        ["train_number", "seq"]
    ).reset_index(drop=True)

    total_trains = stops["train_number"].nunique()

    all_issues = []

    for train_number, train in stops.groupby(
        "train_number",
        sort=False
    ):

        issues = validate_train_timeline(train)

        for issue in issues:
            issue["train"] = train_number
            all_issues.append(issue)

    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------

    print("\n" + "=" * 70)
    print("TrackEase - Timeline Validation V2")
    print("=" * 70)

    print(f"\nTotal trains checked : {total_trains:,}")
    print(f"Timeline issues      : {len(all_issues):,}")

    print("\n" + "-" * 70)
    print("RESULT")
    print("-" * 70)

    if not all_issues:

        print("Timeline validation passed.")
        print(
            "Train stop sequences are chronologically consistent "
            "when overnight transitions are allowed."
        )

    else:

        print("Timeline issues detected.")
        print("\nExamples:")

        for issue in all_issues[:20]:
            print(issue)

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()