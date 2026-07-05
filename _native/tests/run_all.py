"""
快速回归测试运行器：逐个执行所有 test_*.py，汇报通过/失败。
用法：
  python run_all.py
"""
import sys
import os
import importlib.util
import traceback

# 把 _Lib/py311 加到路径，让 HotoolsPackage 可被 import
HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "..", "..", "_Lib", "py311")
sys.path.insert(0, os.path.normpath(LIB))

tests = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))

passed = []
failed = []

for fname in tests:
    path = os.path.join(HERE, fname)
    spec = importlib.util.spec_from_file_location(fname[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        # 找并运行所有 test_* 函数
        fns = [v for k, v in vars(mod).items() if k.startswith("test_") and callable(v)]
        for fn in fns:
            try:
                fn()
            except Exception as e:
                failed.append(f"{fname}::{fn.__name__}: {e}")
                traceback.print_exc()
                continue
        passed.append(fname)
    except Exception as e:
        failed.append(f"{fname}: {e}")
        traceback.print_exc()

print(f"\n{'='*50}")
print(f"通过: {len(passed)}  失败: {len(failed)}")
if failed:
    print("失败项:")
    for f in failed:
        print(f"  ✗ {f}")
else:
    print("全部通过 ✓")
