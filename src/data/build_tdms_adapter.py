"""
TrackEase - TDMS Prototype Adapter

Purpose:
    Create a controlled prototype representation of TDMS
    (Traction Distribution / Electrical) maintenance requirements.

Input:
    data/processed/railway_sections.csv

Outputs:
    data/processed/tdms_prototype_tasks.csv
    data/processed/tdms_adapter_report.txt

Important:
    - TrackEase does NOT claim access to real TDMS production data.
    - These tasks are deterministic prototype records.
    - Real railway sections are used.
    - Electrical task type, duration and priority are prototype values
      created only to demonstrate multi-department block coordination.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

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
    / "tdms_prototype_tasks.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "tdms_adapter_report.txt"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TOTAL_TDMS_TASKS = 200


ELECTRICAL_TASKS = [
    {
        "task_type": "OHE inspection",
        "asset_category": "Overhead Equipment",
        "required_minutes": 90,
    },
    {
        "task_type": "OHE preventive maintenance",
        "asset_category": "Overhead Equipment",
        "required_minutes": 120,
    },
    {
        "task_type": "Traction power equipment inspection",
        "asset_category": "Traction Power",
        "required_minutes": 75,
    },
    {
        "task_type": "Sectioning equipment maintenance",
        "asset_category": "Sectioning Equipment",
        "required_minutes": 120,
    },
    {
        "task_type": "Electrical isolation inspection",
        "asset_category": "Electrical Isolation",
        "required_minutes": 60,
    },
]


# ---------------------------------------------------------------------------
# Priority logic
# ---------------------------------------------------------------------------

def assign_priority(index: int):
    """
    Assign deterministic prototype priority.

    Distribution intentionally contains multiple priority levels
    so the future optimizer can demonstrate scheduling behaviour.
    """

    position = index % 20

    if position < 2:
        return "Critical", 4

    if position < 7:
        return "High", 3

    if position < 15:
        return "Medium", 2

    return "Low", 1


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------

def build_tdms_adapter():
    """Build prototype TDMS electrical maintenance requirements."""

    print("=" * 72)
    print("TrackEase - TDMS Prototype Adapter")
    print("=" * 72)

    print("\nRailway sections:")
    print(f"  {SECTIONS_FILE}")

    if not SECTIONS_FILE.exists():
        raise FileNotFoundError(
            f"Railway section file not found:\n{SECTIONS_FILE}"
        )

    print("  ✓ Found")

    sections = pd.read_csv(SECTIONS_FILE)

    print(
        f"\nRailway sections loaded : "
        f"{len(sections):,}"
    )

    # -----------------------------------------------------------------------
    # Select useful operational sections
    # -----------------------------------------------------------------------

    eligible = sections[
        sections["unique_trains"] >= 2
    ].copy()

    if eligible.empty:
        eligible = sections.copy()

    # Prefer more operationally active sections for the prototype.
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
    ).reset_index(drop=True)

    selected = eligible.head(
        TOTAL_TDMS_TASKS
    ).copy()

    # -----------------------------------------------------------------------
    # Build prototype TDMS tasks
    # -----------------------------------------------------------------------

    task_rows = []

    for index, section in selected.iterrows():

        template = ELECTRICAL_TASKS[
            index % len(ELECTRICAL_TASKS)
        ]

        priority_level, priority_rank = (
            assign_priority(index)
        )

        required_minutes = int(
            template["required_minutes"]
        )

        # Critical jobs get a small duration allowance.
        if priority_level == "Critical":
            required_minutes += 30

        elif priority_level == "High":
            required_minutes += 15

        task_rows.append(
            {
                "tdms_task_id":
                    f"TDMS-{index + 1:05d}",

                "source_system":
                    "TDMS",

                "department":
                    "Electrical",

                "asset_category":
                    template["asset_category"],

                "task_type":
                    template["task_type"],

                "section_id":
                    section["section_id"],

                "station_a_code":
                    section["station_a_code"],

                "station_a_name":
                    section["station_a_name"],

                "station_b_code":
                    section["station_b_code"],

                "station_b_name":
                    section["station_b_name"],

                "section_unique_trains":
                    int(section["unique_trains"]),

                "priority_level":
                    priority_level,

                "priority_rank":
                    priority_rank,

                "required_minutes":
                    required_minutes,

                "task_status":
                    "PENDING",

                "planning_horizon":
                    "UNASSIGNED",

                "coordination_group":
                    "",

                "coordination_eligible":
                    1,

                "integration_mode":
                    "PROTOTYPE_ADAPTER",

                "source_data_type":
                    "PROTOTYPE_TDMS",

                "location_assignment_type":
                    "REAL_SECTION_PROTOTYPE_TASK",
            }
        )

    tdms = pd.DataFrame(
        task_rows
    )

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    tdms.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Statistics
    # -----------------------------------------------------------------------

    priority_counts = (
        tdms["priority_level"]
        .value_counts()
    )

    task_counts = (
        tdms["task_type"]
        .value_counts()
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase TDMS Prototype Adapter Report",
        "=" * 72,
        "",
        f"Railway sections available : {len(sections):,}",
        f"Eligible sections          : {len(eligible):,}",
        f"TDMS tasks created         : {len(tdms):,}",
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
            "TASK DISTRIBUTION",
            "-" * 72,
        ]
    )

    for task, count in task_counts.items():
        report.append(
            f"{task:<40} {count:>8,}"
        )

    report.extend(
        [
            "",
            "IMPORTANT PROTOTYPE NOTE",
            "-" * 72,
            (
                "These records represent a TDMS integration adapter "
                "for prototype demonstration only."
            ),
            (
                "TrackEase does not claim that these tasks originated "
                "from a live Indian Railways TDMS system."
            ),
            (
                "Railway section identifiers are real sections derived "
                "from the TrackEase timetable dataset."
            ),
            (
                "Task types, priorities and maintenance durations are "
                "controlled deterministic prototype values."
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
    print("TDMS PROTOTYPE ADAPTER COMPLETE")
    print("=" * 72)

    print(
        f"\nTDMS tasks created : "
        f"{len(tdms):,}"
    )

    print(
        f"Sections represented: "
        f"{tdms['section_id'].nunique():,}"
    )

    print("\nPriorities:")

    for priority, count in priority_counts.items():
        print(
            f"  {priority:<10} {count:>6,}"
        )

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")

    print(
        "\nTDMS is now represented through a transparent "
        "prototype electrical-maintenance adapter."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_tdms_adapter()