"""
TrackEase V3 - Diagnose Resource Feasibility Gaps

Purpose:
    Explain WHY V3.5 resource requirements have no assignment candidate.

This diagnostic does not modify any planning data. It classifies each gap as:
    - missing resource type / skill
    - unavailable resource
    - insufficient stock
    - section not represented in the network graph
    - no network path from any compatible resource base
    - reachable in the network but outside the current travel/radius policy

Outputs:
    data/processed/v3_resource_gap_diagnostics.csv
    data/processed/v3_resource_gap_diagnostic_report.txt
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import heapq
import math

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

GAPS_FILE = PROCESSED_DIR / "v3_resource_feasibility_gaps.csv"
REQUIREMENTS_FILE = PROCESSED_DIR / "v3_task_resource_requirements.csv"

CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
CREW_SKILLS_FILE = PROCESSED_DIR / "v3_crew_skills.csv"
CREW_AVAILABILITY_FILE = PROCESSED_DIR / "v3_crew_availability.csv"

MACHINES_FILE = PROCESSED_DIR / "v3_machines.csv"
MACHINE_AVAILABILITY_FILE = PROCESSED_DIR / "v3_machine_availability.csv"

EQUIPMENT_FILE = PROCESSED_DIR / "v3_equipment.csv"
MATERIALS_FILE = PROCESSED_DIR / "v3_material_inventory.csv"

SECTIONS_FILE = PROCESSED_DIR / "v3_sections.csv"
STATIONS_FILE = PROCESSED_DIR / "v3_stations.csv"

DIAGNOSTICS_OUTPUT = PROCESSED_DIR / "v3_resource_gap_diagnostics.csv"
REPORT_OUTPUT = PROCESSED_DIR / "v3_resource_gap_diagnostic_report.txt"

DEFAULT_SECTION_DISTANCE_KM = 15.0

CREW_DEFAULT_LIMITS_KM = {
    "Engineering": 120.0,
    "S&T": 100.0,
    "Electrical": 100.0,
    "Protection": 100.0,
}

MAX_MACHINE_TRAVEL_MINUTES = 240.0
MAX_EQUIPMENT_TRAVEL_MINUTES = 180.0
MAX_MATERIAL_TRAVEL_MINUTES = 300.0

EQUIPMENT_TRAVEL_SPEED_KMPH = 50.0
MATERIAL_TRAVEL_SPEED_KMPH = 45.0


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def first_existing(columns, candidates):
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def require_inputs():
    required = [
        GAPS_FILE,
        REQUIREMENTS_FILE,
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

    missing = [path for path in required if not path.exists()]

    if missing:
        raise FileNotFoundError(
            "Missing diagnostic inputs:\n"
            + "\n".join(f"  {path}" for path in missing)
        )


def identify_section_columns(sections):
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
            "Could not identify both section endpoint columns in v3_sections.csv."
        )

    return station_a, station_b, distance


def build_station_coordinates(stations):
    result = {}

    if not {"station_code", "latitude", "longitude"}.issubset(stations.columns):
        return result

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
        subset=["station_code", "latitude", "longitude"]
    )

    for row in working.itertuples(index=False):
        result[clean_text(row.station_code)] = (
            float(row.latitude),
            float(row.longitude),
        )

    return result


def haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    value = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    return 2 * radius_km * math.asin(math.sqrt(value))


def build_network_graph(sections, stations):
    station_a_col, station_b_col, distance_col = identify_section_columns(
        sections
    )

    coordinates = build_station_coordinates(stations)

    graph = defaultdict(list)
    endpoints = {}

    for _, row in sections.iterrows():
        section_id = clean_text(row.get("section_id"))
        station_a = clean_text(row.get(station_a_col))
        station_b = clean_text(row.get(station_b_col))

        if not section_id or not station_a or not station_b:
            continue

        distance_km = None

        if distance_col is not None:
            try:
                parsed = float(row.get(distance_col))
                if math.isfinite(parsed) and parsed > 0:
                    distance_km = parsed
            except (TypeError, ValueError):
                pass

        if (
            distance_km is None
            and station_a in coordinates
            and station_b in coordinates
        ):
            lat1, lon1 = coordinates[station_a]
            lat2, lon2 = coordinates[station_b]

            calculated = haversine_km(
                lat1,
                lon1,
                lat2,
                lon2,
            )

            if calculated > 0:
                distance_km = calculated

        if distance_km is None:
            distance_km = DEFAULT_SECTION_DISTANCE_KM

        graph[station_a].append((station_b, distance_km))
        graph[station_b].append((station_a, distance_km))
        endpoints[section_id] = (station_a, station_b)

    return dict(graph), endpoints


def shortest_distances(graph, source):
    if source not in graph:
        return {source: 0.0}

    distances = {source: 0.0}
    queue = [(0.0, source)]

    while queue:
        current_distance, node = heapq.heappop(queue)

        if current_distance > distances.get(node, math.inf):
            continue

        for neighbor, weight in graph.get(node, []):
            new_distance = current_distance + weight

            if new_distance < distances.get(neighbor, math.inf):
                distances[neighbor] = new_distance
                heapq.heappush(queue, (new_distance, neighbor))

    return distances


def build_distance_cache(graph, bases):
    return {
        base: shortest_distances(graph, base)
        for base in sorted(bases)
        if base
    }


def distance_to_section(base, section_id, endpoints, cache):
    section_endpoints = endpoints.get(section_id)

    if section_endpoints is None:
        return math.inf

    station_a, station_b = section_endpoints

    if base in {station_a, station_b}:
        return 0.0

    distances = cache.get(base, {})

    return min(
        distances.get(station_a, math.inf),
        distances.get(station_b, math.inf),
    )


def available_id_set(df, id_column):
    if "available" not in df.columns:
        return set(df[id_column].astype(str))

    mask = (
        df["available"]
        .astype(str)
        .str.lower()
        .isin(["true", "1"])
    )

    return set(
        df.loc[mask, id_column].astype(str)
    )


def resource_bases_for_gap(
    requirement,
    crews,
    crew_skills,
    crew_available,
    machines,
    machine_available,
    equipment,
    materials,
):
    category = clean_text(requirement.resource_category).upper()
    resource_code = clean_text(requirement.resource_code)
    skill_code = clean_text(requirement.skill_code)
    department = clean_text(requirement.department)
    quantity = int(requirement.quantity_required)

    matching_total = 0
    matching_available = 0
    bases = []
    speed_kmph = None
    distance_limit_km = None
    time_limit_min = None

    if category == "CREW":
        skill_matches = set(
            crew_skills.loc[
                crew_skills["skill_code"].astype(str).eq(skill_code),
                "crew_id",
            ].astype(str)
        )

        eligible = crews[
            crews["crew_id"].astype(str).isin(skill_matches)
        ].copy()

        if department:
            eligible = eligible[
                eligible["department"].astype(str).eq(department)
            ]

        matching_total = len(eligible)

        eligible_available = eligible[
            eligible["crew_id"].astype(str).isin(crew_available)
        ]

        matching_available = len(eligible_available)

        for row in eligible_available.itertuples(index=False):
            bases.append(
                (
                    clean_text(row.base_station_code),
                    float(row.travel_speed_proxy_kmph),
                    float(row.home_operating_radius_km),
                    None,
                )
            )

    elif category == "MACHINE":
        eligible = machines[
            machines["machine_type"].astype(str).eq(resource_code)
        ].copy()

        matching_total = len(eligible)

        eligible_available = eligible[
            eligible["machine_id"].astype(str).isin(machine_available)
        ]

        matching_available = len(eligible_available)

        for row in eligible_available.itertuples(index=False):
            bases.append(
                (
                    clean_text(row.base_station_code),
                    float(row.travel_speed_proxy_kmph),
                    None,
                    MAX_MACHINE_TRAVEL_MINUTES,
                )
            )

    elif category == "EQUIPMENT":
        eligible = equipment[
            equipment["equipment_type"].astype(str).eq(resource_code)
        ].copy()

        matching_total = len(eligible)

        if "status" in eligible.columns:
            eligible_available = eligible[
                eligible["status"].astype(str).eq("AVAILABLE")
            ]
        else:
            eligible_available = eligible

        matching_available = len(eligible_available)

        for row in eligible_available.itertuples(index=False):
            bases.append(
                (
                    clean_text(row.base_station_code),
                    EQUIPMENT_TRAVEL_SPEED_KMPH,
                    None,
                    MAX_EQUIPMENT_TRAVEL_MINUTES,
                )
            )

    elif category == "MATERIAL":
        eligible = materials[
            materials["material_code"].astype(str).eq(resource_code)
        ].copy()

        matching_total = len(eligible)

        stock = pd.to_numeric(
            eligible["quantity_available"],
            errors="coerce",
        ).fillna(0)

        eligible_available = eligible[
            stock >= quantity
        ]

        matching_available = len(eligible_available)

        for row in eligible_available.itertuples(index=False):
            bases.append(
                (
                    clean_text(row.depot_station_code),
                    MATERIAL_TRAVEL_SPEED_KMPH,
                    None,
                    MAX_MATERIAL_TRAVEL_MINUTES,
                )
            )

    elif category == "OPERATIONAL_PREREQUISITE":
        if resource_code == "TRACTION_POWER_ISOLATION":
            skill_code = "ELECTRICAL_ISOLATION"

            skill_matches = set(
                crew_skills.loc[
                    crew_skills["skill_code"].astype(str).eq(skill_code),
                    "crew_id",
                ].astype(str)
            )

            eligible = crews[
                crews["crew_id"].astype(str).isin(skill_matches)
                &
                crews["department"].astype(str).eq("Electrical")
            ].copy()

            matching_total = len(eligible)

            eligible_available = eligible[
                eligible["crew_id"].astype(str).isin(crew_available)
            ]

            matching_available = len(eligible_available)

            for row in eligible_available.itertuples(index=False):
                bases.append(
                    (
                        clean_text(row.base_station_code),
                        float(row.travel_speed_proxy_kmph),
                        float(row.home_operating_radius_km),
                        None,
                    )
                )

    return (
        matching_total,
        matching_available,
        bases,
    )


def classify_gap(
    requirement,
    matching_total,
    matching_available,
    bases,
    section_id,
    endpoints,
    distance_cache,
):
    if matching_total == 0:
        return (
            "NO_MATCHING_RESOURCE_EXISTS",
            None,
            None,
            None,
        )

    if matching_available == 0:
        return (
            "MATCHING_RESOURCE_EXISTS_BUT_NOT_AVAILABLE",
            None,
            None,
            None,
        )

    if section_id not in endpoints:
        return (
            "SECTION_NOT_IN_RESOURCE_NETWORK",
            None,
            None,
            None,
        )

    best_distance = math.inf
    best_travel = math.inf
    any_network_path = False
    any_within_policy = False

    for base, speed, radius_km, max_minutes in bases:
        distance = distance_to_section(
            base,
            section_id,
            endpoints,
            distance_cache,
        )

        if not math.isfinite(distance):
            continue

        any_network_path = True

        travel = (
            distance / speed * 60.0
            if speed > 0
            else math.inf
        )

        best_distance = min(best_distance, distance)
        best_travel = min(best_travel, travel)

        radius_ok = (
            radius_km is None
            or distance <= radius_km
        )

        time_ok = (
            max_minutes is None
            or travel <= max_minutes
        )

        if radius_ok and time_ok:
            any_within_policy = True

    if not any_network_path:
        return (
            "NO_NETWORK_PATH_FROM_COMPATIBLE_RESOURCE_BASE",
            None,
            None,
            None,
        )

    if not any_within_policy:
        return (
            "REACHABLE_BUT_OUTSIDE_CURRENT_TRAVEL_POLICY",
            round(best_distance, 2),
            round(best_travel, 2),
            None,
        )

    return (
        "UNEXPECTED_FEASIBILITY_MISMATCH",
        round(best_distance, 2),
        round(best_travel, 2),
        "A compatible resource appears to satisfy the broad precheck; inspect V3.5 logic.",
    )


def main():
    print("=" * 72)
    print("TrackEase V3 - Resource Gap Diagnostics")
    print("=" * 72)

    require_inputs()

    gaps = pd.read_csv(GAPS_FILE, low_memory=False)
    requirements = pd.read_csv(REQUIREMENTS_FILE, low_memory=False)

    crews = pd.read_csv(CREWS_FILE, low_memory=False)
    crew_skills = pd.read_csv(CREW_SKILLS_FILE, low_memory=False)
    crew_availability = pd.read_csv(
        CREW_AVAILABILITY_FILE,
        low_memory=False,
    )

    machines = pd.read_csv(MACHINES_FILE, low_memory=False)
    machine_availability = pd.read_csv(
        MACHINE_AVAILABILITY_FILE,
        low_memory=False,
    )

    equipment = pd.read_csv(EQUIPMENT_FILE, low_memory=False)
    materials = pd.read_csv(MATERIALS_FILE, low_memory=False)

    sections = pd.read_csv(SECTIONS_FILE, low_memory=False)
    stations = pd.read_csv(STATIONS_FILE, low_memory=False)

    gap_requirements = gaps[
        ["requirement_id"]
    ].merge(
        requirements,
        on="requirement_id",
        how="left",
        validate="one_to_one",
    )

    print(f"\nGap requirements loaded : {len(gap_requirements):,}")

    print("Building network diagnostic graph...")
    graph, endpoints = build_network_graph(
        sections,
        stations,
    )

    crew_available = available_id_set(
        crew_availability,
        "crew_id",
    )

    machine_available = available_id_set(
        machine_availability,
        "machine_id",
    )

    all_bases = set(
        crews["base_station_code"].dropna().astype(str)
    )
    all_bases.update(
        machines["base_station_code"].dropna().astype(str)
    )
    all_bases.update(
        equipment["base_station_code"].dropna().astype(str)
    )
    all_bases.update(
        materials["depot_station_code"].dropna().astype(str)
    )

    distance_cache = build_distance_cache(
        graph,
        all_bases,
    )

    diagnostics = []

    for requirement in gap_requirements.itertuples(index=False):
        (
            matching_total,
            matching_available,
            bases,
        ) = resource_bases_for_gap(
            requirement,
            crews,
            crew_skills,
            crew_available,
            machines,
            machine_available,
            equipment,
            materials,
        )

        (
            diagnosis,
            nearest_distance,
            nearest_travel,
            note,
        ) = classify_gap(
            requirement,
            matching_total,
            matching_available,
            bases,
            clean_text(requirement.section_id),
            endpoints,
            distance_cache,
        )

        diagnostics.append(
            {
                "requirement_id": requirement.requirement_id,
                "task_id": requirement.task_id,
                "section_id": requirement.section_id,
                "resource_category": requirement.resource_category,
                "requirement_type": requirement.requirement_type,
                "department": requirement.department,
                "resource_code": requirement.resource_code,
                "skill_code": requirement.skill_code,
                "matching_resources_total": matching_total,
                "matching_resources_available": matching_available,
                "nearest_network_distance_km": nearest_distance,
                "nearest_travel_minutes": nearest_travel,
                "diagnosis": diagnosis,
                "diagnostic_note": note or "",
            }
        )

    diagnostics_df = pd.DataFrame(diagnostics)

    diagnostics_df.to_csv(
        DIAGNOSTICS_OUTPUT,
        index=False,
    )

    diagnosis_counts = (
        diagnostics_df["diagnosis"]
        .value_counts()
        .sort_values(ascending=False)
    )

    category_diagnosis = (
        diagnostics_df.groupby(
            ["resource_category", "diagnosis"]
        )
        .size()
        .reset_index(name="count")
        .sort_values(
            ["count", "resource_category"],
            ascending=[False, True],
        )
    )

    unexpected_count = int(
        diagnostics_df["diagnosis"]
        .eq("UNEXPECTED_FEASIBILITY_MISMATCH")
        .sum()
    )

    report_lines = [
        "=" * 72,
        "TrackEase V3 Resource Gap Diagnostic Report",
        "=" * 72,
        "",
        f"Gap requirements analysed     : {len(diagnostics_df):,}",
        "",
        "DIAGNOSES",
        "-" * 72,
    ]

    for diagnosis, count in diagnosis_counts.items():
        report_lines.append(
            f"{diagnosis:<52} {count:>8,}"
        )

    report_lines.extend(
        [
            "",
            "CATEGORY + DIAGNOSIS",
            "-" * 72,
        ]
    )

    for row in category_diagnosis.itertuples(index=False):
        label = f"{row.resource_category} | {row.diagnosis}"
        report_lines.append(
            f"{label:<52} {row.count:>8,}"
        )

    report_lines.extend(
        [
            "",
            "INTERPRETATION",
            "-" * 72,
            (
                "NO_MATCHING_RESOURCE_EXISTS means the prototype resource "
                "master lacks that required skill/type."
            ),
            (
                "MATCHING_RESOURCE_EXISTS_BUT_NOT_AVAILABLE means the resource "
                "exists but has no available weekly record."
            ),
            (
                "NO_NETWORK_PATH_FROM_COMPATIBLE_RESOURCE_BASE means the "
                "resource and work section are in disconnected graph components."
            ),
            (
                "REACHABLE_BUT_OUTSIDE_CURRENT_TRAVEL_POLICY means the resource "
                "exists and the section is connected, but current radius/travel "
                "thresholds intentionally reject the assignment."
            ),
            (
                "UNEXPECTED_FEASIBILITY_MISMATCH indicates a likely logic "
                "mismatch that should be fixed before freezing V3.5."
            ),
            "",
            f"Unexpected mismatches          : {unexpected_count:,}",
        ]
    )

    REPORT_OUTPUT.write_text(
        "\n".join(report_lines),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)
    print("V3 RESOURCE GAP DIAGNOSTICS COMPLETE")
    print("=" * 72)

    for diagnosis, count in diagnosis_counts.items():
        print(f"{diagnosis:<52} {count:>8,}")

    print(f"\nUnexpected mismatches : {unexpected_count:,}")

    print("\nOutputs:")
    print(f"  {DIAGNOSTICS_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
