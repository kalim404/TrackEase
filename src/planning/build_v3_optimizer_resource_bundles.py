
"""
TrackEase V3.12A2 - Handover-Aware Resource Bundle Builder

Purpose
-------
Build optimizer-ready resource OPTIONS for every V3.11-feasible candidate
window.

Unlike the older V3.12A table, a resource option can contain MULTIPLE physical
resources. This is required for V3.11 crew handovers:

    Crew A covers 14:30-16:00
    Crew B covers 16:00-17:30

The optimizer must reserve both A and B, rather than treating "A|B" as one
fictional resource.

Important
---------
- Reads only V3.11-feasible windows.
- Uses only existing V3.5 qualified/reachable candidates.
- Does not create crews, machines, equipment, or inventory.
- Does not relax train/goods/safety gates.
- Enumerates bounded alternative handover chains so V3.12 can avoid
  double-booking when another qualified chain exists.
- This is prototype scheduling logic, not an official railway staffing rule.

Outputs
-------
data/processed/v3_optimizer_resource_bundle_members.csv
data/processed/v3_optimizer_resource_bundle_summary.csv
data/processed/v3_optimizer_resource_bundles_report.txt
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import math
import importlib.util

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"

FEASIBILITY_FILE = PROCESSED / "v3_candidate_window_feasibility.csv"
REQUIREMENTS_FILE = PROCESSED / "v3_task_resource_requirements.csv"
V35_CANDIDATES_FILE = PROCESSED / "v3_resource_assignment_candidates.csv"

CREWS_FILE = PROCESSED / "v3_crews.csv"
CREW_AVAILABILITY_FILE = PROCESSED / "v3_crew_availability.csv"
MACHINES_FILE = PROCESSED / "v3_machines.csv"
MACHINE_AVAILABILITY_FILE = PROCESSED / "v3_machine_availability.csv"
EQUIPMENT_FILE = PROCESSED / "v3_equipment.csv"
MATERIAL_FILE = PROCESSED / "v3_material_inventory.csv"

MEMBERS_OUTPUT = PROCESSED / "v3_optimizer_resource_bundle_members.csv"
SUMMARY_OUTPUT = PROCESSED / "v3_optimizer_resource_bundle_summary.csv"
REPORT_OUTPUT = PROCESSED / "v3_optimizer_resource_bundles_report.txt"

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080
EPSILON = 1e-9

FEASIBLE_STATUSES = {
    "FEASIBLE_READY_FOR_OPTIMIZER",
    "FEASIBLE_REPOSITIONING_REQUIRED",
}

DAY_INDEX = {
    "MON": 0, "MONDAY": 0,
    "TUE": 1, "TUES": 1, "TUESDAY": 1,
    "WED": 2, "WEDNESDAY": 2,
    "THU": 3, "THUR": 3, "THURSDAY": 3,
    "FRI": 4, "FRIDAY": 4,
    "SAT": 5, "SATURDAY": 5,
    "SUN": 6, "SUNDAY": 6,
}

MAX_HANDOVER_CHAIN = 4
MAX_HANDOVER_BUNDLES_PER_SLOT = 12
MAX_SINGLE_OPTIONS_PER_SLOT = 20

DATA_ORIGIN = "TRACKEASE_V3_12_HANDOVER_AWARE_RESOURCE_BUNDLES"
INTEGRATION_MODE = "PROTOTYPE_RESOURCE_BUNDLE_ENUMERATION"


# TRACKEASE_V311_MACHINE_SEMANTICS_ALIGNMENT
_V311_BASE_MODULE = None


def load_v311_base_module():
    global _V311_BASE_MODULE

    if _V311_BASE_MODULE is not None:
        return _V311_BASE_MODULE

    base_file = Path(__file__).with_name(
        "validate_v3_candidate_resource_safety.py"
    )

    if not base_file.exists():
        raise FileNotFoundError(
            f"Frozen/base V3.11 validator not found: {base_file}"
        )

    spec = importlib.util.spec_from_file_location(
        "trackease_v311_base_for_bundles",
        base_file,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Unable to load frozen/base V3.11 validator."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _V311_BASE_MODULE = module
    return module


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def to_bool(value: object, default: bool = False) -> bool:
    if pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def number(value: object, default: float | None = None) -> float | None:
    if pd.isna(value):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def parse_time(value: object, end_of_interval: bool = False) -> int | None:
    text = clean(value)
    if ":" not in text:
        return None
    try:
        hour, minute = map(int, text.split(":")[:2])
    except (TypeError, ValueError):
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    if end_of_interval and hour == 0 and minute == 0:
        return MINUTES_PER_DAY

    return hour * 60 + minute


def weekday_index(value: object) -> int | None:
    return DAY_INDEX.get(clean(value).upper())


def first_existing(
    frame: pd.DataFrame,
    names: list[str],
    required: bool = False,
) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    if required:
        raise ValueError(
            f"None of these required columns exist: {names}\n"
            f"Available: {frame.columns.tolist()}"
        )
    return None


def make_lookup(
    frame: pd.DataFrame,
    key_candidates: list[str],
) -> dict[str, dict]:
    key = first_existing(frame, key_candidates, required=True)
    result = {}
    for row in frame.to_dict(orient="records"):
        value = clean(row.get(key))
        if value:
            result[value] = row
    return result


def make_grouped(
    frame: pd.DataFrame,
    key_candidates: list[str],
) -> dict[str, list[dict]]:
    key = first_existing(frame, key_candidates, required=True)
    result: dict[str, list[dict]] = defaultdict(list)
    for row in frame.to_dict(orient="records"):
        value = clean(row.get(key))
        if value:
            result[value].append(row)
    return dict(result)


def merge_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if not intervals:
        return []

    ordered = sorted(intervals)
    merged: list[list[float]] = [
        [float(ordered[0][0]), float(ordered[0][1])]
    ]

    for start, end in ordered[1:]:
        if start <= merged[-1][1] + EPSILON:
            merged[-1][1] = max(merged[-1][1], float(end))
        else:
            merged.append([float(start), float(end)])

    return [(start, end) for start, end in merged]


def build_weekly_availability(
    frame: pd.DataFrame,
    resource_id_candidates: list[str],
    start_candidates: list[str],
    end_candidates: list[str],
) -> dict[str, list[tuple[float, float]]]:
    resource_col = first_existing(frame, resource_id_candidates, required=True)
    start_col = first_existing(frame, start_candidates, required=True)
    end_col = first_existing(frame, end_candidates, required=True)
    weekday_col = first_existing(
        frame,
        ["weekday", "day_name", "day"],
        required=True,
    )
    available_col = first_existing(
        frame,
        ["available", "is_available", "availability_status"],
        required=False,
    )

    raw: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for row in frame.to_dict(orient="records"):
        if available_col is not None:
            raw_value = row.get(available_col)
            available = (
                to_bool(raw_value, default=False)
                if clean(raw_value).upper() not in {"AVAILABLE", "READY"}
                else True
            )
            if not available:
                continue

        resource_id = clean(row.get(resource_col))
        day = weekday_index(row.get(weekday_col))
        start = parse_time(row.get(start_col))
        end = parse_time(row.get(end_col), end_of_interval=True)

        if (
            not resource_id
            or day is None
            or start is None
            or end is None
        ):
            continue

        absolute_start = day * MINUTES_PER_DAY + start
        absolute_end = day * MINUTES_PER_DAY + end

        if absolute_end <= absolute_start:
            absolute_end += MINUTES_PER_DAY

        # Add neighboring copies so Sunday->Monday cyclic intervals work.
        for week_shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
            raw[resource_id].append(
                (
                    float(absolute_start + week_shift),
                    float(absolute_end + week_shift),
                )
            )

    return {
        resource_id: merge_intervals(intervals)
        for resource_id, intervals in raw.items()
    }


def interval_covered(
    intervals: list[tuple[float, float]],
    start: float,
    end: float,
) -> bool:
    return any(
        interval_start <= start + EPSILON
        and interval_end >= end - EPSILON
        for interval_start, interval_end in intervals
    )


def candidate_field(
    row: dict,
    names: list[str],
    default: object = "",
) -> object:
    for name in names:
        if name in row:
            value = row.get(name)
            if not pd.isna(value):
                return value
    return default


def get_resource_id(option: dict) -> str:
    return clean(
        candidate_field(
            option,
            ["resource_id", "selected_resource_id"],
        )
    )


def get_resource_type(option: dict) -> str:
    return clean(
        candidate_field(
            option,
            ["resource_type", "selected_resource_type"],
        )
    )


def get_travel(option: dict) -> float:
    value = number(
        candidate_field(
            option,
            ["travel_minutes_proxy", "travel_minutes"],
            0.0,
        ),
        0.0,
    )
    return max(0.0, float(value or 0.0))


def source_repositioning(option: dict) -> bool:
    status = clean(
        candidate_field(
            option,
            ["readiness_status", "resource_readiness_status"],
        )
    ).upper()
    return status == "REPOSITIONING_REQUIRED"


def status_available(row: dict) -> bool:
    status = clean(
        candidate_field(
            row,
            ["status", "availability_status"],
            "AVAILABLE",
        )
    ).upper()

    return status in {
        "",
        "AVAILABLE",
        "READY",
        "ACTIVE",
        "OPERATIONAL",
    }


def crew_like_requirement(requirement: dict) -> bool:
    category = clean(requirement.get("resource_category")).upper()
    requirement_type = clean(requirement.get("requirement_type")).upper()

    return (
        category == "CREW"
        or (
            category == "OPERATIONAL_PREREQUISITE"
            and requirement_type == "POWER_ISOLATION"
        )
    )


def enumerate_crew_bundles(
    options: list[dict],
    crew_lookup: dict[str, dict],
    availability: dict[str, list[tuple[float, float]]],
    window_start: float,
    window_end: float,
) -> list[list[dict]]:
    """
    Return alternative resource bundles.

    Each bundle is a list of physical crew-member segments. Single-crew options
    are returned first. Then bounded multi-crew continuous-coverage chains are
    enumerated.
    """
    single_bundles: list[list[dict]] = []
    segment_candidates: list[dict] = []

    seen_single = set()

    for option in options:
        crew_id = get_resource_id(option)
        crew = crew_lookup.get(crew_id)

        if not crew_id or crew is None or not status_available(crew):
            continue

        max_work = number(
            candidate_field(
                crew,
                ["max_work_minutes_per_shift", "max_work_minutes"],
                480.0,
            ),
            480.0,
        )
        max_work = float(max_work or 480.0)

        travel = get_travel(option)
        intervals = availability.get(crew_id, [])

        # Single-crew exact coverage.
        if (
            window_end - window_start <= max_work + EPSILON
            and interval_covered(intervals, window_start, window_end)
        ):
            signature = crew_id
            if signature not in seen_single:
                travel_in_shift = interval_covered(
                    intervals,
                    window_start - travel,
                    window_end,
                )

                single_bundles.append(
                    [
                        {
                            "resource_id": crew_id,
                            "resource_type": "CREW",
                            "coverage_start": window_start,
                            "coverage_end": window_end,
                            "booking_start": window_start - travel,
                            "booking_end": window_end,
                            "travel_minutes": travel,
                            "repositioning_required": (
                                source_repositioning(option)
                                or not travel_in_shift
                                or travel + (window_end - window_start)
                                > max_work + EPSILON
                            ),
                            "source_candidate_rank": candidate_field(
                                option,
                                ["candidate_rank"],
                                "",
                            ),
                        }
                    ]
                )
                seen_single.add(signature)

        # Partial coverage segments for possible handover chains.
        for interval_start, interval_end in intervals:
            overlap_start = max(interval_start, window_start)
            overlap_end = min(interval_end, window_end)

            if overlap_end <= overlap_start + EPSILON:
                continue

            segment_candidates.append(
                {
                    "resource_id": crew_id,
                    "resource_type": "CREW",
                    "availability_start": interval_start,
                    "availability_end": interval_end,
                    "max_work": max_work,
                    "travel_minutes": travel,
                    "source_repositioning": source_repositioning(option),
                    "source_candidate_rank": candidate_field(
                        option,
                        ["candidate_rank"],
                        "",
                    ),
                }
            )

    single_bundles.sort(
        key=lambda bundle: (
            1 if bundle[0]["repositioning_required"] else 0,
            bundle[0]["travel_minutes"],
            bundle[0]["resource_id"],
        )
    )
    single_bundles = single_bundles[:MAX_SINGLE_OPTIONS_PER_SLOT]

    # Enumerate multiple continuous chains with DFS.
    handover_bundles: list[list[dict]] = []
    handover_signatures = set()

    def dfs(
        cursor: float,
        chain: list[dict],
        used_ids: set[str],
    ) -> None:
        if len(handover_bundles) >= MAX_HANDOVER_BUNDLES_PER_SLOT:
            return

        if cursor >= window_end - EPSILON:
            if len(chain) >= 2:
                signature = tuple(
                    (
                        member["resource_id"],
                        round(member["coverage_start"], 6),
                        round(member["coverage_end"], 6),
                    )
                    for member in chain
                )

                if signature not in handover_signatures:
                    handover_signatures.add(signature)
                    handover_bundles.append([dict(member) for member in chain])
            return

        if len(chain) >= MAX_HANDOVER_CHAIN:
            return

        next_segments = []

        for item in segment_candidates:
            resource_id = item["resource_id"]

            if resource_id in used_ids:
                continue

            if item["availability_start"] > cursor + EPSILON:
                continue

            if item["availability_end"] <= cursor + EPSILON:
                continue

            coverage_end = min(
                item["availability_end"],
                cursor + item["max_work"],
                window_end,
            )

            if coverage_end <= cursor + EPSILON:
                continue

            # Prefer longest reach, then local/non-reposition, then less travel.
            next_segments.append(
                (
                    -coverage_end,
                    1 if item["source_repositioning"] else 0,
                    item["travel_minutes"],
                    resource_id,
                    item,
                    coverage_end,
                )
            )

        next_segments.sort()

        # Limit branching: enough alternatives for competition, finite runtime.
        for _, _, _, _, item, coverage_end in next_segments[:8]:
            travel = item["travel_minutes"]
            segment_duration = coverage_end - cursor

            repositioning = (
                item["source_repositioning"]
                or item["availability_start"]
                > cursor - travel + EPSILON
                or travel + segment_duration
                > item["max_work"] + EPSILON
            )

            member = {
                "resource_id": item["resource_id"],
                "resource_type": "CREW",
                "coverage_start": cursor,
                "coverage_end": coverage_end,
                "booking_start": cursor - travel,
                "booking_end": coverage_end,
                "travel_minutes": travel,
                "repositioning_required": repositioning,
                "source_candidate_rank": item["source_candidate_rank"],
            }

            dfs(
                coverage_end,
                chain + [member],
                used_ids | {item["resource_id"]},
            )

            if len(handover_bundles) >= MAX_HANDOVER_BUNDLES_PER_SLOT:
                break

    dfs(window_start, [], set())

    handover_bundles.sort(
        key=lambda bundle: (
            len(bundle),
            sum(1 for item in bundle if item["repositioning_required"]),
            sum(item["travel_minutes"] for item in bundle),
            "|".join(item["resource_id"] for item in bundle),
        )
    )

    return single_bundles + handover_bundles


def enumerate_machine_bundles(
    options: list[dict],
    machine_lookup: dict[str, dict],
    availability: dict[str, list[tuple[float, float]]],
    window_start: float,
    window_end: float,
) -> list[list[dict]]:
    v311 = load_v311_base_module()

    bundles = []
    seen = set()

    for option in options:
        resource_id = get_resource_id(option)

        if not resource_id or resource_id in seen:
            continue

        exact_ready, repositioning_required, exact_reason = (
            v311.evaluate_machine_candidate(
                option,
                machine_lookup,
                availability,
                window_start,
                window_end,
            )
        )

        if not exact_ready:
            continue

        travel = get_travel(option)

        bundles.append(
            [
                {
                    "resource_id": resource_id,
                    "resource_type": "MACHINE",
                    "coverage_start": window_start,
                    "coverage_end": window_end,
                    "booking_start": window_start - travel,
                    "booking_end": window_end,
                    "travel_minutes": travel,
                    "repositioning_required": bool(
                        repositioning_required
                    ),
                    "source_candidate_rank": candidate_field(
                        option,
                        ["candidate_rank"],
                        "",
                    ),
                    "v3_11_exact_reason": exact_reason,
                }
            ]
        )

        seen.add(resource_id)

    bundles.sort(
        key=lambda bundle: (
            1 if bundle[0]["repositioning_required"] else 0,
            bundle[0]["travel_minutes"],
            bundle[0]["resource_id"],
        )
    )

    return bundles[:MAX_SINGLE_OPTIONS_PER_SLOT]


def enumerate_equipment_bundles(
    options: list[dict],
    equipment_lookup: dict[str, dict],
    window_start: float,
    window_end: float,
) -> list[list[dict]]:
    bundles = []
    seen = set()

    for option in options:
        resource_id = get_resource_id(option)
        equipment = equipment_lookup.get(resource_id)

        if not resource_id or equipment is None or not status_available(equipment):
            continue

        if resource_id in seen:
            continue

        travel = get_travel(option)

        bundles.append(
            [
                {
                    "resource_id": resource_id,
                    "resource_type": "EQUIPMENT",
                    "coverage_start": window_start,
                    "coverage_end": window_end,
                    "booking_start": window_start - travel,
                    "booking_end": window_end,
                    "travel_minutes": travel,
                    "repositioning_required": source_repositioning(option),
                    "source_candidate_rank": candidate_field(
                        option,
                        ["candidate_rank"],
                        "",
                    ),
                }
            ]
        )
        seen.add(resource_id)

    bundles.sort(
        key=lambda bundle: (
            1 if bundle[0]["repositioning_required"] else 0,
            bundle[0]["travel_minutes"],
            bundle[0]["resource_id"],
        )
    )

    return bundles[:MAX_SINGLE_OPTIONS_PER_SLOT]


def enumerate_material_bundles(
    options: list[dict],
    material_lookup: dict[str, dict],
    requirement: dict,
    window_start: float,
    window_end: float,
) -> list[list[dict]]:
    bundles = []
    seen = set()

    required_quantity = number(
        requirement.get("quantity_required"),
        1.0,
    )
    required_quantity = float(required_quantity or 1.0)

    for option in options:
        resource_id = get_resource_id(option)
        inventory = material_lookup.get(resource_id)

        if not resource_id or inventory is None or resource_id in seen:
            continue

        available_quantity = number(
            candidate_field(
                inventory,
                ["quantity_available", "available_quantity"],
                0.0,
            ),
            0.0,
        )
        available_quantity = float(available_quantity or 0.0)

        if available_quantity + EPSILON < required_quantity:
            continue

        bundles.append(
            [
                {
                    "resource_id": resource_id,
                    "resource_type": "MATERIAL",
                    "coverage_start": window_start,
                    "coverage_end": window_end,
                    "booking_start": window_start,
                    "booking_end": window_end,
                    "travel_minutes": get_travel(option),
                    "repositioning_required": source_repositioning(option),
                    "source_candidate_rank": candidate_field(
                        option,
                        ["candidate_rank"],
                        "",
                    ),
                    "quantity_required": required_quantity,
                    "consumable": True,
                }
            ]
        )
        seen.add(resource_id)

    return bundles[:MAX_SINGLE_OPTIONS_PER_SLOT]


def enumerate_requirement_bundles(
    requirement: dict,
    options: list[dict],
    crew_lookup: dict[str, dict],
    crew_availability: dict[str, list[tuple[float, float]]],
    machine_lookup: dict[str, dict],
    machine_availability: dict[str, list[tuple[float, float]]],
    equipment_lookup: dict[str, dict],
    material_lookup: dict[str, dict],
    window_start: float,
    window_end: float,
) -> list[list[dict]]:
    category = clean(requirement.get("resource_category")).upper()

    if crew_like_requirement(requirement):
        return enumerate_crew_bundles(
            options,
            crew_lookup,
            crew_availability,
            window_start,
            window_end,
        )

    if category == "MACHINE":
        return enumerate_machine_bundles(
            options,
            machine_lookup,
            machine_availability,
            window_start,
            window_end,
        )

    if category == "EQUIPMENT":
        return enumerate_equipment_bundles(
            options,
            equipment_lookup,
            window_start,
            window_end,
        )

    if category == "MATERIAL":
        return enumerate_material_bundles(
            options,
            material_lookup,
            requirement,
            window_start,
            window_end,
        )

    return []


def main() -> None:
    print("=" * 72)
    print("TrackEase V3.12A2 - Handover-Aware Resource Bundle Builder")
    print("=" * 72)

    required_paths = [
        FEASIBILITY_FILE,
        REQUIREMENTS_FILE,
        V35_CANDIDATES_FILE,
        CREWS_FILE,
        CREW_AVAILABILITY_FILE,
        MACHINES_FILE,
        MACHINE_AVAILABILITY_FILE,
        EQUIPMENT_FILE,
        MATERIAL_FILE,
    ]

    missing = [path for path in required_paths if not path.exists()]

    if missing:
        raise FileNotFoundError(
            "Missing required V3 inputs:\n"
            + "\n".join(f"  {path}" for path in missing)
        )

    feasibility = pd.read_csv(FEASIBILITY_FILE, low_memory=False)
    requirements = pd.read_csv(REQUIREMENTS_FILE, low_memory=False)
    v35 = pd.read_csv(V35_CANDIDATES_FILE, low_memory=False)

    crews = pd.read_csv(CREWS_FILE, low_memory=False)
    crew_availability_df = pd.read_csv(
        CREW_AVAILABILITY_FILE,
        low_memory=False,
    )
    machines = pd.read_csv(MACHINES_FILE, low_memory=False)
    machine_availability_df = pd.read_csv(
        MACHINE_AVAILABILITY_FILE,
        low_memory=False,
    )
    equipment = pd.read_csv(EQUIPMENT_FILE, low_memory=False)
    materials = pd.read_csv(MATERIAL_FILE, low_memory=False)

    status_col = first_existing(
        feasibility,
        ["final_feasibility_status", "status"],
        required=True,
    )

    feasible = feasibility[
        feasibility[status_col].astype(str).isin(FEASIBLE_STATUSES)
    ].copy()

    print(f"\nV3.11-feasible windows : {len(feasible):,}")
    print(f"Resource requirements  : {len(requirements):,}")
    print(f"V3.5 candidates        : {len(v35):,}")

    requirements_by_task = make_grouped(requirements, ["task_id"])
    options_by_requirement = make_grouped(v35, ["requirement_id"])

    crew_lookup = make_lookup(crews, ["crew_id"])
    machine_lookup = make_lookup(machines, ["machine_id"])
    equipment_lookup = make_lookup(equipment, ["equipment_id"])
    material_lookup = make_lookup(materials, ["inventory_id"])

    v311 = load_v311_base_module()

    crew_availability = v311.build_weekly_availability_index(
        crew_availability_df,
        "crew_id",
        "shift_start",
        "shift_end",
    )

    machine_availability = v311.build_weekly_availability_index(
        machine_availability_df,
        "machine_id",
        "available_from",
        "available_to",
    )

    member_rows = []
    summary_rows = []
    missing_slots = []

    total_slots = 0
    handover_bundle_count = 0
    single_bundle_count = 0

    print("\nBuilding exact-time resource bundles...")

    for window in feasible.to_dict(orient="records"):
        candidate_id = clean(window.get("candidate_window_id"))
        task_id = clean(window.get("task_id"))
        section_id = clean(window.get("section_id"))

        window_start = number(window.get("window_start_minute_week"))
        window_end = number(window.get("window_end_minute_week"))

        if window_start is None or window_end is None:
            raise RuntimeError(
                f"Invalid timing in feasible candidate {candidate_id}."
            )

        mandatory_requirements = [
            requirement
            for requirement in requirements_by_task.get(task_id, [])
            if to_bool(requirement.get("mandatory"), default=True)
        ]

        for requirement in mandatory_requirements:
            total_slots += 1

            requirement_id = clean(requirement.get("requirement_id"))
            requirement_type = clean(requirement.get("requirement_type"))
            category = clean(requirement.get("resource_category"))

            bundles = enumerate_requirement_bundles(
                requirement,
                options_by_requirement.get(requirement_id, []),
                crew_lookup,
                crew_availability,
                machine_lookup,
                machine_availability,
                equipment_lookup,
                material_lookup,
                float(window_start),
                float(window_end),
            )

            if not bundles:
                missing_slots.append(
                    {
                        "candidate_window_id": candidate_id,
                        "task_id": task_id,
                        "requirement_id": requirement_id,
                        "resource_category": category,
                        "requirement_type": requirement_type,
                    }
                )
                continue

            for option_rank, bundle in enumerate(bundles, start=1):
                bundle_id = (
                    f"{candidate_id}::{requirement_id}::B{option_rank:02d}"
                )

                handover_required = len(bundle) > 1
                repositioning_required = any(
                    bool(member["repositioning_required"])
                    for member in bundle
                )

                if handover_required:
                    handover_bundle_count += 1
                else:
                    single_bundle_count += 1

                summary_rows.append(
                    {
                        "candidate_window_id": candidate_id,
                        "task_id": task_id,
                        "section_id": section_id,
                        "requirement_id": requirement_id,
                        "resource_category": category,
                        "requirement_type": requirement_type,
                        "option_bundle_id": bundle_id,
                        "option_rank": option_rank,
                        "bundle_member_count": len(bundle),
                        "handover_required": handover_required,
                        "handover_count": max(0, len(bundle) - 1),
                        "repositioning_required": repositioning_required,
                        "resource_ids": "|".join(
                            member["resource_id"] for member in bundle
                        ),
                        "data_origin": DATA_ORIGIN,
                        "integration_mode": INTEGRATION_MODE,
                    }
                )

                for member_index, member in enumerate(bundle, start=1):
                    member_rows.append(
                        {
                            "candidate_window_id": candidate_id,
                            "task_id": task_id,
                            "section_id": section_id,
                            "window_start_minute_week": float(window_start),
                            "window_end_minute_week": float(window_end),
                            "requirement_id": requirement_id,
                            "resource_category": category,
                            "requirement_type": requirement_type,
                            "option_bundle_id": bundle_id,
                            "option_rank": option_rank,
                            "bundle_member_index": member_index,
                            "bundle_member_count": len(bundle),
                            "resource_id": member["resource_id"],
                            "resource_type": member["resource_type"],
                            "coverage_start_minute_week":
                                member["coverage_start"],
                            "coverage_end_minute_week":
                                member["coverage_end"],
                            "booking_start_minute_week":
                                member["booking_start"],
                            "booking_end_minute_week":
                                member["booking_end"],
                            "travel_minutes_proxy":
                                member["travel_minutes"],
                            "quantity_required":
                                member.get(
                                    "quantity_required",
                                    requirement.get("quantity_required", 1.0),
                                ),
                            "consumable":
                                bool(member.get("consumable", False)),
                            "repositioning_required":
                                bool(member["repositioning_required"]),
                            "handover_required":
                                handover_required,
                            "source_candidate_rank":
                                member["source_candidate_rank"],
                            "data_origin": DATA_ORIGIN,
                            "integration_mode": INTEGRATION_MODE,
                        }
                    )

    members = pd.DataFrame(member_rows)
    summary = pd.DataFrame(summary_rows)

    if members.empty or summary.empty:
        raise RuntimeError("No optimizer resource bundles were generated.")

    duplicate_members = int(
        members.duplicated(
            subset=[
                "candidate_window_id",
                "requirement_id",
                "option_bundle_id",
                "bundle_member_index",
            ]
        ).sum()
    )

    duplicate_bundles = int(
        summary["option_bundle_id"].duplicated().sum()
    )

    if duplicate_members or duplicate_bundles:
        raise RuntimeError(
            "Bundle integrity failure: "
            f"duplicate members={duplicate_members}, "
            f"duplicate bundles={duplicate_bundles}"
        )

    if missing_slots:
        sample = missing_slots[:10]
        raise RuntimeError(
            "A V3.11-feasible window has a mandatory requirement with no "
            "handover-aware optimizer bundle.\n"
            f"Missing slots: {len(missing_slots):,}\n"
            f"Examples: {sample}"
        )

    # Verify continuous coverage for every handover bundle.
    coverage_failures = 0

    handover_members = members[
        members["handover_required"].astype(bool)
    ]

    for _, group in handover_members.groupby("option_bundle_id"):
        ordered = group.sort_values(
            "coverage_start_minute_week"
        )

        expected_start = float(
            ordered["window_start_minute_week"].iloc[0]
        )
        expected_end = float(
            ordered["window_end_minute_week"].iloc[0]
        )

        cursor = expected_start

        for row in ordered.itertuples(index=False):
            start = float(row.coverage_start_minute_week)
            end = float(row.coverage_end_minute_week)

            if start > cursor + 1e-6:
                coverage_failures += 1
                break

            cursor = max(cursor, end)

        if cursor < expected_end - 1e-6:
            coverage_failures += 1

    if coverage_failures:
        raise RuntimeError(
            f"Continuous handover coverage failures: {coverage_failures:,}"
        )

    members.to_csv(MEMBERS_OUTPUT, index=False)
    summary.to_csv(SUMMARY_OUTPUT, index=False)

    option_counts = (
        summary.groupby(
            ["candidate_window_id", "requirement_id"]
        )
        .size()
    )

    handover_requirement_types = (
        summary[
            summary["handover_required"].astype(bool)
        ]["requirement_type"]
        .value_counts()
    )

    lines = [
        "=" * 72,
        "TrackEase V3.12A2 Handover-Aware Resource Bundle Report",
        "=" * 72,
        "",
        f"V3.11-feasible windows        : {len(feasible):,}",
        f"Mandatory requirement slots   : {total_slots:,}",
        f"Resource option bundles       : {len(summary):,}",
        f"Physical bundle-member rows   : {len(members):,}",
        f"Single-resource bundles       : {single_bundle_count:,}",
        f"Handover bundles              : {handover_bundle_count:,}",
        f"Missing requirement slots     : {len(missing_slots):,}",
        f"Duplicate bundles             : {duplicate_bundles:,}",
        f"Duplicate member rows         : {duplicate_members:,}",
        f"Handover coverage failures    : {coverage_failures:,}",
        f"Average bundles per slot      : {option_counts.mean():.2f}",
        f"Minimum bundles per slot      : {int(option_counts.min()):,}",
        f"Maximum bundles per slot      : {int(option_counts.max()):,}",
        "",
        "HANDOVER BUNDLES BY REQUIREMENT TYPE",
        "-" * 72,
    ]

    if handover_requirement_types.empty:
        lines.append("None")
    else:
        for name, count in handover_requirement_types.items():
            lines.append(f"{str(name):<45} {count:>10,}")

    lines.extend(
        [
            "",
            "BOUNDARY",
            "-" * 72,
            (
                "Each handover bundle explicitly identifies every physical "
                "crew and the exact segment it covers."
            ),
            (
                "V3.12 must reserve every bundle member independently; a "
                "handover chain is never treated as one fictional resource."
            ),
            (
                "Final railway protection/technical handover remains subject "
                "to human authorization and applicable rules."
            ),
        ]
    )

    REPORT_OUTPUT.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 72)
    print("V3.12A2 RESOURCE BUNDLE BUILD COMPLETE")
    print("=" * 72)
    print(f"\nMandatory requirement slots : {total_slots:,}")
    print(f"Resource option bundles     : {len(summary):,}")
    print(f"Physical member rows        : {len(members):,}")
    print(f"Single-resource bundles     : {single_bundle_count:,}")
    print(f"Handover bundles            : {handover_bundle_count:,}")
    print(f"Missing slots               : {len(missing_slots):,}")
    print(f"Duplicate bundles           : {duplicate_bundles:,}")
    print(f"Handover coverage failures  : {coverage_failures:,}")
    print(f"Average bundles per slot    : {option_counts.mean():.2f}")

    print("\nOutputs:")
    print(f"  {MEMBERS_OUTPUT}")
    print(f"  {SUMMARY_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
