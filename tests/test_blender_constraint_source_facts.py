"""Real RNA and persistent Ho Aim metadata, without touching a user's model."""
import bpy, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bpy.props import PointerProperty, BoolProperty, CollectionProperty
from bpy.types import PropertyGroup
from BoneTools.boneProperty import PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo, register_existing_aim_pair, OT_Hotools_RegisterExistingAim
from RigConstraints.source import capture_armature
from RigConstraints.semantics import translate
from RigConstraints.blender.properties import PROPERTY_CLASSES, PG_RigConstraintGroup

class TestProps(PropertyGroup):
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    generateMCH: BoolProperty(default=False)
    constraintGroups: CollectionProperty(type=PG_RigConstraintGroup)
for c in (PG_Hotools_BoneRef,PG_Hotools_AuxBoneInfo,*PROPERTY_CLASSES,TestProps):bpy.utils.register_class(c)
bpy.types.Bone.hotools_boneprops=PointerProperty(type=TestProps)
rig=bpy.data.objects.new('SourceFactsRig',bpy.data.armatures.new('SourceFactsData'));bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig;rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name,head in [('Owner',(0,0,0)),('P',(-1,0,0)),('R',(1,0,0)),('U',(0,1,0)),('Source',(0,0,1))]:
    b=rig.data.edit_bones.new(name);b.head=head;b.tail=(head[0],head[1]+.1,head[2])
bpy.ops.object.mode_set(mode='OBJECT')
owner=rig.pose.bones['Owner']
for ty,name,target in [('COPY_LOCATION','Origin','P'),('DAMPED_TRACK','Aim','R'),('LOCKED_TRACK','Up','U')]:
    c=owner.constraints.new(ty);c.name=name;c.target=rig;c.subtarget=target
    if ty=='DAMPED_TRACK':c.track_axis='TRACK_X'
    if ty=='LOCKED_TRACK':c.track_axis='TRACK_NEGATIVE_Z';c.lock_axis='LOCK_X'
before=translate(capture_armature(rig))
assert len(before['sources']) == 3 and not before['declarations']
assert [s['semanticType'] for s in before['semantics']] == ['COPY_LOCATION']
before_pose=owner.matrix_basis.copy()
before_constraints=[(c.name,c.type,c.influence,c.subtarget) for c in owner.constraints]
register_existing_aim_pair(owner)
register_existing_aim_pair(owner)
assert owner.matrix_basis==before_pose
assert before_constraints==[(c.name,c.type,c.influence,c.subtarget) for c in owner.constraints]
aux=owner.bone.hotools_boneprops.auxBone
assert [r.name for r in aux.sourceBones]==['R','U']
assert [r.name for r in aux.constraintNames]==['Aim','Up']
bpy.utils.register_class(OT_Hotools_RegisterExistingAim)
from Utils.bone_selection import select_bones
bpy.ops.object.mode_set(mode='POSE');select_bones(rig,['Owner'])
assert bpy.ops.hotools.register_existing_aim()=={'FINISHED'}
bpy.ops.object.mode_set(mode='OBJECT')
aux=rig.data.bones['Owner'].hotools_boneprops.auxBone
aux.auxType='FAN'
try:
    register_existing_aim_pair(rig.pose.bones['Owner'])
except ValueError:
    pass
else:
    raise AssertionError('Existing Fan ownership was overwritten')
assert aux.auxType=='FAN'
aux.auxType='AIM'
after=translate(capture_armature(rig))
assert after['schemaVersion'] == 4 and not after['diagnostics']
assert len(after['sources']) == 3
aim = next(s for s in after['semantics'] if s['semanticType'] == 'AIM')
by_id = {s['sourceId']: s for s in after['sources']}
assert [by_id[sid]['constraint']['stackIndex'] for sid in aim['sourceIds']] == [1, 2]
assert 'originBone' not in aim['parameters']
assert all(len(b['restMatrix']) == 16 and len(b['poseBasis']) == 16 for b in after['sourceContext']['bones'])
weighted=rig.pose.bones['Source'].constraints.new('ARMATURE')
for name,weight in [('P',.5),('R',.3)]:
    t=weighted.targets.new();t.target=rig;t.subtarget=name;t.weight=weight
raw=next(r['constraint'] for r in translate(capture_armature(rig))['sources'] if r['ownerBone']=='Source')
assert len(raw['references']['targets'])==2
assert raw['references']['targets'][1]['properties']['subtarget']=='R'
from Exporter.FbxExporter import FBXExporter
rig.data.bones['R'].hotools_boneprops.generateMCH=True
FBXExporter.clear_armatures_bone_rotation([rig],[rig],rig)
mch=translate(capture_armature(rig))
aim = next(s for s in mch['semantics'] if s['semanticType'] == 'AIM')
assert aim['parameters']['targetBone'] == 'MCH_R'
assert rig.data.bones['Owner'].hotools_boneprops.auxBone.sourceBones[0].name=='MCH_R'
raw=next(r['constraint'] for r in mch['sources'] if r['ownerBone']=='Source')
assert raw['references']['targets'][1]['properties']['subtarget']=='MCH_R'
rig.pose.bones['Owner'].keyframe_insert(data_path='rotation_euler',frame=1)
animated=translate(capture_armature(rig))
assert next(b for b in animated['sourceContext']['bones'] if b['boneName']=='Owner')['hasPoseAnimation']
print('BLENDER_SOURCE_FACTS_OK',bpy.app.version_string)
