"""
TrackEase - Safe Block Rescheduling Engine

Purpose:
    Generate safe alternative maintenance block times when a human planner
    requests rescheduling of an existing TrackEase recommendation.

Inputs:
    data/processed/block_decision_queue.csv
    data/processed/scored_block_windows.csv
    data/processed/block_decision_history.csv

Outputs:
    data/processed/reschedule_alternatives.csv
    data/processed/reschedule_report.txt

Commands:
    preview <recommendation_id>
        Generate alternatives for one recommendation without changing the
        human-decision queue.

    generate
        Generate alternatives for every recommendation currently marked
        RESCHEDULE_REQUESTED.

    apply <alternative_id>
        Apply one previously generated safe alternative to the decision queue.
        The recommendation returns to PENDING because the new time still
        requires explicit human approval.

Safety rules:
    - Same railway section only.
    - Full maintenance duration must fit.
    - Alternatives come only from validated scored windows.
    - Existing non-rejected recommendations reserve capacity.
    - The recommendation being rescheduled does not reserve its old slot
      while alternatives are searched.
    - No arbitrary time is invented.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

QUEUE_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_decision_queue.csv"
)

WINDOWS_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "scored_block_windows.csv"
)

HISTORY_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_decision_history.csv"
)

ALTERNATIVES_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "reschedule_alternatives.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "reschedule_report.txt"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

IMPACT_WEIGHT = 0.75
FIT_WEIGHT = 0.25

DEFAULT_ALTERNATIVES = 5

DAY_NAMES = [
    "Mon",
    "Tue",
    "Wed",
    "Thu",
    "Fri",
    "Sat",
    "Sun",
]

HISTORY_COLUMNS = [
    "history_id",
    "recommendation_id",
    "planning_task_id",
    "previous_status",
    "new_status",
    "decision_by",
    "decision_note",
    "decision_timestamp",
    "decision_version",
]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def now_local_iso():
    """Return local machine time for audit logging."""

    return datetime.now().astimezone().isoformat(
        timespec="seconds"
    )


def atomic_write_csv(df, destination):
    """Write CSV through a temporary file and replace the destination."""

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = destination.with_suffix(
        destination.suffix + ".tmp"
    )

    df.to_csv(
        temporary,
        index=False,
    )

    temporary.replace(
        destination
    )


def require_columns(df, required_columns, dataset_name):
    """Raise a clear schema error."""

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(sorted(missing))
        )


def weekly_minute_to_label(value):
    """Convert recurring-week minute into weekday and HH:MM."""

    value = int(value)

    if value == MINUTES_PER_WEEK:
        return "Mon", "00:00"

    value %= MINUTES_PER_WEEK

    day_index = value // MINUTES_PER_DAY
    minute_of_day = value % MINUTES_PER_DAY

    hour = minute_of_day // 60
    minute = minute_of_day % 60

    return (
        DAY_NAMES[day_index],
        f"{hour:02d}:{minute:02d}",
    )


def load_history():
    """Load existing audit history or create an empty history table."""

    if not HISTORY_FILE.exists():
        return pd.DataFrame(
            columns=HISTORY_COLUMNS
        )

    history = pd.read_csv(
        HISTORY_FILE
    )

    for column in HISTORY_COLUMNS:
        if column not in history.columns:
            history[column] = pd.NA

    return history[
        HISTORY_COLUMNS
    ]


# ---------------------------------------------------------------------------
# Interval helpers
# ---------------------------------------------------------------------------

def merge_intervals(intervals):
    """Merge overlapping or touching occupancy intervals."""

    if not intervals:
        return []

    intervals = sorted(
        intervals,
        key=lambda item: item[0],
    )

    merged = [
        list(intervals[0])
    ]

    for start, end in intervals[1:]:

        previous = merged[-1]

        if start <= previous[1]:
            previous[1] = max(
                previous[1],
                end,
            )
        else:
            merged.append(
                [start, end]
            )

    return [
        (int(start), int(end))
        for start, end in merged
    ]


def subtract_intervals(
    window_start,
    window_end,
    occupied_intervals,
):
    """Return free fragments after removing maintenance occupancy."""

    fragments = [
        (
            int(window_start),
            int(window_end),
        )
    ]

    for blocked_start, blocked_end in occupied_intervals:

        updated = []

        for free_start, free_end in fragments:

            if (
                blocked_end <= free_start
                or blocked_start >= free_end
            ):
                updated.append(
                    (
                        free_start,
                        free_end,
                    )
                )
                continue

            if blocked_start > free_start:
                updated.append(
                    (
                        free_start,
                        min(
                            blocked_start,
                            free_end,
                        ),
                    )
                )

            if blocked_end < free_end:
                updated.append(
                    (
                        max(
                            blocked_end,
                            free_start,
                        ),
                        free_end,
                    )
                )

        fragments = updated

        if not fragments:
            break

    return fragments


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def load_sources():
    """Load and validate decision queue and scored windows."""

    for file_path, label in [
        (
            QUEUE_FILE,
            "Human decision queue",
        ),
        (
            WINDOWS_FILE,
            "Scored safe windows",
        ),
    ]:

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n{file_path}"
            )

    queue = pd.read_csv(
        QUEUE_FILE
    )

    windows = pd.read_csv(
        WINDOWS_FILE
    )

    require_columns(
        queue,
        {
            "recommendation_id",
            "planning_task_id",
            "section_id",
            "required_minutes",
            "scheduled_start_minute",
            "scheduled_end_minute",
            "scheduled_start_day",
            "scheduled_start_time",
            "scheduled_end_day",
            "scheduled_end_time",
            "trackease_priority_score",
            "trackease_priority_level",
            "decision_status",
            "decision_version",
            "reschedule_required",
        },
        "Human decision queue",
    )

    require_columns(
        windows,
        {
            "adjusted_window_id",
            "source_window_id",
            "section_id",
            "window_start_minute",
            "window_end_minute",
            "duration_minutes",
            "operational_impact_score",
            "operational_impact_level",
            "goods_forecast_present",
            "coa_adjusted",
            "weekly_train_movements",
        },
        "Scored safe windows",
    )

    return queue, windows


# ---------------------------------------------------------------------------
# Alternative generation
# ---------------------------------------------------------------------------

def occupied_by_other_recommendations(
    queue,
    section_id,
    current_recommendation_id,
):
    """
    Return maintenance occupancy from all other non-rejected recommendations
    on the same railway section.
    """

    active = queue[
        (
            queue["section_id"]
            == section_id
        )
        & (
            queue["recommendation_id"]
            .astype(str)
            != str(current_recommendation_id)
        )
        & (
            queue["decision_status"]
            .astype(str)
            != "REJECTED"
        )
    ].copy()

    intervals = []

    for row in active.itertuples():

        start = pd.to_numeric(
            row.scheduled_start_minute,
            errors="coerce",
        )

        end = pd.to_numeric(
            row.scheduled_end_minute,
            errors="coerce",
        )

        if pd.isna(start) or pd.isna(end):
            continue

        start = int(start)
        end = int(end)

        if end > start:
            intervals.append(
                (
                    start,
                    end,
                )
            )

    return merge_intervals(
        intervals
    )


def generate_for_recommendation(
    queue,
    windows,
    recommendation_id,
    max_alternatives,
):
    """Generate ranked safe alternatives for one recommendation."""

    matches = queue[
        queue["recommendation_id"]
        .astype(str)
        == str(recommendation_id)
    ]

    if len(matches) == 0:
        raise ValueError(
            f"Recommendation not found: {recommendation_id}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            f"Recommendation ID is not unique: {recommendation_id}"
        )

    task = matches.iloc[0]

    required = int(
        pd.to_numeric(
            task["required_minutes"],
            errors="raise",
        )
    )

    section_id = task["section_id"]

    original_start = int(
        pd.to_numeric(
            task["scheduled_start_minute"],
            errors="raise",
        )
    )

    original_end = int(
        pd.to_numeric(
            task["scheduled_end_minute"],
            errors="raise",
        )
    )

    occupied = occupied_by_other_recommendations(
        queue,
        section_id,
        recommendation_id,
    )

    section_windows = windows[
        windows["section_id"]
        == section_id
    ].copy()

    alternatives = []

    for window in section_windows.itertuples():

        window_start = int(
            window.window_start_minute
        )

        window_end = int(
            window.window_end_minute
        )

        if (
            window_end
            - window_start
            < required
        ):
            continue

        fragments = subtract_intervals(
            window_start,
            window_end,
            occupied,
        )

        for fragment_start, fragment_end in fragments:

            fragment_duration = (
                fragment_end
                - fragment_start
            )

            if fragment_duration < required:
                continue

            proposed_start = int(
                fragment_start
            )

            proposed_end = (
                proposed_start
                + required
            )

            # Do not return the exact original slot as an alternative.
            if (
                proposed_start == original_start
                and proposed_end == original_end
            ):
                continue

            slack_after = (
                fragment_duration
                - required
            )

            fit_penalty = (
                slack_after
                / fragment_duration
                * 100
                if fragment_duration > 0
                else 100
            )

            impact = float(
                window.operational_impact_score
            )

            candidate_cost = (
                IMPACT_WEIGHT * impact
                + FIT_WEIGHT * fit_penalty
            )

            start_day, start_time = (
                weekly_minute_to_label(
                    proposed_start
                )
            )

            end_day, end_time = (
                weekly_minute_to_label(
                    proposed_end
                )
            )

            alternatives.append(
                {
                    "recommendation_id":
                        recommendation_id,

                    "planning_task_id":
                        task["planning_task_id"],

                    "section_id":
                        section_id,

                    "trackease_priority_score":
                        float(
                            task[
                                "trackease_priority_score"
                            ]
                        ),

                    "trackease_priority_level":
                        task[
                            "trackease_priority_level"
                        ],

                    "required_minutes":
                        required,

                    "original_start_minute":
                        original_start,

                    "original_end_minute":
                        original_end,

                    "adjusted_window_id":
                        window.adjusted_window_id,

                    "source_window_id":
                        window.source_window_id,

                    "proposed_start_minute":
                        proposed_start,

                    "proposed_end_minute":
                        proposed_end,

                    "proposed_start_day":
                        start_day,

                    "proposed_start_time":
                        start_time,

                    "proposed_end_day":
                        end_day,

                    "proposed_end_time":
                        end_time,

                    "free_fragment_minutes":
                        fragment_duration,

                    "remaining_after_minutes":
                        slack_after,

                    "operational_impact_score":
                        impact,

                    "operational_impact_level":
                        window.operational_impact_level,

                    "weekly_train_movements":
                        int(
                            window.weekly_train_movements
                        ),

                    "goods_forecast_present":
                        int(
                            window.goods_forecast_present
                        ),

                    "coa_adjusted_window":
                        int(
                            window.coa_adjusted
                        ),

                    "fit_penalty":
                        round(
                            fit_penalty,
                            2,
                        ),

                    "alternative_cost":
                        round(
                            candidate_cost,
                            2,
                        ),

                    "alternative_score":
                        round(
                            max(
                                0.0,
                                min(
                                    100.0,
                                    100.0
                                    - candidate_cost,
                                ),
                            ),
                            2,
                        ),
                }
            )

    alternatives.sort(
        key=lambda item: (
            item["alternative_cost"],
            item["operational_impact_score"],
            item["remaining_after_minutes"],
            item["proposed_start_minute"],
            item["adjusted_window_id"],
        )
    )

    return alternatives[
        :max_alternatives
    ]


def write_generation_report(
    mode,
    requested_count,
    alternatives,
):
    """Write reschedule-generation summary."""

    recommendations_with_options = (
        alternatives[
            "recommendation_id"
        ].nunique()
        if not alternatives.empty
        else 0
    )

    report = [
        "=" * 72,
        "TrackEase Safe Reschedule Report",
        "=" * 72,
        "",
        f"Generation mode               : {mode}",
        f"Recommendations evaluated     : {requested_count:,}",
        f"Recommendations with options  : {recommendations_with_options:,}",
        f"Alternative options generated : {len(alternatives):,}",
        "",
        "SAFETY",
        "-" * 72,
        (
            "Alternatives are generated only from validated scored "
            "maintenance windows."
        ),
        (
            "Existing non-rejected recommendations reserve capacity."
        ),
        (
            "The recommendation being rescheduled does not reserve its "
            "old slot while alternatives are evaluated."
        ),
        (
            "No arbitrary time is generated outside validated windows."
        ),
        "",
        "RANKING",
        "-" * 72,
        (
            f"{IMPACT_WEIGHT:.0%} operational impact + "
            f"{FIT_WEIGHT:.0%} fit/slack penalty."
        ),
        "Lower alternative cost is preferred.",
        "",
        "HUMAN-IN-THE-LOOP",
        "-" * 72,
        (
            "Applying an alternative returns the recommendation to PENDING. "
            "The planner must explicitly approve the replacement."
        ),
    ]

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )


def save_alternatives(
    all_rows,
    mode,
    requested_count,
):
    """Save generated alternatives and report."""

    alternatives = pd.DataFrame(
        all_rows
    )

    if not alternatives.empty:

        alternatives.insert(
            0,
            "alternative_id",
            [
                f"ALT-{number:06d}"
                for number in range(
                    1,
                    len(alternatives) + 1
                )
            ],
        )

        alternatives["generation_mode"] = mode
        alternatives["generated_at"] = now_local_iso()

    else:

        alternatives = pd.DataFrame(
            columns=[
                "alternative_id",
                "recommendation_id",
                "planning_task_id",
                "section_id",
                "trackease_priority_score",
                "trackease_priority_level",
                "required_minutes",
                "original_start_minute",
                "original_end_minute",
                "adjusted_window_id",
                "source_window_id",
                "proposed_start_minute",
                "proposed_end_minute",
                "proposed_start_day",
                "proposed_start_time",
                "proposed_end_day",
                "proposed_end_time",
                "free_fragment_minutes",
                "remaining_after_minutes",
                "operational_impact_score",
                "operational_impact_level",
                "weekly_train_movements",
                "goods_forecast_present",
                "coa_adjusted_window",
                "fit_penalty",
                "alternative_cost",
                "alternative_score",
                "generation_mode",
                "generated_at",
            ]
        )

    atomic_write_csv(
        alternatives,
        ALTERNATIVES_FILE,
    )

    write_generation_report(
        mode=mode,
        requested_count=requested_count,
        alternatives=alternatives,
    )

    return alternatives


def generate_alternatives(
    recommendation_ids,
    mode,
    max_alternatives,
):
    """Generate alternatives for one or more recommendations."""

    queue, windows = load_sources()

    all_rows = []

    for recommendation_id in recommendation_ids:

        rows = generate_for_recommendation(
            queue=queue,
            windows=windows,
            recommendation_id=recommendation_id,
            max_alternatives=max_alternatives,
        )

        all_rows.extend(
            rows
        )

    alternatives = save_alternatives(
        all_rows=all_rows,
        mode=mode,
        requested_count=len(recommendation_ids),
    )

    print("=" * 72)
    print("TrackEase - Safe Reschedule Alternatives")
    print("=" * 72)

    print(
        f"\nRecommendations evaluated : "
        f"{len(recommendation_ids):,}"
    )

    print(
        f"Alternatives generated    : "
        f"{len(alternatives):,}"
    )

    if not alternatives.empty:

        print("\nTop alternatives:")

        columns = [
            "alternative_id",
            "recommendation_id",
            "proposed_start_day",
            "proposed_start_time",
            "proposed_end_day",
            "proposed_end_time",
            "operational_impact_score",
            "alternative_score",
        ]

        print(
            alternatives[
                columns
            ]
            .head(10)
            .to_string(
                index=False
            )
        )

    print("\nOutputs:")
    print(
        f"  {ALTERNATIVES_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )


# ---------------------------------------------------------------------------
# Apply a safe alternative
# ---------------------------------------------------------------------------

def apply_alternative(
    alternative_id,
    decision_by,
    note,
):
    """
    Apply one generated alternative.

    The recommendation returns to PENDING because the replacement block
    still requires explicit approval.
    """

    if not ALTERNATIVES_FILE.exists():
        raise FileNotFoundError(
            "No reschedule alternatives file exists. "
            "Generate alternatives first."
        )

    queue, _ = load_sources()

    alternatives = pd.read_csv(
        ALTERNATIVES_FILE
    )

    matches = alternatives[
        alternatives[
            "alternative_id"
        ].astype(str)
        == str(alternative_id)
    ]

    if len(matches) == 0:
        raise ValueError(
            f"Alternative not found: {alternative_id}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            f"Alternative ID is not unique: {alternative_id}"
        )

    alternative = matches.iloc[0]

    recommendation_id = str(
        alternative[
            "recommendation_id"
        ]
    )

    queue_matches = (
        queue[
            "recommendation_id"
        ].astype(str)
        == recommendation_id
    )

    if int(
        queue_matches.sum()
    ) != 1:
        raise RuntimeError(
            f"Decision queue does not contain exactly one {recommendation_id}."
        )

    index = queue.index[
        queue_matches
    ][0]

    current_status = str(
        queue.at[
            index,
            "decision_status",
        ]
    )

    if current_status != "RESCHEDULE_REQUESTED":
        raise ValueError(
            (
                f"{recommendation_id} is {current_status}, not "
                "RESCHEDULE_REQUESTED. Request rescheduling before "
                "applying an alternative."
            )
        )

    previous_version = pd.to_numeric(
        queue.at[
            index,
            "decision_version",
        ],
        errors="coerce",
    )

    if pd.isna(previous_version):
        previous_version = 0

    new_version = int(
        previous_version
    ) + 1

    timestamp = now_local_iso()

    old_block = (
        f"{queue.at[index, 'scheduled_start_day']} "
        f"{queue.at[index, 'scheduled_start_time']} -> "
        f"{queue.at[index, 'scheduled_end_day']} "
        f"{queue.at[index, 'scheduled_end_time']}"
    )

    new_block = (
        f"{alternative['proposed_start_day']} "
        f"{alternative['proposed_start_time']} -> "
        f"{alternative['proposed_end_day']} "
        f"{alternative['proposed_end_time']}"
    )

    # -----------------------------------------------------------------------
    # Update recommendation timing and selected-window metadata.
    # -----------------------------------------------------------------------

    queue.at[
        index,
        "scheduled_start_minute",
    ] = int(
        alternative[
            "proposed_start_minute"
        ]
    )

    queue.at[
        index,
        "scheduled_end_minute",
    ] = int(
        alternative[
            "proposed_end_minute"
        ]
    )

    queue.at[
        index,
        "scheduled_start_day",
    ] = alternative[
        "proposed_start_day"
    ]

    queue.at[
        index,
        "scheduled_start_time",
    ] = alternative[
        "proposed_start_time"
    ]

    queue.at[
        index,
        "scheduled_end_day",
    ] = alternative[
        "proposed_end_day"
    ]

    queue.at[
        index,
        "scheduled_end_time",
    ] = alternative[
        "proposed_end_time"
    ]

    if "adjusted_window_id" in queue.columns:
        queue.at[
            index,
            "adjusted_window_id",
        ] = alternative[
            "adjusted_window_id"
        ]

    if "source_window_id" in queue.columns:
        queue.at[
            index,
            "source_window_id",
        ] = alternative[
            "source_window_id"
        ]

    if "operational_impact_score" in queue.columns:
        queue.at[
            index,
            "operational_impact_score",
        ] = float(
            alternative[
                "operational_impact_score"
            ]
        )

    if "operational_impact_level" in queue.columns:
        queue.at[
            index,
            "operational_impact_level",
        ] = alternative[
            "operational_impact_level"
        ]

    # The replacement now requires explicit human approval again.
    queue.at[
        index,
        "decision_status",
    ] = "PENDING"

    queue.at[
        index,
        "reschedule_required",
    ] = 0

    queue.at[
        index,
        "decision_by",
    ] = decision_by

    queue.at[
        index,
        "decision_note",
    ] = note

    queue.at[
        index,
        "decision_timestamp",
    ] = timestamp

    queue.at[
        index,
        "decision_version",
    ] = new_version

    # Refresh human-readable display fields when present.
    if "block_display" in queue.columns:
        queue.at[
            index,
            "block_display",
        ] = (
            f"{alternative['proposed_start_day']} "
            f"{alternative['proposed_start_time']} → "
            f"{alternative['proposed_end_day']} "
            f"{alternative['proposed_end_time']}"
        )

    # -----------------------------------------------------------------------
    # Append audit history.
    # -----------------------------------------------------------------------

    history = load_history()

    history_note = (
        f"Safe reschedule applied: {old_block} -> {new_block}. "
        f"Alternative {alternative_id}."
    )

    if note:
        history_note += (
            f" Planner note: {note}"
        )

    history_row = {
        "history_id":
            f"HIST-{len(history) + 1:07d}",

        "recommendation_id":
            recommendation_id,

        "planning_task_id":
            queue.at[
                index,
                "planning_task_id",
            ],

        "previous_status":
            "RESCHEDULE_REQUESTED",

        "new_status":
            "PENDING",

        "decision_by":
            decision_by,

        "decision_note":
            history_note,

        "decision_timestamp":
            timestamp,

        "decision_version":
            new_version,
    }

    history = pd.concat(
        [
            history,
            pd.DataFrame(
                [
                    history_row
                ]
            ),
        ],
        ignore_index=True,
    )

    atomic_write_csv(
        queue,
        QUEUE_FILE,
    )

    atomic_write_csv(
        history,
        HISTORY_FILE,
    )

    print("=" * 72)
    print("TrackEase - Safe Reschedule Applied")
    print("=" * 72)

    print(
        f"\nRecommendation : {recommendation_id}"
    )

    print(
        f"Alternative    : {alternative_id}"
    )

    print(
        f"Old block      : {old_block}"
    )

    print(
        f"New block      : {new_block}"
    )

    print(
        "Decision state : PENDING"
    )

    print(
        "\nThe replacement remains pending until a human planner "
        "explicitly approves it."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    """Build command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "TrackEase safe block rescheduling engine."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    preview = subparsers.add_parser(
        "preview",
        help="Generate alternatives for one recommendation.",
    )

    preview.add_argument(
        "recommendation_id",
    )

    preview.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_ALTERNATIVES,
    )

    generate = subparsers.add_parser(
        "generate",
        help=(
            "Generate alternatives for all RESCHEDULE_REQUESTED "
            "recommendations."
        ),
    )

    generate.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_ALTERNATIVES,
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Apply one generated safe alternative.",
    )

    apply_parser.add_argument(
        "alternative_id",
    )

    apply_parser.add_argument(
        "--by",
        dest="decision_by",
        default="Human Planner",
    )

    apply_parser.add_argument(
        "--note",
        default="",
    )

    return parser.parse_args()


def main():
    """CLI entry point."""

    args = parse_args()

    if args.command == "preview":

        generate_alternatives(
            recommendation_ids=[
                args.recommendation_id
            ],
            mode="PREVIEW",
            max_alternatives=max(
                1,
                args.limit,
            ),
        )

        return

    if args.command == "generate":

        queue, _ = load_sources()

        ids = (
            queue.loc[
                queue[
                    "decision_status"
                ].astype(str)
                == "RESCHEDULE_REQUESTED",
                "recommendation_id",
            ]
            .astype(str)
            .tolist()
        )

        if not ids:

            print(
                "No recommendations are currently marked "
                "RESCHEDULE_REQUESTED."
            )

            return

        generate_alternatives(
            recommendation_ids=ids,
            mode="RESCHEDULE_REQUESTED",
            max_alternatives=max(
                1,
                args.limit,
            ),
        )

        return

    if args.command == "apply":

        apply_alternative(
            alternative_id=args.alternative_id,
            decision_by=args.decision_by,
            note=args.note,
        )

        return


if __name__ == "__main__":
    main()
