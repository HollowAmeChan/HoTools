"""粘贴形态键的尽力匹配支线：拓扑变了也要尽量把位移对上。

设计要点：

- 剪贴板 V2 只存**引用**（源物体名）与位移数组，不存基型或 UV 快照；
  匹配时现读还在的源几何与 UV，所以剪贴板体积与旧格式基本一样。
- 引用失效（源物体被删/改名、源网格在复制后被改、剪贴板来自其它文件）时
  直接给出原因并退出，**不做「按点序直填」的降级**——那在删点之后会整体错位，
  属于静默产生错误数据的路径。
- 旧格式（裸数组）剪贴板完全不进这条链路，保持原行为。
- 几何、UV、KD-tree 能力复用 :mod:`paste.geometry`，与「传递形态键」模块同一份实现。

匹配空间由模式自己决定：点序模式比**本地空间**（点序本来就是网格内部的概念，
物体被移动、旋转、缩放都不影响，复制体放在别处也照样能用），世界位置模式比
**世界空间**（与传递模块口径一致，要求两个物体在世界里贴得近），UV 模式比 UV 空间。

UV 模式额外按**模型原点分左右象限**：镜像对称的模型左右两侧常常共用同一片 UV，
纯 UV 最近邻会在两侧的同名点之间随机挑一个，所以先查同侧、同侧够不到才退回另一侧。
"""

import json
from dataclasses import dataclass

import bpy
import numpy as np

try:
    from . import geometry as core
except ImportError:  # 兼容把 ShapekeyTools 目录当脚本路径直接导入
    from paste import geometry as core


#: 剪贴板格式标识。老格式是裸数组，不带 type。
CLIPBOARD_TYPE = "HoToolsShapekeyClipboardV2"

#: 点数一致时，点序位置吻合率低于这个值就认为点序已经变了。
MISMATCH_AGREEMENT = 0.95

#: 自动容差：世界/点序模式取包围盒对角线的这个比例，UV 模式取 UV 空间的绝对值。
WORLD_TOLERANCE_RATIO = 0.01
UV_TOLERANCE = 0.02


@dataclass(frozen=True)
class SourceReference:
    """剪贴板里的源物体引用是否还可用。"""

    ok: bool
    obj: object
    reason: str


@dataclass(frozen=True)
class TopologyEntry:
    """单个目标物体的拓扑体检结果。"""

    name: str
    source_count: int
    dest_count: int
    agreement: float | None
    mismatch: bool


@dataclass(frozen=True)
class TopologyReport:
    """一次粘贴预检的整体结果。"""

    entries: tuple
    mismatch: bool
    reference: SourceReference


@dataclass
class PasteMatchResult:
    """一个目标物体的顶点映射与统计。

    ``pairs`` 是 ``{目标顶点索引: [(源顶点索引, 权重), ...]}``；权重当前恒为 1.0，
    保留成列表是为了以后能接 RBF 多点混合而不改调用方。
    没有出现在 ``pairs`` 里的目标顶点就是**未匹配**，调用方应保持它们原值。
    """

    pairs: dict
    exact: int = 0
    rescued: int = 0
    matched: int = 0
    unmatched: int = 0
    tolerance: float = 0.0

    def summary(self):
        total = self.exact + self.rescued + self.matched + self.unmatched
        parts = []
        if self.exact:
            parts.append(f"点序 {self.exact}")
        if self.rescued:
            parts.append(f"修正 {self.rescued}")
        if self.matched:
            parts.append(f"最近邻 {self.matched}")
        parts.append(f"未匹配 {self.unmatched}")
        return f"尽力匹配 {total} 点：" + " / ".join(parts)


