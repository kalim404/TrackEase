
"""
TrackEase V3.11 Fix A - Continuous Prototype Crew Coverage

Rebalances the EXISTING prototype Engineering, S&T and Electrical crews across
EARLY / DAY / LATE shifts so the generated resource layer no longer contains
artificial 04:00-08:00 and 16:00-20:00 departmental coverage gaps.

No crews are added. No skills, departments, bases, duty limits or rest-day
availability flags are invented or removed.

Protection already uses EARLY / DAY / LATE and is left unchanged.

The script:
- backs up v3_crews.csv and v3_crew_availability.csv once;
- balances shifts using existing skill mappings where available;
- updates shift_pattern + shift_start/shift_end only;
- preserves the existing weekday/rest-day availability rows;
- writes a transparent report.

This is PROTOTYPE GENERATED resource policy, not an official Indian Railways
staffing roster.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import shutil

import pandas as pd


PROJECT_ROOT = Path.cwd()
PROCESSED = PROJECT_ROOT / "data" / "processed"

CREWS_FILE = PROCESSED / "v3_crews.csv"
AVAILABILITY_FILE = PROCESSED / "v3_crew_availability.csv"
SKILLS_FILE = PROCESSED / "v3_crew_skills.csv"

CREWS_BACKUP = PROCESSED / "v3_crews.csv.bak_before_continuous_shift_model"
AVAILABILITY_BACKUP = (
    PROCESSED / "v3_crew_availability.csv.bak_before_continuous_shift_model"
)
REPORT_FILE = PROCESSED / "v3_crew_shift_coverage_fix_report.txt"

TARGET_DEPARTMENTS = {
    "Engineering",
    "S&T",
    "Electrical",
}

SHIFT_TIMES = {
    "EARLY": ("00:00", "08:00"),
    "DAY": ("08:00", "16:00"),
    "LATE": ("16:00", "00:00"),
}

SHIFT_ORDER = ("EARLY", "DAY", "LATE")


def clean(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{label} missing required columns: {missing}\n"
            f"Available: {frame.columns.tolist()}"
        )


def main() -> None:
    print("=" * 72)
    print("TrackEase V3.11 Fix A - Continuous Prototype Crew Coverage")
    print("=" * 72)

    if not CREWS_FILE.exists() or not AVAILABILITY_FILE.exists():
        raise FileNotFoundError(
            "Required resource files are missing. Expected:\n"
            f"  {CREWS_FILE}\n"
            f"  {AVAILABILITY_FILE}"
        )

    crews = pd.read_csv(CREWS_FILE, low_memory=False)
    availability = pd.read_csv(AVAILABILITY_FILE, low_memory=False)

    require_columns(
        crews,
        ["crew_id", "department", "shift_pattern"],
        "v3_crews.csv",
    )
    require_columns(
        availability,
        ["crew_id", "shift_start", "shift_end"],
        "v3_crew_availability.csv",
    )

    if not CREWS_BACKUP.exists():
        shutil.copy2(CREWS_FILE, CREWS_BACKUP)

    if not AVAILABILITY_BACKUP.exists():
        shutil.copy2(AVAILABILITY_FILE, AVAILABILITY_BACKUP)

    skills_by_crew: dict[str, set[str]] = defaultdict(set)

    if SKILLS_FILE.exists():
        skills = pd.read_csv(SKILLS_FILE, low_memory=False)
        if {"crew_id", "skill_code"}.issubset(skills.columns):
            for row in skills.itertuples(index=False):
                crew_id = clean(getattr(row, "crew_id"))
                skill = clean(getattr(row, "skill_code"))
                if crew_id and skill:
                    skills_by_crew[crew_id].add(skill)

    before_counts = (
        crews.groupby(["department", "shift_pattern"])
        .size()
        .to_dict()
    )

    assigned_shift: dict[str, str] = {}

    for department in sorted(TARGET_DEPARTMENTS):
        department_rows = crews[
            crews["department"].astype(str).eq(department)
        ].copy()

        if department_rows.empty:
            continue

        # Process multi-skilled crews first so their capabilities are spread
        # across shifts instead of accidentally clustering.
        records = department_rows.to_dict(orient="records")
        records.sort(
            key=lambda row: (
                -len(skills_by_crew.get(clean(row["crew_id"]), set())),
                clean(row.get("base_station_code")),
                clean(row["crew_id"]),
            )
        )

        total_count = {shift: 0 for shift in SHIFT_ORDER}
        skill_count: dict[str, dict[str, int]] = defaultdict(
            lambda: {shift: 0 for shift in SHIFT_ORDER}
        )

        for row in records:
            crew_id = clean(row["crew_id"])
            crew_skills = skills_by_crew.get(crew_id, set())

            def shift_score(shift: str) -> tuple:
                # Prefer the shift with the least representation of this crew's
                # existing skills, then the least total crew count.
                skill_pressure = sum(
                    skill_count[skill][shift]
                    for skill in crew_skills
                )
                max_skill_pressure = max(
                    [skill_count[skill][shift] for skill in crew_skills]
                    or [0]
                )
                return (
                    max_skill_pressure,
                    skill_pressure,
                    total_count[shift],
                    SHIFT_ORDER.index(shift),
                )

            chosen = min(SHIFT_ORDER, key=shift_score)
            assigned_shift[crew_id] = chosen
            total_count[chosen] += 1

            for skill in crew_skills:
                skill_count[skill][chosen] += 1

    # Protection stays as generated. Ordinary target departments receive the
    # balanced continuous-coverage model.
    for index, row in crews.iterrows():
        crew_id = clean(row["crew_id"])
        if crew_id in assigned_shift:
            crews.at[index, "shift_pattern"] = assigned_shift[crew_id]

    # Keep the exact existing availability row count and rest-day flags; only
    # the crew's shift clock changes.
    crew_shift_lookup = {
        clean(row["crew_id"]): clean(row["shift_pattern"])
        for row in crews.to_dict(orient="records")
    }

    unknown_shift_crews = set()

    for index, row in availability.iterrows():
        crew_id = clean(row["crew_id"])
        shift = crew_shift_lookup.get(crew_id, "")

        if shift not in SHIFT_TIMES:
            unknown_shift_crews.add(crew_id)
            continue

        start, end = SHIFT_TIMES[shift]
        availability.at[index, "shift_start"] = start
        availability.at[index, "shift_end"] = end

    if unknown_shift_crews:
        raise RuntimeError(
            "Some crews have unsupported shift labels after balancing: "
            + ", ".join(sorted(unknown_shift_crews)[:20])
        )

    after_counts = (
        crews.groupby(["department", "shift_pattern"])
        .size()
        .to_dict()
    )

    crews.to_csv(CREWS_FILE, index=False)
    availability.to_csv(AVAILABILITY_FILE, index=False)

    lines = [
        "=" * 72,
        "TrackEase V3 Crew Shift Coverage Fix Report",
        "=" * 72,
        "",
        "POLICY",
        "-" * 72,
        "Existing crews only; no crew count increased.",
        "Engineering/S&T/Electrical redistributed across:",
        "  EARLY 00:00-08:00",
        "  DAY   08:00-16:00",
        "  LATE  16:00-00:00",
        "Protection shift allocation retained.",
        "Existing rest-day/weekday availability flags retained.",
        "",
        "BEFORE",
        "-" * 72,
    ]

    for (department, shift), count in sorted(before_counts.items()):
        lines.append(f"{department:<20} {shift:<10} {count:>5}")

    lines.extend(["", "AFTER", "-" * 72])

    for (department, shift), count in sorted(after_counts.items()):
        lines.append(f"{department:<20} {shift:<10} {count:>5}")

    lines.extend(
        [
            "",
            "PROVENANCE",
            "-" * 72,
            "data_origin      : PROTOTYPE_GENERATED",
            "integration_mode : DETERMINISTIC_CONTINUOUS_SHIFT_COVERAGE_POLICY",
            (
                "Important: This is a prototype staffing-availability model, "
                "not an official Indian Railways roster."
            ),
        ]
    )

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")

    print("\nUpdated shift distribution:")
    display = (
        crews.groupby(["department", "shift_pattern"])
        .size()
        .reset_index(name="count")
    )
    print(display.to_string(index=False))

    print("\nIntegrity:")
    print(f"  Crew rows preserved        : {len(crews):,}")
    print(f"  Availability rows preserved: {len(availability):,}")
    print(f"  Unknown shift crews        : {len(unknown_shift_crews):,}")

    print("\nOutputs:")
    print(f"  {CREWS_FILE}")
    print(f"  {AVAILABILITY_FILE}")
    print(f"  {REPORT_FILE}")


if __name__ == "__main__":
    main()
