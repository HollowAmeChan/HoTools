"""
无头 Blender 测试脚本：测试 hotools_jolt 在 Blender 进程内的完整行为
包括：import、JoltWorld 创建、add_body、step
"""
import sys
import os

addon_root = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(addon_root, "_Lib", "py311", "HotoolsPackage")
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

print("[TEST] Python:", sys.version.split()[0])

print("[TEST] import hotools_jolt ...")
try:
    import hotools_jolt
    print("[TEST] import OK")
except Exception as e:
    import traceback
    print("[TEST] import FAILED:", e)
    traceback.print_exc()
    sys.exit(1)

print("[TEST] create JoltWorld ...")
try:
    jw = hotools_jolt.JoltWorld(max_bodies=64, max_body_pairs=256, max_contact_constraints=128)
    print("[TEST] JoltWorld OK:", jw)
except Exception as e:
    import traceback
    print("[TEST] JoltWorld FAILED:", e)
    traceback.print_exc()
    sys.exit(1)

print("[TEST] add_body ...")
try:
    h = jw.add_body(
        "DYNAMIC", 1.0, 0.5, 0.3,
        [0.0, 5.0, 0.0], [1.0, 0.0, 0.0, 0.0],
        "SPHERE", 0.5
    )
    print("[TEST] add_body OK, handle =", h)
except Exception as e:
    import traceback
    print("[TEST] add_body FAILED:", e)
    traceback.print_exc()
    sys.exit(1)

print("[TEST] step(1/60) ...")
try:
    ms = jw.step(1.0 / 60.0, 1)
    print("[TEST] step OK, %.3f ms" % ms)
except Exception as e:
    import traceback
    print("[TEST] step FAILED:", e)
    traceback.print_exc()
    sys.exit(1)

pos, rot = jw.get_body_transform(h)
print("[TEST] body pos after 1 step:", [round(v, 4) for v in pos])
print("[TEST] 全部通过！")
