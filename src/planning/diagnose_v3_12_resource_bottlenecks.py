"""
TrackEase V3.12 - Resource Double-Booking Bottleneck Diagnostic

Purpose
-------
Diagnose why tasks that already passed V3.11 still remain unscheduled in the
dynamic V3.12 optimizer.

For each UNSCHEDULED_AFTER_OPTIMIZATION task, this script checks every
V3.11-feasible candidate window and every exact-time-safe resource option.
It identifies requirement slots where ALL resource alternatives overlap
resources already booked in the final V3.12 schedule.

This is read-only. It does not modify planning outputs.

Outputs
-------
    data/processed/v3_12_resource_bottleneck_diagnostics.csv
    data/processed/v3_12_resource_bottleneck_report.txt
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import math

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

UNSCHEDULED_FILE = (
    PROCESSED_DIR / "v3_optimizer_unscheduled_tasks.csv"
)
OPTIONS_FILE = (
    PROCESSED_DIR / "v3_optimizer_resource_options.csv"
)
BOOKINGS_FILE = (
    PROCESSED_DIR / "v3_optimizer_resource_bookings.csv"
)

OUTPUT_FILE = (
    PROCESSED_DIR / "v3_12_resource_bottleneck_diagnostics.csv"
)
REPORT_FILE = (
    PROCESSED_DIR / "v3_12_resource_bottleneck_report.txt"
)

MINUTES_PER_WEEK = 10080


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def cyclic_overlap(
    start_a: float,
    end_a: float,
    start_b: float,
    end_b: float,
) -> bool:
    for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
        shifted_start = start_b + shift
        shifted_end = end_b + shift

        if start_a < shifted_end and end_a > shifted_start:
            return True

    return False


def main() -> None:
    print("=" * 72)
    print("TrackEase V3.12 - Resource Double-Booking Bottleneck Diagnostic")
    print("=" * 72)

    for path in [
        UNSCHEDULED_FILE,
        OPTIONS_FILE,
        BOOKINGS_FILE,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    unscheduled = pd.read_csv(
        UNSCHEDULED_FILE,
        low_memory=False,
    )

    options = pd.read_csv(
        OPTIONS_FILE,
        low_memory=False,
    )

    bookings = pd.read_csv(
        BOOKINGS_FILE,
        low_memory=False,
    )

    target_tasks = set(
        unscheduled.loc[
            (
                unscheduled["optimizer_status"]
                .astype(str)
                .eq("UNSCHEDULED_AFTER_OPTIMIZATION")
            )
            & (
                unscheduled["primary_reason"]
                .astype(str)
                .eq("RESOURCE_DOUBLE_BOOKING")
            ),
            "task_id",
        ].astype(str)
    )

    print(
        f"\nDouble-booking unscheduled tasks : {len(target_tasks):,}"
    )
    print(
        f"Exact-time option rows           : {len(options):,}"
    )
    print(
        f"Final resource booking rows      : {len(bookings):,}"
    )

    if not target_tasks:
        print("\nNo RESOURCE_DOUBLE_BOOKING tasks found.")
        return

    options = options[
        options["task_id"]
        .astype(str)
        .isin(target_tasks)
    ].copy()

    bookings_by_resource: dict[
        str,
        list[dict]
    ] = defaultdict(list)

    for row in bookings.to_dict(
        orient="records"
    ):
        resource_id = clean(
            row.get("resource_id")
        )

        if resource_id:
            bookings_by_resource[
                resource_id
            ].append(row)

    diagnostics = []
    blocked_resource_counter = Counter()
    blocked_category_counter = Counter()
    blocked_type_counter = Counter()
    task_primary_counter = Counter()

    options_by_task = {
        task_id: group
        for task_id, group in options.groupby("task_id")
    }

    for task_id in sorted(target_tasks):
        task_options = options_by_task.get(task_id)

        if task_options is None or task_options.empty:
            diagnostics.append(
                {
                    "task_id": task_id,
                    "candidate_window_id": "",
                    "requirement_id": "",
                    "resource_category": "",
                    "requirement_type": "",
                    "option_count": 0,
                    "blocked_option_count": 0,
                    "all_options_blocked": False,
                    "blocked_resource_ids": "",
                    "diagnosis": "NO_EXACT_TIME_RESOURCE_OPTIONS_FOUND",
                }
            )
            task_primary_counter[
                "NO_EXACT_TIME_RESOURCE_OPTIONS_FOUND"
            ] += 1
            continue

        candidate_groups = {
            candidate_id: group
            for candidate_id, group
            in task_options.groupby("candidate_window_id")
        }

        task_blocked_slots = Counter()

        for candidate_id, candidate_options in candidate_groups.items():
            for requirement_id, slot in candidate_options.groupby(
                "requirement_id"
            ):
                first = slot.iloc[0]

                window_start = number(
                    first.get("window_start_minute_week")
                )
                window_end = number(
                    first.get("window_end_minute_week")
                )

                blocked_ids = []
                free_ids = []

                for option in slot.to_dict(orient="records"):
                    resource_id = clean(
                        option.get("resource_id")
                    )

                    category = clean(
                        option.get("resource_category")
                    ).upper()

                    if category == "MATERIAL":
                        free_ids.append(resource_id)
                        continue

                    travel = max(
                        0.0,
                        number(
                            option.get("travel_minutes_proxy")
                        ),
                    )

                    proposed_start = (
                        window_start - travel
                    )
                    proposed_end = window_end

                    conflicts = []

                    for booking in bookings_by_resource.get(
                        resource_id,
                        [],
                    ):
                        booking_task = clean(
                            booking.get("task_id")
                        )

                        if booking_task == task_id:
                            continue

                        booking_start = number(
                            booking.get("booking_start")
                        )
                        booking_end = number(
                            booking.get("booking_end")
                        )

                        if cyclic_overlap(
                            proposed_start,
                            proposed_end,
                            booking_start,
                            booking_end,
                        ):
                            conflicts.append(
                                booking_task
                            )

                    if conflicts:
                        blocked_ids.append(
                            resource_id
                        )
                        blocked_resource_counter[
                            resource_id
                        ] += 1
                    else:
                        free_ids.append(
                            resource_id
                        )

                all_blocked = (
                    len(slot) > 0
                    and len(free_ids) == 0
                )

                category = clean(
                    first.get("resource_category")
                )

                requirement_type = clean(
                    first.get("requirement_type")
                )

                if all_blocked:
                    blocked_category_counter[
                        category
                    ] += 1

                    blocked_type_counter[
                        (
                            category,
                            requirement_type,
                        )
                    ] += 1

                    task_blocked_slots[
                        (
                            category,
                            requirement_type,
                        )
                    ] += 1

                diagnostics.append(
                    {
                        "task_id": task_id,
                        "candidate_window_id": candidate_id,
                        "requirement_id": requirement_id,
                        "resource_category": category,
                        "requirement_type": requirement_type,
                        "option_count": len(slot),
                        "blocked_option_count": len(blocked_ids),
                        "free_option_count": len(free_ids),
                        "all_options_blocked": all_blocked,
                        "blocked_resource_ids": "|".join(
                            sorted(set(blocked_ids))
                        ),
                        "free_resource_ids": "|".join(
                            sorted(set(free_ids))
                        ),
                        "diagnosis": (
                            "ALL_OPTIONS_DOUBLE_BOOKED"
                            if all_blocked
                            else "AT_LEAST_ONE_OPTION_FREE"
                        ),
                    }
                )

        if task_blocked_slots:
            primary = task_blocked_slots.most_common(1)[0][0]
            task_primary_counter[
                f"{primary[0]}::{primary[1]}"
            ] += 1
        else:
            task_primary_counter[
                "NO_ALL-BLOCKED_SLOT_IN_FINAL_STATE"
            ] += 1

    diagnostics_df = pd.DataFrame(diagnostics)

    diagnostics_df.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    all_blocked_df = diagnostics_df[
        diagnostics_df["all_options_blocked"]
        .astype(bool)
    ].copy()

    report = [
        "=" * 72,
        "TrackEase V3.12 Resource Double-Booking Bottleneck Report",
        "=" * 72,
        "",
        f"Double-booking unscheduled tasks : {len(target_tasks):,}",
        f"Diagnostic requirement slots     : {len(diagnostics_df):,}",
        f"Fully blocked requirement slots  : {len(all_blocked_df):,}",
        "",
        "PRIMARY BLOCKER BY TASK",
        "-" * 72,
    ]

    for name, count in task_primary_counter.most_common():
        report.append(
            f"{name:<48} {count:>10,}"
        )

    report.extend(
        [
            "",
            "FULLY BLOCKED SLOTS BY CATEGORY",
            "-" * 72,
        ]
    )

    for name, count in blocked_category_counter.most_common():
        report.append(
            f"{name:<48} {count:>10,}"
        )

    report.extend(
        [
            "",
            "FULLY BLOCKED SLOTS BY REQUIREMENT TYPE",
            "-" * 72,
        ]
    )

    for (category, requirement_type), count in (
        blocked_type_counter.most_common()
    ):
        label = f"{category}::{requirement_type}"
        report.append(
            f"{label:<48} {count:>10,}"
        )

    report.extend(
        [
            "",
            "MOST COMMON BLOCKED RESOURCE IDS",
            "-" * 72,
        ]
    )

    for resource_id, count in blocked_resource_counter.most_common(30):
        report.append(
            f"{resource_id:<48} {count:>10,}"
        )

    report.extend(
        [
            "",
            "INTERPRETATION",
            "-" * 72,
            (
                "A fully blocked requirement slot means every exact-time-safe "
                "resource option currently available to that requirement "
                "overlaps a resource already selected in the final schedule."
            ),
            (
                "If equipment/machine/crew categories dominate, the next fix "
                "should widen or diversify that resource candidate pool rather "
                "than weaken safety or allow double-booking."
            ),
            (
                "NO_ALL-BLOCKED_SLOT_IN_FINAL_STATE can occur because the "
                "optimizer is sequential: a resource conflict existed when the "
                "task was considered, but the final diagnostic state does not "
                "reconstruct the exact intermediate search state."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    print("\nPrimary blocker by task:")
    for name, count in task_primary_counter.most_common(12):
        print(f"  {name:<48} {count:>8,}")

    print("\nFully blocked slots by category:")
    for name, count in blocked_category_counter.most_common():
        print(f"  {name:<24} {count:>8,}")

    print("\nTop blocked resource IDs:")
    for resource_id, count in blocked_resource_counter.most_common(15):
        print(f"  {resource_id:<32} {count:>8,}")

    print("\nOutputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")


if __name__ == "__main__":
    main()
