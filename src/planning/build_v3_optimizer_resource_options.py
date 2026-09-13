"""
TrackEase V3.12A - Exact-Time Resource Option Expansion

Build ALL exact-time-feasible resource alternatives for every V3.11-feasible
candidate window. This prevents Optimizer V3 from being locked to the single
resource choice that V3.11 used only to prove feasibility.

Safety rules are unchanged. Output:
    data/processed/v3_optimizer_resource_options.csv
    data/processed/v3_optimizer_resource_options_report.txt
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import math

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

FEASIBILITY_FILE = PROCESSED_DIR / "v3_candidate_window_feasibility.csv"
REQUIREMENTS_FILE = PROCESSED_DIR / "v3_task_resource_requirements.csv"
V35_CANDIDATES_FILE = PROCESSED_DIR / "v3_resource_assignment_candidates.csv"
CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
CREW_AVAILABILITY_FILE = PROCESSED_DIR / "v3_crew_availability.csv"
MACHINES_FILE = PROCESSED_DIR / "v3_machines.csv"
MACHINE_AVAILABILITY_FILE = PROCESSED_DIR / "v3_machine_availability.csv"
EQUIPMENT_FILE = PROCESSED_DIR / "v3_equipment.csv"
MATERIAL_FILE = PROCESSED_DIR / "v3_material_inventory.csv"

OUTPUT_FILE = PROCESSED_DIR / "v3_optimizer_resource_options.csv"
REPORT_FILE = PROCESSED_DIR / "v3_optimizer_resource_options_report.txt"

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

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

DATA_ORIGIN = "TRACKEASE_V3_OPTIMIZER_RESOURCE_OPTION_EXPANSION"
INTEGRATION_MODE = "PROTOTYPE_EXACT_TIME_RESOURCE_OPTION_LAYER"


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


def hhmm(value: object, end_of_day: bool = False) -> int | None:
    text = clean(value)
    if ":" not in text:
        return None
    try:
        hour, minute = map(int, text.split(":")[:2])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if end_of_day and hour == 0 and minute == 0:
        return MINUTES_PER_DAY
    if end_of_day and hour == 23 and minute == 59:
        return MINUTES_PER_DAY
    return hour * 60 + minute


def weekday(value: object) -> int | None:
    return DAY_INDEX.get(clean(value).upper())


def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(float(start), float(end)) for start, end in merged]


def interval_covered(
    intervals: list[tuple[float, float]],
    start: float,
    end: float,
) -> bool:
    return any(
        interval_start <= start and interval_end >= end
        for interval_start, interval_end in intervals
    )


def build_availability_index(
    dataframe: pd.DataFrame,
    resource_id_column: str,
    start_column: str,
    end_column: str,
) -> dict[str, list[tuple[float, float]]]:
    raw: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for row in dataframe.to_dict(orient="records"):
        if not to_bool(row.get("available")):
            continue

        resource_id = clean(row.get(resource_id_column))
        day = weekday(row.get("weekday"))
        start = hhmm(row.get(start_column))
        end = hhmm(row.get(end_column), end_of_day=True)

        if not resource_id or day is None or start is None or end is None:
            continue

        absolute_start = day * MINUTES_PER_DAY + start
        absolute_end = day * MINUTES_PER_DAY + end
        if absolute_end <= absolute_start:
            absolute_end += MINUTES_PER_DAY

        for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
            raw[resource_id].append(
                (absolute_start + shift, absolute_end + shift)
            )

    return {
        resource_id: merge_intervals(intervals)
        for resource_id, intervals in raw.items()
    }


def lookup(dataframe: pd.DataFrame, key: str) -> dict[str, dict]:
    return {
        clean(row.get(key)): row
        for row in dataframe.to_dict(orient="records")
        if clean(row.get(key))
    }


def grouped(dataframe: pd.DataFrame, key: str) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for row in dataframe.to_dict(orient="records"):
        value = clean(row.get(key))
        if value:
            result[value].append(row)
    return dict(result)


def evaluate_option(
    option: dict,
    requirement: dict,
    window_start: float,
    window_end: float,
    crew_lookup: dict[str, dict],
    crew_availability: dict[str, list[tuple[float, float]]],
    machine_lookup: dict[str, dict],
    machine_availability: dict[str, list[tuple[float, float]]],
    equipment_lookup: dict[str, dict],
    material_lookup: dict[str, dict],
) -> tuple[bool, bool, str]:
    category = clean(requirement.get("resource_category")).upper()
    resource_id = clean(option.get("resource_id"))
    resource_type = clean(option.get("resource_type")).upper()
    block_minutes = window_end - window_start

    if not resource_id:
        return False, False, "MISSING_RESOURCE_ID"

    if category == "CREW" or resource_type in {"CREW", "ISOLATION_SUPPORT_CREW"}:
        crew = crew_lookup.get(resource_id)
        if crew is None or clean(crew.get("status")).upper() != "AVAILABLE":
            return False, False, "CREW_NOT_AVAILABLE"

        max_work = number(crew.get("max_work_minutes_per_shift"), 480.0) or 480.0
        if block_minutes > max_work:
            return False, False, "CREW_WORK_LIMIT"
        if not interval_covered(
            crew_availability.get(resource_id, []),
            window_start,
            window_end,
        ):
            return False, False, "CREW_SHIFT_NOT_COVERING_BLOCK"

        travel = number(option.get("travel_minutes_proxy"), 0.0) or 0.0
        travel_covered = interval_covered(
            crew_availability.get(resource_id, []),
            window_start - travel,
            window_end,
        )
        source_reposition = (
            clean(option.get("readiness_status")).upper()
            == "REPOSITIONING_REQUIRED"
        )
        repositioning = (
            source_reposition
            or not travel_covered
            or travel + block_minutes > max_work
        )
        return True, repositioning, (
            "EXACT_TIME_FEASIBLE_REPOSITIONING_REQUIRED"
            if repositioning else "EXACT_TIME_READY"
        )

    if category == "MACHINE":
        machine = machine_lookup.get(resource_id)
        if machine is None or clean(machine.get("status")).upper() != "AVAILABLE":
            return False, False, "MACHINE_NOT_AVAILABLE"

        max_minutes = number(
            machine.get("max_operating_minutes_per_day"),
            600.0,
        ) or 600.0
        if block_minutes > max_minutes:
            return False, False, "MACHINE_DAILY_LIMIT"
        if not interval_covered(
            machine_availability.get(resource_id, []),
            window_start,
            window_end,
        ):
            return False, False, "MACHINE_TIME_NOT_AVAILABLE"

        travel = number(option.get("travel_minutes_proxy"), 0.0) or 0.0
        travel_covered = interval_covered(
            machine_availability.get(resource_id, []),
            window_start - travel,
            window_end,
        )
        source_reposition = (
            clean(option.get("readiness_status")).upper()
            == "REPOSITIONING_REQUIRED"
        )
        repositioning = (
            source_reposition
            or not travel_covered
            or travel + block_minutes > max_minutes
        )
        return True, repositioning, (
            "EXACT_TIME_FEASIBLE_REPOSITIONING_REQUIRED"
            if repositioning else "EXACT_TIME_READY"
        )

    if category == "EQUIPMENT":
        equipment = equipment_lookup.get(resource_id)
        if equipment is None or clean(equipment.get("status")).upper() != "AVAILABLE":
            return False, False, "EQUIPMENT_NOT_AVAILABLE"
        repositioning = (
            clean(option.get("readiness_status")).upper()
            == "REPOSITIONING_REQUIRED"
        )
        return True, repositioning, (
            "EXACT_TIME_FEASIBLE_REPOSITIONING_REQUIRED"
            if repositioning else "EXACT_TIME_READY"
        )

    if category == "MATERIAL":
        inventory = material_lookup.get(resource_id)
        if inventory is None:
            return False, False, "MATERIAL_MASTER_MISSING"
        available = number(inventory.get("quantity_available"), 0.0) or 0.0
        required = number(requirement.get("quantity_required"), 1.0) or 1.0
        if available < required:
            return False, False, "MATERIAL_STOCK_INSUFFICIENT"
        repositioning = (
            clean(option.get("readiness_status")).upper()
            == "REPOSITIONING_REQUIRED"
        )
        return True, repositioning, (
            "EXACT_TIME_FEASIBLE_REPOSITIONING_REQUIRED"
            if repositioning else "EXACT_TIME_READY"
        )

    if category == "OPERATIONAL_PREREQUISITE":
        crew = crew_lookup.get(resource_id)
        if crew is None or clean(crew.get("status")).upper() != "AVAILABLE":
            return False, False, "ISOLATION_CREW_NOT_AVAILABLE"
        max_work = number(crew.get("max_work_minutes_per_shift"), 480.0) or 480.0
        if block_minutes > max_work:
            return False, False, "ISOLATION_CREW_WORK_LIMIT"
        if not interval_covered(
            crew_availability.get(resource_id, []),
            window_start,
            window_end,
        ):
            return False, False, "ISOLATION_CREW_SHIFT_NOT_COVERING_BLOCK"
        travel = number(option.get("travel_minutes_proxy"), 0.0) or 0.0
        travel_covered = interval_covered(
            crew_availability.get(resource_id, []),
            window_start - travel,
            window_end,
        )
        source_reposition = (
            clean(option.get("readiness_status")).upper()
            == "REPOSITIONING_REQUIRED"
        )
        repositioning = (
            source_reposition
            or not travel_covered
            or travel + block_minutes > max_work
        )
        return True, repositioning, (
            "EXACT_TIME_FEASIBLE_REPOSITIONING_REQUIRED"
            if repositioning else "EXACT_TIME_READY"
        )

    return False, False, "UNSUPPORTED_RESOURCE_CATEGORY"


def main() -> None:
    print("=" * 72)
    print("TrackEase V3.12A - Exact-Time Resource Option Expansion")
    print("=" * 72)

    required_files = [
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
    missing = [path for path in required_files if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing required files:\n"
            + "\n".join(f"  {path}" for path in missing)
        )

    print("\nLoading V3.11 windows and V3.5 resource alternatives...")
    feasibility = pd.read_csv(FEASIBILITY_FILE, low_memory=False)
    requirements = pd.read_csv(REQUIREMENTS_FILE, low_memory=False)
    v35_candidates = pd.read_csv(V35_CANDIDATES_FILE, low_memory=False)
    crews = pd.read_csv(CREWS_FILE, low_memory=False)
    crew_availability_df = pd.read_csv(CREW_AVAILABILITY_FILE, low_memory=False)
    machines = pd.read_csv(MACHINES_FILE, low_memory=False)
    machine_availability_df = pd.read_csv(MACHINE_AVAILABILITY_FILE, low_memory=False)
    equipment = pd.read_csv(EQUIPMENT_FILE, low_memory=False)
    materials = pd.read_csv(MATERIAL_FILE, low_memory=False)

    feasible_windows = feasibility[
        feasibility["final_feasibility_status"].astype(str).isin(FEASIBLE_STATUSES)
    ].copy()

    print(f"V3.11-feasible windows : {len(feasible_windows):,}")
    print(f"V3.5 candidate rows    : {len(v35_candidates):,}")
    print(f"Resource requirements  : {len(requirements):,}")

    requirements_by_task = grouped(requirements, "task_id")
    options_by_requirement = grouped(v35_candidates, "requirement_id")
    crew_lookup = lookup(crews, "crew_id")
    machine_lookup = lookup(machines, "machine_id")
    equipment_lookup = lookup(equipment, "equipment_id")
    material_lookup = lookup(materials, "inventory_id")

    crew_availability = build_availability_index(
        crew_availability_df,
        "crew_id",
        "shift_start",
        "shift_end",
    )
    machine_availability = build_availability_index(
        machine_availability_df,
        "machine_id",
        "available_from",
        "available_to",
    )

    print("\nExpanding exact-time-safe alternatives...")
    output_rows = []
    missing_option_slots = []
    slot_count = 0

    for window in feasible_windows.to_dict(orient="records"):
        candidate_id = clean(window.get("candidate_window_id"))
        task_id = clean(window.get("task_id"))
        start = number(window.get("window_start_minute_week"))
        end = number(window.get("window_end_minute_week"))
        if start is None or end is None:
            raise RuntimeError(f"Invalid timing for candidate {candidate_id}")

        for requirement in requirements_by_task.get(task_id, []):
            if not to_bool(requirement.get("mandatory"), default=True):
                continue

            requirement_id = clean(requirement.get("requirement_id"))
            slot_count += 1
            safe_options = []

            for option in options_by_requirement.get(requirement_id, []):
                feasible, repositioning, exact_status = evaluate_option(
                    option,
                    requirement,
                    float(start),
                    float(end),
                    crew_lookup,
                    crew_availability,
                    machine_lookup,
                    machine_availability,
                    equipment_lookup,
                    material_lookup,
                )
                if not feasible:
                    continue

                safe_options.append(
                    {
                        "candidate_window_id": candidate_id,
                        "task_id": task_id,
                        "section_id": clean(window.get("section_id")),
                        "window_start_minute_week": float(start),
                        "window_end_minute_week": float(end),
                        "requirement_id": requirement_id,
                        "requirement_type": clean(requirement.get("requirement_type")),
                        "resource_category": clean(requirement.get("resource_category")),
                        "required_resource_code": clean(requirement.get("resource_code")),
                        "required_skill_code": clean(requirement.get("skill_code")),
                        "quantity_required": requirement.get("quantity_required"),
                        "resource_id": clean(option.get("resource_id")),
                        "resource_type": clean(option.get("resource_type")),
                        "base_station_code": clean(option.get("base_station_code")),
                        "travel_distance_proxy_km": option.get("travel_distance_proxy_km"),
                        "travel_minutes_proxy": option.get("travel_minutes_proxy"),
                        "v3_5_candidate_rank": option.get("candidate_rank"),
                        "v3_5_readiness_status": clean(option.get("readiness_status")),
                        "exact_time_status": exact_status,
                        "repositioning_required": bool(repositioning),
                        "data_origin": DATA_ORIGIN,
                        "integration_mode": INTEGRATION_MODE,
                        "is_prototype_derived": True,
                    }
                )

            safe_options.sort(
                key=lambda row: (
                    1 if row["repositioning_required"] else 0,
                    number(row["travel_minutes_proxy"], math.inf),
                    number(row["v3_5_candidate_rank"], math.inf),
                    row["resource_id"],
                )
            )

            for exact_rank, row in enumerate(safe_options, start=1):
                row["exact_time_option_rank"] = exact_rank
                output_rows.append(row)

            if not safe_options:
                missing_option_slots.append(
                    {
                        "candidate_window_id": candidate_id,
                        "task_id": task_id,
                        "requirement_id": requirement_id,
                        "requirement_type": clean(requirement.get("requirement_type")),
                    }
                )

    output = pd.DataFrame(output_rows)
    if output.empty:
        raise RuntimeError("No optimizer resource options were generated.")

    duplicate_rows = int(
        output.duplicated(
            subset=["candidate_window_id", "requirement_id", "resource_id"]
        ).sum()
    )
    if duplicate_rows:
        raise RuntimeError(f"Duplicate option rows detected: {duplicate_rows}")

    if missing_option_slots:
        raise RuntimeError(
            "A V3.11-feasible window has a mandatory requirement with no "
            "exact-time-safe resource option. This should not happen.\n"
            f"Missing slots: {len(missing_option_slots):,}\n"
            f"Examples: {missing_option_slots[:10]}"
        )

    option_counts = output.groupby(
        ["candidate_window_id", "requirement_id"]
    ).size()

    output.to_csv(OUTPUT_FILE, index=False)

    category_counts = output["resource_category"].value_counts().sort_index()
    report = [
        "=" * 72,
        "TrackEase V3.12A Exact-Time Resource Option Expansion Report",
        "=" * 72,
        "",
        f"V3.11-feasible windows        : {len(feasible_windows):,}",
        f"Mandatory requirement slots   : {slot_count:,}",
        f"Exact-time resource options   : {len(output):,}",
        f"Missing mandatory option slots: {len(missing_option_slots):,}",
        f"Duplicate option rows         : {duplicate_rows:,}",
        f"Average options per slot      : {option_counts.mean():.2f}",
        f"Minimum options per slot      : {int(option_counts.min()):,}",
        f"Maximum options per slot      : {int(option_counts.max()):,}",
        "",
        "OPTION ROWS BY RESOURCE CATEGORY",
        "-" * 72,
    ]
    for category, count in category_counts.items():
        report.append(f"{category:<30} {count:>10,}")
    report.extend(
        [
            "",
            "INTERPRETATION",
            "-" * 72,
            "Every option independently passes the exact window-time checks.",
            "Optimizer V3 may choose another safe option when one is booked.",
            "No safety, shift, qualification or material rule is relaxed.",
        ]
    )
    REPORT_FILE.write_text("\n".join(report), encoding="utf-8")

    print("\n" + "=" * 72)
    print("V3.12A RESOURCE OPTION EXPANSION COMPLETE")
    print("=" * 72)
    print(f"\nMandatory requirement slots : {slot_count:,}")
    print(f"Exact-time resource options : {len(output):,}")
    print(f"Average options per slot    : {option_counts.mean():.2f}")
    print(f"Missing option slots        : {len(missing_option_slots):,}")
    print(f"Duplicate option rows       : {duplicate_rows:,}")
    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")


if __name__ == "__main__":
    main()
