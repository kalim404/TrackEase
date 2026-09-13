"""
TrackEase V3.12B - Dynamic Resource-Aware Optimizer V3

Purpose
-------
Select one safe, resource-feasible maintenance window per task while enforcing
resource exclusivity, section occupancy, dependencies, material stock, crew
duty limits, machine daily limits, and cyclic week-boundary conflicts.

This optimizer consumes ONLY windows that passed V3.11. It dynamically selects among all exact-time-safe resource alternatives produced by V3.12A instead of locking each window to one preselected crew/machine/equipment unit.

Important design principles
---------------------------
1. Safety is a hard constraint, never a soft score.
2. Train/goods conflicts must already be zero from V3.10/V3.11.
3. A crew/machine/equipment unit cannot be double-booked.
4. Mobilization/travel is reserved before a task using the V3 travel proxy.
5. Crew duty and machine operating limits are enforced conservatively.
6. Materials are treated as consumable inventory and cannot be over-allocated.
7. Dependencies require the selected predecessor to finish before the successor.
8. Same-section overlap is forbidden unless the pair is explicitly supported by
   a READY, parallel-capable integrated-block opportunity.
9. Shadow opportunities do not bypass section/resource/safety constraints.
10. Repositioning remains allowed, but receives a resource-efficiency penalty.
11. Human authorization remains mandatory after optimization.

Optimization approach
---------------------
A deterministic constraint-aware greedy heuristic is used. The prototype does
not claim global mathematical optimality. The heuristic orders tasks using
maintenance/operations value plus scarcity of feasible alternatives, then
selects the highest-scoring conflict-free candidate.

Candidate score (0-100 prototype DSS policy):
    60% maintenance value
    25% low operational impact
    10% resource efficiency
     5% coordination potential

The 60% maintenance component already incorporates V3.8 risk, urgency, safety
consequence, overdue/postponement, asset-availability gain and duration
efficiency. The 25% operational term represents passenger/timetable + freight
exposure. These are transparent prototype policy weights, not official Indian
Railways weights.

Inputs
------
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_candidate_block_windows.csv
    data/processed/v3_candidate_window_feasibility.csv
    data/processed/v3_optimizer_resource_options.csv
    data/processed/v3_task_dependencies.csv
    data/processed/v3_crews.csv
    data/processed/v3_machines.csv
    data/processed/v3_material_inventory.csv
    data/processed/v3_integrated_opportunity_feasibility.csv
    data/processed/v3_shadow_opportunity_feasibility.csv
    data/processed/v3_task_compatibility_graph.csv

Outputs
-------
    data/processed/v3_optimized_schedule.csv
    data/processed/v3_optimizer_unscheduled_tasks.csv
    data/processed/v3_optimizer_resource_bookings.csv
    data/processed/v3_optimizer_material_usage.csv
    data/processed/v3_optimizer_coordination_realization.csv
    data/processed/v3_optimizer_report.txt
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from itertools import combinations
from pathlib import Path
import math

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"
CANDIDATES_FILE = PROCESSED_DIR / "v3_candidate_block_windows.csv"
FEASIBILITY_FILE = PROCESSED_DIR / "v3_candidate_window_feasibility.csv"
RESOURCE_OPTIONS_FILE = PROCESSED_DIR / "v3_optimizer_resource_options.csv"
DEPENDENCIES_FILE = PROCESSED_DIR / "v3_task_dependencies.csv"

CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
MACHINES_FILE = PROCESSED_DIR / "v3_machines.csv"
MATERIAL_FILE = PROCESSED_DIR / "v3_material_inventory.csv"

INTEGRATED_FILE = (
    PROCESSED_DIR / "v3_integrated_opportunity_feasibility.csv"
)
SHADOW_FILE = (
    PROCESSED_DIR / "v3_shadow_opportunity_feasibility.csv"
)
COMPATIBILITY_FILE = (
    PROCESSED_DIR / "v3_task_compatibility_graph.csv"
)

SCHEDULE_OUTPUT = PROCESSED_DIR / "v3_optimized_schedule.csv"
UNSCHEDULED_OUTPUT = PROCESSED_DIR / "v3_optimizer_unscheduled_tasks.csv"
RESOURCE_BOOKINGS_OUTPUT = (
    PROCESSED_DIR / "v3_optimizer_resource_bookings.csv"
)
MATERIAL_USAGE_OUTPUT = (
    PROCESSED_DIR / "v3_optimizer_material_usage.csv"
)
COORDINATION_OUTPUT = (
    PROCESSED_DIR / "v3_optimizer_coordination_realization.csv"
)
REPORT_OUTPUT = PROCESSED_DIR / "v3_optimizer_report.txt"


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

WEIGHT_MAINTENANCE_VALUE = 0.60
WEIGHT_LOW_OPERATIONAL_IMPACT = 0.25
WEIGHT_RESOURCE_EFFICIENCY = 0.10
WEIGHT_COORDINATION_POTENTIAL = 0.05

DATA_ORIGIN = "TRACKEASE_V3_DYNAMIC_RESOURCE_AWARE_OPTIMIZER"
INTEGRATION_MODE = "PROTOTYPE_DYNAMIC_RESOURCE_CONSTRAINT_AWARE_OPTIMIZER"

FEASIBLE_STATUSES = {
    "FEASIBLE_READY_FOR_OPTIMIZER",
    "FEASIBLE_REPOSITIONING_REQUIRED",
}

READY_INTEGRATED_PREFIX = "READY_FOR_OPTIMIZER"
READY_SHADOW_PREFIX = "READY_FOR_OPTIMIZER"


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

    return clean_text(value).lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


def safe_float(
    value: object,
    default: float | None = None,
) -> float | None:
    if pd.isna(value):
        return default

    try:
        result = float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default

    if not math.isfinite(result):
        return default

    return result


def clamp(
    value: float,
    lower: float = 0.0,
    upper: float = 100.0,
) -> float:
    return max(
        lower,
        min(
            upper,
            value,
        ),
    )


def require_columns(
    dataframe: pd.DataFrame,
    required: list[str],
    label: str,
) -> None:
    missing = [
        column
        for column in required
        if column not in dataframe.columns
    ]

    if missing:
        raise ValueError(
            f"{label} is missing required columns: {missing}\n"
            f"Available columns: {dataframe.columns.tolist()}"
        )


def require_inputs() -> None:
    required = [
        TASKS_FILE,
        CANDIDATES_FILE,
        FEASIBILITY_FILE,
        RESOURCE_OPTIONS_FILE,
        DEPENDENCIES_FILE,
        CREWS_FILE,
        MACHINES_FILE,
        MATERIAL_FILE,
        INTEGRATED_FILE,
        SHADOW_FILE,
        COMPATIBILITY_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.12 input files are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


def cyclic_overlap(
    start_a: float,
    end_a: float,
    start_b: float,
    end_b: float,
) -> bool:
    """
    Test overlap on a repeating weekly cycle.

    Intervals can extend below 0 or above 10080 because resource travel and
    Sunday->Monday windows may cross the week boundary.
    """
    for shift in (
        -MINUTES_PER_WEEK,
        0,
        MINUTES_PER_WEEK,
    ):
        shifted_start = start_b + shift
        shifted_end = end_b + shift

        if (
            start_a < shifted_end
            and end_a > shifted_start
        ):
            return True

    return False


def day_index(
    minute_of_week: float,
) -> int:
    return int(
        math.floor(
            minute_of_week / MINUTES_PER_DAY
        )
    ) % 7


def parse_task_ids(
    value: object,
) -> list[str]:
    return [
        item.strip()
        for item in clean_text(value).split("|")
        if item.strip()
    ]


# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

def build_dependency_graph(
    all_task_ids: set[str],
    dependencies: pd.DataFrame,
) -> tuple[
    dict[str, list[str]],
    dict[str, int],
]:
    predecessors: dict[
        str,
        list[str]
    ] = defaultdict(list)

    successors: dict[
        str,
        list[str]
    ] = defaultdict(list)

    indegree = {
        task_id: 0
        for task_id in all_task_ids
    }

    for row in dependencies.to_dict(
        orient="records"
    ):
        predecessor = clean_text(
            row.get(
                "predecessor_task_id"
            )
        )

        successor = clean_text(
            row.get(
                "successor_task_id"
            )
        )

        if (
            not predecessor
            or not successor
            or predecessor not in all_task_ids
            or successor not in all_task_ids
        ):
            continue

        if predecessor in predecessors[
            successor
        ]:
            continue

        predecessors[
            successor
        ].append(
            predecessor
        )

        successors[
            predecessor
        ].append(
            successor
        )

        indegree[
            successor
        ] += 1

    queue = deque(
        sorted(
            task_id
            for (
                task_id,
                degree
            ) in indegree.items()
            if degree == 0
        )
    )

    topological = []

    while queue:
        task_id = queue.popleft()
        topological.append(
            task_id
        )

        for successor in sorted(
            successors.get(
                task_id,
                []
            )
        ):
            indegree[
                successor
            ] -= 1

            if indegree[
                successor
            ] == 0:
                queue.append(
                    successor
                )

    if len(topological) != len(
        all_task_ids
    ):
        raise RuntimeError(
            "Dependency cycle detected in V3 task dependencies."
        )

    depth = {
        task_id: 0
        for task_id in all_task_ids
    }

    for task_id in topological:
        for successor in successors.get(
            task_id,
            []
        ):
            depth[
                successor
            ] = max(
                depth[
                    successor
                ],
                depth[
                    task_id
                ] + 1,
            )

    return (
        dict(
            predecessors
        ),
        depth,
    )


# ---------------------------------------------------------------------------
# Coordination indexes
# ---------------------------------------------------------------------------

def build_parallel_pair_index(
    compatibility: pd.DataFrame,
) -> set[
    tuple[str, str]
]:
    require_columns(
        compatibility,
        [
            "task_a_id",
            "task_b_id",
        ],
        "Compatibility graph",
    )

    pairs = set()

    for row in compatibility.to_dict(
        orient="records"
    ):
        task_a = clean_text(
            row.get(
                "task_a_id"
            )
        )

        task_b = clean_text(
            row.get(
                "task_b_id"
            )
        )

        if not task_a or not task_b:
            continue

        parallel = bool_value(
            row.get(
                "parallel_capable"
            )
        )

        relationship = clean_text(
            row.get(
                "relationship_type"
            )
        ).upper()

        if (
            parallel
            or relationship.startswith(
                "PARALLEL_"
            )
        ):
            pairs.add(
                tuple(
                    sorted(
                        (
                            task_a,
                            task_b,
                        )
                    )
                )
            )

    return pairs


def build_integrated_indexes(
    integrated: pd.DataFrame,
    parallel_pairs: set[
        tuple[str, str]
    ],
) -> tuple[
    dict[
        tuple[str, str],
        list[
            tuple[
                float,
                float,
                str,
            ]
        ]
    ],
    list[dict],
]:
    intervals_by_pair: dict[
        tuple[str, str],
        list[
            tuple[
                float,
                float,
                str,
            ]
        ],
    ] = defaultdict(list)

    ready_rows = []

    if integrated.empty:
        return (
            {},
            [],
        )

    for row in integrated.to_dict(
        orient="records"
    ):
        status = clean_text(
            row.get(
                "integrated_feasibility_status"
            )
        )

        if not status.startswith(
            READY_INTEGRATED_PREFIX
        ):
            continue

        start = safe_float(
            row.get(
                "window_start_minute_week"
            )
        )

        end = safe_float(
            row.get(
                "window_end_minute_week"
            )
        )

        task_ids = parse_task_ids(
            row.get(
                "task_ids"
            )
        )

        if (
            start is None
            or end is None
            or len(task_ids) < 2
        ):
            continue

        opportunity_id = clean_text(
            row.get(
                "integrated_opportunity_id"
            )
        )

        normalized = dict(
            row
        )
        normalized[
            "_task_ids"
        ] = task_ids
        normalized[
            "_start"
        ] = start
        normalized[
            "_end"
        ] = end

        ready_rows.append(
            normalized
        )

        for task_a, task_b in combinations(
            task_ids,
            2,
        ):
            pair = tuple(
                sorted(
                    (
                        task_a,
                        task_b,
                    )
                )
            )

            # Never use a sequential relationship to justify simultaneous
            # same-section occupation.
            if pair not in parallel_pairs:
                continue

            intervals_by_pair[
                pair
            ].append(
                (
                    start,
                    end,
                    opportunity_id,
                )
            )

    return (
        dict(
            intervals_by_pair
        ),
        ready_rows,
    )


def build_shadow_indexes(
    shadow: pd.DataFrame,
) -> tuple[
    set[str],
    list[dict],
]:
    candidate_ids = set()
    ready_rows = []

    if shadow.empty:
        return (
            candidate_ids,
            ready_rows,
        )

    for row in shadow.to_dict(
        orient="records"
    ):
        status = clean_text(
            row.get(
                "shadow_feasibility_status"
            )
        )

        if not status.startswith(
            READY_SHADOW_PREFIX
        ):
            continue

        host_id = clean_text(
            row.get(
                "host_candidate_window_id"
            )
        )

        shadow_id = clean_text(
            row.get(
                "shadow_candidate_window_id"
            )
        )

        if host_id:
            candidate_ids.add(
                host_id
            )

        if shadow_id:
            candidate_ids.add(
                shadow_id
            )

        ready_rows.append(
            dict(
                row
            )
        )

    return (
        candidate_ids,
        ready_rows,
    )


def candidate_has_integrated_potential(
    task_id: str,
    start: float,
    end: float,
    ready_integrated_rows: list[dict],
) -> bool:
    for row in ready_integrated_rows:
        if task_id not in row[
            "_task_ids"
        ]:
            continue

        if (
            start >= row[
                "_start"
            ]
            and end <= row[
                "_end"
            ]
        ):
            return True

    return False


# ---------------------------------------------------------------------------
# Candidate preparation
# ---------------------------------------------------------------------------

def prepare_candidates(
    candidates: pd.DataFrame,
    feasibility: pd.DataFrame,
    shadow_candidate_ids: set[str],
    ready_integrated_rows: list[dict],
) -> pd.DataFrame:
    require_columns(
        candidates,
        [
            "candidate_window_id",
            "task_id",
            "section_id",
            "window_start_minute_week",
            "window_end_minute_week",
            "required_block_minutes",
            "maintenance_value_score",
            "prewindow_operational_impact_score",
        ],
        "V3.10 candidates",
    )

    require_columns(
        feasibility,
        [
            "candidate_window_id",
            "task_id",
            "final_feasibility_status",
            "repositioning_requirement_count",
        ],
        "V3.11 feasibility",
    )

    feasible = feasibility[
        feasibility[
            "final_feasibility_status"
        ].astype(str).isin(
            FEASIBLE_STATUSES
        )
    ].copy()

    merged = candidates.merge(
        feasible[
            [
                "candidate_window_id",
                "final_feasibility_status",
                "repositioning_requirement_count",
                "requires_resource_repositioning",
                "dependency_gate_required",
                "dependency_gate_passed",
                "infrastructure_review_required",
                "review_flags",
            ]
        ],
        on="candidate_window_id",
        how="inner",
        validate="one_to_one",
    )

    for column in [
        "maintenance_value_score",
        "prewindow_operational_impact_score",
        "window_fit_score",
        "repositioning_requirement_count",
    ]:
        if column not in merged.columns:
            merged[
                column
            ] = 0.0

        merged[
            column
        ] = pd.to_numeric(
            merged[
                column
            ],
            errors="coerce",
        ).fillna(
            0.0
        )

    resource_efficiency = (
        100.0
        - 20.0
        * merged[
            "repositioning_requirement_count"
        ]
    ).clip(
        lower=40.0,
        upper=100.0,
    )

    integrated_potential = []

    for row in merged.itertuples(
        index=False
    ):
        integrated_potential.append(
            candidate_has_integrated_potential(
                clean_text(
                    row.task_id
                ),
                float(
                    row.window_start_minute_week
                ),
                float(
                    row.window_end_minute_week
                ),
                ready_integrated_rows,
            )
        )

    merged[
        "integrated_coordination_potential"
    ] = integrated_potential

    merged[
        "shadow_coordination_potential"
    ] = merged[
        "candidate_window_id"
    ].astype(str).isin(
        shadow_candidate_ids
    )

    merged[
        "coordination_potential_score"
    ] = merged.apply(
        lambda row:
            (
                100.0
                if bool(
                    row[
                        "integrated_coordination_potential"
                    ]
                )
                else (
                    80.0
                    if bool(
                        row[
                            "shadow_coordination_potential"
                        ]
                    )
                    else 0.0
                )
            ),
        axis=1,
    )

    merged[
        "resource_efficiency_score"
    ] = resource_efficiency

    merged[
        "low_operational_impact_score"
    ] = (
        100.0
        - merged[
            "prewindow_operational_impact_score"
        ]
    ).clip(
        lower=0.0,
        upper=100.0,
    )

    merged[
        "optimizer_score"
    ] = (
        WEIGHT_MAINTENANCE_VALUE
        * merged[
            "maintenance_value_score"
        ]
        + WEIGHT_LOW_OPERATIONAL_IMPACT
        * merged[
            "low_operational_impact_score"
        ]
        + WEIGHT_RESOURCE_EFFICIENCY
        * merged[
            "resource_efficiency_score"
        ]
        + WEIGHT_COORDINATION_POTENTIAL
        * merged[
            "coordination_potential_score"
        ]
    ).round(
        4
    )

    return merged


# ---------------------------------------------------------------------------
# Resource/material indexes
# ---------------------------------------------------------------------------

def build_option_index(
    options: pd.DataFrame,
) -> dict[
    str,
    dict[str, list[dict]]
]:
    require_columns(
        options,
        [
            "candidate_window_id",
            "requirement_id",
            "resource_category",
            "resource_id",
            "resource_type",
            "quantity_required",
            "travel_minutes_proxy",
            "repositioning_required",
            "exact_time_option_rank",
        ],
        "V3.12 exact-time resource options",
    )

    result: dict[
        str,
        dict[str, list[dict]]
    ] = defaultdict(
        lambda: defaultdict(list)
    )

    for row in options.to_dict(
        orient="records"
    ):
        candidate_id = clean_text(
            row.get(
                "candidate_window_id"
            )
        )

        requirement_id = clean_text(
            row.get(
                "requirement_id"
            )
        )

        if not candidate_id or not requirement_id:
            continue

        result[
            candidate_id
        ][
            requirement_id
        ].append(
            row
        )

    normalized = {}

    for candidate_id, requirement_map in result.items():
        normalized[
            candidate_id
        ] = {}

        for requirement_id, rows in requirement_map.items():
            normalized[
                candidate_id
            ][
                requirement_id
            ] = sorted(
                rows,
                key=lambda row: (
                    1
                    if bool_value(
                        row.get(
                            "repositioning_required"
                        )
                    )
                    else 0,
                    safe_float(
                        row.get(
                            "travel_minutes_proxy"
                        ),
                        math.inf,
                    ),
                    safe_float(
                        row.get(
                            "exact_time_option_rank"
                        ),
                        math.inf,
                    ),
                    clean_text(
                        row.get(
                            "resource_id"
                        )
                    ),
                ),
            )

    return normalized


def build_resource_limits(
    crews: pd.DataFrame,
    machines: pd.DataFrame,
) -> tuple[
    dict[str, float],
    dict[str, float],
]:
    crew_limits = {}

    for row in crews.to_dict(
        orient="records"
    ):
        crew_id = clean_text(
            row.get(
                "crew_id"
            )
        )

        limit = safe_float(
            row.get(
                "max_work_minutes_per_shift"
            ),
            480.0,
        )

        if crew_id:
            crew_limits[
                crew_id
            ] = float(
                limit
            )

    machine_limits = {}

    for row in machines.to_dict(
        orient="records"
    ):
        machine_id = clean_text(
            row.get(
                "machine_id"
            )
        )

        limit = safe_float(
            row.get(
                "max_operating_minutes_per_day"
            ),
            600.0,
        )

        if machine_id:
            machine_limits[
                machine_id
            ] = float(
                limit
            )

    return (
        crew_limits,
        machine_limits,
    )


def build_material_stock(
    materials: pd.DataFrame,
) -> dict[
    str,
    float
]:
    require_columns(
        materials,
        [
            "inventory_id",
            "quantity_available",
        ],
        "Material inventory",
    )

    stock = {}

    for row in materials.to_dict(
        orient="records"
    ):
        inventory_id = clean_text(
            row.get(
                "inventory_id"
            )
        )

        quantity = safe_float(
            row.get(
                "quantity_available"
            ),
            0.0,
        )

        if inventory_id:
            stock[
                inventory_id
            ] = float(
                quantity
            )

    return stock


# ---------------------------------------------------------------------------
# Optimizer state
# ---------------------------------------------------------------------------

class OptimizerState:
    def __init__(
        self,
        crew_limits: dict[str, float],
        machine_limits: dict[str, float],
        material_stock: dict[str, float],
        integrated_pair_intervals: dict[
            tuple[str, str],
            list[
                tuple[
                    float,
                    float,
                    str,
                ]
            ]
        ],
    ):
        self.crew_limits = crew_limits
        self.machine_limits = machine_limits
        self.material_stock = material_stock.copy()
        self.material_used = defaultdict(float)

        self.integrated_pair_intervals = (
            integrated_pair_intervals
        )

        self.scheduled_by_task = {}
        self.scheduled_candidate_ids = set()

        self.section_bookings: dict[
            str,
            list[dict]
        ] = defaultdict(list)

        self.resource_bookings: dict[
            str,
            list[dict]
        ] = defaultdict(list)

        self.crew_duty_used: dict[
            tuple[str, int],
            float
        ] = defaultdict(float)

        self.machine_minutes_used: dict[
            tuple[str, int],
            float
        ] = defaultdict(float)

        self.schedule_rows = []
        self.resource_booking_rows = []


# ---------------------------------------------------------------------------
# Conflict logic
# ---------------------------------------------------------------------------

def can_share_section_via_integrated_block(
    state: OptimizerState,
    task_a: str,
    start_a: float,
    end_a: float,
    task_b: str,
    start_b: float,
    end_b: float,
) -> tuple[
    bool,
    str,
]:
    pair = tuple(
        sorted(
            (
                task_a,
                task_b,
            )
        )
    )

    intervals = state.integrated_pair_intervals.get(
        pair,
        [],
    )

    for (
        integrated_start,
        integrated_end,
        opportunity_id,
    ) in intervals:
        if (
            start_a >= integrated_start
            and end_a <= integrated_end
            and start_b >= integrated_start
            and end_b <= integrated_end
        ):
            return (
                True,
                opportunity_id,
            )

    return (
        False,
        "",
    )


def check_section_conflict(
    state: OptimizerState,
    candidate: dict,
) -> tuple[
    bool,
    list[str],
]:
    section_id = clean_text(
        candidate.get(
            "section_id"
        )
    )

    task_id = clean_text(
        candidate.get(
            "task_id"
        )
    )

    start = float(
        candidate[
            "window_start_minute_week"
        ]
    )

    end = float(
        candidate[
            "window_end_minute_week"
        ]
    )

    shared_integrated_ids = []

    for existing in state.section_bookings.get(
        section_id,
        [],
    ):
        if not cyclic_overlap(
            start,
            end,
            existing[
                "start"
            ],
            existing[
                "end"
            ],
        ):
            continue

        allowed, opportunity_id = (
            can_share_section_via_integrated_block(
                state,
                task_id,
                start,
                end,
                existing[
                    "task_id"
                ],
                existing[
                    "start"
                ],
                existing[
                    "end"
                ],
            )
        )

        if not allowed:
            return (
                False,
                [],
            )

        shared_integrated_ids.append(
            opportunity_id
        )

    return (
        True,
        sorted(
            set(
                shared_integrated_ids
            )
        ),
    )


def physical_resource_interval(
    assignment: dict,
    task_start: float,
    task_end: float,
) -> tuple[
    float,
    float,
]:
    travel = safe_float(
        assignment.get(
            "travel_minutes_proxy"
        ),
        0.0,
    )

    if travel is None:
        travel = 0.0

    return (
        task_start - max(
            0.0,
            float(
                travel
            ),
        ),
        task_end,
    )


def is_material_assignment(
    assignment: dict,
) -> bool:
    category = clean_text(
        assignment.get(
            "resource_category"
        )
    ).upper()

    resource_type = clean_text(
        assignment.get(
            "resource_type"
        )
        or assignment.get(
            "selected_resource_type"
        )
    ).upper()

    return (
        category == "MATERIAL"
        or "MATERIAL" in resource_type
        or "INVENTORY" in resource_type
    )


def option_resource_id(
    option: dict,
) -> str:
    return clean_text(
        option.get(
            "resource_id"
        )
        or option.get(
            "selected_resource_id"
        )
    )


def option_resource_type(
    option: dict,
) -> str:
    return clean_text(
        option.get(
            "resource_type"
        )
        or option.get(
            "selected_resource_type"
        )
    )


def check_option_against_optimizer_state(
    state: OptimizerState,
    option: dict,
    task_start: float,
    task_end: float,
    local_resource_ids: set[str],
    local_crew_duty: dict[tuple[str, int], float],
    local_machine_minutes: dict[tuple[str, int], float],
    local_material: dict[str, float],
) -> tuple[
    bool,
    str,
    dict | None,
]:
    resource_id = option_resource_id(
        option
    )

    if not resource_id:
        return (
            False,
            "MISSING_RESOURCE_ID",
            None,
        )

    if is_material_assignment(
        option
    ):
        quantity = safe_float(
            option.get(
                "quantity_required"
            ),
            1.0,
        )

        if quantity is None:
            quantity = 1.0

        available = state.material_stock.get(
            resource_id,
            0.0,
        )

        projected = (
            state.material_used[
                resource_id
            ]
            + local_material.get(
                resource_id,
                0.0,
            )
            + float(
                quantity
            )
        )

        if projected > available + 1e-9:
            return (
                False,
                "MATERIAL_STOCK_EXCEEDED",
                None,
            )

        return (
            True,
            "",
            {
                "kind": "MATERIAL",
                "resource_id": resource_id,
                "quantity": float(
                    quantity
                ),
                "option": option,
            },
        )

    # Distinct simultaneous mandatory requirements must not consume the same
    # physical resource twice inside one maintenance task.
    if resource_id in local_resource_ids:
        return (
            False,
            "INTRA_TASK_RESOURCE_CONFLICT",
            None,
        )

    booking_start, booking_end = (
        physical_resource_interval(
            option,
            task_start,
            task_end,
        )
    )

    for existing in state.resource_bookings.get(
        resource_id,
        [],
    ):
        if cyclic_overlap(
            booking_start,
            booking_end,
            existing[
                "booking_start"
            ],
            existing[
                "booking_end"
            ],
        ):
            return (
                False,
                "RESOURCE_DOUBLE_BOOKING",
                None,
            )

    duty_minutes = (
        booking_end
        - booking_start
    )

    start_day = day_index(
        task_start
    )

    if resource_id in state.crew_limits:
        key = (
            resource_id,
            start_day,
        )

        projected = (
            state.crew_duty_used[
                key
            ]
            + local_crew_duty.get(
                key,
                0.0,
            )
            + duty_minutes
        )

        if projected > (
            state.crew_limits[
                resource_id
            ]
            + 1e-9
        ):
            return (
                False,
                "CREW_DUTY_LIMIT_EXCEEDED",
                None,
            )

    if resource_id in state.machine_limits:
        key = (
            resource_id,
            start_day,
        )

        block_minutes = (
            task_end
            - task_start
        )

        projected = (
            state.machine_minutes_used[
                key
            ]
            + local_machine_minutes.get(
                key,
                0.0,
            )
            + block_minutes
        )

        if projected > (
            state.machine_limits[
                resource_id
            ]
            + 1e-9
        ):
            return (
                False,
                "MACHINE_DAILY_LIMIT_EXCEEDED",
                None,
            )

    return (
        True,
        "",
        {
            "kind": "PHYSICAL",
            "resource_id": resource_id,
            "booking_start": booking_start,
            "booking_end": booking_end,
            "duty_minutes": duty_minutes,
            "start_day": start_day,
            "block_minutes": (
                task_end
                - task_start
            ),
            "option": option,
        },
    )


def choose_resource_bundle(
    state: OptimizerState,
    candidate: dict,
    requirement_options: dict[
        str,
        list[dict]
    ],
) -> tuple[
    bool,
    str,
    list[dict],
    dict[str, float],
]:
    """
    Choose one currently usable resource option per mandatory requirement.

    Requirements are processed scarcity-first. Options are already ordered by
    exact-time rank, local-before-repositioning, travel and deterministic ID.
    A bounded depth-first search avoids rejecting a candidate merely because
    the first safe resource choice blocks another mandatory requirement.
    """
    task_start = float(
        candidate[
            "window_start_minute_week"
        ]
    )

    task_end = float(
        candidate[
            "window_end_minute_week"
        ]
    )

    if not requirement_options:
        return (
            False,
            "NO_EXACT_TIME_RESOURCE_OPTIONS",
            [],
            {},
        )

    ordered_requirements = sorted(
        requirement_options.items(),
        key=lambda item: (
            len(
                item[1]
            ),
            item[0],
        ),
    )

    for requirement_id, options in ordered_requirements:
        if not options:
            return (
                False,
                "MANDATORY_REQUIREMENT_WITHOUT_RESOURCE_OPTION",
                [],
                {},
            )

    failure_counter = Counter()
    search_nodes = 0
    max_search_nodes = 2500

    def recurse(
        index: int,
        selected_options: list[dict],
        selected_effects: list[dict],
        local_resource_ids: set[str],
        local_crew_duty: dict[
            tuple[str, int],
            float
        ],
        local_machine_minutes: dict[
            tuple[str, int],
            float
        ],
        local_material: dict[
            str,
            float
        ],
    ) -> tuple[
        list[dict],
        list[dict],
        dict[str, float],
    ] | None:
        nonlocal search_nodes

        if search_nodes >= max_search_nodes:
            failure_counter[
                "RESOURCE_COMBINATION_SEARCH_LIMIT"
            ] += 1
            return None

        if index >= len(
            ordered_requirements
        ):
            return (
                selected_options,
                selected_effects,
                dict(
                    local_material
                ),
            )

        (
            requirement_id,
            options,
        ) = ordered_requirements[
            index
        ]

        for option in options:
            search_nodes += 1

            (
                available,
                reason,
                effect,
            ) = check_option_against_optimizer_state(
                state,
                option,
                task_start,
                task_end,
                local_resource_ids,
                local_crew_duty,
                local_machine_minutes,
                local_material,
            )

            if not available or effect is None:
                failure_counter[
                    reason
                ] += 1
                continue

            next_resource_ids = set(
                local_resource_ids
            )

            next_crew_duty = dict(
                local_crew_duty
            )

            next_machine_minutes = dict(
                local_machine_minutes
            )

            next_material = dict(
                local_material
            )

            if effect[
                "kind"
            ] == "MATERIAL":
                resource_id = effect[
                    "resource_id"
                ]

                next_material[
                    resource_id
                ] = (
                    next_material.get(
                        resource_id,
                        0.0,
                    )
                    + effect[
                        "quantity"
                    ]
                )
            else:
                resource_id = effect[
                    "resource_id"
                ]

                next_resource_ids.add(
                    resource_id
                )

                if resource_id in state.crew_limits:
                    key = (
                        resource_id,
                        effect[
                            "start_day"
                        ],
                    )

                    next_crew_duty[
                        key
                    ] = (
                        next_crew_duty.get(
                            key,
                            0.0,
                        )
                        + effect[
                            "duty_minutes"
                        ]
                    )

                if resource_id in state.machine_limits:
                    key = (
                        resource_id,
                        effect[
                            "start_day"
                        ],
                    )

                    next_machine_minutes[
                        key
                    ] = (
                        next_machine_minutes.get(
                            key,
                            0.0,
                        )
                        + effect[
                            "block_minutes"
                        ]
                    )

            result = recurse(
                index + 1,
                selected_options
                + [
                    option
                ],
                selected_effects
                + [
                    effect
                ],
                next_resource_ids,
                next_crew_duty,
                next_machine_minutes,
                next_material,
            )

            if result is not None:
                return result

        return None

    result = recurse(
        0,
        [],
        [],
        set(),
        {},
        {},
        {},
    )

    if result is None:
        primary_reason = (
            failure_counter.most_common(
                1
            )[0][0]
            if failure_counter
            else "NO_RESOURCE_COMBINATION"
        )

        return (
            False,
            primary_reason,
            [],
            {},
        )

    (
        selected_options,
        selected_effects,
        proposed_material,
    ) = result

    proposed_bookings = []

    for option, effect in zip(
        selected_options,
        selected_effects,
    ):
        if effect[
            "kind"
        ] == "MATERIAL":
            continue

        proposed_bookings.append(
            {
                "resource_id":
                    effect[
                        "resource_id"
                    ],

                "resource_category":
                    clean_text(
                        option.get(
                            "resource_category"
                        )
                    ),

                "resource_type":
                    option_resource_type(
                        option
                    ),

                "requirement_id":
                    clean_text(
                        option.get(
                            "requirement_id"
                        )
                    ),

                "booking_start":
                    effect[
                        "booking_start"
                    ],

                "booking_end":
                    effect[
                        "booking_end"
                    ],

                "task_start":
                    task_start,

                "task_end":
                    task_end,

                "travel_minutes_proxy":
                    safe_float(
                        option.get(
                            "travel_minutes_proxy"
                        ),
                        0.0,
                    ),

                "repositioning_required":
                    bool_value(
                        option.get(
                            "repositioning_required"
                        )
                    ),

                "exact_time_option_rank":
                    option.get(
                        "exact_time_option_rank"
                    ),
            }
        )

    return (
        True,
        "",
        proposed_bookings,
        proposed_material,
    )


def check_dependencies(
    state: OptimizerState,
    task_id: str,
    candidate_start: float,
    predecessors: dict[
        str,
        list[str]
    ],
) -> tuple[
    bool,
    str,
]:
    for predecessor in predecessors.get(
        task_id,
        [],
    ):
        scheduled = state.scheduled_by_task.get(
            predecessor
        )

        if scheduled is None:
            return (
                False,
                "PREDECESSOR_NOT_SCHEDULED",
            )

        if float(
            scheduled[
                "window_end_minute_week"
            ]
        ) > candidate_start + 1e-9:
            return (
                False,
                "PREDECESSOR_FINISHES_AFTER_SUCCESSOR_START",
            )

    return (
        True,
        "",
    )


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

def commit_candidate(
    state: OptimizerState,
    candidate: dict,
    proposed_bookings: list[dict],
    proposed_material: dict[str, float],
    shared_integrated_ids: list[str],
) -> None:
    task_id = clean_text(
        candidate.get(
            "task_id"
        )
    )

    candidate_id = clean_text(
        candidate.get(
            "candidate_window_id"
        )
    )

    section_id = clean_text(
        candidate.get(
            "section_id"
        )
    )

    start = float(
        candidate[
            "window_start_minute_week"
        ]
    )

    end = float(
        candidate[
            "window_end_minute_week"
        ]
    )

    schedule_row = dict(
        candidate
    )

    schedule_row[
        "optimizer_selection_status"
    ] = "SELECTED"

    schedule_row[
        "shared_integrated_opportunity_ids"
    ] = "|".join(
        shared_integrated_ids
    )

    schedule_row[
        "human_authorization_required"
    ] = True

    schedule_row[
        "data_origin_v3_12"
    ] = DATA_ORIGIN

    schedule_row[
        "integration_mode_v3_12"
    ] = INTEGRATION_MODE

    state.schedule_rows.append(
        schedule_row
    )

    state.scheduled_by_task[
        task_id
    ] = schedule_row

    state.scheduled_candidate_ids.add(
        candidate_id
    )

    state.section_bookings[
        section_id
    ].append(
        {
            "task_id":
                task_id,
            "candidate_window_id":
                candidate_id,
            "start":
                start,
            "end":
                end,
        }
    )

    dedupe_resource_booking = set()

    for booking in proposed_bookings:
        resource_id = booking[
            "resource_id"
        ]

        signature = (
            resource_id,
            round(
                booking[
                    "booking_start"
                ],
                6,
            ),
            round(
                booking[
                    "booking_end"
                ],
                6,
            ),
        )

        if signature in dedupe_resource_booking:
            continue

        dedupe_resource_booking.add(
            signature
        )

        state.resource_bookings[
            resource_id
        ].append(
            dict(
                booking
            )
        )

        duty_minutes = (
            booking[
                "booking_end"
            ]
            - booking[
                "booking_start"
            ]
        )

        start_day = day_index(
            booking[
                "task_start"
            ]
        )

        if resource_id in state.crew_limits:
            state.crew_duty_used[
                (
                    resource_id,
                    start_day,
                )
            ] += duty_minutes

        if resource_id in state.machine_limits:
            state.machine_minutes_used[
                (
                    resource_id,
                    start_day,
                )
            ] += (
                booking[
                    "task_end"
                ]
                - booking[
                    "task_start"
                ]
            )

        output_booking = dict(
            booking
        )
        output_booking[
            "candidate_window_id"
        ] = candidate_id
        output_booking[
            "task_id"
        ] = task_id
        output_booking[
            "section_id"
        ] = section_id
        output_booking[
            "data_origin"
        ] = DATA_ORIGIN
        output_booking[
            "integration_mode"
        ] = INTEGRATION_MODE

        state.resource_booking_rows.append(
            output_booking
        )

    for (
        inventory_id,
        quantity
    ) in proposed_material.items():
        state.material_used[
            inventory_id
        ] += quantity


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------

def build_task_order(
    all_feasible_candidates: pd.DataFrame,
    dependency_depth: dict[
        str,
        int
    ],
) -> list[str]:
    grouped = (
        all_feasible_candidates.groupby(
            "task_id"
        )
        .agg(
            max_optimizer_score=(
                "optimizer_score",
                "max",
            ),
            candidate_count=(
                "candidate_window_id",
                "count",
            ),
            max_maintenance_value=(
                "maintenance_value_score",
                "max",
            ),
        )
        .reset_index()
    )

    grouped[
        "scarcity_bonus"
    ] = grouped[
        "candidate_count"
    ].apply(
        lambda count:
            10.0
            / math.sqrt(
                max(
                    1,
                    int(
                        count
                    ),
                )
            )
    )

    grouped[
        "task_order_score"
    ] = (
        grouped[
            "max_optimizer_score"
        ]
        + grouped[
            "scarcity_bonus"
        ]
    )

    grouped[
        "dependency_depth"
    ] = grouped[
        "task_id"
    ].map(
        dependency_depth
    ).fillna(
        0
    ).astype(
        int
    )

    grouped = grouped.sort_values(
        by=[
            "dependency_depth",
            "task_order_score",
            "max_maintenance_value",
            "candidate_count",
            "task_id",
        ],
        ascending=[
            True,
            False,
            False,
            True,
            True,
        ],
        kind="stable",
    )

    return grouped[
        "task_id"
    ].astype(str).tolist()


def optimize(
    all_tasks: pd.DataFrame,
    prepared_candidates: pd.DataFrame,
    option_index: dict[
        str,
        dict[str, list[dict]]
    ],
    predecessors: dict[
        str,
        list[str]
    ],
    dependency_depth: dict[
        str,
        int
    ],
    crew_limits: dict[str, float],
    machine_limits: dict[str, float],
    material_stock: dict[str, float],
    integrated_pair_intervals: dict[
        tuple[str, str],
        list[
            tuple[
                float,
                float,
                str,
            ]
        ]
    ],
) -> tuple[
    OptimizerState,
    pd.DataFrame,
]:
    state = OptimizerState(
        crew_limits,
        machine_limits,
        material_stock,
        integrated_pair_intervals,
    )

    candidates_by_task = {
        task_id:
            group.sort_values(
                by=[
                    "optimizer_score",
                    "window_fit_score",
                    "window_start_minute_week",
                    "candidate_window_id",
                ],
                ascending=[
                    False,
                    False,
                    True,
                    True,
                ],
                kind="stable",
            )
        for (
            task_id,
            group
        ) in prepared_candidates.groupby(
            "task_id"
        )
    }

    task_order = build_task_order(
        prepared_candidates,
        dependency_depth,
    )

    unscheduled_rows = []

    for task_id in task_order:
        task_candidates = candidates_by_task[
            task_id
        ]

        rejection_counter = Counter()
        selected = False

        for candidate_series in task_candidates.to_dict(
            orient="records"
        ):
            candidate_id = clean_text(
                candidate_series.get(
                    "candidate_window_id"
                )
            )

            start = float(
                candidate_series[
                    "window_start_minute_week"
                ]
            )

            dependency_ok, dependency_reason = (
                check_dependencies(
                    state,
                    task_id,
                    start,
                    predecessors,
                )
            )

            if not dependency_ok:
                rejection_counter[
                    dependency_reason
                ] += 1
                continue

            section_ok, shared_ids = (
                check_section_conflict(
                    state,
                    candidate_series,
                )
            )

            if not section_ok:
                rejection_counter[
                    "SECTION_BLOCK_CONFLICT"
                ] += 1
                continue

            candidate_options = (
                option_index.get(
                    candidate_id,
                    {},
                )
            )

            if not candidate_options:
                rejection_counter[
                    "NO_EXACT_TIME_RESOURCE_OPTIONS"
                ] += 1
                continue

            (
                resources_ok,
                resource_reason,
                proposed_bookings,
                proposed_material,
            ) = choose_resource_bundle(
                state,
                candidate_series,
                candidate_options,
            )

            if not resources_ok:
                rejection_counter[
                    resource_reason
                ] += 1
                continue

            commit_candidate(
                state,
                candidate_series,
                proposed_bookings,
                proposed_material,
                shared_ids,
            )

            selected = True
            break

        if not selected:
            primary_reason = (
                rejection_counter.most_common(
                    1
                )[0][0]
                if rejection_counter
                else "NO_SELECTABLE_CANDIDATE"
            )

            unscheduled_rows.append(
                {
                    "task_id":
                        task_id,

                    "optimizer_status":
                        "UNSCHEDULED_AFTER_OPTIMIZATION",

                    "primary_reason":
                        primary_reason,

                    "reason_counts":
                        "|".join(
                            f"{reason}:{count}"
                            for (
                                reason,
                                count
                            ) in rejection_counter.most_common()
                        ),

                    "v3_11_feasible_candidate_count":
                        len(
                            task_candidates
                        ),

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        INTEGRATION_MODE,
                }
            )

    # Add all canonical tasks that never had any V3.11-feasible candidate.
    all_task_ids = set(
        all_tasks[
            "task_id"
        ].astype(str)
    )

    tasks_with_v3_11_candidates = set(
        prepared_candidates[
            "task_id"
        ].astype(str)
    )

    already_unscheduled = {
        row[
            "task_id"
        ]
        for row in unscheduled_rows
    }

    for task_id in sorted(
        all_task_ids
        - tasks_with_v3_11_candidates
    ):
        if task_id in already_unscheduled:
            continue

        unscheduled_rows.append(
            {
                "task_id":
                    task_id,

                "optimizer_status":
                    "UNSCHEDULED_PRE_OPTIMIZER",

                "primary_reason":
                    "NO_V3_11_FEASIBLE_WINDOW",

                "reason_counts":
                    "NO_V3_11_FEASIBLE_WINDOW:1",

                "v3_11_feasible_candidate_count":
                    0,

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,
            }
        )

    return (
        state,
        pd.DataFrame(
            unscheduled_rows
        ),
    )


# ---------------------------------------------------------------------------
# Coordination realization
# ---------------------------------------------------------------------------

def build_coordination_realization(
    state: OptimizerState,
    ready_integrated_rows: list[dict],
    ready_shadow_rows: list[dict],
) -> pd.DataFrame:
    rows = []

    for row in ready_integrated_rows:
        task_ids = row[
            "_task_ids"
        ]

        start = row[
            "_start"
        ]

        end = row[
            "_end"
        ]

        selected_tasks = []

        for task_id in task_ids:
            scheduled = state.scheduled_by_task.get(
                task_id
            )

            if scheduled is None:
                continue

            scheduled_start = float(
                scheduled[
                    "window_start_minute_week"
                ]
            )

            scheduled_end = float(
                scheduled[
                    "window_end_minute_week"
                ]
            )

            if (
                scheduled_start >= start
                and scheduled_end <= end
            ):
                selected_tasks.append(
                    task_id
                )

        realized = (
            len(
                selected_tasks
            )
            == len(
                task_ids
            )
            and len(
                task_ids
            )
            >= 2
        )

        rows.append(
            {
                "coordination_type":
                    "INTEGRATED",

                "opportunity_id":
                    clean_text(
                        row.get(
                            "integrated_opportunity_id"
                        )
                    ),

                "task_ids":
                    "|".join(
                        task_ids
                    ),

                "selected_task_ids":
                    "|".join(
                        selected_tasks
                    ),

                "required_task_count":
                    len(
                        task_ids
                    ),

                "selected_task_count":
                    len(
                        selected_tasks
                    ),

                "realized":
                    realized,

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,
            }
        )

    for row in ready_shadow_rows:
        host_id = clean_text(
            row.get(
                "host_candidate_window_id"
            )
        )

        shadow_id = clean_text(
            row.get(
                "shadow_candidate_window_id"
            )
        )

        realized = (
            host_id
            in state.scheduled_candidate_ids
            and shadow_id
            in state.scheduled_candidate_ids
        )

        rows.append(
            {
                "coordination_type":
                    "SHADOW",

                "opportunity_id":
                    clean_text(
                        row.get(
                            "shadow_opportunity_id"
                        )
                    ),

                "task_ids":
                    "|".join(
                        [
                            clean_text(
                                row.get(
                                    "host_task_id"
                                )
                            ),
                            clean_text(
                                row.get(
                                    "shadow_task_id"
                                )
                            ),
                        ]
                    ),

                "selected_task_ids":
                    (
                        "|".join(
                            [
                                clean_text(
                                    row.get(
                                        "host_task_id"
                                    )
                                ),
                                clean_text(
                                    row.get(
                                        "shadow_task_id"
                                    )
                                ),
                            ]
                        )
                        if realized
                        else ""
                    ),

                "required_task_count":
                    2,

                "selected_task_count":
                    (
                        2
                        if realized
                        else 0
                    ),

                "realized":
                    realized,

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,
            }
        )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Final validation
# ---------------------------------------------------------------------------

def validate_final_schedule(
    schedule: pd.DataFrame,
    resource_bookings: pd.DataFrame,
    state: OptimizerState,
    predecessors: dict[
        str,
        list[str]
    ],
) -> dict[str, int]:
    duplicate_tasks = int(
        schedule[
            "task_id"
        ].duplicated().sum()
    )

    duplicate_candidates = int(
        schedule[
            "candidate_window_id"
        ].duplicated().sum()
    )

    section_conflicts = 0

    schedule_records = schedule.to_dict(
        orient="records"
    )

    for index_a in range(
        len(
            schedule_records
        )
    ):
        a = schedule_records[
            index_a
        ]

        for index_b in range(
            index_a + 1,
            len(
                schedule_records
            )
        ):
            b = schedule_records[
                index_b
            ]

            if clean_text(
                a.get(
                    "section_id"
                )
            ) != clean_text(
                b.get(
                    "section_id"
                )
            ):
                continue

            start_a = float(
                a[
                    "window_start_minute_week"
                ]
            )
            end_a = float(
                a[
                    "window_end_minute_week"
                ]
            )
            start_b = float(
                b[
                    "window_start_minute_week"
                ]
            )
            end_b = float(
                b[
                    "window_end_minute_week"
                ]
            )

            if not cyclic_overlap(
                start_a,
                end_a,
                start_b,
                end_b,
            ):
                continue

            allowed, _ = (
                can_share_section_via_integrated_block(
                    state,
                    clean_text(
                        a.get(
                            "task_id"
                        )
                    ),
                    start_a,
                    end_a,
                    clean_text(
                        b.get(
                            "task_id"
                        )
                    ),
                    start_b,
                    end_b,
                )
            )

            if not allowed:
                section_conflicts += 1

    resource_conflicts = 0

    if not resource_bookings.empty:
        for (
            resource_id,
            group
        ) in resource_bookings.groupby(
            "resource_id"
        ):
            records = group.to_dict(
                orient="records"
            )

            for index_a in range(
                len(
                    records
                )
            ):
                for index_b in range(
                    index_a + 1,
                    len(
                        records
                    )
                ):
                    a = records[
                        index_a
                    ]
                    b = records[
                        index_b
                    ]

                    if (
                        clean_text(
                            a.get(
                                "task_id"
                            )
                        )
                        == clean_text(
                            b.get(
                                "task_id"
                            )
                        )
                    ):
                        continue

                    if cyclic_overlap(
                        float(
                            a[
                                "booking_start"
                            ]
                        ),
                        float(
                            a[
                                "booking_end"
                            ]
                        ),
                        float(
                            b[
                                "booking_start"
                            ]
                        ),
                        float(
                            b[
                                "booking_end"
                            ]
                        ),
                    ):
                        resource_conflicts += 1

    dependency_violations = 0

    scheduled_lookup = {
        clean_text(
            row[
                "task_id"
            ]
        ):
            row
        for row in schedule_records
    }

    for (
        successor,
        predecessor_ids
    ) in predecessors.items():
        successor_row = scheduled_lookup.get(
            successor
        )

        if successor_row is None:
            continue

        successor_start = float(
            successor_row[
                "window_start_minute_week"
            ]
        )

        for predecessor in predecessor_ids:
            predecessor_row = scheduled_lookup.get(
                predecessor
            )

            if (
                predecessor_row is None
                or float(
                    predecessor_row[
                        "window_end_minute_week"
                    ]
                )
                > successor_start + 1e-9
            ):
                dependency_violations += 1

    material_overdraws = 0

    for (
        inventory_id,
        used
    ) in state.material_used.items():
        available = state.material_stock.get(
            inventory_id,
            0.0,
        )

        if used > available + 1e-9:
            material_overdraws += 1

    return {
        "duplicate_tasks":
            duplicate_tasks,

        "duplicate_candidates":
            duplicate_candidates,

        "section_conflicts":
            section_conflicts,

        "resource_conflicts":
            resource_conflicts,

        "dependency_violations":
            dependency_violations,

        "material_overdraws":
            material_overdraws,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    total_tasks: int,
    schedule: pd.DataFrame,
    unscheduled: pd.DataFrame,
    resource_bookings: pd.DataFrame,
    material_usage: pd.DataFrame,
    coordination: pd.DataFrame,
    validation: dict[str, int],
) -> None:
    scheduled_count = len(
        schedule
    )

    feasibility_rate = (
        100.0
        * scheduled_count
        / total_tasks
        if total_tasks
        else 0.0
    )

    avg_optimizer_score = (
        float(
            schedule[
                "optimizer_score"
            ].mean()
        )
        if scheduled_count
        else 0.0
    )

    avg_maintenance_value = (
        float(
            schedule[
                "maintenance_value_score"
            ].mean()
        )
        if scheduled_count
        else 0.0
    )

    avg_operational_impact = (
        float(
            schedule[
                "prewindow_operational_impact_score"
            ].mean()
        )
        if scheduled_count
        else 0.0
    )

    repositioning_tasks = (
        int(
            schedule[
                "requires_resource_repositioning"
            ]
            .astype(bool)
            .sum()
        )
        if scheduled_count
        else 0
    )

    integrated_realized = 0
    shadow_realized = 0

    if not coordination.empty:
        realized = coordination[
            coordination[
                "realized"
            ].astype(bool)
        ]

        integrated_realized = int(
            (
                realized[
                    "coordination_type"
                ]
                == "INTEGRATED"
            ).sum()
        )

        shadow_realized = int(
            (
                realized[
                    "coordination_type"
                ]
                == "SHADOW"
            ).sum()
        )

    unscheduled_reason_counts = (
        unscheduled[
            "primary_reason"
        ]
        .value_counts()
        .sort_values(
            ascending=False
        )
        if not unscheduled.empty
        else pd.Series(
            dtype="int64"
        )
    )

    lines = [
        "=" * 72,
        "TrackEase V3.12 Resource-Aware Optimizer Report",
        "=" * 72,
        "",
        "OPTIMIZATION SUMMARY",
        "-" * 72,
        f"Canonical maintenance tasks      : {total_tasks:,}",
        f"Scheduled tasks                  : {scheduled_count:,}",
        f"Unscheduled tasks                : {len(unscheduled):,}",
        f"Overall scheduled percentage     : {feasibility_rate:.2f}%",
        f"Resource booking rows            : {len(resource_bookings):,}",
        f"Repositioning-required selections: {repositioning_tasks:,}",
        f"Integrated opportunities realized: {integrated_realized:,}",
        f"Shadow opportunities realized    : {shadow_realized:,}",
        "",
        "SELECTED PLAN QUALITY",
        "-" * 72,
        f"Average optimizer score          : {avg_optimizer_score:.2f}",
        f"Average maintenance value        : {avg_maintenance_value:.2f}",
        f"Average operational impact       : {avg_operational_impact:.2f}",
        "",
        "UNSCHEDULED REASONS",
        "-" * 72,
    ]

    if unscheduled_reason_counts.empty:
        lines.append(
            "None"
        )
    else:
        for (
            reason,
            count
        ) in unscheduled_reason_counts.items():
            lines.append(
                f"{reason:<48} {count:>10,}"
            )

    lines.extend(
        [
            "",
            "FINAL HARD-CONSTRAINT VALIDATION",
            "-" * 72,
            (
                "Duplicate scheduled tasks      : "
                f"{validation['duplicate_tasks']:,}"
            ),
            (
                "Duplicate selected candidates  : "
                f"{validation['duplicate_candidates']:,}"
            ),
            (
                "Invalid section overlaps       : "
                f"{validation['section_conflicts']:,}"
            ),
            (
                "Physical resource overlaps     : "
                f"{validation['resource_conflicts']:,}"
            ),
            (
                "Dependency violations          : "
                f"{validation['dependency_violations']:,}"
            ),
            (
                "Material inventory overdraws   : "
                f"{validation['material_overdraws']:,}"
            ),
            "",
            "OPTIMIZER BOUNDARY",
            "-" * 72,
            (
                "This is a deterministic constraint-aware heuristic. It does "
                "not claim mathematical global optimality."
            ),
            (
                "All selected windows already passed V3.10 train/goods safety "
                "and V3.11 exact resource-time/safety feasibility."
            ),
            (
                "Physical infrastructure fields unavailable from source data "
                "remain review flags and are not fabricated."
            ),
            (
                "Human railway authorization, execution monitoring, testing "
                "and technical handback remain mandatory."
            ),
            "",
            "NEXT STAGES",
            "-" * 72,
            (
                "V3.13 adds emergency + multi-disruption handling. V3.14 then "
                "tests scenario robustness before rolling-horizon replanning."
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
    print("TrackEase V3.12B - Dynamic Resource-Aware Optimizer V3")
    print("=" * 72)

    require_inputs()

    print(
        "\nLoading V3.11-feasible planning data..."
    )

    tasks = pd.read_csv(
        TASKS_FILE,
        low_memory=False,
    )

    candidates = pd.read_csv(
        CANDIDATES_FILE,
        low_memory=False,
    )

    feasibility = pd.read_csv(
        FEASIBILITY_FILE,
        low_memory=False,
    )

    resource_options = pd.read_csv(
        RESOURCE_OPTIONS_FILE,
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

    machines = pd.read_csv(
        MACHINES_FILE,
        low_memory=False,
    )

    materials = pd.read_csv(
        MATERIAL_FILE,
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

    compatibility = pd.read_csv(
        COMPATIBILITY_FILE,
        low_memory=False,
    )

    require_columns(
        tasks,
        [
            "task_id",
        ],
        "V3 maintenance tasks",
    )

    all_task_ids = set(
        tasks[
            "task_id"
        ].astype(str)
    )

    print(
        f"Canonical tasks             : {len(tasks):,}"
    )

    print(
        f"V3.10 candidate windows     : {len(candidates):,}"
    )

    print(
        f"V3.11 feasibility rows      : {len(feasibility):,}"
    )

    print(
        f"Exact-time resource options : {len(resource_options):,}"
    )

    print(
        f"Task dependencies           : {len(dependencies):,}"
    )

    parallel_pairs = (
        build_parallel_pair_index(
            compatibility
        )
    )

    (
        integrated_pair_intervals,
        ready_integrated_rows,
    ) = build_integrated_indexes(
        integrated,
        parallel_pairs,
    )

    (
        shadow_candidate_ids,
        ready_shadow_rows,
    ) = build_shadow_indexes(
        shadow
    )

    print(
        "\nPreparing optimizer candidate scores..."
    )

    prepared_candidates = (
        prepare_candidates(
            candidates,
            feasibility,
            shadow_candidate_ids,
            ready_integrated_rows,
        )
    )

    print(
        f"V3.11-feasible windows      : {len(prepared_candidates):,}"
    )

    print(
        f"Tasks entering optimizer    : "
        f"{prepared_candidates['task_id'].nunique():,}"
    )

    print(
        f"Ready integrated windows    : {len(ready_integrated_rows):,}"
    )

    print(
        f"Ready shadow relationships  : {len(ready_shadow_rows):,}"
    )

    option_index = (
        build_option_index(
            resource_options
        )
    )

    (
        predecessors,
        dependency_depth,
    ) = build_dependency_graph(
        all_task_ids,
        dependencies,
    )

    (
        crew_limits,
        machine_limits,
    ) = build_resource_limits(
        crews,
        machines,
    )

    material_stock = (
        build_material_stock(
            materials
        )
    )

    print(
        "\nRunning deterministic resource-aware optimization..."
    )

    (
        state,
        unscheduled,
    ) = optimize(
        tasks,
        prepared_candidates,
        option_index,
        predecessors,
        dependency_depth,
        crew_limits,
        machine_limits,
        material_stock,
        integrated_pair_intervals,
    )

    schedule = pd.DataFrame(
        state.schedule_rows
    )

    if not schedule.empty:
        schedule = schedule.sort_values(
            by=[
                "window_start_minute_week",
                "section_id",
                "task_id",
            ],
            kind="stable",
        ).reset_index(
            drop=True
        )

    resource_bookings = pd.DataFrame(
        state.resource_booking_rows
    )

    material_rows = []

    for inventory_id in sorted(
        state.material_stock
    ):
        available = state.material_stock[
            inventory_id
        ]

        used = state.material_used.get(
            inventory_id,
            0.0,
        )

        if used <= 0:
            continue

        material_rows.append(
            {
                "inventory_id":
                    inventory_id,

                "quantity_available":
                    available,

                "quantity_allocated":
                    used,

                "quantity_remaining":
                    available
                    - used,

                "overdrawn":
                    used
                    > available
                    + 1e-9,

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,
            }
        )

    material_usage = pd.DataFrame(
        material_rows
    )

    coordination = (
        build_coordination_realization(
            state,
            ready_integrated_rows,
            ready_shadow_rows,
        )
    )

    validation = validate_final_schedule(
        schedule,
        resource_bookings,
        state,
        predecessors,
    )

    hard_failure_total = sum(
        validation.values()
    )

    if hard_failure_total:
        raise RuntimeError(
            "Optimizer produced a hard-constraint violation. "
            f"Validation: {validation}"
        )

    schedule.to_csv(
        SCHEDULE_OUTPUT,
        index=False,
    )

    unscheduled.to_csv(
        UNSCHEDULED_OUTPUT,
        index=False,
    )

    resource_bookings.to_csv(
        RESOURCE_BOOKINGS_OUTPUT,
        index=False,
    )

    material_usage.to_csv(
        MATERIAL_USAGE_OUTPUT,
        index=False,
    )

    coordination.to_csv(
        COORDINATION_OUTPUT,
        index=False,
    )

    write_report(
        len(
            tasks
        ),
        schedule,
        unscheduled,
        resource_bookings,
        material_usage,
        coordination,
        validation,
    )

    integrated_realized = (
        int(
            (
                coordination[
                    "coordination_type"
                ].eq(
                    "INTEGRATED"
                )
                & coordination[
                    "realized"
                ].astype(bool)
            ).sum()
        )
        if not coordination.empty
        else 0
    )

    shadow_realized = (
        int(
            (
                coordination[
                    "coordination_type"
                ].eq(
                    "SHADOW"
                )
                & coordination[
                    "realized"
                ].astype(bool)
            ).sum()
        )
        if not coordination.empty
        else 0
    )

    print(
        "\n"
        + "=" * 72
    )

    print(
        "V3.12B DYNAMIC RESOURCE-AWARE OPTIMIZATION COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        f"\nScheduled tasks             : {len(schedule):,}"
    )

    print(
        f"Unscheduled tasks           : {len(unscheduled):,}"
    )

    print(
        f"Optimizer scheduling rate   : "
        f"{(100.0 * len(schedule) / len(tasks)):.2f}%"
    )

    print(
        f"Integrated opportunities    : {integrated_realized:,}"
    )

    print(
        f"Shadow opportunities        : {shadow_realized:,}"
    )

    print(
        "\nHard-constraint validation:"
    )

    print(
        f"  Duplicate tasks           : {validation['duplicate_tasks']:,}"
    )

    print(
        f"  Invalid section overlaps  : {validation['section_conflicts']:,}"
    )

    print(
        f"  Resource overlaps         : {validation['resource_conflicts']:,}"
    )

    print(
        f"  Dependency violations     : {validation['dependency_violations']:,}"
    )

    print(
        f"  Material overdraws        : {validation['material_overdraws']:,}"
    )

    print(
        "\nOutputs:"
    )

    for path in [
        SCHEDULE_OUTPUT,
        UNSCHEDULED_OUTPUT,
        RESOURCE_BOOKINGS_OUTPUT,
        MATERIAL_USAGE_OUTPUT,
        COORDINATION_OUTPUT,
        REPORT_OUTPUT,
    ]:
        print(
            f"  {path}"
        )

    print(
        "\nTrackEase V3 now has a conflict-free resource-aware optimized "
        "weekly planning layer ready for disruption and robustness testing."
    )


if __name__ == "__main__":
    main()
