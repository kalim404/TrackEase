"""
TrackEase V3.9 - Passenger / Freight Operational Impact Model

Purpose
-------
Prepare explicit train-operation exposure metrics before candidate-window
selection and Optimizer V3.

This stage estimates how much scheduled passenger/timetable traffic and
forecast goods traffic a maintenance task is likely to interact with on its
section, using:
    - validated weekly section movements
    - V3 detailed block duration
    - optional COA-style goods forecast/events
    - observed section traffic intensity

Important scope
---------------
This is a PRE-WINDOW operational exposure model.

It does NOT claim that a specific train is affected until a concrete block
window is selected. Exact affected train numbers, exact overlaps and final
delay estimates are produced later when the opportunity/candidate-window
engine assigns clock times.

Where the public timetable dataset does not explicitly identify train class,
TrackEase labels those movements as SCHEDULED_TIMETABLE_TRAFFIC rather than
silently inventing passenger/freight categories. The separate COA-style goods
forecast is used for freight exposure when available.

Inputs
------
Required:
    data/processed/v3_task_timing_components.csv
    data/processed/v3_task_block_requirements.csv

Auto-discovered:
    validated weekly section movement CSV
    optional COA/goods forecast CSV

Outputs
-------
    data/processed/v3_section_traffic_profiles.csv
    data/processed/v3_task_operational_exposure.csv
    data/processed/v3_operational_impact_model_report.txt

All scores are transparent TrackEase decision-support proxies, not official
Indian Railways delay predictions.
"""

from __future__ import annotations

from pathlib import Path
import math

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TIMING_FILE = PROCESSED_DIR / "v3_task_timing_components.csv"
BLOCK_REQUIREMENTS_FILE = PROCESSED_DIR / "v3_task_block_requirements.csv"

SECTION_PROFILE_OUTPUT = (
    PROCESSED_DIR / "v3_section_traffic_profiles.csv"
)
TASK_EXPOSURE_OUTPUT = (
    PROCESSED_DIR / "v3_task_operational_exposure.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_operational_impact_model_report.txt"
)


# ---------------------------------------------------------------------------
# Provenance / constants
# ---------------------------------------------------------------------------

DATA_ORIGIN = "TRACKEASE_V3_OPERATIONAL_EXPOSURE"
INTEGRATION_MODE = "PROTOTYPE_TIMETABLE_COA_IMPACT_MODEL"

MINUTES_PER_WEEK = 7 * 24 * 60

# Passenger/timetable and freight remain separate. This combined score is only
# a planning exposure index, not the final Optimizer V3 objective.
COMBINED_WEIGHT_SCHEDULED = 0.65
COMBINED_WEIGHT_GOODS = 0.25
COMBINED_WEIGHT_PEAK = 0.10


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_text(value: object, default: str = "") -> str:
    if pd.isna(value):
        return default

    text = str(value).strip()

    if text.lower() in {"nan", "none", "<na>"}:
        return default

    return text


def first_existing(
    columns: list[str],
    candidates: list[str],
) -> str | None:

    available = set(columns)

    for candidate in candidates:
        if candidate in available:
            return candidate

    return None


def safe_float(value: object) -> float | None:
    if pd.isna(value):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def clamp(
    value: float,
    lower: float = 0.0,
    upper: float = 100.0,
) -> float:
    return max(lower, min(upper, value))


