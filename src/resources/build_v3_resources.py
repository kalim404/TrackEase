"""
TrackEase V3 - Resource Model Builder

Builds the professional resource layer required for resource-aware block
planning.

Inputs:
    data/processed/v3_stations.csv
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_sections.csv

Outputs:
    data/processed/v3_departments.csv
    data/processed/v3_crews.csv
    data/processed/v3_crew_skills.csv
    data/processed/v3_crew_availability.csv
    data/processed/v3_machines.csv
    data/processed/v3_machine_availability.csv
    data/processed/v3_equipment.csv
    data/processed/v3_material_inventory.csv
    data/processed/v3_resource_model_report.txt

Design principles:
    - Existing validated V2/V3 outputs are read-only.
    - No random generation is used.
    - Prototype resource records are deterministic and reproducible.
    - Real TrackEase station codes are used as resource bases.
    - Every generated row carries explicit prototype provenance.
    - Resource counts are demand-aware but are not claimed as real Indian
      Railways staffing/fleet/inventory data.
"""

from __future__ import annotations

from pathlib import Path
from hashlib import sha1
import math

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

STATIONS_FILE = PROCESSED_DIR / "v3_stations.csv"
TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"
SECTIONS_FILE = PROCESSED_DIR / "v3_sections.csv"

DEPARTMENTS_OUTPUT = PROCESSED_DIR / "v3_departments.csv"
CREWS_OUTPUT = PROCESSED_DIR / "v3_crews.csv"
CREW_SKILLS_OUTPUT = PROCESSED_DIR / "v3_crew_skills.csv"
CREW_AVAILABILITY_OUTPUT = PROCESSED_DIR / "v3_crew_availability.csv"
MACHINES_OUTPUT = PROCESSED_DIR / "v3_machines.csv"
MACHINE_AVAILABILITY_OUTPUT = PROCESSED_DIR / "v3_machine_availability.csv"
EQUIPMENT_OUTPUT = PROCESSED_DIR / "v3_equipment.csv"
MATERIALS_OUTPUT = PROCESSED_DIR / "v3_material_inventory.csv"
REPORT_OUTPUT = PROCESSED_DIR / "v3_resource_model_report.txt"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROTOTYPE_MODE = "PROTOTYPE_RESOURCE_ADAPTER"
DATA_ORIGIN = "DETERMINISTIC_RESOURCE_GENERATOR"

WEEKDAYS = [
    "MON",
    "TUE",
    "WED",
    "THU",
    "FRI",
    "SAT",
    "SUN",
]

DEPARTMENT_DEFINITIONS = [
    {
        "department_id": "DEPT-ENG",
        "department_name": "Engineering",
        "source_system": "TMS",
        "can_request_block": True,
        "can_execute_work": True,
        "can_approve_work": False,
        "default_skill_group": "TRACK_INFRASTRUCTURE_ASSET",
    },
    {
        "department_id": "DEPT-SNT",
        "department_name": "S&T",
        "source_system": "SMMS",
        "can_request_block": True,
        "can_execute_work": True,
        "can_approve_work": False,
        "default_skill_group": "SIGNALLING_TELECOM_ASSET",
    },
    {
        "department_id": "DEPT-ELEC",
        "department_name": "Electrical",
        "source_system": "TDMS",
        "can_request_block": True,
        "can_execute_work": True,
        "can_approve_work": False,
        "default_skill_group": "TRACTION_ELECTRICAL_ASSET",
    },
    {
        "department_id": "DEPT-PROT",
        "department_name": "Protection",
        "source_system": "TRACKEASE_RESOURCE_LAYER",
        "can_request_block": False,
        "can_execute_work": True,
        "can_approve_work": False,
        "default_skill_group": "POSSESSION_PROTECTION",
    },
]

