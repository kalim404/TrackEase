"""
TrackEase V3 - Canonical Domain Model Builder

Builds the professional end-to-end maintenance domain model required before
resource-aware optimization:

    Asset -> Maintenance Request -> Maintenance Task

Primary inputs:
    data/processed/unified_maintenance_tasks.csv
    data/processed/prioritized_maintenance_tasks.csv   (preferred when present)

Outputs:
    data/processed/v3_assets.csv
    data/processed/v3_maintenance_requests.csv
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_domain_model_report.txt

Design principles:
    - Preserve current validated V2 outputs; never modify them.
    - Prefer existing TrackEase values where available.
    - Derive only the minimum missing prototype fields needed for V3.
    - Every derived row carries provenance / prototype labels.
    - Stable IDs are deterministic and reproducible.
    - The builder is schema-tolerant so small column-name differences do not
      silently break the V3 migration.
"""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

UNIFIED_FILE = PROCESSED_DIR / "unified_maintenance_tasks.csv"
PRIORITIZED_FILE = PROCESSED_DIR / "prioritized_maintenance_tasks.csv"

ASSET_OUTPUT = PROCESSED_DIR / "v3_assets.csv"
REQUEST_OUTPUT = PROCESSED_DIR / "v3_maintenance_requests.csv"
TASK_OUTPUT = PROCESSED_DIR / "v3_maintenance_tasks.csv"
REPORT_OUTPUT = PROCESSED_DIR / "v3_domain_model_report.txt"

PROTOTYPE_MODE = "PROTOTYPE_DERIVED_DOMAIN_MODEL"
DATA_ORIGIN = "TRACKEASE_V2_DERIVED"

PRIORITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
}


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def clean_text(value, default: str = "") -> str:
    if pd.isna(value):
        return default
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return default
    return text


