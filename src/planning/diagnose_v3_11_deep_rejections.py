
# TrackEase V3.11 - Deep Rejection Diagnostic
#
# Read-only diagnostic for the V3.11 exact resource-time & safety layer.
# It does not modify any existing TrackEase planning outputs.

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

FEASIBILITY_FILE = PROCESSED_DIR / "v3_candidate_window_feasibility.csv"
REJECTIONS_FILE = PROCESSED_DIR / "v3_candidate_window_rejections.csv"
TASK_SUMMARY_FILE = PROCESSED_DIR / "v3_task_feasible_window_summary.csv"
REQUIREMENTS_FILE = PROCESSED_DIR / "v3_task_resource_requirements.csv"
ASSIGNMENTS_FILE = PROCESSED_DIR / "v3_candidate_resource_assignments.csv"
PROTECTION_DIAGNOSTIC_FILE = (
    PROCESSED_DIR / "v3_11_protection_bottleneck_diagnostics.csv"
)

DETAIL_OUTPUT = PROCESSED_DIR / "v3_11_deep_rejection_diagnostics.csv"
TASK_OUTPUT = PROCESSED_DIR / "v3_11_task_rejection_diagnostics.csv"
REPORT_OUTPUT = PROCESSED_DIR / "v3_11_deep_rejection_report.txt"


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def truthy(value: object) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def first_existing(columns: list[str], frame: pd.DataFrame) -> str | None:
    for column in columns:
        if column in frame.columns:
            return column
    return None


def split_pipe(value: object) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def load_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return pd.read_csv(path, low_memory=False)


def normalize_reason(reason: str) -> str:
    reason = clean(reason).upper()
    if not reason:
        return "UNKNOWN_REJECTION_REASON"

    aliases = {
        "MANDATORY_RESOURCE_TIME_FAILURE": "MANDATORY_RESOURCE_TIME_FAILURE",
        "RESOURCE_TIME_FAILURE": "MANDATORY_RESOURCE_TIME_FAILURE",
        "NO_PROTECTION_CREW_ON_DUTY_AT_WINDOW_START":
            "NO_PROTECTION_CREW_ON_DUTY_AT_WINDOW_START",
        "WINDOW_EXTENDS_OUTSIDE_PROTECTION_SHIFT":
            "WINDOW_EXTENDS_OUTSIDE_PROTECTION_SHIFT",
        "POWER_ISOLATION_SUPPORT_NOT_TIME_READY":
            "POWER_ISOLATION_SUPPORT_NOT_TIME_READY",
        "DEPENDENCY_GATE_FAILED": "DEPENDENCY_GATE_FAILED",
        "DEPENDENCY_NOT_READY": "DEPENDENCY_GATE_FAILED",
    }

    return aliases.get(reason, reason)


