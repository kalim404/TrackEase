"""
TrackEase V3 - Railway Network & Constraint Model

Builds the professional network layer required before resource-aware
optimization.

Inputs:
    data/processed/railway_sections.csv
    data/processed/weekly_section_movements.csv
    data/processed/stops_normalized.csv
    data/raw/stations.csv
    data/processed/v3_maintenance_tasks.csv   (optional supporting evidence)

Outputs:
    data/processed/v3_stations.csv
    data/processed/v3_sections.csv
    data/processed/v3_section_constraints.csv
    data/processed/v3_operational_rules.csv
    data/processed/v3_network_model_report.txt

Important:
    - Existing validated V2 files are read-only.
    - Observed traffic statistics are derived from TrackEase timetable data.
    - Infrastructure attributes unavailable from the source data are explicit
      prototype planning proxies, not claims about real Indian Railways assets.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

SECTIONS_FILE = PROCESSED_DIR / "railway_sections.csv"
WEEKLY_MOVEMENTS_FILE = PROCESSED_DIR / "weekly_section_movements.csv"
STOPS_FILE = PROCESSED_DIR / "stops_normalized.csv"
RAW_STATIONS_FILE = RAW_DIR / "stations.csv"
V3_TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"

STATIONS_OUTPUT = PROCESSED_DIR / "v3_stations.csv"
SECTIONS_OUTPUT = PROCESSED_DIR / "v3_sections.csv"
CONSTRAINTS_OUTPUT = PROCESSED_DIR / "v3_section_constraints.csv"
RULES_OUTPUT = PROCESSED_DIR / "v3_operational_rules.csv"
REPORT_OUTPUT = PROCESSED_DIR / "v3_network_model_report.txt"

WEEK_MINUTES = 10080
WEEK_HOURS = 168
DATA_ORIGIN_OBSERVED = "TRACKEASE_TIMETABLE_DERIVED"
PROTOTYPE_MODE = "PROTOTYPE_NETWORK_CONSTRAINT_ADAPTER"


def first_existing(columns, candidates):
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def text_series(df, column, default=""):
    if column is None:
        return pd.Series(
            [default] * len(df),
            index=df.index,
            dtype="string",
        )
    return (
        df[column]
        .fillna(default)
        .astype("string")
        .str.strip()
    )


def classify_by_quantiles(series):
    clean = pd.to_numeric(series, errors="coerce").fillna(0.0)

    if clean.nunique() <= 1:
        return pd.Series(
            ["Moderate"] * len(clean),
            index=clean.index,
            dtype="string",
        )

    q25 = float(clean.quantile(0.25))
    q50 = float(clean.quantile(0.50))
    q75 = float(clean.quantile(0.75))

    def classify(value):
        if value <= q25:
            return "Low"
        if value <= q50:
            return "Moderate"
        if value <= q75:
            return "High"
        return "Very High"

    return clean.map(classify)


def build_station_model():
    if not STOPS_FILE.exists():
        raise FileNotFoundError(f"Normalized stops file not found:\n{STOPS_FILE}")

    stops = pd.read_csv(STOPS_FILE, low_memory=False)
    columns = stops.columns.tolist()

    station_code_col = first_existing(
        columns, ["station_code", "station", "station_id"]
    )
    station_name_col = first_existing(
        columns, ["station_name", "name"]
    )
    train_col = first_existing(
        columns, ["train_number", "train_id", "train"]
    )

    if station_code_col is None:
        raise ValueError(
            "Could not identify station code in stops_normalized.csv."
        )

    if train_col:
        station_stats = (
            stops.groupby(station_code_col, dropna=False)
            .agg(
                stop_records=(station_code_col, "size"),
                unique_trains=(train_col, "nunique"),
            )
            .reset_index()
            .rename(columns={station_code_col: "station_code"})
        )
    else:
        station_stats = (
            stops.groupby(station_code_col, dropna=False)
            .size()
            .rename("stop_records")
            .reset_index()
            .rename(columns={station_code_col: "station_code"})
        )
        station_stats["unique_trains"] = station_stats["stop_records"]

    if station_name_col:
        names = (
            stops.groupby(station_code_col, dropna=False)[station_name_col]
            .first()
            .reset_index()
            .rename(
                columns={
                    station_code_col: "station_code",
                    station_name_col: "station_name",
                }
            )
        )
        station_stats = station_stats.merge(
            names,
            on="station_code",
            how="left",
            validate="one_to_one",
        )
    else:
        station_stats["station_name"] = ""

    latitude = {}
    longitude = {}

    if RAW_STATIONS_FILE.exists():
        raw = pd.read_csv(RAW_STATIONS_FILE, low_memory=False)
        raw_columns = raw.columns.tolist()
        raw_code_col = first_existing(
            raw_columns, ["station_code", "code", "station", "station_id"]
        )
        lat_col = first_existing(
            raw_columns, ["latitude", "lat", "station_latitude"]
        )
        lon_col = first_existing(
            raw_columns, ["longitude", "lon", "lng", "station_longitude"]
        )

        if raw_code_col:
            raw = raw.copy()
            raw["_station_code"] = text_series(raw, raw_code_col)
            raw = raw.drop_duplicates("_station_code", keep="first")

            if lat_col:
                latitude = raw.set_index("_station_code")[lat_col].to_dict()
            if lon_col:
                longitude = raw.set_index("_station_code")[lon_col].to_dict()

    station_stats["station_code"] = (
        station_stats["station_code"].astype("string").str.strip()
    )
    station_stats["latitude"] = station_stats["station_code"].map(latitude)
    station_stats["longitude"] = station_stats["station_code"].map(longitude)

    station_stats["traffic_class"] = classify_by_quantiles(
        station_stats["stop_records"]
    )

    max_stops = max(1.0, float(station_stats["stop_records"].max()))
    max_trains = max(1.0, float(station_stats["unique_trains"].max()))

    station_stats["hub_score"] = (
        60.0 * station_stats["stop_records"] / max_stops
        + 40.0 * station_stats["unique_trains"] / max_trains
    ).round(2)

    station_stats["hub_class"] = classify_by_quantiles(
        station_stats["hub_score"]
    )

    station_stats["maintenance_access_proxy"] = (
        station_stats["hub_class"].isin(["High", "Very High"])
    )
    station_stats["loop_facility_proxy"] = (
        station_stats["traffic_class"].isin(["High", "Very High"])
    )
    station_stats["yard_facility_proxy"] = (
        station_stats["hub_class"].eq("Very High")
    )

    station_stats["traffic_data_origin"] = DATA_ORIGIN_OBSERVED
    station_stats["facility_data_origin"] = PROTOTYPE_MODE
    station_stats["is_prototype_enriched"] = True

    return (
        station_stats[
            [
                "station_code",
                "station_name",
                "latitude",
                "longitude",
                "stop_records",
                "unique_trains",
                "traffic_class",
                "hub_score",
                "hub_class",
                "maintenance_access_proxy",
                "loop_facility_proxy",
                "yard_facility_proxy",
                "traffic_data_origin",
                "facility_data_origin",
                "is_prototype_enriched",
            ]
        ]
        .sort_values("station_code")
        .reset_index(drop=True)
    )


def load_section_master():
    if not SECTIONS_FILE.exists():
        raise FileNotFoundError(f"Section master not found:\n{SECTIONS_FILE}")

    sections = pd.read_csv(SECTIONS_FILE, low_memory=False)
    section_id_col = first_existing(
        sections.columns.tolist(), ["section_id", "railway_section_id"]
    )

    if section_id_col is None:
        raise ValueError(
            "Could not identify section_id in railway_sections.csv."
        )

    if section_id_col != "section_id":
        sections = sections.rename(columns={section_id_col: "section_id"})

    sections["section_id"] = (
        sections["section_id"].astype("string").str.strip()
    )

    duplicate_count = int(sections["section_id"].duplicated().sum())
    if duplicate_count:
        raise ValueError(
            f"Section master contains {duplicate_count:,} duplicate section IDs."
        )

    return sections


def build_movement_statistics():
    if not WEEKLY_MOVEMENTS_FILE.exists():
        raise FileNotFoundError(
            f"Weekly movements file not found:\n{WEEKLY_MOVEMENTS_FILE}"
        )

    movements = pd.read_csv(WEEKLY_MOVEMENTS_FILE, low_memory=False)
    columns = movements.columns.tolist()

    section_col = first_existing(
        columns, ["section_id", "railway_section_id"]
    )
    train_col = first_existing(
        columns, ["train_number", "train_id", "train"]
    )
    start_col = first_existing(
        columns,
        [
            "weekly_start_minute",
            "start_week_minute",
            "movement_start_minute",
            "entry_week_minute",
            "departure_week_minute",
            "start_minute",
        ],
    )
    from_col = first_existing(
        columns,
        [
            "from_station_code",
            "station_a_code",
            "from_station",
            "origin_station_code",
        ],
    )
    to_col = first_existing(
        columns,
        [
            "to_station_code",
            "station_b_code",
            "to_station",
            "destination_station_code",
        ],
    )

    if section_col is None:
        raise ValueError(
            "weekly_section_movements.csv has no recognizable section ID."
        )

    working = pd.DataFrame(
        {"section_id": text_series(movements, section_col)}
    )
    working["train_number"] = (
        text_series(movements, train_col) if train_col else ""
    )

    if from_col and to_col:
        working["direction_key"] = (
            text_series(movements, from_col)
            + ">"
            + text_series(movements, to_col)
        )
    else:
        working["direction_key"] = ""

    if start_col:
        working["start_minute"] = (
            pd.to_numeric(movements[start_col], errors="coerce")
            % WEEK_MINUTES
        )
        working["hour_bucket"] = working["start_minute"] // 60
    else:
        working["start_minute"] = np.nan
        working["hour_bucket"] = np.nan

    grouped = (
        working.groupby("section_id", dropna=False)
        .agg(
            weekly_train_movements=("section_id", "size"),
            unique_trains=("train_number", "nunique"),
            observed_directions=(
                "direction_key",
                lambda values: len(
                    {
                        str(v).strip()
                        for v in values
                        if str(v).strip()
                    }
                ),
            ),
        )
        .reset_index()
    )

    if start_col:
        hourly = (
            working.dropna(subset=["hour_bucket"])
            .groupby(["section_id", "hour_bucket"])
            .size()
            .rename("hourly_movements")
            .reset_index()
        )

        peak = (
            hourly.groupby("section_id")["hourly_movements"]
            .max()
            .rename("observed_peak_trains_per_hour")
            .reset_index()
        )

        grouped = grouped.merge(
            peak,
            on="section_id",
            how="left",
            validate="one_to_one",
        )
    else:
        grouped["observed_peak_trains_per_hour"] = np.nan

    fallback_peak = np.ceil(
        grouped["weekly_train_movements"] / WEEK_HOURS
    )

    grouped["observed_peak_trains_per_hour"] = (
        pd.to_numeric(
            grouped["observed_peak_trains_per_hour"],
            errors="coerce",
        )
        .fillna(fallback_peak)
        .clip(lower=1)
        .astype(int)
    )

    grouped["average_trains_per_day"] = (
        grouped["weekly_train_movements"] / 7.0
    ).round(2)

    return grouped


def build_section_model(section_master, movement_stats):
    """
    Merge validated section metadata with newly derived weekly movement stats.

    Some V2 section-master files already contain columns such as
    ``unique_trains``. A normal pandas merge would rename those duplicates to
    ``unique_trains_x`` / ``unique_trains_y``, after which downstream code
    looking for the canonical ``unique_trains`` field would fail.

    Preserve the older section-master value under a ``master_`` prefix and let
    the freshly derived weekly-movement statistic keep the canonical name.
    This makes the migration robust without discarding historical V2 fields.
    """

    section_master = section_master.copy()
    movement_stats = movement_stats.copy()

    overlapping_columns = sorted(
        (
            set(section_master.columns)
            & set(movement_stats.columns)
        )
        - {"section_id"}
    )

    if overlapping_columns:
        section_master = section_master.rename(
            columns={
                column: f"master_{column}"
                for column in overlapping_columns
            }
        )

    sections = section_master.merge(
        movement_stats,
        on="section_id",
        how="left",
        validate="one_to_one",
    )

    numeric_columns = [
        "weekly_train_movements",
        "unique_trains",
        "observed_directions",
        "observed_peak_trains_per_hour",
        "average_trains_per_day",
    ]

    for column in numeric_columns:
        sections[column] = pd.to_numeric(
            sections[column], errors="coerce"
        ).fillna(0)

    for column in [
        "weekly_train_movements",
        "unique_trains",
        "observed_directions",
        "observed_peak_trains_per_hour",
    ]:
        sections[column] = sections[column].astype(int)

    sections["traffic_class"] = classify_by_quantiles(
        sections["weekly_train_movements"]
    )

    max_traffic = max(
        1.0,
        float(sections["weekly_train_movements"].max()),
    )

    sections["section_criticality_score"] = (
        100.0
        * sections["weekly_train_movements"]
        / max_traffic
    ).round(2)

    sections["section_criticality_level"] = classify_by_quantiles(
        sections["section_criticality_score"]
    )

    sections["directionality_observed"] = np.select(
        [
            sections["observed_directions"] >= 2,
            sections["observed_directions"] == 1,
        ],
        [
            "BIDIRECTIONAL_MOVEMENTS_OBSERVED",
            "SINGLE_DIRECTION_MOVEMENTS_OBSERVED",
        ],
        default="NO_MOVEMENT_DIRECTION_EVIDENCE",
    )

    sections["traffic_data_origin"] = DATA_ORIGIN_OBSERVED

    return sections


def build_section_constraints(sections):
    constraints = pd.DataFrame(
        {
            "section_id": sections["section_id"],
            "weekly_train_movements":
                sections["weekly_train_movements"],
            "observed_peak_trains_per_hour":
                sections["observed_peak_trains_per_hour"],
            "traffic_class":
                sections["traffic_class"],
            "section_criticality_score":
                sections["section_criticality_score"],
            "section_criticality_level":
                sections["section_criticality_level"],
            "directionality_observed":
                sections["directionality_observed"],
        }
    )

    constraints["capacity_proxy_trains_per_hour"] = (
        constraints["observed_peak_trains_per_hour"]
        + np.where(
            constraints["traffic_class"].isin(["High", "Very High"]),
            2,
            1,
        )
    ).astype(int)

    constraints["capacity_utilization_proxy"] = (
        constraints["observed_peak_trains_per_hour"]
        / constraints["capacity_proxy_trains_per_hour"]
    ).round(3)

    constraints["track_configuration_proxy"] = np.select(
        [
            constraints["observed_peak_trains_per_hour"] >= 4,
            constraints["observed_peak_trains_per_hour"] >= 2,
        ],
        [
            "HIGH_CAPACITY_CORRIDOR_PROXY",
            "MEDIUM_CAPACITY_CORRIDOR_PROXY",
        ],
        default="LOW_CAPACITY_CORRIDOR_PROXY",
    )

    constraints["allowed_block_types"] = np.where(
        constraints["track_configuration_proxy"].eq(
            "HIGH_CAPACITY_CORRIDOR_PROXY"
        ),
        "FULL_POSSESSION|PARTIAL_POSSESSION",
        "FULL_POSSESSION",
    )

    constraints["operational_constraint_level"] = np.select(
        [
            constraints["traffic_class"].eq("Very High"),
            constraints["traffic_class"].eq("High"),
            constraints["traffic_class"].eq("Moderate"),
        ],
        ["VERY_HIGH", "HIGH", "MODERATE"],
        default="LOW",
    )

    constraints["minimum_block_minutes"] = 30
    constraints["train_safety_buffer_minutes"] = 10
    constraints["goods_safety_buffer_minutes"] = 10

    constraints["physical_track_type"] = "UNKNOWN_SOURCE_DATA"
    constraints["electrification_status"] = "UNKNOWN_SOURCE_DATA"
    constraints["signalling_system"] = "UNKNOWN_SOURCE_DATA"
    constraints["permanent_speed_limit_kmph"] = np.nan

    constraints["capacity_basis"] = (
        "OBSERVED_TIMETABLE_PEAK_PLUS_HEADROOM"
    )
    constraints["physical_infrastructure_origin"] = (
        "NOT_AVAILABLE_IN_CURRENT_SOURCE"
    )
    constraints["planning_constraint_origin"] = PROTOTYPE_MODE
    constraints["is_prototype_enriched"] = True

    return constraints.sort_values("section_id").reset_index(drop=True)


def add_task_evidence(constraints):
    result = constraints.copy()

    result["maintenance_task_count"] = 0
    result["electrical_task_present"] = False
    result["signal_task_present"] = False
    result["engineering_task_present"] = False

    if not V3_TASKS_FILE.exists():
        return result

    tasks = pd.read_csv(V3_TASKS_FILE, low_memory=False)

    if not {"section_id", "department"}.issubset(tasks.columns):
        return result

    evidence = tasks.copy()
    evidence["department_upper"] = (
        evidence["department"]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    section_evidence = (
        evidence.groupby("section_id")
        .agg(
            maintenance_task_count=("section_id", "size"),
            electrical_task_present=(
                "department_upper",
                lambda values: any(
                    "ELECTRICAL" in value or "TDMS" in value
                    for value in values
                ),
            ),
            signal_task_present=(
                "department_upper",
                lambda values: any(
                    "S&T" in value
                    or "SIGNAL" in value
                    or "SMMS" in value
                    for value in values
                ),
            ),
            engineering_task_present=(
                "department_upper",
                lambda values: any(
                    "ENGINEERING" in value or "TMS" in value
                    for value in values
                ),
            ),
        )
        .reset_index()
    )

    result = (
        result.drop(
            columns=[
                "maintenance_task_count",
                "electrical_task_present",
                "signal_task_present",
                "engineering_task_present",
            ]
        )
        .merge(
            section_evidence,
            on="section_id",
            how="left",
            validate="one_to_one",
        )
    )

    result["maintenance_task_count"] = (
        result["maintenance_task_count"]
        .fillna(0)
        .astype(int)
    )

    for column in [
        "electrical_task_present",
        "signal_task_present",
        "engineering_task_present",
    ]:
        result[column] = (
            result[column]
            .fillna(False)
            .astype(bool)
        )

    return result


def build_operational_rules():
    rules = [
        (
            "RULE-001",
            "BLOCK_DURATION",
            "Minimum usable maintenance block",
            "30",
            "minutes",
            True,
            "Candidate maintenance blocks shorter than 30 minutes are "
            "not considered usable by the prototype.",
        ),
        (
            "RULE-002",
            "TRAIN_SAFETY",
            "Scheduled train safety buffer",
            "10",
            "minutes",
            True,
            "Maintenance occupancy must remain outside the configured "
            "scheduled-train safety buffer.",
        ),
        (
            "RULE-003",
            "FREIGHT_SAFETY",
            "COA goods forecast safety buffer",
            "10",
            "minutes",
            True,
            "Forecast goods occupancy receives the configured prototype "
            "safety buffer.",
        ),
        (
            "RULE-004",
            "SAFETY",
            "Safety is not tradeable",
            "ENFORCED",
            "",
            True,
            "Safety and conflict feasibility are hard gates and cannot "
            "be compensated by a better optimization score.",
        ),
        (
            "RULE-005",
            "ELECTRICAL",
            "Power isolation for electrical work",
            "REQUIRED_WHEN_TASK_REQUIRES",
            "",
            True,
            "Electrical/OHE tasks requiring isolation cannot be scheduled "
            "unless isolation feasibility is satisfied.",
        ),
        (
            "RULE-006",
            "PROTECTION",
            "Protection staff requirement",
            "REQUIRED_WHEN_TASK_REQUIRES",
            "",
            True,
            "Possession tasks requiring protection staff cannot be "
            "scheduled without compatible protection resources.",
        ),
        (
            "RULE-007",
            "HUMAN_APPROVAL",
            "Human approval before downstream submission",
            "APPROVED_ONLY",
            "",
            True,
            "Only human-approved recommendations may enter the "
            "BDMS-style export.",
        ),
        (
            "RULE-008",
            "PROVENANCE",
            "Prototype data disclosure",
            "MANDATORY",
            "",
            True,
            "Generated resource/infrastructure data must retain explicit "
            "prototype provenance labels.",
        ),
    ]

    columns = [
        "rule_id",
        "rule_category",
        "rule_name",
        "rule_value",
        "unit",
        "hard_constraint",
        "description",
    ]

    rules_df = pd.DataFrame(rules, columns=columns)
    rules_df["rule_source"] = "TRACKEASE_PROTOTYPE_POLICY"
    return rules_df


def validate_outputs(stations, sections, constraints, rules):
    checks = {
        "stations": len(stations),
        "sections": len(sections),
        "constraints": len(constraints),
        "rules": len(rules),
        "duplicate_station_codes":
            int(stations["station_code"].duplicated().sum()),
        "duplicate_section_ids":
            int(sections["section_id"].duplicated().sum()),
        "duplicate_constraint_sections":
            int(constraints["section_id"].duplicated().sum()),
        "missing_constraint_sections":
            int(
                (
                    ~sections["section_id"].isin(
                        constraints["section_id"]
                    )
                ).sum()
            ),
        "invalid_capacity_proxy":
            int(
                (
                    constraints["capacity_proxy_trains_per_hour"]
                    < constraints["observed_peak_trains_per_hour"]
                ).sum()
            ),
        "invalid_utilization":
            int(
                (
                    constraints["capacity_utilization_proxy"] > 1.0
                ).sum()
            ),
    }

    failures = sum(
        checks[key]
        for key in [
            "duplicate_station_codes",
            "duplicate_section_ids",
            "duplicate_constraint_sections",
            "missing_constraint_sections",
            "invalid_capacity_proxy",
            "invalid_utilization",
        ]
    )

    if len(sections) != len(constraints):
        raise RuntimeError(
            "Every V3 section must have exactly one constraint record."
        )

    if failures:
        raise RuntimeError(
            "V3 network-model integrity validation failed."
        )

    return checks


def write_report(stations, sections, constraints, rules, checks):
    traffic_counts = (
        sections["traffic_class"]
        .value_counts()
        .sort_index()
    )

    constraint_counts = (
        constraints["operational_constraint_level"]
        .value_counts()
        .sort_index()
    )

    lines = [
        "=" * 72,
        "TrackEase V3 Railway Network Model Report",
        "=" * 72,
        "",
        "OUTPUT SUMMARY",
        "-" * 72,
        f"Stations                     : {len(stations):,}",
        f"Railway sections             : {len(sections):,}",
        f"Section constraint records   : {len(constraints):,}",
        f"Operational rules            : {len(rules):,}",
        "",
        "SECTION TRAFFIC CLASS",
        "-" * 72,
    ]

    for name, count in traffic_counts.items():
        lines.append(f"{name:<30} {count:>10,}")

    lines.extend(
        [
            "",
            "OPERATIONAL CONSTRAINT LEVEL",
            "-" * 72,
        ]
    )

    for name, count in constraint_counts.items():
        lines.append(f"{name:<30} {count:>10,}")

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                f"Duplicate station codes      : "
                f"{checks['duplicate_station_codes']:,}"
            ),
            (
                f"Duplicate section IDs        : "
                f"{checks['duplicate_section_ids']:,}"
            ),
            (
                f"Duplicate constraint sections: "
                f"{checks['duplicate_constraint_sections']:,}"
            ),
            (
                f"Sections missing constraints : "
                f"{checks['missing_constraint_sections']:,}"
            ),
            (
                f"Invalid capacity proxies     : "
                f"{checks['invalid_capacity_proxy']:,}"
            ),
            (
                f"Invalid utilization proxies  : "
                f"{checks['invalid_utilization']:,}"
            ),
            "",
            "DATA PROVENANCE",
            "-" * 72,
            (
                "Observed traffic metrics come from TrackEase timetable-derived "
                "weekly section movements."
            ),
            (
                "Unavailable physical track, signalling, electrification and "
                "station-facility attributes are not claimed as real source facts."
            ),
            (
                "Prototype planning fields are explicitly marked with "
                f"{PROTOTYPE_MODE}."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build departments, crews, crew skills/shifts, machines, "
                "equipment, materials and their availability datasets."
            ),
        ]
    )

    REPORT_OUTPUT.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main():
    print("=" * 72)
    print("TrackEase V3 - Railway Network & Constraint Model")
    print("=" * 72)

    print("\nBuilding station model...")
    stations = build_station_model()

    print("Loading validated section master...")
    section_master = load_section_master()

    print("Deriving weekly section traffic...")
    movement_stats = build_movement_statistics()

    print("Building V3 section model...")
    sections = build_section_model(
        section_master,
        movement_stats,
    )

    print("Building section constraints...")
    constraints = build_section_constraints(sections)
    constraints = add_task_evidence(constraints)

    print("Building operational rules...")
    rules = build_operational_rules()

    checks = validate_outputs(
        stations,
        sections,
        constraints,
        rules,
    )

    stations.to_csv(STATIONS_OUTPUT, index=False)
    sections.to_csv(SECTIONS_OUTPUT, index=False)
    constraints.to_csv(CONSTRAINTS_OUTPUT, index=False)
    rules.to_csv(RULES_OUTPUT, index=False)

    write_report(
        stations,
        sections,
        constraints,
        rules,
        checks,
    )

    print("\n" + "=" * 72)
    print("V3 NETWORK MODEL COMPLETE")
    print("=" * 72)

    print(f"\nStations                  : {len(stations):,}")
    print(f"Railway sections          : {len(sections):,}")
    print(f"Section constraints       : {len(constraints):,}")
    print(f"Operational rules         : {len(rules):,}")

    print("\nIntegrity:")
    print(
        f"  Duplicate station codes      : "
        f"{checks['duplicate_station_codes']:,}"
    )
    print(
        f"  Duplicate section IDs        : "
        f"{checks['duplicate_section_ids']:,}"
    )
    print(
        f"  Missing section constraints  : "
        f"{checks['missing_constraint_sections']:,}"
    )
    print(
        f"  Invalid capacity proxies     : "
        f"{checks['invalid_capacity_proxy']:,}"
    )

    print("\nOutputs:")
    print(f"  {STATIONS_OUTPUT}")
    print(f"  {SECTIONS_OUTPUT}")
    print(f"  {CONSTRAINTS_OUTPUT}")
    print(f"  {RULES_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")

    print(
        "\nTrackEase V3 now has an explicit railway network and "
        "constraint layer for resource-aware planning."
    )


if __name__ == "__main__":
    main()
