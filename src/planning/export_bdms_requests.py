"""
TrackEase - BDMS-Style Approved Block Export Adapter

Purpose:
    Convert human-approved TrackEase block recommendations into a
    structured downstream block-request format representing integration
    with a BDMS-style block management system.

Input:
    data/processed/block_decision_queue.csv

Outputs:
    data/processed/bdms_block_requests.csv
    data/processed/bdms_block_requests.jsonl
    data/processed/bdms_export_report.txt

Important:
    - Only APPROVED TrackEase recommendations are exported.
    - PENDING, REJECTED and RESCHEDULE_REQUESTED records are not exported.
    - This is a prototype integration schema.
    - TrackEase does NOT claim access to a real Indian Railways BDMS API
      or reproduce an official production BDMS schema.
"""

from pathlib import Path
import json

import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DECISION_QUEUE_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "block_decision_queue.csv"
)

CSV_OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "bdms_block_requests.csv"
)

JSONL_OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "bdms_block_requests.jsonl"
)

REPORT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "bdms_export_report.txt"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_columns(df, required_columns, dataset_name):
    """Raise a clear error when required columns are missing."""

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{dataset_name} is missing required columns:\n"
            + ", ".join(sorted(missing))
        )


def normalize_text(value):
    """Return a clean text value suitable for export."""

    if pd.isna(value):
        return ""

    return str(value)


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

