import unittest
import sys
from types import SimpleNamespace
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from Utils.keymap_utils import find_user_keymap_item


class _Items(list):
    def find_from_operator(self, idname, properties=None):
        return next((item for item in self if item.idname == idname), None)


class _KeywordItems(list):
    """模仿 Blender 4.1+ 的 ``find_from_operator``：properties 仅限关键字。"""

    def find_from_operator(self, idname, *, properties=None):
        for item in self:
            if item.idname != idname:
                continue
            if properties is None:
                return item
            if all(
                getattr(item.properties, name, None)
                == getattr(properties, name, None)
                for name in vars(properties)
            ):
                return item
        return None


def _pie_item(menu_name, key_type="A"):
    return SimpleNamespace(
        idname="wm.call_menu_pie",
        properties=SimpleNamespace(name=menu_name),
        type=key_type,
    )


def _uv_editor_config(user_items):
    user_map = SimpleNamespace(
        name="UV Editor",
        space_type="EMPTY",
        region_type="WINDOW",
        keymap_items=user_items,
    )
    return SimpleNamespace(keymaps=_Maps([user_map])), user_map


class _Maps(list):
    def find(self, name, *, space_type=None, region_type=None):
        return next(
            (
                keymap
                for keymap in self
                if keymap.name == name
                and keymap.space_type == space_type
                and keymap.region_type == region_type
            ),
            None,
        )


class KeymapPreferenceTests(unittest.TestCase):
    def test_missing_user_item_is_not_replaced_by_addon_item(self):
        addon_item = SimpleNamespace(
            idname="ho.example",
            properties=SimpleNamespace(name="Example"),
        )
        addon_map = SimpleNamespace(
            name="Window",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=[addon_item],
        )
        user_config = SimpleNamespace(keymaps=_Maps([]))

        self.assertIsNone(
            find_user_keymap_item(user_config, addon_map, addon_item)
        )

    def test_missing_user_item_in_existing_map_is_not_editable_addon_default(self):
        addon_item = SimpleNamespace(
            idname="ho.example",
            properties=SimpleNamespace(name="Example"),
        )
        addon_map = SimpleNamespace(
            name="Window",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=[addon_item],
        )
        user_map = SimpleNamespace(
            name="Window",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=[],
        )
        user_config = SimpleNamespace(keymaps=_Maps([user_map]))

        self.assertIsNone(
            find_user_keymap_item(user_config, addon_map, addon_item)
        )

    def test_resolves_modified_user_item_instead_of_addon_item(self):
        addon_item = SimpleNamespace(
            idname="ho.example",
            properties=SimpleNamespace(name="Example"),
            type="A",
        )
        addon_map = SimpleNamespace(
            name="3D View Generic",
            space_type="VIEW_3D",
            region_type="WINDOW",
            keymap_items=[addon_item],
        )
        user_item = SimpleNamespace(
            idname="ho.example",
            properties=SimpleNamespace(name="Example"),
            type="F",
        )
        user_map = SimpleNamespace(
            name=addon_map.name,
            space_type=addon_map.space_type,
            region_type=addon_map.region_type,
            keymap_items=_Items([user_item]),
        )
        user_config = SimpleNamespace(keymaps=_Maps([user_map]))

        resolved = find_user_keymap_item(user_config, addon_map, addon_item)

        self.assertIsNotNone(resolved)
        self.assertIs(resolved[0], user_map)
        self.assertIs(resolved[1], user_item)
        self.assertIsNot(resolved[1], addon_item)

    def test_preserves_ordinal_for_duplicate_operator_bindings(self):
        addon_items = [
            SimpleNamespace(idname="ho.example", properties=SimpleNamespace(slot="a")),
            SimpleNamespace(idname="ho.example", properties=SimpleNamespace(slot="b")),
        ]
        addon_map = SimpleNamespace(
            name="Window",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=addon_items,
        )
        user_items = [
            SimpleNamespace(idname="ho.example", properties=SimpleNamespace(slot="a")),
            SimpleNamespace(idname="ho.example", properties=SimpleNamespace(slot="b")),
        ]
        user_map = SimpleNamespace(
            name="Window",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=user_items,
        )
        user_config = SimpleNamespace(keymaps=_Maps([user_map]))

        resolved = find_user_keymap_item(user_config, addon_map, addon_items[1])

        self.assertIs(resolved[1], user_items[1])

    def test_shared_menu_operator_does_not_resolve_to_foreign_addon(self):
        """另一个插件（如 UV Toolkit）的饼菜单不能顶替 HoTools 的绑定。"""
        addon_item = _pie_item("HO_MT_uv_align_pie")
        addon_map = SimpleNamespace(
            name="UV Editor",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=[addon_item],
        )
        foreign_item = _pie_item("UVTOOLKIT_MT_pie_uv_editor", key_type="Q")
        own_item = _pie_item("HO_MT_uv_align_pie")
        user_config, user_map = _uv_editor_config(
            _KeywordItems([foreign_item, own_item])
        )

        resolved = find_user_keymap_item(user_config, addon_map, addon_item)

        self.assertIs(resolved[0], user_map)
        self.assertIs(resolved[1], own_item)

    def test_shared_menu_operator_falls_back_to_matching_properties(self):
        """用户配置项来自不支持关键字参数的实现时也要按属性匹配。"""
        addon_item = _pie_item("HO_MT_uv_align_pie")
        addon_map = SimpleNamespace(
            name="UV Editor",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=[addon_item],
        )
        foreign_item = _pie_item("UVTOOLKIT_MT_pie_uv_editor", key_type="Q")
        own_item = _pie_item("HO_MT_uv_align_pie")
        user_config, _user_map = _uv_editor_config(
            _Items([foreign_item, own_item])
        )

        resolved = find_user_keymap_item(user_config, addon_map, addon_item)

        self.assertIs(resolved[1], own_item)

    def test_ambiguous_foreign_binding_is_not_guessed(self):
        """只有别的插件的同名操作符时不能把它的绑定显示成 HoTools 的。"""
        addon_item = _pie_item("HO_MT_uv_align_pie")
        addon_map = SimpleNamespace(
            name="UV Editor",
            space_type="EMPTY",
            region_type="WINDOW",
            keymap_items=[addon_item],
        )
        foreign_item = _pie_item("UVTOOLKIT_MT_pie_uv_editor", key_type="Q")
        user_config, _user_map = _uv_editor_config(_KeywordItems([foreign_item]))

        self.assertIsNone(
            find_user_keymap_item(user_config, addon_map, addon_item)
        )


if __name__ == "__main__":
    unittest.main()
