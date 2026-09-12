"""
TrackEase - COA Goods Train Forecast Adapter

Purpose:
    Build a controlled prototype representation of goods-train forecasts
    from the Control Office / COA side of the SIH26027 architecture.

Inputs:
    data/processed/coordinated_planning_tasks.csv
    data/processed/railway_sections.csv

Outputs:
    data/processed/coa_goods_forecast.csv
    data/processed/coa_goods_forecast_report.txt

Important:
    - TrackEase does NOT claim live COA connectivity.
    - Forecasts are deterministic prototype records.
    - Railway sections are genuine TrackEase timetable-derived sections.
    - Forecast timing and confidence are simulated for demonstrating
      operational-impact-aware block planning.
"""

from pathlib import Path
import hashlib

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PLANNING_TASKS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coordinated_planning_tasks.csv"
)

SECTIONS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "railway_sections.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coa_goods_forecast.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coa_goods_forecast_report.txt"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

DAY_NAMES = [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
]

MAX_FORECAST_SECTIONS = 300
FORECASTS_PER_SECTION = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def deterministic_number(key, minimum, maximum):
    """
    Generate a stable deterministic integer from text.

    Same input always gives the same result.
    """

    digest = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()

    value = int(
        digest[:16],
        16,
    )

    return minimum + (
        value % (maximum - minimum + 1)
    )


def weekly_minute_label(value):
    """Convert weekly minute into weekday + HH:MM."""

    value %= MINUTES_PER_WEEK

    day_index = (
        value // MINUTES_PER_DAY
    )

    minute_of_day = (
        value % MINUTES_PER_DAY
    )

    hour = minute_of_day // 60
    minute = minute_of_day % 60

    return (
        DAY_NAMES[day_index],
        f"{hour:02d}:{minute:02d}",
    )


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

