"""
TrackEase V3 - Task Resource Requirements Builder

Purpose:
    Connect every canonical V3 maintenance task to the resources and
    execution prerequisites required to make it physically executable.

Inputs:
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_crews.csv
    data/processed/v3_crew_skills.csv
    data/processed/v3_machines.csv
    data/processed/v3_equipment.csv
    data/processed/v3_material_inventory.csv

Outputs:
    data/processed/v3_task_resource_requirements.csv
    data/processed/v3_task_execution_requirements.csv
    data/processed/v3_task_dependencies.csv
    data/processed/v3_task_resource_report.txt

Design principles:
    - Existing V2/V3 outputs are read-only.
    - Requirements are deterministic and reproducible.
    - Requirements are mapped only to resource types that actually exist in
      the V3 resource master.
    - Safety prerequisites (possession, protection, electrical isolation) are
      explicit hard requirements.
    - Task-to-task dependencies are inferred conservatively from same-asset
      inspection -> maintenance relationships; unsupported dependencies are
      not invented.
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"
CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
CREW_SKILLS_FILE = PROCESSED_DIR / "v3_crew_skills.csv"
MACHINES_FILE = PROCESSED_DIR / "v3_machines.csv"
EQUIPMENT_FILE = PROCESSED_DIR / "v3_equipment.csv"
MATERIALS_FILE = PROCESSED_DIR / "v3_material_inventory.csv"

REQUIREMENTS_OUTPUT = (
    PROCESSED_DIR / "v3_task_resource_requirements.csv"
)
EXECUTION_OUTPUT = (
    PROCESSED_DIR / "v3_task_execution_requirements.csv"
)
DEPENDENCIES_OUTPUT = (
    PROCESSED_DIR / "v3_task_dependencies.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_task_resource_report.txt"
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATA_ORIGIN = "TRACKEASE_V3_DERIVED_REQUIREMENTS"
INTEGRATION_MODE = "PROTOTYPE_RESOURCE_REQUIREMENT_MODEL"

TASK_TYPE_ORDER = {
    "INSPECTION": 1,
    "PREVENTIVE": 2,
    "URGENT_PLANNED": 3,
    "CORRECTIVE": 4,
    "EMERGENCY": 5,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stable_id(prefix: str, *parts: object, length: int = 12) -> str:
    normalized = "|".join(
        str(part).strip().upper()
        for part in parts
    )
    digest = sha1(
        normalized.encode("utf-8")
    ).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def require_inputs() -> None:
    required = [
        TASKS_FILE,
        CREWS_FILE,
        CREW_SKILLS_FILE,
        MACHINES_FILE,
        EQUIPMENT_FILE,
        MATERIALS_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3 resource inputs are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


def canonical_departments(value: object) -> list[str]:
    text = clean_text(value).upper()
    result = []

    if "ENGINEERING" in text or "TMS" in text:
        result.append("Engineering")

    if (
        "S&T" in text
        or "SIGNAL" in text
        or "SMMS" in text
    ):
        result.append("S&T")

    if (
        "ELECTRICAL" in text
        or "TDMS" in text
        or "OHE" in text
        or "TRACTION" in text
    ):
        result.append("Electrical")

    if not result:
        result.append("Engineering")

    return list(dict.fromkeys(result))


def infer_skill(
    department: str,
    task_name: str,
    task_type: str,
) -> str:
    text = f"{task_name} {task_type}".upper()

    if department == "Engineering":
        if "BALLAST" in text:
            return "BALLAST_MAINTENANCE"
        if "SLEEPER" in text:
            return "SLEEPER_MAINTENANCE"
        if "RAIL" in text or "DEFECT" in text or "FAILURE" in text:
            return "RAIL_REPAIR"
        if "INSPECTION" in text:
            return "TRACK_INSPECTION"
        return "TRACK_MAINTENANCE"

    if department == "S&T":
        if "POINT" in text:
            return "POINT_MACHINE_MAINTENANCE"
        if "TELECOM" in text:
            return "TELECOM_MAINTENANCE"
        if "INSPECTION" in text:
            return "SIGNAL_INSPECTION"
        return "SIGNAL_MAINTENANCE"

    if department == "Electrical":
        if "ISOLATION" in text:
            return "ELECTRICAL_ISOLATION"
        if "POWER" in text or "TRACTION" in text:
            return "TRACTION_POWER"
        if "INSPECTION" in text:
            return "OHE_INSPECTION"
        return "OHE_MAINTENANCE"

    return "POSSESSION_PROTECTION"


def required_crew_size(department: str, task_type: str) -> int:
    base = {
        "Engineering": 6,
        "S&T": 3,
        "Electrical": 4,
        "Protection": 2,
    }[department]

    if task_type in {"CORRECTIVE", "EMERGENCY"}:
        return base + 2

    if task_type == "URGENT_PLANNED":
        return base + 1

    return base


def infer_machine(
    department: str,
    task_name: str,
    task_type: str,
) -> str:
    text = f"{task_name} {task_type}".upper()

    if department == "Engineering":
        if "BALLAST" in text:
            return "BALLAST_REGULATOR"
        if "INSPECTION" in text:
            return "TRACK_INSPECTION_VEHICLE"
        if "RAIL" in text or "DEFECT" in text or "FAILURE" in text:
            return "RAIL_MAINTENANCE_VEHICLE"
        if task_type in {"CORRECTIVE", "URGENT_PLANNED"}:
            return "TAMPING_MACHINE"
        return ""

    if department == "S&T":
        if "POINT" in text:
            return "POINT_MACHINE_SERVICE_VAN"
        if "INSPECTION" in text or "SIGNAL" in text:
            return "SIGNAL_TEST_VAN"
        return ""

    if department == "Electrical":
        if "POWER" in text or "TRACTION" in text:
            return "TRACTION_POWER_TEST_VAN"
        if "INSPECTION" in text:
            return "TOWER_WAGON"
        return "OHE_MAINTENANCE_VEHICLE"

    return ""


def infer_equipment(
    department: str,
    task_name: str,
    task_type: str,
) -> list[str]:
    text = f"{task_name} {task_type}".upper()

    if department == "Engineering":
        result = ["TRACK_MEASUREMENT_KIT"]
        if "RAIL" in text or "DEFECT" in text or "FAILURE" in text:
            result.append("ULTRASONIC_RAIL_TESTER")
        if task_type in {"CORRECTIVE", "URGENT_PLANNED"}:
            result.append("HYDRAULIC_TRACK_TOOLKIT")
        return result

    if department == "S&T":
        if "POINT" in text:
            return ["POINT_MACHINE_TEST_KIT"]
        return ["SIGNAL_TEST_KIT"]

    if department == "Electrical":
        result = ["OHE_TEST_KIT"]
        if (
            "ISOLATION" in text
            or "POWER" in text
            or task_type in {"CORRECTIVE", "URGENT_PLANNED"}
        ):
            result.append("ELECTRICAL_ISOLATION_KIT")
        return result

    return []


def infer_material(
    department: str,
    task_name: str,
    task_type: str,
) -> list[tuple[str, int]]:
    text = f"{task_name} {task_type}".upper()

    # Inspections consume no maintenance stock by default.
    if task_type == "INSPECTION":
        return []

    if department == "Engineering":
        if "BALLAST" in text:
            return [("MAT-BALLAST", 1)]
        if "SLEEPER" in text:
            return [("MAT-SLEEPER", 2), ("MAT-FASTENER", 1)]
        if "RAIL" in text or "DEFECT" in text or "FAILURE" in text:
            return [("MAT-RAIL", 1), ("MAT-FASTENER", 1)]
        return [("MAT-FASTENER", 1)]

    if department == "S&T":
        if "TELECOM" in text:
            return [("MAT-CABLE", 1)]
        return [("MAT-SIGNAL", 1)]

    if department == "Electrical":
        if "INSULATOR" in text:
            return [("MAT-INSULATOR", 1)]
        return [("MAT-OHE", 1)]

    return []


def add_requirement(
    rows: list[dict],
    task_id: str,
    section_id: str,
    requirement_type: str,
    resource_category: str,
    department: str,
    resource_code: str,
    quantity_required: int,
    skill_code: str = "",
    mandatory: bool = True,
    can_share: bool = False,
    readiness_rule: str = "",
) -> None:

    requirement_id = stable_id(
        "REQRES",
        task_id,
        requirement_type,
        department,
        resource_code,
        skill_code,
    )

    rows.append(
        {
            "requirement_id":
                requirement_id,

            "task_id":
                task_id,

            "section_id":
                section_id,

            "requirement_type":
                requirement_type,

            "resource_category":
                resource_category,

            "department":
                department,

            "resource_code":
                resource_code,

            "quantity_required":
                int(quantity_required),

            "skill_code":
                skill_code,

            "mandatory":
                bool(mandatory),

            "can_share_across_coordinated_tasks":
                bool(can_share),

            "readiness_rule":
                readiness_rule,

            "data_origin":
                DATA_ORIGIN,

            "integration_mode":
                INTEGRATION_MODE,

            "is_prototype_derived":
                True,
        }
    )


# ---------------------------------------------------------------------------
# Requirement construction
# ---------------------------------------------------------------------------

def build_requirements(
    tasks: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    requirement_rows = []
    execution_rows = []

    for row in tasks.itertuples(index=False):

        task_id = clean_text(row.task_id)
        section_id = clean_text(row.section_id)
        task_name = clean_text(row.task_name)
        task_type = clean_text(row.task_type).upper()
        departments = canonical_departments(
            row.department
        )

        required_skills = []
        required_machines = []
        required_equipment = []
        required_materials = []

        # Department-specific execution crews.
        for department in departments:
            skill = infer_skill(
                department,
                task_name,
                task_type,
            )
            crew_size = required_crew_size(
                department,
                task_type,
            )

            required_skills.append(skill)

            add_requirement(
                requirement_rows,
                task_id,
                section_id,
                "CREW",
                "CREW",
                department,
                "QUALIFIED_CREW",
                1,
                skill_code=skill,
                mandatory=True,
                can_share=False,
                readiness_rule=(
                    f"One available {department} crew with skill "
                    f"{skill} and at least {crew_size} personnel."
                ),
            )

            machine_type = infer_machine(
                department,
                task_name,
                task_type,
            )

            if machine_type:
                required_machines.append(
                    machine_type
                )
                add_requirement(
                    requirement_rows,
                    task_id,
                    section_id,
                    "MACHINE",
                    "MACHINE",
                    department,
                    machine_type,
                    1,
                    mandatory=True,
                    can_share=True,
                    readiness_rule=(
                        "Machine must be available, operational, and able "
                        "to reach the worksite before block start."
                    ),
                )

            for equipment_type in infer_equipment(
                department,
                task_name,
                task_type,
            ):
                required_equipment.append(
                    equipment_type
                )
                add_requirement(
                    requirement_rows,
                    task_id,
                    section_id,
                    "EQUIPMENT",
                    "EQUIPMENT",
                    department,
                    equipment_type,
                    1,
                    mandatory=True,
                    can_share=True,
                    readiness_rule=(
                        "Required portable equipment must be available "
                        "before work starts."
                    ),
                )

            for material_code, quantity in infer_material(
                department,
                task_name,
                task_type,
            ):
                required_materials.append(
                    material_code
                )
                add_requirement(
                    requirement_rows,
                    task_id,
                    section_id,
                    "MATERIAL",
                    "MATERIAL",
                    department,
                    material_code,
                    quantity,
                    mandatory=True,
                    can_share=False,
                    readiness_rule=(
                        "Required material quantity must be available at "
                        "a reachable depot before execution."
                    ),
                )

        requires_protection = bool(
            getattr(
                row,
                "requires_protection_staff",
                True,
            )
        )

        if requires_protection:
            required_skills.append(
                "POSSESSION_PROTECTION"
            )
            required_equipment.append(
                "POSSESSION_PROTECTION_KIT"
            )

            add_requirement(
                requirement_rows,
                task_id,
                section_id,
                "PROTECTION_CREW",
                "CREW",
                "Protection",
                "QUALIFIED_PROTECTION_CREW",
                1,
                skill_code="POSSESSION_PROTECTION",
                mandatory=True,
                can_share=True,
                readiness_rule=(
                    "Qualified protection staff must cover the full "
                    "possession period."
                ),
            )

            add_requirement(
                requirement_rows,
                task_id,
                section_id,
                "PROTECTION_EQUIPMENT",
                "EQUIPMENT",
                "Protection",
                "POSSESSION_PROTECTION_KIT",
                1,
                mandatory=True,
                can_share=True,
                readiness_rule=(
                    "Protection kit must be available for the possession."
                ),
            )

        requires_isolation = bool(
            getattr(
                row,
                "requires_power_isolation",
                False,
            )
        )

        if requires_isolation:
            add_requirement(
                requirement_rows,
                task_id,
                section_id,
                "POWER_ISOLATION",
                "OPERATIONAL_PREREQUISITE",
                "Electrical",
                "TRACTION_POWER_ISOLATION",
                1,
                skill_code="ELECTRICAL_ISOLATION",
                mandatory=True,
                can_share=True,
                readiness_rule=(
                    "Electrical isolation must be confirmed before "
                    "maintenance possession begins."
                ),
            )

        execution_rows.append(
            {
                "task_id":
                    task_id,

                "request_id":
                    clean_text(row.request_id),

                "asset_id":
                    clean_text(row.asset_id),

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

                "crew_skills_required":
                    "|".join(
                        sorted(
                            set(
                                required_skills
                            )
                        )
                    ),

                "machine_types_required":
                    "|".join(
                        sorted(
                            set(
                                required_machines
                            )
                        )
                    ),

                "equipment_types_required":
                    "|".join(
                        sorted(
                            set(
                                required_equipment
                            )
                        )
                    ),

                "material_codes_required":
                    "|".join(
                        sorted(
                            set(
                                required_materials
                            )
                        )
                    ),

                "requires_possession":
                    bool(
                        getattr(
                            row,
                            "requires_possession",
                            True,
                        )
                    ),

                "requires_power_isolation":
                    requires_isolation,

                "requires_protection_staff":
                    requires_protection,

                "minimum_duration_min":
                    int(
                        row.minimum_duration_min
                    ),

                "expected_duration_min":
                    int(
                        row.expected_duration_min
                    ),

                "maximum_duration_min":
                    int(
                        row.maximum_duration_min
                    ),

                "priority_level":
                    clean_text(
                        row.priority_level
                    ),

                "trackease_priority_score":
                    float(
                        row.trackease_priority_score
                    ),

                "resource_requirement_count":
                    0,  # filled after long table is built

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,

                "is_prototype_derived":
                    True,
            }
        )

    requirements = pd.DataFrame(
        requirement_rows
    )

    execution = pd.DataFrame(
        execution_rows
    )

    counts = (
        requirements.groupby(
            "task_id"
        )
        .size()
        .rename(
            "resource_requirement_count"
        )
    )

    execution = execution.drop(
        columns=[
            "resource_requirement_count"
        ]
    ).merge(
        counts,
        on="task_id",
        how="left",
        validate="one_to_one",
    )

    execution[
        "resource_requirement_count"
    ] = (
        execution[
            "resource_requirement_count"
        ]
        .fillna(0)
        .astype(int)
    )

    return requirements, execution


# ---------------------------------------------------------------------------
# Dependency construction
# ---------------------------------------------------------------------------

def build_dependencies(
    tasks: pd.DataFrame,
) -> pd.DataFrame:
    """
    Conservatively infer task dependencies on the same asset.

    If an asset has both an inspection and a later maintenance-type task,
    the inspection is treated as a prerequisite. No arbitrary dependencies
    are created between unrelated assets.
    """

    rows = []

    if "asset_id" not in tasks.columns:
        return pd.DataFrame(
            columns=[
                "dependency_id",
                "predecessor_task_id",
                "successor_task_id",
                "asset_id",
                "dependency_type",
                "minimum_lag_minutes",
                "mandatory",
                "reason",
                "data_origin",
                "integration_mode",
                "is_prototype_derived",
            ]
        )

    working = tasks.copy()

    working["task_type_upper"] = (
        working["task_type"]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    working["type_order"] = (
        working["task_type_upper"]
        .map(TASK_TYPE_ORDER)
        .fillna(99)
        .astype(int)
    )

    for asset_id, group in working.groupby(
        "asset_id",
        dropna=False,
    ):
        if len(group) < 2:
            continue

        inspections = group[
            group[
                "task_type_upper"
            ].eq("INSPECTION")
        ]

        successors = group[
            group[
                "task_type_upper"
            ].isin(
                [
                    "PREVENTIVE",
                    "URGENT_PLANNED",
                    "CORRECTIVE",
                    "EMERGENCY",
                ]
            )
        ]

        if inspections.empty or successors.empty:
            continue

        predecessor = inspections.sort_values(
            [
                "trackease_priority_score",
                "task_id",
            ],
            ascending=[
                False,
                True,
            ],
        ).iloc[0]

        for _, successor in successors.iterrows():
            if (
                predecessor["task_id"]
                == successor["task_id"]
            ):
                continue

            dependency_id = stable_id(
                "DEP",
                predecessor["task_id"],
                successor["task_id"],
            )

            rows.append(
                {
                    "dependency_id":
                        dependency_id,

                    "predecessor_task_id":
                        predecessor["task_id"],

                    "successor_task_id":
                        successor["task_id"],

                    "asset_id":
                        asset_id,

                    "dependency_type":
                        "FINISH_TO_START",

                    "minimum_lag_minutes":
                        0,

                    "mandatory":
                        True,

                    "reason":
                        (
                            "Same-asset inspection must complete before "
                            "derived maintenance execution."
                        ),

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        INTEGRATION_MODE,

                    "is_prototype_derived":
                        True,
                }
            )

    columns = [
        "dependency_id",
        "predecessor_task_id",
        "successor_task_id",
        "asset_id",
        "dependency_type",
        "minimum_lag_minutes",
        "mandatory",
        "reason",
        "data_origin",
        "integration_mode",
        "is_prototype_derived",
    ]

    return pd.DataFrame(
        rows,
        columns=columns,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_requirements(
    tasks: pd.DataFrame,
    requirements: pd.DataFrame,
    execution: pd.DataFrame,
    dependencies: pd.DataFrame,
    crew_skills: pd.DataFrame,
    machines: pd.DataFrame,
    equipment: pd.DataFrame,
    materials: pd.DataFrame,
) -> dict[str, int]:

    known_skills = set(
        crew_skills[
            "skill_code"
        ].astype(str)
    )

    known_machines = set(
        machines[
            "machine_type"
        ].astype(str)
    )

    known_equipment = set(
        equipment[
            "equipment_type"
        ].astype(str)
    )

    known_materials = set(
        materials[
            "material_code"
        ].astype(str)
    )

    crew_requirements = requirements[
        requirements[
            "resource_category"
        ].eq("CREW")
    ]

    machine_requirements = requirements[
        requirements[
            "resource_category"
        ].eq("MACHINE")
    ]

    equipment_requirements = requirements[
        requirements[
            "resource_category"
        ].eq("EQUIPMENT")
    ]

    material_requirements = requirements[
        requirements[
            "resource_category"
        ].eq("MATERIAL")
    ]

    unknown_skills = int(
        (
            ~crew_requirements[
                "skill_code"
            ].isin(
                known_skills
            )
        ).sum()
    )

    unknown_machines = int(
        (
            ~machine_requirements[
                "resource_code"
            ].isin(
                known_machines
            )
        ).sum()
    )

    unknown_equipment = int(
        (
            ~equipment_requirements[
                "resource_code"
            ].isin(
                known_equipment
            )
        ).sum()
    )

    unknown_materials = int(
        (
            ~material_requirements[
                "resource_code"
            ].isin(
                known_materials
            )
        ).sum()
    )

    task_ids = set(
        tasks["task_id"].astype(str)
    )

    invalid_dependencies = 0

    if not dependencies.empty:
        invalid_dependencies = int(
            (
                ~dependencies[
                    "predecessor_task_id"
                ].astype(str).isin(task_ids)
                |
                ~dependencies[
                    "successor_task_id"
                ].astype(str).isin(task_ids)
            ).sum()
        )

    checks = {
        "tasks":
            len(tasks),

        "requirements":
            len(requirements),

        "execution_rows":
            len(execution),

        "dependencies":
            len(dependencies),

        "duplicate_requirement_ids":
            int(
                requirements[
                    "requirement_id"
                ].duplicated().sum()
            ),

        "duplicate_execution_task_ids":
            int(
                execution[
                    "task_id"
                ].duplicated().sum()
            ),

        "tasks_missing_requirements":
            int(
                (
                    ~tasks[
                        "task_id"
                    ].astype(str).isin(
                        requirements[
                            "task_id"
                        ].astype(str)
                    )
                ).sum()
            ),

        "unknown_skills":
            unknown_skills,

        "unknown_machines":
            unknown_machines,

        "unknown_equipment":
            unknown_equipment,

        "unknown_materials":
            unknown_materials,

        "invalid_dependencies":
            invalid_dependencies,
    }

    failure_keys = [
        "duplicate_requirement_ids",
        "duplicate_execution_task_ids",
        "tasks_missing_requirements",
        "unknown_skills",
        "unknown_machines",
        "unknown_equipment",
        "unknown_materials",
        "invalid_dependencies",
    ]

    if len(execution) != len(tasks):
        raise RuntimeError(
            "Execution requirement summary must contain exactly one row per task."
        )

    failure_total = sum(
        checks[key]
        for key in failure_keys
    )

    if failure_total:
        raise RuntimeError(
            "V3 task-resource requirement integrity validation failed."
        )

    return checks


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(
    tasks: pd.DataFrame,
    requirements: pd.DataFrame,
    execution: pd.DataFrame,
    dependencies: pd.DataFrame,
    checks: dict[str, int],
) -> None:

    requirement_type_counts = (
        requirements[
            "requirement_type"
        ]
        .value_counts()
        .sort_index()
    )

    resource_category_counts = (
        requirements[
            "resource_category"
        ]
        .value_counts()
        .sort_index()
    )

    machine_task_count = int(
        execution[
            "machine_types_required"
        ]
        .astype(str)
        .str.len()
        .gt(0)
        .sum()
    )

    isolation_task_count = int(
        execution[
            "requires_power_isolation"
        ]
        .astype(bool)
        .sum()
    )

    protection_task_count = int(
        execution[
            "requires_protection_staff"
        ]
        .astype(bool)
        .sum()
    )

    lines = [
        "=" * 72,
        "TrackEase V3 Task Resource Requirement Report",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Maintenance tasks            : {len(tasks):,}",
        f"Resource requirements        : {len(requirements):,}",
        f"Execution summaries          : {len(execution):,}",
        f"Task dependencies            : {len(dependencies):,}",
        f"Tasks requiring machines     : {machine_task_count:,}",
        f"Tasks requiring isolation    : {isolation_task_count:,}",
        f"Tasks requiring protection   : {protection_task_count:,}",
        "",
        "REQUIREMENTS BY TYPE",
        "-" * 72,
    ]

    for name, count in requirement_type_counts.items():
        lines.append(
            f"{name:<32} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "REQUIREMENTS BY RESOURCE CATEGORY",
            "-" * 72,
        ]
    )

    for name, count in resource_category_counts.items():
        lines.append(
            f"{name:<32} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                f"Duplicate requirement IDs    : "
                f"{checks['duplicate_requirement_ids']:,}"
            ),
            (
                f"Duplicate execution task IDs : "
                f"{checks['duplicate_execution_task_ids']:,}"
            ),
            (
                f"Tasks missing requirements   : "
                f"{checks['tasks_missing_requirements']:,}"
            ),
            (
                f"Unknown crew skills          : "
                f"{checks['unknown_skills']:,}"
            ),
            (
                f"Unknown machine types        : "
                f"{checks['unknown_machines']:,}"
            ),
            (
                f"Unknown equipment types      : "
                f"{checks['unknown_equipment']:,}"
            ),
            (
                f"Unknown materials            : "
                f"{checks['unknown_materials']:,}"
            ),
            (
                f"Invalid task dependencies    : "
                f"{checks['invalid_dependencies']:,}"
            ),
            "",
            "PROVENANCE",
            "-" * 72,
            f"Data origin                  : {DATA_ORIGIN}",
            f"Integration mode             : {INTEGRATION_MODE}",
            "",
            (
                "Resource requirements are deterministic prototype mappings "
                "derived from canonical TrackEase task type, department and "
                "safety prerequisites."
            ),
            (
                "They are not claimed to be official Indian Railways work "
                "norms or resource standards."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Validate physical resource feasibility: crew skill/shift, "
                "machine availability, equipment, materials, protection, "
                "power isolation and resource travel to the worksite."
            ),
        ]
    )

    REPORT_OUTPUT.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:

    print("=" * 72)
    print("TrackEase V3 - Task Resource Requirements")
    print("=" * 72)

    require_inputs()

    print("\nLoading V3 task and resource masters...")

    tasks = pd.read_csv(
        TASKS_FILE,
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
    materials = pd.read_csv(
        MATERIALS_FILE,
        low_memory=False,
    )

    print(
        f"Maintenance tasks : {len(tasks):,}"
    )
    print(
        f"Crews             : {len(crews):,}"
    )
    print(
        f"Machines          : {len(machines):,}"
    )
    print(
        f"Equipment units   : {len(equipment):,}"
    )
    print(
        f"Inventory rows    : {len(materials):,}"
    )

    print("\nBuilding task-resource requirement mappings...")
    requirements, execution = build_requirements(
        tasks
    )

    print("Building conservative task dependencies...")
    dependencies = build_dependencies(
        tasks
    )

    checks = validate_requirements(
        tasks,
        requirements,
        execution,
        dependencies,
        crew_skills,
        machines,
        equipment,
        materials,
    )

    requirements.to_csv(
        REQUIREMENTS_OUTPUT,
        index=False,
    )

    execution.to_csv(
        EXECUTION_OUTPUT,
        index=False,
    )

    dependencies.to_csv(
        DEPENDENCIES_OUTPUT,
        index=False,
    )

    write_report(
        tasks,
        requirements,
        execution,
        dependencies,
        checks,
    )

    print("\n" + "=" * 72)
    print("V3 TASK-RESOURCE REQUIREMENTS COMPLETE")
    print("=" * 72)

    print(
        f"\nMaintenance tasks       : "
        f"{len(tasks):,}"
    )
    print(
        f"Resource requirements   : "
        f"{len(requirements):,}"
    )
    print(
        f"Execution summaries     : "
        f"{len(execution):,}"
    )
    print(
        f"Task dependencies       : "
        f"{len(dependencies):,}"
    )

    print("\nIntegrity:")
    print(
        f"  Duplicate requirement IDs : "
        f"{checks['duplicate_requirement_ids']:,}"
    )
    print(
        f"  Tasks missing requirements: "
        f"{checks['tasks_missing_requirements']:,}"
    )
    print(
        f"  Unknown crew skills       : "
        f"{checks['unknown_skills']:,}"
    )
    print(
        f"  Unknown machine types     : "
        f"{checks['unknown_machines']:,}"
    )
    print(
        f"  Unknown equipment types   : "
        f"{checks['unknown_equipment']:,}"
    )
    print(
        f"  Unknown materials         : "
        f"{checks['unknown_materials']:,}"
    )
    print(
        f"  Invalid dependencies      : "
        f"{checks['invalid_dependencies']:,}"
    )

    print("\nOutputs:")
    print(f"  {REQUIREMENTS_OUTPUT}")
    print(f"  {EXECUTION_OUTPUT}")
    print(f"  {DEPENDENCIES_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")

    print(
        "\nTrackEase V3 now links every maintenance task to the "
        "resources and safety prerequisites required for execution."
    )


if __name__ == "__main__":
    main()
