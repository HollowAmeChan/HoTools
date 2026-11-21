"""Generate/check readable coverage without Blender or Unity installed."""

import argparse
from pathlib import Path

from . import generate_coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the generated coverage table")
    mode.add_argument("--check", action="store_true", help="fail when the checked-in table has drifted")
    arguments = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / "docs" / "COVERAGE.md"
    expected = generate_coverage()
    if arguments.write:
        destination.write_text(expected, encoding="utf-8", newline="\n")
        print(destination)
    elif arguments.check:
        if not destination.is_file() or destination.read_text(encoding="utf-8") != expected:
            raise SystemExit("coverage drift; run python -m RigConstraints.registry --write")
        print("Rig constraint registry coverage is current")
    else:
        print(expected, end="")


if __name__ == "__main__":
    main()
