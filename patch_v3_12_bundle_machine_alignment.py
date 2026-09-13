
from pathlib import Path
import re
import shutil

PROJECT_ROOT = Path.cwd()
TARGET = PROJECT_ROOT / "src" / "planning" / "build_v3_optimizer_resource_bundles.py"
BACKUP = TARGET.with_suffix(".py.bak_before_v311_machine_alignment")
MARKER = "TRACKEASE_V311_MACHINE_SEMANTICS_ALIGNMENT"


def main():
    print("=" * 72)
    print("TrackEase V3.12A2 - Align Bundle Builder With V3.11 Machine Logic")
    print("=" * 72)

    if not TARGET.exists():
        raise FileNotFoundError(f"Target not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")

    if MARKER in text:
        compile(text, str(TARGET), "exec")
        print("\nPatch already applied.")
        print("Syntax check: PASS")
        return

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"\nBackup created:\n  {BACKUP}")

    if "import importlib.util" not in text:
        text = text.replace(
            "import math\n\nimport pandas as pd",
            "import math\nimport importlib.util\n\nimport pandas as pd",
            1,
        )

    anchor = 'INTEGRATION_MODE = "PROTOTYPE_RESOURCE_BUNDLE_ENUMERATION"\n'

    helper = r'''

# TRACKEASE_V311_MACHINE_SEMANTICS_ALIGNMENT
_V311_BASE_MODULE = None


def load_v311_base_module():
    global _V311_BASE_MODULE

    if _V311_BASE_MODULE is not None:
        return _V311_BASE_MODULE

    base_file = Path(__file__).with_name(
        "validate_v3_candidate_resource_safety.py"
    )

    if not base_file.exists():
        raise FileNotFoundError(
            f"Frozen/base V3.11 validator not found: {base_file}"
        )

    spec = importlib.util.spec_from_file_location(
        "trackease_v311_base_for_bundles",
        base_file,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            "Unable to load frozen/base V3.11 validator."
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _V311_BASE_MODULE = module
    return module
'''

    if anchor not in text:
        raise RuntimeError(
            "Could not find integration-mode anchor. No file was modified."
        )

    text = text.replace(anchor, anchor + helper, 1)

    pattern = re.compile(
        r"def enumerate_machine_bundles\("
        r".*?"
        r"\n\ndef enumerate_equipment_bundles\(",
        re.DOTALL,
    )

    replacement = r'''def enumerate_machine_bundles(
    options: list[dict],
    machine_lookup: dict[str, dict],
    availability: dict[str, list[tuple[float, float]]],
    window_start: float,
    window_end: float,
) -> list[list[dict]]:
    v311 = load_v311_base_module()

    bundles = []
    seen = set()

    for option in options:
        resource_id = get_resource_id(option)

        if not resource_id or resource_id in seen:
            continue

        exact_ready, repositioning_required, exact_reason = (
            v311.evaluate_machine_candidate(
                option,
                machine_lookup,
                availability,
                window_start,
                window_end,
            )
        )

        if not exact_ready:
            continue

        travel = get_travel(option)

        bundles.append(
            [
                {
                    "resource_id": resource_id,
                    "resource_type": "MACHINE",
                    "coverage_start": window_start,
                    "coverage_end": window_end,
                    "booking_start": window_start - travel,
                    "booking_end": window_end,
                    "travel_minutes": travel,
                    "repositioning_required": bool(
                        repositioning_required
                    ),
                    "source_candidate_rank": candidate_field(
                        option,
                        ["candidate_rank"],
                        "",
                    ),
                    "v3_11_exact_reason": exact_reason,
                }
            ]
        )

        seen.add(resource_id)

    bundles.sort(
        key=lambda bundle: (
            1 if bundle[0]["repositioning_required"] else 0,
            bundle[0]["travel_minutes"],
            bundle[0]["resource_id"],
        )
    )

    return bundles[:MAX_SINGLE_OPTIONS_PER_SLOT]


def enumerate_equipment_bundles('''

    text, count = pattern.subn(replacement, text, count=1)

    if count != 1:
        raise RuntimeError(
            "Could not uniquely replace enumerate_machine_bundles(). "
            "No file was modified."
        )

    old_block = r'''    crew_availability = build_weekly_availability(
        crew_availability_df,
        ["crew_id"],
        ["shift_start", "available_from"],
        ["shift_end", "available_to"],
    )

    machine_availability = build_weekly_availability(
        machine_availability_df,
        ["machine_id"],
        ["available_from", "shift_start"],
        ["available_to", "shift_end"],
    )
'''

    new_block = r'''    v311 = load_v311_base_module()

    crew_availability = v311.build_weekly_availability_index(
        crew_availability_df,
        "crew_id",
        "shift_start",
        "shift_end",
    )

    machine_availability = v311.build_weekly_availability_index(
        machine_availability_df,
        "machine_id",
        "available_from",
        "available_to",
    )
'''

    if old_block not in text:
        raise RuntimeError(
            "Could not find availability-index block. No file was modified."
        )

    text = text.replace(old_block, new_block, 1)

    compile(text, str(TARGET), "exec")
    TARGET.write_text(text, encoding="utf-8")

    print("\nPatch applied successfully.")
    print("Syntax check: PASS")
    print("Machine availability now exactly follows frozen V3.11 semantics.")
    print("No safety rule was weakened.")


if __name__ == "__main__":
    main()
