"""
TrackEase - Maintenance Work Order Builder

Purpose:
    Convert infrastructure maintenance candidates into practical
    TrackEase prototype work orders that can be consumed by the
    automatic block-planning engine.

Inputs:
    data/processed/block_maintenance_candidates.csv
    data/processed/railway_sections.csv
    data/processed/available_block_windows.csv

Output:
    data/processed/maintenance_work_orders.csv
    data/processed/maintenance_work_order_report.txt

Important:
    The source maintenance dataset does NOT contain genuine railway
    section locations.

    Therefore, section assignment in this prototype is deterministic
    and simulated. It must not be presented as source-data truth.
"""

from pathlib import Path
import hashlib

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CANDIDATES_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_maintenance_candidates.csv"
)

SECTIONS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "railway_sections.csv"
)

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "available_block_windows.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_work_orders.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_work_order_report.txt"
)


# ---------------------------------------------------------------------------
# Prototype configuration
# ---------------------------------------------------------------------------

MAX_WORK_ORDERS = 1000

# We deliberately keep a mixture of priorities for dashboard/demo testing.
PRIORITY_LIMITS = {
    "Critical": 200,
    "High": 300,
    "Medium": 350,
    "Low": 150,
}


# ---------------------------------------------------------------------------
# Prototype maintenance-duration rules
# ---------------------------------------------------------------------------

TASK_BASE_DURATION = {
    "Track defect maintenance": 120,
    "Track and ballast maintenance": 180,
    "Signal system maintenance": 90,
    "Signal fault investigation": 60,
    "Joint infrastructure inspection": 150,
    "Track and ballast inspection": 60,
    "Signal system inspection": 45,
    "Infrastructure inspection": 45,
}