def minmax_0_100(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    valid = numeric.dropna()

    if valid.empty:
        return pd.Series(
            [0.0] * len(series),
            index=series.index,
            dtype=float,
        )

    low = float(valid.min())
    high = float(valid.max())

    if math.isclose(low, high):
        return pd.Series(
            [50.0] * len(series),
            index=series.index,
            dtype=float,
        )

    return (
        (
            numeric - low
        )
        / (
            high - low
        )
        * 100.0
    ).fillna(0.0).clip(
        0,
        100,
    )


def require_inputs() -> None:
    missing = [
        path
        for path in [
            TIMING_FILE,
            BLOCK_REQUIREMENTS_FILE,
        ]
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.9 inputs are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_weekly_movements_file() -> Path:
    preferred = [
        PROCESSED_DIR / "weekly_section_movements.csv",
        PROCESSED_DIR / "section_weekly_movements.csv",
        PROCESSED_DIR / "weekly_movements.csv",
    ]

    for path in preferred:
        if path.exists():
            return path

    patterns = [
        "*weekly*section*movement*.csv",
        "*section*movement*weekly*.csv",
        "*weekly*movement*.csv",
    ]

    candidates: list[Path] = []

    for pattern in patterns:
        candidates.extend(
            PROCESSED_DIR.glob(
                pattern
            )
        )

    candidates = sorted(
        {
            path.resolve()
            for path in candidates
            if not path.name.startswith(
                "v3_"
            )
        }
    )

    if not candidates:
        raise FileNotFoundError(
            "Could not find the validated weekly section movement CSV in "
            f"{PROCESSED_DIR}."
        )

    return Path(
        candidates[0]
    )


def discover_goods_file() -> Path | None:
    preferred = [
        PROCESSED_DIR / "coa_goods_forecast.csv",
        PROCESSED_DIR / "coa_goods_events.csv",
        PROCESSED_DIR / "prototype_coa_goods_forecast.csv",
        PROCESSED_DIR / "goods_train_forecast.csv",
    ]

    for path in preferred:
        if path.exists():
            return path

    patterns = [
        "*coa*goods*.csv",
        "*goods*forecast*.csv",
        "*goods*event*.csv",
        "*freight*forecast*.csv",
    ]

    candidates: list[Path] = []

    for pattern in patterns:
        candidates.extend(
            PROCESSED_DIR.glob(
                pattern
            )
        )

    candidates = sorted(
        {
            path.resolve()
            for path in candidates
            if "adjusted_safe_window" not in path.name.lower()
        }
    )

    if not candidates:
        return None

    return Path(
        candidates[0]
    )


# ---------------------------------------------------------------------------
# Movement schema detection
# ---------------------------------------------------------------------------

def detect_movement_schema(
    movements: pd.DataFrame,
) -> dict[str, str | None]:

    columns = movements.columns.tolist()

    section = first_existing(
        columns,
        [
            "section_id",
            "railway_section_id",
            "section",
        ],
    )

    train = first_existing(
        columns,
        [
            "train_number",
            "train_id",
            "train_no",
            "train",
        ],
    )

    absolute_start = first_existing(
        columns,
        [
            "entry_abs_min",
            "start_abs_min",
            "section_entry_abs_min",
            "entry_minute_of_week",
            "start_minute_of_week",
            "absolute_start_min",
            "entry_min",
            "start_min",
        ],
    )

    day = first_existing(
        columns,
        [
            "day_of_week",
            "weekday",
            "week_day",
            "day",
        ],
    )

    time_text = first_existing(
        columns,
        [
            "entry_time",
            "start_time",
            "section_entry_time",
            "departure",
            "arrival",
        ],
    )

    train_class = first_existing(
        columns,
        [
            "train_type",
            "category",
            "train_category",
            "service_type",
            "traffic_type",
        ],
    )

    if section is None:
        raise ValueError(
            "Weekly movement file does not contain a recognizable section_id "
            f"column. Columns found: {columns}"
        )

    return {
        "section":
            section,

        "train":
            train,

        "absolute_start":
            absolute_start,

        "day":
            day,

        "time_text":
            time_text,

        "train_class":
            train_class,
    }


def hhmm_to_minutes(value: object) -> float | None:
    text = clean_text(
        value
    )

    if not text:
        return None

    if ":" not in text:
        return None

    try:
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1])

        if (
            hour < 0
            or hour > 23
            or minute < 0
            or minute > 59
        ):
            return None

        return float(
            hour * 60
            + minute
        )
    except (
        TypeError,
        ValueError,
        IndexError,
    ):
        return None


