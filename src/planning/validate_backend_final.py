"""
TrackEase - Final Backend Validation

Purpose:
    Perform a lightweight end-to-end consistency check across the completed
    TrackEase backend before frontend integration.

This validator DOES NOT retrain models or rebuild planning data.
It checks that the outputs of the major backend stages agree with one another.

Checks:
    - Core output files exist.
    - Unified/coordinated/optimized task accounting is consistent.
    - Weekly and monthly plans contain the same scheduled recommendations.
    - Decision queue mirrors the weekly plan.
    - BDMS-style export contains only approved recommendations.
    - Approved decision count matches BDMS export count.
    - No duplicate recommendation/task IDs in key outputs.
    - Existing planning-readiness and Optimizer V2 reports indicate success.
    - Maintenance ML V2 metadata is consistent with its evidence decision.

Output:
    data/processed/final_backend_validation_report.txt
"""

from pathlib import Path

import joblib
import pandas as pd


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = PROJECT_ROOT / "data" / "processed"
MODELS = PROJECT_ROOT / "data" / "models"

FILES = {
    "unified_tasks":
        PROCESSED / "unified_maintenance_tasks.csv",

    "planning_tasks":
        PROCESSED / "coordinated_planning_tasks.csv",

    "optimized_weekly":
        PROCESSED / "optimized_weekly_blocks.csv",

    "optimizer_unscheduled":
        PROCESSED / "optimizer_v2_unscheduled.csv",

    "weekly_plan":
        PROCESSED / "weekly_block_plan.csv",

    "monthly_plan":
        PROCESSED / "monthly_block_plan.csv",

    "decision_queue":
        PROCESSED / "block_decision_queue.csv",

    "decision_history":
        PROCESSED / "block_decision_history.csv",

    "bdms_export":
        PROCESSED / "bdms_block_requests.csv",

    "planning_readiness_report":
        PROCESSED / "planning_readiness_report.txt",

    "optimizer_validation_report":
        PROCESSED / "optimizer_v2_validation_report.txt",

    "ml_v2_metrics":
        PROCESSED / "maintenance_ml_v2_metrics.csv",

    "ml_v2_metadata":
        MODELS / "maintenance_model_v2_metadata.joblib",
}

REPORT_FILE = (
    PROCESSED
    / "final_backend_validation_report.txt"
)


# ---------------------------------------------------------------------------
# Validation collector
# ---------------------------------------------------------------------------