def main() -> None:
    print("=" * 72)
    print("TrackEase V3.11 - Deep Rejection Diagnostic")
    print("=" * 72)

    feasibility = load_required(FEASIBILITY_FILE)
    rejections = load_required(REJECTIONS_FILE)
    task_summary = load_required(TASK_SUMMARY_FILE)
    requirements = load_required(REQUIREMENTS_FILE)
    assignments = load_required(ASSIGNMENTS_FILE)

    protection_diag = (
        pd.read_csv(PROTECTION_DIAGNOSTIC_FILE, low_memory=False)
        if PROTECTION_DIAGNOSTIC_FILE.exists()
        else pd.DataFrame()
    )

    print("\nLoaded:")
    print(f"  Feasibility rows       : {len(feasibility):,}")
    print(f"  Rejection rows         : {len(rejections):,}")
    print(f"  Task summary rows      : {len(task_summary):,}")
    print(f"  Requirement rows       : {len(requirements):,}")
    print(f"  Resource assignments   : {len(assignments):,}")
    print(f"  Protection diagnostics : {len(protection_diag):,}")

    candidate_id_col = first_existing(
        ["candidate_window_id", "window_id"],
        rejections,
    )
    task_id_col = first_existing(
        ["task_id"],
        rejections,
    )
    failed_ids_col = first_existing(
        [
            "failed_requirement_ids",
            "failed_resource_requirement_ids",
            "failed_requirements",
        ],
        rejections,
    )
    failed_reasons_col = first_existing(
        [
            "failed_requirement_reasons",
            "rejection_reasons",
            "failure_reasons",
            "reason_codes",
        ],
        rejections,
    )

    if candidate_id_col is None:
        raise ValueError(
            "Could not find candidate window ID column in "
            f"{REJECTIONS_FILE.name}. Columns: {rejections.columns.tolist()}"
        )

    # Build requirement lookup.
    required_requirement_columns = {
        "requirement_id",
        "task_id",
        "resource_category",
        "requirement_type",
    }
    missing_requirement_columns = (
        required_requirement_columns - set(requirements.columns)
    )
    if missing_requirement_columns:
        raise ValueError(
            "Requirement file is missing columns: "
            f"{sorted(missing_requirement_columns)}"
        )

    requirement_lookup = {
        clean(row["requirement_id"]): row
        for row in requirements.to_dict(orient="records")
        if clean(row.get("requirement_id"))
    }

    detail_rows = []
    raw_reason_counter = Counter()
    normalized_reason_counter = Counter()
    category_counter = Counter()
    type_counter = Counter()
    category_type_counter = Counter()
    candidate_reason_counter = Counter()
    candidate_failed_slot_counter = Counter()

    for row in rejections.to_dict(orient="records"):
        candidate_id = clean(row.get(candidate_id_col))
        task_id = clean(row.get(task_id_col)) if task_id_col else ""

        failed_ids = (
            split_pipe(row.get(failed_ids_col))
            if failed_ids_col
            else []
        )
        failed_reasons = (
            split_pipe(row.get(failed_reasons_col))
            if failed_reasons_col
            else []
        )

        # If reasons exist but requirement IDs do not, still preserve the
        # candidate-level diagnosis.
        if not failed_ids and failed_reasons:
            for reason in failed_reasons:
                normalized = normalize_reason(reason)
                raw_reason_counter[clean(reason)] += 1
                normalized_reason_counter[normalized] += 1
                candidate_reason_counter[(candidate_id, normalized)] += 1

                detail_rows.append(
                    {
                        "candidate_window_id": candidate_id,
                        "task_id": task_id,
                        "requirement_id": "",
                        "resource_category": "",
                        "requirement_type": "",
                        "raw_reason": clean(reason),
                        "normalized_reason": normalized,
                        "diagnostic_level": "CANDIDATE",
                    }
                )
            continue

        if failed_ids:
            candidate_failed_slot_counter[candidate_id] = len(failed_ids)

        # Align IDs and reasons by position when possible. If there is one
        # generic reason for several IDs, repeat it for each failed slot.
        if failed_ids:
            if len(failed_reasons) == 1 and len(failed_ids) > 1:
                aligned_reasons = failed_reasons * len(failed_ids)
            elif len(failed_reasons) == len(failed_ids):
                aligned_reasons = failed_reasons
            else:
                aligned_reasons = [
                    failed_reasons[index]
                    if index < len(failed_reasons)
                    else "UNSPECIFIED_FAILED_REQUIREMENT"
                    for index in range(len(failed_ids))
                ]

            for requirement_id, reason in zip(failed_ids, aligned_reasons):
                requirement = requirement_lookup.get(requirement_id, {})
                category = clean(requirement.get("resource_category"))
                requirement_type = clean(requirement.get("requirement_type"))
                requirement_task = clean(requirement.get("task_id"))
                resolved_task_id = task_id or requirement_task

                normalized = normalize_reason(reason)

                raw_reason_counter[clean(reason)] += 1
                normalized_reason_counter[normalized] += 1

                if category:
                    category_counter[category] += 1
                if requirement_type:
                    type_counter[requirement_type] += 1
                if category or requirement_type:
                    category_type_counter[
                        (category, requirement_type)
                    ] += 1

                candidate_reason_counter[(candidate_id, normalized)] += 1

                detail_rows.append(
                    {
                        "candidate_window_id": candidate_id,
                        "task_id": resolved_task_id,
                        "requirement_id": requirement_id,
                        "resource_category": category,
                        "requirement_type": requirement_type,
                        "raw_reason": clean(reason),
                        "normalized_reason": normalized,
                        "diagnostic_level": "REQUIREMENT",
                    }
                )
        elif not failed_reasons:
            detail_rows.append(
                {
                    "candidate_window_id": candidate_id,
                    "task_id": task_id,
                    "requirement_id": "",
                    "resource_category": "",
                    "requirement_type": "",
                    "raw_reason": "",
                    "normalized_reason": "REJECTION_WITHOUT_PARSED_REASON",
                    "diagnostic_level": "CANDIDATE",
                }
            )
            normalized_reason_counter[
                "REJECTION_WITHOUT_PARSED_REASON"
            ] += 1

    detail = pd.DataFrame(detail_rows)

    # ------------------------------------------------------------------
    # Feasibility status counts.
    # ------------------------------------------------------------------
    status_col = first_existing(
        [
            "final_feasibility_status",
            "status",
            "feasibility_status",
        ],
        feasibility,
    )

    status_counts = (
        feasibility[status_col]
        .astype(str)
        .value_counts()
        if status_col
        else pd.Series(dtype="int64")
    )

    # ------------------------------------------------------------------
    # Task-level diagnosis.
    # ------------------------------------------------------------------
    summary_task_col = first_existing(["task_id"], task_summary)
    feasible_count_col = first_existing(
        [
            "feasible_window_count",
            "feasible_candidate_count",
            "total_feasible_windows",
        ],
        task_summary,
    )

    rejection_candidates_by_task: dict[str, set[str]] = defaultdict(set)
    rejection_reasons_by_task: dict[str, Counter] = defaultdict(Counter)
    failed_categories_by_task: dict[str, Counter] = defaultdict(Counter)
    failed_types_by_task: dict[str, Counter] = defaultdict(Counter)

    for row in detail.to_dict(orient="records"):
        task_id = clean(row.get("task_id"))
        candidate_id = clean(row.get("candidate_window_id"))
        reason = clean(row.get("normalized_reason"))
        category = clean(row.get("resource_category"))
        requirement_type = clean(row.get("requirement_type"))

        if not task_id:
            continue

        if candidate_id:
            rejection_candidates_by_task[task_id].add(candidate_id)
        if reason:
            rejection_reasons_by_task[task_id][reason] += 1
        if category:
            failed_categories_by_task[task_id][category] += 1
        if requirement_type:
            failed_types_by_task[task_id][requirement_type] += 1

    task_rows = []

    if summary_task_col:
        for row in task_summary.to_dict(orient="records"):
            task_id = clean(row.get(summary_task_col))
            if not task_id:
                continue

            feasible_count = 0
            if feasible_count_col:
                try:
                    feasible_count = int(float(row.get(feasible_count_col, 0)))
                except (TypeError, ValueError):
                    feasible_count = 0
            else:
                # Fall back to status-like fields when count is unavailable.
                status_value = clean(
                    row.get(
                        first_existing(
                            ["task_feasibility_status", "status"],
                            task_summary,
                        )
                    )
                ).upper()
                feasible_count = 1 if "FEASIBLE" in status_value else 0

            reason_counter = rejection_reasons_by_task.get(
                task_id,
                Counter(),
            )
            category_count = failed_categories_by_task.get(
                task_id,
                Counter(),
            )
            type_count = failed_types_by_task.get(
                task_id,
                Counter(),
            )

            task_rows.append(
                {
                    "task_id": task_id,
                    "feasible_window_count": feasible_count,
                    "rejected_candidate_count": len(
                        rejection_candidates_by_task.get(task_id, set())
                    ),
                    "has_feasible_window": feasible_count > 0,
                    "primary_rejection_reason": (
                        reason_counter.most_common(1)[0][0]
                        if reason_counter
                        else ""
                    ),
                    "primary_failed_resource_category": (
                        category_count.most_common(1)[0][0]
                        if category_count
                        else ""
                    ),
                    "primary_failed_requirement_type": (
                        type_count.most_common(1)[0][0]
                        if type_count
                        else ""
                    ),
                    "reason_counts": "|".join(
                        f"{name}:{count}"
                        for name, count in reason_counter.most_common()
                    ),
                }
            )

    task_diag = pd.DataFrame(task_rows)

    # ------------------------------------------------------------------
    # Optional protection diagnostic summary.
    # ------------------------------------------------------------------
    protection_counts = Counter()

    if not protection_diag.empty:
        protection_reason_col = first_existing(
            [
                "diagnostic_classification",
                "classification",
                "diagnosis",
                "reason",
            ],
            protection_diag,
        )

        if protection_reason_col:
            for value in protection_diag[protection_reason_col]:
                text = clean(value)
                if text:
                    protection_counts[text] += 1

    # ------------------------------------------------------------------
    # Candidate assignment coverage sanity check.
    # ------------------------------------------------------------------
    assignment_candidate_col = first_existing(
        ["candidate_window_id"],
        assignments,
    )

    assignment_requirement_col = first_existing(
        ["requirement_id"],
        assignments,
    )

    assignment_coverage = 0
    assignment_slots = 0

    if assignment_candidate_col and assignment_requirement_col:
        assignment_slots = len(
            assignments[
                [
                    assignment_candidate_col,
                    assignment_requirement_col,
                ]
            ].drop_duplicates()
        )
        assignment_coverage = assignments[
            assignment_candidate_col
        ].nunique()

    # ------------------------------------------------------------------
    # Write outputs/report.
    # ------------------------------------------------------------------
    detail.to_csv(DETAIL_OUTPUT, index=False)
    task_diag.to_csv(TASK_OUTPUT, index=False)

    zero_feasible_tasks = (
        int((~task_diag["has_feasible_window"]).sum())
        if not task_diag.empty
        else 0
    )

    lines = [
        "=" * 72,
        "TrackEase V3.11 Deep Rejection Diagnostic Report",
        "=" * 72,
        "",
        "INPUT SUMMARY",
        "-" * 72,
        f"Feasibility rows                  : {len(feasibility):,}",
        f"Rejection rows                    : {len(rejections):,}",
        f"Task summary rows                 : {len(task_summary):,}",
        f"Requirement rows                  : {len(requirements):,}",
        f"Resource assignment rows          : {len(assignments):,}",
        f"Assignment candidate coverage     : {assignment_coverage:,}",
        f"Assignment candidate/req slots    : {assignment_slots:,}",
        f"Tasks with zero feasible windows  : {zero_feasible_tasks:,}",
        "",
        "V3.11 FINAL STATUS COUNTS",
        "-" * 72,
    ]

    if status_counts.empty:
        lines.append("No recognizable status column found.")
    else:
        for name, count in status_counts.items():
            lines.append(f"{str(name):<52} {count:>10,}")

    lines.extend(
        [
            "",
            "FAILED REQUIREMENT REASONS",
            "-" * 72,
        ]
    )

    for name, count in normalized_reason_counter.most_common(30):
        lines.append(f"{name:<52} {count:>10,}")

    lines.extend(
        [
            "",
            "FAILED RESOURCE CATEGORIES",
            "-" * 72,
        ]
    )

    for name, count in category_counter.most_common():
        lines.append(f"{name:<52} {count:>10,}")

    lines.extend(
        [
            "",
            "FAILED CATEGORY + REQUIREMENT TYPE",
            "-" * 72,
        ]
    )

    for (category, requirement_type), count in (
        category_type_counter.most_common(40)
    ):
        label = f"{category}::{requirement_type}"
        lines.append(f"{label:<52} {count:>10,}")

    if protection_counts:
        lines.extend(
            [
                "",
                "PROTECTION-SPECIFIC DIAGNOSTIC",
                "-" * 72,
            ]
        )

        for name, count in protection_counts.most_common():
            lines.append(f"{name:<52} {count:>10,}")

    if not task_diag.empty:
        no_feasible = task_diag[
            ~task_diag["has_feasible_window"]
        ]

        primary_task_reasons = (
            no_feasible["primary_rejection_reason"]
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )

        primary_task_categories = (
            no_feasible["primary_failed_resource_category"]
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )

        primary_task_types = (
            no_feasible["primary_failed_requirement_type"]
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )

        lines.extend(
            [
                "",
                "ZERO-FEASIBLE-WINDOW TASKS: PRIMARY REASON",
                "-" * 72,
            ]
        )

        for name, count in primary_task_reasons.items():
            lines.append(f"{name:<52} {count:>10,}")

        lines.extend(
            [
                "",
                "ZERO-FEASIBLE-WINDOW TASKS: PRIMARY RESOURCE CATEGORY",
                "-" * 72,
            ]
        )

        for name, count in primary_task_categories.items():
            lines.append(f"{name:<52} {count:>10,}")

        lines.extend(
            [
                "",
                "ZERO-FEASIBLE-WINDOW TASKS: PRIMARY REQUIREMENT TYPE",
                "-" * 72,
            ]
        )

        for name, count in primary_task_types.items():
            lines.append(f"{name:<52} {count:>10,}")

    lines.extend(
        [
            "",
            "INTERPRETATION GUIDE",
            "-" * 72,
            (
                "If WINDOW_EXTENDS_OUTSIDE_PROTECTION_SHIFT dominates, the "
                "current conservative no-handover protection model is the "
                "main V3.11 capacity limiter."
            ),
            (
                "If POWER_ISOLATION_SUPPORT_NOT_TIME_READY or other crew-time "
                "failures dominate, inspect exact shift coverage before "
                "changing the optimizer."
            ),
            (
                "If failures remain spread across many real resource types "
                "after the expanded V3.5 pool, V3.11 is probably exposing "
                "genuine prototype resource/time limits rather than a shortlist "
                "artifact."
            ),
            (
                "This diagnostic does not weaken any safety gate and does not "
                "change the planning outputs."
            ),
        ]
    )

    REPORT_OUTPUT.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("\nTop failed requirement reasons:")
    for name, count in normalized_reason_counter.most_common(12):
        print(f"  {name:<52} {count:>8,}")

    print("\nTop failed resource category/type:")
    for (category, requirement_type), count in (
        category_type_counter.most_common(12)
    ):
        print(
            f"  {category}::{requirement_type:<36} {count:>8,}"
        )

    if protection_counts:
        print("\nProtection-specific diagnosis:")
        for name, count in protection_counts.most_common():
            print(f"  {name:<52} {count:>8,}")

    if not task_diag.empty:
        no_feasible = task_diag[
            ~task_diag["has_feasible_window"]
        ]

        print(
            f"\nTasks with zero V3.11-feasible windows : "
            f"{len(no_feasible):,}"
        )

        print("\nTheir primary failed requirement types:")
        type_counts = (
            no_feasible["primary_failed_requirement_type"]
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )

        for name, count in type_counts.head(12).items():
            print(f"  {name:<44} {count:>8,}")

    print("\nOutputs:")
    print(f"  {DETAIL_OUTPUT}")
    print(f"  {TASK_OUTPUT}")
    print(f"  {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
