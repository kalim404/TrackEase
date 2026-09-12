"""
TrackEase - Block Maintenance Candidate Builder

Purpose:
    Convert the prepared predictive-maintenance dataset into a smaller,
    block-planning-specific maintenance candidate layer.

Input:
    data/processed/maintenance_prepared.csv

Outputs:
    data/processed/block_maintenance_candidates.csv
    data/processed/block_candidate_report.txt

Important:
    - This script does NOT modify raw data.
    - Maintenance train_id is NOT mapped to schedule train_number.
    - Only infrastructure-related maintenance records are considered.
    - Spatial location and maintenance duration will be added later.
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
    / "processed"
    / "maintenance_prepared.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_maintenance_candidates.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_candidate_report.txt"
)


# ---------------------------------------------------------------------------
# Candidate classification
# ---------------------------------------------------------------------------

def classify_department(row: pd.Series) -> str:
    """
    Identify which railway infrastructure department is primarily involved.
    """

    track_issue = (
        row["failure_type"] == "Track Defect"
        or row["ballast_condition"] in {"Fair", "Poor"}
    )

    signal_issue = (
        row["failure_type"] == "Signal Failure"
        or row["signal_system_status"] in {"Warning", "Fault"}
    )

    if track_issue and signal_issue:
        return "Engineering + S&T"

    if track_issue:
        return "Engineering"

    if signal_issue:
        return "S&T"

    return "Not Block Relevant"


def classify_task_type(row: pd.Series) -> str:
    """Create a simple human-readable maintenance task type."""

    track_issue = (
        row["failure_type"] == "Track Defect"
        or row["ballast_condition"] in {"Fair", "Poor"}
    )

    signal_issue = (
        row["failure_type"] == "Signal Failure"
        or row["signal_system_status"] in {"Warning", "Fault"}
    )

    if track_issue and signal_issue:
        return "Joint infrastructure inspection"

    if row["failure_type"] == "Track Defect":
        return "Track defect maintenance"

    if row["failure_type"] == "Signal Failure":
        return "Signal system maintenance"

    if row["signal_system_status"] == "Fault":
        return "Signal fault investigation"

    if row["ballast_condition"] == "Poor":
        return "Track and ballast maintenance"

    if row["signal_system_status"] == "Warning":
        return "Signal system inspection"

    if row["ballast_condition"] == "Fair":
        return "Track and ballast inspection"

    return "Infrastructure inspection"


def classify_priority(row: pd.Series) -> tuple[str, int]:
    """
    Convert maintenance severity and condition indicators into a
    transparent planning priority.

    This is a rule-based prototype priority, not an ML prediction.
    """

    severity = row["failure_severity"]

    if severity == "Critical":
        return "Critical", 4

    if (
        severity == "High"
        or row["signal_system_status"] == "Fault"
        or (
            row["ballast_condition"] == "Poor"
            and row["high_risk_flag"] == 1
        )
    ):
        return "High", 3

    if (
        severity == "Medium"
        or row["maintenance_needed"] == 1
        or row["high_risk_flag"] == 1
    ):
        return "Medium", 2

    return "Low", 1


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_block_candidates() -> None:
    """Build the TrackEase infrastructure maintenance candidate layer."""

    print("=" * 72)
    print("TrackEase - Block Maintenance Candidate Builder")
    print("=" * 72)

    print("\nInput file:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Prepared maintenance dataset not found:\n{INPUT_FILE}"
        )

    print("  ✓ Input file found")

    df = pd.read_csv(INPUT_FILE)

    print(f"\nPrepared maintenance rows : {len(df):,}")

    # -----------------------------------------------------------------------
    # Preserve source row identity
    # -----------------------------------------------------------------------

    df = df.reset_index(drop=True)

    df["source_maintenance_row"] = df.index + 1

    # -----------------------------------------------------------------------
    # Identify infrastructure conditions
    # -----------------------------------------------------------------------

    track_issue = (
        df["failure_type"].eq("Track Defect")
        | df["ballast_condition"].isin(["Fair", "Poor"])
    )

    signal_issue = (
        df["failure_type"].eq("Signal Failure")
        | df["signal_system_status"].isin(["Warning", "Fault"])
    )

    block_relevant = track_issue | signal_issue

    # -----------------------------------------------------------------------
    # Decide which records should become actual planning candidates
    # -----------------------------------------------------------------------
    #
    # A record becomes a candidate when:
    #
    #   1. It concerns track or signalling infrastructure
    #
    # AND at least one of:
    #
    #   - maintenance is required
    #   - the record is high-risk
    #   - ballast condition is Poor
    #   - signal status is Fault
    #
    # This prevents mild warnings from creating unnecessary maintenance blocks.
    # -----------------------------------------------------------------------

    candidate_mask = (
        block_relevant
        & (
            df["maintenance_needed"].eq(1)
            | df["high_risk_flag"].eq(1)
            | df["ballast_condition"].eq("Poor")
            | df["signal_system_status"].eq("Fault")
        )
    )

    candidates = df.loc[candidate_mask].copy()

    # -----------------------------------------------------------------------
    # Department classification
    # -----------------------------------------------------------------------

    candidates["department"] = candidates.apply(
        classify_department,
        axis=1,
    )

    # -----------------------------------------------------------------------
    # Task classification
    # -----------------------------------------------------------------------

    candidates["task_type"] = candidates.apply(
        classify_task_type,
        axis=1,
    )

    # -----------------------------------------------------------------------
    # Priority classification
    # -----------------------------------------------------------------------

    priority_values = candidates.apply(
        classify_priority,
        axis=1,
    )

    candidates["priority_level"] = [
        value[0] for value in priority_values
    ]

    candidates["priority_rank"] = [
        value[1] for value in priority_values
    ]

    # -----------------------------------------------------------------------
    # Generate stable TrackEase task IDs
    # -----------------------------------------------------------------------

    candidates = candidates.reset_index(drop=True)

    candidates["task_id"] = [
        f"MT-{number:06d}"
        for number in range(1, len(candidates) + 1)
    ]

    # -----------------------------------------------------------------------
    # Select only useful block-planning fields
    # -----------------------------------------------------------------------

    output_columns = [
        "task_id",
        "source_maintenance_row",
        "train_id",
        "department",
        "task_type",
        "priority_level",
        "priority_rank",
        "maintenance_needed",
        "failure_type",
        "failure_severity",
        "risk_score",
        "ballast_condition",
        "signal_system_status",
        "rail_wear_mm",
        "track_vibration_level",
        "inspection_score",
        "last_maintenance_days",
        "infrastructure_warning",
        "high_risk_flag",
    ]

    candidates = candidates[output_columns]

    # -----------------------------------------------------------------------
    # Sort highest-priority candidates first
    # -----------------------------------------------------------------------

    candidates = candidates.sort_values(
        by=["priority_rank", "risk_score"],
        ascending=[False, False],
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Save result
    # -----------------------------------------------------------------------

    candidates.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Create report
    # -----------------------------------------------------------------------

    department_counts = candidates["department"].value_counts()

    priority_counts = candidates["priority_level"].value_counts()

    report_lines = [
        "=" * 72,
        "TrackEase Block Maintenance Candidate Report",
        "=" * 72,
        "",
        f"Input file                 : {INPUT_FILE}",
        f"Output file                : {OUTPUT_FILE}",
        "",
        "DATASET SUMMARY",
        "-" * 72,
        f"Prepared maintenance rows  : {len(df):,}",
        f"Block candidates created   : {len(candidates):,}",
        "",
        "DEPARTMENT DISTRIBUTION",
        "-" * 72,
    ]

    for department, count in department_counts.items():
        report_lines.append(
            f"{department:<30} {count:>8,}"
        )

    report_lines.extend(
        [
            "",
            "PRIORITY DISTRIBUTION",
            "-" * 72,
        ]
    )

    for priority, count in priority_counts.items():
        report_lines.append(
            f"{priority:<30} {count:>8,}"
        )

    report_lines.extend(
        [
            "",
            "ARCHITECTURE NOTES",
            "-" * 72,
            (
                "Only infrastructure-related records were converted "
                "into block-planning candidates."
            ),
            (
                "Rolling-stock failures such as Brake Failure, Wheel Defect "
                "and Bearing Failure are not directly treated as track-block "
                "maintenance tasks."
            ),
            (
                "Electrical maintenance is not inferred artificially because "
                "the current dataset does not provide a reliable electrical "
                "maintenance label."
            ),
            (
                "train_id is retained only for source traceability and is NOT "
                "assumed to match train_number in the timetable dataset."
            ),
            (
                "Station/section location, required block duration and allowed "
                "maintenance windows will be added in the next planning layer."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console output
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("BLOCK CANDIDATE BUILD COMPLETE")
    print("=" * 72)

    print(f"\nPrepared rows checked : {len(df):,}")
    print(f"Candidates created    : {len(candidates):,}")

    print("\nDepartment distribution:")
    for department, count in department_counts.items():
        print(f"  {department:<24} {count:>8,}")

    print("\nPriority distribution:")
    for priority, count in priority_counts.items():
        print(f"  {priority:<24} {count:>8,}")

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nNo timetable train IDs or railway locations were "
        "artificially linked."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_block_candidates()