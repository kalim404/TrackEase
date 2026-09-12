"""
TrackEase - Train Timeline Validation

Checks whether the day, arrival time, and departure time
form a logically increasing journey timeline for each train.

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
    """Convert HH:MM time into minutes from midnight."""
    if pd.isna(time_value):
        return None

    hours, minutes = map(int, str(time_value).split(":"))
    return hours * 60 + minutes


def absolute_minutes(day, time_value):
    """
    Convert journey day + HH:MM into minutes from the beginning
    of Day 1.
    """
    minutes = time_to_minutes(time_value)

    if minutes is None:
        return None

    return (int(day) - 1) * 1440 + minutes


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def main():
    """Load the stops dataset and validate train timelines."""

    stops = pd.read_csv(STOPS_FILE)

    # Sort records so every train is processed in route order.
    stops = stops.sort_values(["train_number", "seq"]).reset_index(drop=True)

    total_trains = stops["train_number"].nunique()

    stop_time_issues = []
    journey_time_issues = []

    for train_number, train in stops.groupby("train_number", sort=False):

        train = train.sort_values("seq")

        previous_departure = None
        previous_seq = None

        for _, row in train.iterrows():

            arrival = absolute_minutes(row["day"], row["arrival"])
            departure = absolute_minutes(row["day"], row["departure"])

            # ---------------------------------------------------------------
            # Check arrival -> departure
            # ---------------------------------------------------------------

            if arrival is not None and departure is not None:

                # A departure earlier than arrival may indicate
                # an overnight transition.
                if departure < arrival:
                    departure += 1440

                if departure < arrival:
                    stop_time_issues.append(
                        {
                            "train": train_number,
                            "seq": row["seq"],
                            "issue": "Departure before arrival",
                        }
                    )

            # ---------------------------------------------------------------
            # Check previous departure -> current arrival
            # ---------------------------------------------------------------

            if previous_departure is not None and arrival is not None:

                current_arrival = arrival

                # If the source day/time combination produces an
                # impossible backwards movement, record it.
                if current_arrival < previous_departure:

                    journey_time_issues.append(
                        {
                            "train": train_number,
                            "previous_seq": previous_seq,
                            "current_seq": row["seq"],
                            "previous_departure": previous_departure,
                            "current_arrival": current_arrival,
                        }
                    )

            # Use departure as the reference for the next stop.
            if departure is not None:
                previous_departure = departure
                previous_seq = row["seq"]


    # -----------------------------------------------------------------------
    # Results
    # -----------------------------------------------------------------------

    print("\n" + "=" * 60)
    print("TrackEase - Train Timeline Validation")
    print("=" * 60)

    print(f"\nTotal trains checked              : {total_trains:,}")
    print(f"Stop-level timing issues         : {len(stop_time_issues):,}")
    print(f"Journey timeline issues          : {len(journey_time_issues):,}")

    print("\n" + "-" * 60)
    print("RESULT")
    print("-" * 60)

    if not stop_time_issues and not journey_time_issues:
        print("Timeline validation passed.")
        print("Day + arrival + departure form a consistent timeline.")
    else:
        print("Timeline issues detected.")
        print("These records need further investigation.")

    # Show a few examples if problems exist.
    if stop_time_issues:

        print("\nExample stop-level issues:")

        for issue in stop_time_issues[:10]:
            print(issue)

    if journey_time_issues:

        print("\nExample journey-level issues:")

        for issue in journey_time_issues[:10]:
            print(issue)


if __name__ == "__main__":
    main()