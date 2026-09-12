"""
TrackEase - Unified Maintenance Layer V2

Purpose:
    Combine Engineering (TMS), S&T (SMMS), joint TMS+SMMS,
    and prototype Electrical (TDMS) maintenance requirements into
    one common TrackEase maintenance-task schema.

Inputs:
    data/processed/maintenance_work_orders.csv
    data/processed/tdms_prototype_tasks.csv

Outputs:
    data/processed/unified_maintenance_tasks.csv
    data/processed/unified_maintenance_report.txt

Important:
    TMS / SMMS / TDMS values represent prototype integration adapters.
    TrackEase does not claim direct connectivity to railway production systems.
"""

from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

WORK_ORDERS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_work_orders.csv"
)

TDMS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "tdms_prototype_tasks.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "unified_maintenance_tasks.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "unified_maintenance_report.txt"
)


SOURCE_SYSTEM_MAP = {
    "Engineering": "TMS",
    "S&T": "SMMS",
    "Engineering + S&T": "TMS+SMMS",
}


def classify_asset_category(row):
    """Assign a normalized asset category to existing work orders."""

    task = str(row.get("task_type", "")).lower()

    if row.get("department") == "Engineering + S&T":
        return "Joint Infrastructure"

    if "signal" in task:
        return "Signalling"

    if "ballast" in task:
        return "Track & Ballast"

    if "track" in task:
        return "Track"

    return "Infrastructure"


def add_missing_columns(df, required_columns):
    """Add missing schema fields without inventing source information."""

    for column in required_columns:
        if column not in df.columns:
            df[column] = pd.NA

    return df


