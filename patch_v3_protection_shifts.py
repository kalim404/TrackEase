
# TrackEase V3 - Protection Shift Coverage Patch
#
# Purpose:
# Patch ONLY the prototype Protection-department shift generation in:
#   src/resources/build_v3_resources.py
#
# Protection becomes:
#   EARLY 00:00-08:00
#   DAY   08:00-16:00
#   LATE  16:00-00:00
#
# Engineering, S&T and Electrical keep their existing DAY/NIGHT logic.
# The script creates a backup, refuses unexpected layouts, is idempotent,
# and syntax-checks the modified generator.

from pathlib import Path
import py_compile
import shutil


PROJECT_ROOT = Path.cwd()
TARGET = PROJECT_ROOT / "src" / "resources" / "build_v3_resources.py"
BACKUP = TARGET.with_suffix(".py.bak_before_protection_shift_fix")


OLD_SHIFT_ASSIGNMENT = '''            shift_pattern = (
                "DAY"
                if index % 3 != 0
                else "NIGHT"
            )
'''

NEW_SHIFT_ASSIGNMENT = '''            # Prototype shift policy:
            # Protection needs continuous 24-hour coverage capability.
            # Other departments retain the existing DAY/NIGHT generator.
            if department == "Protection":
                protection_shift_cycle = (
                    "EARLY",
                    "DAY",
                    "LATE",
                )

                shift_pattern = protection_shift_cycle[
                    (index - 1)
                    % len(protection_shift_cycle)
                ]
            else:
                shift_pattern = (
                    "DAY"
                    if index % 3 != 0
                    else "NIGHT"
                )
'''


OLD_AVAILABILITY_ASSIGNMENT = '''                if shift_pattern == "DAY":
                    shift_start = "08:00"
                    shift_end = "16:00"
                else:
                    shift_start = "20:00"
                    shift_end = "04:00"
'''

NEW_AVAILABILITY_ASSIGNMENT = '''                if department == "Protection":
                    if shift_pattern == "EARLY":
                        shift_start = "00:00"
                        shift_end = "08:00"
                    elif shift_pattern == "DAY":
                        shift_start = "08:00"
                        shift_end = "16:00"
                    elif shift_pattern == "LATE":
                        shift_start = "16:00"
                        shift_end = "00:00"
                    else:
                        raise ValueError(
                            "Unexpected Protection shift pattern: "
                            f"{shift_pattern}"
                        )
                elif shift_pattern == "DAY":
                    shift_start = "08:00"
                    shift_end = "16:00"
                else:
                    shift_start = "20:00"
                    shift_end = "04:00"
'''


PATCH_MARKER = "protection_shift_cycle"


def main():
    print("=" * 72)
    print("TrackEase V3 - Protection Shift Coverage Patch")
    print("=" * 72)

    if not TARGET.exists():
        raise FileNotFoundError(
            f"Target file not found: {TARGET}\\n"
            "Run this patch from C:\\\\SIH_PROJECT."
        )

    text = TARGET.read_text(encoding="utf-8")

    if PATCH_MARKER in text:
        print("\\nProtection shift patch is already present.")
        py_compile.compile(str(TARGET), doraise=True)
        print("Syntax check: PASS")
        return

    missing_blocks = []

    if OLD_SHIFT_ASSIGNMENT not in text:
        missing_blocks.append("shift_pattern assignment")

    if OLD_AVAILABILITY_ASSIGNMENT not in text:
        missing_blocks.append("shift_start/shift_end assignment")

    if missing_blocks:
        raise RuntimeError(
            "Patch stopped because the expected source layout was not found.\\n"
            "Missing blocks:\\n  - "
            + "\\n  - ".join(missing_blocks)
            + "\\nNo file was modified."
        )

    if not BACKUP.exists():
        shutil.copy2(TARGET, BACKUP)
        print(f"\\nBackup created:\\n  {BACKUP}")
    else:
        print(f"\\nExisting backup preserved:\\n  {BACKUP}")

    text = text.replace(
        OLD_SHIFT_ASSIGNMENT,
        NEW_SHIFT_ASSIGNMENT,
        1,
    )

    text = text.replace(
        OLD_AVAILABILITY_ASSIGNMENT,
        NEW_AVAILABILITY_ASSIGNMENT,
        1,
    )

    TARGET.write_text(text, encoding="utf-8")

    try:
        py_compile.compile(str(TARGET), doraise=True)
    except Exception:
        if BACKUP.exists():
            shutil.copy2(BACKUP, TARGET)

        print(
            "\\nSyntax validation failed. "
            "Original file restored from backup."
        )
        raise

    print("\\nPatch applied successfully.")
    print("Syntax check: PASS")

    print("\\nProtection shift policy:")
    print("  EARLY : 00:00-08:00")
    print("  DAY   : 08:00-16:00")
    print("  LATE  : 16:00-00:00")

    print(
        "\\nEngineering, S&T and Electrical retain "
        "their previous DAY/NIGHT shift generator."
    )


if __name__ == "__main__":
    main()