def stable_id(prefix: str, *parts: object, length: int = 12) -> str:
    normalized = "|".join(clean_text(part, "UNKNOWN").upper() for part in parts)
    digest = sha1(normalized.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def numeric_series(df: pd.DataFrame, column: str | None, default: float = 0.0) -> pd.Series:
    if column is None:
        return pd.Series([default] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce").fillna(default)


def text_series(df: pd.DataFrame, column: str | None, default: str = "") -> pd.Series:
    if column is None:
        return pd.Series([default] * len(df), index=df.index, dtype="string")
    return df[column].fillna(default).astype("string").str.strip()


def load_source() -> tuple[pd.DataFrame, str]:
    if PRIORITIZED_FILE.exists():
        source_file = PRIORITIZED_FILE
        source_label = "prioritized_maintenance_tasks.csv"
    elif UNIFIED_FILE.exists():
        source_file = UNIFIED_FILE
        source_label = "unified_maintenance_tasks.csv"
    else:
        raise FileNotFoundError(
            "Neither prioritized nor unified maintenance task file exists.\n"
            f"Expected one of:\n  {PRIORITIZED_FILE}\n  {UNIFIED_FILE}"
        )

    df = pd.read_csv(source_file, low_memory=False)
    if df.empty:
        raise ValueError(f"{source_label} is empty.")
    return df, source_label


def normalize_source(df: pd.DataFrame) -> pd.DataFrame:
    columns = df.columns.tolist()

    source_task_col = first_existing(
        columns,
        ["unified_task_id", "source_task_id", "work_order_id", "task_id", "planning_task_id"],
    )
    section_col = first_existing(columns, ["section_id", "assigned_section_id", "railway_section_id"])
    department_col = first_existing(columns, ["department", "departments_involved", "responsible_department"])
    source_system_col = first_existing(columns, ["source_system", "source_systems", "maintenance_source"])
    task_name_col = first_existing(
        columns,
        ["task_name", "maintenance_task", "maintenance_type", "task_type", "planning_task_type", "failure_type"],
    )
    priority_level_col = first_existing(
        columns,
        ["trackease_priority_level", "priority_level", "priority", "severity_priority"],
    )
    priority_score_col = first_existing(columns, ["trackease_priority_score", "priority_score"])
    duration_col = first_existing(
        columns,
        ["required_minutes", "duration_minutes", "expected_duration_min", "maintenance_duration_min"],
    )

    if source_task_col is None:
        raise ValueError("Could not identify a task identifier column in the V2 source.")
    if section_col is None:
        raise ValueError("Could not identify section_id in the V2 source.")

    normalized = pd.DataFrame(
        {
            "source_task_id": text_series(df, source_task_col),
            "section_id": text_series(df, section_col),
            "department": text_series(df, department_col, "UNKNOWN"),
            "source_system": text_series(df, source_system_col, "UNKNOWN"),
            "task_name": text_series(df, task_name_col, "Maintenance Work"),
            "priority_level": text_series(df, priority_level_col, "MEDIUM").str.upper(),
            "priority_score": numeric_series(df, priority_score_col, 0.0),
            "expected_duration_min": numeric_series(df, duration_col, 60.0),
        }
    )

    normalized.loc[normalized["expected_duration_min"] <= 0, "expected_duration_min"] = 60.0
    normalized["priority_level"] = normalized["priority_level"].replace(
        {"1": "LOW", "2": "MEDIUM", "3": "HIGH", "4": "CRITICAL"}
    )
    normalized.loc[~normalized["priority_level"].isin(PRIORITY_ORDER), "priority_level"] = "MEDIUM"

    duplicate_count = int(normalized["source_task_id"].duplicated().sum())
    if duplicate_count:
        raise ValueError(f"V2 source contains {duplicate_count:,} duplicate source task IDs.")

    missing_count = int(normalized["section_id"].eq("").sum())
    if missing_count:
        raise ValueError(f"{missing_count:,} maintenance tasks have no section_id.")

    return normalized


def infer_asset_type(source_system: str, department: str, task_name: str) -> str:
    combined = f"{source_system} {department} {task_name}".upper()

    keyword_map = [
        (["SIGNAL", "SMMS", "TELECOM", "POINT MACHINE"], "SIGNALLING_TELECOM_ASSET"),
        (["OHE", "TDMS", "TRACTION", "ELECTRICAL", "POWER"], "TRACTION_ELECTRICAL_ASSET"),
        (["BALLAST", "RAIL", "TRACK", "SLEEPER", "ENGINEERING", "TMS"], "TRACK_INFRASTRUCTURE_ASSET"),
    ]

    for keywords, asset_type in keyword_map:
        if any(keyword in combined for keyword in keywords):
            return asset_type
    return "RAILWAY_INFRASTRUCTURE_ASSET"


def infer_request_type(task_name: str, priority_level: str) -> str:
    text = task_name.upper()
    if "INSPECTION" in text:
        return "INSPECTION"
    if any(keyword in text for keyword in ["FAILURE", "DEFECT", "FAULT", "REPAIR", "CORRECTIVE"]):
        return "CORRECTIVE"
    if priority_level == "CRITICAL":
        return "URGENT_PLANNED"
    return "PREVENTIVE"


def build_assets(source: pd.DataFrame) -> pd.DataFrame:
    working = source.copy()
    working["asset_type"] = working.apply(
        lambda row: infer_asset_type(row["source_system"], row["department"], row["task_name"]),
        axis=1,
    )

    asset_rows = []
    grouped = working.groupby(["section_id", "department", "asset_type"], sort=True, dropna=False)

    for (section_id, department, asset_type), group in grouped:
        highest_priority = max(
            group["priority_level"],
            key=lambda level: PRIORITY_ORDER.get(level, 0),
        )
        condition_proxy = round(
            max(0.0, min(100.0, 100.0 - float(group["priority_score"].max()))),
            2,
        )

        asset_rows.append(
            {
                "asset_id": stable_id("AST", section_id, department, asset_type),
                "asset_type": asset_type,
                "section_id": clean_text(section_id),
                "department": clean_text(department, "UNKNOWN"),
                "criticality_level": highest_priority,
                "condition_score_proxy": condition_proxy,
                "open_request_count": int(len(group)),
                "availability_status": "RESTRICTED" if highest_priority in {"CRITICAL", "HIGH"} else "AVAILABLE",
                "source_systems": "|".join(
                    sorted({clean_text(value, "UNKNOWN") for value in group["source_system"]})
                ),
                "data_origin": DATA_ORIGIN,
                "integration_mode": PROTOTYPE_MODE,
                "is_prototype_derived": True,
            }
        )

    assets = pd.DataFrame(asset_rows)
    return assets.sort_values("asset_id").reset_index(drop=True)


def attach_asset_ids(source: pd.DataFrame, assets: pd.DataFrame) -> pd.DataFrame:
    working = source.copy()
    working["asset_type"] = working.apply(
        lambda row: infer_asset_type(row["source_system"], row["department"], row["task_name"]),
        axis=1,
    )

    lookup = assets[["asset_id", "section_id", "department", "asset_type"]]
    working = working.merge(
        lookup,
        on=["section_id", "department", "asset_type"],
        how="left",
        validate="many_to_one",
    )

    if working["asset_id"].isna().any():
        raise RuntimeError("Asset mapping failed for one or more maintenance tasks.")
    return working


def build_requests(source_with_assets: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in source_with_assets.itertuples(index=False):
        request_id = stable_id("REQ", row.source_task_id, row.asset_id)
        rows.append(
            {
                "request_id": request_id,
                "asset_id": row.asset_id,
                "section_id": row.section_id,
                "request_source": row.source_system,
                "request_type": infer_request_type(row.task_name, row.priority_level),
                "request_description": row.task_name,
                "department": row.department,
                "urgency_level": row.priority_level,
                "trackease_priority_score": round(float(row.priority_score), 2),
                "required_by": "",
                "safety_critical": row.priority_level == "CRITICAL",
                "request_status": "OPEN",
                "source_task_id": row.source_task_id,
                "data_origin": DATA_ORIGIN,
                "integration_mode": PROTOTYPE_MODE,
                "is_prototype_derived": True,
            }
        )

    return pd.DataFrame(rows).sort_values("request_id").reset_index(drop=True)


def build_tasks(source_with_assets: pd.DataFrame, requests: pd.DataFrame) -> pd.DataFrame:
    request_lookup = requests.set_index("source_task_id")["request_id"].to_dict()
    rows = []

    for row in source_with_assets.itertuples(index=False):
        request_id = request_lookup[row.source_task_id]
        task_id = stable_id("TASK", request_id, row.source_task_id)
        combined = f"{row.department} {row.source_system} {row.task_name}".upper()
        electrical_work = any(marker in combined for marker in ["ELECTRICAL", "TDMS", "OHE", "TRACTION", "POWER"])

        expected_duration = int(round(float(row.expected_duration_min)))
        minimum_duration = max(30, int(round(expected_duration * 0.80)))
        maximum_duration = max(expected_duration, int(round(expected_duration * 1.25)))

        rows.append(
            {
                "task_id": task_id,
                "request_id": request_id,
                "asset_id": row.asset_id,
                "section_id": row.section_id,
                "source_task_id": row.source_task_id,
                "task_name": row.task_name,
                "department": row.department,
                "task_type": infer_request_type(row.task_name, row.priority_level),
                "minimum_duration_min": minimum_duration,
                "expected_duration_min": expected_duration,
                "maximum_duration_min": maximum_duration,
                "minimum_continuous_time_min": minimum_duration,
                "requires_possession": True,
                "requires_power_isolation": bool(electrical_work),
                "requires_protection_staff": True,
                "requires_special_machine": False,
                "machine_type_required": "",
                "crew_skill_required": infer_asset_type(row.source_system, row.department, row.task_name),
                "material_readiness_required": True,
                "task_dependency_group": "",
                "priority_level": row.priority_level,
                "trackease_priority_score": round(float(row.priority_score), 2),
                "task_status": "READY_FOR_RESOURCE_PLANNING",
                "data_origin": DATA_ORIGIN,
                "integration_mode": PROTOTYPE_MODE,
                "is_prototype_derived": True,
            }
        )

    return pd.DataFrame(rows).sort_values("task_id").reset_index(drop=True)


def validate_domain(source, assets, requests, tasks):
    checks = {
        "source_tasks": len(source),
        "assets": len(assets),
        "requests": len(requests),
        "tasks": len(tasks),
        "duplicate_asset_ids": int(assets["asset_id"].duplicated().sum()),
        "duplicate_request_ids": int(requests["request_id"].duplicated().sum()),
        "duplicate_task_ids": int(tasks["task_id"].duplicated().sum()),
        "requests_missing_asset": int(requests["asset_id"].isna().sum()),
        "tasks_missing_request": int(tasks["request_id"].isna().sum()),
        "tasks_missing_asset": int(tasks["asset_id"].isna().sum()),
        "tasks_invalid_duration": int(
            (tasks["minimum_duration_min"] > tasks["expected_duration_min"]).sum()
            + (tasks["expected_duration_min"] > tasks["maximum_duration_min"]).sum()
        ),
    }

    hard_failures = [
        "duplicate_asset_ids",
        "duplicate_request_ids",
        "duplicate_task_ids",
        "requests_missing_asset",
        "tasks_missing_request",
        "tasks_missing_asset",
        "tasks_invalid_duration",
    ]

    if len(requests) != len(source):
        raise RuntimeError("Canonical request count does not match V2 source task count.")
    if len(tasks) != len(source):
        raise RuntimeError("Canonical task count does not match V2 source task count.")
    if sum(checks[key] for key in hard_failures) > 0:
        raise RuntimeError("V3 domain-model integrity validation failed.")

    return checks


def write_report(source_label, source, assets, requests, tasks, checks):
    department_counts = tasks["department"].value_counts().sort_index()
    asset_counts = assets["asset_type"].value_counts().sort_index()
    request_type_counts = requests["request_type"].value_counts().sort_index()

    lines = [
        "=" * 72,
        "TrackEase V3 Canonical Domain Model Report",
        "=" * 72,
        "",
        "SOURCE",
        "-" * 72,
        f"Input source                 : {source_label}",
        f"Input maintenance tasks      : {len(source):,}",
        "",
        "CANONICAL OUTPUTS",
        "-" * 72,
        f"Assets                       : {len(assets):,}",
        f"Maintenance requests         : {len(requests):,}",
        f"Executable tasks             : {len(tasks):,}",
        "",
        "ASSET TYPES",
        "-" * 72,
    ]

    for name, count in asset_counts.items():
        lines.append(f"{name:<36} {count:>8,}")

    lines.extend(["", "REQUEST TYPES", "-" * 72])
    for name, count in request_type_counts.items():
        lines.append(f"{name:<36} {count:>8,}")

    lines.extend(["", "TASK DEPARTMENTS", "-" * 72])
    for name, count in department_counts.items():
        lines.append(f"{name:<36} {count:>8,}")

    lines.extend(
        [
            "",
            "INTEGRITY CHECKS",
            "-" * 72,
            f"Duplicate asset IDs          : {checks['duplicate_asset_ids']:,}",
            f"Duplicate request IDs        : {checks['duplicate_request_ids']:,}",
            f"Duplicate task IDs           : {checks['duplicate_task_ids']:,}",
            f"Requests missing asset       : {checks['requests_missing_asset']:,}",
            f"Tasks missing request        : {checks['tasks_missing_request']:,}",
            f"Tasks missing asset          : {checks['tasks_missing_asset']:,}",
            f"Invalid duration ranges      : {checks['tasks_invalid_duration']:,}",
            "",
            "PROVENANCE",
            "-" * 72,
            f"Data origin                  : {DATA_ORIGIN}",
            f"Integration mode             : {PROTOTYPE_MODE}",
            "",
            "This layer converts existing TrackEase V2 maintenance planning records",
            "into a canonical Asset -> Request -> Task model.",
            "It does not claim unavailable public maintenance records contain",
            "authoritative Indian Railways asset serial numbers.",
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            "Build network-constraint enrichment and the resource master",
            "(departments, crews, machines, equipment, materials).",
        ]
    )

    REPORT_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    print("=" * 72)
    print("TrackEase V3 - Canonical Domain Model")
    print("=" * 72)

    source_raw, source_label = load_source()
    print(f"\nInput source : {source_label}")
    print(f"Rows loaded  : {len(source_raw):,}")

    source = normalize_source(source_raw)
    assets = build_assets(source)
    source_with_assets = attach_asset_ids(source, assets)
    requests = build_requests(source_with_assets)
    tasks = build_tasks(source_with_assets, requests)
    checks = validate_domain(source, assets, requests, tasks)

    assets.to_csv(ASSET_OUTPUT, index=False)
    requests.to_csv(REQUEST_OUTPUT, index=False)
    tasks.to_csv(TASK_OUTPUT, index=False)
    write_report(source_label, source, assets, requests, tasks, checks)

    print("\n" + "=" * 72)
    print("V3 DOMAIN MODEL COMPLETE")
    print("=" * 72)
    print(f"\nCanonical assets      : {len(assets):,}")
    print(f"Maintenance requests  : {len(requests):,}")
    print(f"Executable tasks      : {len(tasks):,}")
    print("\nIntegrity:")
    print(f"  Duplicate asset IDs     : {checks['duplicate_asset_ids']:,}")
    print(f"  Duplicate request IDs   : {checks['duplicate_request_ids']:,}")
    print(f"  Duplicate task IDs      : {checks['duplicate_task_ids']:,}")
    print(f"  Invalid duration ranges : {checks['tasks_invalid_duration']:,}")
    print("\nOutputs:")
    print(f"  {ASSET_OUTPUT}")
    print(f"  {REQUEST_OUTPUT}")
    print(f"  {TASK_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")
    print("\nTrackEase V3 now has a traceable Asset -> Request -> Task foundation.")


if __name__ == "__main__":
    main()
