"""
TrackEase V3 - Physical Resource Feasibility

Purpose:
    Determine whether each canonical maintenance task has realistic,
    reachable resource candidates before exact block-time optimization.

This stage validates:
    - required crew skill and minimum crew size
    - crew weekly availability
    - crew network reachability to the work section
    - machine availability and network reachability
    - equipment availability and network reachability
    - material stock and depot network reachability
    - protection-resource readiness
    - electrical-isolation support
    - task dependency structure

Important:
    Exact shift-vs-block-time conflicts and long-distance repositioning are
    intentionally deferred to the resource-aware optimizer, because a task
    does not yet have its final V3 block time at this stage.

Inputs:
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_task_resource_requirements.csv
    data/processed/v3_task_dependencies.csv
    data/processed/v3_crews.csv
    data/processed/v3_crew_skills.csv
    data/processed/v3_crew_availability.csv
    data/processed/v3_machines.csv
    data/processed/v3_machine_availability.csv
    data/processed/v3_equipment.csv
    data/processed/v3_material_inventory.csv
    data/processed/v3_sections.csv
    data/processed/v3_stations.csv

Outputs:
    data/processed/v3_resource_assignment_candidates.csv
    data/processed/v3_task_resource_feasibility.csv
    data/processed/v3_resource_feasibility_gaps.csv
    data/processed/v3_resource_feasibility_report.txt

All prototype thresholds are explicit TrackEase planning policies, not
official Indian Railways resource norms.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha1
from pathlib import Path
import heapq
import math

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"
REQUIREMENTS_FILE = PROCESSED_DIR / "v3_task_resource_requirements.csv"
DEPENDENCIES_FILE = PROCESSED_DIR / "v3_task_dependencies.csv"

CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
CREW_SKILLS_FILE = PROCESSED_DIR / "v3_crew_skills.csv"
CREW_AVAILABILITY_FILE = PROCESSED_DIR / "v3_crew_availability.csv"

MACHINES_FILE = PROCESSED_DIR / "v3_machines.csv"
MACHINE_AVAILABILITY_FILE = PROCESSED_DIR / "v3_machine_availability.csv"

EQUIPMENT_FILE = PROCESSED_DIR / "v3_equipment.csv"
MATERIALS_FILE = PROCESSED_DIR / "v3_material_inventory.csv"

SECTIONS_FILE = PROCESSED_DIR / "v3_sections.csv"
STATIONS_FILE = PROCESSED_DIR / "v3_stations.csv"

CANDIDATES_OUTPUT = (
    PROCESSED_DIR / "v3_resource_assignment_candidates.csv"
)
FEASIBILITY_OUTPUT = (
    PROCESSED_DIR / "v3_task_resource_feasibility.csv"
)
GAPS_OUTPUT = (
    PROCESSED_DIR / "v3_resource_feasibility_gaps.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_resource_feasibility_report.txt"
)


# ---------------------------------------------------------------------------
# Prototype policy
# ---------------------------------------------------------------------------

DATA_ORIGIN = "TRACKEASE_V3_RESOURCE_FEASIBILITY"
INTEGRATION_MODE = "PROTOTYPE_RESOURCE_FEASIBILITY_ENGINE"

DEFAULT_SECTION_DISTANCE_KM = 15.0

# TRACKEASE_V3_EXPANDED_RESOURCE_POOL_POLICY
#
# V3.5 is a pre-scheduling reachability layer. Keep a broader but still finite
# set of already-existing qualified resources so V3.11/V3.12 can resolve exact
# time and resource competition without being trapped by an artificial
# nearest-N shortlist.
MAX_CANDIDATES_PER_REQUIREMENT = {
    "CREW": 10,
    "MACHINE": 6,
    "EQUIPMENT": 8,
    "MATERIAL": 3,
    "OPERATIONAL_PREREQUISITE": 6,
}

# Protection is a hard safety prerequisite. Preserve shift-diverse candidates
# before exact block time is known. Six per shift adds deterministic location
# and rest-day redundancy while keeping the candidate pool finite.
#
# This is a prototype search-policy parameter, not an Indian Railways staffing
# standard and it does not increase the actual number of Protection crews.
PROTECTION_CANDIDATES_PER_SHIFT = 6
PROTECTION_SHIFT_ORDER = (
    "EARLY",
    "DAY",
    "LATE",
)

MAX_MACHINE_TRAVEL_MINUTES = 240
MAX_EQUIPMENT_TRAVEL_MINUTES = 180
MAX_MATERIAL_TRAVEL_MINUTES = 300

EQUIPMENT_TRAVEL_SPEED_KMPH = 50.0
MATERIAL_TRAVEL_SPEED_KMPH = 45.0


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def require_inputs() -> None:
    required = [
        TASKS_FILE,
        REQUIREMENTS_FILE,
        DEPENDENCIES_FILE,
        CREWS_FILE,
        CREW_SKILLS_FILE,
        CREW_AVAILABILITY_FILE,
        MACHINES_FILE,
        MACHINE_AVAILABILITY_FILE,
        EQUIPMENT_FILE,
        MATERIALS_FILE,
        SECTIONS_FILE,
        STATIONS_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3 feasibility inputs are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "<na>"}:
        return ""

    return text


def first_existing(
    columns: list[str],
    candidates: list[str],
) -> str | None:
    column_set = set(columns)

    for candidate in candidates:
        if candidate in column_set:
            return candidate

    return None


def stable_id(
    prefix: str,
    *parts: object,
    length: int = 12,
) -> str:
    normalized = "|".join(
        clean_text(part).upper()
        for part in parts
    )

    digest = sha1(
        normalized.encode("utf-8")
    ).hexdigest()[:length].upper()

    return f"{prefix}-{digest}"


# ---------------------------------------------------------------------------
# Network travel proxy
# ---------------------------------------------------------------------------

def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance between two coordinate pairs."""

    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    d_phi = math.radians(
        lat2 - lat1
    )
    d_lambda = math.radians(
        lon2 - lon1
    )

    value = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    return (
        2
        * radius_km
        * math.asin(
            math.sqrt(value)
        )
    )