class Validation:
    def __init__(self):
        self.records = []

    def passed(self, name, detail):
        self.records.append(
            ("PASS", name, detail)
        )

    def warning(self, name, detail):
        self.records.append(
            ("WARNING", name, detail)
        )

    def error(self, name, detail):
        self.records.append(
            ("ERROR", name, detail)
        )

    @property
    def passes(self):
        return sum(
            level == "PASS"
            for level, _, _ in self.records
        )

    @property
    def warnings(self):
        return sum(
            level == "WARNING"
            for level, _, _ in self.records
        )

    @property
    def errors(self):
        return sum(
            level == "ERROR"
            for level, _, _ in self.records
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read_csv(path):
    return pd.read_csv(
        path,
        low_memory=False,
    )


def check_unique(
    df,
    column,
    label,
    validation,
):
    if column not in df.columns:
        validation.error(
            label,
            f"Required column missing: {column}",
        )
        return

    duplicates = int(
        df[
            column
        ].duplicated().sum()
    )

    if duplicates == 0:
        validation.passed(
            label,
            f"{column} values are unique.",
        )
    else:
        validation.error(
            label,
            f"{duplicates:,} duplicate {column} values found.",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def validate_backend():
    print("=" * 72)
    print("TrackEase - Final Backend Validation")
    print("=" * 72)

    result = Validation()

    # -----------------------------------------------------------------------
    # File existence
    # -----------------------------------------------------------------------

    missing_files = []

    for name, path in FILES.items():

        if path.exists():
            result.passed(
                f"File: {name}",
                f"Found {path}",
            )
        else:
            missing_files.append(
                str(path)
            )
            result.error(
                f"File: {name}",
                f"Missing {path}",
            )

    if missing_files:
        print(
            "\nRequired backend outputs are missing. "
            "Fix missing files before frontend integration."
        )

        write_report(
            result,
            {},
        )

        return

    # -----------------------------------------------------------------------
    # Load key datasets
    # -----------------------------------------------------------------------

    unified = read_csv(
        FILES[
            "unified_tasks"
        ]
    )

    planning = read_csv(
        FILES[
            "planning_tasks"
        ]
    )

    optimized = read_csv(
        FILES[
            "optimized_weekly"
        ]
    )

    unscheduled = read_csv(
        FILES[
            "optimizer_unscheduled"
        ]
    )

    weekly = read_csv(
        FILES[
            "weekly_plan"
        ]
    )

    monthly = read_csv(
        FILES[
            "monthly_plan"
        ]
    )

    decisions = read_csv(
        FILES[
            "decision_queue"
        ]
    )

    history = read_csv(
        FILES[
            "decision_history"
        ]
    )

    bdms = read_csv(
        FILES[
            "bdms_export"
        ]
    )

    ml_metrics = read_csv(
        FILES[
            "ml_v2_metrics"
        ]
    )

    metrics = {
        "unified_tasks":
            len(unified),

        "planning_units":
            len(planning),

        "scheduled_units":
            len(optimized),

        "unscheduled_units":
            len(unscheduled),

        "weekly_plan_rows":
            len(weekly),

        "monthly_plan_rows":
            len(monthly),

        "decision_queue_rows":
            len(decisions),

        "decision_history_events":
            len(history),

        "bdms_export_rows":
            len(bdms),
    }

    # -----------------------------------------------------------------------
    # ID uniqueness
    # -----------------------------------------------------------------------

    check_unique(
        unified,
        "unified_task_id",
        "Unified task IDs",
        result,
    )

    check_unique(
        planning,
        "planning_task_id",
        "Planning task IDs",
        result,
    )

    check_unique(
        optimized,
        "recommendation_id",
        "Optimizer recommendation IDs",
        result,
    )

    check_unique(
        weekly,
        "recommendation_id",
        "Weekly recommendation IDs",
        result,
    )

    check_unique(
        monthly,
        "planning_task_id",
        "Monthly planning task IDs",
        result,
    )

    check_unique(
        decisions,
        "recommendation_id",
        "Decision queue IDs",
        result,
    )

    if len(bdms) > 0:
        check_unique(
            bdms,
            "recommendation_id",
            "BDMS recommendation IDs",
            result,
        )

    # -----------------------------------------------------------------------
    # Optimizer accounting
    # -----------------------------------------------------------------------

    accounted = (
        len(optimized)
        + len(unscheduled)
    )

    if accounted == len(planning):
        result.passed(
            "Optimizer accounting",
            (
                f"{len(optimized):,} scheduled + "
                f"{len(unscheduled):,} unscheduled = "
                f"{len(planning):,} planning units."
            ),
        )
    else:
        result.error(
            "Optimizer accounting",
            (
                f"Scheduled + unscheduled = {accounted:,}, "
                f"but planning input contains {len(planning):,}."
            ),
        )

    # -----------------------------------------------------------------------
    # Weekly plan consistency
    # -----------------------------------------------------------------------

    optimized_ids = set(
        optimized[
            "recommendation_id"
        ].astype(str)
    )

    weekly_ids = set(
        weekly[
            "recommendation_id"
        ].astype(str)
    )

    if (
        len(optimized)
        == len(weekly)
        and optimized_ids
        == weekly_ids
    ):
        result.passed(
            "Weekly plan consistency",
            (
                f"Weekly plan contains exactly the "
                f"{len(optimized):,} optimized recommendations."
            ),
        )
    else:
        result.error(
            "Weekly plan consistency",
            "Weekly plan differs from Optimizer V2 recommendations.",
        )

    # -----------------------------------------------------------------------
    # Monthly plan consistency
    # -----------------------------------------------------------------------

    monthly_ids = set(
        monthly[
            "recommendation_id"
        ].astype(str)
    )

    if (
        len(monthly)
        == len(weekly)
        and monthly_ids
        == weekly_ids
    ):
        result.passed(
            "Monthly plan consistency",
            (
                f"Monthly plan assigns all "
                f"{len(weekly):,} scheduled recommendations exactly once."
            ),
        )
    else:
        result.error(
            "Monthly plan consistency",
            "Monthly plan does not match the validated weekly recommendation set.",
        )

    if "month_week" in monthly.columns:

        invalid_month_weeks = int(
            (
                ~pd.to_numeric(
                    monthly[
                        "month_week"
                    ],
                    errors="coerce",
                ).between(
                    1,
                    4,
                )
            ).sum()
        )

        if invalid_month_weeks == 0:
            result.passed(
                "Monthly week range",
                "All monthly assignments are in Weeks 1-4.",
            )
        else:
            result.error(
                "Monthly week range",
                f"{invalid_month_weeks:,} rows have invalid month_week values.",
            )

    # -----------------------------------------------------------------------
    # Decision queue consistency
    # -----------------------------------------------------------------------

    decision_ids = set(
        decisions[
            "recommendation_id"
        ].astype(str)
    )

    if (
        len(decisions)
        == len(weekly)
        and decision_ids
        == weekly_ids
    ):
        result.passed(
            "Decision queue consistency",
            (
                f"Decision queue mirrors all "
                f"{len(weekly):,} weekly recommendations."
            ),
        )
    else:
        result.error(
            "Decision queue consistency",
            "Decision queue does not match the weekly plan.",
        )

    valid_states = {
        "PENDING",
        "APPROVED",
        "REJECTED",
        "RESCHEDULE_REQUESTED",
    }

    invalid_states = (
        ~decisions[
            "decision_status"
        ].astype(str).isin(
            valid_states
        )
    )

    invalid_state_count = int(
        invalid_states.sum()
    )

    if invalid_state_count == 0:
        result.passed(
            "Decision states",
            "All decision states are valid.",
        )
    else:
        result.error(
            "Decision states",
            f"{invalid_state_count:,} invalid decision states found.",
        )

    # -----------------------------------------------------------------------
    # BDMS export consistency
    # -----------------------------------------------------------------------

    approved = decisions[
        decisions[
            "decision_status"
        ].astype(str)
        == "APPROVED"
    ].copy()

    approved_ids = set(
        approved[
            "recommendation_id"
        ].astype(str)
    )

    bdms_ids = set(
        bdms[
            "recommendation_id"
        ].astype(str)
        if "recommendation_id"
        in bdms.columns
        else []
    )

    if (
        len(approved)
        == len(bdms)
        and approved_ids
        == bdms_ids
    ):
        result.passed(
            "BDMS approved-only export",
            (
                f"{len(approved):,} approved recommendation(s) "
                "match BDMS-style export exactly."
            ),
        )
    else:
        result.error(
            "BDMS approved-only export",
            (
                f"Approved queue count = {len(approved):,}, "
                f"BDMS export count = {len(bdms):,}."
            ),
        )

    if (
        len(bdms) == 0
        or (
            "human_approval_status"
            in bdms.columns
            and (
                bdms[
                    "human_approval_status"
                ].astype(str)
                == "APPROVED"
            ).all()
        )
    ):
        result.passed(
            "BDMS approval safety",
            "No non-approved recommendation appears in the BDMS export.",
        )
    else:
        result.error(
            "BDMS approval safety",
            "BDMS export contains a non-approved recommendation.",
        )

    # -----------------------------------------------------------------------
    # Prior validation reports
    # -----------------------------------------------------------------------

    planning_report = FILES[
        "planning_readiness_report"
    ].read_text(
        encoding="utf-8",
        errors="replace",
    )

    if (
        "READY FOR OPTIMIZER V2"
        in planning_report
        and "Errors        : 0"
        in planning_report
    ):
        result.passed(
            "Planning readiness gate",
            "Planning readiness report indicates zero errors.",
        )
    else:
        result.warning(
            "Planning readiness gate",
            (
                "Could not confirm the expected zero-error READY status "
                "from planning_readiness_report.txt."
            ),
        )

    optimizer_report = FILES[
        "optimizer_validation_report"
    ].read_text(
        encoding="utf-8",
        errors="replace",
    )

    if (
        "OPTIMIZER V2 VALIDATED"
        in optimizer_report
        and "Errors                     : 0"
        in optimizer_report
    ):
        result.passed(
            "Optimizer V2 validation gate",
            "Optimizer V2 validation report indicates zero errors.",
        )
    else:
        result.warning(
            "Optimizer V2 validation gate",
            (
                "Could not confirm the expected zero-error validated status "
                "from optimizer_v2_validation_report.txt."
            ),
        )

    # -----------------------------------------------------------------------
    # ML V2 decision consistency
    # -----------------------------------------------------------------------

    ml_metadata = joblib.load(
        FILES[
            "ml_v2_metadata"
        ]
    )

    evidence_status = str(
        ml_metadata.get(
            "evidence_status",
            "UNKNOWN",
        )
    )

    integration_allowed = bool(
        ml_metadata.get(
            "integration_allowed",
            False,
        )
    )

    if evidence_status == (
        "NOT_RECOMMENDED_FOR_PRIORITY_INTEGRATION"
    ):

        if not integration_allowed:
            result.passed(
                "ML V2 integration guard",
                (
                    "Weak ML evidence is correctly blocked from "
                    "priority-score integration."
                ),
            )
        else:
            result.error(
                "ML V2 integration guard",
                (
                    "Metadata allows ML integration despite "
                    "NOT_RECOMMENDED evidence status."
                ),
            )

        result.warning(
            "ML V2 predictive evidence",
            (
                "ML V2 was intentionally NOT integrated into priority. "
                "TrackEase should continue using its explainable "
                "rule-based priority engine."
            ),
        )

    elif evidence_status in {
        "LIMITED_SUPPORT_SIGNAL",
        "STRONG_SUPPORT_SIGNAL",
    }:

        if integration_allowed:
            result.passed(
                "ML V2 integration guard",
                (
                    f"Metadata is consistent with evidence status "
                    f"{evidence_status}."
                ),
            )
        else:
            result.warning(
                "ML V2 integration guard",
                (
                    "Evidence supports limited ML use, but metadata keeps "
                    "integration disabled."
                ),
            )

    else:

        result.warning(
            "ML V2 evidence status",
            f"Unexpected evidence status: {evidence_status}",
        )

    if len(ml_metrics) >= 3:
        result.passed(
            "ML V2 model comparison",
            (
                f"{len(ml_metrics):,} candidate model results are recorded."
            ),
        )
    else:
        result.warning(
            "ML V2 model comparison",
            "Fewer than three model results were recorded.",
        )

    # -----------------------------------------------------------------------
    # Final status / report
    # -----------------------------------------------------------------------

    write_report(
        result,
        metrics,
    )

    status = (
        "BACKEND READY FOR FRONTEND INTEGRATION"
        if result.errors == 0
        else "BACKEND NOT READY FOR FRONTEND INTEGRATION"
    )

    print("\n" + "=" * 72)
    print("FINAL BACKEND VALIDATION COMPLETE")
    print("=" * 72)

    print(
        f"\nPassed checks : {result.passes}"
    )

    print(
        f"Warnings      : {result.warnings}"
    )

    print(
        f"Errors        : {result.errors}"
    )

    print("\nCore counts:")
    print(
        f"  Unified tasks      : {len(unified):,}"
    )
    print(
        f"  Planning units     : {len(planning):,}"
    )
    print(
        f"  Weekly scheduled   : {len(optimized):,}"
    )
    print(
        f"  Weekly unscheduled : {len(unscheduled):,}"
    )
    print(
        f"  Monthly planned    : {len(monthly):,}"
    )
    print(
        f"  Decision queue     : {len(decisions):,}"
    )
    print(
        f"  BDMS exported      : {len(bdms):,}"
    )

    print(
        f"\nML evidence status:\n  {evidence_status}"
    )

    print("\nStatus:")
    print(
        f"  {status}"
    )

    print("\nReport:")
    print(
        f"  {REPORT_FILE}"
    )


def write_report(
    validation,
    metrics,
):
    """Write final validation report."""

    status = (
        "BACKEND READY FOR FRONTEND INTEGRATION"
        if validation.errors == 0
        else "BACKEND NOT READY FOR FRONTEND INTEGRATION"
    )

    report = [
        "=" * 72,
        "TrackEase Final Backend Validation Report",
        "=" * 72,
        "",
        "VALIDATION RESULTS",
        "-" * 72,
    ]

    for level, name, detail in validation.records:

        report.append(
            f"[{level}] {name}"
        )

        report.append(
            f"    {detail}"
        )

    if metrics:

        report.extend(
            [
                "",
                "CORE COUNTS",
                "-" * 72,
            ]
        )

        for key, value in metrics.items():
            report.append(
                f"{key:<30} {value:>10,}"
            )

    report.extend(
        [
            "",
            "SUMMARY",
            "-" * 72,
            f"Passed checks : {validation.passes}",
            f"Warnings      : {validation.warnings}",
            f"Errors        : {validation.errors}",
            "",
            status,
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )


if __name__ == "__main__":
    validate_backend()
