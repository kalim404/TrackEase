"""
TrackEase - Timeline Issue Investigation

Displays the schedule records around known timeline issues
so we can understand how the day, arrival, and departure
fields behave.

This script only reads the raw dataset.
It does NOT modify any files.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# File path
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STOPS_FILE = PROJECT_ROOT / "data" / "raw" / "stops.csv"


# ---------------------------------------------------------------------------
# Main investigation
# ---------------------------------------------------------------------------

def main():
    """Display records around selected timeline issues."""

    stops = pd.read_csv(STOPS_FILE)

    # Trains identified by the timeline validation script.
    problem_trains = [290, 391, 902, 4013, 4113]

    for train_number in problem_trains:

        train = stops[
            stops["train_number"] == train_number
        ].sort_values("seq")

        print("\n" + "=" * 80)
        print(f"TRAIN {train_number}")
        print("=" * 80)

        print(
            train[
                [
                    "seq",
                    "station_code",
                    "station_name",
                    "day",
                    "arrival",
                    "departure",
                    "halt_min",
                    "distance_km",
                ]
            ].to_string(index=False)
        )

    print("\n" + "=" * 80)
    print("Investigation complete.")
    print("=" * 80)


if __name__ == "__main__":
    main()