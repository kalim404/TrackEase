"""
TrackEase - Human Block Decision Workflow

Purpose:
    Provide a persistent human-in-the-loop decision layer for validated
    TrackEase weekly block recommendations.

Inputs:
    data/processed/weekly_block_plan.csv
    data/processed/monthly_block_plan.csv

Persistent outputs:
    data/processed/block_decision_queue.csv
    data/processed/block_decision_history.csv
    data/processed/approval_workflow_report.txt

Supported commands:
    initialize
        Create or refresh the decision queue while preserving existing
        human decisions for recommendation IDs that still exist.

    summary
        Show current decision-state counts.

    approve <recommendation_id>
        Mark a recommendation APPROVED.

    reject <recommendation_id>
        Mark a recommendation REJECTED.

    reschedule <recommendation_id>
        Mark a recommendation RESCHEDULE_REQUESTED.
        This does NOT invent a new time. A later safe-reschedule engine
        will generate alternative validated windows.

Important:
    - TrackEase remains decision support.
    - No recommendation is treated as sanctioned until a human approves it.
    - Decision history is append-only for auditability.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import shutil

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

WEEKLY_PLAN_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "weekly_block_plan.csv"
)

MONTHLY_PLAN_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "monthly_block_plan.csv"
)

QUEUE_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_decision_queue.csv"
)

HISTORY_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_decision_history.csv"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "approval_workflow_report.txt"
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VALID_DECISIONS = {
    "PENDING",
    "APPROVED",
    "REJECTED",
    "RESCHEDULE_REQUESTED",
}

ACTION_TO_STATUS = {
    "approve": "APPROVED",
    "reject": "REJECTED",
    "reschedule": "RESCHEDULE_REQUESTED",
}

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
# Helpers
# ---------------------------------------------------------------------------

def require_columns(
    df: pd.DataFrame,
    required_columns: set[str],
    dataset_name: str,
) -> None:
    """Raise a clear schema error."""

    missing = (
        required_columns
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(sorted(missing))
        )


def now_local_iso() -> str:
    """Return local machine time for the audit trail."""

    return datetime.now().astimezone().isoformat(
        timespec="seconds"
    )


def atomic_write_csv(
    df: pd.DataFrame,
    destination: Path,
) -> None:
    """
    Write a CSV through a temporary file and replace the destination.

    This reduces the chance of leaving a partially written queue.
    """

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


def load_history() -> pd.DataFrame:
    """Load or initialize the append-only decision history."""

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


def build_report(
    queue: pd.DataFrame,
    history: pd.DataFrame,
) -> None:
    """Create a readable approval-workflow report."""

    status_counts = (
        queue[
            "decision_status"
        ]
        .value_counts()
    )

    priority_pending = (
        queue[
            queue[
                "decision_status"
            ]
            .isin(
                [
                    "PENDING",
                    "RESCHEDULE_REQUESTED",
                ]
            )
        ][
            "trackease_priority_level"
        ]
        .value_counts()
    )

    report = [
        "=" * 72,
        "TrackEase Human Decision Workflow Report",
        "=" * 72,
        "",
        f"Decision queue records       : {len(queue):,}",
        f"Decision history events      : {len(history):,}",
        "",
        "DECISION STATES",
        "-" * 72,
    ]

    for status in [
        "PENDING",
        "APPROVED",
        "REJECTED",
        "RESCHEDULE_REQUESTED",
    ]:
        report.append(
            f"{status:<28} "
            f"{int(status_counts.get(status, 0)):>8,}"
        )

    report.extend(
        [
            "",
            "PENDING / RESCHEDULE PRIORITIES",
            "-" * 72,
        ]
    )

    for priority in [
        "Critical",
        "High",
        "Medium",
        "Low",
    ]:
        report.append(
            f"{priority:<28} "
            f"{int(priority_pending.get(priority, 0)):>8,}"
        )

    report.extend(
        [
            "",
            "WORKFLOW",
            "-" * 72,
            "PENDING -> APPROVED",
            "PENDING -> REJECTED",
            "PENDING -> RESCHEDULE_REQUESTED",
            (
                "A reschedule request does not create an arbitrary time. "
                "A separate safe-reschedule engine will search validated windows."
            ),
            "",
            "AUDITABILITY",
            "-" * 72,
            (
                "Every decision change is appended to "
                "block_decision_history.csv."
            ),
            (
                "The decision queue stores the latest state for each "
                "recommendation."
            ),
            "",
            "SAFETY NOTE",
            "-" * 72,
            (
                "TrackEase recommendations remain decision-support outputs "
                "and are not official railway block sanctions."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )


def validate_queue(queue: pd.DataFrame) -> None:
    """Validate queue integrity before writing."""

    if queue[
        "recommendation_id"
    ].duplicated().any():
        raise RuntimeError(
            "Duplicate recommendation IDs found in decision queue."
        )

    invalid_status = (
        ~queue[
            "decision_status"
        ].isin(
            VALID_DECISIONS
        )
    )

    if invalid_status.any():
        values = sorted(
            queue.loc[
                invalid_status,
                "decision_status",
            ]
            .astype(str)
            .unique()
            .tolist()
        )

        raise RuntimeError(
            "Invalid decision states found: "
            + ", ".join(values)
        )


# ---------------------------------------------------------------------------
# Queue initialization / refresh
# ---------------------------------------------------------------------------

def initialize_queue() -> None:
    """
    Create or refresh the human decision queue.

    Existing human decisions are preserved when recommendation IDs still
    exist in the latest validated weekly plan.
    """

    print("=" * 72)
    print("TrackEase - Initialize Human Decision Workflow")
    print("=" * 72)

    for file_path, label in [
        (
            WEEKLY_PLAN_FILE,
            "Weekly block plan",
        ),
        (
            MONTHLY_PLAN_FILE,
            "Monthly block plan",
        ),
    ]:
        print(f"\n{label}:")
        print(f"  {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(
                f"{label} file not found:\n{file_path}"
            )

        print("  ✓ Found")

    weekly = pd.read_csv(
        WEEKLY_PLAN_FILE
    )

    monthly = pd.read_csv(
        MONTHLY_PLAN_FILE
    )

    require_columns(
        weekly,
        {
            "recommendation_id",
            "planning_task_id",
            "planning_task_type",
            "section_id",
            "departments_involved",
            "trackease_priority_score",
            "trackease_priority_level",
            "required_minutes",
            "scheduled_start_day",
            "scheduled_start_time",
            "scheduled_end_day",
            "scheduled_end_time",
            "operational_impact_score",
            "operational_impact_level",
            "estimated_minutes_saved",
            "recommendation_explanation",
        },
        "Weekly block plan",
    )

    require_columns(
        monthly,
        {
            "recommendation_id",
            "month_week",
            "month_week_label",
        },
        "Monthly block plan",
    )

    monthly_reference = (
        monthly[
            [
                "recommendation_id",
                "month_week",
                "month_week_label",
            ]
        ]
        .drop_duplicates(
            subset=[
                "recommendation_id"
            ]
        )
    )

    queue = weekly.merge(
        monthly_reference,
        on="recommendation_id",
        how="left",
        validate="one_to_one",
    )

    if queue[
        "month_week"
    ].isna().any():
        missing = int(
            queue[
                "month_week"
            ].isna().sum()
        )

        raise RuntimeError(
            f"{missing:,} weekly recommendations are missing "
            "monthly-plan mapping."
        )

    # -----------------------------------------------------------------------
    # Default human-decision state.
    # -----------------------------------------------------------------------

    queue[
        "decision_status"
    ] = "PENDING"

    queue[
        "decision_by"
    ] = ""

    queue[
        "decision_note"
    ] = ""

    queue[
        "decision_timestamp"
    ] = ""

    queue[
        "decision_version"
    ] = 0

    queue[
        "reschedule_required"
    ] = 0

    # -----------------------------------------------------------------------
    # Preserve existing human decisions across a safe refresh.
    # -----------------------------------------------------------------------

    preserved_count = 0

    if QUEUE_FILE.exists():

        existing = pd.read_csv(
            QUEUE_FILE
        )

        preserve_columns = [
            "recommendation_id",
            "decision_status",
            "decision_by",
            "decision_note",
            "decision_timestamp",
            "decision_version",
            "reschedule_required",
        ]

        if set(
            preserve_columns
        ).issubset(
            existing.columns
        ):

            preserved = existing[
                preserve_columns
            ].copy()

            renamed = {
                column:
                    f"_existing_{column}"
                for column in preserve_columns
                if column != "recommendation_id"
            }

            preserved = preserved.rename(
                columns=renamed
            )

            queue = queue.merge(
                preserved,
                on="recommendation_id",
                how="left",
                validate="one_to_one",
            )

            has_existing = (
                queue[
                    "_existing_decision_status"
                ]
                .notna()
            )

            preserved_count = int(
                has_existing.sum()
            )

            for column in [
                "decision_status",
                "decision_by",
                "decision_note",
                "decision_timestamp",
                "decision_version",
                "reschedule_required",
            ]:

                existing_column = (
                    f"_existing_{column}"
                )

                queue.loc[
                    has_existing,
                    column,
                ] = queue.loc[
                    has_existing,
                    existing_column,
                ]

                queue = queue.drop(
                    columns=[
                        existing_column
                    ]
                )

    queue[
        "decision_version"
    ] = pd.to_numeric(
        queue[
            "decision_version"
        ],
        errors="coerce",
    ).fillna(
        0
    ).astype(
        int
    )

    queue[
        "reschedule_required"
    ] = pd.to_numeric(
        queue[
            "reschedule_required"
        ],
        errors="coerce",
    ).fillna(
        0
    ).astype(
        int
    )

    queue[
        "month_week"
    ] = pd.to_numeric(
        queue[
            "month_week"
        ],
        errors="raise",
    ).astype(
        int
    )

    validate_queue(
        queue
    )

    queue = queue.sort_values(
        [
            "month_week",
            "trackease_priority_score",
            "scheduled_start_day",
            "scheduled_start_time",
            "recommendation_id",
        ],
        ascending=[
            True,
            False,
            True,
            True,
            True,
        ],
    ).reset_index(
        drop=True
    )

    atomic_write_csv(
        queue,
        QUEUE_FILE,
    )

    history = load_history()

    if not HISTORY_FILE.exists():
        atomic_write_csv(
            history,
            HISTORY_FILE,
        )

    build_report(
        queue,
        history,
    )

    print("\n" + "=" * 72)
    print("HUMAN DECISION WORKFLOW INITIALIZED")
    print("=" * 72)

    print(
        f"\nQueue records       : {len(queue):,}"
    )

    print(
        f"Existing decisions preserved : {preserved_count:,}"
    )

    print(
        f"History events      : {len(history):,}"
    )

    print("\nOutputs:")
    print(
        f"  {QUEUE_FILE}"
    )
    print(
        f"  {HISTORY_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nAll recommendations begin or remain in an explicit "
        "human-decision state."
    )


# ---------------------------------------------------------------------------
# Decision updates
# ---------------------------------------------------------------------------

def update_decision(
    recommendation_id: str,
    new_status: str,
    decision_by: str,
    note: str,
) -> None:
    """Apply one human decision and append an audit event."""

    if not QUEUE_FILE.exists():
        raise FileNotFoundError(
            "Decision queue does not exist. Run:\n"
            "python src\\planning\\manage_block_decisions.py initialize"
        )

    if new_status not in VALID_DECISIONS:
        raise ValueError(
            f"Unsupported decision status: {new_status}"
        )

    queue = pd.read_csv(
        QUEUE_FILE
    )

    validate_queue(
        queue
    )

    matches = (
        queue[
            "recommendation_id"
        ].astype(str)
        == str(
            recommendation_id
        )
    )

    match_count = int(
        matches.sum()
    )

    if match_count == 0:
        raise ValueError(
            f"Recommendation not found: {recommendation_id}"
        )

    if match_count > 1:
        raise RuntimeError(
            f"Recommendation ID is not unique: {recommendation_id}"
        )

    index = queue.index[
        matches
    ][0]

    previous_status = str(
        queue.at[
            index,
            "decision_status",
        ]
    )

    if previous_status == new_status:
        print(
            f"Recommendation {recommendation_id} is already {new_status}."
        )
        return

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

    queue.at[
        index,
        "decision_status",
    ] = new_status

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

    queue.at[
        index,
        "reschedule_required",
    ] = int(
        new_status
        == "RESCHEDULE_REQUESTED"
    )

    validate_queue(
        queue
    )

    history = load_history()

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
            previous_status,

        "new_status":
            new_status,

        "decision_by":
            decision_by,

        "decision_note":
            note,

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

    build_report(
        queue,
        history,
    )

    print("=" * 72)
    print("TrackEase - Human Decision Updated")
    print("=" * 72)

    print(
        f"\nRecommendation : {recommendation_id}"
    )

    print(
        f"Previous state : {previous_status}"
    )

    print(
        f"New state      : {new_status}"
    )

    print(
        f"Decision by    : {decision_by}"
    )

    print(
        f"Version        : {new_version}"
    )

    if new_status == "RESCHEDULE_REQUESTED":
        print(
            "\nNo arbitrary replacement time has been created. "
            "The safe-reschedule engine must generate alternatives."
        )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def show_summary() -> None:
    """Print current human decision-state summary."""

    if not QUEUE_FILE.exists():
        raise FileNotFoundError(
            "Decision queue does not exist. Run initialize first."
        )

    queue = pd.read_csv(
        QUEUE_FILE
    )

    validate_queue(
        queue
    )

    history = load_history()

    build_report(
        queue,
        history,
    )

    counts = (
        queue[
            "decision_status"
        ]
        .value_counts()
    )

    print("=" * 72)
    print("TrackEase - Human Decision Summary")
    print("=" * 72)

    print(
        f"\nRecommendations : {len(queue):,}"
    )

    for status in [
        "PENDING",
        "APPROVED",
        "REJECTED",
        "RESCHEDULE_REQUESTED",
    ]:

        print(
            f"  {status:<24} "
            f"{int(counts.get(status, 0)):>6,}"
        )

    print(
        f"\nAudit history events : {len(history):,}"
    )

    print(
        f"\nReport:\n  {REPORT_FILE}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    """Build command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "TrackEase human approval / rejection / reschedule workflow."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "initialize",
        help="Create/refresh the persistent decision queue.",
    )

    subparsers.add_parser(
        "summary",
        help="Show current decision-state counts.",
    )

    for command in [
        "approve",
        "reject",
        "reschedule",
    ]:

        action_parser = subparsers.add_parser(
            command
        )

        action_parser.add_argument(
            "recommendation_id",
            help="Optimizer recommendation ID, e.g. REC-000001.",
        )

        action_parser.add_argument(
            "--by",
            default="Human Planner",
            dest="decision_by",
            help="Planner/operator name or role.",
        )

        action_parser.add_argument(
            "--note",
            default="",
            help="Optional audit note.",
        )

    return parser.parse_args()


def main():
    """CLI entry point."""

    args = parse_args()

    if args.command == "initialize":
        initialize_queue()
        return

    if args.command == "summary":
        show_summary()
        return

    new_status = ACTION_TO_STATUS[
        args.command
    ]

    update_decision(
        recommendation_id=args.recommendation_id,
        new_status=new_status,
        decision_by=args.decision_by,
        note=args.note,
    )


if __name__ == "__main__":
    main()
