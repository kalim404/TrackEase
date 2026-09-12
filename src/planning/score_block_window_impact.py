"""
TrackEase - Operational Block Window Impact Scoring

Purpose:
    Score every safe maintenance block window according to its likely
    operational impact.

Inputs:
    data/processed/adjusted_block_windows.csv
    data/processed/weekly_section_movements.csv

Outputs:
    data/processed/scored_block_windows.csv
    data/processed/block_window_impact_report.txt

Scoring:
    Section traffic intensity       : 40 points
    Maintenance-window scarcity     : 20 points
    Window flexibility              : 20 points
    COA goods exposure              : 20 points
                                      ---------
    Maximum operational impact      : 100 points

Interpretation:
    Lower score = operationally more attractive maintenance opportunity.

Important:
    This is a transparent prototype decision-support score.
    It is not an official Indian Railways operational-impact formula.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "adjusted_block_windows.csv"
)

MOVEMENTS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_section_movements.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "scored_block_windows.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_window_impact_report.txt"
)


MINUTES_PER_WEEK = 10080


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def percentile_score(
    series,
    maximum_score,
    higher_is_worse=True,
):
    """
    Convert numeric values into percentile-based scores.

    This avoids inventing arbitrary hard thresholds for dataset-wide
    operational characteristics.
    """

    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    ranks = numeric.rank(
        pct=True,
        method="average",
    )

    if not higher_is_worse:
        ranks = 1 - ranks

    return (
        ranks
        * maximum_score
    ).fillna(0)


def classify_impact(score):
    """Convert numerical impact score into an interpretable category."""

    if score >= 75:
        return "Very High"

    if score >= 50:
        return "High"

    if score >= 25:
        return "Moderate"

    return "Low"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def score_block_window_impact():
    """Calculate operational-impact metrics for every block window."""

    print("=" * 72)
    print("TrackEase - Operational Block Window Impact Scoring")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate inputs
    # -----------------------------------------------------------------------

    for file_path, label in [
        (
            WINDOWS_FILE,
            "Adjusted block windows",
        ),
        (
            MOVEMENTS_FILE,
            "Weekly section movements",
        ),
    ]:

        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n{file_path}"
            )

        print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    movements = pd.read_csv(
        MOVEMENTS_FILE
    )

    print(
        f"\nAdjusted windows loaded : "
        f"{len(windows):,}"
    )

    print(
        f"Weekly movements loaded : "
        f"{len(movements):,}"
    )

    # -----------------------------------------------------------------------
    # Schema validation
    # -----------------------------------------------------------------------

    required_window_columns = {
        "adjusted_window_id",
        "section_id",
        "duration_minutes",
        "coa_adjusted",
        "goods_forecast_present",
    }

    required_movement_columns = {
        "section_id",
    }

    missing_windows = (
        required_window_columns
        - set(windows.columns)
    )

    missing_movements = (
        required_movement_columns
        - set(movements.columns)
    )

    if missing_windows:
        raise ValueError(
            "Adjusted window dataset is missing columns:\n"
            + ", ".join(
                sorted(missing_windows)
            )
        )

    if missing_movements:
        raise ValueError(
            "Weekly movement dataset is missing columns:\n"
            + ", ".join(
                sorted(missing_movements)
            )
        )

    # -----------------------------------------------------------------------
    # Section traffic statistics
    #
    # Number of timetable section movements in one recurring week.
    # -----------------------------------------------------------------------

    movement_counts = (
        movements
        .groupby(
            "section_id"
        )
        .size()
        .rename(
            "weekly_train_movements"
        )
        .reset_index()
    )

    # -----------------------------------------------------------------------
    # Section maintenance-opportunity statistics
    # -----------------------------------------------------------------------

    section_window_stats = (
        windows
        .groupby(
            "section_id"
        )
        .agg(
            section_window_count=(
                "adjusted_window_id",
                "count",
            ),
            section_available_minutes=(
                "duration_minutes",
                "sum",
            ),
        )
        .reset_index()
    )

    section_window_stats[
        "section_availability_ratio"
    ] = (
        section_window_stats[
            "section_available_minutes"
        ]
        / MINUTES_PER_WEEK
    )

    # -----------------------------------------------------------------------
    # Merge statistics into every window
    # -----------------------------------------------------------------------

    scored = windows.merge(
        movement_counts,
        on="section_id",
        how="left",
        validate="many_to_one",
    )

    scored = scored.merge(
        section_window_stats,
        on="section_id",
        how="left",
        validate="many_to_one",
    )

    scored[
        "weekly_train_movements"
    ] = (
        scored[
            "weekly_train_movements"
        ]
        .fillna(0)
        .astype(int)
    )

    # -----------------------------------------------------------------------
    # 1. Traffic intensity — maximum 40
    #
    # Busier sections receive higher impact.
    # -----------------------------------------------------------------------

    scored[
        "traffic_impact_score"
    ] = percentile_score(
        scored[
            "weekly_train_movements"
        ],
        maximum_score=40,
        higher_is_worse=True,
    )

    # -----------------------------------------------------------------------
    # 2. Maintenance opportunity scarcity — maximum 20
    #
    # Sections with less total available maintenance time are more
    # operationally constrained.
    # -----------------------------------------------------------------------

    scored[
        "scarcity_impact_score"
    ] = percentile_score(
        scored[
            "section_availability_ratio"
        ],
        maximum_score=20,
        higher_is_worse=False,
    )

    # -----------------------------------------------------------------------
    # 3. Window flexibility — maximum 20
    #
    # Shorter windows provide less flexibility and therefore have
    # greater planning risk.
    # -----------------------------------------------------------------------

    scored[
        "flexibility_impact_score"
    ] = percentile_score(
        scored[
            "duration_minutes"
        ],
        maximum_score=20,
        higher_is_worse=False,
    )

    # -----------------------------------------------------------------------
    # 4. COA goods exposure — maximum 20
    #
    # A window that was actually modified by a forecast receives the
    # highest goods-related impact.
    #
    # A section containing prototype goods forecasts but where this
    # specific source window did not require adjustment receives only
    # a small contextual penalty.
    # -----------------------------------------------------------------------

    def goods_score(row):

        if int(
            row.get(
                "coa_adjusted",
                0,
            )
        ) == 1:
            return 20

        if int(
            row.get(
                "goods_forecast_present",
                0,
            )
        ) == 1:
            return 6

        return 0

    scored[
        "goods_impact_score"
    ] = scored.apply(
        goods_score,
        axis=1,
    )

    # -----------------------------------------------------------------------
    # Final operational-impact score
    # -----------------------------------------------------------------------

    scored[
        "operational_impact_score"
    ] = (
        scored[
            [
                "traffic_impact_score",
                "scarcity_impact_score",
                "flexibility_impact_score",
                "goods_impact_score",
            ]
        ]
        .sum(
            axis=1
        )
        .round(2)
    )

    scored[
        "operational_impact_level"
    ] = (
        scored[
            "operational_impact_score"
        ]
        .apply(
            classify_impact
        )
    )

    # -----------------------------------------------------------------------
    # Explanation
    # -----------------------------------------------------------------------

    scored[
        "impact_explanation"
    ] = (
        "Traffic "
        + scored[
            "traffic_impact_score"
        ].round(1).astype(str)
        + "/40; Scarcity "
        + scored[
            "scarcity_impact_score"
        ].round(1).astype(str)
        + "/20; Flexibility "
        + scored[
            "flexibility_impact_score"
        ].round(1).astype(str)
        + "/20; Goods "
        + scored[
            "goods_impact_score"
        ].round(1).astype(str)
        + "/20"
    )

    # -----------------------------------------------------------------------
    # Sort
    #
    # Keep the lowest-impact windows first inside each section.
    # -----------------------------------------------------------------------

    scored = scored.sort_values(
        [
            "section_id",
            "operational_impact_score",
            "duration_minutes",
            "window_start_minute",
        ],
        ascending=[
            True,
            True,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    scored.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    average_impact = (
        scored[
            "operational_impact_score"
        ].mean()
    )

    minimum_impact = (
        scored[
            "operational_impact_score"
        ].min()
    )

    maximum_impact = (
        scored[
            "operational_impact_score"
        ].max()
    )

    impact_counts = (
        scored[
            "operational_impact_level"
        ]
        .value_counts()
    )

    coa_affected = int(
        scored[
            "coa_adjusted"
        ].sum()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Operational Block Window Impact Report",
        "=" * 72,
        "",
        "INPUT",
        "-" * 72,
        f"Adjusted maintenance windows : {len(windows):,}",
        f"Weekly train movements       : {len(movements):,}",
        "",
        "RESULT",
        "-" * 72,
        f"Windows scored               : {len(scored):,}",
        f"Sections scored              : {scored['section_id'].nunique():,}",
        f"Average impact score         : {average_impact:.2f}/100",
        f"Minimum impact score         : {minimum_impact:.2f}/100",
        f"Maximum impact score         : {maximum_impact:.2f}/100",
        f"COA-adjusted windows         : {coa_affected:,}",
        "",
        "OPERATIONAL IMPACT LEVELS",
        "-" * 72,
    ]

    for level in [
        "Low",
        "Moderate",
        "High",
        "Very High",
    ]:

        report.append(
            f"{level:<20} "
            f"{int(impact_counts.get(level, 0)):>10,}"
        )

    report.extend(
        [
            "",
            "SCORING MODEL",
            "-" * 72,
            "Section traffic intensity      : 40 points",
            "Maintenance-window scarcity    : 20 points",
            "Window flexibility             : 20 points",
            "COA goods exposure             : 20 points",
            "                                 ---------",
            "Maximum operational impact     : 100 points",
            "",
            "INTERPRETATION",
            "-" * 72,
            "LOWER SCORE = more attractive operational window.",
            "",
            (
                "The score does not declare whether a maintenance "
                "task fits inside a window."
            ),
            (
                "Task-duration feasibility and best-fit allocation "
                "will be handled by Optimizer V2."
            ),
            "",
            "PROTOTYPE LIMITATION",
            "-" * 72,
            (
                "This is a transparent decision-support scoring model "
                "and is not an official Indian Railways operational "
                "impact formula."
            ),
            "",
            "NEXT STAGE",
            "-" * 72,
            (
                "Optimizer V2 will combine TrackEase maintenance "
                "priority, coordination, window duration and "
                "operational impact to select final blocks."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(
            report
        ),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("OPERATIONAL IMPACT SCORING COMPLETE")
    print("=" * 72)

    print(
        f"\nWindows scored      : "
        f"{len(scored):,}"
    )

    print(
        f"Sections scored     : "
        f"{scored['section_id'].nunique():,}"
    )

    print(
        f"Average impact      : "
        f"{average_impact:.2f}/100"
    )

    print(
        f"Impact range        : "
        f"{minimum_impact:.2f} - "
        f"{maximum_impact:.2f}"
    )

    print("\nImpact levels:")

    for level in [
        "Low",
        "Moderate",
        "High",
        "Very High",
    ]:

        print(
            f"  {level:<10} "
            f"{int(impact_counts.get(level, 0)):>10,}"
        )

    print("\nOutputs:")
    print(
        f"  {OUTPUT_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nTrackEase can now distinguish between merely "
        "available windows and operationally preferable windows."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    score_block_window_impact()