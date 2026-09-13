"""
TrackEase V3.8 - Asset Risk & Asset Availability Scoring

Purpose
-------
Create an explainable, deterministic maintenance-value layer before train-impact
and final block optimization.

This module intentionally does NOT use the weak TrackEase ML V2 model.
It combines canonical asset/task information into:
    1. asset risk score
    2. expected maintenance risk-reduction score
    3. asset-availability gain score
    4. explainable intrinsic maintenance-value score

Later Optimizer V3 will combine these maintenance-value signals with:
    - passenger/train impact
    - freight impact
    - resource feasibility/cost
    - coordination benefit
    - robustness
    - safety hard constraints

Inputs
------
    data/processed/v3_assets.csv
    data/processed/v3_maintenance_requests.csv
    data/processed/v3_maintenance_tasks.csv
    data/processed/v3_task_timing_components.csv
    data/processed/v3_task_resource_feasibility.csv

Outputs
-------
    data/processed/v3_asset_risk_availability_scores.csv
    data/processed/v3_task_maintenance_value_scores.csv
    data/processed/v3_risk_availability_report.txt

Notes
-----
- Existing V2/V3 files are read-only.
- No random values are generated.
- Missing source features are handled transparently with documented deterministic
  fallbacks from canonical task/request information.
- Scores are prototype decision-support scores, not official Indian Railways
  safety/risk ratings.
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

ASSETS_FILE = PROCESSED_DIR / "v3_assets.csv"
REQUESTS_FILE = PROCESSED_DIR / "v3_maintenance_requests.csv"
TASKS_FILE = PROCESSED_DIR / "v3_maintenance_tasks.csv"
TIMING_FILE = PROCESSED_DIR / "v3_task_timing_components.csv"
RESOURCE_FEASIBILITY_FILE = (
    PROCESSED_DIR / "v3_task_resource_feasibility.csv"
)

ASSET_OUTPUT = (
    PROCESSED_DIR / "v3_asset_risk_availability_scores.csv"
)
TASK_OUTPUT = (
    PROCESSED_DIR / "v3_task_maintenance_value_scores.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_risk_availability_report.txt"
)


# ---------------------------------------------------------------------------
# Provenance / policy
# ---------------------------------------------------------------------------

DATA_ORIGIN = "TRACKEASE_V3_EXPLAINABLE_RISK_SCORING"
INTEGRATION_MODE = "PROTOTYPE_RULE_BASED_RISK_AVAILABILITY_ENGINE"
SCORING_METHOD = "EXPLAINABLE_RULE_BASED_V3"
ML_MODEL_USED = False

# Intrinsic maintenance-value weights. These sum to 100.
WEIGHTS = {
    "asset_criticality": 20.0,
    "condition_failure_risk": 20.0,
    "urgency": 15.0,
    "safety_consequence": 15.0,
    "overdue_postponement": 10.0,
    "availability_gain": 15.0,
    "duration_efficiency": 5.0,
}

# Prototype risk-reduction assumptions by maintenance intent.
TASK_RISK_REDUCTION = {
    "INSPECTION": 0.10,
    "PREVENTIVE": 0.35,
    "URGENT_PLANNED": 0.45,
    "CORRECTIVE": 0.60,
    "EMERGENCY": 0.70,
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def require_inputs() -> None:
    required = [
        ASSETS_FILE,
        REQUESTS_FILE,
        TASKS_FILE,
        TIMING_FILE,
        RESOURCE_FEASIBILITY_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.8 inputs are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


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


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def minmax_0_100(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    valid = numeric.dropna()

    if valid.empty:
        return pd.Series(
            [50.0] * len(series),
            index=series.index,
            dtype=float,
        )

    low = float(valid.min())
    high = float(valid.max())

    if math.isclose(low, high):
        result = pd.Series(
            [50.0] * len(series),
            index=series.index,
            dtype=float,
        )
        result[numeric.isna()] = 50.0
        return result

    result = (
        (numeric - low)
        / (high - low)
        * 100.0
    )

    return result.fillna(50.0).clip(0, 100)


def categorical_score(
    value: object,
    mapping: dict[str, float],
    default: float = 50.0,
) -> float:
    text = clean_text(value).upper()

    if not text:
        return default

    for key, score in mapping.items():
        if key in text:
            return score

    return default


def normalize_probability(value: object) -> float | None:
    number = safe_float(value)

    if number is None:
        return None

    # Accept either 0..1 probability or 0..100 percentage-like values.
    if 0.0 <= number <= 1.0:
        return number * 100.0

    if 0.0 <= number <= 100.0:
        return number

    return None


def risk_band(score: float) -> str:
    if score >= 75:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MEDIUM"
    return "LOW"


def confidence_band(source_signal_count: int) -> str:
    if source_signal_count >= 4:
        return "HIGH"
    if source_signal_count >= 2:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Source signal extraction
# ---------------------------------------------------------------------------

def detect_asset_columns(assets: pd.DataFrame) -> dict[str, str | None]:
    columns = assets.columns.tolist()

    return {
        "criticality":
            first_existing(
                columns,
                [
                    "criticality_score",
                    "asset_criticality_score",
                    "criticality",
                    "asset_criticality",
                    "criticality_level",
                ],
            ),

        "failure_probability":
            first_existing(
                columns,
                [
                    "failure_probability",
                    "failure_prob",
                    "predicted_failure_probability",
                    "failure_risk",
                    "risk_probability",
                ],
            ),

        "condition":
            first_existing(
                columns,
                [
                    "condition_score",
                    "asset_condition_score",
                    "health_score",
                    "condition",
                    "asset_condition",
                    "health_status",
                ],
            ),

        "safety_consequence":
            first_existing(
                columns,
                [
                    "safety_consequence_score",
                    "safety_consequence",
                    "consequence_score",
                    "consequence",
                    "severity_score",
                    "severity",
                ],
            ),

        "last_maintenance":
            first_existing(
                columns,
                [
                    "last_maintenance_date",
                    "last_maintenance",
                    "last_service_date",
                ],
            ),

        "next_maintenance":
            first_existing(
                columns,
                [
                    "next_maintenance_date",
                    "next_maintenance",
                    "due_date",
                    "maintenance_due_date",
                ],
            ),
    }


def detect_request_columns(requests: pd.DataFrame) -> dict[str, str | None]:
    columns = requests.columns.tolist()

    return {
        "urgency":
            first_existing(
                columns,
                [
                    "urgency_score",
                    "urgency",
                    "priority",
                    "priority_level",
                    "request_priority",
                ],
            ),

        "overdue_days":
            first_existing(
                columns,
                [
                    "overdue_days",
                    "days_overdue",
                    "maintenance_overdue_days",
                ],
            ),

        "postponement_count":
            first_existing(
                columns,
                [
                    "postponement_count",
                    "times_postponed",
                    "defer_count",
                    "deferral_count",
                ],
            ),
    }


def criticality_score(
    asset_row: pd.Series,
    column: str | None,
    task_priority_score: float,
) -> tuple[float, bool, str]:
    if column is not None:
        raw = asset_row.get(column)

        numeric = safe_float(raw)

        if numeric is not None:
            if 0 <= numeric <= 1:
                numeric *= 100
            return clamp(numeric), True, f"ASSET_SOURCE:{column}"

        score = categorical_score(
            raw,
            {
                "CRITICAL": 95,
                "VERY HIGH": 90,
                "HIGH": 80,
                "MEDIUM": 55,
                "MODERATE": 55,
                "LOW": 25,
            },
        )

        return score, True, f"ASSET_SOURCE:{column}"

    # Fallback is transparent and uses existing TrackEase priority rather than
    # generating a random or hidden criticality value.
    return (
        clamp(task_priority_score),
        False,
        "FALLBACK_FROM_EXISTING_TRACKEASE_PRIORITY",
    )


def condition_failure_score(
    asset_row: pd.Series,
    columns: dict[str, str | None],
    task_priority_score: float,
) -> tuple[float, int, str]:
    signals = []
    reasons = []

    failure_column = columns["failure_probability"]

    if failure_column is not None:
        probability = normalize_probability(
            asset_row.get(failure_column)
        )

        if probability is not None:
            signals.append(probability)
            reasons.append(
                f"FAILURE_SOURCE:{failure_column}"
            )

    condition_column = columns["condition"]

    if condition_column is not None:
        raw = asset_row.get(condition_column)
        numeric = safe_float(raw)

        if numeric is not None:
            if 0 <= numeric <= 1:
                numeric *= 100

            column_name = condition_column.lower()

            # Health/condition scores usually mean high = healthy, therefore
            # convert them into risk. Severity-like condition labels are handled
            # below.
            if (
                "health" in column_name
                or "condition_score" in column_name
            ):
                signals.append(
                    clamp(100.0 - numeric)
                )
            else:
                signals.append(
                    clamp(numeric)
                )

            reasons.append(
                f"CONDITION_SOURCE:{condition_column}"
            )
        else:
            categorical = categorical_score(
                raw,
                {
                    "CRITICAL": 95,
                    "FAILED": 100,
                    "VERY POOR": 90,
                    "POOR": 80,
                    "DEGRADED": 70,
                    "FAIR": 50,
                    "GOOD": 25,
                    "HEALTHY": 15,
                    "EXCELLENT": 5,
                },
            )

            signals.append(
                categorical
            )

            reasons.append(
                f"CONDITION_SOURCE:{condition_column}"
            )

    if signals:
        return (
            float(sum(signals) / len(signals)),
            len(signals),
            "|".join(reasons),
        )

    return (
        clamp(task_priority_score),
        0,
        "FALLBACK_FROM_EXISTING_TRACKEASE_PRIORITY",
    )


def safety_score(
    asset_row: pd.Series,
    column: str | None,
    task_type: str,
) -> tuple[float, bool, str]:
    if column is not None:
        raw = asset_row.get(column)
        numeric = safe_float(raw)

        if numeric is not None:
            if 0 <= numeric <= 1:
                numeric *= 100

            return (
                clamp(numeric),
                True,
                f"ASSET_SOURCE:{column}",
            )

        return (
            categorical_score(
                raw,
                {
                    "CATASTROPHIC": 100,
                    "CRITICAL": 95,
                    "VERY HIGH": 90,
                    "HIGH": 80,
                    "MAJOR": 75,
                    "MEDIUM": 55,
                    "MODERATE": 55,
                    "LOW": 25,
                    "MINOR": 20,
                },
            ),
            True,
            f"ASSET_SOURCE:{column}",
        )

    fallback = {
        "EMERGENCY": 95.0,
        "CORRECTIVE": 75.0,
        "URGENT_PLANNED": 70.0,
        "PREVENTIVE": 45.0,
        "INSPECTION": 35.0,
    }.get(
        task_type,
        50.0,
    )

    return (
        fallback,
        False,
        "FALLBACK_FROM_TASK_TYPE",
    )


def urgency_score(
    request_row: pd.Series | None,
    request_columns: dict[str, str | None],
    task_priority_score: float,
    priority_level: str,
) -> tuple[float, bool, str]:
    column = request_columns["urgency"]

    if request_row is not None and column is not None:
        raw = request_row.get(column)
        numeric = safe_float(raw)

        if numeric is not None:
            if 0 <= numeric <= 1:
                numeric *= 100

            return (
                clamp(numeric),
                True,
                f"REQUEST_SOURCE:{column}",
            )

        return (
            categorical_score(
                raw,
                {
                    "CRITICAL": 95,
                    "EMERGENCY": 100,
                    "URGENT": 90,
                    "HIGH": 80,
                    "MEDIUM": 55,
                    "NORMAL": 45,
                    "LOW": 25,
                },
            ),
            True,
            f"REQUEST_SOURCE:{column}",
        )

    if priority_level:
        score = categorical_score(
            priority_level,
            {
                "CRITICAL": 95,
                "HIGH": 80,
                "MEDIUM": 55,
                "LOW": 25,
            },
            default=task_priority_score,
        )

        return (
            score,
            False,
            "FALLBACK_FROM_TASK_PRIORITY_LEVEL",
        )

    return (
        clamp(task_priority_score),
        False,
        "FALLBACK_FROM_EXISTING_TRACKEASE_PRIORITY",
    )


def overdue_postponement_score(
    request_row: pd.Series | None,
    request_columns: dict[str, str | None],
    urgency: float,
) -> tuple[float, int, str]:
    components = []
    reasons = []

    if request_row is not None:
        overdue_column = request_columns["overdue_days"]

        if overdue_column is not None:
            overdue = safe_float(
                request_row.get(overdue_column)
            )

            if overdue is not None:
                # 90+ days overdue saturates this component.
                components.append(
                    clamp(
                        overdue / 90.0 * 100.0
                    )
                )
                reasons.append(
                    f"REQUEST_SOURCE:{overdue_column}"
                )

        postponement_column = request_columns[
            "postponement_count"
        ]

        if postponement_column is not None:
            count = safe_float(
                request_row.get(
                    postponement_column
                )
            )

            if count is not None:
                # Five repeated deferrals saturate postponement debt.
                components.append(
                    clamp(
                        count / 5.0 * 100.0
                    )
                )
                reasons.append(
                    f"REQUEST_SOURCE:{postponement_column}"
                )

    if components:
        return (
            float(
                sum(components)
                / len(components)
            ),
            len(components),
            "|".join(reasons),
        )

    # No fabricated overdue days. Use urgency only as a documented fallback.
    return (
        clamp(
            urgency * 0.60
        ),
        0,
        "FALLBACK_FROM_URGENCY_NO_OVERDUE_HISTORY",
    )


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def build_scores(
    assets: pd.DataFrame,
    requests: pd.DataFrame,
    tasks: pd.DataFrame,
    timing: pd.DataFrame,
    feasibility: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    if "asset_id" not in assets.columns:
        raise ValueError(
            "v3_assets.csv must contain asset_id."
        )

    if "task_id" not in tasks.columns:
        raise ValueError(
            "v3_maintenance_tasks.csv must contain task_id."
        )

    asset_columns = detect_asset_columns(
        assets
    )

    request_columns = detect_request_columns(
        requests
    )

    asset_lookup = (
        assets
        .drop_duplicates(
            subset=["asset_id"]
        )
        .set_index(
            "asset_id",
            drop=False,
        )
    )

    request_lookup = (
        requests
        .drop_duplicates(
            subset=["request_id"]
        )
        .set_index(
            "request_id",
            drop=False,
        )
        if "request_id" in requests.columns
        else pd.DataFrame()
    )

    timing_lookup = (
        timing
        .drop_duplicates(
            subset=["task_id"]
        )
        .set_index(
            "task_id",
            drop=False,
        )
    )

    feasibility_lookup = (
        feasibility
        .drop_duplicates(
            subset=["task_id"]
        )
        .set_index(
            "task_id",
            drop=False,
        )
    )

    duration_series = (
        pd.to_numeric(
            timing[
                "total_block_expected_minutes"
            ],
            errors="coerce",
        )
        if "total_block_expected_minutes" in timing.columns
        else pd.Series(
            [60.0] * len(timing)
        )
    )

    duration_efficiency_lookup = {}

    if "task_id" in timing.columns:
        efficiency = (
            100.0
            - minmax_0_100(
                duration_series
            )
        )

        duration_efficiency_lookup = dict(
            zip(
                timing["task_id"].astype(str),
                efficiency.astype(float),
            )
        )

    task_rows = []

    for task in tasks.itertuples(
        index=False
    ):
        task_dict = task._asdict()

        task_id = clean_text(
            task_dict.get("task_id")
        )

        asset_id = clean_text(
            task_dict.get("asset_id")
        )

        request_id = clean_text(
            task_dict.get("request_id")
        )

        task_type = clean_text(
            task_dict.get("task_type")
        ).upper()

        priority_level = clean_text(
            task_dict.get("priority_level")
        ).upper()

        existing_priority = safe_float(
            task_dict.get(
                "trackease_priority_score"
            )
        )

        if existing_priority is None:
            existing_priority = 50.0

        if asset_id in asset_lookup.index:
            asset_row = asset_lookup.loc[
                asset_id
            ]
        else:
            asset_row = pd.Series(
                dtype=object
            )

        request_row = None

        if (
            not request_lookup.empty
            and request_id in request_lookup.index
        ):
            request_row = request_lookup.loc[
                request_id
            ]

        (
            criticality,
            criticality_real,
            criticality_basis,
        ) = criticality_score(
            asset_row,
            asset_columns["criticality"],
            existing_priority,
        )

        (
            condition_failure,
            condition_signal_count,
            condition_basis,
        ) = condition_failure_score(
            asset_row,
            asset_columns,
            existing_priority,
        )

        (
            safety,
            safety_real,
            safety_basis,
        ) = safety_score(
            asset_row,
            asset_columns["safety_consequence"],
            task_type,
        )

        (
            urgency,
            urgency_real,
            urgency_basis,
        ) = urgency_score(
            request_row,
            request_columns,
            existing_priority,
            priority_level,
        )

        (
            overdue_postponement,
            overdue_signal_count,
            overdue_basis,
        ) = overdue_postponement_score(
            request_row,
            request_columns,
            urgency,
        )

        asset_risk = (
            0.30 * criticality
            + 0.35 * condition_failure
            + 0.20 * safety
            + 0.15 * urgency
        )

        asset_risk = clamp(
            asset_risk
        )

        reduction_fraction = TASK_RISK_REDUCTION.get(
            task_type,
            0.30,
        )

        expected_risk_reduction = (
            asset_risk
            * reduction_fraction
        )

        post_maintenance_risk = clamp(
            asset_risk
            - expected_risk_reduction
        )

        # Direct asset-availability objective proxy:
        # risk reduction is rewarded; long expected block duration slightly
        # reduces efficiency. This is a score, not an uptime percentage.
        duration_efficiency = float(
            duration_efficiency_lookup.get(
                task_id,
                50.0,
            )
        )

        availability_gain = clamp(
            0.80 * (
                expected_risk_reduction
                / 70.0
                * 100.0
            )
            + 0.20 * duration_efficiency
        )

        maintenance_value = (
            WEIGHTS["asset_criticality"]
            * criticality
            / 100.0
            + WEIGHTS["condition_failure_risk"]
            * condition_failure
            / 100.0
            + WEIGHTS["urgency"]
            * urgency
            / 100.0
            + WEIGHTS["safety_consequence"]
            * safety
            / 100.0
            + WEIGHTS["overdue_postponement"]
            * overdue_postponement
            / 100.0
            + WEIGHTS["availability_gain"]
            * availability_gain
            / 100.0
            + WEIGHTS["duration_efficiency"]
            * duration_efficiency
            / 100.0
        )

        maintenance_value = clamp(
            maintenance_value
        )

        source_signal_count = (
            int(criticality_real)
            + condition_signal_count
            + int(safety_real)
            + int(urgency_real)
            + overdue_signal_count
        )

        resource_status = ""

        if task_id in feasibility_lookup.index:
            resource_status = clean_text(
                feasibility_lookup.loc[
                    task_id
                ].get(
                    "resource_feasibility_status"
                )
            )

        timing_row = (
            timing_lookup.loc[
                task_id
            ]
            if task_id in timing_lookup.index
            else pd.Series(
                dtype=object
            )
        )

        expected_block_minutes = safe_float(
            timing_row.get(
                "total_block_expected_minutes"
            )
        )

        if expected_block_minutes is None:
            expected_block_minutes = safe_float(
                task_dict.get(
                    "expected_duration_min"
                )
            ) or 0.0

        task_rows.append(
            {
                "task_id":
                    task_id,

                "request_id":
                    request_id,

                "asset_id":
                    asset_id,

                "section_id":
                    clean_text(
                        task_dict.get(
                            "section_id"
                        )
                    ),

                "task_type":
                    task_type,

                "priority_level_source":
                    priority_level,

                "existing_trackease_priority_score":
                    round(
                        existing_priority,
                        3,
                    ),

                "asset_criticality_score":
                    round(
                        criticality,
                        3,
                    ),

                "condition_failure_risk_score":
                    round(
                        condition_failure,
                        3,
                    ),

                "urgency_score":
                    round(
                        urgency,
                        3,
                    ),

                "safety_consequence_score":
                    round(
                        safety,
                        3,
                    ),

                "overdue_postponement_score":
                    round(
                        overdue_postponement,
                        3,
                    ),

                "asset_risk_score":
                    round(
                        asset_risk,
                        3,
                    ),

                "asset_risk_band":
                    risk_band(
                        asset_risk
                    ),

                "expected_risk_reduction_fraction":
                    round(
                        reduction_fraction,
                        3,
                    ),

                "expected_risk_reduction_score":
                    round(
                        expected_risk_reduction,
                        3,
                    ),

                "estimated_post_maintenance_risk_score":
                    round(
                        post_maintenance_risk,
                        3,
                    ),

                "duration_efficiency_score":
                    round(
                        duration_efficiency,
                        3,
                    ),

                "asset_availability_gain_score":
                    round(
                        availability_gain,
                        3,
                    ),

                "intrinsic_maintenance_value_score":
                    round(
                        maintenance_value,
                        3,
                    ),

                "maintenance_value_band":
                    risk_band(
                        maintenance_value
                    ),

                "expected_block_minutes":
                    round(
                        expected_block_minutes,
                        3,
                    ),

                "resource_feasibility_status":
                    resource_status,

                "source_signal_count":
                    source_signal_count,

                "score_confidence":
                    confidence_band(
                        source_signal_count
                    ),

                "criticality_basis":
                    criticality_basis,

                "condition_failure_basis":
                    condition_basis,

                "urgency_basis":
                    urgency_basis,

                "safety_basis":
                    safety_basis,

                "overdue_postponement_basis":
                    overdue_basis,

                "scoring_method":
                    SCORING_METHOD,

                "ml_model_used":
                    ML_MODEL_USED,

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,

                "is_prototype_derived":
                    True,
            }
        )

    task_scores = pd.DataFrame(
        task_rows
    )

    # One asset may have more than one maintenance task. Asset-level output
    # retains the highest current risk / maintenance value plus task counts.
    asset_scores = (
        task_scores.groupby(
            "asset_id",
            dropna=False,
        )
        .agg(
            linked_task_count=(
                "task_id",
                "size",
            ),
            asset_risk_score=(
                "asset_risk_score",
                "max",
            ),
            expected_risk_reduction_score=(
                "expected_risk_reduction_score",
                "max",
            ),
            estimated_post_maintenance_risk_score=(
                "estimated_post_maintenance_risk_score",
                "min",
            ),
            asset_availability_gain_score=(
                "asset_availability_gain_score",
                "max",
            ),
            max_intrinsic_maintenance_value_score=(
                "intrinsic_maintenance_value_score",
                "max",
            ),
            score_confidence=(
                "score_confidence",
                lambda values: (
                    "HIGH"
                    if "HIGH" in set(values)
                    else (
                        "MEDIUM"
                        if "MEDIUM" in set(values)
                        else "LOW"
                    )
                ),
            ),
        )
        .reset_index()
    )

    asset_scores[
        "asset_risk_band"
    ] = asset_scores[
        "asset_risk_score"
    ].map(
        risk_band
    )

    asset_scores[
        "scoring_method"
    ] = SCORING_METHOD

    asset_scores[
        "ml_model_used"
    ] = ML_MODEL_USED

    asset_scores[
        "data_origin"
    ] = DATA_ORIGIN

    asset_scores[
        "integration_mode"
    ] = INTEGRATION_MODE

    asset_scores[
        "is_prototype_derived"
    ] = True

    return (
        asset_scores,
        task_scores,
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_outputs(
    assets: pd.DataFrame,
    tasks: pd.DataFrame,
    asset_scores: pd.DataFrame,
    task_scores: pd.DataFrame,
) -> dict[str, int]:

    numeric_score_columns = [
        "asset_criticality_score",
        "condition_failure_risk_score",
        "urgency_score",
        "safety_consequence_score",
        "overdue_postponement_score",
        "asset_risk_score",
        "duration_efficiency_score",
        "asset_availability_gain_score",
        "intrinsic_maintenance_value_score",
    ]

    out_of_range = 0

    for column in numeric_score_columns:
        if column not in task_scores.columns:
            continue

        numeric = pd.to_numeric(
            task_scores[column],
            errors="coerce",
        )

        out_of_range += int(
            (
                (numeric < 0)
                | (numeric > 100)
                | numeric.isna()
            ).sum()
        )

    checks = {
        "canonical_assets":
            len(
                assets
            ),

        "canonical_tasks":
            len(
                tasks
            ),

        "scored_assets":
            len(
                asset_scores
            ),

        "scored_tasks":
            len(
                task_scores
            ),

        "duplicate_asset_scores":
            int(
                asset_scores[
                    "asset_id"
                ].duplicated().sum()
            ),

        "duplicate_task_scores":
            int(
                task_scores[
                    "task_id"
                ].duplicated().sum()
            ),

        "tasks_missing_scores":
            int(
                (
                    ~tasks[
                        "task_id"
                    ].astype(str).isin(
                        task_scores[
                            "task_id"
                        ].astype(str)
                    )
                ).sum()
            ),

        "score_values_out_of_range":
            out_of_range,

        "ml_used_rows":
            int(
                task_scores[
                    "ml_model_used"
                ].astype(bool).sum()
            ),

        "low_confidence_tasks":
            int(
                task_scores[
                    "score_confidence"
                ].eq(
                    "LOW"
                ).sum()
            ),
    }

    hard_failures = [
        "duplicate_asset_scores",
        "duplicate_task_scores",
        "tasks_missing_scores",
        "score_values_out_of_range",
        "ml_used_rows",
    ]

    if len(task_scores) != len(tasks):
        raise RuntimeError(
            "V3.8 must produce exactly one task score per canonical task."
        )

    if sum(
        checks[key]
        for key in hard_failures
    ):
        raise RuntimeError(
            "V3.8 risk/availability scoring integrity validation failed."
        )

    return checks


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(
    task_scores: pd.DataFrame,
    asset_scores: pd.DataFrame,
    checks: dict[str, int],
) -> None:

    risk_counts = (
        task_scores[
            "asset_risk_band"
        ]
        .value_counts()
        .reindex(
            [
                "CRITICAL",
                "HIGH",
                "MEDIUM",
                "LOW",
            ],
            fill_value=0,
        )
    )

    value_counts = (
        task_scores[
            "maintenance_value_band"
        ]
        .value_counts()
        .reindex(
            [
                "CRITICAL",
                "HIGH",
                "MEDIUM",
                "LOW",
            ],
            fill_value=0,
        )
    )

    confidence_counts = (
        task_scores[
            "score_confidence"
        ]
        .value_counts()
        .reindex(
            [
                "HIGH",
                "MEDIUM",
                "LOW",
            ],
            fill_value=0,
        )
    )

    lines = [
        "=" * 72,
        "TrackEase V3.8 Asset Risk & Availability Report",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Canonical assets                  : {checks['canonical_assets']:,}",
        f"Scored assets                     : {checks['scored_assets']:,}",
        f"Canonical tasks                   : {checks['canonical_tasks']:,}",
        f"Scored tasks                      : {checks['scored_tasks']:,}",
        f"Average asset-risk score          : {task_scores['asset_risk_score'].mean():.2f}",
        f"Average availability-gain score   : {task_scores['asset_availability_gain_score'].mean():.2f}",
        f"Average maintenance-value score   : {task_scores['intrinsic_maintenance_value_score'].mean():.2f}",
        f"Average expected risk reduction   : {task_scores['expected_risk_reduction_score'].mean():.2f}",
        "",
        "ASSET RISK BANDS",
        "-" * 72,
    ]

    for band, count in risk_counts.items():
        lines.append(
            f"{band:<20} {int(count):>10,}"
        )

    lines.extend(
        [
            "",
            "MAINTENANCE VALUE BANDS",
            "-" * 72,
        ]
    )

    for band, count in value_counts.items():
        lines.append(
            f"{band:<20} {int(count):>10,}"
        )

    lines.extend(
        [
            "",
            "SCORE CONFIDENCE",
            "-" * 72,
        ]
    )

    for band, count in confidence_counts.items():
        lines.append(
            f"{band:<20} {int(count):>10,}"
        )

    lines.extend(
        [
            "",
            "SCORING WEIGHTS",
            "-" * 72,
        ]
    )

    for name, weight in WEIGHTS.items():
        lines.append(
            f"{name:<32} {weight:>6.1f}"
        )

    lines.extend(
        [
            "",
            "INTEGRITY",
            "-" * 72,
            (
                "Duplicate asset scores           : "
                f"{checks['duplicate_asset_scores']:,}"
            ),
            (
                "Duplicate task scores            : "
                f"{checks['duplicate_task_scores']:,}"
            ),
            (
                "Tasks missing scores             : "
                f"{checks['tasks_missing_scores']:,}"
            ),
            (
                "Score values out of range        : "
                f"{checks['score_values_out_of_range']:,}"
            ),
            (
                "Rows using ML                    : "
                f"{checks['ml_used_rows']:,}"
            ),
            "",
            "INTERPRETATION",
            "-" * 72,
            (
                "The V3.8 score measures intrinsic maintenance value before "
                "train/freight disruption cost is considered."
            ),
            (
                "Asset-availability gain is a normalized decision-support score, "
                "not a claim of percentage uptime improvement."
            ),
            (
                "Where real/canonical source signals are unavailable, TrackEase "
                "uses documented fallbacks from existing task priority/type rather "
                "than fabricating hidden asset measurements."
            ),
            (
                "The weak V2 ML model is intentionally not used in this scoring "
                "layer."
            ),
            (
                "Safety remains a hard constraint; a high score cannot override "
                "an unsafe block arrangement."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Build explicit passenger/freight train-impact metrics so "
                "Optimizer V3 can balance maintenance value against operational "
                "disruption."
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
        "TrackEase V3.8 - Asset Risk & Asset Availability Scoring"
    )
    print("=" * 72)

    require_inputs()

    print(
        "\nLoading canonical asset, request, task, timing and resource data..."
    )

    assets = pd.read_csv(
        ASSETS_FILE,
        low_memory=False,
    )

    requests = pd.read_csv(
        REQUESTS_FILE,
        low_memory=False,
    )

    tasks = pd.read_csv(
        TASKS_FILE,
        low_memory=False,
    )

    timing = pd.read_csv(
        TIMING_FILE,
        low_memory=False,
    )

    feasibility = pd.read_csv(
        RESOURCE_FEASIBILITY_FILE,
        low_memory=False,
    )

    print(
        f"Assets loaded : {len(assets):,}"
    )
    print(
        f"Requests      : {len(requests):,}"
    )
    print(
        f"Tasks         : {len(tasks):,}"
    )

    print(
        "\nBuilding explainable risk and availability scores..."
    )

    (
        asset_scores,
        task_scores,
    ) = build_scores(
        assets,
        requests,
        tasks,
        timing,
        feasibility,
    )

    checks = validate_outputs(
        assets,
        tasks,
        asset_scores,
        task_scores,
    )

    asset_scores.to_csv(
        ASSET_OUTPUT,
        index=False,
    )

    task_scores.to_csv(
        TASK_OUTPUT,
        index=False,
    )

    write_report(
        task_scores,
        asset_scores,
        checks,
    )

    print(
        "\n"
        + "=" * 72
    )
    print(
        "V3.8 RISK & ASSET AVAILABILITY SCORING COMPLETE"
    )
    print(
        "=" * 72
    )

    print(
        f"\nScored assets                   : "
        f"{len(asset_scores):,}"
    )
    print(
        f"Scored tasks                    : "
        f"{len(task_scores):,}"
    )
    print(
        f"Average asset-risk score        : "
        f"{task_scores['asset_risk_score'].mean():.2f}"
    )
    print(
        f"Average availability-gain score : "
        f"{task_scores['asset_availability_gain_score'].mean():.2f}"
    )
    print(
        f"Average maintenance-value score : "
        f"{task_scores['intrinsic_maintenance_value_score'].mean():.2f}"
    )

    print(
        "\nIntegrity:"
    )
    print(
        f"  Duplicate asset scores       : "
        f"{checks['duplicate_asset_scores']:,}"
    )
    print(
        f"  Duplicate task scores        : "
        f"{checks['duplicate_task_scores']:,}"
    )
    print(
        f"  Missing task scores          : "
        f"{checks['tasks_missing_scores']:,}"
    )
    print(
        f"  Out-of-range score values    : "
        f"{checks['score_values_out_of_range']:,}"
    )
    print(
        f"  ML-used rows                 : "
        f"{checks['ml_used_rows']:,}"
    )

    print(
        "\nOutputs:"
    )
    print(
        f"  {ASSET_OUTPUT}"
    )
    print(
        f"  {TASK_OUTPUT}"
    )
    print(
        f"  {REPORT_OUTPUT}"
    )

    print(
        "\nTrackEase V3 can now rank maintenance by explainable asset risk, "
        "risk reduction and expected asset-availability benefit."
    )


if __name__ == "__main__":
    main()
