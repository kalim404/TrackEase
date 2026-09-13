"""
TrackEase V3.10 - Opportunity / Shadow Block Detector

Purpose
-------
Convert validated railway safe windows into exact task-level block
opportunities and detect integrated/shadow coordination opportunities.

This stage is deliberately safety-first:
    - every task candidate must fit its required V3.6 block duration
    - exact timetable movement overlap is rechecked
    - exact COA-style goods overlap is rechecked when time fields are available
    - only conflict-free task candidates are exported as safe opportunities
    - integrated and shadow relationships remain recommendations requiring
      later exact resource/safety validation and human authorization

Inputs
------
Required:
    data/processed/v3_task_timing_components.csv
    data/processed/v3_task_block_requirements.csv
    data/processed/v3_task_maintenance_value_scores.csv
    data/processed/v3_task_operational_exposure.csv
    data/processed/v3_task_compatibility_graph.csv
    data/processed/v3_coordination_groups.csv

Auto-discovered:
    adjusted safe-window CSV from the validated V2 pipeline
    weekly section movements CSV
    COA-style goods forecast CSV (optional exact timing validation)

Outputs
-------
    data/processed/v3_candidate_block_windows.csv
    data/processed/v3_integrated_block_opportunities.csv
    data/processed/v3_shadow_block_opportunities.csv
    data/processed/v3_task_opportunity_summary.csv
    data/processed/v3_opportunity_detector_report.txt

Notes
-----
- Existing V2/V3 files are read-only.
- Candidate windows are recommendations, never railway block authority.
- All prototype scoring/ranking assumptions are explicitly labelled.

Exact TrackEase timing schemas recognized
-----------------------------------------
weekly_section_movements.csv:
    weekly_departure_minute -> weekly_arrival_minute
    movement_departure / movement_arrival as clock fallbacks

coa_goods_forecast.csv:
    expected_start_minute -> expected_end_minute
    expected_start_time / expected_end_time as clock fallbacks

adjusted_block_windows.csv:
    window_start_minute -> window_end_minute
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha1
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
MAINTENANCE_VALUE_FILE = (
    PROCESSED_DIR / "v3_task_maintenance_value_scores.csv"
)
OPERATIONAL_EXPOSURE_FILE = (
    PROCESSED_DIR / "v3_task_operational_exposure.csv"
)
COMPATIBILITY_FILE = (
    PROCESSED_DIR / "v3_task_compatibility_graph.csv"
)
COORDINATION_GROUPS_FILE = (
    PROCESSED_DIR / "v3_coordination_groups.csv"
)

CANDIDATE_OUTPUT = (
    PROCESSED_DIR / "v3_candidate_block_windows.csv"
)
INTEGRATED_OUTPUT = (
    PROCESSED_DIR / "v3_integrated_block_opportunities.csv"
)
SHADOW_OUTPUT = (
    PROCESSED_DIR / "v3_shadow_block_opportunities.csv"
)
SUMMARY_OUTPUT = (
    PROCESSED_DIR / "v3_task_opportunity_summary.csv"
)
REPORT_OUTPUT = (
    PROCESSED_DIR / "v3_opportunity_detector_report.txt"
)


# ---------------------------------------------------------------------------
# Policy / provenance
# ---------------------------------------------------------------------------

MINUTES_PER_WEEK = 7 * 24 * 60

DATA_ORIGIN = "TRACKEASE_V3_OPPORTUNITY_DETECTOR"
INTEGRATION_MODE = "PROTOTYPE_SAFE_WINDOW_OPPORTUNITY_ENGINE"

MAX_CANDIDATES_PER_TASK = 20
MAX_INTEGRATED_WINDOWS_PER_GROUP = 10
MAX_SHADOW_LINKS_PER_EDGE = 3

# Candidate ranking is only used to keep a manageable shortlist.
# Final selection belongs to Optimizer V3.
WEIGHT_MAINTENANCE_VALUE = 0.50
WEIGHT_LOW_OPERATIONAL_EXPOSURE = 0.30
WEIGHT_WINDOW_FIT = 0.20


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


def bool_value(value: object, default: bool = False) -> bool:
    if pd.isna(value):
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"true", "1", "yes", "y"}:
        return True

    if text in {"false", "0", "no", "n"}:
        return False

    return default


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


def stable_id(
    prefix: str,
    *parts: object,
    length: int = 12,
) -> str:

    normalized = "|".join(
        clean_text(part).upper()
        for part in parts
    )

    digest = sha1(
        normalized.encode("utf-8")
    ).hexdigest()[:length].upper()

    return f"{prefix}-{digest}"


def first_existing(
    columns: list[str],
    candidates: list[str],
) -> str | None:

    available = set(columns)

    for candidate in candidates:
        if candidate in available:
            return candidate

    return None


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


def require_inputs() -> None:
    required = [
        TIMING_FILE,
        BLOCK_REQUIREMENTS_FILE,
        MAINTENANCE_VALUE_FILE,
        OPERATIONAL_EXPOSURE_FILE,
        COMPATIBILITY_FILE,
        COORDINATION_GROUPS_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        raise FileNotFoundError(
            "Required V3.10 input files are missing:\n"
            + "\n".join(
                f"  {path}"
                for path in missing
            )
        )


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------

def discover_file(
    preferred_names: list[str],
    patterns: list[str],
    exclude_prefixes: tuple[str, ...] = ("v3_",),
) -> Path | None:

    for name in preferred_names:
        path = PROCESSED_DIR / name

        if path.exists():
            return path

    candidates: list[Path] = []

    for pattern in patterns:
        candidates.extend(
            PROCESSED_DIR.glob(pattern)
        )

    unique = sorted(
        {
            path.resolve()
            for path in candidates
            if not any(
                path.name.lower().startswith(
                    prefix.lower()
                )
                for prefix in exclude_prefixes
            )
        }
    )

    if not unique:
        return None

    return Path(unique[0])


def discover_safe_windows_file() -> Path:
    path = discover_file(
        preferred_names=[
            "adjusted_safe_windows.csv",
            "adjusted_safe_block_windows.csv",
            "safe_windows_adjusted.csv",
            "safe_block_windows.csv",
            "block_windows.csv",
        ],
        patterns=[
            "*adjusted*safe*window*.csv",
            "*safe*block*window*.csv",
            "*safe*window*.csv",
            "*block*window*.csv",
        ],
    )

    if path is None:
        raise FileNotFoundError(
            "Could not locate the validated safe-window CSV in "
            f"{PROCESSED_DIR}."
        )

    return path


def discover_weekly_movements_file() -> Path:
    path = discover_file(
        preferred_names=[
            "weekly_section_movements.csv",
            "section_weekly_movements.csv",
            "weekly_movements.csv",
        ],
        patterns=[
            "*weekly*section*movement*.csv",
            "*section*movement*weekly*.csv",
            "*weekly*movement*.csv",
        ],
    )

    if path is None:
        raise FileNotFoundError(
            "Could not locate weekly section movements in "
            f"{PROCESSED_DIR}."
        )

    return path


def discover_goods_file() -> Path | None:
    return discover_file(
        preferred_names=[
            "coa_goods_forecast.csv",
            "coa_goods_events.csv",
            "prototype_coa_goods_forecast.csv",
            "goods_train_forecast.csv",
        ],
        patterns=[
            "*coa*goods*.csv",
            "*goods*forecast*.csv",
            "*goods*event*.csv",
            "*freight*forecast*.csv",
        ],
        exclude_prefixes=(
            "v3_",
            "adjusted_",
        ),
    )


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------

def hhmm_to_minutes(value: object) -> float | None:
    text = clean_text(value)

    if not text or ":" not in text:
        return None

    try:
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1])

        if not (
            0 <= hour <= 23
            and 0 <= minute <= 59
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

    names = {
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

    if text in names:
        return names[text]

    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None

    if 0 <= number <= 6:
        return number

    if 1 <= number <= 7:
        return number - 1

    return None


def minute_to_week_label(value: float) -> str:
    minute = int(round(value)) % MINUTES_PER_WEEK

    day_index = minute // 1440
    minute_of_day = minute % 1440

    hour = minute_of_day // 60
    minute_part = minute_of_day % 60

    days = [
        "MON",
        "TUE",
        "WED",
        "THU",
        "FRI",
        "SAT",
        "SUN",
    ]

    return (
        f"{days[day_index]} "
        f"{hour:02d}:{minute_part:02d}"
    )


# ---------------------------------------------------------------------------
# Safe-window normalization
# ---------------------------------------------------------------------------

def detect_safe_window_schema(
    windows: pd.DataFrame,
) -> dict[str, str | None]:

    columns = windows.columns.tolist()

    schema = {
        "section":
            first_existing(
                columns,
                [
                    "section_id",
                    "railway_section_id",
                    "section",
                ],
            ),

        "start_abs":
            first_existing(
                columns,
                [
                    "adjusted_start_abs_min",
                    "safe_start_abs_min",
                    "start_abs_min",
                    "window_start_abs_min",
                    "start_minute_of_week",
                    "window_start_minute",
                    "start_minute",
                    "start_min",
                ],
            ),

        "end_abs":
            first_existing(
                columns,
                [
                    "adjusted_end_abs_min",
                    "safe_end_abs_min",
                    "end_abs_min",
                    "window_end_abs_min",
                    "end_minute_of_week",
                    "window_end_minute",
                    "end_minute",
                    "end_min",
                ],
            ),

        "duration":
            first_existing(
                columns,
                [
                    "adjusted_duration_min",
                    "safe_duration_min",
                    "window_duration_min",
                    "duration_min",
                    "duration_minutes",
                    "window_minutes",
                ],
            ),

        "day":
            first_existing(
                columns,
                [
                    "day_of_week",
                    "weekday",
                    "week_day",
                    "day",
                ],
            ),

        "start_time":
            first_existing(
                columns,
                [
                    "adjusted_start_time",
                    "safe_start_time",
                    "window_start_time",
                    "start_time",
                ],
            ),

        "end_time":
            first_existing(
                columns,
                [
                    "adjusted_end_time",
                    "safe_end_time",
                    "window_end_time",
                    "end_time",
                ],
            ),
    }

    if schema["section"] is None:
        raise ValueError(
            "Safe-window file has no recognizable section column. "
            f"Columns: {columns}"
        )

    has_absolute = (
        schema["start_abs"] is not None
        and (
            schema["end_abs"] is not None
            or schema["duration"] is not None
        )
    )

    has_clock = (
        schema["day"] is not None
        and schema["start_time"] is not None
        and (
            schema["end_time"] is not None
            or schema["duration"] is not None
        )
    )

    if not (
        has_absolute
        or has_clock
    ):
        raise ValueError(
            "Safe-window timing schema could not be recognized. "
            f"Columns: {columns}"
        )

    return schema


def normalize_safe_windows(
    windows: pd.DataFrame,
    schema: dict[str, str | None],
) -> pd.DataFrame:

    rows = []

    for source_index, row in windows.iterrows():
        section_id = clean_text(
            row.get(
                schema["section"]
            )
        )

        if not section_id:
            continue

        start = None
        end = None
        duration = None

        if schema["start_abs"] is not None:
            start = safe_float(
                row.get(
                    schema["start_abs"]
                )
            )

        if schema["end_abs"] is not None:
            end = safe_float(
                row.get(
                    schema["end_abs"]
                )
            )

        if schema["duration"] is not None:
            duration = safe_float(
                row.get(
                    schema["duration"]
                )
            )

        if start is None:
            day_index = normalized_day_index(
                row.get(
                    schema["day"]
                )
            )

            start_clock = hhmm_to_minutes(
                row.get(
                    schema["start_time"]
                )
            )

            if (
                day_index is None
                or start_clock is None
            ):
                continue

            start = (
                day_index * 1440
                + start_clock
            )

        if duration is None:
            if end is None:
                end_clock = hhmm_to_minutes(
                    row.get(
                        schema["end_time"]
                    )
                )

                day_index = normalized_day_index(
                    row.get(
                        schema["day"]
                    )
                )

                if (
                    end_clock is None
                    or day_index is None
                ):
                    continue

                end = (
                    day_index * 1440
                    + end_clock
                )

            duration = end - start

            while duration <= 0:
                duration += MINUTES_PER_WEEK

        if end is None:
            end = start + duration

        if end <= start:
            end = start + duration

        if duration <= 0:
            continue

        # Keep a cyclic representation in which a Sunday->Monday window can
        # legitimately end beyond minute 10080.
        normalized_start = (
            start % MINUTES_PER_WEEK
        )

        normalized_end = (
            normalized_start
            + duration
        )

        rows.append(
            {
                "source_safe_window_index":
                    int(source_index),

                "section_id":
                    section_id,

                "window_start_minute_week":
                    float(
                        normalized_start
                    ),

                "window_end_minute_week":
                    float(
                        normalized_end
                    ),

                "window_duration_minutes":
                    float(
                        duration
                    ),

                "window_start_label":
                    minute_to_week_label(
                        normalized_start
                    ),

                "window_end_label":
                    minute_to_week_label(
                        normalized_end
                    ),

                "crosses_week_boundary":
                    bool(
                        normalized_end
                        > MINUTES_PER_WEEK
                    ),
            }
        )

    result = pd.DataFrame(
        rows
    )

    if result.empty:
        raise RuntimeError(
            "No usable safe windows remained after normalization."
        )

    return result


# ---------------------------------------------------------------------------
# Operational event normalization
# ---------------------------------------------------------------------------

def detect_event_schema(
    data: pd.DataFrame,
    is_goods: bool,
) -> dict[str, str | None]:

    columns = data.columns.tolist()

    event_candidates = (
        [
            "event_id",
            "goods_event_id",
            "forecast_id",
            "train_number",
            "train_id",
        ]
        if is_goods
        else
        [
            "train_number",
            "train_id",
            "train_no",
            "movement_id",
        ]
    )

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
                event_candidates,
            ),

        "start_abs":
            first_existing(
                columns,
                [
                    # TrackEase validated weekly movement schema
                    "weekly_departure_minute",

                    # TrackEase COA prototype schema
                    "expected_start_minute",

                    # Generic fallbacks
                    "entry_abs_min",
                    "start_abs_min",
                    "section_entry_abs_min",
                    "forecast_start_abs_min",
                    "entry_minute_of_week",
                    "start_minute_of_week",
                    "event_start_minute",
                    "entry_min",
                    "start_min",
                ],
            ),

        "end_abs":
            first_existing(
                columns,
                [
                    # TrackEase validated weekly movement schema
                    "weekly_arrival_minute",

                    # TrackEase COA prototype schema
                    "expected_end_minute",

                    # Generic fallbacks
                    "exit_abs_min",
                    "end_abs_min",
                    "section_exit_abs_min",
                    "forecast_end_abs_min",
                    "exit_minute_of_week",
                    "end_minute_of_week",
                    "event_end_minute",
                    "exit_min",
                    "end_min",
                ],
            ),

        "day":
            first_existing(
                columns,
                [
                    # TrackEase movement / COA schemas
                    "departure_weekday",
                    "forecast_day",

                    # Generic fallbacks
                    "day_of_week",
                    "weekday",
                    "week_day",
                    "day",
                ],
            ),

        "end_day":
            first_existing(
                columns,
                [
                    "arrival_weekday",
                    "expected_end_day",
                ],
            ),

        "start_time":
            first_existing(
                columns,
                [
                    # TrackEase movement / COA schemas
                    "movement_departure",
                    "expected_start_time",

                    # Generic fallbacks
                    "entry_time",
                    "start_time",
                    "forecast_start_time",
                    "departure",
                    "arrival",
                ],
            ),

        "end_time":
            first_existing(
                columns,
                [
                    # TrackEase movement / COA schemas
                    "movement_arrival",
                    "expected_end_time",

                    # Generic fallbacks
                    "exit_time",
                    "end_time",
                    "forecast_end_time",
                ],
            ),

        "duration":
            first_existing(
                columns,
                [
                    "travel_minutes",
                    "forecast_duration_minutes",
                    "duration_minutes",
                ],
            ),
    }


def normalize_events(
    data: pd.DataFrame | None,
    is_goods: bool,
) -> tuple[pd.DataFrame, str]:

    columns = [
        "section_id",
        "event_id",
        "event_start_minute_week",
        "event_end_minute_week",
    ]

    if data is None:
        return (
            pd.DataFrame(
                columns=columns
            ),
            "NO_SOURCE_FILE",
        )

    schema = detect_event_schema(
        data,
        is_goods=is_goods,
    )

    if schema["section"] is None:
        return (
            pd.DataFrame(
                columns=columns
            ),
            "SECTION_COLUMN_UNRECOGNIZED",
        )

    has_time = (
        schema["start_abs"] is not None
        or (
            schema["day"] is not None
            and schema["start_time"] is not None
        )
    )

    if not has_time:
        return (
            pd.DataFrame(
                columns=columns
            ),
            "TIME_SCHEMA_UNAVAILABLE",
        )

    rows = []

    for source_index, row in data.iterrows():
        section_id = clean_text(
            row.get(
                schema["section"]
            )
        )

        if not section_id:
            continue

        event_id = (
            clean_text(
                row.get(
                    schema["event_id"]
                )
            )
            if schema["event_id"] is not None
            else str(
                source_index
            )
        )

        start = None
        end = None

        if schema["start_abs"] is not None:
            start = safe_float(
                row.get(
                    schema["start_abs"]
                )
            )

        if schema["end_abs"] is not None:
            end = safe_float(
                row.get(
                    schema["end_abs"]
                )
            )

        if start is None:
            day_index = normalized_day_index(
                row.get(
                    schema["day"]
                )
            )

            start_clock = hhmm_to_minutes(
                row.get(
                    schema["start_time"]
                )
            )

            if (
                day_index is None
                or start_clock is None
            ):
                continue

            start = (
                day_index * 1440
                + start_clock
            )

        if end is None:
            end_clock = (
                hhmm_to_minutes(
                    row.get(
                        schema["end_time"]
                    )
                )
                if schema["end_time"] is not None
                else None
            )

            end_day_index = (
                normalized_day_index(
                    row.get(
                        schema["end_day"]
                    )
                )
                if schema.get("end_day") is not None
                else None
            )

            if (
                end_clock is not None
                and end_day_index is not None
            ):
                end = (
                    end_day_index * 1440
                    + end_clock
                )

                # A Sunday -> Monday event may wrap into the next week.
                while end < start:
                    end += MINUTES_PER_WEEK

            elif end_clock is not None:
                end = (
                    (
                        int(
                            start
                        )
                        // 1440
                    )
                    * 1440
                    + end_clock
                )

                while end < start:
                    end += 1440

            else:
                duration = (
                    safe_float(
                        row.get(
                            schema["duration"]
                        )
                    )
                    if schema.get("duration") is not None
                    else None
                )

                if duration is not None:
                    end = (
                        start
                        + max(
                            0.0,
                            duration,
                        )
                    )
                else:
                    # If only one event timestamp exists, keep it as an
                    # instantaneous section-event marker.
                    end = start

        # Absolute weekly end columns may wrap to the beginning of the next
        # week. Preserve that duration instead of collapsing it to zero.
        if end < start:
            duration = (
                safe_float(
                    row.get(
                        schema["duration"]
                    )
                )
                if schema.get("duration") is not None
                else None
            )

            if duration is not None:
                end = (
                    start
                    + max(
                        0.0,
                        duration,
                    )
                )
            else:
                while end < start:
                    end += MINUTES_PER_WEEK

        normalized_start = (
            start % MINUTES_PER_WEEK
        )

        raw_duration = max(
            0.0,
            end - start,
        )

        normalized_end = (
            normalized_start
            + raw_duration
        )

        rows.append(
            {
                "section_id":
                    section_id,

                "event_id":
                    event_id,

                "event_start_minute_week":
                    float(
                        normalized_start
                    ),

                "event_end_minute_week":
                    float(
                        normalized_end
                    ),
            }
        )

    normalized = pd.DataFrame(
        rows,
        columns=columns,
    )

    if (
        schema["start_abs"]
        in {
            "weekly_departure_minute",
            "expected_start_minute",
        }
        and schema["end_abs"]
        in {
            "weekly_arrival_minute",
            "expected_end_minute",
        }
    ):
        status = (
            "TIME_SCHEMA_AVAILABLE_TRACK_EASE_WEEKLY_MINUTES"
        )
    else:
        status = "TIME_SCHEMA_AVAILABLE"

    return (
        normalized,
        status,
    )


def build_event_index(
    events: pd.DataFrame,
) -> dict[
    str,
    list[tuple[float, float, str]]
]:

    result: dict[
        str,
        list[tuple[float, float, str]]
    ] = defaultdict(
        list
    )

    for row in events.itertuples(
        index=False
    ):
        start = float(
            row.event_start_minute_week
        )

        end = float(
            row.event_end_minute_week
        )

        event_id = clean_text(
            row.event_id
        )

        # Duplicate cyclic copies allow Sunday->Monday windows to be checked
        # without special-case overlap logic.
        for shift in (
            -MINUTES_PER_WEEK,
            0,
            MINUTES_PER_WEEK,
        ):
            result[
                clean_text(
                    row.section_id
                )
            ].append(
                (
                    start + shift,
                    end + shift,
                    event_id,
                )
            )

    for section_id in result:
        result[
            section_id
        ].sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            )
        )

    return dict(
        result
    )


def overlapping_events(
    event_index: dict[
        str,
        list[tuple[float, float, str]]
    ],
    section_id: str,
    start: float,
    end: float,
) -> list[str]:

    overlaps = []

    for (
        event_start,
        event_end,
        event_id,
    ) in event_index.get(
        section_id,
        [],
    ):
        if event_start > end:
            break

        if math.isclose(
            event_start,
            event_end,
        ):
            is_overlap = (
                start
                <= event_start
                < end
            )
        else:
            is_overlap = (
                event_start < end
                and event_end > start
            )

        if is_overlap:
            overlaps.append(
                event_id
            )

    return sorted(
        set(
            overlaps
        )
    )


# ---------------------------------------------------------------------------
# Task candidate generation
# ---------------------------------------------------------------------------

def window_fit_score(
    safe_window_minutes: float,
    required_minutes: float,
) -> float:
    slack = (
        safe_window_minutes
        - required_minutes
    )

    if slack < 0:
        return 0.0

    # 20-90 minutes of spare capacity is useful; very large gaps remain good
    # but should not dominate maintenance priority.
    if slack <= 90:
        return clamp(
            70.0
            + (
                slack / 90.0
            )
            * 30.0
        )

    return 100.0


def build_task_candidates(
    timing: pd.DataFrame,
    block_requirements: pd.DataFrame,
    maintenance_value: pd.DataFrame,
    operational_exposure: pd.DataFrame,
    safe_windows: pd.DataFrame,
    train_index: dict[
        str,
        list[tuple[float, float, str]]
    ],
    goods_index: dict[
        str,
        list[tuple[float, float, str]]
    ],
    goods_exact_status: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:

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
                "work_splittable",
            ]
        ]
        .merge(
            block_requirements[
                [
                    "task_id",
                    "planning_mode",
                    "eligible_for_integrated_block",
                    "eligible_for_shadow_block",
                    "emergency_block",
                    "requires_traffic_block",
                    "requires_power_block",
                    "requires_disconnection",
                ]
            ],
            on="task_id",
            how="left",
            validate="one_to_one",
        )
        .merge(
            maintenance_value[
                [
                    "task_id",
                    "intrinsic_maintenance_value_score",
                    "asset_risk_score",
                    "asset_availability_gain_score",
                ]
            ],
            on="task_id",
            how="left",
            validate="one_to_one",
        )
        .merge(
            operational_exposure[
                [
                    "task_id",
                    "prewindow_operational_impact_score",
                ]
            ],
            on="task_id",
            how="left",
            validate="one_to_one",
        )
    )

    windows_by_section = {
        section_id:
            group.sort_values(
                [
                    "window_start_minute_week",
                    "window_duration_minutes",
                ]
            )
        for (
            section_id,
            group
        ) in safe_windows.groupby(
            "section_id"
        )
    }

    candidate_rows = []
    summary_rows = []

    for task in task_table.itertuples(
        index=False
    ):
        task_id = clean_text(
            task.task_id
        )

        section_id = clean_text(
            task.section_id
        )

        required_minutes = float(
            task.total_block_expected_minutes
        )

        section_windows = windows_by_section.get(
            section_id
        )

        safe_window_count = (
            len(
                section_windows
            )
            if section_windows is not None
            else 0
        )

        duration_fit_count = 0
        train_conflict_rejections = 0
        goods_conflict_rejections = 0
        accepted = []

        if section_windows is not None:
            for window in section_windows.itertuples(
                index=False
            ):
                if (
                    float(
                        window.window_duration_minutes
                    )
                    < required_minutes
                ):
                    continue

                duration_fit_count += 1

                start = float(
                    window.window_start_minute_week
                )

                end = (
                    start
                    + required_minutes
                )

                train_conflicts = overlapping_events(
                    train_index,
                    section_id,
                    start,
                    end,
                )

                if train_conflicts:
                    train_conflict_rejections += 1
                    continue

                goods_conflicts = overlapping_events(
                    goods_index,
                    section_id,
                    start,
                    end,
                )

                if goods_conflicts:
                    goods_conflict_rejections += 1
                    continue

                fit_score = window_fit_score(
                    float(
                        window.window_duration_minutes
                    ),
                    required_minutes,
                )

                maintenance_score = float(
                    task.intrinsic_maintenance_value_score
                )

                operational_score = float(
                    task.prewindow_operational_impact_score
                )

                low_operational_score = (
                    100.0
                    - operational_score
                )

                shortlist_score = (
                    WEIGHT_MAINTENANCE_VALUE
                    * maintenance_score
                    + WEIGHT_LOW_OPERATIONAL_EXPOSURE
                    * low_operational_score
                    + WEIGHT_WINDOW_FIT
                    * fit_score
                )

                candidate_id = stable_id(
                    "V3WIN",
                    task_id,
                    section_id,
                    start,
                    end,
                )

                opportunity_type = (
                    "NATURAL_SAFE_WINDOW"
                )

                if bool_value(
                    task.eligible_for_integrated_block
                ):
                    opportunity_type = (
                        "SAFE_WINDOW_WITH_INTEGRATION_POTENTIAL"
                    )

                accepted.append(
                    {
                        "candidate_window_id":
                            candidate_id,

                        "task_id":
                            task_id,

                        "section_id":
                            section_id,

                        "task_type":
                            clean_text(
                                task.task_type
                            ),

                        "primary_block_requirement":
                            clean_text(
                                task.primary_block_requirement
                            ),

                        "planning_mode":
                            clean_text(
                                task.planning_mode
                            ),

                        "opportunity_type":
                            opportunity_type,

                        "window_start_minute_week":
                            round(
                                start,
                                3,
                            ),

                        "window_end_minute_week":
                            round(
                                end,
                                3,
                            ),

                        "window_start_label":
                            minute_to_week_label(
                                start
                            ),

                        "window_end_label":
                            minute_to_week_label(
                                end
                            ),

                        "required_block_minutes":
                            round(
                                required_minutes,
                                3,
                            ),

                        "source_safe_window_minutes":
                            round(
                                float(
                                    window.window_duration_minutes
                                ),
                                3,
                            ),

                        "window_slack_minutes":
                            round(
                                float(
                                    window.window_duration_minutes
                                )
                                - required_minutes,
                                3,
                            ),

                        "crosses_week_boundary":
                            bool(
                                end
                                > MINUTES_PER_WEEK
                            ),

                        "exact_train_conflict_count":
                            0,

                        "exact_train_conflict_ids":
                            "",

                        "exact_goods_conflict_count":
                            0,

                        "exact_goods_conflict_ids":
                            "",

                        "goods_exact_validation_status":
                            goods_exact_status,

                        "safety_candidate_status":
                            "TRAIN_AND_GOODS_CONFLICT_FREE",

                        "maintenance_value_score":
                            round(
                                maintenance_score,
                                3,
                            ),

                        "prewindow_operational_impact_score":
                            round(
                                operational_score,
                                3,
                            ),

                        "window_fit_score":
                            round(
                                fit_score,
                                3,
                            ),

                        "opportunity_shortlist_score":
                            round(
                                shortlist_score,
                                3,
                            ),

                        "eligible_for_shadow_block":
                            bool_value(
                                task.eligible_for_shadow_block
                            ),

                        "eligible_for_integrated_block":
                            bool_value(
                                task.eligible_for_integrated_block
                            ),

                        "requires_exact_resource_time_check":
                            True,

                        "requires_detailed_safety_gate":
                            True,

                        "human_authorization_required":
                            True,

                        "data_origin":
                            DATA_ORIGIN,

                        "integration_mode":
                            INTEGRATION_MODE,

                        "is_prototype_derived":
                            True,
                    }
                )

        accepted.sort(
            key=lambda item: (
                -item[
                    "opportunity_shortlist_score"
                ],
                item[
                    "window_start_minute_week"
                ],
            )
        )

        accepted = accepted[
            :MAX_CANDIDATES_PER_TASK
        ]

        for rank, candidate in enumerate(
            accepted,
            start=1,
        ):
            candidate[
                "task_candidate_rank"
            ] = rank

            candidate_rows.append(
                candidate
            )

        summary_rows.append(
            {
                "task_id":
                    task_id,

                "section_id":
                    section_id,

                "safe_windows_on_section":
                    safe_window_count,

                "duration_fit_windows":
                    duration_fit_count,

                "train_conflict_rejections":
                    train_conflict_rejections,

                "goods_conflict_rejections":
                    goods_conflict_rejections,

                "accepted_candidate_windows":
                    len(
                        accepted
                    ),

                "has_safe_opportunity":
                    bool(
                        accepted
                    ),

                "opportunity_status":
                    (
                        "SAFE_OPPORTUNITY_AVAILABLE"
                        if accepted
                        else (
                            "NO_DURATION_FIT_WINDOW"
                            if duration_fit_count == 0
                            else "NO_CONFLICT_FREE_WINDOW"
                        )
                    ),

                "data_origin":
                    DATA_ORIGIN,

                "integration_mode":
                    INTEGRATION_MODE,
            }
        )

    return (
        pd.DataFrame(
            candidate_rows
        ),
        pd.DataFrame(
            summary_rows
        ),
    )


# ---------------------------------------------------------------------------
# Integrated opportunities
# ---------------------------------------------------------------------------

def build_integrated_opportunities(
    coordination_groups: pd.DataFrame,
    safe_windows: pd.DataFrame,
    maintenance_value: pd.DataFrame,
    train_index: dict[
        str,
        list[tuple[float, float, str]]
    ],
    goods_index: dict[
        str,
        list[tuple[float, float, str]]
    ],
) -> pd.DataFrame:

    if coordination_groups.empty:
        return pd.DataFrame()

    value_lookup = maintenance_value.set_index(
        "task_id"
    )[
        "intrinsic_maintenance_value_score"
    ].to_dict()

    windows_by_section = {
        section_id:
            group
        for (
            section_id,
            group
        ) in safe_windows.groupby(
            "section_id"
        )
    }

    rows = []

    for group in coordination_groups.itertuples(
        index=False
    ):
        section_id = clean_text(
            group.section_id
        )

        required_minutes = float(
            group.estimated_group_block_minutes
        )

        task_ids = [
            task_id
            for task_id in clean_text(
                group.task_ids
            ).split("|")
            if task_id
        ]

        values = [
            float(
                value_lookup.get(
                    task_id,
                    50.0,
                )
            )
            for task_id in task_ids
        ]

        group_value = (
            sum(values)
            / len(values)
            if values
            else 50.0
        )

        candidates = []

        for window in windows_by_section.get(
            section_id,
            pd.DataFrame(),
        ).itertuples(
            index=False
        ):
            if (
                float(
                    window.window_duration_minutes
                )
                < required_minutes
            ):
                continue

            start = float(
                window.window_start_minute_week
            )

            end = (
                start
                + required_minutes
            )

            if overlapping_events(
                train_index,
                section_id,
                start,
                end,
            ):
                continue

            if overlapping_events(
                goods_index,
                section_id,
                start,
                end,
            ):
                continue

            fit_score = window_fit_score(
                float(
                    window.window_duration_minutes
                ),
                required_minutes,
            )

            integrated_score = (
                0.70
                * group_value
                + 0.30
                * fit_score
            )

            candidates.append(
                {
                    "integrated_opportunity_id":
                        stable_id(
                            "INTWIN",
                            group.coordination_group_id,
                            start,
                            end,
                        ),

                    "coordination_group_id":
                        group.coordination_group_id,

                    "section_id":
                        section_id,

                    "task_count":
                        int(
                            group.task_count
                        ),

                    "task_ids":
                        clean_text(
                            group.task_ids
                        ),

                    "departments":
                        clean_text(
                            group.departments
                        ),

                    "window_start_minute_week":
                        round(
                            start,
                            3,
                        ),

                    "window_end_minute_week":
                        round(
                            end,
                            3,
                        ),

                    "window_start_label":
                        minute_to_week_label(
                            start
                        ),

                    "window_end_label":
                        minute_to_week_label(
                            end
                        ),

                    "required_group_block_minutes":
                        round(
                            required_minutes,
                            3,
                        ),

                    "window_slack_minutes":
                        round(
                            float(
                                window.window_duration_minutes
                            )
                            - required_minutes,
                            3,
                        ),

                    "group_maintenance_value_score":
                        round(
                            group_value,
                            3,
                        ),

                    "integrated_opportunity_score":
                        round(
                            integrated_score,
                            3,
                        ),

                    "requires_additional_power_isolation":
                        bool_value(
                            group.requires_additional_power_isolation
                        ),

                    "requires_additional_disconnection":
                        bool_value(
                            group.requires_additional_disconnection
                        ),

                    "safety_candidate_status":
                        "TRAIN_AND_GOODS_CONFLICT_FREE",

                    "requires_exact_resource_time_check":
                        True,

                    "requires_detailed_safety_gate":
                        True,

                    "human_authorization_required":
                        True,

                    "data_origin":
                        DATA_ORIGIN,

                    "integration_mode":
                        INTEGRATION_MODE,

                    "is_prototype_derived":
                        True,
                }
            )

        candidates.sort(
            key=lambda item: (
                -item[
                    "integrated_opportunity_score"
                ],
                item[
                    "window_start_minute_week"
                ],
            )
        )

        for rank, candidate in enumerate(
            candidates[
                :MAX_INTEGRATED_WINDOWS_PER_GROUP
            ],
            start=1,
        ):
            candidate[
                "group_candidate_rank"
            ] = rank

            rows.append(
                candidate
            )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Shadow opportunity alignment
# ---------------------------------------------------------------------------

def overlap_minutes(
    start_a: float,
    end_a: float,
    start_b: float,
    end_b: float,
) -> float:

    return max(
        0.0,
        min(
            end_a,
            end_b,
        )
        - max(
            start_a,
            start_b,
        ),
    )


def build_shadow_opportunities(
    compatibility: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:

    if (
        compatibility.empty
        or candidates.empty
    ):
        return pd.DataFrame()

    shadow_edges = compatibility[
        compatibility[
            "shadow_block_candidate"
        ]
        .astype(str)
        .str.lower()
        .eq("true")
    ].copy()

    if shadow_edges.empty:
        return pd.DataFrame()

    by_task = {
        task_id:
            group.sort_values(
                "task_candidate_rank"
            )
        for (
            task_id,
            group
        ) in candidates.groupby(
            "task_id"
        )
    }

    rows = []

    for edge in shadow_edges.itertuples(
        index=False
    ):
        task_a_id = clean_text(
            edge.task_a_id
        )

        task_b_id = clean_text(
            edge.task_b_id
        )

        candidates_a = by_task.get(
            task_a_id
        )

        candidates_b = by_task.get(
            task_b_id
        )

        if (
            candidates_a is None
            or candidates_b is None
        ):
            continue

        pair_candidates = []

        for a in candidates_a.itertuples(
            index=False
        ):
            for b in candidates_b.itertuples(
                index=False
            ):
                overlap = overlap_minutes(
                    float(
                        a.window_start_minute_week
                    ),
                    float(
                        a.window_end_minute_week
                    ),
                    float(
                        b.window_start_minute_week
                    ),
                    float(
                        b.window_end_minute_week
                    ),
                )

                shorter_required = min(
                    float(
                        a.required_block_minutes
                    ),
                    float(
                        b.required_block_minutes
                    ),
                )

                if overlap < shorter_required:
                    continue

                # Longer task acts as the host opportunity; the shorter task can
                # potentially shadow within the common safe interval.
                if (
                    float(
                        a.required_block_minutes
                    )
                    >= float(
                        b.required_block_minutes
                    )
                ):
                    host_task_id = task_a_id
                    shadow_task_id = task_b_id
                    host_candidate_id = (
                        a.candidate_window_id
                    )
                    shadow_candidate_id = (
                        b.candidate_window_id
                    )
                else:
                    host_task_id = task_b_id
                    shadow_task_id = task_a_id
                    host_candidate_id = (
                        b.candidate_window_id
                    )
                    shadow_candidate_id = (
                        a.candidate_window_id
                    )

                pair_score = (
                    (
                        float(
                            a.opportunity_shortlist_score
                        )
                        + float(
                            b.opportunity_shortlist_score
                        )
                    )
                    / 2.0
                )

                pair_candidates.append(
                    {
                        "shadow_opportunity_id":
                            stable_id(
                                "SHADOW",
                                edge.compatibility_edge_id,
                                host_candidate_id,
                                shadow_candidate_id,
                            ),

                        "compatibility_edge_id":
                            edge.compatibility_edge_id,

                        "host_task_id":
                            host_task_id,

                        "shadow_task_id":
                            shadow_task_id,

                        "host_candidate_window_id":
                            host_candidate_id,

                        "shadow_candidate_window_id":
                            shadow_candidate_id,

                        "host_section_id":
                            (
                                a.section_id
                                if host_task_id
                                == task_a_id
                                else b.section_id
                            ),

                        "shadow_section_id":
                            (
                                b.section_id
                                if shadow_task_id
                                == task_b_id
                                else a.section_id
                            ),

                        "common_overlap_minutes":
                            round(
                                overlap,
                                3,
                            ),

                        "relationship_type":
                            clean_text(
                                edge.relationship_type
                            ),

                        "requires_additional_power_isolation":
                            bool_value(
                                edge.requires_additional_power_isolation
                            ),

                        "requires_additional_disconnection":
                            bool_value(
                                edge.requires_additional_disconnection
                            ),

                        "shadow_opportunity_score":
                            round(
                                pair_score,
                                3,
                            ),

                        "shadow_status":
                            "ALIGNED_SAFE_WINDOW_CANDIDATE",

                        "requires_exact_resource_time_check":
                            True,

                        "requires_detailed_safety_gate":
                            True,

                        "human_authorization_required":
                            True,

                        "data_origin":
                            DATA_ORIGIN,

                        "integration_mode":
                            INTEGRATION_MODE,

                        "is_prototype_derived":
                            True,
                    }
                )

        pair_candidates.sort(
            key=lambda item: (
                -item[
                    "shadow_opportunity_score"
                ],
                -item[
                    "common_overlap_minutes"
                ],
            )
        )

        rows.extend(
            pair_candidates[
                :MAX_SHADOW_LINKS_PER_EDGE
            ]
        )

    return pd.DataFrame(
        rows
    )


# ---------------------------------------------------------------------------
# Validation / report
# ---------------------------------------------------------------------------

def validate_outputs(
    timing: pd.DataFrame,
    candidates: pd.DataFrame,
    summaries: pd.DataFrame,
    integrated: pd.DataFrame,
    shadow: pd.DataFrame,
) -> dict[str, int]:

    checks = {
        "tasks":
            len(
                timing
            ),

        "candidate_windows":
            len(
                candidates
            ),

        "task_summaries":
            len(
                summaries
            ),

        "tasks_with_candidates":
            int(
                summaries[
                    "has_safe_opportunity"
                ]
                .astype(bool)
                .sum()
            ),

        "tasks_without_candidates":
            int(
                (
                    ~summaries[
                        "has_safe_opportunity"
                    ]
                    .astype(bool)
                )
                .sum()
            ),

        "integrated_opportunities":
            len(
                integrated
            ),

        "shadow_opportunities":
            len(
                shadow
            ),

        "duplicate_candidate_ids":
            (
                int(
                    candidates[
                        "candidate_window_id"
                    ]
                    .duplicated()
                    .sum()
                )
                if not candidates.empty
                else 0
            ),

        "duplicate_task_summaries":
            int(
                summaries[
                    "task_id"
                ]
                .duplicated()
                .sum()
            ),

        "missing_task_summaries":
            int(
                (
                    ~timing[
                        "task_id"
                    ]
                    .astype(str)
                    .isin(
                        summaries[
                            "task_id"
                        ]
                        .astype(str)
                    )
                )
                .sum()
            ),

        "candidate_train_conflicts":
            (
                int(
                    (
                        candidates[
                            "exact_train_conflict_count"
                        ]
                        > 0
                    )
                    .sum()
                )
                if not candidates.empty
                else 0
            ),

        "candidate_goods_conflicts":
            (
                int(
                    (
                        candidates[
                            "exact_goods_conflict_count"
                        ]
                        > 0
                    )
                    .sum()
                )
                if not candidates.empty
                else 0
            ),
    }

    hard_failures = [
        "duplicate_candidate_ids",
        "duplicate_task_summaries",
        "missing_task_summaries",
        "candidate_train_conflicts",
        "candidate_goods_conflicts",
    ]

    if len(
        summaries
    ) != len(
        timing
    ):
        raise RuntimeError(
            "V3.10 must create exactly one opportunity summary per task."
        )

    if sum(
        checks[
            key
        ]
        for key in hard_failures
    ):
        raise RuntimeError(
            "V3.10 opportunity-detector integrity validation failed."
        )

    return checks


def write_report(
    safe_window_file: Path,
    movement_file: Path,
    goods_file: Path | None,
    train_status: str,
    goods_status: str,
    normalized_windows: pd.DataFrame,
    checks: dict[str, int],
    summaries: pd.DataFrame,
) -> None:

    status_counts = (
        summaries[
            "opportunity_status"
        ]
        .value_counts()
        .sort_index()
    )

    lines = [
        "=" * 72,
        "TrackEase V3.10 Opportunity / Shadow Block Detector Report",
        "=" * 72,
        "",
        "SOURCES",
        "-" * 72,
        f"Safe-window source       : {safe_window_file}",
        f"Weekly movements source  : {movement_file}",
        (
            f"COA/goods source         : {goods_file}"
            if goods_file is not None
            else
            "COA/goods source         : NOT FOUND"
        ),
        f"Train exact-time status  : {train_status}",
        f"Goods exact-time status  : {goods_status}",
        "",
        "SUMMARY",
        "-" * 72,
        f"Normalized safe windows  : {len(normalized_windows):,}",
        f"Maintenance tasks        : {checks['tasks']:,}",
        f"Candidate block windows  : {checks['candidate_windows']:,}",
        f"Tasks with opportunities : {checks['tasks_with_candidates']:,}",
        f"Tasks without opportunity: {checks['tasks_without_candidates']:,}",
        f"Integrated opportunities : {checks['integrated_opportunities']:,}",
        f"Shadow opportunities     : {checks['shadow_opportunities']:,}",
        "",
        "TASK OPPORTUNITY STATUS",
        "-" * 72,
    ]

    for status, count in status_counts.items():
        lines.append(
            f"{status:<38} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "INTEGRITY / SAFETY",
            "-" * 72,
            (
                "Duplicate candidate IDs      : "
                f"{checks['duplicate_candidate_ids']:,}"
            ),
            (
                "Duplicate task summaries     : "
                f"{checks['duplicate_task_summaries']:,}"
            ),
            (
                "Missing task summaries       : "
                f"{checks['missing_task_summaries']:,}"
            ),
            (
                "Accepted train conflicts     : "
                f"{checks['candidate_train_conflicts']:,}"
            ),
            (
                "Accepted goods conflicts     : "
                f"{checks['candidate_goods_conflicts']:,}"
            ),
            "",
            "INTERPRETATION",
            "-" * 72,
            (
                "Task candidates come only from the previously validated safe "
                "window layer and are rechecked against exact available "
                "movement/event timing."
            ),
            (
                "Integrated and shadow outputs are still candidate coordination "
                "arrangements. They require exact resource timing, isolation/"
                "disconnection validation, detailed safety gates and human "
                "authorization."
            ),
            (
                "A task with no opportunity is not silently forced into the "
                "schedule; it remains available for later deferral, alternative "
                "planning or disruption/replanning logic."
            ),
            "",
            "NEXT V3 STAGE",
            "-" * 72,
            (
                "Run detailed safety/resource-time feasibility for candidate "
                "windows, then feed only validated windows into Resource-Aware "
                "Optimizer V3."
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
        "TrackEase V3.10 - Opportunity / Shadow Block Detector"
    )
    print("=" * 72)

    require_inputs()

    safe_window_file = (
        discover_safe_windows_file()
    )

    movement_file = (
        discover_weekly_movements_file()
    )

    goods_file = (
        discover_goods_file()
    )

    print(
        "\nDiscovered sources:"
    )
    print(
        f"Safe windows     : {safe_window_file}"
    )
    print(
        f"Weekly movements : {movement_file}"
    )
    print(
        f"COA/goods        : "
        f"{goods_file if goods_file is not None else 'NOT FOUND'}"
    )

    print(
        "\nLoading V3 planning layers..."
    )

    timing = pd.read_csv(
        TIMING_FILE,
        low_memory=False,
    )

    block_requirements = pd.read_csv(
        BLOCK_REQUIREMENTS_FILE,
        low_memory=False,
    )

    maintenance_value = pd.read_csv(
        MAINTENANCE_VALUE_FILE,
        low_memory=False,
    )

    operational_exposure = pd.read_csv(
        OPERATIONAL_EXPOSURE_FILE,
        low_memory=False,
    )

    compatibility = pd.read_csv(
        COMPATIBILITY_FILE,
        low_memory=False,
    )

    coordination_groups = pd.read_csv(
        COORDINATION_GROUPS_FILE,
        low_memory=False,
    )

    safe_windows_raw = pd.read_csv(
        safe_window_file,
        low_memory=False,
    )

    movements_raw = pd.read_csv(
        movement_file,
        low_memory=False,
    )

    goods_raw = (
        pd.read_csv(
            goods_file,
            low_memory=False,
        )
        if goods_file is not None
        else None
    )

    print(
        f"Tasks              : {len(timing):,}"
    )
    print(
        f"Safe windows raw   : {len(safe_windows_raw):,}"
    )
    print(
        f"Movement rows      : {len(movements_raw):,}"
    )
    print(
        f"Goods rows         : "
        f"{len(goods_raw):,}"
        if goods_raw is not None
        else
        "Goods rows         : 0"
    )

    print(
        "\nNormalizing validated safe windows..."
    )

    safe_schema = detect_safe_window_schema(
        safe_windows_raw
    )

    safe_windows = normalize_safe_windows(
        safe_windows_raw,
        safe_schema,
    )

    print(
        f"Normalized windows : {len(safe_windows):,}"
    )

    print(
        "Normalizing exact train/goods event timing..."
    )

    train_events, train_status = normalize_events(
        movements_raw,
        is_goods=False,
    )

    goods_events, goods_status = normalize_events(
        goods_raw,
        is_goods=True,
    )

    print(
        f"Train event timing  : {train_status}"
    )
    print(
        f"Goods event timing  : {goods_status}"
    )

    train_index = build_event_index(
        train_events
    )

    goods_index = build_event_index(
        goods_events
    )

    print(
        "\nGenerating exact task-level safe opportunities..."
    )

    (
        candidates,
        summaries,
    ) = build_task_candidates(
        timing,
        block_requirements,
        maintenance_value,
        operational_exposure,
        safe_windows,
        train_index,
        goods_index,
        goods_status,
    )

    print(
        "Detecting integrated-block opportunities..."
    )

    integrated = build_integrated_opportunities(
        coordination_groups,
        safe_windows,
        maintenance_value,
        train_index,
        goods_index,
    )

    print(
        "Aligning shadow/opportunity relationships..."
    )

    shadow = build_shadow_opportunities(
        compatibility,
        candidates,
    )

    checks = validate_outputs(
        timing,
        candidates,
        summaries,
        integrated,
        shadow,
    )

    candidates.to_csv(
        CANDIDATE_OUTPUT,
        index=False,
    )

    integrated.to_csv(
        INTEGRATED_OUTPUT,
        index=False,
    )

    shadow.to_csv(
        SHADOW_OUTPUT,
        index=False,
    )

    summaries.to_csv(
        SUMMARY_OUTPUT,
        index=False,
    )

    write_report(
        safe_window_file,
        movement_file,
        goods_file,
        train_status,
        goods_status,
        safe_windows,
        checks,
        summaries,
    )

    print(
        "\n"
        + "=" * 72
    )

    print(
        "V3.10 OPPORTUNITY DETECTOR COMPLETE"
    )

    print(
        "=" * 72
    )

    print(
        f"\nCandidate block windows     : "
        f"{checks['candidate_windows']:,}"
    )

    print(
        f"Tasks with opportunities    : "
        f"{checks['tasks_with_candidates']:,}"
    )

    print(
        f"Tasks without opportunities : "
        f"{checks['tasks_without_candidates']:,}"
    )

    print(
        f"Integrated opportunities    : "
        f"{checks['integrated_opportunities']:,}"
    )

    print(
        f"Shadow opportunities        : "
        f"{checks['shadow_opportunities']:,}"
    )

    print(
        "\nSafety / integrity:"
    )

    print(
        f"  Accepted train conflicts   : "
        f"{checks['candidate_train_conflicts']:,}"
    )

    print(
        f"  Accepted goods conflicts   : "
        f"{checks['candidate_goods_conflicts']:,}"
    )

    print(
        f"  Duplicate candidate IDs    : "
        f"{checks['duplicate_candidate_ids']:,}"
    )

    print(
        f"  Missing task summaries     : "
        f"{checks['missing_task_summaries']:,}"
    )

    print(
        "\nOutputs:"
    )

    print(
        f"  {CANDIDATE_OUTPUT}"
    )

    print(
        f"  {INTEGRATED_OUTPUT}"
    )

    print(
        f"  {SHADOW_OUTPUT}"
    )

    print(
        f"  {SUMMARY_OUTPUT}"
    )

    print(
        f"  {REPORT_OUTPUT}"
    )

    print(
        "\nTrackEase V3 now has exact safe candidate windows plus "
        "integrated and shadow/opportunity candidates ready for detailed "
        "resource/safety validation."
    )


if __name__ == "__main__":
    main()
