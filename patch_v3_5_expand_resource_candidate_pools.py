
# TrackEase V3.5 - Resource Candidate Pool Expansion Patch
#
# Expands ONLY the pre-scheduling candidate shortlist in:
#   src/resources/validate_v3_resource_feasibility.py
#
# No new resources are created and no safety rule is relaxed.

from pathlib import Path
import shutil


PROJECT_ROOT = Path.cwd()
TARGET = (
    PROJECT_ROOT
    / "src"
    / "resources"
    / "validate_v3_resource_feasibility.py"
)

BACKUP = TARGET.with_suffix(
    ".py.bak_before_candidate_pool_expansion"
)

PATCH_MARKER = "TRACKEASE_V3_EXPANDED_RESOURCE_POOL_POLICY"


OLD_BLOCK = '''MAX_CANDIDATES_PER_REQUIREMENT = {
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


NEW_BLOCK = '''# TRACKEASE_V3_EXPANDED_RESOURCE_POOL_POLICY
#
# V3.5 is a pre-scheduling reachability layer. Keep a broader but still finite
# set of already-existing qualified resources so V3.11/V3.12 can resolve exact
# time and resource competition without being trapped by an artificial
# nearest-N shortlist.
MAX_CANDIDATES_PER_REQUIREMENT = {
    "CREW": 10,
    "MACHINE": 6,
    "EQUIPMENT": 8,
    "MATERIAL": 3,
    "OPERATIONAL_PREREQUISITE": 6,
}

# Protection is a hard safety prerequisite. Preserve shift-diverse candidates
# before exact block time is known. Six per shift adds deterministic location
# and rest-day redundancy while keeping the candidate pool finite.
#
# This is a prototype search-policy parameter, not an Indian Railways staffing
# standard and it does not increase the actual number of Protection crews.
PROTECTION_CANDIDATES_PER_SHIFT = 6
PROTECTION_SHIFT_ORDER = (
    "EARLY",
    "DAY",
    "LATE",
)
'''


def main():
    print("=" * 72)
    print("TrackEase V3.5 - Resource Candidate Pool Expansion Patch")
    print("=" * 72)

    if not TARGET.exists():
        raise FileNotFoundError(
            f"Target file not found: {TARGET}\n"
            "Run this patch from C:\\SIH_PROJECT."
        )

    text = TARGET.read_text(encoding="utf-8")

    if PATCH_MARKER in text:
        print("\nExpanded candidate-pool policy is already present.")
        compile(text, str(TARGET), "exec")
        print("Syntax check: PASS")
        return

    if OLD_BLOCK not in text:
        raise RuntimeError(
            "Expected V3.5 candidate-policy block was not found.\n"
            "No file was modified."
        )

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"\nBackup created:\n  {BACKUP}")
    else:
        print(f"\nExisting backup preserved:\n  {BACKUP}")

    patched = text.replace(
        OLD_BLOCK,
        NEW_BLOCK,
        1,
    )

    compile(
        patched,
        str(TARGET),
        "exec",
    )

    TARGET.write_text(
        patched,
        encoding="utf-8",
    )

    print("\nPatch applied successfully.")
    print("Syntax check: PASS")
    print()
    print("New V3.5 candidate policy:")
    print("  CREW                    : 10")
    print("  MACHINE                 : 6")
    print("  EQUIPMENT               : 8")
    print("  MATERIAL                : 3")
    print("  OPERATIONAL_PREREQUISITE: 6")
    print("  PROTECTION              : 6 per shift (max 18)")
    print()
    print(
        "No resources were added; only the pre-scheduling search pool "
        "was widened."
    )


if __name__ == "__main__":
    main()