def build_unified_maintenance_layer():
    """Combine all current TrackEase maintenance source adapters."""

    print("=" * 72)
    print("TrackEase - Unified Maintenance Layer V2")
    print("=" * 72)

    # ------------------------------------------------------------------
    # Validate inputs
    # ------------------------------------------------------------------

    for path, name in [
        (WORK_ORDERS_FILE, "TMS / SMMS work orders"),
        (TDMS_FILE, "TDMS prototype tasks"),
    ]:
        print(f"\n{name}:")
        print(f"  {path}")

        if not path.exists():
            raise FileNotFoundError(
                f"{name} file not found:\n{path}"
            )

        print("  ✓ Found")

    # ------------------------------------------------------------------
    # Load current Engineering / S&T work orders
    # ------------------------------------------------------------------

    work_orders = pd.read_csv(WORK_ORDERS_FILE)

    print(
        f"\nExisting maintenance work orders : "
        f"{len(work_orders):,}"
    )

    work_orders["source_system"] = (
        work_orders["department"]
        .map(SOURCE_SYSTEM_MAP)
        .fillna("UNKNOWN")
    )

    work_orders["asset_category"] = work_orders.apply(
        classify_asset_category,
        axis=1,
    )

    work_orders["source_record_id"] = (
        work_orders["work_order_id"]
    )

    work_orders["task_status"] = "PENDING"
    work_orders["planning_horizon"] = "UNASSIGNED"
    work_orders["coordination_group"] = ""

    work_orders["coordination_eligible"] = 1

    work_orders["integration_mode"] = (
        "PROTOTYPE_ADAPTER"
    )

    work_orders["source_data_type"] = (
        "MAINTENANCE_DATASET"
    )

    # ------------------------------------------------------------------
    # Load TDMS tasks
    # ------------------------------------------------------------------

    tdms = pd.read_csv(TDMS_FILE)

    print(
        f"TDMS prototype tasks              : "
        f"{len(tdms):,}"
    )

    tdms["source_record_id"] = (
        tdms["tdms_task_id"]
    )

    # Use the TDMS task ID as task_id for traceability.
    tdms["task_id"] = tdms["tdms_task_id"]

    tdms["work_order_id"] = pd.NA

    # ------------------------------------------------------------------
    # Common unified schema
    # ------------------------------------------------------------------

    common_columns = [
        "source_record_id",
        "work_order_id",
        "task_id",

        "source_system",
        "department",
        "asset_category",
        "task_type",

        "section_id",
        "station_a_code",
        "station_a_name",
        "station_b_code",
        "station_b_name",
        "section_unique_trains",

        "priority_level",
        "priority_rank",
        "required_minutes",

        "failure_type",
        "failure_severity",

        "ballast_condition",
        "signal_system_status",

        "rail_wear_mm",
        "track_vibration_level",
        "inspection_score",
        "last_maintenance_days",

        "task_status",
        "planning_horizon",

        "coordination_group",
        "coordination_eligible",

        "integration_mode",
        "source_data_type",
        "location_assignment_type",
    ]

    work_orders = add_missing_columns(
        work_orders,
        common_columns,
    )

    tdms = add_missing_columns(
        tdms,
        common_columns,
    )

    # ------------------------------------------------------------------
    # Combine source systems
    # ------------------------------------------------------------------

    unified = pd.concat(
        [
            work_orders[common_columns],
            tdms[common_columns],
        ],
        ignore_index=True,
    )

    # ------------------------------------------------------------------
    # Generate final unified TrackEase IDs
    # ------------------------------------------------------------------

    unified.insert(
        0,
        "unified_task_id",
        [
            f"UMT-{number:06d}"
            for number in range(
                1,
                len(unified) + 1
            )
        ],
    )

    # ------------------------------------------------------------------
    # Sort for priority processing
    # ------------------------------------------------------------------

    unified = unified.sort_values(
        [
            "priority_rank",
            "section_unique_trains",
            "section_id",
            "unified_task_id",
        ],
        ascending=[
            False,
            False,
            True,
            True,
        ],
    ).reset_index(drop=True)

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    duplicate_ids = int(
        unified[
            "unified_task_id"
        ].duplicated().sum()
    )

    missing_sections = int(
        unified[
            "section_id"
        ].isna().sum()
    )

    unknown_sources = int(
        unified[
            "source_system"
        ].eq("UNKNOWN").sum()
    )

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    unified.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    source_counts = (
        unified["source_system"]
        .value_counts()
    )

    department_counts = (
        unified["department"]
        .value_counts()
    )

    priority_counts = (
        unified["priority_level"]
        .value_counts()
    )

    unique_sections = (
        unified["section_id"]
        .nunique()
    )

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Unified Maintenance Layer V2 Report",
        "=" * 72,
        "",
        f"TMS/SMMS work orders      : {len(work_orders):,}",
        f"TDMS prototype tasks      : {len(tdms):,}",
        f"Unified maintenance tasks : {len(unified):,}",
        f"Sections represented      : {unique_sections:,}",
        "",
        "SOURCE SYSTEMS",
        "-" * 72,
    ]

    for source, count in source_counts.items():
        report.append(
            f"{source:<20} {count:>8,}"
        )

    report.extend([
        "",
        "DEPARTMENTS",
        "-" * 72,
    ])

    for department, count in department_counts.items():
        report.append(
            f"{department:<30} {count:>8,}"
        )

    report.extend([
        "",
        "PRIORITIES",
        "-" * 72,
    ])

    for priority, count in priority_counts.items():
        report.append(
            f"{priority:<20} {count:>8,}"
        )

    report.extend([
        "",
        "QUALITY CHECKS",
        "-" * 72,
        f"Duplicate unified IDs : {duplicate_ids:,}",
        f"Missing sections      : {missing_sections:,}",
        f"Unknown sources       : {unknown_sources:,}",
        "",
        "ARCHITECTURE STATUS",
        "-" * 72,
        "TMS Engineering representation : COMPLETE",
        "SMMS S&T representation        : COMPLETE",
        "TDMS Electrical representation : COMPLETE",
        "",
        (
            "All three departmental maintenance sources now feed "
            "one common TrackEase planning schema."
        ),
        "",
        "PROTOTYPE LIMITATION",
        "-" * 72,
        (
            "Source-system names represent integration adapters. "
            "No live TMS, SMMS or TDMS production connection is claimed."
        ),
        (
            "TDMS electrical tasks are controlled prototype records."
        ),
    ])

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # ------------------------------------------------------------------
    # Console
    # ------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("UNIFIED MAINTENANCE LAYER V2 COMPLETE")
    print("=" * 72)

    print(
        f"\nUnified tasks      : {len(unified):,}"
    )

    print(
        f"Sections represented: {unique_sections:,}"
    )

    print("\nSource systems:")

    for source, count in source_counts.items():
        print(
            f"  {source:<15} {count:>6,}"
        )

    print("\nDepartments:")

    for department, count in department_counts.items():
        print(
            f"  {department:<24} {count:>6,}"
        )

    print("\nQuality checks:")
    print(
        f"  Duplicate IDs : {duplicate_ids:,}"
    )
    print(
        f"  Missing sections: {missing_sections:,}"
    )
    print(
        f"  Unknown sources : {unknown_sources:,}"
    )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nTMS + SMMS + TDMS now feed one "
        "TrackEase maintenance layer."
    )


if __name__ == "__main__":
    build_unified_maintenance_layer()