def build_station_coordinate_lookup(
    stations: pd.DataFrame,
) -> dict[str, tuple[float, float]]:
    lookup = {}

    if not {
        "station_code",
        "latitude",
        "longitude",
    }.issubset(
        stations.columns
    ):
        return lookup

    working = stations.copy()

    working["latitude"] = pd.to_numeric(
        working["latitude"],
        errors="coerce",
    )

    working["longitude"] = pd.to_numeric(
        working["longitude"],
        errors="coerce",
    )

    working = working.dropna(
        subset=[
            "station_code",
            "latitude",
            "longitude",
        ]
    )

    for row in working.itertuples(
        index=False
    ):
        lookup[
            clean_text(
                row.station_code
            )
        ] = (
            float(
                row.latitude
            ),
            float(
                row.longitude
            ),
        )

    return lookup


def identify_section_columns(
    sections: pd.DataFrame,
) -> tuple[str, str, str | None]:
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

    distance = first_existing(
        columns,
        [
            "section_distance_km",
            "distance_km",
            "length_km",
            "avg_distance_km",
            "average_distance_km",
            "distance",
        ],
    )

    if station_a is None or station_b is None:
        raise ValueError(
            "Could not identify both section endpoint station columns "
            "in v3_sections.csv."
        )

    return (
        station_a,
        station_b,
        distance,
    )


def build_network_graph(
    sections: pd.DataFrame,
    stations: pd.DataFrame,
) -> tuple[
    dict[str, list[tuple[str, float]]],
    dict[str, tuple[str, str]],
    dict[str, str],
]:
    """
    Build an undirected resource-access graph.

    Edge distance priority:
        1. section source distance if available
        2. station-coordinate geodesic distance
        3. deterministic 15 km hop proxy
    """

    station_a_col, station_b_col, distance_col = (
        identify_section_columns(
            sections
        )
    )

    coordinates = (
        build_station_coordinate_lookup(
            stations
        )
    )

    graph = defaultdict(
        list
    )

    section_endpoints = {}
    section_distance_basis = {}

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

        distance_km = None
        basis = ""

        if distance_col is not None:
            raw_distance = row_dict.get(
                distance_col
            )

            try:
                parsed = float(
                    raw_distance
                )

                if (
                    math.isfinite(
                        parsed
                    )
                    and parsed > 0
                ):
                    distance_km = parsed
                    basis = (
                        "SECTION_SOURCE_DISTANCE"
                    )
            except (
                TypeError,
                ValueError,
            ):
                pass

        if (
            distance_km is None
            and station_a in coordinates
            and station_b in coordinates
        ):
            lat1, lon1 = coordinates[
                station_a
            ]
            lat2, lon2 = coordinates[
                station_b
            ]

            calculated = haversine_km(
                lat1,
                lon1,
                lat2,
                lon2,
            )

            if calculated > 0:
                distance_km = calculated
                basis = (
                    "STATION_GEODESIC_PROXY"
                )

        if distance_km is None:
            distance_km = (
                DEFAULT_SECTION_DISTANCE_KM
            )
            basis = (
                "NETWORK_HOP_DISTANCE_PROXY"
            )

        graph[
            station_a
        ].append(
            (
                station_b,
                distance_km,
            )
        )

        graph[
            station_b
        ].append(
            (
                station_a,
                distance_km,
            )
        )

        section_endpoints[
            section_id
        ] = (
            station_a,
            station_b,
        )

        section_distance_basis[
            section_id
        ] = basis

    return (
        dict(
            graph
        ),
        section_endpoints,
        section_distance_basis,
    )


def shortest_distances(
    graph: dict[str, list[tuple[str, float]]],
    source: str,
) -> dict[str, float]:
    """Dijkstra shortest-path distances from one resource base."""

    if source not in graph:
        return {
            source:
                0.0
        }

    distances = {
        source:
            0.0
    }

    queue = [
        (
            0.0,
            source,
        )
    ]

    while queue:
        current_distance, node = (
            heapq.heappop(
                queue
            )
        )

        if (
            current_distance
            > distances.get(
                node,
                math.inf,
            )
        ):
            continue

        for neighbor, weight in graph.get(
            node,
            [],
        ):
            new_distance = (
                current_distance
                + weight
            )

            if (
                new_distance
                < distances.get(
                    neighbor,
                    math.inf,
                )
            ):
                distances[
                    neighbor
                ] = new_distance

                heapq.heappush(
                    queue,
                    (
                        new_distance,
                        neighbor,
                    ),
                )

    return distances


def build_base_distance_cache(
    graph: dict[str, list[tuple[str, float]]],
    bases: set[str],
) -> dict[str, dict[str, float]]:
    cache = {}

    for base in sorted(
        bases
    ):
        if base:
            cache[
                base
            ] = shortest_distances(
                graph,
                base,
            )

    return cache