def build_coa_forecast():
    """Build TrackEase prototype COA goods-train forecast records."""

    print("=" * 72)
    print("TrackEase - COA Goods Train Forecast Adapter")
    print("=" * 72)

    for file_path, label in [
        (
            PLANNING_TASKS_FILE,
            "Coordinated planning tasks",
        ),
        (
            SECTIONS_FILE,
            "Railway section master",
        ),
    ]:

        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} not found:\n{file_path}"
            )

        print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------

    planning = pd.read_csv(
        PLANNING_TASKS_FILE
    )

    sections = pd.read_csv(
        SECTIONS_FILE
    )

    print(
        f"\nPlanning units loaded : "
        f"{len(planning):,}"
    )

    print(
        f"Railway sections      : "
        f"{len(sections):,}"
    )

    # -----------------------------------------------------------------------
    # Focus forecast on sections relevant to current maintenance planning
    # -----------------------------------------------------------------------

    planning_sections = (
        planning[
            ["section_id"]
        ]
        .drop_duplicates()
    )

    eligible = planning_sections.merge(
        sections[
            [
                "section_id",
                "station_a_code",
                "station_a_name",
                "station_b_code",
                "station_b_name",
                "unique_trains",
                "traversal_count",
            ]
        ],
        on="section_id",
        how="left",
        validate="one_to_one",
    )

    eligible = eligible[
        eligible[
            "unique_trains"
        ].notna()
    ].copy()

    # Prefer busier sections because goods forecasts matter more
    # operationally on active corridors.
    eligible = eligible.sort_values(
        [
            "unique_trains",
            "traversal_count",
            "section_id",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).head(
        MAX_FORECAST_SECTIONS
    )

    if eligible.empty:
        raise ValueError(
            "No eligible railway sections were found "
            "for the COA forecast adapter."
        )

    # -----------------------------------------------------------------------
    # Generate forecast events
    # -----------------------------------------------------------------------

    forecast_rows = []

    forecast_counter = 1

    for section in eligible.itertuples():

        for event_number in range(
            1,
            FORECASTS_PER_SECTION + 1,
        ):

            key = (
                f"{section.section_id}|"
                f"{event_number}"
            )

            # ---------------------------------------------------------------
            # Forecast weekday
            # ---------------------------------------------------------------

            day_index = deterministic_number(
                key + "|day",
                0,
                6,
            )

            # ---------------------------------------------------------------
            # Forecast time
            #
            # Allow events across the full day.
            # ---------------------------------------------------------------

            minute_of_day = deterministic_number(
                key + "|time",
                0,
                23 * 60,
            )

            # Round to a 5-minute boundary.
            minute_of_day = (
                minute_of_day // 5
            ) * 5

            start_minute = (
                day_index
                * MINUTES_PER_DAY
                + minute_of_day
            )

            # ---------------------------------------------------------------
            # Expected section occupancy
            # ---------------------------------------------------------------

            duration = deterministic_number(
                key + "|duration",
                25,
                70,
            )

            duration = (
                (duration + 4) // 5
            ) * 5

            end_minute = (
                start_minute
                + duration
            )

            # Keep raw end minute so later code can correctly handle
            # Sunday -> Monday boundary crossing.
            # ---------------------------------------------------------------
            # Forecast confidence
            # ---------------------------------------------------------------

            confidence_percent = deterministic_number(
                key + "|confidence",
                65,
                95,
            )

            confidence = (
                confidence_percent
                / 100
            )

            # ---------------------------------------------------------------
            # Expected goods movements
            # ---------------------------------------------------------------

            expected_goods_trains = (
                deterministic_number(
                    key + "|goods",
                    1,
                    3,
                )
            )

            start_day, start_time = (
                weekly_minute_label(
                    start_minute
                )
            )

            end_day, end_time = (
                weekly_minute_label(
                    end_minute
                )
            )

            forecast_rows.append(
                {
                    "forecast_id":
                        f"COA-{forecast_counter:06d}",

                    "section_id":
                        section.section_id,

                    "station_a_code":
                        section.station_a_code,

                    "station_a_name":
                        section.station_a_name,

                    "station_b_code":
                        section.station_b_code,

                    "station_b_name":
                        section.station_b_name,

                    "section_unique_trains":
                        int(section.unique_trains),

                    "forecast_day":
                        start_day,

                    "expected_start_time":
                        start_time,

                    "expected_end_day":
                        end_day,

                    "expected_end_time":
                        end_time,

                    "expected_start_minute":
                        int(start_minute),

                    "expected_end_minute":
                        int(end_minute),

                    "forecast_duration_minutes":
                        int(duration),

                    "expected_goods_trains":
                        int(expected_goods_trains),

                    "confidence":
                        confidence,

                    "train_category":
                        "GOODS",

                    "source_system":
                        "COA",

                    "integration_mode":
                        "PROTOTYPE_ADAPTER",

                    "source_data_type":
                        "PROTOTYPE_COA_FORECAST",
                }
            )

            forecast_counter += 1

    forecast = pd.DataFrame(
        forecast_rows
    )

    # -----------------------------------------------------------------------
    # Sort
    # -----------------------------------------------------------------------

    forecast = forecast.sort_values(
        [
            "section_id",
            "expected_start_minute",
        ]
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    forecast.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    forecast_sections = (
        forecast[
            "section_id"
        ].nunique()
    )

    average_confidence = (
        forecast[
            "confidence"
        ].mean()
    )

    average_duration = (
        forecast[
            "forecast_duration_minutes"
        ].mean()
    )

    total_goods_movements = int(
        forecast[
            "expected_goods_trains"
        ].sum()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase COA Goods Train Forecast Adapter Report",
        "=" * 72,
        "",
        f"Planning units available      : {len(planning):,}",
        f"Planning sections             : {planning['section_id'].nunique():,}",
        f"Sections selected for forecast: {forecast_sections:,}",
        f"Forecast events created       : {len(forecast):,}",
        f"Expected goods movements      : {total_goods_movements:,}",
        f"Average forecast duration     : {average_duration:.2f} minutes",
        f"Average confidence            : {average_confidence:.2%}",
        "",
        "INTEGRATION",
        "-" * 72,
        "Source-system representation : COA",
        "Train category               : GOODS",
        "Integration mode             : PROTOTYPE_ADAPTER",
        "",
        "IMPORTANT LIMITATION",
        "-" * 72,
        (
            "These forecast events are deterministic prototype "
            "records used to demonstrate Control Office / COA "
            "integration."
        ),
        (
            "TrackEase does not claim live access to Indian Railways "
            "goods-train forecasts."
        ),
        (
            "Railway sections are real TrackEase sections derived "
            "from the timetable dataset."
        ),
        "",
        "NEXT STEP",
        "-" * 72,
        (
            "Subtract / penalize forecast goods-train occupancy from "
            "candidate maintenance block windows before optimization."
        ),
    ]

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("COA GOODS FORECAST ADAPTER COMPLETE")
    print("=" * 72)

    print(
        f"\nForecast events    : "
        f"{len(forecast):,}"
    )

    print(
        f"Sections forecast  : "
        f"{forecast_sections:,}"
    )

    print(
        f"Expected goods runs: "
        f"{total_goods_movements:,}"
    )

    print(
        f"Average confidence : "
        f"{average_confidence:.2%}"
    )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nCOA / goods-train forecasting is now "
        "represented through a transparent prototype adapter."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_coa_forecast()