class ShapekeyPasteMatch:
    """拓扑不一致时的尽力匹配（纯静态工具类，不持有状态）。"""

    MODE_ITEMS = (
        (core.MODE_VERTEX_INDEX, "点序",
         "按点序对齐，基型位置校验不过的点再用最近邻修正；删点/加点后用这个"),
        (core.MODE_WORLD_POSITION, "世界位置",
         "按基型世界位置找最近顶点；两个物体需要在世界空间里贴得近"),
        (core.MODE_UV_POSITION, "UV",
         "按活动 UV 层的平均 UV 找最近顶点；需要两边都有活动 UV 层。"
         "UV 重合时按模型原点分左右，取同侧的点"),
    )

    DEFAULT_MODE = core.MODE_UV_POSITION

    #: 容差字段的默认值。**0 表示按包围盒自动计算**：位置模式取包围盒对角线的 1%，
    #: UV 模式取 0.02。自动是严格模式的超集——删点、合并同位置物体这类坐标一模一样的
    #: 情形距离本来就是 0，任何容差都过；简化/重拓扑那种点会被挪位的情形只有自动能救。
    #: 填具体的绝对值就是只认那么近的点（位置模式是模型单位，UV 模式是 UV 单位），
    #: 可用来避免把合并进来的新部位糊到最近的源点上。
    DEFAULT_TOLERANCE = 0.0

    #: 弹窗里的固定提示：UV 模式的依赖与已知限制
    UV_MODE_HINT = "UV 模式需要源与目标都有活动 UV 层"
    UV_SIDE_HINT = "UV 重合时按模型原点分左右，优先取同侧的点"

    # ------------------------------------------------------------------
    # 剪贴板
    # ------------------------------------------------------------------

    @staticmethod
    def extract_coords(obj, active_sk, *, is_abs, value):
        """取活动键的位移或绝对位置，算术与旧的复制实现逐位一致。"""
        coords = []
        if is_abs:
            for point in active_sk.data:
                coords.append([point.co.x, point.co.y, point.co.z])
            return coords

        basis = obj.data.shape_keys.reference_key
        for base_point, key_point in zip(basis.data, active_sk.data):
            delta = (key_point.co - base_point.co) * value
            coords.append([delta.x, delta.y, delta.z])
        return coords

    @staticmethod
    def build_payload(obj, active_sk, *, is_abs, value, coords=None):
        """组装 V2 剪贴板内容；只多存一个源物体引用，不存几何快照。"""
        if coords is None:
            coords = ShapekeyPasteMatch.extract_coords(
                obj, active_sk, is_abs=is_abs, value=value)
        return {
            "type": CLIPBOARD_TYPE,
            "shape_key": active_sk.name,
            "value": value,
            "is_abs": bool(is_abs),
            "vertex_count": len(coords),
            "source_object": obj.name,
            "coords": coords,
        }

    @staticmethod
    def _parse_coords(raw):
        if not isinstance(raw, list) or not raw:
            return None, "剪贴板缺少顶点位移数据"
        coords = []
        for item in raw:
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                return None, "剪贴板顶点数据格式错误"
            try:
                coords.append([float(item[0]), float(item[1]), float(item[2])])
            except (TypeError, ValueError):
                return None, "剪贴板顶点数据格式错误"
        return coords, None

    @staticmethod
    def parse_payload(text):
        """解析剪贴板文本，返回 ``(标准化 payload | None, 错误信息)``。

        裸数组视为旧格式，payload 里 ``legacy`` 为 True、没有源引用；
        旧格式不会进入尽力匹配，调用方照旧按点序直填即可。
        """
        try:
            data = json.loads(text)
        except Exception:
            return None, "剪贴板数据解析失败"

        if isinstance(data, list):
            coords, error = ShapekeyPasteMatch._parse_coords(data)
            if error:
                return None, error
            return {
                "type": None,
                "legacy": True,
                "shape_key": "",
                "value": 1.0,
                "is_abs": False,
                "vertex_count": len(coords),
                "source_object": "",
                "coords": coords,
            }, None

        if not isinstance(data, dict):
            return None, "剪贴板数据格式错误"

        if data.get("type") != CLIPBOARD_TYPE:
            return None, "剪贴板不是全量形态键数据（可能是局部粘贴数据或其它工具的内容）"

        coords, error = ShapekeyPasteMatch._parse_coords(data.get("coords"))
        if error:
            return None, error

        try:
            vertex_count = int(data.get("vertex_count", len(coords)))
        except (TypeError, ValueError):
            return None, "剪贴板顶点数量格式错误"
        if vertex_count != len(coords):
            return None, "剪贴板自洽性校验失败：顶点数量与位移数量不一致"

        source_object = data.get("source_object")
        if not isinstance(source_object, str) or not source_object:
            return None, "剪贴板缺少源物体引用"

        return {
            "type": CLIPBOARD_TYPE,
            "legacy": False,
            "shape_key": str(data.get("shape_key", "")),
            "value": data.get("value", 1.0),
            "is_abs": bool(data.get("is_abs", False)),
            "vertex_count": vertex_count,
            "source_object": source_object,
            "coords": coords,
        }, None

    # ------------------------------------------------------------------
    # 源引用
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_source(payload):
        """检查剪贴板引用的源物体是否还能用来匹配。"""
        if payload is None:
            return SourceReference(False, None, "剪贴板数据无效")

        name = payload.get("source_object") or ""
        if payload.get("legacy") or not name:
            return SourceReference(
                False, None, "剪贴板是旧格式，没有源物体引用，无法做位置或 UV 匹配")

        obj = bpy.data.objects.get(name)
        if obj is None:
            return SourceReference(
                False, None,
                f"源物体 {name} 已不存在（被删除、改名，或剪贴板来自其它文件）")
        if obj.type != 'MESH':
            return SourceReference(False, None, f"源物体 {name} 已不是网格")

        shape_keys = getattr(obj.data, "shape_keys", None)
        basis = getattr(shape_keys, "reference_key", None)
        if basis is None:
            return SourceReference(False, None, f"源物体 {name} 已没有形态键")

        current_count = len(basis.data)
        if current_count != payload["vertex_count"]:
            return SourceReference(
                False, None,
                f"源物体 {name} 的顶点数已变化（剪贴板 {payload['vertex_count']} / "
                f"当前 {current_count}），源网格在复制后被改过")

        return SourceReference(True, obj, "")

    # ------------------------------------------------------------------
    # 拓扑体检
    # ------------------------------------------------------------------

    @staticmethod
    def _positions_in_space(obj, world):
        """取物体基型坐标；``world`` 为真时换算到世界空间。"""
        positions = core.basis_positions(obj)
        if not world:
            return positions
        return core.to_world(obj, positions)

    @staticmethod
    def mode_uses_world(mode):
        """只有世界位置模式比较世界空间，其余模式一律比本地空间。"""
        return mode == core.MODE_WORLD_POSITION

    @staticmethod
    def auto_tolerance(dest_obj, mode):
        """``0 = 自动`` 时使用的容差。"""
        if mode == core.MODE_UV_POSITION:
            return UV_TOLERANCE
        positions = ShapekeyPasteMatch._positions_in_space(
            dest_obj, ShapekeyPasteMatch.mode_uses_world(mode))
        return max(core.bbox_diagonal(positions) * WORLD_TOLERANCE_RATIO, 1e-5)

    @staticmethod
    def resolve_tolerance(dest_obj, mode, max_distance):
        if max_distance and max_distance > 0:
            return float(max_distance)
        return ShapekeyPasteMatch.auto_tolerance(dest_obj, mode)

    @staticmethod
    def _inspect_object(payload, reference, obj):
        if obj is None or getattr(obj, "type", None) != 'MESH':
            return None
        shape_keys = getattr(obj.data, "shape_keys", None)
        if shape_keys is None or shape_keys.reference_key is None:
            return None

        # 体检用本地空间：点序模式才是默认与推荐入口，用世界空间会对着
        # 「复制体被挪到别处」这类正常用法误报不一致。
        try:
            dest_positions = ShapekeyPasteMatch._positions_in_space(obj, False)
        except core.ShapekeyMatchError:
            return None

        source_count = int(payload["vertex_count"])
        dest_count = len(dest_positions)
        agreement = None

        if reference.ok:
            try:
                source_positions = ShapekeyPasteMatch._positions_in_space(
                    reference.obj, False)
            except core.ShapekeyMatchError:
                source_positions = None
            if source_positions is not None:
                count = min(source_count, dest_count, len(source_positions))
                if count > 0:
                    tolerance = ShapekeyPasteMatch.auto_tolerance(
                        obj, core.MODE_VERTEX_INDEX)
                    differences = source_positions[:count] - dest_positions[:count]
                    distances = np.linalg.norm(differences, axis=1)
                    agreement = float(np.count_nonzero(distances <= tolerance) / count)
                else:
                    agreement = 0.0

        if agreement is None:
            mismatch = source_count != dest_count
        else:
            mismatch = source_count != dest_count or agreement < MISMATCH_AGREEMENT

        return TopologyEntry(obj.name, source_count, dest_count, agreement, mismatch)

    @staticmethod
    def inspect(payload, objects):
        """对每个目标物体做拓扑体检，供弹窗与分支判断使用。"""
        reference = ShapekeyPasteMatch.resolve_source(payload)
        entries = []
        mismatch = False
        for obj in objects:
            entry = ShapekeyPasteMatch._inspect_object(payload, reference, obj)
            if entry is None:
                continue
            entries.append(entry)
            mismatch = mismatch or entry.mismatch
        return TopologyReport(tuple(entries), mismatch, reference)

    # ------------------------------------------------------------------
    # 映射
    # ------------------------------------------------------------------

    @staticmethod
    def build_mapping(src_obj, dest_obj, payload, *, mode, max_distance=0.0):
        """建立 ``{目标顶点索引: [(源顶点索引, 权重)]}``。

        未出现在结果里的目标顶点就是未匹配，调用方应保持它们原值。
        """
        if mode not in (core.MODE_VERTEX_INDEX,
                        core.MODE_WORLD_POSITION,
                        core.MODE_UV_POSITION):
            raise core.ShapekeyMatchError(f"未知的匹配方式：{mode}")

        coords = payload["coords"]
        world = ShapekeyPasteMatch.mode_uses_world(mode)
        tolerance = ShapekeyPasteMatch.resolve_tolerance(
            dest_obj, mode, max_distance)

        if mode == core.MODE_UV_POSITION:
            result = ShapekeyPasteMatch._map_by_uv(src_obj, dest_obj, tolerance)
        else:
            result = ShapekeyPasteMatch._map_by_position(
                src_obj, dest_obj, len(coords), tolerance,
                use_index=(mode == core.MODE_VERTEX_INDEX), world=world)

        result.tolerance = tolerance
        return result

    @staticmethod
    def _map_by_position(
            src_obj, dest_obj, source_count, tolerance, *, use_index, world):
        source_positions = ShapekeyPasteMatch._positions_in_space(src_obj, world)
        dest_positions = ShapekeyPasteMatch._positions_in_space(dest_obj, world)
        available = min(source_count, len(source_positions))
        dest_count = len(dest_positions)
        result = PasteMatchResult(pairs={})

        pending = list(range(dest_count))
        if use_index:
            # 点序模式：先用基型位置逐点校验，能对上的直接沿用点序。
            count = min(available, dest_count)
            if count > 0:
                differences = source_positions[:count] - dest_positions[:count]
                distances = np.linalg.norm(differences, axis=1)
                exact = np.flatnonzero(distances <= tolerance)
                for index in exact:
                    position = int(index)
                    result.pairs[position] = [(position, 1.0)]
                result.exact = int(len(exact))
                hit = {int(index) for index in exact}
                pending = [index for index in range(dest_count) if index not in hit]

        if not pending:
            return result

        # 世界位置模式整体走最近邻；点序模式只对校验不过的点做最近邻修正。
        kd, indices = core.build_kdtree(
            (index, source_positions[index]) for index in range(available))
        for dest_index in pending:
            source_index, distance = core.nearest(
                kd, indices, dest_positions[dest_index])
            if source_index is None or distance > tolerance:
                result.unmatched += 1
                continue
            result.pairs[dest_index] = [(source_index, 1.0)]
            if use_index:
                result.rescued += 1
            else:
                result.matched += 1

        return result

    @staticmethod
    def _map_by_uv(src_obj, dest_obj, tolerance):
        source_uv = core.average_uv_per_vertex(src_obj.data)
        dest_uv = core.average_uv_per_vertex(dest_obj.data)
        if not source_uv:
            raise core.ShapekeyMatchError(
                f"源物体 {src_obj.name} 没有可用的 UV")

        # 镜像对称的模型左右两侧常常共用同一片 UV：全部塞进一棵树时，最近邻会在
        # 两侧的同名 UV 点之间随机挑一个（谁先插入就挑谁）。这里按模型原点
        # （本地 X 轴）把源点分成左右两棵树，先查同侧。
        source_sides = core.side_mask(
            ShapekeyPasteMatch._positions_in_space(src_obj, False))
        dest_sides = core.side_mask(
            ShapekeyPasteMatch._positions_in_space(dest_obj, False))
        source_items = sorted(source_uv.items())
        side_trees = {
            side: core.build_kdtree(
                (index, uv) for index, uv in source_items
                if int(source_sides[index]) == side)
            for side in (1, 0)
        }

        result = PasteMatchResult(pairs={})
        for dest_index in range(len(dest_obj.data.vertices)):
            uv = dest_uv.get(dest_index)
            if uv is None:
                result.unmatched += 1
                continue

            # 同侧优先；同侧够不到才退回另一侧。两棵树各取最近再比，等价于原来的
            # 全局最近邻，所以「镜像粘贴」「模型原点偏在一边」这类旧用法不会被打断。
            side = int(dest_sides[dest_index])
            source_index, distance = core.nearest(*side_trees[side], uv)
            if source_index is None or distance > tolerance:
                source_index, distance = core.nearest(
                    *side_trees[1 - side], uv)
            if source_index is None or distance > tolerance:
                result.unmatched += 1
                continue

            result.pairs[dest_index] = [(source_index, 1.0)]
            result.matched += 1
        return result