SKILL_CATALOG = {
    "Engineering": [
        "TRACK_INSPECTION",
        "TRACK_MAINTENANCE",
        "RAIL_REPAIR",
        "BALLAST_MAINTENANCE",
        "SLEEPER_MAINTENANCE",
    ],
    "S&T": [
        "SIGNAL_INSPECTION",
        "SIGNAL_MAINTENANCE",
        "POINT_MACHINE_MAINTENANCE",
        "TELECOM_MAINTENANCE",
    ],
    "Electrical": [
        "OHE_INSPECTION",
        "OHE_MAINTENANCE",
        "TRACTION_POWER",
        "ELECTRICAL_ISOLATION",
    ],
    "Protection": [
        "POSSESSION_PROTECTION",
        "WORKSITE_PROTECTION",
    ],
}

MACHINE_CATALOG = [
    ("TAMPING_MACHINE", "Engineering", 6, 25.0, 45),
    ("BALLAST_REGULATOR", "Engineering", 4, 30.0, 40),
    ("TRACK_INSPECTION_VEHICLE", "Engineering", 5, 45.0, 20),
    ("RAIL_MAINTENANCE_VEHICLE", "Engineering", 3, 35.0, 35),
    ("SIGNAL_TEST_VAN", "S&T", 5, 40.0, 20),
    ("POINT_MACHINE_SERVICE_VAN", "S&T", 4, 40.0, 20),
    ("TOWER_WAGON", "Electrical", 5, 45.0, 30),
    ("OHE_MAINTENANCE_VEHICLE", "Electrical", 4, 40.0, 35),
    ("TRACTION_POWER_TEST_VAN", "Electrical", 3, 40.0, 25),
]

EQUIPMENT_CATALOG = [
    ("EQ-TRACK-GAUGE", "TRACK_MEASUREMENT_KIT", "Engineering", 30),
    ("EQ-ULTRASONIC", "ULTRASONIC_RAIL_TESTER", "Engineering", 18),
    ("EQ-HYDRAULIC", "HYDRAULIC_TRACK_TOOLKIT", "Engineering", 24),
    ("EQ-SIGNAL-TEST", "SIGNAL_TEST_KIT", "S&T", 24),
    ("EQ-POINT-TEST", "POINT_MACHINE_TEST_KIT", "S&T", 18),
    ("EQ-OHE-TEST", "OHE_TEST_KIT", "Electrical", 20),
    ("EQ-ISOLATION", "ELECTRICAL_ISOLATION_KIT", "Electrical", 20),
    ("EQ-PROTECTION", "POSSESSION_PROTECTION_KIT", "Protection", 40),
]

