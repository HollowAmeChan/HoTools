"""MC2 MeshCloth setup 的持久 RNA 纯数据 schema；不导入 bpy。"""

MESH_COLLISION_RNA_FIELDS = (
    {
        "name": "mc2_base_pose_proxy",
        "property": "pointer",
        "kwargs": {
            "type": "Object",
            "name": "BasePose只读对象",
            "description": "MC2每帧只读这个Mesh对象的骨架/修改器变形结果作为基础姿态；不要指向当前物理写入对象",
            "poll": "mesh_object",
        },
    },
    {
        "name": "radius_vertex_group",
        "property": "string",
        "kwargs": {"name": "半径顶点组", "description": "用于缩放逐顶点碰撞半径的顶点组；留空时所有顶点使用完整半径", "default": ""},
    },
    {
        "name": "pin_enabled",
        "property": "bool",
        "kwargs": {"name": "Pin启用", "description": "启用简单布料Pin顶点；只在物理cache重建时读取，模拟过程中修改不会立即生效", "default": False},
    },
    {
        "name": "pin_vertex_group",
        "property": "string",
        "kwargs": {"name": "Pin顶点组", "description": "用于指定固定顶点的顶点组；启用Pin且留空时固定全部顶点", "default": ""},
    },
    {
        "name": "primary_collision_group",
        "property": "int",
        "kwargs": {"name": "主碰撞组", "description": "这个网格的所有逐顶点碰撞球所属的主碰撞组", "default": 1, "min": 1, "max": 16},
    },
    {
        "name": "collided_by_groups",
        "property": "int",
        "kwargs": {"name": "被碰撞组", "description": "允许哪些主碰撞组碰撞到这个网格的逐顶点碰撞球", "default": 0, "min": 0, "max": 65535},
    },
)


__all__ = ["MESH_COLLISION_RNA_FIELDS"]
