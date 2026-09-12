"""
TrackEase - Multi-Department Maintenance Coordinator

Purpose:
    Detect maintenance requirements on the same railway section that
    can potentially be coordinated into a common maintenance block.

Input:
    data/processed/prioritized_maintenance_tasks.csv

Outputs:
    data/processed/coordinated_planning_tasks.csv
    data/processed/maintenance_coordination_groups.csv
    data/processed/coordination_report.txt

Important:
    Coordination-duration calculations are transparent prototype
    assumptions. They demonstrate planning logic and must not be
    presented as official railway maintenance-duration rules.
"""

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "prioritized_maintenance_tasks.csv"
)

PLANNING_OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coordinated_planning_tasks.csv"
)

GROUP_OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "maintenance_coordination_groups.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "coordination_report.txt"
)


# ---------------------------------------------------------------------------
# Prototype assumptions
# ---------------------------------------------------------------------------

COORDINATION_OVERHEAD_MINUTES = 10


# ---------------------------------------------------------------------------
# Department helpers
# ---------------------------------------------------------------------------

def expand_department(value):
    """
    Convert TrackEase department labels into the actual participating
    railway departments.
    """

    value = str(value)

    if value == "Engineering + S&T":
        return {"Engineering", "S&T"}

    if value == "Engineering":
        return {"Engineering"}

    if value == "S&T":
        return {"S&T"}

    if value == "Electrical":
        return {"Electrical"}

    return set()


def priority_level_from_score(score):
    """Convert TrackEase numeric priority score into its final level."""

    if score >= 80:
        return "Critical"

    if score >= 60:
        return "High"

    if score >= 40:
        return "Medium"

    return "Low"


# ---------------------------------------------------------------------------
# Coordination duration
# ---------------------------------------------------------------------------

