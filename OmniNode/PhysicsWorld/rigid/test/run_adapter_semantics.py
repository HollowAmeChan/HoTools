"""Run Rigid/Jolt fixtures through production specs and JoltAdapter."""

from __future__ import annotations

import sys
import traceback
from typing import Sequence

try:
    from .adapter_fixture_runtime import AdapterFixtureRuntime
    from .run_native_semantics import HERE, _parser, run
except ImportError:  # Support direct script execution.
    from adapter_fixture_runtime import AdapterFixtureRuntime
    from run_native_semantics import HERE, _parser, run


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        code, _summary = run(
            args,
            runtime_factory=lambda native: AdapterFixtureRuntime(native, HERE.parent),
            summary_schema="hotools_jolt_adapter_run_v1",
            runner_id=AdapterFixtureRuntime.RUNNER_ID,
        )
        return code
    except Exception as exc:
        print(f"fatal: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