def distance_to_section(
    base_station: str,
    section_id: str,
    section_endpoints: dict[
        str,
        tuple[str, str]
    ],
    distance_cache: dict[
        str,
        dict[str, float]
    ],
) -> float:
    """
    Resource travel is measured to the nearer endpoint of the work section.
    """

    endpoints = section_endpoints.get(
        section_id
    )

    if endpoints is None:
        return math.inf

    station_a, station_b = endpoints

    if base_station in {
        station_a,
        station_b,
    }:
        return 0.0

    distances = distance_cache.get(
        base_station,
        {},
    )

    return min(
        distances.get(
            station_a,
            math.inf,
        ),
        distances.get(
            station_b,
            math.inf,
        ),
    )


def travel_minutes(
    distance_km: float,
    speed_kmph: float,
) -> float:
    if (
        not math.isfinite(
            distance_km
        )
        or speed_kmph <= 0
    ):
        return math.inf

    return (
        distance_km
        / speed_kmph
        * 60.0
    )


# ---------------------------------------------------------------------------
# Candidate indexes
# ---------------------------------------------------------------------------

def build_availability_sets(
    crew_availability: pd.DataFrame,
    machine_availability: pd.DataFrame,
) -> tuple[set[str], set[str]]:
    available_crews = set(
        crew_availability.loc[
            crew_availability[
                "available"
            ].astype(str).str.lower().isin(
                [
                    "true",
                    "1",
                ]
            ),
            "crew_id",
        ].astype(str)
    )

    available_machines = set(
        machine_availability.loc[
            machine_availability[
                "available"
            ].astype(str).str.lower().isin(
                [
                    "true",
                    "1",
                ]
            ),
            "machine_id",
        ].astype(str)
    )

    return (
        available_crews,
        available_machines,
    )


def build_skill_index(
    crew_skills: pd.DataFrame,
) -> dict[str, set[str]]:
    index = defaultdict(
        set
    )

    for row in crew_skills.itertuples(
        index=False
    ):
        index[
            clean_text(
                row.skill_code
            )
        ].add(
            clean_text(
                row.crew_id
            )
        )

    return dict(
        index
    )


# ---------------------------------------------------------------------------
# Candidate evaluation
# ---------------------------------------------------------------------------

def append_candidate(
    rows: list[dict],
    requirement,
    resource_id: str,
    resource_type: str,
    base_station: str,
    distance_km: float,
    travel_min: float,
    candidate_rank: int,
    distance_basis: str,
    availability_status: str,
    qualification_status: str,
    readiness_status: str,
    notes: str,
) -> None:

    rows.append(
        {
            "candidate_id":
                stable_id(
                    "CAND",
                    requirement.requirement_id,
                    resource_id,
                ),

            "requirement_id":
                requirement.requirement_id,

            "task_id":
                requirement.task_id,

            "section_id":
                requirement.section_id,

            "requirement_type":
                requirement.requirement_type,

            "resource_category":
                requirement.resource_category,

            "required_resource_code":
                requirement.resource_code,

            "required_skill_code":
                requirement.skill_code,

            "resource_id":
                resource_id,

            "resource_type":
                resource_type,

            "base_station_code":
                base_station,

            "travel_distance_proxy_km":
                (
                    round(
                        distance_km,
                        2,
                    )
                    if math.isfinite(
                        distance_km
                    )
                    else None
                ),

            "travel_minutes_proxy":
                (
                    round(
                        travel_min,
                        2,
                    )
                    if math.isfinite(
                        travel_min
                    )
                    else None
                ),

            "distance_basis":
                distance_basis,

            "availability_status":
                availability_status,

            "qualification_status":
                qualification_status,

            "readiness_status":
                readiness_status,

            "candidate_rank":
                candidate_rank,

            "notes":
                notes,

            "data_origin":
                DATA_ORIGIN,

            "integration_mode":
                INTEGRATION_MODE,

            "is_prototype_derived":
                True,
        }
    )


