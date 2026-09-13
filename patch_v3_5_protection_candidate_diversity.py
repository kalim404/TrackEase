
# TrackEase V3.5 - Protection Shift-Diverse Candidate Patch
#
# Patches ONLY:
#   src/resources/validate_v3_resource_feasibility.py
#
# For PROTECTION_CREW requirements, V3.5 will preserve the nearest
# 3 EARLY, 3 DAY and 3 LATE Protection crews so exact time filtering
# in V3.11 does not lose entire shift classes prematurely.

from pathlib import Path
import py_compile
import shutil


PROJECT_ROOT = Path.cwd()
TARGET = (
    PROJECT_ROOT
    / "src"
    / "resources"
    / "validate_v3_resource_feasibility.py"
)
BACKUP = TARGET.with_suffix(
    ".py.bak_before_protection_candidate_diversity_fix"
)

PATCH_MARKER = "PROTECTION_CANDIDATES_PER_SHIFT"


OLD_CONSTANT_BLOCK = '''MAX_CANDIDATES_PER_REQUIREMENT = {
    "CREW": 5,
    "MACHINE": 3,
    "EQUIPMENT": 3,
    "MATERIAL": 3,
    "OPERATIONAL_PREREQUISITE": 3,
}
'''

NEW_CONSTANT_BLOCK = '''MAX_CANDIDATES_PER_REQUIREMENT = {
    "CREW": 5,
    "MACHINE": 3,
    "EQUIPMENT": 3,
    "MATERIAL": 3,
    "OPERATIONAL_PREREQUISITE": 3,
}

# Protection is a hard safety prerequisite. Before exact block time is known,
# keep a small candidate pool from every prototype Protection shift so V3.11
# can perform the real weekday/time check without losing valid resources.
#
# Three candidates per shift provide deterministic rest-day redundancy while
# keeping the pool finite. This is a prototype search-policy parameter, not an
# Indian Railways staffing standard.
PROTECTION_CANDIDATES_PER_SHIFT = 3
PROTECTION_SHIFT_ORDER = (
    "EARLY",
    "DAY",
    "LATE",
)
'''


OLD_SELECTION_BLOCK = '''        limit = MAX_CANDIDATES_PER_REQUIREMENT.get(
            category,
            3,
        )

        selected = candidate_records[
            :limit
        ]
'''

NEW_SELECTION_BLOCK = '''        limit = MAX_CANDIDATES_PER_REQUIREMENT.get(
            category,
            3,
        )

        requirement_type = clean_text(
            requirement.requirement_type
        ).upper()

        if (
            category == "CREW"
            and requirement_type == "PROTECTION_CREW"
        ):
            # V3.5 is a pre-scheduling layer: exact block time is not known
            # yet. Preserve nearest candidates from every Protection shift
            # instead of allowing the global nearest-N shortlist to remove
            # an entire shift before V3.11 can evaluate it.
            selected = []

            for shift_pattern in PROTECTION_SHIFT_ORDER:
                shift_candidates = [
                    candidate
                    for candidate in candidate_records
                    if (
                        candidate[1] in crew_lookup.index
                        and clean_text(
                            crew_lookup.loc[
                                candidate[1],
                                "shift_pattern",
                            ]
                        ).upper()
                        == shift_pattern
                    )
                ]

                selected.extend(
                    shift_candidates[
                        :PROTECTION_CANDIDATES_PER_SHIFT
                    ]
                )

            # Defensive fallback for a future/legacy Protection shift label.
            if not selected:
                selected = candidate_records[
                    :limit
                ]
        else:
            selected = candidate_records[
                :limit
            ]
'''


def main():
    print("=" * 72)
    print("TrackEase V3.5 - Protection Shift-Diverse Candidate Patch")
    print("=" * 72)

    if not TARGET.exists():
        raise FileNotFoundError(
            f"Target file not found: {TARGET}\n"
            "Run this patch from C:\\SIH_PROJECT."
        )

    text = TARGET.read_text(encoding="utf-8")

    if PATCH_MARKER in text:
        print("\nPatch is already present.")
        py_compile.compile(str(TARGET), doraise=True)
        print("Syntax check: PASS")
        return

    missing = []

    if OLD_CONSTANT_BLOCK not in text:
        missing.append("MAX_CANDIDATES_PER_REQUIREMENT block")

    if OLD_SELECTION_BLOCK not in text:
        missing.append("candidate selection block")

    if missing:
        raise RuntimeError(
            "Patch stopped because the expected V3.5 source layout "
            "was not found.\nMissing:\n  - "
            + "\n  - ".join(missing)
            + "\nNo file was modified."
        )

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"\nBackup created:\n  {BACKUP}")
    else:
        print(f"\nExisting backup preserved:\n  {BACKUP}")

    patched = text.replace(
        OLD_CONSTANT_BLOCK,
        NEW_CONSTANT_BLOCK,
        1,
    )

    patched = patched.replace(
        OLD_SELECTION_BLOCK,
        NEW_SELECTION_BLOCK,
        1,
    )

    TARGET.write_text(
        patched,
        encoding="utf-8",
    )

    try:
        py_compile.compile(
            str(TARGET),
            doraise=True,
        )
    except Exception:
        shutil.copy2(
            BACKUP,
            TARGET,
        )
        print(
            "\nSyntax validation failed. "
            "Original V3.5 file restored."
        )
        raise

    print("\nPatch applied successfully.")
    print("Syntax check: PASS")
    print()
    print("Protection candidate policy:")
    print("  EARLY : nearest 3")
    print("  DAY   : nearest 3")
    print("  LATE  : nearest 3")
    print("  Maximum Protection candidates per requirement: 9")
    print()
    print(
        "All ordinary crew and non-crew candidate limits are unchanged."
    )


if __name__ == "__main__":
    main()
