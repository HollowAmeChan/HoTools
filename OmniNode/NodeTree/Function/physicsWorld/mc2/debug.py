"""MC2 debug draw 声明；框架阶段不生成几何。"""

from .names import MC2_DEBUG_DRAW_MODE


MC2_DEBUG_DRAW_MODES = {
    MC2_DEBUG_DRAW_MODE: {
        "label": "MC2",
        "owner": "physicsWorld.mc2",
        "implementation_status": "framework_only",
        "setup_types": ("mesh_cloth", "bone_cloth", "bone_spring"),
    },
}
