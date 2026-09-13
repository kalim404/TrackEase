
"""
TrackEase V3.11 - Handover-Aware Exact Resource/Safety Validator

This wrapper preserves the existing V3.11 validator and changes ONLY the crew
requirement selection behavior when no single qualified crew can cover the
whole block.

Policy:
1. First run the original V3.11 resource selection unchanged.
2. If it succeeds, keep its result.
3. If it fails for a crew-backed requirement, try a continuous coverage chain
   of already-qualified V3.5 crew candidates.
4. Every minute of the block must remain covered.
5. Every selected crew must be AVAILABLE and inside its own availability
   interval.
6. Each crew's own coverage segment must respect its max-work limit.
7. Handover is explicit and recorded; uncovered gaps are never accepted.
8. Long-distance mobilisation remains flagged as repositioning.
9. Maximum chain size is finite to prevent unrealistic chaining.

No train/goods/section/infrastructure/machine/equipment/material/dependency safety
gate from the base V3.11 validator is bypassed.

This is prototype feasibility logic. Actual railway protection/technical
handover remains subject to authorized rules and human approval.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import math


BASE_FILE = Path(__file__).with_name(
    "validate_v3_candidate_resource_safety.py"
)

if not BASE_FILE.exists():
    raise FileNotFoundError(
        f"Base V3.11 validator not found: {BASE_FILE}"
    )

spec = importlib.util.spec_from_file_location(
    "trackease_v3_11_base",
    BASE_FILE,
)

if spec is None or spec.loader is None:
    raise RuntimeError("Could not load base V3.11 validator.")

base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

ORIGINAL_SELECT = base.select_resource_for_requirement

MAX_CREWS_PER_HANDOVER_CHAIN = 4
EPSILON = 1e-6


def clean(value: object) -> str:
    return base.clean_text(value)


def safe_number(value: object, default: float = 0.0) -> float:
    result = base.safe_float(value)
    if result is None or not math.isfinite(float(result)):
        return default
    return float(result)


def crew_like_requirement(requirement: dict) -> bool:
    category = clean(
        requirement.get("resource_category")
    ).upper()

    requirement_type = clean(
        requirement.get("requirement_type")
    ).upper()

    return (
        category == "CREW"
        or (
            category == "OPERATIONAL_PREREQUISITE"
            and requirement_type == "POWER_ISOLATION"
        )
    )


def build_handover_chain(
    requirement: dict,
    assignments: list[dict],
    crew_lookup: dict[str, dict],
    availability_index: dict[
        str,
        list[tuple[float, float]]
    ],
    window_start: float,
    window_end: float,
):
    """
    Greedy minimum-chain interval cover.

    Assignments are already V3.5 requirement-specific candidates, so skill,
    department and reachability filtering has already happened upstream.
    """
    candidate_segments = []

    for assignment in assignments:
        crew_id = clean(
            assignment.get("resource_id")
        )

        crew = crew_lookup.get(crew_id)

        if crew is None:
            continue

        if clean(
            crew.get("status")
        ).upper() != "AVAILABLE":
            continue

        max_work = safe_number(
            crew.get("max_work_minutes_per_shift"),
            480.0,
        )

        if max_work <= 0:
            continue

        intervals = availability_index.get(
            crew_id,
            [],
        )

        travel = max(
            0.0,
            safe_number(
                assignment.get("travel_minutes_proxy"),
                0.0,
            ),
        )

        source_repositioning = (
            clean(
                assignment.get("readiness_status")
            ).upper()
            == "REPOSITIONING_REQUIRED"
        )

        for interval_start, interval_end in intervals:
            overlap_start = max(
                float(interval_start),
                window_start,
            )

            overlap_end = min(
                float(interval_end),
                window_end,
            )

            if overlap_end <= overlap_start + EPSILON:
                continue

            candidate_segments.append(
                {
                    "crew_id": crew_id,
                    "assignment": assignment,
                    "interval_start": float(interval_start),
                    "interval_end": float(interval_end),
                    "max_work": max_work,
                    "travel": travel,
                    "source_repositioning": source_repositioning,
                }
            )

    cursor = window_start
    chain = []
    used_crew_ids = set()

    while cursor < window_end - EPSILON:
        best = None
        best_end = cursor

        for item in candidate_segments:
            crew_id = item["crew_id"]

            if crew_id in used_crew_ids:
                continue

            interval_start = item["interval_start"]
            interval_end = item["interval_end"]

            if interval_start > cursor + EPSILON:
                continue

            if interval_end <= cursor + EPSILON:
                continue

            coverage_end = min(
                interval_end,
                cursor + item["max_work"],
                window_end,
            )

            if coverage_end <= cursor + EPSILON:
                continue

            tie_key = (
                coverage_end,
                -int(item["source_repositioning"]),
                -item["travel"],
                crew_id,
            )

            if (
                best is None
                or tie_key > best["tie_key"]
            ):
                best = {
                    **item,
                    "coverage_start": cursor,
                    "coverage_end": coverage_end,
                    "tie_key": tie_key,
                }
                best_end = coverage_end

        if best is None:
            return None

        chain.append(best)
        used_crew_ids.add(best["crew_id"])
        cursor = best_end

        if len(chain) > MAX_CREWS_PER_HANDOVER_CHAIN:
            return None

    if cursor < window_end - EPSILON:
        return None

    return chain


def make_handover_selection(
    window_id: str,
    task_id: str,
    requirement: dict,
    chain: list[dict],
):
    first_assignment = dict(chain[0]["assignment"])

    requirement_id = clean(
        requirement.get("requirement_id")
    )

    requirement_type = clean(
        requirement.get("requirement_type")
    )

    resource_category = clean(
        requirement.get("resource_category")
    )

    crew_ids = [
        item["crew_id"]
        for item in chain
    ]

    repositioning_required = any(
        item["source_repositioning"]
        or (
            item["interval_start"]
            > item["coverage_start"] - item["travel"] + EPSILON
        )
        for item in chain
    )

    coverage_segments = "|".join(
        (
            f"{item['crew_id']}@"
            f"{item['coverage_start']:.0f}-"
            f"{item['coverage_end']:.0f}"
        )
        for item in chain
    )

    selected = dict(first_assignment)

    # Include both naming styles used across TrackEase V3 artifacts.
    selected.update(
        {
            "candidate_window_id": window_id,
            "task_id": task_id,
            "requirement_id": requirement_id,
            "requirement_type": requirement_type,
            "resource_category": resource_category,
            "resource_id": "|".join(crew_ids),
            "resource_type": "CREW_HANDOVER_CHAIN",
            "selected_resource_id": "|".join(crew_ids),
            "selected_resource_type": "CREW_HANDOVER_CHAIN",
            "repositioning_required": repositioning_required,
            "exact_time_status": (
                "EXACT_CREW_HANDOVER_REPOSITIONING_REQUIRED"
                if repositioning_required
                else "EXACT_CREW_HANDOVER_READY"
            ),
            "evaluation_reason": "CONTINUOUS_CREW_HANDOVER_COVERAGE",
            "handover_required": True,
            "handover_count": max(0, len(chain) - 1),
            "handover_resource_ids": "|".join(crew_ids),
            "handover_coverage_segments": coverage_segments,
            "handover_policy": (
                "CONTINUOUS_NO_GAP_QUALIFIED_CREW_CHAIN"
            ),
        }
    )

    return selected


def handover_aware_select(
    window_id,
    task_id,
    requirement,
    assignments,
    crew_lookup,
    crew_availability_index,
    machine_lookup,
    machine_availability_index,
    equipment_lookup,
    material_lookup,
    window_start,
    window_end,
):
    # Preserve every existing V3.11 rule first.
    selected, failures = ORIGINAL_SELECT(
        window_id,
        task_id,
        requirement,
        assignments,
        crew_lookup,
        crew_availability_index,
        machine_lookup,
        machine_availability_index,
        equipment_lookup,
        material_lookup,
        window_start,
        window_end,
    )

    if selected is not None:
        # Make handover fields explicit even for single-resource cases so the
        # output remains easy to consume later.
        selected = dict(selected)
        selected.setdefault("handover_required", False)
        selected.setdefault("handover_count", 0)
        selected.setdefault("handover_resource_ids", "")
        selected.setdefault("handover_coverage_segments", "")
        selected.setdefault("handover_policy", "")
        return selected, failures

    if not crew_like_requirement(requirement):
        return selected, failures

    chain = build_handover_chain(
        requirement,
        assignments,
        crew_lookup,
        crew_availability_index,
        float(window_start),
        float(window_end),
    )

    if chain is None or len(chain) < 2:
        return selected, failures

    handover_selection = make_handover_selection(
        window_id,
        task_id,
        requirement,
        chain,
    )

    return (
        handover_selection,
        [],
    )


# Monkey-patch ONLY the requirement selector. base.main() retains every other
# existing V3.11 safety and integrity check.
base.select_resource_for_requirement = handover_aware_select


if __name__ == "__main__":
    print("=" * 72)
    print("TrackEase V3.11 - Handover-Aware Validator")
    print("=" * 72)
    print(
        "\nBase V3.11 safety logic retained; continuous qualified crew "
        "handover enabled only when single-crew coverage fails.\n"
    )
    base.main()