def calculate_joint_duration(group):
    """
    Estimate coordinated block duration.

    Logic:
        - Tasks belonging to the same department are assumed sequential.
        - Different departments may work in parallel where operationally
          permitted.
        - Joint Engineering + S&T tasks consume workload for both
          Engineering and S&T.
        - A small coordination overhead is added.
        - Coordinated duration can never exceed the sum of individual
          block durations.

    This is a prototype planning assumption.
    """

    workloads = {
        "Engineering": 0,
        "S&T": 0,
        "Electrical": 0,
    }

    separate_total = 0

    for row in group.itertuples():

        duration = int(
            row.required_minutes
        )

        separate_total += duration

        departments = expand_department(
            row.department
        )

        for department in departments:

            if department in workloads:
                workloads[department] += duration

    active_workloads = [
        value
        for value in workloads.values()
        if value > 0
    ]

    if not active_workloads:
        return separate_total, separate_total, workloads

    parallel_workload = max(
        active_workloads
    )

    estimated_joint = (
        parallel_workload
        + COORDINATION_OVERHEAD_MINUTES
    )

    # Coordination must never make the block longer than
    # separate execution.
    joint_duration = min(
        estimated_joint,
        separate_total,
    )

    return (
        separate_total,
        joint_duration,
        workloads,
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def coordinate_maintenance():
    """Build coordinated maintenance planning units."""

    print("=" * 72)
    print("TrackEase - Multi-Department Maintenance Coordinator")
    print("=" * 72)

    print("\nInput:")
    print(f"  {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Prioritized maintenance tasks not found:\n{INPUT_FILE}"
        )

    print("  ✓ Found")

    tasks = pd.read_csv(
        INPUT_FILE
    )

    print(
        f"\nPrioritized tasks loaded : "
        f"{len(tasks):,}"
    )

    print(
        f"Sections represented     : "
        f"{tasks['section_id'].nunique():,}"
    )

    # -----------------------------------------------------------------------
    # Determine the actual departments represented on each section
    # -----------------------------------------------------------------------

    section_departments = {}

    for row in tasks.itertuples():

        section_departments.setdefault(
            row.section_id,
            set(),
        )

        section_departments[
            row.section_id
        ].update(
            expand_department(
                row.department
            )
        )

    # -----------------------------------------------------------------------
    # Create coordination groups and planner inputs
    # -----------------------------------------------------------------------

    coordination_groups = []
    planning_rows = []

    coordination_counter = 1
    planning_counter = 1

    tasks_consumed = set()

    # -----------------------------------------------------------------------
    # Process section by section
    # -----------------------------------------------------------------------

    for section_id, group in tasks.groupby(
        "section_id",
        sort=True,
    ):

        group = group.copy()

        actual_departments = (
            section_departments.get(
                section_id,
                set(),
            )
        )

        # ---------------------------------------------------------------
        # Create a new coordinated group only if:
        #
        # 1. At least two maintenance task records exist on the section.
        # 2. At least two actual departments are represented.
        #
        # A single Engineering + S&T source task is already joint and
        # should not generate artificial "new" coordination savings.
        # ---------------------------------------------------------------

        should_coordinate = (
            len(group) >= 2
            and len(actual_departments) >= 2
        )

        if not should_coordinate:
            continue

        coordination_id = (
            f"COORD-{coordination_counter:05d}"
        )

        coordination_counter += 1

        (
            separate_minutes,
            joint_minutes,
            workloads,
        ) = calculate_joint_duration(
            group
        )

        minutes_saved = max(
            separate_minutes
            - joint_minutes,
            0,
        )

        saving_percent = (
            minutes_saved
            / separate_minutes
            * 100
            if separate_minutes > 0
            else 0
        )

        highest_score = float(
            group[
                "trackease_priority_score"
            ].max()
        )

        group_priority = (
            priority_level_from_score(
                highest_score
            )
        )

        task_ids = (
            group[
                "unified_task_id"
            ]
            .astype(str)
            .tolist()
        )

        source_systems = sorted(
            group[
                "source_system"
            ]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        departments_text = (
            " + ".join(
                sorted(actual_departments)
            )
        )

        # ---------------------------------------------------------------
        # Coordination-group record
        # ---------------------------------------------------------------

        first = group.iloc[0]

        coordination_groups.append(
            {
                "coordination_group":
                    coordination_id,

                "section_id":
                    section_id,

                "station_a_code":
                    first.get(
                        "station_a_code"
                    ),

                "station_a_name":
                    first.get(
                        "station_a_name"
                    ),

                "station_b_code":
                    first.get(
                        "station_b_code"
                    ),

                "station_b_name":
                    first.get(
                        "station_b_name"
                    ),

                "task_count":
                    len(group),

                "department_count":
                    len(actual_departments),

                "departments_involved":
                    departments_text,

                "source_systems":
                    "|".join(
                        source_systems
                    ),

                "source_task_ids":
                    "|".join(
                        task_ids
                    ),

                "highest_priority_score":
                    round(
                        highest_score,
                        2,
                    ),

                "coordination_priority":
                    group_priority,

                "separate_minutes_total":
                    int(
                        separate_minutes
                    ),

                "coordinated_required_minutes":
                    int(
                        joint_minutes
                    ),

                "estimated_minutes_saved":
                    int(
                        minutes_saved
                    ),

                "estimated_saving_percent":
                    round(
                        saving_percent,
                        2,
                    ),

                "engineering_workload_minutes":
                    int(
                        workloads[
                            "Engineering"
                        ]
                    ),

                "st_workload_minutes":
                    int(
                        workloads[
                            "S&T"
                        ]
                    ),

                "electrical_workload_minutes":
                    int(
                        workloads[
                            "Electrical"
                        ]
                    ),

                "coordination_assumption":
                    "PROTOTYPE_PARALLEL_DEPARTMENT_WORK",
            }
        )

        # ---------------------------------------------------------------
        # Planner-level coordinated unit
        # ---------------------------------------------------------------

        planning_rows.append(
            {
                "planning_task_id":
                    f"PT-{planning_counter:06d}",

                "planning_task_type":
                    "COORDINATED",

                "coordination_group":
                    coordination_id,

                "section_id":
                    section_id,

                "station_a_code":
                    first.get(
                        "station_a_code"
                    ),

                "station_a_name":
                    first.get(
                        "station_a_name"
                    ),

                "station_b_code":
                    first.get(
                        "station_b_code"
                    ),

                "station_b_name":
                    first.get(
                        "station_b_name"
                    ),

                "departments_involved":
                    departments_text,

                "source_systems":
                    "|".join(
                        source_systems
                    ),

                "source_task_ids":
                    "|".join(
                        task_ids
                    ),

                "task_count":
                    len(group),

                "department_count":
                    len(actual_departments),

                "trackease_priority_score":
                    round(
                        highest_score,
                        2,
                    ),

                "trackease_priority_level":
                    group_priority,

                "required_minutes":
                    int(
                        joint_minutes
                    ),

                "separate_minutes_total":
                    int(
                        separate_minutes
                    ),

                "estimated_minutes_saved":
                    int(
                        minutes_saved
                    ),

                "estimated_saving_percent":
                    round(
                        saving_percent,
                        2,
                    ),

                "coordination_status":
                    "COORDINATED",

                "planning_status":
                    "PENDING",
            }
        )

        planning_counter += 1

        tasks_consumed.update(
            task_ids
        )

    # -----------------------------------------------------------------------
    # Add all remaining tasks as standalone planning units
    # -----------------------------------------------------------------------

    remaining_tasks = tasks[
        ~tasks[
            "unified_task_id"
        ].isin(
            tasks_consumed
        )
    ].copy()

    for row in remaining_tasks.itertuples():

        actual_departments = (
            expand_department(
                row.department
            )
        )

        # A source Engineering + S&T task is already a joint requirement.
        if (
            row.department
            == "Engineering + S&T"
        ):
            planning_type = (
                "PRECOORDINATED_SOURCE"
            )

            coordination_status = (
                "SOURCE_JOINT_TASK"
            )

        else:
            planning_type = "SINGLE"

            coordination_status = (
                "NOT_COORDINATED"
            )

        planning_rows.append(
            {
                "planning_task_id":
                    f"PT-{planning_counter:06d}",

                "planning_task_type":
                    planning_type,

                "coordination_group":
                    "",

                "section_id":
                    row.section_id,

                "station_a_code":
                    getattr(
                        row,
                        "station_a_code",
                        None,
                    ),

                "station_a_name":
                    getattr(
                        row,
                        "station_a_name",
                        None,
                    ),

                "station_b_code":
                    getattr(
                        row,
                        "station_b_code",
                        None,
                    ),

                "station_b_name":
                    getattr(
                        row,
                        "station_b_name",
                        None,
                    ),

                "departments_involved":
                    " + ".join(
                        sorted(
                            actual_departments
                        )
                    ),

                "source_systems":
                    str(
                        row.source_system
                    ),

                "source_task_ids":
                    str(
                        row.unified_task_id
                    ),

                "task_count":
                    1,

                "department_count":
                    len(
                        actual_departments
                    ),

                "trackease_priority_score":
                    float(
                        row.trackease_priority_score
                    ),

                "trackease_priority_level":
                    row.trackease_priority_level,

                "required_minutes":
                    int(
                        row.required_minutes
                    ),

                "separate_minutes_total":
                    int(
                        row.required_minutes
                    ),

                "estimated_minutes_saved":
                    0,

                "estimated_saving_percent":
                    0.0,

                "coordination_status":
                    coordination_status,

                "planning_status":
                    "PENDING",
            }
        )

        planning_counter += 1

    # -----------------------------------------------------------------------
    # Build output DataFrames
    # -----------------------------------------------------------------------

    planning = pd.DataFrame(
        planning_rows
    )

    groups = pd.DataFrame(
        coordination_groups
    )

    # -----------------------------------------------------------------------
    # Sort planner inputs by priority
    # -----------------------------------------------------------------------

    planning = planning.sort_values(
        [
            "trackease_priority_score",
            "required_minutes",
            "planning_task_id",
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

    planning.to_csv(
        PLANNING_OUTPUT_FILE,
        index=False,
    )

    groups.to_csv(
        GROUP_OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    coordinated_group_count = len(
        groups
    )

    tasks_bundled = len(
        tasks_consumed
    )

    coordinated_planning_units = int(
        (
            planning[
                "planning_task_type"
            ]
            == "COORDINATED"
        ).sum()
    )

    source_joint_units = int(
        (
            planning[
                "planning_task_type"
            ]
            == "PRECOORDINATED_SOURCE"
        ).sum()
    )

    single_units = int(
        (
            planning[
                "planning_task_type"
            ]
            == "SINGLE"
        ).sum()
    )

    original_minutes = int(
        pd.to_numeric(
            tasks[
                "required_minutes"
            ],
            errors="coerce",
        )
        .fillna(0)
        .sum()
    )

    planned_minutes = int(
        planning[
            "required_minutes"
        ].sum()
    )

    total_minutes_saved = (
        original_minutes
        - planned_minutes
    )

    saving_percentage = (
        total_minutes_saved
        / original_minutes
        * 100
        if original_minutes > 0
        else 0
    )

    if groups.empty:

        two_department_groups = 0
        three_department_groups = 0

    else:

        two_department_groups = int(
            (
                groups[
                    "department_count"
                ]
                == 2
            ).sum()
        )

        three_department_groups = int(
            (
                groups[
                    "department_count"
                ]
                >= 3
            ).sum()
        )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase Multi-Department Coordination Report",
        "=" * 72,
        "",
        "INPUT",
        "-" * 72,
        f"Prioritized maintenance tasks   : {len(tasks):,}",
        f"Railway sections represented    : {tasks['section_id'].nunique():,}",
        "",
        "COORDINATION",
        "-" * 72,
        f"New coordination groups         : {coordinated_group_count:,}",
        f"Maintenance tasks bundled       : {tasks_bundled:,}",
        f"Two-department groups           : {two_department_groups:,}",
        f"Three-department groups         : {three_department_groups:,}",
        f"Existing source joint tasks     : {source_joint_units:,}",
        "",
        "PLANNER INPUT",
        "-" * 72,
        f"Original maintenance tasks      : {len(tasks):,}",
        f"Final planning units            : {len(planning):,}",
        f"Coordinated planning units      : {coordinated_planning_units:,}",
        f"Standalone planning units       : {single_units:,}",
        "",
        "ESTIMATED INFRASTRUCTURE DOWNTIME",
        "-" * 72,
        f"Separate-task duration total    : {original_minutes:,} minutes",
        f"Coordinated duration total      : {planned_minutes:,} minutes",
        f"Estimated minutes saved         : {total_minutes_saved:,} minutes",
        f"Estimated reduction             : {saving_percentage:.2f}%",
        "",
        "PROTOTYPE COORDINATION ASSUMPTION",
        "-" * 72,
        (
            "Tasks belonging to the same department are treated as "
            "sequential workload."
        ),
        (
            "Different departments on the same section may operate "
            "in parallel where coordination is assumed feasible."
        ),
        (
            f"A {COORDINATION_OVERHEAD_MINUTES}-minute coordination "
            "overhead is included."
        ),
        (
            "These values demonstrate optimization logic and are not "
            "official Indian Railways maintenance-duration rules."
        ),
        "",
        "NEXT STAGE",
        "-" * 72,
        (
            "Integrate COA / goods-train forecast information before "
            "the final impact-aware weekly and monthly block optimizer."
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
    print("MULTI-DEPARTMENT COORDINATION COMPLETE")
    print("=" * 72)

    print(
        f"\nOriginal maintenance tasks : "
        f"{len(tasks):,}"
    )

    print(
        f"Coordination groups        : "
        f"{coordinated_group_count:,}"
    )

    print(
        f"Tasks bundled              : "
        f"{tasks_bundled:,}"
    )

    print(
        f"Final planning units       : "
        f"{len(planning):,}"
    )

    print("\nDepartment coordination:")

    print(
        f"  Two-department groups   : "
        f"{two_department_groups:,}"
    )

    print(
        f"  Three-department groups : "
        f"{three_department_groups:,}"
    )

    print(
        f"  Existing joint tasks    : "
        f"{source_joint_units:,}"
    )

    print("\nEstimated block-time impact:")

    print(
        f"  Separate duration   : "
        f"{original_minutes:,} min"
    )

    print(
        f"  Coordinated duration: "
        f"{planned_minutes:,} min"
    )

    print(
        f"  Minutes saved       : "
        f"{total_minutes_saved:,} min"
    )

    print(
        f"  Reduction           : "
        f"{saving_percentage:.2f}%"
    )

    print("\nOutputs:")
    print(
        f"  {PLANNING_OUTPUT_FILE}"
    )
    print(
        f"  {GROUP_OUTPUT_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nTrackEase now coordinates departmental "
        "maintenance requirements before block optimization."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    coordinate_maintenance()