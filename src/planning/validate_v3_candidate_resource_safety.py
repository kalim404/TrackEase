"""
TrackEase V3.11 - Exact Resource-Time & Safety Feasibility

Purpose
-------
Apply candidate-window-specific resource and safety gates before Optimizer V3.

This stage consumes the exact V3.10 candidate windows and checks:
    - accepted train/goods conflict counts remain zero
    - section minimum-block rule
    - crew availability for the actual weekday / clock time
    - crew duty-limit compatibility
    - machine availability for the actual weekday / clock time
    - machine operating-duration compatibility
    - equipment readiness
    - material stock readiness
    - protection-crew / protection-equipment readiness
    - electrical-isolation support when required
    - S&T/disconnection support when required
    - task dependency sequencing feasibility
    - resource repositioning requirements
    - infrastructure-data review flags

Important boundary
------------------
This module validates whether a candidate window CAN be supported by at least
one compatible resource candidate. It does not yet solve simultaneous
competition between different maintenance tasks for the same crew/machine.
That exclusivity decision belongs to Resource-Aware Optimizer V3.

Long-distance resources remain allowed only as explicitly flagged
REPOSITIONING_REQUIRED candidates. Optimizer V3 must prove that the movement
can be scheduled without conflicting with another assignment.

Inputs
------
    data/processed/v3_candidate_block_windows.csv
    data/processed/v3_integrated_block_opportunities.csv
    data/processed/v3_shadow_block_opportunities.csv
    data/processed/v3_task_block_requirements.csv
    data/processed/v3_task_resource_requirements.csv
    data/processed/v3_resource_assignment_candidates.csv
    data/processed/v3_task_dependencies.csv
    data/processed/v3_crew_availability.csv
    data/processed/v3_crews.csv
    data/processed/v3_machine_availability.csv
    data/processed/v3_machines.csv
    data/processed/v3_equipment.csv
    data/processed/v3_material_inventory.csv
    data/processed/v3_section_constraints.csv

Outputs
-------
    data/processed/v3_candidate_resource_assignments.csv
    data/processed/v3_candidate_window_feasibility.csv
    data/processed/v3_candidate_window_rejections.csv
    data/processed/v3_task_feasible_window_summary.csv
    data/processed/v3_integrated_opportunity_feasibility.csv
    data/processed/v3_shadow_opportunity_feasibility.csv
    data/processed/v3_resource_safety_feasibility_report.txt

All generated resource/infrastructure information remains prototype-labelled.
TrackEase remains a decision-support system; human railway authorization is
required before execution.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import math

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

CANDIDATES_FILE = PROCESSED_DIR / "v3_candidate_block_windows.csv"
INTEGRATED_FILE = (
    PROCESSED_DIR / "v3_integrated_block_opportunities.csv"
)
SHADOW_FILE = (
    PROCESSED_DIR / "v3_shadow_block_opportunities.csv"
)

BLOCK_REQUIREMENTS_FILE = (
    PROCESSED_DIR / "v3_task_block_requirements.csv"
)
RESOURCE_REQUIREMENTS_FILE = (
    PROCESSED_DIR / "v3_task_resource_requirements.csv"
)
ASSIGNMENT_CANDIDATES_FILE = (
    PROCESSED_DIR / "v3_resource_assignment_candidates.csv"
)
DEPENDENCIES_FILE = (
    PROCESSED_DIR / "v3_task_dependencies.csv"
)

CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
CREW_AVAILABILITY_FILE = (
    PROCESSED_DIR / "v3_crew_availability.csv"
)
MACHINES_FILE = PROCESSED_DIR / "v3_machines.csv"
MACHINE_AVAILABILITY_FILE = (
    PROCESSED_DIR / "v3_machine_availability.csv"
)
EQUIPMENT_FILE = PROCESSED_DIR / "v3_equipment.csv"
MATERIAL_FILE = PROCESSED_DIR / "v3_material_inventory.csv"

SECTION_CONSTRAINTS_FILE = (
    PROCESSED_DIR / "v3_section_constraints.csv"
)

ASSIGNMENTS_OUTPUT = (
    PROCESSED_DIR / "v3_candidate_resource_assignments.csv"
)
FEASIBILITY_OUTPUT = (
    PROCESSED_DIR / "v3_candidate_window_feasibility.csv"
)
REJECTIONS_OUTPUT = (
    PROCESSED_DIR / "v3_candidate_window_rejections.csv"
)
TASK_SUMMARY_OUTPUT = (
    PROCESSED_DIR / "v3_task_feasible_window_summary.csv"
)
INTEGRATED_FEASIBILITY_OUTPUT = (
    PROCESSED_DIR / "v3_integrated_opportunity_feasibility.csv"
)
SHADOW_FEASIBILITY_OUTPUT = (
    PROCESSED_DIR / "v3_shadow_opportunity_feasibility.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_resource_safety_feasibility_report.txt"
)


# ---------------------------------------------------------------------------
# Constants / provenance
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

WEEKDAY_TO_INDEX = {
    "MON": 0,
    "MONDAY": 0,
    "TUE": 1,
    "TUES": 1,
    "TUESDAY": 1,
    "WED": 2,
    "WEDNESDAY": 2,
    "THU": 3,
    "THUR": 3,
    "THURSDAY": 3,
    "FRI": 4,
    "FRIDAY": 4,
    "SAT": 5,
    "SATURDAY": 5,
    "SUN": 6,
    "SUNDAY": 6,
}

DATA_ORIGIN = "TRACKEASE_V3_EXACT_RESOURCE_SAFETY_GATE"
INTEGRATION_MODE = "PROTOTYPE_CANDIDATE_WINDOW_FEASIBILITY_ENGINE"


# ---------------------------------------------------------------------------
# Generic helpers
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


def safe_float(value: object) -> float | None:
    if pd.isna(value):
        return None

    try:
        result = float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if not math.isfinite(
        result
    ):
        return None

    return result


def hhmm_to_minutes(
    value: object,
    end_of_day: bool = False,
) -> int | None:
    text = clean_text(
        value
    )

    if not text or ":" not in text:
        return None

    try:
        hour, minute = map(
            int,
            text.split(":")[:2],
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if not (
        0 <= hour <= 23
        and 0 <= minute <= 59
    ):
        return None

    # Treat 23:59 as the practical end of the day for prototype availability
    # intervals, avoiding an artificial one-minute gap at midnight.
    if (
        end_of_day
        and hour == 23
        and minute == 59
    ):
        return MINUTES_PER_DAY

    return (
        hour * 60
        + minute
    )


def weekday_index(
    value: object,
) -> int | None:
    text = clean_text(
        value
    ).upper()

    if text in WEEKDAY_TO_INDEX:
        return WEEKDAY_TO_INDEX[
            text
        ]

    return None


def require_inputs() -> None:
    required = [
        CANDIDATES_FILE,
        INTEGRATED_FILE,
        SHADOW_FILE,
        BLOCK_REQUIREMENTS_FILE,
        RESOURCE_REQUIREMENTS_FILE,
        ASSIGNMENT_CANDIDATES_FILE,
        DEPENDENCIES_FILE,
        CREWS_FILE,
        CREW_AVAILABILITY_FILE,
        MACHINES_FILE,
        MACHINE_AVAILABILITY_FILE,
        EQUIPMENT_FILE,
        MATERIAL_FILE,
        SECTION_CONSTRAINTS_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.11 input files are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


# ---------------------------------------------------------------------------
# Availability interval utilities
# ---------------------------------------------------------------------------

def merge_intervals(
    intervals: list[
        tuple[float, float]
    ],
) -> list[
    tuple[float, float]
]:

    if not intervals:
        return []

    ordered = sorted(
        intervals
    )

    merged = [
        [
            ordered[0][0],
            ordered[0][1],
        ]
    ]

    for start, end in ordered[1:]:
        last = merged[-1]

        if start <= last[1]:
            last[1] = max(
                last[1],
                end,
            )
        else:
            merged.append(
                [
                    start,
                    end,
                ]
            )

    return [
        (
            float(start),
            float(end),
        )
        for start, end in merged
    ]


def interval_is_covered(
    intervals: list[
        tuple[float, float]
    ],
    start: float,
    end: float,
) -> bool:

    for interval_start, interval_end in intervals:
        if (
            interval_start
            <= start
            and interval_end
            >= end
        ):
            return True

    return False


def build_weekly_availability_index(
    availability: pd.DataFrame,
    resource_id_column: str,
    start_column: str,
    end_column: str,
) -> dict[
    str,
    list[
        tuple[float, float]
    ],
]:

    raw: dict[
        str,
        list[
            tuple[float, float]
        ],
    ] = defaultdict(
        list
    )

    for row in availability.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        if not bool_value(
            row_dict.get(
                "available"
            )
        ):
            continue

        resource_id = clean_text(
            row_dict.get(
                resource_id_column
            )
        )

        day_index = weekday_index(
            row_dict.get(
                "weekday"
            )
        )

        start_minute = hhmm_to_minutes(
            row_dict.get(
                start_column
            )
        )

        end_minute = hhmm_to_minutes(
            row_dict.get(
                end_column
            ),
            end_of_day=True,
        )

        if (
            not resource_id
            or day_index is None
            or start_minute is None
            or end_minute is None
        ):
            continue

        start = (
            day_index
            * MINUTES_PER_DAY
            + start_minute
        )

        end = (
            day_index
            * MINUTES_PER_DAY
            + end_minute
        )

        if end <= start:
            end += MINUTES_PER_DAY

        # Copies around the week boundary let Sunday-night availability cover
        # an early-Monday candidate and vice versa.
        for shift in (
            -MINUTES_PER_WEEK,
            0,
            MINUTES_PER_WEEK,
        ):
            raw[
                resource_id
            ].append(
                (
                    start + shift,
                    end + shift,
                )
            )

    return {
        resource_id:
            merge_intervals(
                intervals
            )
        for (
            resource_id,
            intervals
        ) in raw.items()
    }


# ---------------------------------------------------------------------------
# Resource indexes
# ---------------------------------------------------------------------------

def dataframe_lookup(
    dataframe: pd.DataFrame,
    key_column: str,
) -> dict[
    str,
    dict,
]:

    result = {}

    for row in dataframe.to_dict(
        orient="records"
    ):
        key = clean_text(
            row.get(
                key_column
            )
        )

        if key:
            result[
                key
            ] = row

    return result


def grouped_records(
    dataframe: pd.DataFrame,
    key_column: str,
) -> dict[
    str,
    list[
        dict
    ],
]:

    result: dict[
        str,
        list[
            dict
        ],
    ] = defaultdict(
        list
    )

    for row in dataframe.to_dict(
        orient="records"
    ):
        key = clean_text(
            row.get(
                key_column
            )
        )

        if key:
            result[
                key
            ].append(
                row
            )

    return dict(
        result
    )


# ---------------------------------------------------------------------------
# Exact resource-time checks
# ---------------------------------------------------------------------------

def evaluate_crew_candidate(
    assignment: dict,
    crew_lookup: dict[
        str,
        dict
    ],
    availability_index: dict[
        str,
        list[
            tuple[float, float]
        ]
    ],
    window_start: float,
    window_end: float,
) -> tuple[
    bool,
    bool,
    str,
]:

    crew_id = clean_text(
        assignment.get(
            "resource_id"
        )
    )

    crew = crew_lookup.get(
        crew_id
    )

    if crew is None:
        return (
            False,
            False,
            "CREW_MASTER_RECORD_MISSING",
        )

    if clean_text(
        crew.get(
            "status"
        )
    ).upper() != "AVAILABLE":
        return (
            False,
            False,
            "CREW_NOT_AVAILABLE_IN_MASTER",
        )

    intervals = availability_index.get(
        crew_id,
        [],
    )

    block_minutes = (
        window_end
        - window_start
    )

    max_work = safe_float(
        crew.get(
            "max_work_minutes_per_shift"
        )
    )

    if max_work is None:
        max_work = 480.0

    if block_minutes > max_work:
        return (
            False,
            False,
            "BLOCK_EXCEEDS_CREW_SHIFT_WORK_LIMIT",
        )

    if not interval_is_covered(
        intervals,
        window_start,
        window_end,
    ):
        return (
            False,
            False,
            "CREW_SHIFT_DOES_NOT_COVER_BLOCK",
        )

    travel = safe_float(
        assignment.get(
            "travel_minutes_proxy"
        )
    )

    if travel is None:
        travel = 0.0

    same_shift_mobilization = (
        interval_is_covered(
            intervals,
            window_start - travel,
            window_end,
        )
        and (
            travel
            + block_minutes
            <= max_work
        )
    )

    already_flagged_reposition = (
        clean_text(
            assignment.get(
                "readiness_status"
            )
        ).upper()
        == "REPOSITIONING_REQUIRED"
    )

    if (
        same_shift_mobilization
        and not already_flagged_reposition
    ):
        return (
            True,
            False,
            "EXACT_CREW_TIME_READY",
        )

    # The crew can cover the actual maintenance block, but its movement to the
    # worksite must be planned explicitly by the optimizer.
    return (
        True,
        True,
        "CREW_BLOCK_COVERED_REPOSITIONING_REQUIRED",
    )


def evaluate_machine_candidate(
    assignment: dict,
    machine_lookup: dict[
        str,
        dict
    ],
    availability_index: dict[
        str,
        list[
            tuple[float, float]
        ]
    ],
    window_start: float,
    window_end: float,
) -> tuple[
    bool,
    bool,
    str,
]:

    machine_id = clean_text(
        assignment.get(
            "resource_id"
        )
    )

    machine = machine_lookup.get(
        machine_id
    )

    if machine is None:
        return (
            False,
            False,
            "MACHINE_MASTER_RECORD_MISSING",
        )

    if clean_text(
        machine.get(
            "status"
        )
    ).upper() != "AVAILABLE":
        return (
            False,
            False,
            "MACHINE_NOT_AVAILABLE_IN_MASTER",
        )

    intervals = availability_index.get(
        machine_id,
        [],
    )

    block_minutes = (
        window_end
        - window_start
    )

    max_operating = safe_float(
        machine.get(
            "max_operating_minutes_per_day"
        )
    )

    if max_operating is None:
        max_operating = 600.0

    if block_minutes > max_operating:
        return (
            False,
            False,
            "BLOCK_EXCEEDS_MACHINE_DAILY_LIMIT",
        )

    if not interval_is_covered(
        intervals,
        window_start,
        window_end,
    ):
        return (
            False,
            False,
            "MACHINE_NOT_AVAILABLE_FOR_BLOCK_TIME",
        )

    travel = safe_float(
        assignment.get(
            "travel_minutes_proxy"
        )
    )

    if travel is None:
        travel = 0.0

    same_period_mobilization = (
        interval_is_covered(
            intervals,
            window_start - travel,
            window_end,
        )
        and (
            travel
            + block_minutes
            <= max_operating
        )
    )

    already_flagged_reposition = (
        clean_text(
            assignment.get(
                "readiness_status"
            )
        ).upper()
        == "REPOSITIONING_REQUIRED"
    )

    if (
        same_period_mobilization
        and not already_flagged_reposition
    ):
        return (
            True,
            False,
            "EXACT_MACHINE_TIME_READY",
        )

    return (
        True,
        True,
        "MACHINE_BLOCK_COVERED_REPOSITIONING_REQUIRED",
    )


def evaluate_equipment_candidate(
    assignment: dict,
    equipment_lookup: dict[
        str,
        dict
    ],
) -> tuple[
    bool,
    bool,
    str,
]:

    equipment_id = clean_text(
        assignment.get(
            "resource_id"
        )
    )

    equipment = equipment_lookup.get(
        equipment_id
    )

    if equipment is None:
        return (
            False,
            False,
            "EQUIPMENT_MASTER_RECORD_MISSING",
        )

    if clean_text(
        equipment.get(
            "status"
        )
    ).upper() != "AVAILABLE":
        return (
            False,
            False,
            "EQUIPMENT_NOT_READY",
        )

    reposition = (
        clean_text(
            assignment.get(
                "readiness_status"
            )
        ).upper()
        == "REPOSITIONING_REQUIRED"
    )

    return (
        True,
        reposition,
        (
            "EQUIPMENT_REPOSITIONING_REQUIRED"
            if reposition
            else "EQUIPMENT_READY"
        ),
    )


def evaluate_material_candidate(
    assignment: dict,
    material_lookup: dict[
        str,
        dict
    ],
    requirement: dict,
) -> tuple[
    bool,
    bool,
    str,
]:

    inventory_id = clean_text(
        assignment.get(
            "resource_id"
        )
    )

    inventory = material_lookup.get(
        inventory_id
    )

    if inventory is None:
        return (
            False,
            False,
            "MATERIAL_INVENTORY_RECORD_MISSING",
        )

    available = safe_float(
        inventory.get(
            "quantity_available"
        )
    )

    required = safe_float(
        requirement.get(
            "quantity_required"
        )
    )

    if available is None:
        available = 0.0

    if required is None:
        required = 1.0

    if available < required:
        return (
            False,
            False,
            "INSUFFICIENT_MATERIAL_STOCK",
        )

    reposition = (
        clean_text(
            assignment.get(
                "readiness_status"
            )
        ).upper()
        == "REPOSITIONING_REQUIRED"
    )

    return (
        True,
        reposition,
        (
            "MATERIAL_DELIVERY_REPOSITIONING_REQUIRED"
            if reposition
            else "MATERIAL_READY"
        ),
    )


def evaluate_assignment_candidate(
    assignment: dict,
    requirement: dict,
    crew_lookup: dict[
        str,
        dict
    ],
    crew_availability_index: dict[
        str,
        list[
            tuple[float, float]
        ]
    ],
    machine_lookup: dict[
        str,
        dict
    ],
    machine_availability_index: dict[
        str,
        list[
            tuple[float, float]
        ]
    ],
    equipment_lookup: dict[
        str,
        dict
    ],
    material_lookup: dict[
        str,
        dict
    ],
    window_start: float,
    window_end: float,
) -> tuple[
    bool,
    bool,
    str,
]:

    category = clean_text(
        requirement.get(
            "resource_category"
        )
    ).upper()

    resource_type = clean_text(
        assignment.get(
            "resource_type"
        )
    ).upper()

    if (
        category == "CREW"
        or resource_type
        in {
            "CREW",
            "ISOLATION_SUPPORT_CREW",
        }
    ):
        return evaluate_crew_candidate(
            assignment,
            crew_lookup,
            crew_availability_index,
            window_start,
            window_end,
        )

    if category == "MACHINE":
        return evaluate_machine_candidate(
            assignment,
            machine_lookup,
            machine_availability_index,
            window_start,
            window_end,
        )

    if category == "EQUIPMENT":
        return evaluate_equipment_candidate(
            assignment,
            equipment_lookup,
        )

    if category == "MATERIAL":
        return evaluate_material_candidate(
            assignment,
            material_lookup,
            requirement,
        )

    if category == "OPERATIONAL_PREREQUISITE":
        # The V3.5 candidate layer maps power-isolation prerequisites to
        # qualified Electrical isolation-support crews.
        return evaluate_crew_candidate(
            assignment,
            crew_lookup,
            crew_availability_index,
            window_start,
            window_end,
        )

    return (
        False,
        False,
        "UNSUPPORTED_RESOURCE_CATEGORY",
    )


# ---------------------------------------------------------------------------
# Base candidate feasibility
# ---------------------------------------------------------------------------

def select_resource_for_requirement(
    window_id: str,
    task_id: str,
    requirement: dict,
    assignment_options: list[
        dict
    ],
    crew_lookup: dict[
        str,
        dict
    ],
    crew_availability_index: dict[
        str,
        list[
            tuple[float, float]
        ]
    ],
    machine_lookup: dict[
        str,
        dict
    ],
    machine_availability_index: dict[
        str,
        list[
            tuple[float, float]
        ]
    ],
    equipment_lookup: dict[
        str,
        dict
    ],
    material_lookup: dict[
        str,
        dict
    ],
    window_start: float,
    window_end: float,
) -> tuple[
    dict | None,
    list[str],
]:

    evaluations = []
    failure_reasons = []

    for assignment in assignment_options:
        (
            feasible,
            repositioning,
            exact_status,
        ) = evaluate_assignment_candidate(
            assignment,
            requirement,
            crew_lookup,
            crew_availability_index,
            machine_lookup,
            machine_availability_index,
            equipment_lookup,
            material_lookup,
            window_start,
            window_end,
        )

        if not feasible:
            failure_reasons.append(
                exact_status
            )
            continue

        travel = safe_float(
            assignment.get(
                "travel_minutes_proxy"
            )
        )

        if travel is None:
            travel = math.inf

        candidate_rank = safe_float(
            assignment.get(
                "candidate_rank"
            )
        )

        if candidate_rank is None:
            candidate_rank = 999.0

        evaluations.append(
            (
                1
                if repositioning
                else 0,
                travel,
                candidate_rank,
                clean_text(
                    assignment.get(
                        "resource_id"
                    )
                ),
                assignment,
                exact_status,
                repositioning,
            )
        )

    if not evaluations:
        return (
            None,
            sorted(
                set(
                    failure_reasons
                )
            ),
        )

    evaluations.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3],
        )
    )

    (
        _reposition_sort,
        _travel_sort,
        _rank_sort,
        _resource_sort,
        selected,
        exact_status,
        repositioning,
    ) = evaluations[0]

    output = {
        "candidate_window_id":
            window_id,

        "task_id":
            task_id,

        "requirement_id":
            clean_text(
                requirement.get(
                    "requirement_id"
                )
            ),

        "requirement_type":
            clean_text(
                requirement.get(
                    "requirement_type"
                )
            ),

        "resource_category":
            clean_text(
                requirement.get(
                    "resource_category"
                )
            ),

        "required_resource_code":
            clean_text(
                requirement.get(
                    "resource_code"
                )
            ),

        "required_skill_code":
            clean_text(
                requirement.get(
                    "skill_code"
                )
            ),

        "quantity_required":
            requirement.get(
                "quantity_required"
            ),

        "selected_resource_id":
            clean_text(
                selected.get(
                    "resource_id"
                )
            ),

        "selected_resource_type":
            clean_text(
                selected.get(
                    "resource_type"
                )
            ),

        "base_station_code":
            clean_text(
                selected.get(
                    "base_station_code"
                )
            ),

        "travel_distance_proxy_km":
            selected.get(
                "travel_distance_proxy_km"
            ),

        "travel_minutes_proxy":
            selected.get(
                "travel_minutes_proxy"
            ),

        "candidate_rank":
            selected.get(
                "candidate_rank"
            ),

        "exact_time_status":
            exact_status,

        "repositioning_required":
            bool(
                repositioning
            ),

        "assignment_status":
            (
                "EXACT_TIME_FEASIBLE_REPOSITIONING_REQUIRED"
                if repositioning
                else "EXACT_TIME_READY"
            ),

        "requires_optimizer_exclusivity_check":
            True,

        "data_origin":
            DATA_ORIGIN,

        "integration_mode":
            INTEGRATION_MODE,

        "is_prototype_derived":
            True,
    }

    return (
        output,
        [],
    )


def build_base_feasibility(
    candidates: pd.DataFrame,
    block_requirements: pd.DataFrame,
    resource_requirements: pd.DataFrame,
    assignment_candidates: pd.DataFrame,
    crews: pd.DataFrame,
    crew_availability: pd.DataFrame,
    machines: pd.DataFrame,
    machine_availability: pd.DataFrame,
    equipment: pd.DataFrame,
    materials: pd.DataFrame,
    section_constraints: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:

    block_lookup = dataframe_lookup(
        block_requirements,
        "task_id",
    )

    requirements_by_task = grouped_records(
        resource_requirements,
        "task_id",
    )

    assignments_by_requirement = grouped_records(
        assignment_candidates,
        "requirement_id",
    )

    crew_lookup = dataframe_lookup(
        crews,
        "crew_id",
    )

    machine_lookup = dataframe_lookup(
        machines,
        "machine_id",
    )

    equipment_lookup = dataframe_lookup(
        equipment,
        "equipment_id",
    )

    material_lookup = dataframe_lookup(
        materials,
        "inventory_id",
    )

    section_lookup = dataframe_lookup(
        section_constraints,
        "section_id",
    )

    crew_availability_index = (
        build_weekly_availability_index(
            crew_availability,
            "crew_id",
            "shift_start",
            "shift_end",
        )
    )

    machine_availability_index = (
        build_weekly_availability_index(
            machine_availability,
            "machine_id",
            "available_from",
            "available_to",
        )
    )

    feasibility_rows = []
    assignment_rows = []

    for candidate in candidates.to_dict(
        orient="records"
    ):
        window_id = clean_text(
            candidate.get(
                "candidate_window_id"
            )
        )

        task_id = clean_text(
            candidate.get(
                "task_id"
            )
        )

        section_id = clean_text(
            candidate.get(
                "section_id"
            )
        )

        window_start = safe_float(
            candidate.get(
                "window_start_minute_week"
            )
        )

        window_end = safe_float(
            candidate.get(
                "window_end_minute_week"
            )
        )

        if (
            window_start is None
            or window_end is None
        ):
            raise RuntimeError(
                f"Candidate {window_id} has invalid window timing."
            )

        task_block = block_lookup.get(
            task_id,
            {}
        )

        section = section_lookup.get(
            section_id,
            {}
        )

        rejection_reasons = []
        warning_reasons = []

        # ---------------------------------------------------------------
        # Hard operational safety gates
        # ---------------------------------------------------------------

        train_conflicts = safe_float(
            candidate.get(
                "exact_train_conflict_count"
            )
        )

        goods_conflicts = safe_float(
            candidate.get(
                "exact_goods_conflict_count"
            )
        )

        if (
            train_conflicts is not None
            and train_conflicts > 0
        ):
            rejection_reasons.append(
                "TRAIN_CONFLICT_PRESENT"
            )

        if (
            goods_conflicts is not None
            and goods_conflicts > 0
        ):
            rejection_reasons.append(
                "GOODS_CONFLICT_PRESENT"
            )

        required_block = safe_float(
            candidate.get(
                "required_block_minutes"
            )
        )

        source_window = safe_float(
            candidate.get(
                "source_safe_window_minutes"
            )
        )

        if (
            required_block is None
            or source_window is None
            or required_block
            > source_window
        ):
            rejection_reasons.append(
                "BLOCK_DURATION_DOES_NOT_FIT_WINDOW"
            )

        minimum_block = safe_float(
            section.get(
                "minimum_block_minutes"
            )
        )

        if minimum_block is None:
            minimum_block = 30.0

        if (
            required_block is not None
            and required_block
            < minimum_block
        ):
            rejection_reasons.append(
                "BLOCK_BELOW_SECTION_MINIMUM_DURATION"
            )

        # Physical track/electrification/signalling details are intentionally
        # UNKNOWN in the current source. This is a review flag, not a fabricated
        # pass/fail assumption.
        unknown_infrastructure_fields = []

        for field in [
            "physical_track_type",
            "electrification_status",
            "signalling_system",
        ]:
            value = clean_text(
                section.get(
                    field
                )
            ).upper()

            if (
                not value
                or value
                == "UNKNOWN_SOURCE_DATA"
            ):
                unknown_infrastructure_fields.append(
                    field
                )

        infrastructure_review_required = bool(
            unknown_infrastructure_fields
        )

        if infrastructure_review_required:
            warning_reasons.append(
                "PHYSICAL_INFRASTRUCTURE_REVIEW_REQUIRED"
            )

        # ---------------------------------------------------------------
        # Requirement-level exact resource checks
        # ---------------------------------------------------------------

        task_requirements = [
            requirement
            for requirement in requirements_by_task.get(
                task_id,
                []
            )
            if bool_value(
                requirement.get(
                    "mandatory"
                ),
                default=True,
            )
        ]

        selected_for_window = []
        failed_requirement_ids = []
        failed_requirement_reasons = []
        repositioning_count = 0

        for requirement in task_requirements:
            requirement_id = clean_text(
                requirement.get(
                    "requirement_id"
                )
            )

            selected, failures = (
                select_resource_for_requirement(
                    window_id,
                    task_id,
                    requirement,
                    assignments_by_requirement.get(
                        requirement_id,
                        [],
                    ),
                    crew_lookup,
                    crew_availability_index,
                    machine_lookup,
                    machine_availability_index,
                    equipment_lookup,
                    material_lookup,
                    window_start,
                    window_end,
                )
            )

            if selected is None:
                failed_requirement_ids.append(
                    requirement_id
                )

                failed_requirement_reasons.extend(
                    failures
                    or [
                        "NO_EXACT_TIME_RESOURCE_CANDIDATE",
                    ]
                )

                continue

            if bool_value(
                selected.get(
                    "repositioning_required"
                )
            ):
                repositioning_count += 1

            selected_for_window.append(
                selected
            )

        if failed_requirement_ids:
            rejection_reasons.append(
                "MANDATORY_RESOURCE_TIME_REQUIREMENT_FAILED"
            )

        # ---------------------------------------------------------------
        # Explicit safety-support checks
        # ---------------------------------------------------------------

        selected_requirement_types = {
            clean_text(
                row.get(
                    "requirement_type"
                )
            ).upper()
            for row in selected_for_window
        }

        selected_departments = {
            clean_text(
                requirement.get(
                    "department"
                )
            ).upper()
            for requirement in task_requirements
            if clean_text(
                requirement.get(
                    "requirement_id"
                )
            )
            in {
                clean_text(
                    row.get(
                        "requirement_id"
                    )
                )
                for row in selected_for_window
            }
        }

        if bool_value(
            task_block.get(
                "requires_protection_staff"
            )
        ):
            if "PROTECTION_CREW" not in selected_requirement_types:
                rejection_reasons.append(
                    "PROTECTION_CREW_NOT_TIME_READY"
                )

            if (
                "PROTECTION_EQUIPMENT"
                not in selected_requirement_types
            ):
                rejection_reasons.append(
                    "PROTECTION_EQUIPMENT_NOT_READY"
                )

        if bool_value(
            task_block.get(
                "requires_power_block"
            )
        ):
            if "POWER_ISOLATION" not in selected_requirement_types:
                rejection_reasons.append(
                    "POWER_ISOLATION_SUPPORT_NOT_TIME_READY"
                )

        if bool_value(
            task_block.get(
                "requires_disconnection"
            )
        ):
            has_signal_support = any(
                (
                    department == "S&T"
                    or "SIGNAL" in department
                    or "SMMS" in department
                )
                for department in selected_departments
            )

            if not has_signal_support:
                rejection_reasons.append(
                    "S_AND_T_DISCONNECTION_SUPPORT_NOT_READY"
                )

            warning_reasons.append(
                "AUTHORIZED_DISCONNECTION_CONFIRMATION_REQUIRED"
            )

        # Human approval / handback are lifecycle safety requirements and are
        # never auto-granted by this feasibility engine.
        warning_reasons.append(
            "HUMAN_BLOCK_AUTHORIZATION_REQUIRED"
        )

        warning_reasons.append(
            "TECHNICAL_HANDBACK_REQUIRED"
        )

        base_pass = (
            len(
                rejection_reasons
            )
            == 0
        )

        if base_pass:
            assignment_rows.extend(
                selected_for_window
            )

        feasibility_rows.append(
            {
                "candidate_window_id":
                    window_id,

                "task_id":
                    task_id,

                "section_id":
                    section_id,

                "window_start_minute_week":
                    window_start,

                "window_end_minute_week":
                    window_end,

                "window_start_label":
                    clean_text(
                        candidate.get(
                            "window_start_label"
                        )
                    ),

                "window_end_label":
                    clean_text(
                        candidate.get(
                            "window_end_label"
                        )
                    ),

                "required_block_minutes":
                    required_block,

                "mandatory_requirement_count":
                    len(
                        task_requirements
                    ),

                "time_ready_requirement_count":
                    len(
                        selected_for_window
                    ),

                "failed_requirement_count":
                    len(
                        failed_requirement_ids
                    ),

                "failed_requirement_ids":
                    "|".join(
                        failed_requirement_ids
                    ),

                "failed_requirement_reasons":
                    "|".join(
                        sorted(
                            set(
                                failed_requirement_reasons
                            )
                        )
                    ),

                "repositioning_requirement_count":
                    repositioning_count,

                "requires_resource_repositioning":
                    repositioning_count
                    > 0,

                "train_conflict_free":
                    (
                        train_conflicts is None
                        or train_conflicts == 0
                    ),

                "goods_conflict_free":
                    (
                        goods_conflicts is None
                        or goods_conflicts == 0
                    ),

                "duration_fit_passed":
                    (
                        required_block is not None
                        and source_window is not None
                        and required_block
                        <= source_window
                        and required_block
                        >= minimum_block
                    ),

                "protection_gate_passed":
                    (
                        not bool_value(
                            task_block.get(
                                "requires_protection_staff"
                            )
                        )
                        or (
                            "PROTECTION_CREW"
                            in selected_requirement_types
                            and
                            "PROTECTION_EQUIPMENT"
                            in selected_requirement_types
                        )
                    ),

                "power_isolation_gate_passed":
                    (
                        not bool_value(
                            task_block.get(
                                "requires_power_block"
                            )
                        )
                        or (
                            "POWER_ISOLATION"
                            in selected_requirement_types
                        )
                    ),

                "disconnection_support_gate_passed":
                    (
                        not bool_value(
                            task_block.get(
                                "requires_disconnection"
                            )
                        )
                        or any(
                            (
                                department == "S&T"
                                or "SIGNAL"
                                in department
                                or "SMMS"
                                in department
                            )
                            for department
                            in selected_departments
                        )
                    ),

                "infrastructure_review_required":
                    infrastructure_review_required,

                "unknown_infrastructure_fields":
                    "|".join(
                        unknown_infrastructure_fields
                    ),

                "base_resource_safety_passed":
                    base_pass,

                "base_rejection_reasons":
                    "|".join(
                        sorted(
                            set(
                                rejection_reasons
                            )
                        )
                    ),

                "review_flags":
                    "|".join(
                        sorted(
                            set(
                                warning_reasons
                            )
                        )
                    ),

                "human_authorization_required":
                    True,

                "technical_handback_required":
                    True,

                "requires_optimizer_exclusivity_check":
                    True,

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
            feasibility_rows
        ),
        pd.DataFrame(
            assignment_rows
        ),
    )


# ---------------------------------------------------------------------------
# Dependency gate
# ---------------------------------------------------------------------------

def apply_dependency_gate(
    feasibility: pd.DataFrame,
    dependencies: pd.DataFrame,
) -> pd.DataFrame:

    result = feasibility.copy()

    result[
        "dependency_gate_required"
    ] = False

    result[
        "dependency_gate_passed"
    ] = True

    result[
        "dependency_status"
    ] = "NO_PREDECESSOR"

    if dependencies.empty:
        result[
            "final_feasibility_status"
        ] = result.apply(
            final_status,
            axis=1,
        )

        return result

    predecessors_by_successor: dict[
        str,
        list[str]
    ] = defaultdict(
        list
    )

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
            predecessors_by_successor[
                successor
            ].append(
                predecessor
            )

    base_pass = result[
        result[
            "base_resource_safety_passed"
        ]
        .astype(bool)
    ]

    feasible_end_times_by_task: dict[
        str,
        list[float]
    ] = defaultdict(
        list
    )

    for row in base_pass.itertuples(
        index=False
    ):
        feasible_end_times_by_task[
            clean_text(
                row.task_id
            )
        ].append(
            float(
                row.window_end_minute_week
            )
        )

    for index, row in result.iterrows():
        task_id = clean_text(
            row[
                "task_id"
            ]
        )

        predecessors = predecessors_by_successor.get(
            task_id,
            [],
        )

        if not predecessors:
            continue

        result.at[
            index,
            "dependency_gate_required",
        ] = True

        candidate_start = float(
            row[
                "window_start_minute_week"
            ]
        )

        missing_or_late = []

        for predecessor in predecessors:
            predecessor_end_times = (
                feasible_end_times_by_task.get(
                    predecessor,
                    [],
                )
            )

            has_earlier_feasible_predecessor = any(
                end_time
                <= candidate_start
                for end_time
                in predecessor_end_times
            )

            if not has_earlier_feasible_predecessor:
                missing_or_late.append(
                    predecessor
                )

        if missing_or_late:
            result.at[
                index,
                "dependency_gate_passed",
            ] = False

            result.at[
                index,
                "dependency_status",
            ] = (
                "NO_EARLIER_FEASIBLE_PREDECESSOR:"
                + "|".join(
                    sorted(
                        missing_or_late
                    )
                )
            )
        else:
            result.at[
                index,
                "dependency_status",
            ] = (
                "EARLIER_FEASIBLE_PREDECESSOR_AVAILABLE"
            )

    result[
        "final_feasibility_status"
    ] = result.apply(
        final_status,
        axis=1,
    )

    return result


def final_status(
    row: pd.Series,
) -> str:

    if not bool_value(
        row.get(
            "base_resource_safety_passed"
        )
    ):
        return (
            "REJECTED_RESOURCE_OR_SAFETY_GATE"
        )

    if not bool_value(
        row.get(
            "dependency_gate_passed"
        ),
        default=True,
    ):
        return (
            "REJECTED_DEPENDENCY_SEQUENCE"
        )

    if bool_value(
        row.get(
            "requires_resource_repositioning"
        )
    ):
        return (
            "FEASIBLE_REPOSITIONING_REQUIRED"
        )

    return "FEASIBLE_READY_FOR_OPTIMIZER"


# ---------------------------------------------------------------------------
# Final assignment filtering
# ---------------------------------------------------------------------------

def filter_assignments_for_final_windows(
    assignments: pd.DataFrame,
    feasibility: pd.DataFrame,
) -> pd.DataFrame:

    if assignments.empty:
        return assignments

    accepted_window_ids = set(
        feasibility.loc[
            feasibility[
                "final_feasibility_status"
            ].isin(
                [
                    "FEASIBLE_READY_FOR_OPTIMIZER",
                    "FEASIBLE_REPOSITIONING_REQUIRED",
                ]
            ),
            "candidate_window_id",
        ].astype(str)
    )

    return (
        assignments[
            assignments[
                "candidate_window_id"
            ]
            .astype(str)
            .isin(
                accepted_window_ids
            )
        ]
        .reset_index(
            drop=True
        )
    )


# ---------------------------------------------------------------------------
# Task summaries
# ---------------------------------------------------------------------------

def build_task_summary(
    candidates: pd.DataFrame,
    feasibility: pd.DataFrame,
) -> pd.DataFrame:

    candidate_counts = (
        candidates.groupby(
            "task_id"
        )
        .size()
        .rename(
            "input_candidate_windows"
        )
    )

    feasible = feasibility[
        feasibility[
            "final_feasibility_status"
        ].isin(
            [
                "FEASIBLE_READY_FOR_OPTIMIZER",
                "FEASIBLE_REPOSITIONING_REQUIRED",
            ]
        )
    ].copy()

    feasible_counts = (
        feasible.groupby(
            "task_id"
        )
        .size()
        .rename(
            "feasible_candidate_windows"
        )
    )

    ready_counts = (
        feasible[
            feasible[
                "final_feasibility_status"
            ]
            .eq(
                "FEASIBLE_READY_FOR_OPTIMIZER"
            )
        ]
        .groupby(
            "task_id"
        )
        .size()
        .rename(
            "ready_candidate_windows"
        )
    )

    reposition_counts = (
        feasible[
            feasible[
                "final_feasibility_status"
            ]
            .eq(
                "FEASIBLE_REPOSITIONING_REQUIRED"
            )
        ]
        .groupby(
            "task_id"
        )
        .size()
        .rename(
            "repositioning_candidate_windows"
        )
    )

    rejected = feasibility[
        ~feasibility[
            "final_feasibility_status"
        ].isin(
            [
                "FEASIBLE_READY_FOR_OPTIMIZER",
                "FEASIBLE_REPOSITIONING_REQUIRED",
            ]
        )
    ]

    rejection_reasons = (
        rejected.groupby(
            "task_id"
        )[
            "final_feasibility_status"
        ]
        .apply(
            lambda values:
                "|".join(
                    sorted(
                        set(
                            values.astype(str)
                        )
                    )
                )
        )
        .rename(
            "rejection_statuses"
        )
    )

    summary = (
        candidate_counts.to_frame()
        .join(
            feasible_counts,
            how="left",
        )
        .join(
            ready_counts,
            how="left",
        )
        .join(
            reposition_counts,
            how="left",
        )
        .join(
            rejection_reasons,
            how="left",
        )
        .fillna(
            {
                "feasible_candidate_windows": 0,
                "ready_candidate_windows": 0,
                "repositioning_candidate_windows": 0,
                "rejection_statuses": "",
            }
        )
        .reset_index()
    )

    for column in [
        "input_candidate_windows",
        "feasible_candidate_windows",
        "ready_candidate_windows",
        "repositioning_candidate_windows",
    ]:
        summary[
            column
        ] = summary[
            column
        ].astype(int)

    summary[
        "has_feasible_window"
    ] = (
        summary[
            "feasible_candidate_windows"
        ]
        > 0
    )

    summary[
        "task_feasibility_status"
    ] = summary.apply(
        lambda row:
            (
                "READY_FOR_OPTIMIZER"
                if row[
                    "ready_candidate_windows"
                ]
                > 0
                else (
                    "REPOSITIONING_REQUIRED"
                    if row[
                        "repositioning_candidate_windows"
                    ]
                    > 0
                    else "NO_FEASIBLE_V3_11_WINDOW"
                )
            ),
        axis=1,
    )

    summary[
        "data_origin"
    ] = DATA_ORIGIN

    summary[
        "integration_mode"
    ] = INTEGRATION_MODE

    return summary


# ---------------------------------------------------------------------------
# Integrated / shadow opportunity gates
# ---------------------------------------------------------------------------

def validate_integrated_opportunities(
    integrated: pd.DataFrame,
    feasibility: pd.DataFrame,
) -> pd.DataFrame:

    if integrated.empty:
        return pd.DataFrame(
            columns=[
                "integrated_opportunity_id",
                "integrated_feasibility_status",
            ]
        )

    accepted = feasibility[
        feasibility[
            "final_feasibility_status"
        ].isin(
            [
                "FEASIBLE_READY_FOR_OPTIMIZER",
                "FEASIBLE_REPOSITIONING_REQUIRED",
            ]
        )
    ].copy()

    starts_by_task: dict[
        str,
        list[
            tuple[
                float,
                float,
                str,
            ]
        ]
    ] = defaultdict(
        list
    )

    for row in accepted.itertuples(
        index=False
    ):
        starts_by_task[
            clean_text(
                row.task_id
            )
        ].append(
            (
                float(
                    row.window_start_minute_week
                ),
                float(
                    row.window_end_minute_week
                ),
                clean_text(
                    row.final_feasibility_status
                ),
            )
        )

    rows = []

    for opportunity in integrated.to_dict(
        orient="records"
    ):
        task_ids = [
            task_id
            for task_id in clean_text(
                opportunity.get(
                    "task_ids"
                )
            ).split("|")
            if task_id
        ]

        group_start = safe_float(
            opportunity.get(
                "window_start_minute_week"
            )
        )

        group_end = safe_float(
            opportunity.get(
                "window_end_minute_week"
            )
        )

        member_ready = []
        member_repositioning = []

        if (
            group_start is None
            or group_end is None
        ):
            member_ready = [
                False
                for _ in task_ids
            ]
        else:
            for task_id in task_ids:
                options = starts_by_task.get(
                    task_id,
                    [],
                )

                matching = [
                    option
                    for option in options
                    if (
                        option[0]
                        >= group_start
                        and option[1]
                        <= group_end
                    )
                ]

                member_ready.append(
                    bool(
                        matching
                    )
                )

                member_repositioning.append(
                    bool(
                        matching
                        and all(
                            option[2]
                            == "FEASIBLE_REPOSITIONING_REQUIRED"
                            for option
                            in matching
                        )
                    )
                )

        all_members_ready = (
            bool(
                task_ids
            )
            and all(
                member_ready
            )
        )

        any_repositioning = any(
            member_repositioning
        )

        if all_members_ready:
            status = (
                "READY_FOR_OPTIMIZER_REPOSITIONING_REQUIRED"
                if any_repositioning
                else "READY_FOR_OPTIMIZER"
            )
        else:
            status = (
                "REJECTED_MEMBER_TASK_NOT_TIME_FEASIBLE"
            )

        output = dict(
            opportunity
        )

        output[
            "member_task_time_gate_passed"
        ] = all_members_ready

        output[
            "member_repositioning_required"
        ] = any_repositioning

        output[
            "integrated_feasibility_status"
        ] = status

        output[
            "requires_group_resource_exclusivity_check"
        ] = True

        output[
            "data_origin_v3_11"
        ] = DATA_ORIGIN

        output[
            "integration_mode_v3_11"
        ] = INTEGRATION_MODE

        rows.append(
            output
        )

    return pd.DataFrame(
        rows
    )


def validate_shadow_opportunities(
    shadow: pd.DataFrame,
    feasibility: pd.DataFrame,
) -> pd.DataFrame:

    if shadow.empty:
        return pd.DataFrame(
            columns=[
                "shadow_opportunity_id",
                "shadow_feasibility_status",
            ]
        )

    status_lookup = (
        feasibility.set_index(
            "candidate_window_id"
        )[
            "final_feasibility_status"
        ]
        .astype(str)
        .to_dict()
    )

    accepted_statuses = {
        "FEASIBLE_READY_FOR_OPTIMIZER",
        "FEASIBLE_REPOSITIONING_REQUIRED",
    }

    rows = []

    for opportunity in shadow.to_dict(
        orient="records"
    ):
        host_id = clean_text(
            opportunity.get(
                "host_candidate_window_id"
            )
        )

        shadow_id = clean_text(
            opportunity.get(
                "shadow_candidate_window_id"
            )
        )

        host_status = status_lookup.get(
            host_id,
            "NOT_FOUND",
        )

        shadow_status = status_lookup.get(
            shadow_id,
            "NOT_FOUND",
        )

        host_pass = (
            host_status
            in accepted_statuses
        )

        shadow_pass = (
            shadow_status
            in accepted_statuses
        )

        repositioning = (
            host_status
            == "FEASIBLE_REPOSITIONING_REQUIRED"
            or shadow_status
            == "FEASIBLE_REPOSITIONING_REQUIRED"
        )

        if (
            host_pass
            and shadow_pass
        ):
            status = (
                "READY_FOR_OPTIMIZER_REPOSITIONING_REQUIRED"
                if repositioning
                else "READY_FOR_OPTIMIZER"
            )
        else:
            status = (
                "REJECTED_MEMBER_WINDOW_NOT_TIME_FEASIBLE"
            )

        output = dict(
            opportunity
        )

        output[
            "host_v3_11_status"
        ] = host_status

        output[
            "shadow_v3_11_status"
        ] = shadow_status

        output[
            "shadow_feasibility_status"
        ] = status

        output[
            "requires_pair_resource_exclusivity_check"
        ] = True

        output[
            "data_origin_v3_11"
        ] = DATA_ORIGIN

        output[
            "integration_mode_v3_11"
        ] = INTEGRATION_MODE

        rows.append(
            output
        )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Validation / report
# ---------------------------------------------------------------------------

def validate_outputs(
    candidates: pd.DataFrame,
    feasibility: pd.DataFrame,
    assignments: pd.DataFrame,
    task_summary: pd.DataFrame,
) -> dict[
    str,
    int
]:

    accepted_statuses = [
        "FEASIBLE_READY_FOR_OPTIMIZER",
        "FEASIBLE_REPOSITIONING_REQUIRED",
    ]

    accepted = feasibility[
        feasibility[
            "final_feasibility_status"
        ].isin(
            accepted_statuses
        )
    ]

    checks = {
        "input_candidate_windows":
            len(
                candidates
            ),

        "feasibility_rows":
            len(
                feasibility
            ),

        "accepted_windows":
            len(
                accepted
            ),

        "ready_windows":
            int(
                (
                    feasibility[
                        "final_feasibility_status"
                    ]
                    == "FEASIBLE_READY_FOR_OPTIMIZER"
                )
                .sum()
            ),

        "repositioning_windows":
            int(
                (
                    feasibility[
                        "final_feasibility_status"
                    ]
                    == "FEASIBLE_REPOSITIONING_REQUIRED"
                )
                .sum()
            ),

        "rejected_windows":
            int(
                (
                    ~feasibility[
                        "final_feasibility_status"
                    ]
                    .isin(
                        accepted_statuses
                    )
                )
                .sum()
            ),

        "tasks_with_feasible_window":
            int(
                task_summary[
                    "has_feasible_window"
                ]
                .astype(bool)
                .sum()
            ),

        "duplicate_feasibility_ids":
            int(
                feasibility[
                    "candidate_window_id"
                ]
                .duplicated()
                .sum()
            ),

        "missing_feasibility_rows":
            int(
                (
                    ~candidates[
                        "candidate_window_id"
                    ]
                    .astype(str)
                    .isin(
                        feasibility[
                            "candidate_window_id"
                        ]
                        .astype(str)
                    )
                )
                .sum()
            ),

        "accepted_train_conflicts":
            int(
                (
                    accepted[
                        "train_conflict_free"
                    ]
                    .astype(bool)
                    == False  # noqa: E712
                )
                .sum()
            ),

        "accepted_goods_conflicts":
            int(
                (
                    accepted[
                        "goods_conflict_free"
                    ]
                    .astype(bool)
                    == False  # noqa: E712
                )
                .sum()
            ),

        "accepted_resource_failures":
            int(
                (
                    accepted[
                        "failed_requirement_count"
                    ]
                    > 0
                )
                .sum()
            ),

        "assignment_rows":
            len(
                assignments
            ),
    }

    if (
        len(
            feasibility
        )
        != len(
            candidates
        )
    ):
        raise RuntimeError(
            "V3.11 must produce exactly one feasibility row per candidate."
        )

    hard_failures = [
        "duplicate_feasibility_ids",
        "missing_feasibility_rows",
        "accepted_train_conflicts",
        "accepted_goods_conflicts",
        "accepted_resource_failures",
    ]

    if sum(
        checks[
            key
        ]
        for key in hard_failures
    ):
        raise RuntimeError(
            "V3.11 output integrity validation failed."
        )

    return checks


def write_report(
    checks: dict[
        str,
        int
    ],
    feasibility: pd.DataFrame,
    task_summary: pd.DataFrame,
    integrated_feasibility: pd.DataFrame,
    shadow_feasibility: pd.DataFrame,
) -> None:

    status_counts = (
        feasibility[
            "final_feasibility_status"
        ]
        .value_counts()
        .sort_index()
    )

    base_rejections = (
        feasibility.loc[
            ~feasibility[
                "base_resource_safety_passed"
            ]
            .astype(bool),
            "base_rejection_reasons",
        ]
        .fillna("")
        .astype(str)
        .str.split("|")
        .explode()
    )

    base_rejections = (
        base_rejections[
            base_rejections
            .str.len()
            > 0
        ]
        .value_counts()
    )

    task_status_counts = (
        task_summary[
            "task_feasibility_status"
        ]
        .value_counts()
        .sort_index()
    )

    integrated_ready = (
        int(
            integrated_feasibility[
                "integrated_feasibility_status"
            ]
            .astype(str)
            .str.startswith(
                "READY_FOR_OPTIMIZER"
            )
            .sum()
        )
        if (
            not integrated_feasibility.empty
            and
            "integrated_feasibility_status"
            in integrated_feasibility.columns
        )
        else 0
    )

    shadow_ready = (
        int(
            shadow_feasibility[
                "shadow_feasibility_status"
            ]
            .astype(str)
            .str.startswith(
                "READY_FOR_OPTIMIZER"
            )
            .sum()
        )
        if (
            not shadow_feasibility.empty
            and
            "shadow_feasibility_status"
            in shadow_feasibility.columns
        )
        else 0
    )

    lines = [
        "=" * 72,
        "TrackEase V3.11 Exact Resource-Time & Safety Feasibility Report",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Input candidate windows          : {checks['input_candidate_windows']:,}",
        f"Feasible windows                 : {checks['accepted_windows']:,}",
        f"  Ready without repositioning    : {checks['ready_windows']:,}",
        f"  Repositioning required         : {checks['repositioning_windows']:,}",
        f"Rejected windows                 : {checks['rejected_windows']:,}",
        f"Tasks with >=1 feasible window   : {checks['tasks_with_feasible_window']:,}",
        f"Selected requirement assignments : {checks['assignment_rows']:,}",
        f"Integrated opportunities ready   : {integrated_ready:,}",
        f"Shadow opportunities ready       : {shadow_ready:,}",
        "",
        "WINDOW STATUS",
        "-" * 72,
    ]

    for status, count in status_counts.items():
        lines.append(
            f"{status:<46} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "TASK STATUS",
            "-" * 72,
        ]
    )

    for status, count in task_status_counts.items():
        lines.append(
            f"{status:<46} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "BASE REJECTION REASONS",
            "-" * 72,
        ]
    )

    if base_rejections.empty:
        lines.append(
            "None"
        )
    else:
        for reason, count in base_rejections.items():
            lines.append(
                f"{reason:<46} {count:>10,}"
            )

    lines.extend(
        [
            "",
            "INTEGRITY / HARD SAFETY",
            "-" * 72,
            (
                "Duplicate feasibility IDs        : "
                f"{checks['duplicate_feasibility_ids']:,}"
            ),
            (
                "Missing feasibility rows         : "
                f"{checks['missing_feasibility_rows']:,}"
            ),
            (
                "Accepted train conflicts         : "
                f"{checks['accepted_train_conflicts']:,}"
            ),
            (
                "Accepted goods conflicts         : "
                f"{checks['accepted_goods_conflicts']:,}"
            ),
            (
                "Accepted mandatory resource fail : "
                f"{checks['accepted_resource_failures']:,}"
            ),
            "",
            "IMPORTANT BOUNDARIES",
            "-" * 72,
            (
                "A V3.11 feasible window has at least one compatible candidate "
                "for every mandatory resource requirement at that actual block "
                "time."
            ),
            (
                "REPOSITIONING_REQUIRED means the resource can cover the block "
                "but its movement to the worksite must be explicitly scheduled "
                "by Optimizer V3."
            ),
            (
                "Simultaneous competition between different tasks for the same "
                "crew, machine or equipment is intentionally deferred to "
                "Resource-Aware Optimizer V3."
            ),
            (
                "Physical track/electrification/signalling details unavailable "
                "from source data remain explicit review flags; TrackEase does "
                "not fabricate them."
            ),
            (
                "Human authorization, disconnection confirmation, testing and "
                "technical handback remain mandatory lifecycle gates."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Feed only V3.11-feasible windows and their candidate resource "
                "assignments into Resource-Aware Optimizer V3."
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
        "TrackEase V3.11 - Exact Resource-Time & Safety Feasibility"
    )
    print("=" * 72)

    require_inputs()

    print(
        "\nLoading candidate windows and V3 resource/safety layers..."
    )

    candidates = pd.read_csv(
        CANDIDATES_FILE,
        low_memory=False,
    )

    integrated = pd.read_csv(
        INTEGRATED_FILE,
        low_memory=False,
    )

    shadow = pd.read_csv(
        SHADOW_FILE,
        low_memory=False,
    )

    block_requirements = pd.read_csv(
        BLOCK_REQUIREMENTS_FILE,
        low_memory=False,
    )

    resource_requirements = pd.read_csv(
        RESOURCE_REQUIREMENTS_FILE,
        low_memory=False,
    )

    assignment_candidates = pd.read_csv(
        ASSIGNMENT_CANDIDATES_FILE,
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
        MATERIAL_FILE,
        low_memory=False,
    )

    section_constraints = pd.read_csv(
        SECTION_CONSTRAINTS_FILE,
        low_memory=False,
    )

    print(
        f"Candidate windows        : {len(candidates):,}"
    )

    print(
        f"Resource requirements    : {len(resource_requirements):,}"
    )

    print(
        f"Assignment candidates    : {len(assignment_candidates):,}"
    )

    print(
        f"Task dependencies        : {len(dependencies):,}"
    )

    print(
        "\nApplying exact resource-time and safety gates..."
    )

    (
        base_feasibility,
        assignment_rows,
    ) = build_base_feasibility(
        candidates,
        block_requirements,
        resource_requirements,
        assignment_candidates,
        crews,
        crew_availability,
        machines,
        machine_availability,
        equipment,
        materials,
        section_constraints,
    )

    print(
        "Applying dependency sequencing gate..."
    )

    feasibility = apply_dependency_gate(
        base_feasibility,
        dependencies,
    )

    final_assignments = (
        filter_assignments_for_final_windows(
            assignment_rows,
            feasibility,
        )
    )

    print(
        "Building task-level feasibility summary..."
    )

    task_summary = build_task_summary(
        candidates,
        feasibility,
    )

    print(
        "Validating integrated/shadow opportunities..."
    )

    integrated_feasibility = (
        validate_integrated_opportunities(
            integrated,
            feasibility,
        )
    )

    shadow_feasibility = (
        validate_shadow_opportunities(
            shadow,
            feasibility,
        )
    )

    checks = validate_outputs(
        candidates,
        feasibility,
        final_assignments,
        task_summary,
    )

    rejections = feasibility[
        ~feasibility[
            "final_feasibility_status"
        ].isin(
            [
                "FEASIBLE_READY_FOR_OPTIMIZER",
                "FEASIBLE_REPOSITIONING_REQUIRED",
            ]
        )
    ].copy()

    final_assignments.to_csv(
        ASSIGNMENTS_OUTPUT,
        index=False,
    )

    feasibility.to_csv(
        FEASIBILITY_OUTPUT,
        index=False,
    )

    rejections.to_csv(
        REJECTIONS_OUTPUT,
        index=False,
    )

    task_summary.to_csv(
        TASK_SUMMARY_OUTPUT,
        index=False,
    )

    integrated_feasibility.to_csv(
        INTEGRATED_FEASIBILITY_OUTPUT,
        index=False,
    )

    shadow_feasibility.to_csv(
        SHADOW_FEASIBILITY_OUTPUT,
        index=False,
    )

    write_report(
        checks,
        feasibility,
        task_summary,
        integrated_feasibility,
        shadow_feasibility,
    )

    integrated_ready = (
        int(
            integrated_feasibility[
                "integrated_feasibility_status"
            ]
            .astype(str)
            .str.startswith(
                "READY_FOR_OPTIMIZER"
            )
            .sum()
        )
        if (
            not integrated_feasibility.empty
            and
            "integrated_feasibility_status"
            in integrated_feasibility.columns
        )
        else 0
    )

    shadow_ready = (
        int(
            shadow_feasibility[
                "shadow_feasibility_status"
            ]
            .astype(str)
            .str.startswith(
                "READY_FOR_OPTIMIZER"
            )
            .sum()
        )
        if (
            not shadow_feasibility.empty
            and
            "shadow_feasibility_status"
            in shadow_feasibility.columns
        )
        else 0
    )

    print(
        "\n"
        + "=" * 72
    )

    print(
        "V3.11 RESOURCE-TIME & SAFETY FEASIBILITY COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        f"\nInput candidate windows       : "
        f"{checks['input_candidate_windows']:,}"
    )

    print(
        f"Feasible windows              : "
        f"{checks['accepted_windows']:,}"
    )

    print(
        f"Ready without repositioning   : "
        f"{checks['ready_windows']:,}"
    )

    print(
        f"Repositioning-required windows : "
        f"{checks['repositioning_windows']:,}"
    )

    print(
        f"Rejected windows              : "
        f"{checks['rejected_windows']:,}"
    )

    print(
        f"Tasks with feasible windows   : "
        f"{checks['tasks_with_feasible_window']:,}"
    )

    print(
        f"Integrated opportunities ready: "
        f"{integrated_ready:,}"
    )

    print(
        f"Shadow opportunities ready    : "
        f"{shadow_ready:,}"
    )

    print(
        "\nHard-safety integrity:"
    )

    print(
        f"  Accepted train conflicts    : "
        f"{checks['accepted_train_conflicts']:,}"
    )

    print(
        f"  Accepted goods conflicts    : "
        f"{checks['accepted_goods_conflicts']:,}"
    )

    print(
        f"  Accepted resource failures  : "
        f"{checks['accepted_resource_failures']:,}"
    )

    print(
        f"  Duplicate feasibility IDs   : "
        f"{checks['duplicate_feasibility_ids']:,}"
    )

    print(
        f"  Missing feasibility rows    : "
        f"{checks['missing_feasibility_rows']:,}"
    )

    print(
        "\nOutputs:"
    )

    for path in [
        ASSIGNMENTS_OUTPUT,
        FEASIBILITY_OUTPUT,
        REJECTIONS_OUTPUT,
        TASK_SUMMARY_OUTPUT,
        INTEGRATED_FEASIBILITY_OUTPUT,
        SHADOW_FEASIBILITY_OUTPUT,
        REPORT_OUTPUT,
    ]:
        print(
            f"  {path}"
        )

    print(
        "\nOnly V3.11-feasible candidate windows are now eligible for "
        "Resource-Aware Optimizer V3."
    )


if __name__ == "__main__":
    main()
