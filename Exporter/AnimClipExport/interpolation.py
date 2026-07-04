# -*- coding: utf-8 -*-
# Blender 关键帧插值 → Unity .anim 切线格式转换。

from dataclasses import dataclass


@dataclass
class UnityKey:
    """一个 Unity AnimationCurve 关键帧。"""
    time: float
    value: float
    in_slope: float   # 特殊值：float('inf') 表示阶梯
    out_slope: float
    tangent_mode: int # 103 = constant ; 0 = free
    weighted_mode: int = 0
    in_weight: float = 0.33333334
    out_weight: float = 0.33333334


_INF = float('inf')


def _slope_from_handles(kp0, kp1, fps: float) -> tuple[float, float]:
    """用 Blender BEZIER 控制柄计算 kp0→kp1 段的出切线 (kp0.out) 和入切线 (kp1.in)。

    Blender 控制柄坐标单位：x = 帧，y = 属性值。
    Unity 切线单位：dy/dt，t 的单位是秒，因此需要乘以 fps。
    """
    t0, v0 = kp0.co
    t1, v1 = kp1.co
    dt = (t1 - t0) / fps  # 帧差 → 秒差

    if dt <= 0:
        return 0.0, 0.0

    # kp0 的右控制柄
    hr_t = (kp0.handle_right[0] - t0) / fps
    hr_v = kp0.handle_right[1] - v0
    out_slope = (hr_v / hr_t) if abs(hr_t) > 1e-9 else 0.0

    # kp1 的左控制柄
    hl_t = (t1 - kp1.handle_left[0]) / fps
    hl_v = v1 - kp1.handle_left[1]
    in_slope = (hl_v / hl_t) if abs(hl_t) > 1e-9 else 0.0

    return out_slope, in_slope


def convert_fcurve(
    fcurve,
    fps: float,
    start_frame: float,
    force_stepped: bool = False,
    snap_binary: bool = False,
) -> list[UnityKey]:
    """把一条 Blender FCurve 转成 UnityKey 列表。

    force_stepped : 强制用阶梯插值（适用于布尔属性）
    snap_binary   : 把值钳到 0/1（与 force_stepped 配合用）
    """
    kps = sorted(fcurve.keyframe_points, key=lambda k: k.co.x)
    if not kps:
        return []

    # 自动检测布尔轨道（所有关键帧值仅含 0/1）
    if not force_stepped:
        vals = {round(k.co.y) for k in kps}
        if vals <= {0, 1} and all(abs(k.co.y - round(k.co.y)) < 1e-4 for k in kps):
            force_stepped = True
            snap_binary = True

    result: list[UnityKey] = []

    if force_stepped:
        prev_val = None
        for kp in kps:
            val = 1.0 if kp.co.y >= 0.5 else 0.0 if snap_binary else kp.co.y
            # 去冗余帧（阶梯轨道相邻相同值无意义）
            if prev_val is not None and val == prev_val:
                continue
            t = (kp.co.x - start_frame) / fps
            result.append(UnityKey(
                time=t, value=val,
                in_slope=_INF, out_slope=_INF,
                tangent_mode=103,
                weighted_mode=0, in_weight=0.0, out_weight=0.0,
            ))
            prev_val = val
        return result

    # ── 非阶梯：按 Blender 插值类型转切线 ──────────────────────
    n = len(kps)
    # 预计算每段的出/入斜率
    seg_out: list[float] = []  # seg_out[i] = kps[i] 对 kps[i+1] 的出切线
    seg_in:  list[float] = []  # seg_in[i]  = kps[i] 对 kps[i-1] 的入切线 (从 kps[i] 视角)

    for i in range(n):
        if i < n - 1:
            kp0, kp1 = kps[i], kps[i + 1]
            interp = kp0.interpolation  # 段插值取前帧
            if interp == 'CONSTANT':
                seg_out.append(_INF)
                seg_in.append(_INF)
            elif interp == 'LINEAR':
                dt = (kp1.co.x - kp0.co.x) / fps
                dv = kp1.co.y - kp0.co.y
                s = dv / dt if dt > 0 else 0.0
                seg_out.append(s)
                seg_in.append(s)
            else:  # BEZIER
                out_s, in_s = _slope_from_handles(kp0, kp1, fps)
                seg_out.append(out_s)
                seg_in.append(in_s)
        else:
            seg_out.append(0.0)

    for i, kp in enumerate(kps):
        t = (kp.co.x - start_frame) / fps
        val = kp.co.y

        # 本帧的入切线来自左侧段（i-1 段的 seg_in）
        # 本帧的出切线来自右侧段（i 段的 seg_out）
        in_s  = seg_in[i - 1] if i > 0 else 0.0
        out_s = seg_out[i]

        # 如果两侧有一侧是 CONSTANT 段，对应方向用 Infinity
        left_const  = (i > 0 and kps[i - 1].interpolation == 'CONSTANT')
        right_const = (i < n - 1 and kp.interpolation == 'CONSTANT')
        if left_const:
            in_s = _INF
        if right_const:
            out_s = _INF

        tmode = 103 if (left_const or right_const) else 0
        w = 0.0 if tmode == 103 else 0.33333334
        result.append(UnityKey(
            time=t, value=val,
            in_slope=in_s, out_slope=out_s,
            tangent_mode=tmode,
            weighted_mode=0, in_weight=w, out_weight=w,
        ))

    return result
