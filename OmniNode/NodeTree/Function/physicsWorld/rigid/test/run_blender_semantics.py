"""Run the minimal Rigid/Jolt semantic fixture slice inside background Blender."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from blender_fixture_runtime import BlenderFixtureRuntime
from run_native_semantics import HERE, _parser, run


def _script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def main() -> int:
    args = _parser().parse_args(_script_args())
    if not args.id:
        args.id = sorted(BlenderFixtureRuntime.SUPPORTED_FIXTURES)
    try:
        code, _summary = run(
            args,
            runtime_factory=lambda native: BlenderFixtureRuntime(
                native, HERE.parent / "backends" / "test_blender_rigid.py"
            ),
            summary_schema="hotools_jolt_blender_run_v1",
            runner_id=BlenderFixtureRuntime.RUNNER_ID,
        )
        return code
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
