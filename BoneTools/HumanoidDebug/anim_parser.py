"""Streaming reader for Unity Humanoid AnimationClip YAML assets."""

from __future__ import annotations

from array import array
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
import logging
from pathlib import Path
import re


MAX_CLIP_SIZE = 256 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)
_FLOAT_PATTERN = re.compile(
    r"^\s*(time|value|inSlope|outSlope|inWeight|outWeight):\s*"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
_TARGET_CURVES = frozenset({
    "RootT.x", "RootT.y", "RootT.z",
    "RootQ.x", "RootQ.y", "RootQ.z", "RootQ.w",
    "Spine Front-Back", "Spine Left-Right", "Spine Twist Left-Right",
    "Chest Front-Back", "Chest Left-Right", "Chest Twist Left-Right",
    "UpperChest Front-Back", "UpperChest Left-Right", "UpperChest Twist Left-Right",
    "Neck Nod Down-Up", "Neck Tilt Left-Right", "Neck Turn Left-Right",
    "Head Nod Down-Up", "Head Tilt Left-Right", "Head Turn Left-Right",
    "Left Eye Down-Up", "Left Eye In-Out", "Right Eye Down-Up", "Right Eye In-Out",
    "Jaw Close", "Jaw Left-Right",
    "Left Upper Leg Front-Back", "Left Upper Leg In-Out",
    "Left Upper Leg Twist In-Out", "Left Lower Leg Stretch",
    "Left Lower Leg Twist In-Out", "Left Foot Up-Down", "Left Foot Twist In-Out",
    "Left Toes Up-Down",
    "Right Upper Leg Front-Back", "Right Upper Leg In-Out",
    "Right Upper Leg Twist In-Out", "Right Lower Leg Stretch",
    "Right Lower Leg Twist In-Out", "Right Foot Up-Down", "Right Foot Twist In-Out",
    "Right Toes Up-Down",
    "Left Shoulder Down-Up", "Left Shoulder Front-Back",
    "Left Arm Down-Up", "Left Arm Front-Back", "Left Arm Twist In-Out",
    "Left Forearm Stretch", "Left Forearm Twist In-Out",
    "Left Hand Down-Up", "Left Hand In-Out",
    "Right Shoulder Down-Up", "Right Shoulder Front-Back",
    "Right Arm Down-Up", "Right Arm Front-Back", "Right Arm Twist In-Out",
    "Right Forearm Stretch", "Right Forearm Twist In-Out",
    "Right Hand Down-Up", "Right Hand In-Out",
    "LeftHand.Thumb.1 Stretched", "LeftHand.Thumb.Spread",
    "LeftHand.Thumb.2 Stretched", "LeftHand.Thumb.3 Stretched",
    "LeftHand.Index.1 Stretched", "LeftHand.Index.Spread",
    "LeftHand.Index.2 Stretched", "LeftHand.Index.3 Stretched",
    "LeftHand.Middle.1 Stretched", "LeftHand.Middle.Spread",
    "LeftHand.Middle.2 Stretched", "LeftHand.Middle.3 Stretched",
    "LeftHand.Ring.1 Stretched", "LeftHand.Ring.Spread",
    "LeftHand.Ring.2 Stretched", "LeftHand.Ring.3 Stretched",
    "LeftHand.Little.1 Stretched", "LeftHand.Little.Spread",
    "LeftHand.Little.2 Stretched", "LeftHand.Little.3 Stretched",
    "RightHand.Thumb.1 Stretched", "RightHand.Thumb.Spread",
    "RightHand.Thumb.2 Stretched", "RightHand.Thumb.3 Stretched",
    "RightHand.Index.1 Stretched", "RightHand.Index.Spread",
    "RightHand.Index.2 Stretched", "RightHand.Index.3 Stretched",
    "RightHand.Middle.1 Stretched", "RightHand.Middle.Spread",
    "RightHand.Middle.2 Stretched", "RightHand.Middle.3 Stretched",
    "RightHand.Ring.1 Stretched", "RightHand.Ring.Spread",
    "RightHand.Ring.2 Stretched", "RightHand.Ring.3 Stretched",
    "RightHand.Little.1 Stretched", "RightHand.Little.Spread",
    "RightHand.Little.2 Stretched", "RightHand.Little.3 Stretched",
})


@dataclass(frozen=True, slots=True)
class ClipInfo:
    identifier: str
    name: str
    path: Path
    sample_rate: float
    duration: float

    def frame_count(self, frame_rate: int) -> int:
        return max(1, round(self.duration * max(1, frame_rate)) + 1)


@dataclass(frozen=True, slots=True)
class ScalarCurve:
    times: array
    values: array
    in_slopes: array
    out_slopes: array
    in_weights: array
    out_weights: array

    def evaluate(self, time: float) -> float:
        if not self.times:
            return 0.0
        if time <= self.times[0]:
            return self.values[0]
        if time >= self.times[-1]:
            return self.values[-1]

        right = bisect_right(self.times, time)
        left = right - 1
        span = self.times[right] - self.times[left]
        if span <= 1e-8:
            return self.values[right]

        factor = (time - self.times[left]) / span
        # Unity's clips in this pack use unweighted cubic Hermite keys.
        t2 = factor * factor
        t3 = t2 * factor
        left_term = 2.0 * t3 - 3.0 * t2 + 1.0
        left_slope = t3 - 2.0 * t2 + factor
        right_term = -2.0 * t3 + 3.0 * t2
        right_slope = t3 - t2
        return (
            left_term * self.values[left]
            + left_slope * span * self.out_slopes[left]
            + right_term * self.values[right]
            + right_slope * span * self.in_slopes[right]
        )


@dataclass(frozen=True, slots=True)
class HumanoidClip:
    info: ClipInfo
    curves: dict[str, ScalarCurve]

    def sample(self, time: float) -> dict[str, float]:
        bounded_time = min(max(0.0, time), self.info.duration)
        return {
            name: curve.evaluate(bounded_time)
            for name, curve in self.curves.items()
        }


def _read_clip_header(stream, path: Path) -> ClipInfo:
    name = path.stem
    sample_rate = 0.0
    duration = 0.0
    for line in stream:
        if line.startswith("  m_Name:"):
            name = line.split(":", 1)[1].strip() or name
        elif line.startswith("  m_SampleRate:"):
            sample_rate = float(line.split(":", 1)[1].strip())
        elif line.startswith("    m_StopTime:"):
            duration = float(line.split(":", 1)[1].strip())
        elif line.startswith("  m_EditorCurves:"):
            break
    if sample_rate <= 0.0 or duration <= 0.0:
        raise ValueError(f"{path.name}: missing Unity sample rate or clip duration")
    return ClipInfo(
        identifier=path.stem,
        name=name,
        path=path,
        sample_rate=sample_rate,
        duration=duration,
    )


@lru_cache(maxsize=512)
def _read_file_header(path: str, modified_ns: int, file_size: int) -> ClipInfo:
    del modified_ns
    if file_size > MAX_CLIP_SIZE:
        raise ValueError(
            f"Animation clip exceeds the {MAX_CLIP_SIZE // (1024 * 1024)} MB limit"
        )
    clip_path = Path(path)
    with clip_path.open(encoding="utf-8-sig", errors="replace") as stream:
        return _read_clip_header(stream, clip_path)


def list_clips(directory: str | Path) -> tuple[ClipInfo, ...]:
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        return ()
    try:
        paths = sorted(
            (
                path for path in directory.rglob("*")
                if path.suffix.casefold() == ".anim" and path.is_file()
            ),
            key=lambda path: path.relative_to(directory).as_posix().casefold(),
        )
    except OSError:
        return ()

    infos = []
    for path in paths:
        try:
            stat = path.stat()
            info = _read_file_header(str(path), stat.st_mtime_ns, stat.st_size)
        except (OSError, ValueError) as error:
            _LOGGER.warning("Skipping Humanoid animation %s: %s", path, error)
            continue
        # Relative paths keep same-named files in separate subfolders selectable.
        identifier = path.relative_to(directory).with_suffix("").as_posix()
        infos.append(ClipInfo(
            identifier, info.name, path, info.sample_rate, info.duration,
        ))
    return tuple(infos)


def _float_or_default(key: dict[str, float], name: str) -> float:
    return key.get(name, 0.0)


def _curve_from_keys(keys: list[dict[str, float]]) -> ScalarCurve:
    return ScalarCurve(
        times=array("d", (key["time"] for key in keys)),
        values=array("d", (key["value"] for key in keys)),
        in_slopes=array("d", (_float_or_default(key, "inSlope") for key in keys)),
        out_slopes=array("d", (_float_or_default(key, "outSlope") for key in keys)),
        in_weights=array("d", (_float_or_default(key, "inWeight") for key in keys)),
        out_weights=array("d", (_float_or_default(key, "outWeight") for key in keys)),
    )


def _parse_curve_stream(stream, info: ClipInfo, in_editor_curves=False) -> HumanoidClip:
    curves = {}
    keys = []
    current_key = None

    def store_curve(name):
        nonlocal keys
        if name in _TARGET_CURVES and keys:
            curves[name] = _curve_from_keys(keys)
        keys = []

    for line in stream:
        if not in_editor_curves:
            if line.startswith("  m_EditorCurves:"):
                in_editor_curves = True
            continue
        if line.startswith("  m_EulerEditorCurves:"):
            store_curve("")
            break
        if line.startswith("    attribute:"):
            store_curve(line.split(":", 1)[1].strip())
            current_key = None
            continue
        if line.startswith("      - serializedVersion: 3"):
            current_key = {}
            keys.append(current_key)
            continue
        if current_key is None:
            continue
        match = _FLOAT_PATTERN.match(line)
        if match:
            current_key[match.group(1)] = float(match.group(2))

    if not in_editor_curves:
        raise ValueError(f"{info.path.name}: no m_EditorCurves section")
    store_curve("")
    return HumanoidClip(info, curves)


@lru_cache(maxsize=3)
def _load_clip_cached(
    path: str,
    identifier: str,
    modified_ns: int,
    file_size: int,
) -> HumanoidClip:
    if file_size > MAX_CLIP_SIZE:
        raise ValueError(
            f"Animation clip exceeds the {MAX_CLIP_SIZE // (1024 * 1024)} MB limit"
        )
    header = _read_file_header(path, modified_ns, file_size)
    info = ClipInfo(
        identifier, header.name, header.path, header.sample_rate, header.duration,
    )
    with info.path.open(encoding="utf-8-sig", errors="replace") as stream:
        return _parse_curve_stream(stream, info)


def load_clip(clip: ClipInfo) -> HumanoidClip:
    path = clip.path.expanduser().resolve()
    stat = path.stat()
    return _load_clip_cached(
        str(path),
        clip.identifier,
        stat.st_mtime_ns,
        stat.st_size,
    )


def clear_clip_cache() -> None:
    _load_clip_cached.cache_clear()
    _read_file_header.cache_clear()