MATERIAL_CATALOG = [
    ("MAT-RAIL", "RAIL_COMPONENT", "Engineering", 80, 20),
    ("MAT-SLEEPER", "SLEEPER_COMPONENT", "Engineering", 140, 35),
    ("MAT-BALLAST", "BALLAST_BATCH", "Engineering", 220, 50),
    ("MAT-FASTENER", "TRACK_FASTENER_SET", "Engineering", 300, 75),
    ("MAT-SIGNAL", "SIGNAL_COMPONENT_SET", "S&T", 120, 30),
    ("MAT-CABLE", "SIGNAL_TELECOM_CABLE_BATCH", "S&T", 160, 40),
    ("MAT-OHE", "OHE_COMPONENT_SET", "Electrical", 120, 30),
    ("MAT-INSULATOR", "OHE_INSULATOR_SET", "Electrical", 100, 25),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stable_id(prefix: str, *parts: object, length: int = 10) -> str:
    normalized = "|".join(
        str(part).strip().upper()
        for part in parts
    )
    digest = sha1(
        normalized.encode("utf-8")
    ).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def require_inputs() -> None:
    missing = [
        path
        for path in [
            STATIONS_FILE,
            TASKS_FILE,
            SECTIONS_FILE,
        ]
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3 inputs are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


def normalize_department(value: object) -> list[str]:
    """
    Convert V3 department text into one or more canonical departments.

    Examples:
        Engineering
        S&T
        Electrical
        Engineering + S&T
        TMS+SMMS
    """

    text = str(value).strip().upper()

    departments = []

    if any(
        token in text
        for token in [
            "ENGINEERING",
            "TMS",
        ]
    ):
        departments.append("Engineering")

    if any(
        token in text
        for token in [
            "S&T",
            "SIGNAL",
            "SMMS",
        ]
    ):
        departments.append("S&T")

    if any(
        token in text
        for token in [
            "ELECTRICAL",
            "TDMS",
            "TRACTION",
            "OHE",
        ]
    ):
        departments.append("Electrical")

    if not departments:
        departments.append("Engineering")

    return list(dict.fromkeys(departments))


def pick_base_stations(stations: pd.DataFrame, count: int) -> list[str]:
    """
    Select deterministic high-value resource bases from real TrackEase
    stations using hub score and traffic evidence.
    """

    candidates = stations.copy()

    candidates["hub_score"] = pd.to_numeric(
        candidates["hub_score"],
        errors="coerce",
    ).fillna(0.0)

    candidates["stop_records"] = pd.to_numeric(
        candidates["stop_records"],
        errors="coerce",
    ).fillna(0)

    candidates = (
        candidates.sort_values(
            [
                "hub_score",
                "stop_records",
                "station_code",
            ],
            ascending=[
                False,
                False,
                True,
            ],
        )
        .drop_duplicates(
            "station_code"
        )
    )

    if len(candidates) < count:
        raise ValueError(
            "Not enough stations to build resource bases."
        )

    return (
        candidates.head(count)[
            "station_code"
        ]
        .astype(str)
        .tolist()
    )


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

def build_departments() -> pd.DataFrame:
    rows = []

    for definition in DEPARTMENT_DEFINITIONS:
        row = dict(definition)
        row["data_origin"] = DATA_ORIGIN
        row["integration_mode"] = PROTOTYPE_MODE
        row["is_prototype"] = True
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Crew generation
# ---------------------------------------------------------------------------

def derive_department_demand(
    tasks: pd.DataFrame,
) -> dict[str, int]:
    """Count task demand by canonical department."""

    demand = {
        "Engineering": 0,
        "S&T": 0,
        "Electrical": 0,
        "Protection": 0,
    }

    for value in tasks["department"]:
        departments = normalize_department(
            value
        )

        for department in departments:
            demand[department] += 1

    # All possession tasks require protection capacity in the current V3 model.
    if "requires_protection_staff" in tasks.columns:
        protection_count = int(
            tasks[
                "requires_protection_staff"
            ]
            .fillna(False)
            .astype(bool)
            .sum()
        )
    else:
        protection_count = len(tasks)

    demand["Protection"] = protection_count

    return demand


def calculate_crew_counts(
    demand: dict[str, int],
) -> dict[str, int]:
    """
    Convert task demand into a manageable prototype crew pool.

    Ratios are prototype planning assumptions, not real staffing levels.
    """

    ratios = {
        "Engineering": 14,
        "S&T": 10,
        "Electrical": 8,
        "Protection": 18,
    }

    minimums = {
        "Engineering": 30,
        "S&T": 16,
        "Electrical": 16,
        "Protection": 20,
    }

    maximums = {
        "Engineering": 90,
        "S&T": 60,
        "Electrical": 60,
        "Protection": 70,
    }

    counts = {}

    for department in ratios:
        raw_count = math.ceil(
            max(
                1,
                demand.get(
                    department,
                    0,
                ),
            )
            / ratios[department]
        )

        counts[department] = min(
            maximums[department],
            max(
                minimums[department],
                raw_count,
            ),
        )

    return counts


def build_crews(
    stations: pd.DataFrame,
    tasks: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Build crew master, crew skill mapping and weekly availability.
    """

    demand = derive_department_demand(
        tasks
    )

    crew_counts = calculate_crew_counts(
        demand
    )

    # More bases than departments so crews are geographically distributed.
    base_stations = pick_base_stations(
        stations,
        36,
    )

    crew_rows = []
    skill_rows = []
    availability_rows = []

    department_prefix = {
        "Engineering": "ENG",
        "S&T": "SNT",
        "Electrical": "ELEC",
        "Protection": "PROT",
    }

    department_id = {
        "Engineering": "DEPT-ENG",
        "S&T": "DEPT-SNT",
        "Electrical": "DEPT-ELEC",
        "Protection": "DEPT-PROT",
    }

    crew_size_ranges = {
        "Engineering": [6, 8, 10],
        "S&T": [3, 4, 5],
        "Electrical": [4, 5, 6],
        "Protection": [2, 3, 4],
    }

    for department, count in crew_counts.items():

        skills = SKILL_CATALOG[
            department
        ]

        sizes = crew_size_ranges[
            department
        ]

        for index in range(
            1,
            count + 1,
        ):
            prefix = department_prefix[
                department
            ]

            crew_id = (
                f"CREW-{prefix}-{index:03d}"
            )

            base_station = base_stations[
                (
                    index
                    + len(department)
                )
                % len(base_stations)
            ]

            crew_size = sizes[
                (index - 1)
                % len(sizes)
            ]

            primary_skill = skills[
                (index - 1)
                % len(skills)
            ]

            # Prototype shift policy:
            # Protection needs continuous 24-hour coverage capability.
            # Other departments retain the existing DAY/NIGHT generator.
            if department == "Protection":
                protection_shift_cycle = (
                    "EARLY",
                    "DAY",
                    "LATE",
                )

                shift_pattern = protection_shift_cycle[
                    (index - 1)
                    % len(protection_shift_cycle)
                ]
            else:
                shift_pattern = (
                    "DAY"
                    if index % 3 != 0
                    else "NIGHT"
                )

            home_radius_km = (
                120
                if department == "Engineering"
                else 100
            )

            crew_rows.append(
                {
                    "crew_id":
                        crew_id,

                    "department_id":
                        department_id[
                            department
                        ],

                    "department":
                        department,

                    "base_station_code":
                        base_station,

                    "crew_size":
                        crew_size,

                    "primary_skill":
                        primary_skill,

                    "shift_pattern":
                        shift_pattern,

                    "max_work_minutes_per_shift":
                        480,

                    "home_operating_radius_km":
                        home_radius_km,

                    "travel_speed_proxy_kmph":
                        (
                            45.0
                            if department
                            != "Protection"
                            else 50.0
                        ),

                    "status":
                        "AVAILABLE",

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        PROTOTYPE_MODE,

                    "is_prototype":
                        True,
                }
            )

            # Primary skill.
            skill_rows.append(
                {
                    "crew_id":
                        crew_id,

                    "skill_code":
                        primary_skill,

                    "proficiency_level":
                        "PRIMARY",

                    "certification_status":
                        "PROTOTYPE_VALID",

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        PROTOTYPE_MODE,

                    "is_prototype":
                        True,
                }
            )

            # Give every second crew a deterministic secondary skill.
            if len(skills) > 1 and index % 2 == 0:
                secondary_skill = skills[
                    index
                    % len(skills)
                ]

                if secondary_skill != primary_skill:
                    skill_rows.append(
                        {
                            "crew_id":
                                crew_id,

                            "skill_code":
                                secondary_skill,

                            "proficiency_level":
                                "SECONDARY",

                            "certification_status":
                                "PROTOTYPE_VALID",

                            "data_origin":
                                DATA_ORIGIN,

                            "integration_mode":
                                PROTOTYPE_MODE,

                            "is_prototype":
                                True,
                        }
                    )

            # Weekly availability.
            for day_index, day in enumerate(
                WEEKDAYS
            ):
                rest_day = (
                    (
                        index
                        + day_index
                    )
                    % 7
                    == 0
                )

                if department == "Protection":
                    if shift_pattern == "EARLY":
                        shift_start = "00:00"
                        shift_end = "08:00"
                    elif shift_pattern == "DAY":
                        shift_start = "08:00"
                        shift_end = "16:00"
                    elif shift_pattern == "LATE":
                        shift_start = "16:00"
                        shift_end = "00:00"
                    else:
                        raise ValueError(
                            "Unexpected Protection shift pattern: "
                            f"{shift_pattern}"
                        )
                elif shift_pattern == "DAY":
                    shift_start = "08:00"
                    shift_end = "16:00"
                else:
                    shift_start = "20:00"
                    shift_end = "04:00"

                availability_rows.append(
                    {
                        "crew_id":
                            crew_id,

                        "weekday":
                            day,

                        "available":
                            not rest_day,

                        "shift_start":
                            shift_start,

                        "shift_end":
                            shift_end,

                        "max_work_minutes":
                            480,

                        "availability_reason":
                            (
                                "REST_DAY"
                                if rest_day
                                else "PLANNED_AVAILABLE"
                            ),

                        "data_origin":
                            DATA_ORIGIN,

                        "integration_mode":
                            PROTOTYPE_MODE,

                        "is_prototype":
                            True,
                    }
                )

    crews = pd.DataFrame(
        crew_rows
    )

    crew_skills = pd.DataFrame(
        skill_rows
    )

    crew_availability = pd.DataFrame(
        availability_rows
    )

    return (
        crews,
        crew_skills,
        crew_availability,
    )


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------

def build_machines(
    stations: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build deterministic specialist machine fleet and weekly availability."""

    base_stations = pick_base_stations(
        stations,
        20,
    )

    machine_rows = []
    availability_rows = []

    for (
        machine_type,
        department,
        count,
        travel_speed,
        setup_minutes,
    ) in MACHINE_CATALOG:

        prefix = (
            machine_type
            .replace("_", "-")
            [:14]
        )

        for index in range(
            1,
            count + 1,
        ):
            machine_id = (
                f"MACH-{prefix}-{index:02d}"
            )

            base_station = base_stations[
                (
                    index
                    + len(machine_type)
                )
                % len(base_stations)
            ]

            machine_rows.append(
                {
                    "machine_id":
                        machine_id,

                    "machine_type":
                        machine_type,

                    "department":
                        department,

                    "base_station_code":
                        base_station,

                    "travel_speed_proxy_kmph":
                        travel_speed,

                    "setup_minutes":
                        setup_minutes,

                    "max_operating_minutes_per_day":
                        600,

                    "status":
                        "AVAILABLE",

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        PROTOTYPE_MODE,

                    "is_prototype":
                        True,
                }
            )

            for day_index, day in enumerate(
                WEEKDAYS
            ):
                planned_maintenance_day = (
                    (
                        index
                        * 2
                        + day_index
                        + len(machine_type)
                    )
                    % 17
                    == 0
                )

                availability_rows.append(
                    {
                        "machine_id":
                            machine_id,

                        "weekday":
                            day,

                        "available":
                            not planned_maintenance_day,

                        "available_from":
                            "00:00",

                        "available_to":
                            "23:59",

                        "availability_reason":
                            (
                                "PLANNED_MACHINE_MAINTENANCE"
                                if planned_maintenance_day
                                else "PLANNED_AVAILABLE"
                            ),

                        "data_origin":
                            DATA_ORIGIN,

                        "integration_mode":
                            PROTOTYPE_MODE,

                        "is_prototype":
                            True,
                    }
                )

    return (
        pd.DataFrame(
            machine_rows
        ),
        pd.DataFrame(
            availability_rows
        ),
    )


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------

def build_equipment(
    stations: pd.DataFrame,
) -> pd.DataFrame:
    """Build portable equipment pools distributed across real station bases."""

    base_stations = pick_base_stations(
        stations,
        24,
    )

    rows = []

    for (
        family_id,
        equipment_type,
        department,
        quantity,
    ) in EQUIPMENT_CATALOG:

        for index in range(
            1,
            quantity + 1,
        ):
            equipment_id = (
                f"{family_id}-{index:03d}"
            )

            rows.append(
                {
                    "equipment_id":
                        equipment_id,

                    "equipment_type":
                        equipment_type,

                    "department":
                        department,

                    "base_station_code":
                        base_stations[
                            (
                                index
                                + len(equipment_type)
                            )
                            % len(base_stations)
                        ],

                    "portable":
                        True,

                    "status":
                        (
                            "INSPECTION_DUE"
                            if index % 23 == 0
                            else "AVAILABLE"
                        ),

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        PROTOTYPE_MODE,

                    "is_prototype":
                        True,
                }
            )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------

def build_material_inventory(
    stations: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build lightweight maintenance material inventory.

    This is not a procurement/ERP subsystem. It only provides the readiness
    signal required by resource feasibility.
    """

    depots = pick_base_stations(
        stations,
        18,
    )

    rows = []

    for (
        material_code,
        material_type,
        department,
        base_quantity,
        reorder_level,
    ) in MATERIAL_CATALOG:

        for depot_index, depot in enumerate(
            depots,
            start=1,
        ):
            variation = (
                depot_index
                * 7
                + len(material_type)
            ) % 31

            quantity = max(
                0,
                base_quantity
                - variation,
            )

            rows.append(
                {
                    "inventory_id":
                        stable_id(
                            "INV",
                            material_code,
                            depot,
                        ),

                    "material_code":
                        material_code,

                    "material_type":
                        material_type,

                    "department":
                        department,

                    "depot_station_code":
                        depot,

                    "quantity_available":
                        quantity,

                    "reorder_level":
                        reorder_level,

                    "stock_status":
                        (
                            "LOW_STOCK"
                            if quantity
                            <= reorder_level
                            else "AVAILABLE"
                        ),

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        PROTOTYPE_MODE,

                    "is_prototype":
                        True,
                }
            )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Validation / reporting
# ---------------------------------------------------------------------------

def validate_outputs(
    departments,
    crews,
    crew_skills,
    crew_availability,
    machines,
    machine_availability,
    equipment,
    materials,
):
    checks = {
        "departments":
            len(departments),

        "crews":
            len(crews),

        "crew_skills":
            len(crew_skills),

        "crew_availability_rows":
            len(crew_availability),

        "machines":
            len(machines),

        "machine_availability_rows":
            len(machine_availability),

        "equipment":
            len(equipment),

        "material_inventory_rows":
            len(materials),

        "duplicate_department_ids":
            int(
                departments[
                    "department_id"
                ].duplicated().sum()
            ),

        "duplicate_crew_ids":
            int(
                crews[
                    "crew_id"
                ].duplicated().sum()
            ),

        "duplicate_machine_ids":
            int(
                machines[
                    "machine_id"
                ].duplicated().sum()
            ),

        "duplicate_equipment_ids":
            int(
                equipment[
                    "equipment_id"
                ].duplicated().sum()
            ),

        "duplicate_inventory_ids":
            int(
                materials[
                    "inventory_id"
                ].duplicated().sum()
            ),

        "crew_missing_skills":
            int(
                (
                    ~crews[
                        "crew_id"
                    ].isin(
                        crew_skills[
                            "crew_id"
                        ]
                    )
                ).sum()
            ),

        "crew_missing_availability":
            int(
                (
                    ~crews[
                        "crew_id"
                    ].isin(
                        crew_availability[
                            "crew_id"
                        ]
                    )
                ).sum()
            ),

        "machine_missing_availability":
            int(
                (
                    ~machines[
                        "machine_id"
                    ].isin(
                        machine_availability[
                            "machine_id"
                        ]
                    )
                ).sum()
            ),
    }

    failure_keys = [
        "duplicate_department_ids",
        "duplicate_crew_ids",
        "duplicate_machine_ids",
        "duplicate_equipment_ids",
        "duplicate_inventory_ids",
        "crew_missing_skills",
        "crew_missing_availability",
        "machine_missing_availability",
    ]

    failure_total = sum(
        checks[key]
        for key in failure_keys
    )

    expected_crew_availability = (
        len(crews)
        * len(WEEKDAYS)
    )

    expected_machine_availability = (
        len(machines)
        * len(WEEKDAYS)
    )

    if (
        len(crew_availability)
        != expected_crew_availability
    ):
        raise RuntimeError(
            "Crew availability table does not contain exactly 7 rows per crew."
        )

    if (
        len(machine_availability)
        != expected_machine_availability
    ):
        raise RuntimeError(
            "Machine availability table does not contain exactly 7 rows per machine."
        )

    if failure_total:
        raise RuntimeError(
            "V3 resource-model integrity validation failed."
        )

    return checks


def write_report(
    tasks,
    departments,
    crews,
    crew_skills,
    crew_availability,
    machines,
    machine_availability,
    equipment,
    materials,
    checks,
):
    demand = derive_department_demand(
        tasks
    )

    crew_counts = (
        crews[
            "department"
        ]
        .value_counts()
        .sort_index()
    )

    machine_counts = (
        machines[
            "department"
        ]
        .value_counts()
        .sort_index()
    )

    equipment_counts = (
        equipment[
            "department"
        ]
        .value_counts()
        .sort_index()
    )

    material_counts = (
        materials[
            "department"
        ]
        .value_counts()
        .sort_index()
    )

    lines = [
        "=" * 72,
        "TrackEase V3 Resource Model Report",
        "=" * 72,
        "",
        "TASK DEMAND",
        "-" * 72,
    ]

    for name, count in demand.items():
        lines.append(
            f"{name:<28} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "RESOURCE SUMMARY",
            "-" * 72,
            f"Departments                  : {len(departments):,}",
            f"Crews                        : {len(crews):,}",
            f"Crew-skill mappings          : {len(crew_skills):,}",
            f"Crew availability rows       : {len(crew_availability):,}",
            f"Machines                     : {len(machines):,}",
            f"Machine availability rows    : {len(machine_availability):,}",
            f"Equipment units              : {len(equipment):,}",
            f"Material inventory rows      : {len(materials):,}",
            "",
            "CREWS BY DEPARTMENT",
            "-" * 72,
        ]
    )

    for name, count in crew_counts.items():
        lines.append(
            f"{name:<28} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "MACHINES BY DEPARTMENT",
            "-" * 72,
        ]
    )

    for name, count in machine_counts.items():
        lines.append(
            f"{name:<28} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "EQUIPMENT BY DEPARTMENT",
            "-" * 72,
        ]
    )

    for name, count in equipment_counts.items():
        lines.append(
            f"{name:<28} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "MATERIAL INVENTORY BY DEPARTMENT",
            "-" * 72,
        ]
    )

    for name, count in material_counts.items():
        lines.append(
            f"{name:<28} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                f"Duplicate department IDs     : "
                f"{checks['duplicate_department_ids']:,}"
            ),
            (
                f"Duplicate crew IDs           : "
                f"{checks['duplicate_crew_ids']:,}"
            ),
            (
                f"Duplicate machine IDs        : "
                f"{checks['duplicate_machine_ids']:,}"
            ),
            (
                f"Duplicate equipment IDs      : "
                f"{checks['duplicate_equipment_ids']:,}"
            ),
            (
                f"Duplicate inventory IDs      : "
                f"{checks['duplicate_inventory_ids']:,}"
            ),
            (
                f"Crews missing skills         : "
                f"{checks['crew_missing_skills']:,}"
            ),
            (
                f"Crews missing availability   : "
                f"{checks['crew_missing_availability']:,}"
            ),
            (
                f"Machines missing availability: "
                f"{checks['machine_missing_availability']:,}"
            ),
            "",
            "PROVENANCE",
            "-" * 72,
            f"Data origin                  : {DATA_ORIGIN}",
            f"Integration mode             : {PROTOTYPE_MODE}",
            "",
            (
                "All resource records are deterministic prototype planning "
                "data anchored to real TrackEase station codes."
            ),
            (
                "They are not claimed to be real Indian Railways crew rosters, "
                "machine allocations, equipment registers or inventory records."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build task-resource requirements linking each V3 maintenance "
                "task to required skills, crew capacity, machines, equipment, "
                "materials, protection and electrical isolation."
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

def main():
    print("=" * 72)
    print("TrackEase V3 - Resource Model Builder")
    print("=" * 72)

    require_inputs()

    print("\nLoading V3 stations and maintenance tasks...")

    stations = pd.read_csv(
        STATIONS_FILE,
        low_memory=False,
    )

    tasks = pd.read_csv(
        TASKS_FILE,
        low_memory=False,
    )

    if "department" not in tasks.columns:
        raise ValueError(
            "v3_maintenance_tasks.csv is missing department."
        )

    print(
        f"Stations loaded : {len(stations):,}"
    )
    print(
        f"Tasks loaded    : {len(tasks):,}"
    )

    print("\nBuilding department master...")
    departments = build_departments()

    print("Building crews, skills and shifts...")
    (
        crews,
        crew_skills,
        crew_availability,
    ) = build_crews(
        stations,
        tasks,
    )

    print("Building machine fleet...")
    (
        machines,
        machine_availability,
    ) = build_machines(
        stations
    )

    print("Building equipment pools...")
    equipment = build_equipment(
        stations
    )

    print("Building lightweight material inventory...")
    materials = build_material_inventory(
        stations
    )

    checks = validate_outputs(
        departments,
        crews,
        crew_skills,
        crew_availability,
        machines,
        machine_availability,
        equipment,
        materials,
    )

    departments.to_csv(
        DEPARTMENTS_OUTPUT,
        index=False,
    )

    crews.to_csv(
        CREWS_OUTPUT,
        index=False,
    )

    crew_skills.to_csv(
        CREW_SKILLS_OUTPUT,
        index=False,
    )

    crew_availability.to_csv(
        CREW_AVAILABILITY_OUTPUT,
        index=False,
    )

    machines.to_csv(
        MACHINES_OUTPUT,
        index=False,
    )

    machine_availability.to_csv(
        MACHINE_AVAILABILITY_OUTPUT,
        index=False,
    )

    equipment.to_csv(
        EQUIPMENT_OUTPUT,
        index=False,
    )

    materials.to_csv(
        MATERIALS_OUTPUT,
        index=False,
    )

    write_report(
        tasks,
        departments,
        crews,
        crew_skills,
        crew_availability,
        machines,
        machine_availability,
        equipment,
        materials,
        checks,
    )

    print("\n" + "=" * 72)
    print("V3 RESOURCE MODEL COMPLETE")
    print("=" * 72)

    print(
        f"\nDepartments              : {len(departments):,}"
    )
    print(
        f"Crews                    : {len(crews):,}"
    )
    print(
        f"Crew-skill mappings      : {len(crew_skills):,}"
    )
    print(
        f"Crew availability rows   : {len(crew_availability):,}"
    )
    print(
        f"Machines                 : {len(machines):,}"
    )
    print(
        f"Machine availability rows: {len(machine_availability):,}"
    )
    print(
        f"Equipment units          : {len(equipment):,}"
    )
    print(
        f"Material inventory rows  : {len(materials):,}"
    )

    print("\nIntegrity:")
    print(
        f"  Duplicate crew IDs           : "
        f"{checks['duplicate_crew_ids']:,}"
    )
    print(
        f"  Duplicate machine IDs        : "
        f"{checks['duplicate_machine_ids']:,}"
    )
    print(
        f"  Crews missing skills         : "
        f"{checks['crew_missing_skills']:,}"
    )
    print(
        f"  Crews missing availability   : "
        f"{checks['crew_missing_availability']:,}"
    )
    print(
        f"  Machines missing availability: "
        f"{checks['machine_missing_availability']:,}"
    )

    print("\nOutputs:")
    print(f"  {DEPARTMENTS_OUTPUT}")
    print(f"  {CREWS_OUTPUT}")
    print(f"  {CREW_SKILLS_OUTPUT}")
    print(f"  {CREW_AVAILABILITY_OUTPUT}")
    print(f"  {MACHINES_OUTPUT}")
    print(f"  {MACHINE_AVAILABILITY_OUTPUT}")
    print(f"  {EQUIPMENT_OUTPUT}")
    print(f"  {MATERIALS_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")

    print(
        "\nTrackEase V3 now has a deterministic professional resource layer "
        "for resource-aware maintenance planning."
    )


if __name__ == "__main__":
    main()
