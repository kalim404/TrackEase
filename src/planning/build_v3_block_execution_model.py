"""
TrackEase V3.6 - Block Requirement & Detailed Execution Timing Model

Purpose
-------
Translate each canonical maintenance task into the operational block
requirements and detailed execution-time components needed for realistic block
planning.

This stage models concepts identified in the TrackEase research:
    - traffic block
    - power block
    - disconnection
    - integrated-block eligibility
    - shadow/opportunity-block eligibility
    - emergency planning mode
    - setup time
    - minimum continuous work time
    - core work duration
    - dismantling / restoration preparation
    - testing / inspection
    - clearance
    - handback

Important design decision
-------------------------
Traffic / power / disconnection are operational restrictions.

Integrated block and shadow block are coordination arrangements, not simply
substitutes for the underlying safety restrictions. Therefore this module keeps
them as separate eligibility fields.

Existing V2/V3 files are read-only. All derived fields are deterministic and
explicitly provenance-labelled as TrackEase prototype planning rules.

Inputs
------
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_task_execution_requirements.csv
    data/processed/v3_task_resource_feasibility.csv

Outputs
-------
    data/processed/v3_task_block_requirements.csv
    data/processed/v3_task_timing_components.csv
    data/processed/v3_block_type_rules.csv
    data/processed/v3_block_execution_model_report.txt
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"
EXECUTION_REQUIREMENTS_FILE = (
    PROCESSED_DIR / "v3_task_execution_requirements.csv"
)
RESOURCE_FEASIBILITY_FILE = (
    PROCESSED_DIR / "v3_task_resource_feasibility.csv"
)

BLOCK_REQUIREMENTS_OUTPUT = (
    PROCESSED_DIR / "v3_task_block_requirements.csv"
)
TIMING_OUTPUT = (
    PROCESSED_DIR / "v3_task_timing_components.csv"
)
BLOCK_RULES_OUTPUT = (
    PROCESSED_DIR / "v3_block_type_rules.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_block_execution_model_report.txt"
)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

DATA_ORIGIN = "TRACKEASE_V3_DERIVED_BLOCK_MODEL"
INTEGRATION_MODE = "PROTOTYPE_BLOCK_EXECUTION_RULE_MODEL"


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


def require_inputs() -> None:
    required = [
        TASKS_FILE,
        EXECUTION_REQUIREMENTS_FILE,
        RESOURCE_FEASIBILITY_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.6 input files are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


def canonical_departments(value: object) -> list[str]:
    text = clean_text(
        value
    ).upper()

    result: list[str] = []

    if (
        "ENGINEERING" in text
        or "TMS" in text
    ):
        result.append(
            "Engineering"
        )

    if (
        "S&T" in text
        or "SIGNAL" in text
        or "SMMS" in text
    ):
        result.append(
            "S&T"
        )

    if (
        "ELECTRICAL" in text
        or "TDMS" in text
        or "TRACTION" in text
        or "OHE" in text
    ):
        result.append(
            "Electrical"
        )

    if not result:
        result.append(
            "Engineering"
        )

    return list(
        dict.fromkeys(
            result
        )
    )


# ---------------------------------------------------------------------------
# Block requirement rules
# ---------------------------------------------------------------------------

def determine_disconnection_requirement(
    departments: list[str],
    task_name: str,
    task_type: str,
) -> tuple[bool, str]:
    """
    Conservatively infer S&T disconnection needs.

    Because the source task data does not contain official equipment-level
    disconnection instructions, this is an explicit prototype rule.
    """

    if "S&T" not in departments:
        return False, "NOT_S_AND_T_WORK"

    text = (
        f"{task_name} {task_type}"
        .upper()
    )

    strong_markers = [
        "SIGNAL",
        "POINT",
        "INTERLOCK",
        "TRACK CIRCUIT",
        "AXLE",
        "TELECOM",
        "CABLE",
        "CORRECTIVE",
        "FAILURE",
        "DEFECT",
    ]

    if any(
        marker in text
        for marker in strong_markers
    ):
        return (
            True,
            "PROTOTYPE_S_AND_T_DISCONNECTION_RULE",
        )

    # Maintenance on S&T assets still requires explicit review even when
    # the coarse source text cannot prove that disconnection is mandatory.
    return (
        False,
        "S_AND_T_DISCONNECTION_REVIEW_REQUIRED",
    )


def classify_block_requirement(
    requires_traffic: bool,
    requires_power: bool,
    requires_disconnection: bool,
) -> str:

    if (
        requires_traffic
        and requires_power
        and requires_disconnection
    ):
        return (
            "TRAFFIC_POWER_DISCONNECTION"
        )

    if (
        requires_traffic
        and requires_power
    ):
        return "TRAFFIC_POWER_BLOCK"

    if (
        requires_traffic
        and requires_disconnection
    ):
        return (
            "TRAFFIC_DISCONNECTION_BLOCK"
        )

    if (
        requires_power
        and requires_disconnection
    ):
        return (
            "POWER_DISCONNECTION_BLOCK"
        )

    if requires_traffic:
        return "TRAFFIC_BLOCK"

    if requires_power:
        return "POWER_BLOCK"

    if requires_disconnection:
        return "DISCONNECTION"

    return "NO_FORMAL_BLOCK_REQUIRED"


def derive_block_requirements(
    tasks: pd.DataFrame,
    execution: pd.DataFrame,
    resource_feasibility: pd.DataFrame,
) -> pd.DataFrame:

    execution_columns = [
        "task_id",
        "departments_required",
        "requires_possession",
        "requires_power_isolation",
        "requires_protection_staff",
    ]

    missing_execution_columns = [
        column
        for column in execution_columns
        if column not in execution.columns
    ]

    if missing_execution_columns:
        raise ValueError(
            "v3_task_execution_requirements.csv is missing columns: "
            + ", ".join(
                missing_execution_columns
            )
        )

    feasibility_columns = [
        "task_id",
        "resource_precheck_passed",
        "requires_resource_repositioning",
        "requires_dependency_sequence",
        "resource_feasibility_status",
    ]

    available_feasibility_columns = [
        column
        for column in feasibility_columns
        if column in resource_feasibility.columns
    ]

    merged = tasks.merge(
        execution[
            execution_columns
        ],
        on="task_id",
        how="left",
        validate="one_to_one",
        suffixes=(
            "",
            "_execution",
        ),
    )

    merged = merged.merge(
        resource_feasibility[
            available_feasibility_columns
        ],
        on="task_id",
        how="left",
        validate="one_to_one",
    )

    section_department_count = (
        merged.assign(
            _department_set=merged[
                "departments_required"
            ]
            .fillna(
                merged["department"]
            )
            .map(
                lambda value: set(
                    canonical_departments(
                        value
                    )
                )
            )
        )
        .groupby(
            "section_id"
        )["_department_set"]
        .apply(
            lambda values: len(
                set().union(
                    *values
                )
                if len(values)
                else set()
            )
        )
        .to_dict()
    )

    section_task_count = (
        merged.groupby(
            "section_id"
        )
        .size()
        .to_dict()
    )

    rows = []

    for row in merged.itertuples(
        index=False
    ):
        task_id = clean_text(
            row.task_id
        )
        task_type = clean_text(
            row.task_type
        ).upper()
        task_name = clean_text(
            row.task_name
        )
        section_id = clean_text(
            row.section_id
        )

        departments = canonical_departments(
            getattr(
                row,
                "departments_required",
                row.department,
            )
        )

        requires_traffic = bool_value(
            getattr(
                row,
                "requires_possession",
                True,
            ),
            default=True,
        )

        requires_power = bool_value(
            getattr(
                row,
                "requires_power_isolation",
                False,
            ),
            default=False,
        )

        (
            requires_disconnection,
            disconnection_basis,
        ) = determine_disconnection_requirement(
            departments,
            task_name,
            task_type,
        )

        primary_requirement = (
            classify_block_requirement(
                requires_traffic,
                requires_power,
                requires_disconnection,
            )
        )

        is_emergency = (
            task_type == "EMERGENCY"
        )

        same_section_task_count = int(
            section_task_count.get(
                section_id,
                1,
            )
        )

        same_section_department_count = int(
            section_department_count.get(
                section_id,
                len(
                    departments
                ),
            )
        )

        integrated_eligible = (
            same_section_task_count >= 2
            and (
                same_section_department_count >= 2
                or len(
                    departments
                ) >= 2
            )
        )

        # Shadow/opportunity eligibility does not mean authorization. It only
        # means the job may be considered if another compatible possession
        # creates a safe window.
        shadow_eligible = (
            not is_emergency
            and requires_traffic
            and task_type
            in {
                "INSPECTION",
                "PREVENTIVE",
                "URGENT_PLANNED",
                "CORRECTIVE",
            }
        )

        if is_emergency:
            planning_mode = (
                "EMERGENCY_INSERTION"
            )
        elif integrated_eligible:
            planning_mode = (
                "INTEGRATED_BLOCK_CANDIDATE"
            )
        else:
            planning_mode = (
                "STANDARD_PLANNED_BLOCK"
            )

        requires_post_work_testing = (
            (
                "S&T" in departments
            )
            or (
                "Electrical"
                in departments
            )
            or task_type
            in {
                "CORRECTIVE",
                "EMERGENCY",
            }
        )

        requires_technical_handback = (
            requires_traffic
            or requires_power
            or requires_disconnection
        )

        resource_precheck_passed = bool_value(
            getattr(
                row,
                "resource_precheck_passed",
                True,
            ),
            default=True,
        )

        requires_repositioning = bool_value(
            getattr(
                row,
                "requires_resource_repositioning",
                False,
            )
        )

        requires_sequence = bool_value(
            getattr(
                row,
                "requires_dependency_sequence",
                False,
            )
        )

        rows.append(
            {
                "task_id":
                    task_id,

                "request_id":
                    clean_text(
                        row.request_id
                    ),

                "asset_id":
                    clean_text(
                        row.asset_id
                    ),

                "section_id":
                    section_id,

                "task_name":
                    task_name,

                "task_type":
                    task_type,

                "departments_required":
                    "|".join(
                        departments
                    ),

                "requires_traffic_block":
                    requires_traffic,

                "requires_power_block":
                    requires_power,

                "requires_disconnection":
                    requires_disconnection,

                "disconnection_requirement_basis":
                    disconnection_basis,

                "primary_block_requirement":
                    primary_requirement,

                "planning_mode":
                    planning_mode,

                "emergency_block":
                    is_emergency,

                "eligible_for_integrated_block":
                    integrated_eligible,

                "eligible_for_shadow_block":
                    shadow_eligible,

                "same_section_task_count":
                    same_section_task_count,

                "same_section_department_count":
                    same_section_department_count,

                "requires_protection_staff":
                    bool_value(
                        getattr(
                            row,
                            "requires_protection_staff",
                            True,
                        ),
                        default=True,
                    ),

                "requires_post_work_testing":
                    requires_post_work_testing,

                "requires_technical_handback":
                    requires_technical_handback,

                "resource_precheck_passed":
                    resource_precheck_passed,

                "requires_resource_repositioning":
                    requires_repositioning,

                "requires_dependency_sequence":
                    requires_sequence,

                "block_authority_mode":
                    "HUMAN_AUTHORIZATION_REQUIRED",

                "safety_gate_mode":
                    "HARD_CONSTRAINT",

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,

                "is_prototype_derived":
                    True,
            }
        )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Detailed execution timing rules
# ---------------------------------------------------------------------------

def timing_components(
    task_type: str,
    departments: list[str],
    requires_power: bool,
    requires_disconnection: bool,
    requires_testing: bool,
) -> dict[str, int | bool]:
    """
    Deterministic prototype overhead model.

    Values are planning assumptions for TrackEase demonstration and are not
    represented as official Indian Railways standard times.
    """

    if task_type == "INSPECTION":
        setup = 10
        dismantling = 5
        clearance = 5
        handback = 5
        splittable = True
    elif task_type == "PREVENTIVE":
        setup = 15
        dismantling = 10
        clearance = 10
        handback = 10
        splittable = True
    elif task_type == "URGENT_PLANNED":
        setup = 20
        dismantling = 15
        clearance = 10
        handback = 15
        splittable = False
    elif task_type == "CORRECTIVE":
        setup = 25
        dismantling = 15
        clearance = 15
        handback = 15
        splittable = False
    elif task_type == "EMERGENCY":
        setup = 15
        dismantling = 15
        clearance = 15
        handback = 15
        splittable = False
    else:
        setup = 15
        dismantling = 10
        clearance = 10
        handback = 10
        splittable = False

    # Multi-department mobilization requires additional coordination.
    if len(
        departments
    ) >= 2:
        setup += 10

    power_isolation_setup = (
        15
        if requires_power
        else 0
    )

    disconnection_setup = (
        10
        if requires_disconnection
        else 0
    )

    if not requires_testing:
        testing = 0
    elif (
        "S&T" in departments
        and "Electrical" in departments
    ):
        testing = 25
    elif "S&T" in departments:
        testing = 20
    elif "Electrical" in departments:
        testing = 15
    else:
        testing = 10

    return {
        "setup_minutes":
            setup,

        "power_isolation_setup_minutes":
            power_isolation_setup,

        "disconnection_setup_minutes":
            disconnection_setup,

        "dismantling_restoration_minutes":
            dismantling,

        "testing_inspection_minutes":
            testing,

        "clearance_minutes":
            clearance,

        "handback_minutes":
            handback,

        "work_splittable":
            splittable,
    }


def build_timing_model(
    tasks: pd.DataFrame,
    block_requirements: pd.DataFrame,
) -> pd.DataFrame:

    timing_source_columns = [
        "task_id",
        "minimum_duration_min",
        "expected_duration_min",
        "maximum_duration_min",
        "minimum_continuous_time_min",
    ]

    missing_columns = [
        column
        for column in timing_source_columns
        if column not in tasks.columns
    ]

    if missing_columns:
        raise ValueError(
            "v3_maintenance_tasks.csv is missing timing columns: "
            + ", ".join(
                missing_columns
            )
        )

    merged = block_requirements.merge(
        tasks[
            timing_source_columns
        ],
        on="task_id",
        how="left",
        validate="one_to_one",
    )

    rows = []

    for row in merged.itertuples(
        index=False
    ):
        departments = canonical_departments(
            row.departments_required
        )

        components = timing_components(
            clean_text(
                row.task_type
            ).upper(),
            departments,
            bool_value(
                row.requires_power_block
            ),
            bool_value(
                row.requires_disconnection
            ),
            bool_value(
                row.requires_post_work_testing
            ),
        )

        minimum_core = int(
            row.minimum_duration_min
        )

        expected_core = int(
            row.expected_duration_min
        )

        maximum_core = int(
            row.maximum_duration_min
        )

        fixed_overhead = sum(
            [
                int(
                    components[
                        "setup_minutes"
                    ]
                ),
                int(
                    components[
                        "power_isolation_setup_minutes"
                    ]
                ),
                int(
                    components[
                        "disconnection_setup_minutes"
                    ]
                ),
                int(
                    components[
                        "dismantling_restoration_minutes"
                    ]
                ),
                int(
                    components[
                        "testing_inspection_minutes"
                    ]
                ),
                int(
                    components[
                        "clearance_minutes"
                    ]
                ),
                int(
                    components[
                        "handback_minutes"
                    ]
                ),
            ]
        )

        minimum_total = (
            minimum_core
            + fixed_overhead
        )

        expected_total = (
            expected_core
            + fixed_overhead
        )

        maximum_total = (
            maximum_core
            + fixed_overhead
        )

        source_min_continuous = int(
            row.minimum_continuous_time_min
        )

        if bool(
            components[
                "work_splittable"
            ]
        ):
            minimum_continuous_core = min(
                expected_core,
                max(
                    30,
                    source_min_continuous,
                ),
            )
        else:
            minimum_continuous_core = (
                expected_core
            )

        minimum_continuous_possession = (
            minimum_continuous_core
            + fixed_overhead
        )

        rows.append(
            {
                "task_id":
                    row.task_id,

                "section_id":
                    row.section_id,

                "task_type":
                    row.task_type,

                "primary_block_requirement":
                    row.primary_block_requirement,

                "core_work_min_minutes":
                    minimum_core,

                "core_work_expected_minutes":
                    expected_core,

                "core_work_max_minutes":
                    maximum_core,

                **components,

                "fixed_execution_overhead_minutes":
                    fixed_overhead,

                "total_block_min_minutes":
                    minimum_total,

                "total_block_expected_minutes":
                    expected_total,

                "total_block_max_minutes":
                    maximum_total,

                "minimum_continuous_core_work_minutes":
                    minimum_continuous_core,

                "minimum_continuous_possession_minutes":
                    minimum_continuous_possession,

                "timing_model_status":
                    "READY_FOR_BLOCK_WINDOW_MATCHING",

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,

                "is_prototype_derived":
                    True,
            }
        )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Block-type / coordination rule catalog
# ---------------------------------------------------------------------------

def build_block_type_rules() -> pd.DataFrame:
    rows = [
        {
            "rule_id":
                "BLOCKTYPE-001",
            "concept":
                "TRAFFIC_BLOCK",
            "category":
                "OPERATIONAL_RESTRICTION",
            "description":
                "Train movement over the affected line or route is stopped "
                "or restricted for the maintenance work.",
            "requires_human_authorization":
                True,
            "hard_safety_gate":
                True,
        },
        {
            "rule_id":
                "BLOCKTYPE-002",
            "concept":
                "POWER_BLOCK",
            "category":
                "OPERATIONAL_RESTRICTION",
            "description":
                "Traction power isolation or shutdown is required before "
                "work may safely proceed.",
            "requires_human_authorization":
                True,
            "hard_safety_gate":
                True,
        },
        {
            "rule_id":
                "BLOCKTYPE-003",
            "concept":
                "DISCONNECTION",
            "category":
                "OPERATIONAL_RESTRICTION",
            "description":
                "Signal, telecom or other operational equipment requires "
                "authorized temporary disconnection or isolation.",
            "requires_human_authorization":
                True,
            "hard_safety_gate":
                True,
        },
        {
            "rule_id":
                "BLOCKTYPE-004",
            "concept":
                "INTEGRATED_BLOCK",
            "category":
                "COORDINATION_ARRANGEMENT",
            "description":
                "Compatible work from multiple departments is coordinated "
                "within one jointly feasible block.",
            "requires_human_authorization":
                True,
            "hard_safety_gate":
                True,
        },
        {
            "rule_id":
                "BLOCKTYPE-005",
            "concept":
                "SHADOW_BLOCK",
            "category":
                "OPPORTUNITY_ARRANGEMENT",
            "description":
                "Compatible maintenance may use an already-created safe "
                "operational opportunity, subject to full compatibility, "
                "resource and authorization checks.",
            "requires_human_authorization":
                True,
            "hard_safety_gate":
                True,
        },
        {
            "rule_id":
                "BLOCKTYPE-006",
            "concept":
                "EMERGENCY_BLOCK",
            "category":
                "EMERGENCY_ARRANGEMENT",
            "description":
                "Urgent safety-critical work is inserted through an "
                "emergency planning and authorization path.",
            "requires_human_authorization":
                True,
            "hard_safety_gate":
                True,
        },
    ]

    rules = pd.DataFrame(
        rows
    )

    rules[
        "rule_source"
    ] = (
        "TRACKEASE_RESEARCH_DERIVED_PROTOTYPE_POLICY"
    )

    rules[
        "integration_mode"
    ] = INTEGRATION_MODE

    return rules


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_outputs(
    tasks: pd.DataFrame,
    block_requirements: pd.DataFrame,
    timing: pd.DataFrame,
    rules: pd.DataFrame,
) -> dict[str, int]:

    valid_primary_requirements = {
        "TRAFFIC_POWER_DISCONNECTION",
        "TRAFFIC_POWER_BLOCK",
        "TRAFFIC_DISCONNECTION_BLOCK",
        "POWER_DISCONNECTION_BLOCK",
        "TRAFFIC_BLOCK",
        "POWER_BLOCK",
        "DISCONNECTION",
        "NO_FORMAL_BLOCK_REQUIRED",
    }

    checks = {
        "tasks":
            len(
                tasks
            ),

        "block_requirement_rows":
            len(
                block_requirements
            ),

        "timing_rows":
            len(
                timing
            ),

        "block_rules":
            len(
                rules
            ),

        "duplicate_block_task_ids":
            int(
                block_requirements[
                    "task_id"
                ]
                .duplicated()
                .sum()
            ),

        "duplicate_timing_task_ids":
            int(
                timing[
                    "task_id"
                ]
                .duplicated()
                .sum()
            ),

        "tasks_missing_block_requirement":
            int(
                (
                    ~tasks[
                        "task_id"
                    ]
                    .astype(
                        str
                    )
                    .isin(
                        block_requirements[
                            "task_id"
                        ]
                        .astype(
                            str
                        )
                    )
                )
                .sum()
            ),

        "tasks_missing_timing":
            int(
                (
                    ~tasks[
                        "task_id"
                    ]
                    .astype(
                        str
                    )
                    .isin(
                        timing[
                            "task_id"
                        ]
                        .astype(
                            str
                        )
                    )
                )
                .sum()
            ),

        "invalid_block_requirement":
            int(
                (
                    ~block_requirements[
                        "primary_block_requirement"
                    ]
                    .isin(
                        valid_primary_requirements
                    )
                )
                .sum()
            ),

        "invalid_total_duration_order":
            int(
                (
                    (
                        timing[
                            "total_block_min_minutes"
                        ]
                        >
                        timing[
                            "total_block_expected_minutes"
                        ]
                    )
                    |
                    (
                        timing[
                            "total_block_expected_minutes"
                        ]
                        >
                        timing[
                            "total_block_max_minutes"
                        ]
                    )
                )
                .sum()
            ),

        "invalid_minimum_continuous_duration":
            int(
                (
                    timing[
                        "minimum_continuous_possession_minutes"
                    ]
                    >
                    timing[
                        "total_block_expected_minutes"
                    ]
                )
                .sum()
            ),

        "non_human_authorized_rows":
            int(
                (
                    block_requirements[
                        "block_authority_mode"
                    ]
                    !=
                    "HUMAN_AUTHORIZATION_REQUIRED"
                )
                .sum()
            ),

        "non_hard_safety_rows":
            int(
                (
                    block_requirements[
                        "safety_gate_mode"
                    ]
                    !=
                    "HARD_CONSTRAINT"
                )
                .sum()
            ),
    }

    hard_failure_keys = [
        "duplicate_block_task_ids",
        "duplicate_timing_task_ids",
        "tasks_missing_block_requirement",
        "tasks_missing_timing",
        "invalid_block_requirement",
        "invalid_total_duration_order",
        "invalid_minimum_continuous_duration",
        "non_human_authorized_rows",
        "non_hard_safety_rows",
    ]

    if (
        len(
            block_requirements
        )
        != len(
            tasks
        )
    ):
        raise RuntimeError(
            "Block requirement model must contain exactly one row per task."
        )

    if (
        len(
            timing
        )
        != len(
            tasks
        )
    ):
        raise RuntimeError(
            "Timing model must contain exactly one row per task."
        )

    if sum(
        checks[
            key
        ]
        for key in hard_failure_keys
    ):
        raise RuntimeError(
            "V3.6 block execution model integrity validation failed."
        )

    return checks


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(
    block_requirements: pd.DataFrame,
    timing: pd.DataFrame,
    checks: dict[str, int],
) -> None:

    block_counts = (
        block_requirements[
            "primary_block_requirement"
        ]
        .value_counts()
        .sort_index()
    )

    planning_mode_counts = (
        block_requirements[
            "planning_mode"
        ]
        .value_counts()
        .sort_index()
    )

    integrated_count = int(
        block_requirements[
            "eligible_for_integrated_block"
        ]
        .astype(
            bool
        )
        .sum()
    )

    shadow_count = int(
        block_requirements[
            "eligible_for_shadow_block"
        ]
        .astype(
            bool
        )
        .sum()
    )

    emergency_count = int(
        block_requirements[
            "emergency_block"
        ]
        .astype(
            bool
        )
        .sum()
    )

    splittable_count = int(
        timing[
            "work_splittable"
        ]
        .astype(
            bool
        )
        .sum()
    )

    lines = [
        "=" * 72,
        "TrackEase V3.6 Block Requirement & Execution Timing Report",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Maintenance tasks                : {checks['tasks']:,}",
        f"Block requirement records        : {checks['block_requirement_rows']:,}",
        f"Timing records                   : {checks['timing_rows']:,}",
        f"Integrated-block eligible tasks  : {integrated_count:,}",
        f"Shadow/opportunity eligible tasks: {shadow_count:,}",
        f"Emergency tasks in current data  : {emergency_count:,}",
        f"Splittable tasks                 : {splittable_count:,}",
        "",
        "PRIMARY BLOCK REQUIREMENTS",
        "-" * 72,
    ]

    for name, count in block_counts.items():
        lines.append(
            f"{name:<42} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "PLANNING MODES",
            "-" * 72,
        ]
    )

    for name, count in planning_mode_counts.items():
        lines.append(
            f"{name:<42} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "TIMING",
            "-" * 72,
            (
                "Average expected core work min  : "
                f"{timing['core_work_expected_minutes'].mean():.2f}"
            ),
            (
                "Average fixed overhead min      : "
                f"{timing['fixed_execution_overhead_minutes'].mean():.2f}"
            ),
            (
                "Average expected total block min: "
                f"{timing['total_block_expected_minutes'].mean():.2f}"
            ),
            (
                "Maximum expected total block min: "
                f"{timing['total_block_expected_minutes'].max():,.0f}"
            ),
            "",
            "INTEGRITY",
            "-" * 72,
            (
                "Duplicate block task IDs        : "
                f"{checks['duplicate_block_task_ids']:,}"
            ),
            (
                "Duplicate timing task IDs       : "
                f"{checks['duplicate_timing_task_ids']:,}"
            ),
            (
                "Tasks missing block requirement : "
                f"{checks['tasks_missing_block_requirement']:,}"
            ),
            (
                "Tasks missing timing            : "
                f"{checks['tasks_missing_timing']:,}"
            ),
            (
                "Invalid duration ordering       : "
                f"{checks['invalid_total_duration_order']:,}"
            ),
            (
                "Invalid continuous duration     : "
                f"{checks['invalid_minimum_continuous_duration']:,}"
            ),
            (
                "Non-human authorization rows    : "
                f"{checks['non_human_authorized_rows']:,}"
            ),
            (
                "Non-hard-safety rows            : "
                f"{checks['non_hard_safety_rows']:,}"
            ),
            "",
            "IMPORTANT INTERPRETATION",
            "-" * 72,
            (
                "Traffic block, power block and disconnection are modeled as "
                "operational restrictions."
            ),
            (
                "Integrated and shadow blocks are modeled as coordination or "
                "opportunity arrangements that still retain all underlying "
                "safety, resource and authorization requirements."
            ),
            (
                "Timing overheads are deterministic TrackEase prototype "
                "planning assumptions; they are not presented as official "
                "Indian Railways standard times."
            ),
            (
                "TrackEase recommends and validates candidate arrangements; "
                "it does not grant or authorize a railway block."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build the multi-department compatibility graph to decide "
                "whether same/adjacent-section tasks may run in parallel, "
                "sequentially, under common isolation, as an integrated block, "
                "or must remain incompatible."
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
        "TrackEase V3.6 - Block Requirement & Detailed Execution Timing"
    )
    print("=" * 72)

    require_inputs()

    print(
        "\nLoading canonical tasks, execution requirements and resource "
        "feasibility..."
    )

    tasks = pd.read_csv(
        TASKS_FILE,
        low_memory=False,
    )

    execution = pd.read_csv(
        EXECUTION_REQUIREMENTS_FILE,
        low_memory=False,
    )

    resource_feasibility = pd.read_csv(
        RESOURCE_FEASIBILITY_FILE,
        low_memory=False,
    )

    print(
        f"Tasks loaded                 : {len(tasks):,}"
    )

    print(
        "Building operational block requirements..."
    )

    block_requirements = (
        derive_block_requirements(
            tasks,
            execution,
            resource_feasibility,
        )
    )

    print(
        "Building detailed execution timing components..."
    )

    timing = build_timing_model(
        tasks,
        block_requirements,
    )

    print(
        "Building block-type rule catalog..."
    )

    rules = (
        build_block_type_rules()
    )

    checks = validate_outputs(
        tasks,
        block_requirements,
        timing,
        rules,
    )

    block_requirements.to_csv(
        BLOCK_REQUIREMENTS_OUTPUT,
        index=False,
    )

    timing.to_csv(
        TIMING_OUTPUT,
        index=False,
    )

    rules.to_csv(
        BLOCK_RULES_OUTPUT,
        index=False,
    )

    write_report(
        block_requirements,
        timing,
        checks,
    )

    print(
        "\n"
        + "=" * 72
    )

    print(
        "V3.6 BLOCK EXECUTION MODEL COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        f"\nBlock requirement rows       : "
        f"{len(block_requirements):,}"
    )

    print(
        f"Timing rows                  : "
        f"{len(timing):,}"
    )

    print(
        f"Integrated-block eligible    : "
        f"{int(block_requirements['eligible_for_integrated_block'].sum()):,}"
    )

    print(
        f"Shadow/opportunity eligible  : "
        f"{int(block_requirements['eligible_for_shadow_block'].sum()):,}"
    )

    print(
        f"Emergency tasks              : "
        f"{int(block_requirements['emergency_block'].sum()):,}"
    )

    print(
        f"Splittable tasks             : "
        f"{int(timing['work_splittable'].sum()):,}"
    )

    print(
        "\nIntegrity:"
    )

    print(
        f"  Duplicate block task IDs      : "
        f"{checks['duplicate_block_task_ids']:,}"
    )

    print(
        f"  Duplicate timing task IDs     : "
        f"{checks['duplicate_timing_task_ids']:,}"
    )

    print(
        f"  Missing block requirements    : "
        f"{checks['tasks_missing_block_requirement']:,}"
    )

    print(
        f"  Missing timing rows           : "
        f"{checks['tasks_missing_timing']:,}"
    )

    print(
        f"  Invalid duration ordering     : "
        f"{checks['invalid_total_duration_order']:,}"
    )

    print(
        f"  Non-human authorization rows  : "
        f"{checks['non_human_authorized_rows']:,}"
    )

    print(
        "\nOutputs:"
    )

    print(
        f"  {BLOCK_REQUIREMENTS_OUTPUT}"
    )

    print(
        f"  {TIMING_OUTPUT}"
    )

    print(
        f"  {BLOCK_RULES_OUTPUT}"
    )

    print(
        f"  {REPORT_OUTPUT}"
    )

    print(
        "\nTrackEase V3 now represents block restrictions and full "
        "maintenance execution timing before compatibility and optimization."
    )


if __name__ == "__main__":
    main()