PRIORITY_EXTRA_DURATION = {
    "Critical": 60,
    "High": 30,
    "Medium": 0,
    "Low": 0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calculate_required_duration(row):
    """
    Estimate prototype maintenance duration.

    This is rule-based because the current source dataset contains
    no genuine maintenance-duration target for supervised training.
    """

    base_duration = TASK_BASE_DURATION.get(
        row["task_type"],
        60,
    )

    extra_duration = PRIORITY_EXTRA_DURATION.get(
        row["priority_level"],
        0,
    )

    duration = base_duration + extra_duration

    # Keep durations on 15-minute planning boundaries.
    duration = int(
        round(duration / 15) * 15
    )

    return max(duration, 30)


def stable_section_index(task_id, source_row, section_count):
    """
    Generate a deterministic section index.

    Python's built-in hash() changes between sessions, therefore SHA256
    is used so the same work order always receives the same prototype
    section assignment.
    """

    key = f"{task_id}|{source_row}"

    digest = hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()

    numeric_value = int(
        digest[:16],
        16,
    )

    return numeric_value % section_count


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_work_orders():
    """Build TrackEase prototype maintenance work orders."""

    print("=" * 72)
    print("TrackEase - Maintenance Work Order Builder")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # Validate inputs
    # -----------------------------------------------------------------------

    for file_path, label in [
        (CANDIDATES_FILE, "Maintenance candidates"),
        (SECTIONS_FILE, "Railway sections"),
        (WINDOWS_FILE, "Available block windows"),
    ]:

        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n{file_path}"
            )

        print("  ✓ Found")

    # -----------------------------------------------------------------------
    # Load datasets
    # -----------------------------------------------------------------------

    candidates = pd.read_csv(
        CANDIDATES_FILE
    )

    sections = pd.read_csv(
        SECTIONS_FILE
    )

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    print(
        f"\nMaintenance candidates : {len(candidates):,}"
    )

    print(
        f"Railway sections       : {len(sections):,}"
    )

    print(
        f"Available windows       : {len(windows):,}"
    )

    # -----------------------------------------------------------------------
    # Identify sections that actually have block opportunities
    # -----------------------------------------------------------------------

    sections_with_windows = set(
        windows["section_id"]
        .dropna()
        .unique()
    )

    eligible_sections = sections[
        sections["section_id"].isin(
            sections_with_windows
        )
    ].copy()

    if eligible_sections.empty:
        raise ValueError(
            "No railway sections contain available block windows."
        )

    # -----------------------------------------------------------------------
    # Prefer operationally meaningful sections
    #
    # Very lightly used sections are less interesting for demonstrating
    # automatic block planning. Therefore we use sections with at least
    # two unique train services where possible.
    # -----------------------------------------------------------------------

    useful_sections = eligible_sections[
        eligible_sections["unique_trains"] >= 2
    ].copy()

    if not useful_sections.empty:
        eligible_sections = useful_sections

    eligible_sections = eligible_sections.sort_values(
        [
            "unique_trains",
            "section_id",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(drop=True)

    print(
        f"Eligible planning sections: "
        f"{len(eligible_sections):,}"
    )

    # -----------------------------------------------------------------------
    # Select controlled demonstration work orders
    # -----------------------------------------------------------------------

    selected_groups = []

    for priority, limit in PRIORITY_LIMITS.items():

        group = candidates[
            candidates["priority_level"] == priority
        ].copy()

        group = group.sort_values(
            [
                "priority_rank",
                "maintenance_needed",
                "risk_score",
            ],
            ascending=[
                False,
                False,
                False,
            ],
        )

        selected_groups.append(
            group.head(limit)
        )

    work_orders = pd.concat(
        selected_groups,
        ignore_index=True,
    )

    work_orders = work_orders.head(
        MAX_WORK_ORDERS
    ).copy()

    # -----------------------------------------------------------------------
    # Estimate required block duration
    # -----------------------------------------------------------------------

    work_orders["required_minutes"] = (
        work_orders.apply(
            calculate_required_duration,
            axis=1,
        )
    )

    # -----------------------------------------------------------------------
    # Deterministic prototype section assignment
    # -----------------------------------------------------------------------

    section_count = len(
        eligible_sections
    )

    assigned_rows = []

    for row in work_orders.itertuples():

        index = stable_section_index(
            row.task_id,
            row.source_maintenance_row,
            section_count,
        )

        section = eligible_sections.iloc[
            index
        ]

        assigned_rows.append(
            {
                "section_id": section["section_id"],
                "station_a_code": section["station_a_code"],
                "station_a_name": section["station_a_name"],
                "station_b_code": section["station_b_code"],
                "station_b_name": section["station_b_name"],
                "section_unique_trains": int(
                    section["unique_trains"]
                ),
            }
        )

    assignment_df = pd.DataFrame(
        assigned_rows
    )

    work_orders = pd.concat(
        [
            work_orders.reset_index(drop=True),
            assignment_df,
        ],
        axis=1,
    )

    # -----------------------------------------------------------------------
    # Generate TrackEase work-order IDs
    # -----------------------------------------------------------------------

    work_orders.insert(
        0,
        "work_order_id",
        [
            f"WO-{number:06d}"
            for number in range(
                1,
                len(work_orders) + 1
            )
        ],
    )

    # -----------------------------------------------------------------------
    # Location metadata
    # -----------------------------------------------------------------------

    work_orders[
        "location_assignment_type"
    ] = "PROTOTYPE_DETERMINISTIC"

    # -----------------------------------------------------------------------
    # Final fields
    # -----------------------------------------------------------------------

    output_columns = [
        "work_order_id",
        "task_id",
        "source_maintenance_row",

        "section_id",
        "station_a_code",
        "station_a_name",
        "station_b_code",
        "station_b_name",
        "section_unique_trains",

        "department",
        "task_type",

        "priority_level",
        "priority_rank",

        "required_minutes",

        "maintenance_needed",
        "failure_type",
        "failure_severity",

        "ballast_condition",
        "signal_system_status",

        "rail_wear_mm",
        "track_vibration_level",
        "inspection_score",
        "last_maintenance_days",

        "location_assignment_type",
    ]

    work_orders = work_orders[
        output_columns
    ]

    # -----------------------------------------------------------------------
    # Sort for planner
    # -----------------------------------------------------------------------

    work_orders = work_orders.sort_values(
        [
            "priority_rank",
            "required_minutes",
            "work_order_id",
        ],
        ascending=[
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    work_orders.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Report statistics
    # -----------------------------------------------------------------------

    priority_counts = (
        work_orders[
            "priority_level"
        ]
        .value_counts()
    )

    department_counts = (
        work_orders[
            "department"
        ]
        .value_counts()
    )

    duration_counts = (
        work_orders[
            "required_minutes"
        ]
        .value_counts()
        .sort_index()
    )

    unique_assigned_sections = (
        work_orders[
            "section_id"
        ]
        .nunique()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Maintenance Work Order Report",
        "=" * 72,
        "",
        f"Source candidates       : {len(candidates):,}",
        f"Work orders created     : {len(work_orders):,}",
        f"Planning sections used  : {unique_assigned_sections:,}",
        "",
        "PRIORITY DISTRIBUTION",
        "-" * 72,
    ]

    for priority, count in priority_counts.items():
        report.append(
            f"{priority:<20} {count:>8,}"
        )

    report.extend(
        [
            "",
            "DEPARTMENT DISTRIBUTION",
            "-" * 72,
        ]
    )

    for department, count in department_counts.items():
        report.append(
            f"{department:<25} {count:>8,}"
        )

    report.extend(
        [
            "",
            "REQUIRED BLOCK DURATIONS",
            "-" * 72,
        ]
    )

    for duration, count in duration_counts.items():
        report.append(
            f"{int(duration):>4} minutes       {count:>8,}"
        )

    report.extend(
        [
            "",
            "IMPORTANT PROTOTYPE NOTE",
            "-" * 72,
            (
                "The maintenance source dataset contains no genuine "
                "railway section/location information."
            ),
            (
                "Section assignment is therefore deterministic prototype "
                "mapping for demonstrating TrackEase block planning."
            ),
            (
                "It must not be presented as an observed maintenance "
                "location from the source dataset."
            ),
            "",
            "DURATION NOTE",
            "-" * 72,
            (
                "Required maintenance durations are transparent rule-based "
                "prototype estimates because no validated duration target "
                "exists in the source maintenance dataset."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console result
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("MAINTENANCE WORK ORDER BUILD COMPLETE")
    print("=" * 72)

    print(
        f"\nWork orders created : "
        f"{len(work_orders):,}"
    )

    print(
        f"Sections assigned   : "
        f"{unique_assigned_sections:,}"
    )

    print("\nPriorities:")

    for priority, count in priority_counts.items():
        print(
            f"  {priority:<10} {count:>6,}"
        )

    print("\nDepartments:")

    for department, count in department_counts.items():
        print(
            f"  {department:<24} {count:>6,}"
        )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nSection locations are explicitly marked "
        "as prototype assignments."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_work_orders()