def evaluate_requirements(
    requirements: pd.DataFrame,
    crews: pd.DataFrame,
    crew_skills: pd.DataFrame,
    crew_availability: pd.DataFrame,
    machines: pd.DataFrame,
    machine_availability: pd.DataFrame,
    equipment: pd.DataFrame,
    materials: pd.DataFrame,
    section_endpoints: dict[
        str,
        tuple[str, str]
    ],
    section_distance_basis: dict[
        str,
        str
    ],
    distance_cache: dict[
        str,
        dict[str, float]
    ],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    candidate_rows = []
    requirement_status_rows = []

    available_crews, available_machines = (
        build_availability_sets(
            crew_availability,
            machine_availability,
        )
    )

    skill_index = build_skill_index(
        crew_skills
    )

    crew_lookup = crews.set_index(
        "crew_id",
        drop=False,
    )

    machine_lookup = machines.copy()

    for requirement in requirements.itertuples(
        index=False
    ):
        category = clean_text(
            requirement.resource_category
        ).upper()

        section_id = clean_text(
            requirement.section_id
        )

        distance_basis = (
            section_distance_basis.get(
                section_id,
                "UNKNOWN_SECTION_DISTANCE_BASIS",
            )
        )

        candidate_records = []

        # ---------------------------------------------------------------
        # Crew
        # ---------------------------------------------------------------

        if category == "CREW":
            skill = clean_text(
                requirement.skill_code
            )

            eligible_ids = skill_index.get(
                skill,
                set(),
            )

            for crew_id in sorted(
                eligible_ids
            ):
                if crew_id not in crew_lookup.index:
                    continue

                crew = crew_lookup.loc[
                    crew_id
                ]

                required_department = clean_text(
                    requirement.department
                )

                crew_department = clean_text(
                    crew[
                        "department"
                    ]
                )

                if (
                    required_department
                    and crew_department
                    != required_department
                ):
                    continue

                if crew_id not in available_crews:
                    continue

                base = clean_text(
                    crew[
                        "base_station_code"
                    ]
                )

                distance = distance_to_section(
                    base,
                    section_id,
                    section_endpoints,
                    distance_cache,
                )

                radius = float(
                    crew[
                        "home_operating_radius_km"
                    ]
                )

                speed = float(
                    crew[
                        "travel_speed_proxy_kmph"
                    ]
                )

                travel = travel_minutes(
                    distance,
                    speed,
                )

                if math.isfinite(distance):
                    within_local_policy = distance <= radius

                    candidate_records.append(
                        (
                            travel,
                            crew_id,
                            "CREW",
                            base,
                            distance,
                            "AVAILABLE_SOME_WEEKDAYS",
                            "SKILL_MATCH",
                            (
                                "READY_FOR_TIME_SPECIFIC_CHECK"
                                if within_local_policy
                                else "REPOSITIONING_REQUIRED"
                            ),
                            (
                                f"Within crew operating radius "
                                f"({radius:.0f} km)."
                                if within_local_policy
                                else
                                f"Reachable through railway network but outside "
                                f"the crew home-radius proxy ({radius:.0f} km); "
                                f"Optimizer V3 must schedule repositioning/travel."
                            ),
                        )
                    )

        # ---------------------------------------------------------------
        # Machine
        # ---------------------------------------------------------------

        elif category == "MACHINE":
            required_type = clean_text(
                requirement.resource_code
            )

            eligible = machine_lookup[
                machine_lookup[
                    "machine_type"
                ].astype(str).eq(
                    required_type
                )
            ]

            for machine in eligible.itertuples(
                index=False
            ):
                machine_id = clean_text(
                    machine.machine_id
                )

                if machine_id not in available_machines:
                    continue

                base = clean_text(
                    machine.base_station_code
                )

                distance = distance_to_section(
                    base,
                    section_id,
                    section_endpoints,
                    distance_cache,
                )

                travel = travel_minutes(
                    distance,
                    float(
                        machine.travel_speed_proxy_kmph
                    ),
                )

                if math.isfinite(travel):
                    within_local_policy = (
                        travel <= MAX_MACHINE_TRAVEL_MINUTES
                    )

                    candidate_records.append(
                        (
                            travel,
                            machine_id,
                            "MACHINE",
                            base,
                            distance,
                            "AVAILABLE_SOME_WEEKDAYS",
                            "TYPE_MATCH",
                            (
                                "READY_FOR_TIME_SPECIFIC_CHECK"
                                if within_local_policy
                                else "REPOSITIONING_REQUIRED"
                            ),
                            (
                                f"Travel proxy within "
                                f"{MAX_MACHINE_TRAVEL_MINUTES} min local policy."
                                if within_local_policy
                                else
                                f"Machine is network-reachable but exceeds the "
                                f"{MAX_MACHINE_TRAVEL_MINUTES} min local-travel "
                                f"proxy; Optimizer V3 must schedule repositioning."
                            ),
                        )
                    )

        # ---------------------------------------------------------------
        # Equipment
        # ---------------------------------------------------------------

        elif category == "EQUIPMENT":
            required_type = clean_text(
                requirement.resource_code
            )

            eligible = equipment[
                equipment[
                    "equipment_type"
                ].astype(str).eq(
                    required_type
                )
                &
                equipment[
                    "status"
                ].astype(str).eq(
                    "AVAILABLE"
                )
            ]

            for item in eligible.itertuples(
                index=False
            ):
                base = clean_text(
                    item.base_station_code
                )

                distance = distance_to_section(
                    base,
                    section_id,
                    section_endpoints,
                    distance_cache,
                )

                travel = travel_minutes(
                    distance,
                    EQUIPMENT_TRAVEL_SPEED_KMPH,
                )

                if math.isfinite(travel):
                    within_local_policy = (
                        travel <= MAX_EQUIPMENT_TRAVEL_MINUTES
                    )

                    candidate_records.append(
                        (
                            travel,
                            clean_text(
                                item.equipment_id
                            ),
                            "EQUIPMENT",
                            base,
                            distance,
                            "AVAILABLE",
                            "TYPE_MATCH",
                            (
                                "READY"
                                if within_local_policy
                                else "REPOSITIONING_REQUIRED"
                            ),
                            (
                                f"Portable equipment within "
                                f"{MAX_EQUIPMENT_TRAVEL_MINUTES} min local policy."
                                if within_local_policy
                                else
                                f"Equipment is network-reachable but exceeds the "
                                f"{MAX_EQUIPMENT_TRAVEL_MINUTES} min local-travel "
                                f"proxy; Optimizer V3 must schedule repositioning."
                            ),
                        )
                    )

        # ---------------------------------------------------------------
        # Material
        # ---------------------------------------------------------------

        elif category == "MATERIAL":
            material_code = clean_text(
                requirement.resource_code
            )

            quantity_required = int(
                requirement.quantity_required
            )

            eligible = materials[
                materials[
                    "material_code"
                ].astype(str).eq(
                    material_code
                )
                &
                (
                    pd.to_numeric(
                        materials[
                            "quantity_available"
                        ],
                        errors="coerce",
                    ).fillna(0)
                    >= quantity_required
                )
            ]

            for item in eligible.itertuples(
                index=False
            ):
                base = clean_text(
                    item.depot_station_code
                )

                distance = distance_to_section(
                    base,
                    section_id,
                    section_endpoints,
                    distance_cache,
                )

                travel = travel_minutes(
                    distance,
                    MATERIAL_TRAVEL_SPEED_KMPH,
                )

                if math.isfinite(travel):
                    within_local_policy = (
                        travel <= MAX_MATERIAL_TRAVEL_MINUTES
                    )

                    candidate_records.append(
                        (
                            travel,
                            clean_text(
                                item.inventory_id
                            ),
                            "MATERIAL_INVENTORY",
                            base,
                            distance,
                            "IN_STOCK",
                            "MATERIAL_CODE_MATCH",
                            (
                                "READY"
                                if within_local_policy
                                else "REPOSITIONING_REQUIRED"
                            ),
                            (
                                f"Stock >= {quantity_required}; within "
                                f"{MAX_MATERIAL_TRAVEL_MINUTES} min local delivery proxy."
                                if within_local_policy
                                else
                                f"Stock >= {quantity_required}; depot is network-reachable "
                                f"but exceeds the {MAX_MATERIAL_TRAVEL_MINUTES} min local "
                                f"delivery proxy. Optimizer V3 must schedule logistics."
                            ),
                        )
                    )

        # ---------------------------------------------------------------
        # Operational prerequisite: electrical isolation
        # ---------------------------------------------------------------

        elif category == "OPERATIONAL_PREREQUISITE":
            if clean_text(
                requirement.resource_code
            ) == "TRACTION_POWER_ISOLATION":
                isolation_skill = (
                    "ELECTRICAL_ISOLATION"
                )

                eligible_ids = skill_index.get(
                    isolation_skill,
                    set(),
                )

                for crew_id in sorted(
                    eligible_ids
                ):
                    if crew_id not in crew_lookup.index:
                        continue

                    crew = crew_lookup.loc[
                        crew_id
                    ]

                    if (
                        clean_text(
                            crew[
                                "department"
                            ]
                        )
                        != "Electrical"
                    ):
                        continue

                    if crew_id not in available_crews:
                        continue

                    base = clean_text(
                        crew[
                            "base_station_code"
                        ]
                    )

                    distance = distance_to_section(
                        base,
                        section_id,
                        section_endpoints,
                        distance_cache,
                    )

                    radius = float(
                        crew[
                            "home_operating_radius_km"
                        ]
                    )

                    travel = travel_minutes(
                        distance,
                        float(
                            crew[
                                "travel_speed_proxy_kmph"
                            ]
                        ),
                    )

                    if math.isfinite(distance):
                        within_local_policy = distance <= radius

                        candidate_records.append(
                            (
                                travel,
                                crew_id,
                                "ISOLATION_SUPPORT_CREW",
                                base,
                                distance,
                                "AVAILABLE_SOME_WEEKDAYS",
                                "ELECTRICAL_ISOLATION_SKILL_MATCH",
                                (
                                    "READY_FOR_TIME_SPECIFIC_CHECK"
                                    if within_local_policy
                                    else "REPOSITIONING_REQUIRED"
                                ),
                                (
                                    "Qualified electrical isolation support "
                                    "candidate within local operating radius."
                                    if within_local_policy
                                    else
                                    "Qualified electrical isolation support is "
                                    "network-reachable but requires planned "
                                    "repositioning before the block."
                                ),
                            )
                        )

        candidate_records.sort(
            key=lambda item: (
                item[0],
                item[1],
            )
        )

        limit = MAX_CANDIDATES_PER_REQUIREMENT.get(
            category,
            3,
        )

        requirement_type = clean_text(
            requirement.requirement_type
        ).upper()

        if (
            category == "CREW"
            and requirement_type == "PROTECTION_CREW"
        ):
            # V3.5 is a pre-scheduling layer: exact block time is not known
            # yet. Preserve nearest candidates from every Protection shift
            # instead of allowing the global nearest-N shortlist to remove
            # an entire shift before V3.11 can evaluate it.
            selected = []

            for shift_pattern in PROTECTION_SHIFT_ORDER:
                shift_candidates = [
                    candidate
                    for candidate in candidate_records
                    if (
                        candidate[1] in crew_lookup.index
                        and clean_text(
                            crew_lookup.loc[
                                candidate[1],
                                "shift_pattern",
                            ]
                        ).upper()
                        == shift_pattern
                    )
                ]

                selected.extend(
                    shift_candidates[
                        :PROTECTION_CANDIDATES_PER_SHIFT
                    ]
                )

            # Defensive fallback for a future/legacy Protection shift label.
            if not selected:
                selected = candidate_records[
                    :limit
                ]
        else:
            selected = candidate_records[
                :limit
            ]

        for rank, candidate in enumerate(
            selected,
            start=1,
        ):
            (
                travel,
                resource_id,
                resource_type,
                base,
                distance,
                availability_status,
                qualification_status,
                readiness_status,
                notes,
            ) = candidate

            append_candidate(
                candidate_rows,
                requirement,
                resource_id,
                resource_type,
                base,
                distance,
                travel,
                rank,
                distance_basis,
                availability_status,
                qualification_status,
                readiness_status,
                notes,
            )

        local_candidate_available = any(
            candidate[7] != "REPOSITIONING_REQUIRED"
            for candidate in selected
        )

        repositioning_required = bool(
            selected
            and not local_candidate_available
        )

        requirement_status_rows.append(
            {
                "requirement_id":
                    requirement.requirement_id,

                "task_id":
                    requirement.task_id,

                "section_id":
                    requirement.section_id,

                "resource_category":
                    requirement.resource_category,

                "requirement_type":
                    requirement.requirement_type,

                "mandatory":
                    bool(
                        requirement.mandatory
                    ),

                "candidate_count":
                    len(
                        selected
                    ),

                "requirement_feasible":
                    (
                        len(
                            selected
                        )
                        > 0
                    ),

                "repositioning_required":
                    repositioning_required,

                "status":
                    (
                        "RESOURCE_CANDIDATES_AVAILABLE_REPOSITIONING_REQUIRED"
                        if repositioning_required
                        else (
                            "RESOURCE_CANDIDATES_AVAILABLE"
                            if selected
                            else "NO_RESOURCE_CANDIDATE"
                        )
                    ),
            }
        )

    candidates = pd.DataFrame(
        candidate_rows
    )

    requirement_status = pd.DataFrame(
        requirement_status_rows
    )

    return (
        candidates,
        requirement_status,
    )


# ---------------------------------------------------------------------------
# Task-level feasibility
# ---------------------------------------------------------------------------

def build_task_feasibility(
    tasks: pd.DataFrame,
    requirements: pd.DataFrame,
    requirement_status: pd.DataFrame,
    dependencies: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    merged = requirements[
        [
            "requirement_id",
            "task_id",
            "mandatory",
            "resource_category",
            "requirement_type",
        ]
    ].merge(
        requirement_status[
            [
                "requirement_id",
                "candidate_count",
                "requirement_feasible",
                "repositioning_required",
                "status",
            ]
        ],
        on="requirement_id",
        how="left",
        validate="one_to_one",
    )

    merged[
        "candidate_count"
    ] = (
        pd.to_numeric(
            merged[
                "candidate_count"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )

    merged[
        "requirement_feasible"
    ] = (
        merged[
            "requirement_feasible"
        ]
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )

    merged[
        "repositioning_required"
    ] = (
        merged[
            "repositioning_required"
        ]
        .astype("boolean")
        .fillna(False)
        .astype(bool)
    )

    mandatory = merged[
        merged[
            "mandatory"
        ].astype(bool)
    ]

    grouped = (
        mandatory.groupby(
            "task_id"
        )
        .agg(
            mandatory_requirement_count=(
                "requirement_id",
                "size",
            ),
            feasible_requirement_count=(
                "requirement_feasible",
                "sum",
            ),
            total_candidate_count=(
                "candidate_count",
                "sum",
            ),
            repositioning_requirement_count=(
                "repositioning_required",
                "sum",
            ),
        )
        .reset_index()
    )

    grouped[
        "resource_gap_count"
    ] = (
        grouped[
            "mandatory_requirement_count"
        ]
        - grouped[
            "feasible_requirement_count"
        ]
    )

    dependency_counts = (
        dependencies.groupby(
            "successor_task_id"
        )
        .size()
        .rename(
            "predecessor_dependency_count"
        )
        .reset_index()
        if not dependencies.empty
        else pd.DataFrame(
            columns=[
                "successor_task_id",
                "predecessor_dependency_count",
            ]
        )
    )

    feasibility = tasks[
        [
            "task_id",
            "request_id",
            "asset_id",
            "section_id",
            "task_name",
            "task_type",
            "department",
            "priority_level",
            "trackease_priority_score",
            "expected_duration_min",
        ]
    ].merge(
        grouped,
        on="task_id",
        how="left",
        validate="one_to_one",
    )

    feasibility = feasibility.merge(
        dependency_counts,
        left_on="task_id",
        right_on="successor_task_id",
        how="left",
        validate="one_to_one",
    )

    if "successor_task_id" in feasibility.columns:
        feasibility = feasibility.drop(
            columns=[
                "successor_task_id"
            ]
        )

    numeric_fill_zero = [
        "mandatory_requirement_count",
        "feasible_requirement_count",
        "total_candidate_count",
        "resource_gap_count",
        "repositioning_requirement_count",
        "predecessor_dependency_count",
    ]

    for column in numeric_fill_zero:
        feasibility[
            column
        ] = (
            pd.to_numeric(
                feasibility[
                    column
                ],
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

    feasibility[
        "resource_precheck_passed"
    ] = (
        feasibility[
            "resource_gap_count"
        ]
        .eq(0)
    )

    feasibility[
        "requires_resource_repositioning"
    ] = (
        feasibility[
            "repositioning_requirement_count"
        ]
        .gt(0)
    )

    feasibility[
        "requires_dependency_sequence"
    ] = (
        feasibility[
            "predecessor_dependency_count"
        ]
        .gt(0)
    )

    feasibility[
        "time_specific_validation_required"
    ] = True

    def status(row):
        if row.resource_gap_count > 0:
            return "RESOURCE_GAP"

        if (
            row.requires_dependency_sequence
            and row.requires_resource_repositioning
        ):
            return (
                "RESOURCE_READY_REPOSITIONING_AND_SEQUENCE"
            )

        if row.requires_dependency_sequence:
            return (
                "RESOURCE_READY_REQUIRES_SEQUENCE"
            )

        if row.requires_resource_repositioning:
            return (
                "RESOURCE_READY_REPOSITIONING_REQUIRED"
            )

        return "RESOURCE_READY_FOR_OPTIMIZER"

    feasibility[
        "resource_feasibility_status"
    ] = feasibility.apply(
        status,
        axis=1,
    )

    feasibility[
        "data_origin"
    ] = DATA_ORIGIN

    feasibility[
        "integration_mode"
    ] = INTEGRATION_MODE

    feasibility[
        "is_prototype_derived"
    ] = True

    gaps = merged[
        (
            merged[
                "mandatory"
            ].astype(bool)
        )
        &
        (
            ~merged[
                "requirement_feasible"
            ]
        )
    ].copy()

    if gaps.empty:
        gaps = pd.DataFrame(
            columns=[
                "requirement_id",
                "task_id",
                "resource_category",
                "requirement_type",
                "candidate_count",
                "gap_reason",
            ]
        )
    else:
        gaps[
            "gap_reason"
        ] = (
            "NO_REACHABLE_AVAILABLE_RESOURCE_CANDIDATE"
        )

        gaps = gaps[
            [
                "requirement_id",
                "task_id",
                "resource_category",
                "requirement_type",
                "candidate_count",
                "gap_reason",
            ]
        ]

    return (
        feasibility,
        gaps,
    )


# ---------------------------------------------------------------------------
# Integrity validation
# ---------------------------------------------------------------------------

def validate_outputs(
    tasks: pd.DataFrame,
    requirements: pd.DataFrame,
    candidates: pd.DataFrame,
    feasibility: pd.DataFrame,
    gaps: pd.DataFrame,
) -> dict[str, int]:
    checks = {
        "tasks":
            len(tasks),

        "requirements":
            len(requirements),

        "candidate_rows":
            len(candidates),

        "feasibility_rows":
            len(feasibility),

        "gap_rows":
            len(gaps),

        "duplicate_candidate_ids":
            (
                int(
                    candidates[
                        "candidate_id"
                    ].duplicated().sum()
                )
                if not candidates.empty
                else 0
            ),

        "duplicate_feasibility_tasks":
            int(
                feasibility[
                    "task_id"
                ].duplicated().sum()
            ),

        "tasks_missing_feasibility":
            int(
                (
                    ~tasks[
                        "task_id"
                    ].astype(str).isin(
                        feasibility[
                            "task_id"
                        ].astype(str)
                    )
                ).sum()
            ),

        "ready_tasks":
            int(
                feasibility[
                    "resource_precheck_passed"
                ].astype(bool).sum()
            ),

        "tasks_with_resource_gaps":
            int(
                (
                    ~feasibility[
                        "resource_precheck_passed"
                    ].astype(bool)
                ).sum()
            ),

        "tasks_with_dependencies":
            int(
                feasibility[
                    "requires_dependency_sequence"
                ].astype(bool).sum()
            ),

        "tasks_requiring_repositioning":
            int(
                feasibility[
                    "requires_resource_repositioning"
                ].astype(bool).sum()
            ),
    }

    if len(feasibility) != len(tasks):
        raise RuntimeError(
            "Resource feasibility must contain exactly one row per V3 task."
        )

    if (
        checks[
            "duplicate_candidate_ids"
        ]
        or checks[
            "duplicate_feasibility_tasks"
        ]
        or checks[
            "tasks_missing_feasibility"
        ]
    ):
        raise RuntimeError(
            "V3 resource-feasibility integrity validation failed."
        )

    return checks


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    checks: dict[str, int],
    feasibility: pd.DataFrame,
    gaps: pd.DataFrame,
    candidates: pd.DataFrame,
) -> None:
    status_counts = (
        feasibility[
            "resource_feasibility_status"
        ]
        .value_counts()
        .sort_index()
    )

    gap_counts = (
        gaps[
            "resource_category"
        ]
        .value_counts()
        .sort_index()
        if not gaps.empty
        else pd.Series(
            dtype="int64"
        )
    )

    candidate_category_counts = (
        candidates[
            "resource_category"
        ]
        .value_counts()
        .sort_index()
        if not candidates.empty
        else pd.Series(
            dtype="int64"
        )
    )

    lines = [
        "=" * 72,
        "TrackEase V3 Resource Feasibility Report",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Maintenance tasks            : {checks['tasks']:,}",
        f"Resource requirements        : {checks['requirements']:,}",
        f"Assignment candidates        : {checks['candidate_rows']:,}",
        f"Resource-ready tasks         : {checks['ready_tasks']:,}",
        f"Tasks with resource gaps     : {checks['tasks_with_resource_gaps']:,}",
        f"Tasks requiring repositioning: {checks['tasks_requiring_repositioning']:,}",
        f"Tasks with dependencies      : {checks['tasks_with_dependencies']:,}",
        "",
        "TASK STATUS",
        "-" * 72,
    ]

    for name, count in status_counts.items():
        lines.append(
            f"{name:<40} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "CANDIDATES BY RESOURCE CATEGORY",
            "-" * 72,
        ]
    )

    for name, count in candidate_category_counts.items():
        lines.append(
            f"{name:<40} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "RESOURCE GAPS",
            "-" * 72,
        ]
    )

    if gap_counts.empty:
        lines.append(
            "No mandatory task-resource gaps detected."
        )
    else:
        for name, count in gap_counts.items():
            lines.append(
                f"{name:<40} {count:>10,}"
            )

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                f"Duplicate candidate IDs      : "
                f"{checks['duplicate_candidate_ids']:,}"
            ),
            (
                f"Duplicate feasibility tasks  : "
                f"{checks['duplicate_feasibility_tasks']:,}"
            ),
            (
                f"Tasks missing feasibility    : "
                f"{checks['tasks_missing_feasibility']:,}"
            ),
            "",
            "IMPORTANT SCOPE",
            "-" * 72,
            (
                "This stage verifies physical resource readiness and network "
                "reachability before final block-time selection."
            ),
            (
                "Exact crew shift, machine-day, simultaneous resource conflict, "
                "resource repositioning/travel, and block-time coverage checks remain "
                "mandatory in Optimizer V3."
            ),
            (
                "Travel distances are a network-access proxy derived from "
                "available section distances, station coordinates, or an "
                "explicit fallback hop-distance proxy."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build enhanced asset-risk / availability scoring and explicit "
                "train-impact metrics, then run exact resource-aware Optimizer V3."
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
    print("TrackEase V3 - Physical Resource Feasibility")
    print("=" * 72)

    require_inputs()

    print("\nLoading V3 datasets...")

    tasks = pd.read_csv(
        TASKS_FILE,
        low_memory=False,
    )

    requirements = pd.read_csv(
        REQUIREMENTS_FILE,
        low_memory=False,
    )

    dependencies = pd.read_csv(
        DEPENDENCIES_FILE,
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

    crew_availability = pd.read_csv(
        CREW_AVAILABILITY_FILE,
        low_memory=False,
    )

    machines = pd.read_csv(
        MACHINES_FILE,
        low_memory=False,
    )

    machine_availability = pd.read_csv(
        MACHINE_AVAILABILITY_FILE,
        low_memory=False,
    )

    equipment = pd.read_csv(
        EQUIPMENT_FILE,
        low_memory=False,
    )

    materials = pd.read_csv(
        MATERIALS_FILE,
        low_memory=False,
    )

    sections = pd.read_csv(
        SECTIONS_FILE,
        low_memory=False,
    )

    stations = pd.read_csv(
        STATIONS_FILE,
        low_memory=False,
    )

    print(
        f"Tasks                 : {len(tasks):,}"
    )
    print(
        f"Requirements          : {len(requirements):,}"
    )
    print(
        f"Crews                 : {len(crews):,}"
    )
    print(
        f"Machines              : {len(machines):,}"
    )
    print(
        f"Equipment             : {len(equipment):,}"
    )
    print(
        f"Material inventory    : {len(materials):,}"
    )

    print("\nBuilding resource travel network...")

    (
        graph,
        section_endpoints,
        section_distance_basis,
    ) = build_network_graph(
        sections,
        stations,
    )

    all_bases = set(
        crews[
            "base_station_code"
        ].dropna().astype(str)
    )

    all_bases.update(
        machines[
            "base_station_code"
        ].dropna().astype(str)
    )

    all_bases.update(
        equipment[
            "base_station_code"
        ].dropna().astype(str)
    )

    all_bases.update(
        materials[
            "depot_station_code"
        ].dropna().astype(str)
    )

    print(
        f"Resource base stations : {len(all_bases):,}"
    )

    distance_cache = (
        build_base_distance_cache(
            graph,
            all_bases,
        )
    )

    print("Evaluating resource candidates...")

    (
        candidates,
        requirement_status,
    ) = evaluate_requirements(
        requirements,
        crews,
        crew_skills,
        crew_availability,
        machines,
        machine_availability,
        equipment,
        materials,
        section_endpoints,
        section_distance_basis,
        distance_cache,
    )

    print("Building task-level feasibility...")

    (
        feasibility,
        gaps,
    ) = build_task_feasibility(
        tasks,
        requirements,
        requirement_status,
        dependencies,
    )

    checks = validate_outputs(
        tasks,
        requirements,
        candidates,
        feasibility,
        gaps,
    )

    candidates.to_csv(
        CANDIDATES_OUTPUT,
        index=False,
    )

    feasibility.to_csv(
        FEASIBILITY_OUTPUT,
        index=False,
    )

    gaps.to_csv(
        GAPS_OUTPUT,
        index=False,
    )

    write_report(
        checks,
        feasibility,
        gaps,
        candidates,
    )

    print("\n" + "=" * 72)
    print("V3 RESOURCE FEASIBILITY COMPLETE")
    print("=" * 72)

    print(
        f"\nAssignment candidates      : "
        f"{len(candidates):,}"
    )

    print(
        f"Resource-ready tasks       : "
        f"{checks['ready_tasks']:,}"
    )

    print(
        f"Tasks with resource gaps   : "
        f"{checks['tasks_with_resource_gaps']:,}"
    )

    print(
        f"Tasks requiring reposition : "
        f"{checks['tasks_requiring_repositioning']:,}"
    )

    print(
        f"Tasks requiring sequencing : "
        f"{checks['tasks_with_dependencies']:,}"
    )

    print("\nIntegrity:")
    print(
        f"  Duplicate candidate IDs   : "
        f"{checks['duplicate_candidate_ids']:,}"
    )
    print(
        f"  Duplicate feasibility rows: "
        f"{checks['duplicate_feasibility_tasks']:,}"
    )
    print(
        f"  Missing feasibility rows  : "
        f"{checks['tasks_missing_feasibility']:,}"
    )

    print("\nOutputs:")
    print(f"  {CANDIDATES_OUTPUT}")
    print(f"  {FEASIBILITY_OUTPUT}")
    print(f"  {GAPS_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")

    print(
        "\nTrackEase V3 can now determine whether each maintenance task "
        "has reachable resource candidates before exact block scheduling."
    )


if __name__ == "__main__":
    main()
