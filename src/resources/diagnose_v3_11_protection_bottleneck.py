"""
TrackEase V3.11 - Protection Resource Bottleneck Diagnostic

Read-only diagnostic for the dominant V3.11 rejection reason:
PROTECTION_CREW_NOT_TIME_READY.

Creates:
    data/processed/v3_11_protection_bottleneck_diagnostics.csv
    data/processed/v3_11_protection_bottleneck_report.txt

This script does not modify any existing planning/resource file.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

REJECTIONS_FILE = PROCESSED_DIR / "v3_candidate_window_rejections.csv"
REQUIREMENTS_FILE = PROCESSED_DIR / "v3_task_resource_requirements.csv"
ASSIGNMENTS_FILE = PROCESSED_DIR / "v3_resource_assignment_candidates.csv"
CREWS_FILE = PROCESSED_DIR / "v3_crews.csv"
CREW_AVAILABILITY_FILE = PROCESSED_DIR / "v3_crew_availability.csv"

OUTPUT_FILE = (
    PROCESSED_DIR / "v3_11_protection_bottleneck_diagnostics.csv"
)
REPORT_FILE = (
    PROCESSED_DIR / "v3_11_protection_bottleneck_report.txt"
)

MINUTES_PER_DAY = 1440
MINUTES_PER_WEEK = 10080

DAY_MAP = {
    "MON": 0, "MONDAY": 0,
    "TUE": 1, "TUES": 1, "TUESDAY": 1,
    "WED": 2, "WEDNESDAY": 2,
    "THU": 3, "THUR": 3, "THURSDAY": 3,
    "FRI": 4, "FRIDAY": 4,
    "SAT": 5, "SATURDAY": 5,
    "SUN": 6, "SUNDAY": 6,
}


def clean(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def hhmm(value, end=False):
    text = clean(value)
    if ":" not in text:
        return None
    try:
        hour, minute = map(int, text.split(":")[:2])
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if end and hour == 23 and minute == 59:
        return 1440
    return hour * 60 + minute


def weekday(value):
    return DAY_MAP.get(clean(value).upper())


def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals)
    result = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return [(float(a), float(b)) for a, b in result]


def build_availability(availability):
    index = defaultdict(list)

    for row in availability.to_dict("records"):
        if not to_bool(row.get("available")):
            continue

        crew_id = clean(row.get("crew_id"))
        day = weekday(row.get("weekday"))
        start = hhmm(row.get("shift_start"))
        end = hhmm(row.get("shift_end"), end=True)

        if not crew_id or day is None or start is None or end is None:
            continue

        abs_start = day * MINUTES_PER_DAY + start
        abs_end = day * MINUTES_PER_DAY + end

        if abs_end <= abs_start:
            abs_end += MINUTES_PER_DAY

        for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
            index[crew_id].append(
                (abs_start + shift, abs_end + shift)
            )

    return {
        crew_id: merge_intervals(intervals)
        for crew_id, intervals in index.items()
    }


def covered(intervals, start, end):
    return any(
        interval_start <= start and interval_end >= end
        for interval_start, interval_end in intervals
    )


def main():
    print("=" * 72)
    print("TrackEase V3.11 - Protection Crew Bottleneck Diagnostic")
    print("=" * 72)

    for path in [
        REJECTIONS_FILE,
        REQUIREMENTS_FILE,
        ASSIGNMENTS_FILE,
        CREWS_FILE,
        CREW_AVAILABILITY_FILE,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    rejections = pd.read_csv(REJECTIONS_FILE, low_memory=False)
    requirements = pd.read_csv(REQUIREMENTS_FILE, low_memory=False)
    assignments = pd.read_csv(ASSIGNMENTS_FILE, low_memory=False)
    crews = pd.read_csv(CREWS_FILE, low_memory=False)
    availability = pd.read_csv(CREW_AVAILABILITY_FILE, low_memory=False)

    protection_requirements = requirements[
        requirements["requirement_type"]
        .astype(str)
        .str.upper()
        .eq("PROTECTION_CREW")
    ].copy()

    protection_req_ids = set(
        protection_requirements["requirement_id"].astype(str)
    )

    protection_assignments = assignments[
        assignments["requirement_id"]
        .astype(str)
        .isin(protection_req_ids)
    ].copy()

    protection_crew_ids = set(
        protection_assignments["resource_id"]
        .astype(str)
    )

    # Also identify crews explicitly belonging to Protection, where available.
    if "department" in crews.columns:
        explicit_protection = crews[
            crews["department"]
            .astype(str)
            .str.upper()
            .str.contains("PROTECTION", na=False)
        ]
        protection_crew_ids.update(
            explicit_protection["crew_id"].astype(str)
        )

    crew_lookup = (
        crews.drop_duplicates("crew_id")
        .set_index("crew_id")
        .to_dict("index")
    )

    availability_index = build_availability(availability)

    assignments_by_requirement = defaultdict(list)
    for row in protection_assignments.to_dict("records"):
        assignments_by_requirement[
            clean(row.get("requirement_id"))
        ].append(row)

    protection_req_by_task = defaultdict(list)
    for row in protection_requirements.to_dict("records"):
        protection_req_by_task[
            clean(row.get("task_id"))
        ].append(
            clean(row.get("requirement_id"))
        )

    failed = rejections[
        rejections["base_rejection_reasons"]
        .astype(str)
        .str.contains(
            "PROTECTION_CREW_NOT_TIME_READY",
            na=False,
        )
    ].copy()

    diagnostics = []

    for row in failed.to_dict("records"):
        task_id = clean(row.get("task_id"))
        window_id = clean(row.get("candidate_window_id"))

        try:
            start = float(row.get("window_start_minute_week"))
            end = float(row.get("window_end_minute_week"))
        except (TypeError, ValueError):
            continue

        req_ids = protection_req_by_task.get(task_id, [])

        candidate_resources = []
        for req_id in req_ids:
            candidate_resources.extend(
                assignments_by_requirement.get(req_id, [])
            )

        if not candidate_resources:
            diagnosis = "NO_PROTECTION_ASSIGNMENT_CANDIDATE"
            exact_ready_count = 0
            total_candidates = 0
            available_day_count = 0
        else:
            exact_ready = []
            available_day_count = 0

            for candidate in candidate_resources:
                crew_id = clean(candidate.get("resource_id"))
                crew = crew_lookup.get(crew_id, {})

                if clean(crew.get("status")).upper() != "AVAILABLE":
                    continue

                intervals = availability_index.get(crew_id, [])

                if any(
                    interval_start <= start < interval_end
                    for interval_start, interval_end in intervals
                ):
                    available_day_count += 1

                max_work = crew.get("max_work_minutes_per_shift", 480)
                try:
                    max_work = float(max_work)
                except (TypeError, ValueError):
                    max_work = 480.0

                if (
                    end - start <= max_work
                    and covered(intervals, start, end)
                ):
                    exact_ready.append(crew_id)

            exact_ready_count = len(set(exact_ready))
            total_candidates = len({
                clean(item.get("resource_id"))
                for item in candidate_resources
                if clean(item.get("resource_id"))
            })

            if exact_ready_count > 0:
                diagnosis = (
                    "UNEXPECTED_PROTECTION_GATE_MISMATCH"
                )
            elif available_day_count > 0:
                diagnosis = (
                    "WINDOW_EXTENDS_OUTSIDE_PROTECTION_SHIFT"
                )
            else:
                diagnosis = (
                    "NO_PROTECTION_CREW_ON_DUTY_AT_WINDOW_START"
                )

        start_day = int(start // 1440) % 7
        start_hour = int((start % 1440) // 60)

        diagnostics.append(
            {
                "candidate_window_id": window_id,
                "task_id": task_id,
                "window_start_minute_week": start,
                "window_end_minute_week": end,
                "window_duration_minutes": end - start,
                "start_weekday_index": start_day,
                "start_hour": start_hour,
                "protection_requirement_count": len(req_ids),
                "protection_candidate_crew_count": total_candidates,
                "crews_on_duty_at_window_start": available_day_count,
                "exact_time_ready_protection_crew_count": exact_ready_count,
                "diagnosis": diagnosis,
            }
        )

    diagnostics_df = pd.DataFrame(diagnostics)
    diagnostics_df.to_csv(OUTPUT_FILE, index=False)

    # Shift-pattern summary for protection-related crews.
    protection_availability = availability[
        availability["crew_id"].astype(str).isin(protection_crew_ids)
    ].copy()

    shift_summary = (
        protection_availability[
            ["weekday", "shift_start", "shift_end", "available"]
        ]
        .astype(str)
        .value_counts()
        .reset_index(name="rows")
    )

    diagnosis_counts = (
        diagnostics_df["diagnosis"]
        .value_counts()
        if not diagnostics_df.empty
        else pd.Series(dtype="int64")
    )

    hour_counts = (
        diagnostics_df["start_hour"]
        .value_counts()
        .sort_index()
        if not diagnostics_df.empty
        else pd.Series(dtype="int64")
    )

    lines = [
        "=" * 72,
        "TrackEase V3.11 Protection Crew Bottleneck Diagnostic",
        "=" * 72,
        "",
        "SUMMARY",
        "-" * 72,
        f"Protection requirements             : {len(protection_requirements):,}",
        f"Protection assignment candidates     : {len(protection_assignments):,}",
        f"Protection-related crew IDs          : {len(protection_crew_ids):,}",
        f"Rejected windows with protection gate: {len(failed):,}",
        f"Diagnostic rows                      : {len(diagnostics_df):,}",
        "",
        "DIAGNOSIS",
        "-" * 72,
    ]

    if diagnosis_counts.empty:
        lines.append("No protection-gate failures found.")
    else:
        for name, count in diagnosis_counts.items():
            lines.append(f"{name:<48} {count:>10,}")

    lines.extend(
        [
            "",
            "FAILED WINDOW START HOUR DISTRIBUTION",
            "-" * 72,
        ]
    )

    for hour, count in hour_counts.items():
        lines.append(
            f"{int(hour):02d}:00-{int(hour):02d}:59"
            f"{'':<30} {count:>10,}"
        )

    lines.extend(
        [
            "",
            "PROTECTION CREW AVAILABILITY PATTERNS",
            "-" * 72,
        ]
    )

    if shift_summary.empty:
        lines.append("No protection crew availability rows found.")
    else:
        for row in shift_summary.head(40).itertuples(index=False):
            lines.append(
                f"{row.weekday:<10} "
                f"{row.shift_start:>5}-{row.shift_end:<5} "
                f"available={row.available:<5} "
                f"rows={row.rows:>4}"
            )

    lines.extend(
        [
            "",
            "INTERPRETATION GUIDE",
            "-" * 72,
            (
                "NO_PROTECTION_ASSIGNMENT_CANDIDATE: V3.5 did not produce a "
                "protection crew candidate for the requirement."
            ),
            (
                "NO_PROTECTION_CREW_ON_DUTY_AT_WINDOW_START: candidate crews "
                "exist, but none is on duty when the block begins."
            ),
            (
                "WINDOW_EXTENDS_OUTSIDE_PROTECTION_SHIFT: at least one crew is "
                "on duty at the start, but no single crew shift covers the whole "
                "maintenance block."
            ),
            (
                "UNEXPECTED_PROTECTION_GATE_MISMATCH: this diagnostic finds an "
                "exact-time-ready protection crew even though V3.11 rejected "
                "the protection gate; this requires a code fix before freeze."
            ),
        ]
    )

    REPORT_FILE.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print()
    print("Diagnostic classification:")
    if diagnosis_counts.empty:
        print("  No protection-gate failures found.")
    else:
        for name, count in diagnosis_counts.items():
            print(f"  {name:<48} {count:>8,}")

    unexpected = int(
        diagnosis_counts.get(
            "UNEXPECTED_PROTECTION_GATE_MISMATCH",
            0,
        )
    )

    print()
    print(f"Unexpected mismatches : {unexpected:,}")
    print()
    print("Outputs:")
    print(f"  {OUTPUT_FILE}")
    print(f"  {REPORT_FILE}")


if __name__ == "__main__":
    main()
