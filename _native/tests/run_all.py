"""Run native Python regression tests for the current Python ABI."""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


HERE = os.path.dirname(os.path.abspath(__file__))
PY_LIB = "py313" if sys.version_info >= (3, 13) else "py311"
LIB = os.environ.get(
    "HOTOOLS_NATIVE_TEST_DIR",
    os.path.join(HERE, "..", "..", "_Lib", PY_LIB, "HotoolsPackage"),
)
sys.path.insert(0, os.path.normpath(LIB))

tests = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))

passed: list[str] = []
failed: list[str] = []
skipped: list[str] = []

for fname in tests:
    path = os.path.join(HERE, fname)
    spec = importlib.util.spec_from_file_location(fname[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ModuleNotFoundError as exc:
        if getattr(exc, "name", "") == "bpy":
            skipped.append(f"{fname}: requires bpy")
            continue
        failed.append(f"{fname}: {exc}")
        traceback.print_exc()
        continue
    except Exception as exc:
        failed.append(f"{fname}: {exc}")
        traceback.print_exc()
        continue

    file_failed = False
    functions = [
        value
        for name, value in vars(mod).items()
        if name.startswith("test_") and callable(value)
    ]
    for fn in functions:
        try:
            fn()
        except Exception as exc:
            msg = str(exc)
            if msg.startswith("SKIP:"):
                skipped.append(f"{fname}::{fn.__name__}: {msg}")
            else:
                failed.append(f"{fname}::{fn.__name__}: {exc}")
                file_failed = True
                traceback.print_exc()
    if not file_failed:
        passed.append(fname)

print(f"\n{'=' * 50}")
print(f"passed: {len(passed)}  skipped: {len(skipped)}  failed: {len(failed)}")
if skipped:
    print("skipped:")
    for item in skipped:
        print(f"  SKIP {item}")
if failed:
    print("failed:")
    for item in failed:
        print(f"  FAIL {item}")
else:
    print("all runnable tests passed")

if failed:
    raise SystemExit(1)