def normalized_day_index(value: object) -> int | None:
    if pd.isna(value):
        return None

    text = str(value).strip().upper()

    name_map = {
        "MONDAY": 0,
        "MON": 0,
        "TUESDAY": 1,
        "TUE": 1,
        "TUES": 1,
        "WEDNESDAY": 2,
        "WED": 2,
        "THURSDAY": 3,
        "THU": 3,
        "THUR": 3,
        "FRIDAY": 4,
        "FRI": 4,
        "SATURDAY": 5,
        "SAT": 5,
        "SUNDAY": 6,
        "SUN": 6,
    }

    if text in name_map:
        return name_map[text]

    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None

    if 0 <= number <= 6:
        return number

    if 1 <= number <= 7:
        return number - 1

    return None


def add_week_position(
    movements: pd.DataFrame,
    schema: dict[str, str | None],
) -> pd.DataFrame:

    working = movements.copy()

    absolute_column = schema["absolute_start"]

    if absolute_column is not None:
        absolute = pd.to_numeric(
            working[
                absolute_column
            ],
            errors="coerce",
        )

        # Some V2 files may contain absolute journey minutes beyond one week.
        working[
            "_minute_of_week"
        ] = absolute.mod(
            MINUTES_PER_WEEK
        )

    else:
        time_column = schema["time_text"]

        if time_column is None:
            working[
                "_minute_of_week"
            ] = pd.NA
        else:
            minute_of_day = working[
                time_column
            ].map(
                hhmm_to_minutes
            )

            day_column = schema["day"]

            if day_column is None:
                working[
                    "_minute_of_week"
                ] = minute_of_day
            else:
                day_index = working[
                    day_column
                ].map(
                    normalized_day_index
                )

                working[
                    "_minute_of_week"
                ] = (
                    pd.to_numeric(
                        day_index,
                        errors="coerce",
                    )
                    * 1440
                    + pd.to_numeric(
                        minute_of_day,
                        errors="coerce",
                    )
                )

    working[
        "_weekday_index"
    ] = (
        pd.to_numeric(
            working[
                "_minute_of_week"
            ],
            errors="coerce",
        )
        // 1440
    )

    working[
        "_hour_of_day"
    ] = (
        (
            pd.to_numeric(
                working[
                    "_minute_of_week"
                ],
                errors="coerce",
            )
            % 1440
        )
        // 60
    )

    return working


# ---------------------------------------------------------------------------
# Goods schema / aggregation
# ---------------------------------------------------------------------------

def detect_goods_schema(
    goods: pd.DataFrame,
) -> dict[str, str | None]:

    columns = goods.columns.tolist()

    return {
        "section":
            first_existing(
                columns,
                [
                    "section_id",
                    "railway_section_id",
                    "section",
                ],
            ),

        "event_id":
            first_existing(
                columns,
                [
                    "event_id",
                    "goods_event_id",
                    "forecast_id",
                    "train_id",
                    "train_number",
                ],
            ),
    }


def build_goods_counts(
    goods: pd.DataFrame | None,
) -> tuple[pd.DataFrame, str]:

    if goods is None:
        return (
            pd.DataFrame(
                columns=[
                    "section_id",
                    "goods_forecast_events_week",
                ]
            ),
            "NO_COA_GOODS_FILE_FOUND",
        )

    schema = detect_goods_schema(
        goods
    )

    section_column = schema["section"]

    if section_column is None:
        return (
            pd.DataFrame(
                columns=[
                    "section_id",
                    "goods_forecast_events_week",
                ]
            ),
            "COA_FILE_FOUND_BUT_SECTION_COLUMN_UNRECOGNIZED",
        )

    working = goods.copy()

    working[
        "section_id"
    ] = (
        working[
            section_column
        ]
        .astype(str)
        .str.strip()
    )

    event_column = schema["event_id"]

    if event_column is not None:
        counts = (
            working.groupby(
                "section_id"
            )[
                event_column
            ]
            .nunique()
            .rename(
                "goods_forecast_events_week"
            )
            .reset_index()
        )
    else:
        counts = (
            working.groupby(
                "section_id"
            )
            .size()
            .rename(
                "goods_forecast_events_week"
            )
            .reset_index()
        )

    return (
        counts,
        "COA_STYLE_GOODS_FORECAST_USED",
    )


