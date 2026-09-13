"""
TrackEase V3.7 - Multi-Department Compatibility Graph

Purpose
-------
Build a professional compatibility graph between maintenance tasks that are
located on the same railway section or on adjacent sections.

The graph does NOT authorize tasks to share a block. It identifies candidate
relationships for later optimization and human review:

    - parallel integrated-block candidate
    - sequential integrated/shared-block candidate
    - integrated candidate requiring additional isolation/disconnection
    - adjacent shadow/opportunity candidate after duration/resource checks
    - resource-capacity conflict requiring sequential execution
    - dependency-driven sequencing
    - incompatible candidate

This directly supports the TrackEase research requirements for:
    - same/adjacent location checks
    - parallel vs sequential execution
    - common isolation / disconnection
    - resource compatibility
    - task dependencies
    - safe separation
    - integrated blocks
    - shadow/opportunity blocks

Inputs
------
    data/processed/v3_task_block_requirements.csv
    data/processed/v3_task_timing_components.csv
    data/processed/v3_task_resource_requirements.csv
    data/processed/v3_task_dependencies.csv
    data/processed/v3_sections.csv
    data/processed/v3_crews.csv
    data/processed/v3_crew_skills.csv
    data/processed/v3_machines.csv
    data/processed/v3_equipment.csv

Outputs
-------
    data/processed/v3_task_compatibility_graph.csv
    data/processed/v3_coordination_groups.csv
    data/processed/v3_compatibility_report.txt

All compatibility rules in this module are deterministic TrackEase prototype
planning rules, not official Indian Railways compatibility standards.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import Path
from hashlib import sha1

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

BLOCK_REQUIREMENTS_FILE = (
    PROCESSED_DIR / "v3_task_block_requirements.csv"
)
TIMING_FILE = (
    PROCESSED_DIR / "v3_task_timing_components.csv"
)
RESOURCE_REQUIREMENTS_FILE = (
    PROCESSED_DIR / "v3_task_resource_requirements.csv"
)
DEPENDENCIES_FILE = (
    PROCESSED_DIR / "v3_task_dependencies.csv"
)
SECTIONS_FILE = (
    PROCESSED_DIR / "v3_sections.csv"
)

CREWS_FILE = (
    PROCESSED_DIR / "v3_crews.csv"
)
CREW_SKILLS_FILE = (
    PROCESSED_DIR / "v3_crew_skills.csv"
)
MACHINES_FILE = (
    PROCESSED_DIR / "v3_machines.csv"
)
EQUIPMENT_FILE = (
    PROCESSED_DIR / "v3_equipment.csv"
)

GRAPH_OUTPUT = (
    PROCESSED_DIR / "v3_task_compatibility_graph.csv"
)
GROUPS_OUTPUT = (
    PROCESSED_DIR / "v3_coordination_groups.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_compatibility_report.txt"
)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

DATA_ORIGIN = "TRACKEASE_V3_DERIVED_COMPATIBILITY"
INTEGRATION_MODE = "PROTOTYPE_MULTI_DEPARTMENT_COMPATIBILITY_ENGINE"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_text(value: object, default: str = "") -> str:
    if pd.isna(value):
        return default

    text = str(value).strip()

    if text.lower() in {
        "nan",
        "none",
        "<na>",
    }:
        return default

    return text


def bool_value(value: object, default: bool = False) -> bool:
    if pd.isna(value):
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {
        "true",
        "1",
        "yes",
        "y",
    }:
        return True

    if text in {
        "false",
        "0",
        "no",
        "n",
    }:
        return False

    return default


def stable_id(
    prefix: str,
    *parts: object,
    length: int = 12,
) -> str:

    normalized = "|".join(
        clean_text(
            part
        ).upper()
        for part in parts
    )

    digest = sha1(
        normalized.encode(
            "utf-8"
        )
    ).hexdigest()[:length].upper()

    return f"{prefix}-{digest}"


def first_existing(
    columns: list[str],
    candidates: list[str],
) -> str | None:

    column_set = set(
        columns
    )

    for candidate in candidates:
        if candidate in column_set:
            return candidate

    return None


def require_inputs() -> None:
    required = [
        BLOCK_REQUIREMENTS_FILE,
        TIMING_FILE,
        RESOURCE_REQUIREMENTS_FILE,
        DEPENDENCIES_FILE,
        SECTIONS_FILE,
        CREWS_FILE,
        CREW_SKILLS_FILE,
        MACHINES_FILE,
        EQUIPMENT_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.7 inputs are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


def department_set(value: object) -> set[str]:
    text = clean_text(
        value
    )

    return {
        part.strip()
        for part in text.split(
            "|"
        )
        if part.strip()
    }


# ---------------------------------------------------------------------------
# Section adjacency
# ---------------------------------------------------------------------------

def identify_section_endpoints(
    sections: pd.DataFrame,
) -> tuple[str, str]:

    columns = sections.columns.tolist()

    station_a = first_existing(
        columns,
        [
            "station_a_code",
            "from_station_code",
            "source_station_code",
            "station_1_code",
            "station1_code",
            "from_station",
            "station_a",
        ],
    )

    station_b = first_existing(
        columns,
        [
            "station_b_code",
            "to_station_code",
            "destination_station_code",
            "station_2_code",
            "station2_code",
            "to_station",
            "station_b",
        ],
    )

    if (
        station_a is None
        or station_b is None
    ):
        raise ValueError(
            "Could not identify section endpoint columns in v3_sections.csv."
        )

    return (
        station_a,
        station_b,
    )


def build_section_adjacency(
    sections: pd.DataFrame,
) -> tuple[
    dict[str, tuple[str, str]],
    dict[str, set[str]],
]:

    station_a_col, station_b_col = (
        identify_section_endpoints(
            sections
        )
    )

    endpoints: dict[
        str,
        tuple[str, str]
    ] = {}

    station_to_sections: dict[
        str,
        set[str]
    ] = defaultdict(
        set
    )

    for row in sections.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        section_id = clean_text(
            row_dict.get(
                "section_id"
            )
        )

        station_a = clean_text(
            row_dict.get(
                station_a_col
            )
        )

        station_b = clean_text(
            row_dict.get(
                station_b_col
            )
        )

        if not (
            section_id
            and station_a
            and station_b
        ):
            continue

        endpoints[
            section_id
        ] = (
            station_a,
            station_b,
        )

        station_to_sections[
            station_a
        ].add(
            section_id
        )

        station_to_sections[
            station_b
        ].add(
            section_id
        )

    adjacency: dict[
        str,
        set[str]
    ] = defaultdict(
        set
    )

    for section_ids in station_to_sections.values():
        section_list = sorted(
            section_ids
        )

        for section_a, section_b in combinations(
            section_list,
            2,
        ):
            adjacency[
                section_a
            ].add(
                section_b
            )

            adjacency[
                section_b
            ].add(
                section_a
            )

    return (
        endpoints,
        dict(
            adjacency
        ),
    )


# ---------------------------------------------------------------------------
# Resource capacity
# ---------------------------------------------------------------------------

def build_resource_capacity(
    crews: pd.DataFrame,
    crew_skills: pd.DataFrame,
    machines: pd.DataFrame,
    equipment: pd.DataFrame,
) -> dict[str, dict[str, int]]:

    skill_capacity = (
        crew_skills[
            [
                "crew_id",
                "skill_code",
            ]
        ]
        .drop_duplicates()
        .groupby(
            "skill_code"
        )[
            "crew_id"
        ]
        .nunique()
        .astype(
            int
        )
        .to_dict()
    )

    machine_capacity = (
        machines.groupby(
            "machine_type"
        )[
            "machine_id"
        ]
        .nunique()
        .astype(
            int
        )
        .to_dict()
    )

    available_equipment = equipment.copy()

    if (
        "status"
        in available_equipment.columns
    ):
        available_equipment = (
            available_equipment[
                available_equipment[
                    "status"
                ]
                .astype(
                    str
                )
                .eq(
                    "AVAILABLE"
                )
            ]
        )

    equipment_capacity = (
        available_equipment.groupby(
            "equipment_type"
        )[
            "equipment_id"
        ]
        .nunique()
        .astype(
            int
        )
        .to_dict()
    )

    return {
        "CREW":
            skill_capacity,

        "MACHINE":
            machine_capacity,

        "EQUIPMENT":
            equipment_capacity,
    }


def build_task_resource_sets(
    requirements: pd.DataFrame,
) -> dict[
    str,
    dict[str, set[str]],
]:

    result: dict[
        str,
        dict[str, set[str]]
    ] = defaultdict(
        lambda: {
            "CREW": set(),
            "MACHINE": set(),
            "EQUIPMENT": set(),
            "MATERIAL": set(),
        }
    )

    for row in requirements.itertuples(
        index=False
    ):
        task_id = clean_text(
            row.task_id
        )

        category = clean_text(
            row.resource_category
        ).upper()

        if category == "CREW":
            code = clean_text(
                row.skill_code
            )

        elif category in {
            "MACHINE",
            "EQUIPMENT",
            "MATERIAL",
        }:
            code = clean_text(
                row.resource_code
            )

        else:
            continue

        if code:
            result[
                task_id
            ][
                category
            ].add(
                code
            )

    return dict(
        result
    )


def shared_capacity_conflicts(
    task_a: str,
    task_b: str,
    task_resources: dict[
        str,
        dict[str, set[str]]
    ],
    capacities: dict[
        str,
        dict[str, int]
    ],
) -> list[str]:

    conflicts = []

    for category in [
        "CREW",
        "MACHINE",
        "EQUIPMENT",
    ]:
        resources_a = (
            task_resources.get(
                task_a,
                {}
            ).get(
                category,
                set(),
            )
        )

        resources_b = (
            task_resources.get(
                task_b,
                {}
            ).get(
                category,
                set(),
            )
        )

        shared = (
            resources_a
            & resources_b
        )

        for code in sorted(
            shared
        ):
            available = int(
                capacities.get(
                    category,
                    {}
                ).get(
                    code,
                    0,
                )
            )

            if available < 2:
                conflicts.append(
                    f"{category}:{code}:CAPACITY={available}"
                )

    return conflicts


# ---------------------------------------------------------------------------
# Dependency index
# ---------------------------------------------------------------------------

def build_dependency_index(
    dependencies: pd.DataFrame,
) -> set[tuple[str, str]]:

    relations: set[
        tuple[str, str]
    ] = set()

    if dependencies.empty:
        return relations

    for row in dependencies.itertuples(
        index=False
    ):
        predecessor = clean_text(
            row.predecessor_task_id
        )
        successor = clean_text(
            row.successor_task_id
        )

        if predecessor and successor:
            relations.add(
                (
                    predecessor,
                    successor,
                )
            )

    return relations


# ---------------------------------------------------------------------------
# Pair generation
# ---------------------------------------------------------------------------

def generate_candidate_pairs(
    tasks: pd.DataFrame,
    adjacency: dict[str, set[str]],
) -> list[
    tuple[str, str, str]
]:

    section_tasks: dict[
        str,
        list[str]
    ] = defaultdict(
        list
    )

    for row in tasks.itertuples(
        index=False
    ):
        section_id = clean_text(
            row.section_id
        )

        task_id = clean_text(
            row.task_id
        )

        if (
            section_id
            and task_id
        ):
            section_tasks[
                section_id
            ].append(
                task_id
            )

    pair_keys: set[
        tuple[str, str, str]
    ] = set()

    # Same-section pairs.
    for section_id, task_ids in section_tasks.items():
        unique_tasks = sorted(
            set(
                task_ids
            )
        )

        for task_a, task_b in combinations(
            unique_tasks,
            2,
        ):
            pair_keys.add(
                (
                    task_a,
                    task_b,
                    "SAME_SECTION",
                )
            )

    # Adjacent-section pairs, only if both sections contain maintenance work.
    task_sections = set(
        section_tasks
    )

    for section_a in sorted(
        task_sections
    ):
        for section_b in sorted(
            adjacency.get(
                section_a,
                set(),
            )
        ):
            if (
                section_b
                not in task_sections
            ):
                continue

            if section_a >= section_b:
                continue

            for task_a in sorted(
                set(
                    section_tasks[
                        section_a
                    ]
                )
            ):
                for task_b in sorted(
                    set(
                        section_tasks[
                            section_b
                        ]
                    )
                ):
                    ordered = tuple(
                        sorted(
                            [
                                task_a,
                                task_b,
                            ]
                        )
                    )

                    pair_keys.add(
                        (
                            ordered[0],
                            ordered[1],
                            "ADJACENT_SECTION",
                        )
                    )

    return sorted(
        pair_keys
    )


# ---------------------------------------------------------------------------
# Compatibility evaluation
# ---------------------------------------------------------------------------

def duration_compatibility(
    task_a: pd.Series,
    task_b: pd.Series,
) -> tuple[bool, float]:
    """
    Pair-level shadow/integrated duration compatibility.

    A shadow opportunity should not be accepted merely because two tasks are
    geographically adjacent. If neither task can be split and one job is far
    longer than the other, the shorter host opportunity is unlikely to contain
    the longer job. TrackEase therefore applies a transparent prototype ratio
    check and leaves exact window fitting to Optimizer V3.
    """

    duration_a = max(
        1,
        int(
            task_a[
                "total_block_expected_minutes"
            ]
        ),
    )

    duration_b = max(
        1,
        int(
            task_b[
                "total_block_expected_minutes"
            ]
        ),
    )

    ratio = (
        max(
            duration_a,
            duration_b,
        )
        / min(
            duration_a,
            duration_b,
        )
    )

    splittable_a = bool_value(
        task_a[
            "work_splittable"
        ]
    )

    splittable_b = bool_value(
        task_b[
            "work_splittable"
        ]
    )

    compatible = (
        splittable_a
        or splittable_b
        or ratio <= 2.5
    )

    return (
        compatible,
        round(
            ratio,
            3,
        ),
    )


def evaluate_pair(
    task_a: pd.Series,
    task_b: pd.Series,
    locality: str,
    dependencies: set[
        tuple[str, str]
    ],
    task_resources: dict[
        str,
        dict[str, set[str]]
    ],
    capacities: dict[
        str,
        dict[str, int]
    ],
) -> dict[str, object]:

    task_a_id = clean_text(
        task_a[
            "task_id"
        ]
    )

    task_b_id = clean_text(
        task_b[
            "task_id"
        ]
    )

    departments_a = department_set(
        task_a[
            "departments_required"
        ]
    )

    departments_b = department_set(
        task_b[
            "departments_required"
        ]
    )

    combined_departments = (
        departments_a
        | departments_b
    )

    cross_department = (
        departments_a
        != departments_b
        or len(
            combined_departments
        ) >= 2
    )

    direct_dependency = (
        (
            task_a_id,
            task_b_id,
        )
        in dependencies
        or (
            task_b_id,
            task_a_id,
        )
        in dependencies
    )

    same_asset = (
        clean_text(
            task_a[
                "asset_id"
            ]
        )
        ==
        clean_text(
            task_b[
                "asset_id"
            ]
        )
    )

    resource_conflicts = (
        shared_capacity_conflicts(
            task_a_id,
            task_b_id,
            task_resources,
            capacities,
        )
    )

    requires_power_a = bool_value(
        task_a[
            "requires_power_block"
        ]
    )

    requires_power_b = bool_value(
        task_b[
            "requires_power_block"
        ]
    )

    requires_disconnect_a = bool_value(
        task_a[
            "requires_disconnection"
        ]
    )

    requires_disconnect_b = bool_value(
        task_b[
            "requires_disconnection"
        ]
    )

    requires_traffic_a = bool_value(
        task_a[
            "requires_traffic_block"
        ]
    )

    requires_traffic_b = bool_value(
        task_b[
            "requires_traffic_block"
        ]
    )

    additional_power_isolation = (
        requires_power_a
        != requires_power_b
    )

    additional_disconnection = (
        requires_disconnect_a
        != requires_disconnect_b
    )

    common_traffic_restriction = (
        requires_traffic_a
        and requires_traffic_b
    )

    common_power_isolation = (
        requires_power_a
        and requires_power_b
    )

    common_disconnection = (
        requires_disconnect_a
        and requires_disconnect_b
    )

    shadow_eligible = (
        bool_value(
            task_a[
                "eligible_for_shadow_block"
            ]
        )
        and bool_value(
            task_b[
                "eligible_for_shadow_block"
            ]
        )
    )

    (
        duration_compatible,
        duration_ratio,
    ) = duration_compatibility(
        task_a,
        task_b,
    )

    strict_shadow_candidate = (
        shadow_eligible
        and duration_compatible
        and not direct_dependency
        and not same_asset
        and not resource_conflicts
    )

    reasons = []

    if direct_dependency:
        reasons.append(
            "DIRECT_TASK_DEPENDENCY"
        )

    if same_asset:
        reasons.append(
            "SAME_ASSET"
        )

    if resource_conflicts:
        reasons.append(
            "SCARCE_SHARED_RESOURCE:"
            + "|".join(
                resource_conflicts
            )
        )

    if additional_power_isolation:
        reasons.append(
            "ADDITIONAL_POWER_ISOLATION_REQUIRED"
        )

    if additional_disconnection:
        reasons.append(
            "ADDITIONAL_DISCONNECTION_REQUIRED"
        )

    if not duration_compatible:
        reasons.append(
            f"DURATION_PROFILE_MISMATCH:RATIO={duration_ratio}"
        )

    if locality == "SAME_SECTION":
        integrated_candidate = (
            cross_department
        )

        shadow_candidate = False

        if (
            direct_dependency
            or same_asset
        ):
            compatibility_status = (
                "COMPATIBLE_SEQUENTIAL"
            )

            relationship_type = (
                "SEQUENTIAL_INTEGRATED_CANDIDATE"
                if integrated_candidate
                else "SEQUENTIAL_SHARED_BLOCK_CANDIDATE"
            )

            parallel_possible = False
            sequential_possible = True

        elif resource_conflicts:
            compatibility_status = (
                "COMPATIBLE_SEQUENTIAL"
            )

            relationship_type = (
                "SEQUENTIAL_RESOURCE_CONSTRAINED_CANDIDATE"
            )

            parallel_possible = False
            sequential_possible = True

        elif (
            additional_power_isolation
            or additional_disconnection
        ):
            compatibility_status = (
                "CONDITIONAL"
            )

            relationship_type = (
                "PARALLEL_WITH_ADDITIONAL_ISOLATION_REVIEW"
                if integrated_candidate
                else "SHARED_BLOCK_WITH_ADDITIONAL_ISOLATION_REVIEW"
            )

            parallel_possible = True
            sequential_possible = True

        else:
            compatibility_status = (
                "COMPATIBLE_PARALLEL"
            )

            relationship_type = (
                "PARALLEL_INTEGRATED_CANDIDATE"
                if integrated_candidate
                else "PARALLEL_SHARED_BLOCK_CANDIDATE"
            )

            parallel_possible = True
            sequential_possible = True

    else:
        integrated_candidate = False

        if (
            direct_dependency
            or same_asset
        ):
            compatibility_status = (
                "COMPATIBLE_SEQUENTIAL"
            )

            relationship_type = (
                "ADJACENT_SEQUENTIAL_COORDINATION"
            )

            parallel_possible = False
            sequential_possible = True
            shadow_candidate = False

        elif resource_conflicts:
            compatibility_status = (
                "CONDITIONAL"
            )

            relationship_type = (
                "ADJACENT_RESOURCE_CAPACITY_CONFLICT"
            )

            parallel_possible = False
            sequential_possible = True
            shadow_candidate = False

        elif not duration_compatible:
            compatibility_status = (
                "INCOMPATIBLE"
            )

            relationship_type = (
                "ADJACENT_DURATION_PROFILE_INCOMPATIBLE"
            )

            parallel_possible = False
            sequential_possible = False
            shadow_candidate = False

        elif strict_shadow_candidate:
            compatibility_status = (
                "CONDITIONAL"
            )

            relationship_type = (
                "ADJACENT_SHADOW_WITH_ADDITIONAL_ISOLATION_REVIEW"
                if (
                    additional_power_isolation
                    or additional_disconnection
                )
                else
                "ADJACENT_SHADOW_OPPORTUNITY_CANDIDATE"
            )

            parallel_possible = True
            sequential_possible = True
            shadow_candidate = True

        else:
            compatibility_status = (
                "INCOMPATIBLE"
            )

            relationship_type = (
                "NO_SUPPORTED_ADJACENT_COORDINATION_RULE"
            )

            parallel_possible = False
            sequential_possible = False
            shadow_candidate = False

    if not reasons:
        reasons.append(
            "NO_PAIRWISE_CONFLICT_DETECTED"
        )

    return {
        "locality":
            locality,

        "compatibility_status":
            compatibility_status,

        "relationship_type":
            relationship_type,

        "cross_department":
            cross_department,

        "combined_departments":
            "|".join(
                sorted(
                    combined_departments
                )
            ),

        "direct_dependency":
            direct_dependency,

        "same_asset":
            same_asset,

        "shared_resource_capacity_conflict":
            bool(
                resource_conflicts
            ),

        "resource_conflict_details":
            "|".join(
                resource_conflicts
            ),

        "common_traffic_restriction":
            common_traffic_restriction,

        "common_power_isolation":
            common_power_isolation,

        "common_disconnection":
            common_disconnection,

        "requires_additional_power_isolation":
            additional_power_isolation,

        "requires_additional_disconnection":
            additional_disconnection,

        "duration_compatible":
            duration_compatible,

        "duration_ratio":
            duration_ratio,

        "parallel_execution_possible":
            parallel_possible,

        "sequential_execution_possible":
            sequential_possible,

        "integrated_block_candidate":
            integrated_candidate,

        "shadow_block_candidate":
            shadow_candidate,

        "compatibility_reason":
            "|".join(
                reasons
            ),
    }


def build_compatibility_graph(
    block_requirements: pd.DataFrame,
    timing: pd.DataFrame,
    resource_requirements: pd.DataFrame,
    dependencies: pd.DataFrame,
    sections: pd.DataFrame,
    crews: pd.DataFrame,
    crew_skills: pd.DataFrame,
    machines: pd.DataFrame,
    equipment: pd.DataFrame,
) -> pd.DataFrame:

    (
        _section_endpoints,
        adjacency,
    ) = build_section_adjacency(
        sections
    )

    capacities = (
        build_resource_capacity(
            crews,
            crew_skills,
            machines,
            equipment,
        )
    )

    task_resources = (
        build_task_resource_sets(
            resource_requirements
        )
    )

    dependency_index = (
        build_dependency_index(
            dependencies
        )
    )

    task_table = (
        block_requirements.merge(
            timing[
                [
                    "task_id",
                    "total_block_expected_minutes",
                    "minimum_continuous_possession_minutes",
                    "work_splittable",
                ]
            ],
            on="task_id",
            how="left",
            validate="one_to_one",
        )
    )

    task_lookup = (
        task_table.set_index(
            "task_id",
            drop=False,
        )
    )

    candidate_pairs = (
        generate_candidate_pairs(
            task_table,
            adjacency,
        )
    )

    rows = []

    for (
        task_a_id,
        task_b_id,
        locality,
    ) in candidate_pairs:

        if (
            task_a_id
            not in task_lookup.index
            or task_b_id
            not in task_lookup.index
        ):
            continue

        task_a = task_lookup.loc[
            task_a_id
        ]

        task_b = task_lookup.loc[
            task_b_id
        ]

        evaluation = evaluate_pair(
            task_a,
            task_b,
            locality,
            dependency_index,
            task_resources,
            capacities,
        )

        edge_id = stable_id(
            "COMP",
            task_a_id,
            task_b_id,
            locality,
        )

        rows.append(
            {
                "compatibility_edge_id":
                    edge_id,

                "task_a_id":
                    task_a_id,

                "task_b_id":
                    task_b_id,

                "task_a_section_id":
                    clean_text(
                        task_a[
                            "section_id"
                        ]
                    ),

                "task_b_section_id":
                    clean_text(
                        task_b[
                            "section_id"
                        ]
                    ),

                "task_a_asset_id":
                    clean_text(
                        task_a[
                            "asset_id"
                        ]
                    ),

                "task_b_asset_id":
                    clean_text(
                        task_b[
                            "asset_id"
                        ]
                    ),

                "task_a_expected_block_minutes":
                    int(
                        task_a[
                            "total_block_expected_minutes"
                        ]
                    ),

                "task_b_expected_block_minutes":
                    int(
                        task_b[
                            "total_block_expected_minutes"
                        ]
                    ),

                **evaluation,

                "requires_exact_optimizer_check":
                    True,

                "human_review_required":
                    True,

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,

                "is_prototype_derived":
                    True,
            }
        )

    columns = [
        "compatibility_edge_id",
        "task_a_id",
        "task_b_id",
        "task_a_section_id",
        "task_b_section_id",
        "task_a_asset_id",
        "task_b_asset_id",
        "task_a_expected_block_minutes",
        "task_b_expected_block_minutes",
        "locality",
        "compatibility_status",
        "relationship_type",
        "cross_department",
        "combined_departments",
        "direct_dependency",
        "same_asset",
        "shared_resource_capacity_conflict",
        "resource_conflict_details",
        "common_traffic_restriction",
        "common_power_isolation",
        "common_disconnection",
        "requires_additional_power_isolation",
        "requires_additional_disconnection",
        "duration_compatible",
        "duration_ratio",
        "parallel_execution_possible",
        "sequential_execution_possible",
        "integrated_block_candidate",
        "shadow_block_candidate",
        "compatibility_reason",
        "requires_exact_optimizer_check",
        "human_review_required",
        "data_origin",
        "integration_mode",
        "is_prototype_derived",
    ]

    return pd.DataFrame(
        rows,
        columns=columns,
    )


# ---------------------------------------------------------------------------
# Coordination groups
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self):
        self.parent: dict[
            str,
            str
        ] = {}

    def add(self, value: str) -> None:
        if value not in self.parent:
            self.parent[
                value
            ] = value

    def find(self, value: str) -> str:
        parent = self.parent[
            value
        ]

        if parent != value:
            self.parent[
                value
            ] = self.find(
                parent
            )

        return self.parent[
            value
        ]

    def union(
        self,
        left: str,
        right: str,
    ) -> None:

        self.add(
            left
        )

        self.add(
            right
        )

        root_left = self.find(
            left
        )

        root_right = self.find(
            right
        )

        if root_left != root_right:
            self.parent[
                root_right
            ] = root_left


def build_coordination_groups(
    graph: pd.DataFrame,
    block_requirements: pd.DataFrame,
    timing: pd.DataFrame,
) -> pd.DataFrame:

    if graph.empty:
        return pd.DataFrame(
            columns=[
                "coordination_group_id",
                "section_id",
                "task_count",
                "task_ids",
                "departments",
                "all_parallel_pairwise",
                "requires_sequential_work",
                "requires_additional_power_isolation",
                "requires_additional_disconnection",
                "estimated_group_block_minutes",
                "group_status",
                "data_origin",
                "integration_mode",
                "is_prototype_derived",
            ]
        )

    same_section = graph[
        (
            graph[
                "locality"
            ]
            .eq(
                "SAME_SECTION"
            )
        )
        &
        (
            ~graph[
                "compatibility_status"
            ]
            .eq(
                "INCOMPATIBLE"
            )
        )
        &
        (
            graph[
                "integrated_block_candidate"
            ]
            .astype(
                bool
            )
        )
    ].copy()

    union_find = UnionFind()

    for row in same_section.itertuples(
        index=False
    ):
        union_find.union(
            row.task_a_id,
            row.task_b_id,
        )

    groups: dict[
        str,
        set[str]
    ] = defaultdict(
        set
    )

    for task_id in union_find.parent:
        groups[
            union_find.find(
                task_id
            )
        ].add(
            task_id
        )

    if not groups:
        return pd.DataFrame(
            columns=[
                "coordination_group_id",
                "section_id",
                "task_count",
                "task_ids",
                "departments",
                "all_parallel_pairwise",
                "requires_sequential_work",
                "requires_additional_power_isolation",
                "requires_additional_disconnection",
                "estimated_group_block_minutes",
                "group_status",
                "data_origin",
                "integration_mode",
                "is_prototype_derived",
            ]
        )

    task_info = (
        block_requirements[
            [
                "task_id",
                "section_id",
                "departments_required",
            ]
        ]
        .merge(
            timing[
                [
                    "task_id",
                    "total_block_expected_minutes",
                ]
            ],
            on="task_id",
            how="left",
            validate="one_to_one",
        )
        .set_index(
            "task_id"
        )
    )

    rows = []

    for task_ids in groups.values():
        task_ids = set(
            task_ids
        )

        if len(
            task_ids
        ) < 2:
            continue

        group_edges = same_section[
            same_section[
                "task_a_id"
            ].isin(
                task_ids
            )
            &
            same_section[
                "task_b_id"
            ].isin(
                task_ids
            )
        ]

        sections = {
            clean_text(
                task_info.loc[
                    task_id,
                    "section_id",
                ]
            )
            for task_id in task_ids
            if task_id
            in task_info.index
        }

        if len(
            sections
        ) != 1:
            # Coordination groups are same-section only at V3.7.
            continue

        section_id = next(
            iter(
                sections
            )
        )

        departments = set()

        durations = []

        for task_id in sorted(
            task_ids
        ):
            departments.update(
                department_set(
                    task_info.loc[
                        task_id,
                        "departments_required",
                    ]
                )
            )

            durations.append(
                int(
                    task_info.loc[
                        task_id,
                        "total_block_expected_minutes",
                    ]
                )
            )

        all_parallel = bool(
            not group_edges.empty
            and group_edges[
                "parallel_execution_possible"
            ]
            .astype(
                bool
            )
            .all()
        )

        requires_sequential = bool(
            (
                ~group_edges[
                    "parallel_execution_possible"
                ]
                .astype(
                    bool
                )
            )
            .any()
        )

        additional_power = bool(
            group_edges[
                "requires_additional_power_isolation"
            ]
            .astype(
                bool
            )
            .any()
        )

        additional_disconnect = bool(
            group_edges[
                "requires_additional_disconnection"
            ]
            .astype(
                bool
            )
            .any()
        )

        if all_parallel:
            estimated_minutes = max(
                durations
            )
        else:
            # Conservative sequential estimate. Optimizer V3 can improve it
            # using partial overlaps and exact resource assignments.
            estimated_minutes = sum(
                durations
            )

        group_id = stable_id(
            "COORD",
            section_id,
            *sorted(
                task_ids
            ),
        )

        rows.append(
            {
                "coordination_group_id":
                    group_id,

                "section_id":
                    section_id,

                "task_count":
                    len(
                        task_ids
                    ),

                "task_ids":
                    "|".join(
                        sorted(
                            task_ids
                        )
                    ),

                "departments":
                    "|".join(
                        sorted(
                            departments
                        )
                    ),

                "all_parallel_pairwise":
                    all_parallel,

                "requires_sequential_work":
                    requires_sequential,

                "requires_additional_power_isolation":
                    additional_power,

                "requires_additional_disconnection":
                    additional_disconnect,

                "estimated_group_block_minutes":
                    estimated_minutes,

                "group_status":
                    "CANDIDATE_REQUIRES_EXACT_OPTIMIZER_CHECK",

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,

                "is_prototype_derived":
                    True,
            }
        )

    return (
        pd.DataFrame(
            rows
        )
        .sort_values(
            [
                "section_id",
                "coordination_group_id",
            ]
        )
        .reset_index(
            drop=True
        )
        if rows
        else pd.DataFrame(
            columns=[
                "coordination_group_id",
                "section_id",
                "task_count",
                "task_ids",
                "departments",
                "all_parallel_pairwise",
                "requires_sequential_work",
                "requires_additional_power_isolation",
                "requires_additional_disconnection",
                "estimated_group_block_minutes",
                "group_status",
                "data_origin",
                "integration_mode",
                "is_prototype_derived",
            ]
        )
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_outputs(
    graph: pd.DataFrame,
    groups: pd.DataFrame,
    block_requirements: pd.DataFrame,
) -> dict[str, int]:

    valid_tasks = set(
        block_requirements[
            "task_id"
        ].astype(
            str
        )
    )

    checks = {
        "graph_edges":
            len(
                graph
            ),

        "coordination_groups":
            len(
                groups
            ),

        "duplicate_edge_ids":
            (
                int(
                    graph[
                        "compatibility_edge_id"
                    ]
                    .duplicated()
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "self_edges":
            (
                int(
                    (
                        graph[
                            "task_a_id"
                        ]
                        ==
                        graph[
                            "task_b_id"
                        ]
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "unknown_task_edges":
            (
                int(
                    (
                        ~graph[
                            "task_a_id"
                        ]
                        .astype(
                            str
                        )
                        .isin(
                            valid_tasks
                        )
                        |
                        ~graph[
                            "task_b_id"
                        ]
                        .astype(
                            str
                        )
                        .isin(
                            valid_tasks
                        )
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "duplicate_group_ids":
            (
                int(
                    groups[
                        "coordination_group_id"
                    ]
                    .duplicated()
                    .sum()
                )
                if not groups.empty
                else 0
            ),

        "invalid_group_sizes":
            (
                int(
                    (
                        groups[
                            "task_count"
                        ]
                        < 2
                    )
                    .sum()
                )
                if not groups.empty
                else 0
            ),

        "parallel_edges":
            (
                int(
                    graph[
                        "parallel_execution_possible"
                    ]
                    .astype(
                        bool
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "sequential_only_edges":
            (
                int(
                    (
                        ~graph[
                            "parallel_execution_possible"
                        ]
                        .astype(
                            bool
                        )
                        &
                        graph[
                            "sequential_execution_possible"
                        ]
                        .astype(
                            bool
                        )
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "integrated_candidate_edges":
            (
                int(
                    graph[
                        "integrated_block_candidate"
                    ]
                    .astype(
                        bool
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "shadow_candidate_edges":
            (
                int(
                    graph[
                        "shadow_block_candidate"
                    ]
                    .astype(
                        bool
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),

        "incompatible_edges":
            (
                int(
                    graph[
                        "compatibility_status"
                    ]
                    .eq(
                        "INCOMPATIBLE"
                    )
                    .sum()
                )
                if not graph.empty
                else 0
            ),
    }

    hard_failure_keys = [
        "duplicate_edge_ids",
        "self_edges",
        "unknown_task_edges",
        "duplicate_group_ids",
        "invalid_group_sizes",
    ]

    if sum(
        checks[
            key
        ]
        for key in hard_failure_keys
    ):
        raise RuntimeError(
            "V3.7 compatibility graph integrity validation failed."
        )

    return checks


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    graph: pd.DataFrame,
    groups: pd.DataFrame,
    checks: dict[str, int],
) -> None:

    locality_counts = (
        graph[
            "locality"
        ]
        .value_counts()
        .sort_index()
        if not graph.empty
        else pd.Series(
            dtype="int64"
        )
    )

    status_counts = (
        graph[
            "compatibility_status"
        ]
        .value_counts()
        .sort_index()
        if not graph.empty
        else pd.Series(
            dtype="int64"
        )
    )

    relationship_counts = (
        graph[
            "relationship_type"
        ]
        .value_counts()
        .sort_values(
            ascending=False
        )
        if not graph.empty
        else pd.Series(
            dtype="int64"
        )
    )

    lines = [
        "=" * 72,
        "TrackEase V3.7 Multi-Department Compatibility Report",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Compatibility graph edges      : {checks['graph_edges']:,}",
        f"Coordination groups             : {checks['coordination_groups']:,}",
        f"Parallel-capable edges          : {checks['parallel_edges']:,}",
        f"Sequential-only edges           : {checks['sequential_only_edges']:,}",
        f"Integrated-block candidate edges: {checks['integrated_candidate_edges']:,}",
        f"Shadow/opportunity edges        : {checks['shadow_candidate_edges']:,}",
        f"Incompatible edges              : {checks['incompatible_edges']:,}",
        "",
        "LOCALITY",
        "-" * 72,
    ]

    for name, count in locality_counts.items():
        lines.append(
            f"{name:<46} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "COMPATIBILITY STATUS",
            "-" * 72,
        ]
    )

    for name, count in status_counts.items():
        lines.append(
            f"{name:<46} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "RELATIONSHIP TYPES",
            "-" * 72,
        ]
    )

    for name, count in relationship_counts.items():
        lines.append(
            f"{name:<46} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                "Duplicate compatibility edge IDs : "
                f"{checks['duplicate_edge_ids']:,}"
            ),
            (
                "Self-edges                       : "
                f"{checks['self_edges']:,}"
            ),
            (
                "Unknown-task edges               : "
                f"{checks['unknown_task_edges']:,}"
            ),
            (
                "Duplicate coordination group IDs : "
                f"{checks['duplicate_group_ids']:,}"
            ),
            (
                "Invalid coordination group sizes : "
                f"{checks['invalid_group_sizes']:,}"
            ),
            "",
            "IMPORTANT INTERPRETATION",
            "-" * 72,
            (
                "This graph identifies candidate compatibility relationships. "
                "It does not itself authorize simultaneous work."
            ),
            (
                "Optimizer V3 must still check exact train windows, crew shifts, "
                "machine-day availability, travel/repositioning, isolation, "
                "disconnection, resource assignment and safe block duration."
            ),
            (
                "Integrated blocks are limited here to same-section, "
                "cross-department candidate relationships."
            ),
            (
                "Adjacent-section relationships are treated as conditional "
                "shadow/opportunity candidates rather than automatically "
                "integrated blocks."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build the enhanced asset-risk and asset-availability scoring "
                "layer, followed by explicit passenger/freight train-impact "
                "metrics and the opportunity detector."
            ),
        ]
    )

    REPORT_OUTPUT.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:

    print("=" * 72)
    print(
        "TrackEase V3.7 - Multi-Department Compatibility Graph"
    )
    print("=" * 72)

    require_inputs()

    print(
        "\nLoading V3.6 task/block model and resource data..."
    )

    block_requirements = pd.read_csv(
        BLOCK_REQUIREMENTS_FILE,
        low_memory=False,
    )

    timing = pd.read_csv(
        TIMING_FILE,
        low_memory=False,
    )

    resource_requirements = pd.read_csv(
        RESOURCE_REQUIREMENTS_FILE,
        low_memory=False,
    )

    dependencies = pd.read_csv(
        DEPENDENCIES_FILE,
        low_memory=False,
    )

    sections = pd.read_csv(
        SECTIONS_FILE,
        low_memory=False,
    )

    crews = pd.read_csv(
        CREWS_FILE,
        low_memory=False,
    )

    crew_skills = pd.read_csv(
        CREW_SKILLS_FILE,
        low_memory=False,
    )

    machines = pd.read_csv(
        MACHINES_FILE,
        low_memory=False,
    )

    equipment = pd.read_csv(
        EQUIPMENT_FILE,
        low_memory=False,
    )

    print(
        f"Tasks loaded                  : "
        f"{len(block_requirements):,}"
    )

    print(
        "Building same-section and adjacent-section compatibility graph..."
    )

    graph = build_compatibility_graph(
        block_requirements,
        timing,
        resource_requirements,
        dependencies,
        sections,
        crews,
        crew_skills,
        machines,
        equipment,
    )

    print(
        "Building same-section multi-department coordination groups..."
    )

    groups = build_coordination_groups(
        graph,
        block_requirements,
        timing,
    )

    checks = validate_outputs(
        graph,
        groups,
        block_requirements,
    )

    graph.to_csv(
        GRAPH_OUTPUT,
        index=False,
    )

    groups.to_csv(
        GROUPS_OUTPUT,
        index=False,
    )

    write_report(
        graph,
        groups,
        checks,
    )

    print(
        "\n"
        + "=" * 72
    )

    print(
        "V3.7 COMPATIBILITY GRAPH COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        f"\nCompatibility edges          : "
        f"{checks['graph_edges']:,}"
    )

    print(
        f"Coordination groups          : "
        f"{checks['coordination_groups']:,}"
    )

    print(
        f"Parallel-capable edges       : "
        f"{checks['parallel_edges']:,}"
    )

    print(
        f"Sequential-only edges        : "
        f"{checks['sequential_only_edges']:,}"
    )

    print(
        f"Integrated candidate edges   : "
        f"{checks['integrated_candidate_edges']:,}"
    )

    print(
        f"Shadow/opportunity edges     : "
        f"{checks['shadow_candidate_edges']:,}"
    )

    print(
        f"Incompatible edges           : "
        f"{checks['incompatible_edges']:,}"
    )

    print(
        "\nIntegrity:"
    )

    print(
        f"  Duplicate edge IDs          : "
        f"{checks['duplicate_edge_ids']:,}"
    )

    print(
        f"  Self edges                  : "
        f"{checks['self_edges']:,}"
    )

    print(
        f"  Unknown-task edges          : "
        f"{checks['unknown_task_edges']:,}"
    )

    print(
        f"  Duplicate group IDs         : "
        f"{checks['duplicate_group_ids']:,}"
    )

    print(
        "\nOutputs:"
    )

    print(
        f"  {GRAPH_OUTPUT}"
    )

    print(
        f"  {GROUPS_OUTPUT}"
    )

    print(
        f"  {REPORT_OUTPUT}"
    )

    print(
        "\nTrackEase V3 can now distinguish parallel, sequential, "
        "integrated and shadow/opportunity maintenance relationships "
        "before exact optimization."
    )


if __name__ == "__main__":
    main()