def build_bdms_export():
    """Build prototype BDMS-style requests from approved recommendations."""

    print("=" * 72)
    print("TrackEase - BDMS-Style Approved Block Export")
    print("=" * 72)

    print("\nDecision queue:")
    print(f"  {DECISION_QUEUE_FILE}")

    if not DECISION_QUEUE_FILE.exists():
        raise FileNotFoundError(
            "Human decision queue not found:\n"
            f"{DECISION_QUEUE_FILE}"
        )

    print("  ✓ Found")

    queue = pd.read_csv(
        DECISION_QUEUE_FILE
    )

    print(
        f"\nDecision queue records : {len(queue):,}"
    )

    # -----------------------------------------------------------------------
    # Schema validation
    # -----------------------------------------------------------------------

    require_columns(
        queue,
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
            "decision_status",
            "decision_by",
            "decision_note",
            "decision_timestamp",
            "decision_version",
            "month_week",
        },
        "Block decision queue",
    )

    # -----------------------------------------------------------------------
    # Export only approved recommendations
    # -----------------------------------------------------------------------

    approved = queue[
        queue[
            "decision_status"
        ].astype(str)
        == "APPROVED"
    ].copy()

    pending_count = int(
        (
            queue[
                "decision_status"
            ].astype(str)
            == "PENDING"
        ).sum()
    )

    rejected_count = int(
        (
            queue[
                "decision_status"
            ].astype(str)
            == "REJECTED"
        ).sum()
    )

    reschedule_count = int(
        (
            queue[
                "decision_status"
            ].astype(str)
            == "RESCHEDULE_REQUESTED"
        ).sum()
    )

    # -----------------------------------------------------------------------
    # Build downstream prototype schema
    # -----------------------------------------------------------------------

    export_rows = []

    for number, row in enumerate(
        approved.itertuples(),
        start=1,
    ):

        export_rows.append(
            {
                "bdms_request_id":
                    f"BDMS-REQ-{number:06d}",

                "recommendation_id":
                    row.recommendation_id,

                "planning_task_id":
                    row.planning_task_id,

                "request_type":
                    "MAINTENANCE_BLOCK",

                "planning_horizon":
                    "MONTHLY_WEEKLY_INTEGRATED",

                "month_week":
                    int(row.month_week),

                "section_id":
                    row.section_id,

                "station_a_code":
                    normalize_text(
                        getattr(
                            row,
                            "station_a_code",
                            "",
                        )
                    ),

                "station_a_name":
                    normalize_text(
                        getattr(
                            row,
                            "station_a_name",
                            "",
                        )
                    ),

                "station_b_code":
                    normalize_text(
                        getattr(
                            row,
                            "station_b_code",
                            "",
                        )
                    ),

                "station_b_name":
                    normalize_text(
                        getattr(
                            row,
                            "station_b_name",
                            "",
                        )
                    ),

                "departments_involved":
                    normalize_text(
                        row.departments_involved
                    ),

                "source_systems":
                    normalize_text(
                        getattr(
                            row,
                            "source_systems",
                            "",
                        )
                    ),

                "planning_task_type":
                    row.planning_task_type,

                "requested_start_day":
                    row.scheduled_start_day,

                "requested_start_time":
                    row.scheduled_start_time,

                "requested_end_day":
                    row.scheduled_end_day,

                "requested_end_time":
                    row.scheduled_end_time,

                "requested_duration_minutes":
                    int(row.required_minutes),

                "maintenance_priority_score":
                    float(
                        row.trackease_priority_score
                    ),

                "maintenance_priority_level":
                    row.trackease_priority_level,

                "operational_impact_score":
                    float(
                        row.operational_impact_score
                    ),

                "operational_impact_level":
                    row.operational_impact_level,

                "estimated_coordination_minutes_saved":
                    int(
                        row.estimated_minutes_saved
                    ),

                "human_approval_status":
                    "APPROVED",

                "approved_by":
                    normalize_text(
                        row.decision_by
                    ),

                "approval_note":
                    normalize_text(
                        row.decision_note
                    ),

                "approval_timestamp":
                    normalize_text(
                        row.decision_timestamp
                    ),

                "decision_version":
                    int(
                        row.decision_version
                    ),

                "downstream_status":
                    "READY_FOR_SUBMISSION",

                "target_system":
                    "BDMS",

                "integration_mode":
                    "PROTOTYPE_EXPORT_ADAPTER",

                "schema_type":
                    "TRACKEASE_BDMS_STYLE_V1",
            }
        )

    export_df = pd.DataFrame(
        export_rows
    )

    # Ensure predictable headers even when no rows are approved.
    output_columns = [
        "bdms_request_id",
        "recommendation_id",
        "planning_task_id",
        "request_type",
        "planning_horizon",
        "month_week",
        "section_id",
        "station_a_code",
        "station_a_name",
        "station_b_code",
        "station_b_name",
        "departments_involved",
        "source_systems",
        "planning_task_type",
        "requested_start_day",
        "requested_start_time",
        "requested_end_day",
        "requested_end_time",
        "requested_duration_minutes",
        "maintenance_priority_score",
        "maintenance_priority_level",
        "operational_impact_score",
        "operational_impact_level",
        "estimated_coordination_minutes_saved",
        "human_approval_status",
        "approved_by",
        "approval_note",
        "approval_timestamp",
        "decision_version",
        "downstream_status",
        "target_system",
        "integration_mode",
        "schema_type",
    ]

    if export_df.empty:
        export_df = pd.DataFrame(
            columns=output_columns
        )
    else:
        export_df = export_df[
            output_columns
        ]

    # -----------------------------------------------------------------------
    # Quality checks
    # -----------------------------------------------------------------------

    duplicate_requests = int(
        export_df[
            "bdms_request_id"
        ].duplicated().sum()
        if not export_df.empty
        else 0
    )

    duplicate_recommendations = int(
        export_df[
            "recommendation_id"
        ].duplicated().sum()
        if not export_df.empty
        else 0
    )

    invalid_approval = int(
        (
            export_df[
                "human_approval_status"
            ]
            != "APPROVED"
        ).sum()
        if not export_df.empty
        else 0
    )

    if (
        duplicate_requests > 0
        or duplicate_recommendations > 0
        or invalid_approval > 0
    ):
        raise RuntimeError(
            "BDMS export integrity validation failed."
        )

    # -----------------------------------------------------------------------
    # Save CSV
    # -----------------------------------------------------------------------

    export_df.to_csv(
        CSV_OUTPUT_FILE,
        index=False,
    )

    # -----------------------------------------------------------------------
    # Save JSON Lines
    # -----------------------------------------------------------------------

    with JSONL_OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
    ) as file_handle:

        for record in export_df.to_dict(
            orient="records"
        ):

            file_handle.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    approved_count = len(
        export_df
    )

    approved_minutes = int(
        pd.to_numeric(
            export_df[
                "requested_duration_minutes"
            ],
            errors="coerce",
        )
        .fillna(0)
        .sum()
        if not export_df.empty
        else 0
    )

    coordination_saved = int(
        pd.to_numeric(
            export_df[
                "estimated_coordination_minutes_saved"
            ],
            errors="coerce",
        )
        .fillna(0)
        .sum()
        if not export_df.empty
        else 0
    )

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------

    report = [
        "=" * 72,
        "TrackEase BDMS-Style Export Report",
        "=" * 72,
        "",
        "DECISION QUEUE",
        "-" * 72,
        f"Total recommendations          : {len(queue):,}",
        f"Approved                       : {approved_count:,}",
        f"Pending                        : {pending_count:,}",
        f"Rejected                       : {rejected_count:,}",
        f"Reschedule requested           : {reschedule_count:,}",
        "",
        "EXPORTED BLOCK REQUESTS",
        "-" * 72,
        f"BDMS-style requests created    : {approved_count:,}",
        f"Approved maintenance minutes   : {approved_minutes:,}",
        f"Coordination minutes saved     : {coordination_saved:,}",
        "",
        "QUALITY CHECKS",
        "-" * 72,
        f"Duplicate request IDs          : {duplicate_requests:,}",
        f"Duplicate recommendation IDs   : {duplicate_recommendations:,}",
        f"Non-approved records exported  : {invalid_approval:,}",
        "",
        "INTEGRATION",
        "-" * 72,
        "Target system representation  : BDMS",
        "Integration mode              : PROTOTYPE_EXPORT_ADAPTER",
        "Schema                        : TRACKEASE_BDMS_STYLE_V1",
        "",
        "IMPORTANT LIMITATION",
        "-" * 72,
        (
            "This export demonstrates how approved TrackEase recommendations "
            "could be handed to a downstream block-management system."
        ),
        (
            "It is not an official Indian Railways BDMS schema and TrackEase "
            "does not claim live BDMS connectivity."
        ),
        "",
        "NEXT STAGE",
        "-" * 72,
        (
            "Run Maintenance ML V2 experimentation, then perform a final "
            "backend validation and integrate TrackEase outputs into app.py."
        ),
    ]

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    # -----------------------------------------------------------------------
    # Console
    # -----------------------------------------------------------------------

    print("\n" + "=" * 72)
    print("BDMS-STYLE EXPORT COMPLETE")
    print("=" * 72)

    print(
        f"\nApproved recommendations : "
        f"{approved_count:,}"
    )

    print(
        f"Exported requests        : "
        f"{approved_count:,}"
    )

    print(
        f"Approved minutes         : "
        f"{approved_minutes:,}"
    )

    print(
        f"Coordination saved       : "
        f"{coordination_saved:,}"
    )

    print("\nQuality checks:")
    print(
        f"  Duplicate request IDs        : "
        f"{duplicate_requests:,}"
    )
    print(
        f"  Duplicate recommendation IDs : "
        f"{duplicate_recommendations:,}"
    )
    print(
        f"  Non-approved exported        : "
        f"{invalid_approval:,}"
    )

    print("\nOutputs:")
    print(
        f"  {CSV_OUTPUT_FILE}"
    )
    print(
        f"  {JSONL_OUTPUT_FILE}"
    )
    print(
        f"  {REPORT_FILE}"
    )

    print(
        "\nOnly human-approved TrackEase blocks are now represented "
        "as downstream BDMS-style requests."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_bdms_export()
