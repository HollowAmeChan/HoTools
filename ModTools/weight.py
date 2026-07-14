from ..BoneTools.boneHumanoid import OP_MoveHumanoidBonesToCollection


def drawWeightPanel(layout, context):
    column = layout.column(align=True)
    column.operator(
        OP_MoveHumanoidBonesToCollection.bl_idname,
        icon='GROUP_BONE',
    )