# ---------------------------------------------------------------------------
# Section traffic profiles
# ---------------------------------------------------------------------------

def build_section_profiles(
    movements: pd.DataFrame,
    movement_schema: dict[str, str | None],
    goods_counts: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:

    working = add_week_position(
        movements,
        movement_schema,
    )

    section_column = movement_schema[
        "section"
    ]

    working[
        "section_id"
    ] = (
        working[
            section_column
        ]
        .astype(str)
        .str.strip()
    )

    train_column = movement_schema[
        "train"
    ]

    if train_column is not None:
        weekly_counts = (
            working.groupby(
                "section_id"
            )[
                train_column
            ]
            .nunique()
            .rename(
                "scheduled_trains_week"
            )
        )
    else:
        weekly_counts = (
            working.groupby(
                "section_id"
            )
            .size()
            .rename(
                "scheduled_trains_week"
            )
        )

    valid_clock = working.dropna(
        subset=[
            "_weekday_index",
            "_hour_of_day",
        ]
    ).copy()

    if valid_clock.empty:
        peak = pd.Series(
            0,
            index=weekly_counts.index,
            name="observed_peak_trains_per_hour",
            dtype=float,
        )

        clock_basis = (
            "NO_RECOGNIZABLE_MOVEMENT_CLOCK; WEEKLY_COUNTS_ONLY"
        )
    else:
        hourly = (
            valid_clock.groupby(
                [
                    "section_id",
                    "_weekday_index",
                    "_hour_of_day",
                ]
            )
            .size()
            .rename(
                "hourly_movement_count"
            )
            .reset_index()
        )

        peak = (
            hourly.groupby(
                "section_id"
            )[
                "hourly_movement_count"
            ]
            .max()
            .rename(
                "observed_peak_trains_per_hour"
            )
        )

        clock_basis = (
            "WEEKLY_MOVEMENT_CLOCK_AVAILABLE"
        )

    profile = (
        weekly_counts.to_frame()
        .join(
            peak,
            how="left",
        )
        .fillna(
            {
                "observed_peak_trains_per_hour": 0,
            }
        )
        .reset_index()
    )

    profile = profile.merge(
        goods_counts,
        on="section_id",
        how="left",
    )

    profile[
        "goods_forecast_events_week"
    ] = (
        pd.to_numeric(
            profile[
                "goods_forecast_events_week"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )

    profile[
        "scheduled_trains_week"
    ] = (
        pd.to_numeric(
            profile[
                "scheduled_trains_week"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype(int)
    )

    profile[
        "observed_peak_trains_per_hour"
    ] = (
        pd.to_numeric(
            profile[
                "observed_peak_trains_per_hour"
            ],
            errors="coerce",
        )
        .fillna(0)
        .astype(float)
    )

    profile[
        "scheduled_trains_per_hour_average"
    ] = (
        profile[
            "scheduled_trains_week"
        ]
        / (
            7 * 24
        )
    )

    profile[
        "goods_events_per_hour_average"
    ] = (
        profile[
            "goods_forecast_events_week"
        ]
        / (
            7 * 24
        )
    )

    profile[
        "scheduled_traffic_score"
    ] = minmax_0_100(
        profile[
            "scheduled_trains_week"
        ]
    ).round(3)

    profile[
        "goods_traffic_score"
    ] = minmax_0_100(
        profile[
            "goods_forecast_events_week"
        ]
    ).round(3)

    profile[
        "peak_traffic_score"
    ] = minmax_0_100(
        profile[
            "observed_peak_trains_per_hour"
        ]
    ).round(3)

    profile[
        "combined_section_traffic_score"
    ] = (
        COMBINED_WEIGHT_SCHEDULED
        * profile[
            "scheduled_traffic_score"
        ]
        + COMBINED_WEIGHT_GOODS
        * profile[
            "goods_traffic_score"
        ]
        + COMBINED_WEIGHT_PEAK
        * profile[
            "peak_traffic_score"
        ]
    ).round(3)

    train_class_column = movement_schema[
        "train_class"
    ]

    if train_class_column is None:
        timetable_class_basis = (
            "SCHEDULED_TIMETABLE_TRAFFIC; TRAIN_CLASS_NOT_PRESENT"
        )
    else:
        timetable_class_basis = (
            f"SOURCE_TRAIN_CLASS_COLUMN:{train_class_column}"
        )

    profile[
        "timetable_traffic_basis"
    ] = timetable_class_basis

    profile[
        "movement_clock_basis"
    ] = clock_basis

    profile[
        "data_origin"
    ] = DATA_ORIGIN

    profile[
        "integration_mode"
    ] = INTEGRATION_MODE

    profile[
        "is_prototype_derived"
    ] = True

    return (
        profile,
        timetable_class_basis,
    )


# ---------------------------------------------------------------------------
# Task exposure
# ---------------------------------------------------------------------------

def delay_risk_band(
    operational_score: float,
) -> str:
    if operational_score >= 75:
        return "VERY_HIGH"
    if operational_score >= 55:
        return "HIGH"
    if operational_score >= 35:
        return "MEDIUM"
    if operational_score >= 15:
        return "LOW"
    return "VERY_LOW"


def build_task_exposure(
    timing: pd.DataFrame,
    block_requirements: pd.DataFrame,
    profiles: pd.DataFrame,
) -> pd.DataFrame:

    task_table = (
        timing[
            [
                "task_id",
                "section_id",
                "task_type",
                "primary_block_requirement",
                "total_block_expected_minutes",
                "total_block_max_minutes",
                "minimum_continuous_possession_minutes",
            ]
        ]
        .merge(
            block_requirements[
                [
                    "task_id",
                    "requires_traffic_block",
                    "requires_power_block",
                    "requires_disconnection",
                    "eligible_for_integrated_block",
                    "eligible_for_shadow_block",
                    "emergency_block",
                ]
            ],
            on="task_id",
            how="left",
            validate="one_to_one",
        )
    )

    result = task_table.merge(
        profiles[
            [
                "section_id",
                "scheduled_trains_week",
                "goods_forecast_events_week",
                "scheduled_trains_per_hour_average",
                "goods_events_per_hour_average",
                "observed_peak_trains_per_hour",
                "scheduled_traffic_score",
                "goods_traffic_score",
                "peak_traffic_score",
                "combined_section_traffic_score",
            ]
        ],
        on="section_id",
        how="left",
    )

    traffic_columns = [
        "scheduled_trains_week",
        "goods_forecast_events_week",
        "scheduled_trains_per_hour_average",
        "goods_events_per_hour_average",
        "observed_peak_trains_per_hour",
        "scheduled_traffic_score",
        "goods_traffic_score",
        "peak_traffic_score",
        "combined_section_traffic_score",
    ]

    for column in traffic_columns:
        result[
            column
        ] = (
            pd.to_numeric(
                result[
                    column
                ],
                errors="coerce",
            )
            .fillna(0)
        )

    result[
        "expected_block_hours"
    ] = (
        pd.to_numeric(
            result[
                "total_block_expected_minutes"
            ],
            errors="coerce",
        )
        .fillna(0)
        / 60.0
    )

    result[
        "estimated_scheduled_train_exposure"
    ] = (
        result[
            "scheduled_trains_per_hour_average"
        ]
        * result[
            "expected_block_hours"
        ]
    ).round(3)

    result[
        "estimated_goods_train_exposure"
    ] = (
        result[
            "goods_events_per_hour_average"
        ]
        * result[
            "expected_block_hours"
        ]
    ).round(3)

    # Duration increases exposure, but the score remains bounded and transparent.
    duration_factor = (
        pd.to_numeric(
            result[
                "total_block_expected_minutes"
            ],
            errors="coerce",
        )
        .fillna(0)
        / 180.0
    ).clip(
        lower=0.25,
        upper=2.0,
    )

    result[
        "scheduled_train_impact_score"
    ] = (
        result[
            "scheduled_traffic_score"
        ]
        * duration_factor
    ).clip(
        0,
        100,
    ).round(3)

    result[
        "freight_impact_score"
    ] = (
        result[
            "goods_traffic_score"
        ]
        * duration_factor
    ).clip(
        0,
        100,
    ).round(3)

    result[
        "peak_capacity_impact_score"
    ] = (
        result[
            "peak_traffic_score"
        ]
        * duration_factor
    ).clip(
        0,
        100,
    ).round(3)

    result[
        "prewindow_operational_impact_score"
    ] = (
        COMBINED_WEIGHT_SCHEDULED
        * result[
            "scheduled_train_impact_score"
        ]
        + COMBINED_WEIGHT_GOODS
        * result[
            "freight_impact_score"
        ]
        + COMBINED_WEIGHT_PEAK
        * result[
            "peak_capacity_impact_score"
        ]
    ).clip(
        0,
        100,
    ).round(3)

    result[
        "operational_delay_risk_band"
    ] = result[
        "prewindow_operational_impact_score"
    ].map(
        delay_risk_band
    )

    result[
        "exact_affected_trains_status"
    ] = (
        "PENDING_CANDIDATE_WINDOW_SELECTION"
    )

    result[
        "exact_delay_minutes_status"
    ] = (
        "PENDING_CANDIDATE_WINDOW_SELECTION"
    )

    result[
        "impact_model_scope"
    ] = (
        "PRE_WINDOW_EXPOSURE_NOT_FINAL_DELAY_PREDICTION"
    )

    result[
        "data_origin"
    ] = DATA_ORIGIN

    result[
        "integration_mode"
    ] = INTEGRATION_MODE

    result[
        "is_prototype_derived"
    ] = True

    return result


# ---------------------------------------------------------------------------
# Validation / report
# ---------------------------------------------------------------------------

def validate_outputs(
    timing: pd.DataFrame,
    profiles: pd.DataFrame,
    exposure: pd.DataFrame,
) -> dict[str, int]:

    score_columns = [
        "scheduled_train_impact_score",
        "freight_impact_score",
        "peak_capacity_impact_score",
        "prewindow_operational_impact_score",
    ]

    out_of_range = 0

    for column in score_columns:
        numeric = pd.to_numeric(
            exposure[
                column
            ],
            errors="coerce",
        )

        out_of_range += int(
            (
                numeric.isna()
                | (
                    numeric < 0
                )
                | (
                    numeric > 100
                )
            ).sum()
        )

    checks = {
        "tasks":
            len(
                timing
            ),

        "section_profiles":
            len(
                profiles
            ),

        "task_exposure_rows":
            len(
                exposure
            ),

        "duplicate_section_profiles":
            int(
                profiles[
                    "section_id"
                ].duplicated().sum()
            ),

        "duplicate_task_exposure":
            int(
                exposure[
                    "task_id"
                ].duplicated().sum()
            ),

        "tasks_missing_exposure":
            int(
                (
                    ~timing[
                        "task_id"
                    ].astype(str).isin(
                        exposure[
                            "task_id"
                        ].astype(str)
                    )
                ).sum()
            ),

        "tasks_without_section_traffic":
            int(
                (
                    exposure[
                        "scheduled_trains_week"
                    ]
                    .eq(0)
                ).sum()
            ),

        "score_values_out_of_range":
            out_of_range,
    }

    hard_failures = [
        "duplicate_section_profiles",
        "duplicate_task_exposure",
        "tasks_missing_exposure",
        "score_values_out_of_range",
    ]

    if len(
        exposure
    ) != len(
        timing
    ):
        raise RuntimeError(
            "V3.9 must produce exactly one operational exposure row per task."
        )

    if sum(
        checks[key]
        for key in hard_failures
    ):
        raise RuntimeError(
            "V3.9 operational impact integrity validation failed."
        )

    return checks


def write_report(
    movement_file: Path,
    goods_file: Path | None,
    goods_status: str,
    timetable_basis: str,
    profiles: pd.DataFrame,
    exposure: pd.DataFrame,
    checks: dict[str, int],
) -> None:

    risk_counts = (
        exposure[
            "operational_delay_risk_band"
        ]
        .value_counts()
        .reindex(
            [
                "VERY_HIGH",
                "HIGH",
                "MEDIUM",
                "LOW",
                "VERY_LOW",
            ],
            fill_value=0,
        )
    )

    lines = [
        "=" * 72,
        "TrackEase V3.9 Passenger / Freight Operational Impact Report",
        "=" * 72,
        "",
        "SOURCES",
        "-" * 72,
        f"Weekly movement file        : {movement_file}",
        (
            f"COA/goods file              : {goods_file}"
            if goods_file is not None
            else
            "COA/goods file              : NOT FOUND"
        ),
        f"Goods integration status    : {goods_status}",
        f"Timetable traffic basis     : {timetable_basis}",
        "",
        "SUMMARY",
        "-" * 72,
        f"Section traffic profiles    : {len(profiles):,}",
        f"Maintenance tasks evaluated : {len(exposure):,}",
        (
            "Average scheduled exposure  : "
            f"{exposure['estimated_scheduled_train_exposure'].mean():.3f}"
        ),
        (
            "Average goods exposure      : "
            f"{exposure['estimated_goods_train_exposure'].mean():.3f}"
        ),
        (
            "Average operational score   : "
            f"{exposure['prewindow_operational_impact_score'].mean():.2f}"
        ),
        (
            "Maximum operational score   : "
            f"{exposure['prewindow_operational_impact_score'].max():.2f}"
        ),
        "",
        "OPERATIONAL DELAY-RISK BANDS",
        "-" * 72,
    ]

    for band, count in risk_counts.items():
        lines.append(
            f"{band:<20} {int(count):>10,}"
        )

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                "Duplicate section profiles : "
                f"{checks['duplicate_section_profiles']:,}"
            ),
            (
                "Duplicate task exposure    : "
                f"{checks['duplicate_task_exposure']:,}"
            ),
            (
                "Tasks missing exposure     : "
                f"{checks['tasks_missing_exposure']:,}"
            ),
            (
                "Tasks without traffic data : "
                f"{checks['tasks_without_section_traffic']:,}"
            ),
            (
                "Score values out of range  : "
                f"{checks['score_values_out_of_range']:,}"
            ),
            "",
            "IMPORTANT INTERPRETATION",
            "-" * 72,
            (
                "This stage measures PRE-WINDOW operational exposure. It does "
                "not claim that a specific train is affected until an exact "
                "candidate block window is selected."
            ),
            (
                "The scheduled timetable traffic and COA-style goods forecast "
                "remain separate so TrackEase does not silently invent freight "
                "or passenger classifications."
            ),
            (
                "Exact affected train numbers, exact train/block overlaps and "
                "window-specific delay estimates are deferred to the candidate-"
                "window/opportunity stage."
            ),
            (
                "Safety constraints remain hard constraints regardless of the "
                "operational impact score."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build the opportunity/shadow-block detector and exact candidate "
                "windows. At that stage TrackEase will enumerate the actual "
                "scheduled trains and goods events overlapping each candidate "
                "window and calculate window-specific impact."
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
        "TrackEase V3.9 - Passenger / Freight Operational Impact Model"
    )
    print("=" * 72)

    require_inputs()

    movement_file = (
        discover_weekly_movements_file()
    )

    goods_file = (
        discover_goods_file()
    )

    print(
        "\nDiscovered operational sources:"
    )
    print(
        f"Weekly movements : {movement_file}"
    )
    print(
        f"COA/goods        : "
        f"{goods_file if goods_file is not None else 'NOT FOUND'}"
    )

    print(
        "\nLoading task timing and block requirements..."
    )

    timing = pd.read_csv(
        TIMING_FILE,
        low_memory=False,
    )

    block_requirements = pd.read_csv(
        BLOCK_REQUIREMENTS_FILE,
        low_memory=False,
    )

    movements = pd.read_csv(
        movement_file,
        low_memory=False,
    )

    goods = (
        pd.read_csv(
            goods_file,
            low_memory=False,
        )
        if goods_file is not None
        else None
    )

    print(
        f"Task timing rows : {len(timing):,}"
    )
    print(
        f"Movement rows    : {len(movements):,}"
    )
    print(
        f"Goods rows       : {len(goods):,}"
        if goods is not None
        else
        "Goods rows       : 0"
    )

    print(
        "\nBuilding section traffic profiles..."
    )

    movement_schema = (
        detect_movement_schema(
            movements
        )
    )

    goods_counts, goods_status = (
        build_goods_counts(
            goods
        )
    )

    (
        profiles,
        timetable_basis,
    ) = build_section_profiles(
        movements,
        movement_schema,
        goods_counts,
    )

    print(
        "Building task-level passenger/freight exposure metrics..."
    )

    exposure = (
        build_task_exposure(
            timing,
            block_requirements,
            profiles,
        )
    )

    checks = validate_outputs(
        timing,
        profiles,
        exposure,
    )

    profiles.to_csv(
        SECTION_PROFILE_OUTPUT,
        index=False,
    )

    exposure.to_csv(
        TASK_EXPOSURE_OUTPUT,
        index=False,
    )

    write_report(
        movement_file,
        goods_file,
        goods_status,
        timetable_basis,
        profiles,
        exposure,
        checks,
    )

    print(
        "\n"
        + "=" * 72
    )

    print(
        "V3.9 OPERATIONAL IMPACT MODEL COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        f"\nSection traffic profiles     : "
        f"{len(profiles):,}"
    )

    print(
        f"Tasks evaluated              : "
        f"{len(exposure):,}"
    )

    print(
        f"Average scheduled exposure   : "
        f"{exposure['estimated_scheduled_train_exposure'].mean():.3f}"
    )

    print(
        f"Average goods exposure       : "
        f"{exposure['estimated_goods_train_exposure'].mean():.3f}"
    )

    print(
        f"Average operational score    : "
        f"{exposure['prewindow_operational_impact_score'].mean():.2f}"
    )

    print(
        "\nIntegrity:"
    )

    print(
        f"  Duplicate section profiles : "
        f"{checks['duplicate_section_profiles']:,}"
    )

    print(
        f"  Duplicate task exposure    : "
        f"{checks['duplicate_task_exposure']:,}"
    )

    print(
        f"  Missing task exposure      : "
        f"{checks['tasks_missing_exposure']:,}"
    )

    print(
        f"  Tasks without traffic data : "
        f"{checks['tasks_without_section_traffic']:,}"
    )

    print(
        f"  Out-of-range score values  : "
        f"{checks['score_values_out_of_range']:,}"
    )

    print(
        "\nOutputs:"
    )

    print(
        f"  {SECTION_PROFILE_OUTPUT}"
    )

    print(
        f"  {TASK_EXPOSURE_OUTPUT}"
    )

    print(
        f"  {REPORT_OUTPUT}"
    )

    print(
        "\nTrackEase V3 now has separate timetable and freight exposure "
        "signals ready for exact candidate-window impact analysis."
    )


if __name__ == "__main__":
    main()
