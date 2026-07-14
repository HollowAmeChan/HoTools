from ..BoneTools.boneHumanoid import OP_MoveHumanoidBonesToCollection
from ..BoneTools.boneOperators import OP_ApplyRestPose


def drawWeightPanel(layout, context):
    column = layout.column(align=True)
    column.operator(
        OP_MoveHumanoidBonesToCollection.bl_idname,
        icon='GROUP_BONE',
    )
    column.operator(
        OP_ApplyRestPose.bl_idname,
        text="强制应用姿态与Mesh",
        icon='ARMATURE_DATA',
    )
