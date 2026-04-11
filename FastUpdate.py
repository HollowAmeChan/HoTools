import bpy
import urllib.request
import json
import tempfile
import os

from . import bl_info


class HO_OT_update_addon(bpy.types.Operator):
    bl_idname = "ho.update_addon"
    bl_label = "检查更新"
    bl_description = "从GitHub下载最新版本并自动更新插件"

    def execute(self, context):
        try:
            repo = "HollowAmeChan/HoTools"
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"

            # 1️⃣ 获取 release 信息
            with urllib.request.urlopen(api_url) as response:
                data = json.loads(response.read().decode())

            latest_tag = data.get("tag_name", "")
            assets = data.get("assets", [])

            if not assets:
                self.report({'ERROR'}, "Release里没有可下载文件")
                return {'CANCELLED'}

            # 2️⃣ 当前版本
            current_version = bl_info.get("version", (0, 0, 0))
            current_version_str = "".join(map(str, current_version))

            # tag: v20260412-153000 → 20260412153000
            latest_version_str = latest_tag.replace("v", "").replace("-", "")

            if latest_version_str in current_version_str:
                self.report({'INFO'}, "已经是最新版本")
                return {'CANCELLED'}

            # 3️⃣ 找zip（优先HoTools）
            zip_url = None
            zip_name = None

            for asset in assets:
                name = asset["name"]
                if name.endswith(".zip") and "HoTools" in name:
                    zip_url = asset["browser_download_url"]
                    zip_name = name
                    break

            if not zip_url:
                # fallback：随便拿一个zip
                for asset in assets:
                    if asset["name"].endswith(".zip"):
                        zip_url = asset["browser_download_url"]
                        zip_name = asset["name"]
                        break

            if not zip_url:
                self.report({'ERROR'}, "没有找到zip文件")
                return {'CANCELLED'}

            # 4️⃣ 下载
            tmp_dir = tempfile.gettempdir()
            zip_path = os.path.join(tmp_dir, zip_name)

            self.report({'INFO'}, "正在下载更新...")
            urllib.request.urlretrieve(zip_url, zip_path)

            # 5️⃣ 安装插件（覆盖）
            bpy.ops.preferences.addon_install(
                filepath=zip_path,
                overwrite=True
            )

            # 6️⃣ 自动启用（动态获取模块名，避免大小写坑）
            addon_name = os.path.basename(os.path.dirname(__file__))
            bpy.ops.preferences.addon_enable(module=addon_name)

            self.report({'INFO'}, f"更新完成: {latest_tag}（建议重启Blender）")

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"更新失败: {str(e)}")
            return {'CANCELLED'}       

def register():
    bpy.utils.register_class(HO_OT_update_addon)

def unregister():
    bpy.utils.unregister_class(HO_OT_update_addon)
    