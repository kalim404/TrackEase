"""
TrackEase - Explainable Maintenance Priority Engine

Purpose:
    Calculate an explainable TrackEase priority score for every unified
    maintenance task from TMS, SMMS and TDMS representations.

Input:
    data/processed/unified_maintenance_tasks.csv

Outputs:
    data/processed/prioritized_maintenance_tasks.csv
    data/processed/priority_engine_report.txt

Score:
    Criticality             : 35
    Maintenance urgency     : 25
    Asset condition         : 20
    Section traffic         : 15
    Coordination potential  :  5
                              ---
                              100

Important:
    This is an explainable rule-based priority engine.
    It does not replace human railway engineering judgement.
"""

from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "unified_maintenance_tasks.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "prioritized_maintenance_tasks.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "priority_engine_report.txt"
)


# ---------------------------------------------------------------------------
# Score limits
# ---------------------------------------------------------------------------

MAX_CRITICALITY = 35
MAX_URGENCY = 25
MAX_CONDITION = 20
MAX_TRAFFIC = 15
MAX_COORDINATION = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def percentile_score(series, max_score, higher_is_worse=True):
    """
    Convert numeric values into a percentile-based score.

    Missing values receive 0 so unavailable prototype fields do not
    artificially increase priority.
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

    result = ranks * max_score

    return result.fillna(0)


def expand_departments(value):
    """Convert department label into its actual participating departments."""

    value = str(value)

    if value == "Engineering + S&T":
        return {"Engineering", "S&T"}

    if value in {"Engineering", "S&T", "Electrical"}:
        return {value}

    return set()


def trackease_priority_level(score):
    """Convert numeric TrackEase score into an explainable priority."""

    if score >= 80:
        return "Critical"

    if score >= 60:
        return "High"

    if score >= 40:
        return "Medium"

    return "Low"


# ---------------------------------------------------------------------------
# Criticality component
# ---------------------------------------------------------------------------

def calculate_criticality(row):
    """
    Score defect / source criticality.

    Real maintenance-data records primarily use failure severity.
    TDMS prototype records fall back to their adapter priority.
    """

    severity_scores = {
        "Critical": 35,
        "High": 28,
        "Medium": 20,
        "Low": 10,
        "None": 5,
    }

    severity = str(
        row.get("failure_severity", "")
    )

    if severity in severity_scores:
        return severity_scores[severity]

    # TDMS records do not have a genuine source failure severity.
    # Use their explicitly labelled prototype adapter priority.
    fallback = {
        "Critical": 35,
        "High": 28,
        "Medium": 18,
        "Low": 8,
    }

    return fallback.get(
        str(row.get("priority_level", "")),
        5,
    )


# ---------------------------------------------------------------------------
# Asset condition component
# ---------------------------------------------------------------------------

def calculate_condition_score(row):
    """Build an interpretable asset-condition score."""

    scores = []

    # ---------------------------------------------------------------
    # Ballast condition
    # ---------------------------------------------------------------

    ballast_scores = {
        "Poor": 20,
        "Fair": 12,
        "Good": 2,
    }

    ballast = str(
        row.get("ballast_condition", "")
    )

    if ballast in ballast_scores:
        scores.append(
            ballast_scores[ballast]
        )

    # ---------------------------------------------------------------
    # Signal condition
    # ---------------------------------------------------------------

    signal_scores = {
        "Fault": 20,
        "Warning": 13,
        "Normal": 2,
    }

    signal = str(
        row.get("signal_system_status", "")
    )

    if signal in signal_scores:
        scores.append(
            signal_scores[signal]
        )

    # ---------------------------------------------------------------
    # Inspection score
    #
    # Lower inspection score = worse condition.
    # ---------------------------------------------------------------

    inspection = pd.to_numeric(
        row.get("inspection_score"),
        errors="coerce",
    )

    if pd.notna(inspection):

        inspection = max(
            0,
            min(100, float(inspection))
        )

        scores.append(
            (100 - inspection) / 100 * 20
        )

    # ---------------------------------------------------------------
    # For prototype TDMS records without sensor-condition fields,
    # use a conservative source-priority fallback.
    # ---------------------------------------------------------------

    if not scores:

        fallback = {
            "Critical": 18,
            "High": 15,
            "Medium": 10,
            "Low": 5,
        }

        return fallback.get(
            str(row.get("priority_level", "")),
            5,
        )

    # Use the strongest observed condition warning.
    return min(
        max(scores),
        MAX_CONDITION,
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def score_priorities():
    """Generate TrackEase explainable maintenance priorities."""

    print("=" * 72)
    print("TrackEase - Explainable Maintenance Priority Engine")
    print("=" * 72)

    print("\nInput:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Unified maintenance file not found:\n{INPUT_FILE}"
        )

    print("  ✓ Found")

    df = pd.read_csv(INPUT_FILE)

    print(
        f"\nUnified tasks loaded : "
        f"{len(df):,}"
    )

    # -----------------------------------------------------------------------
    # Criticality
    # -----------------------------------------------------------------------

    df["criticality_score"] = (
        df.apply(
            calculate_criticality,
            axis=1,
        )
    )

    # -----------------------------------------------------------------------
    # Urgency
    #
    # Longer time since last maintenance = more urgent.
    # TDMS records without the field receive a fallback later.
    # -----------------------------------------------------------------------

    urgency = percentile_score(
        df["last_maintenance_days"],
        MAX_URGENCY,
        higher_is_worse=True,
    )

    missing_urgency = pd.to_numeric(
        df["last_maintenance_days"],
        errors="coerce",
    ).isna()

    fallback_urgency = (
        df["priority_level"]
        .map(
            {
                "Critical": 25,
                "High": 20,
                "Medium": 13,
                "Low": 6,
            }
        )
        .fillna(5)
    )

    urgency.loc[
        missing_urgency
    ] = fallback_urgency.loc[
        missing_urgency
    ]

    df["urgency_score"] = urgency

    # -----------------------------------------------------------------------
    # Asset condition
    # -----------------------------------------------------------------------

    df["asset_condition_score"] = (
        df.apply(
            calculate_condition_score,
            axis=1,
        )
    )

    # -----------------------------------------------------------------------
    # Traffic importance
    # -----------------------------------------------------------------------

    df["traffic_score"] = percentile_score(
        df["section_unique_trains"],
        MAX_TRAFFIC,
        higher_is_worse=True,
    )

    # -----------------------------------------------------------------------
    # Coordination potential
    #
    # Determine how many distinct departments have work on each section.
    # -----------------------------------------------------------------------

    section_departments = {}

    for row in df.itertuples():

        section = row.section_id

        section_departments.setdefault(
            section,
            set(),
        )

        section_departments[
            section
        ].update(
            expand_departments(
                row.department
            )
        )

    coordination_scores = []
    coordination_counts = []

    for row in df.itertuples():

        departments = section_departments.get(
            row.section_id,
            set(),
        )

        count = len(departments)

        coordination_counts.append(
            count
        )

        if count >= 3:
            score = 5

        elif count == 2:
            score = 3

        else:
            score = 0

        coordination_scores.append(
            score
        )

    df[
        "departments_on_section"
    ] = coordination_counts

    df[
        "coordination_score"
    ] = coordination_scores

    # -----------------------------------------------------------------------
    # Final score
    # -----------------------------------------------------------------------

    df["trackease_priority_score"] = (
        df[
            [
                "criticality_score",
                "urgency_score",
                "asset_condition_score",
                "traffic_score",
                "coordination_score",
            ]
        ]
        .sum(axis=1)
        .round(2)
    )

    df["trackease_priority_level"] = (
        df[
            "trackease_priority_score"
        ]
        .apply(
            trackease_priority_level
        )
    )

    # -----------------------------------------------------------------------
    # Explanation
    # -----------------------------------------------------------------------

    df["priority_explanation"] = (
        "Criticality "
        + df["criticality_score"].round(1).astype(str)
        + "/35; Urgency "
        + df["urgency_score"].round(1).astype(str)
        + "/25; Condition "
        + df["asset_condition_score"].round(1).astype(str)
        + "/20; Traffic "
        + df["traffic_score"].round(1).astype(str)
        + "/15; Coordination "
        + df["coordination_score"].astype(str)
        + "/5"
    )

    # -----------------------------------------------------------------------
    # Sort strongest tasks first
    # -----------------------------------------------------------------------

    df = df.sort_values(
        [
            "trackease_priority_score",
            "priority_rank",
            "section_unique_trains",
        ],
        ascending=[
            False,
            False,
            False,
        ],
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    df.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    level_counts = (
        df[
            "trackease_priority_level"
        ]
        .value_counts()
    )

    source_counts = (
        df[
            "source_system"
        ]
        .value_counts()
    )

    coordination_candidates = int(
        (
            df[
                "departments_on_section"
            ]
            >= 2
        ).sum()
    )

    multi_department_sections = (
        df.loc[
            df[
                "departments_on_section"
            ] >= 2,
            "section_id",
        ]
        .nunique()
    )

    average_score = (
        df[
            "trackease_priority_score"
        ]
        .mean()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Explainable Priority Engine Report",
        "=" * 72,
        "",
        f"Unified tasks scored          : {len(df):,}",
        f"Average TrackEase score       : {average_score:.2f}",
        f"Coordination-eligible tasks   : {coordination_candidates:,}",
        f"Multi-department sections     : {multi_department_sections:,}",
        "",
        "TRACKEASE PRIORITY LEVELS",
        "-" * 72,
    ]

    for level in [
        "Critical",
        "High",
        "Medium",
        "Low",
    ]:

        report.append(
            f"{level:<20} "
            f"{int(level_counts.get(level, 0)):>8,}"
        )

    report.extend(
        [
            "",
            "SOURCE SYSTEMS",
            "-" * 72,
        ]
    )

    for source, count in source_counts.items():

        report.append(
            f"{source:<20} "
            f"{count:>8,}"
        )

    report.extend(
        [
            "",
            "SCORING MODEL",
            "-" * 72,
            "Criticality             : 35 points",
            "Maintenance urgency     : 25 points",
            "Asset condition         : 20 points",
            "Section traffic         : 15 points",
            "Coordination potential  :  5 points",
            "                          ---------",
            "Maximum                  : 100 points",
            "",
            "IMPORTANT NOTE",
            "-" * 72,
            (
                "TrackEase priority is an explainable prototype "
                "decision-support score."
            ),
            (
                "It does not replace railway engineering judgement "
                "or official maintenance priority rules."
            ),
            (
                "TDMS records use explicit prototype fallbacks where "
                "real condition fields are unavailable."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("PRIORITY SCORING COMPLETE")
    print("=" * 72)

    print(
        f"\nTasks scored              : "
        f"{len(df):,}"
    )

    print(
        f"Average priority score    : "
        f"{average_score:.2f}/100"
    )

    print(
        f"Multi-department sections : "
        f"{multi_department_sections:,}"
    )

    print(
        f"Coordination candidates   : "
        f"{coordination_candidates:,}"
    )

    print("\nTrackEase priorities:")

    for level in [
        "Critical",
        "High",
        "Medium",
        "Low",
    ]:

        print(
            f"  {level:<10} "
            f"{int(level_counts.get(level, 0)):>6,}"
        )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nEvery maintenance task now has an "
        "explainable TrackEase priority score."
    )


if __name__ == "__main__":
    score_priorities()