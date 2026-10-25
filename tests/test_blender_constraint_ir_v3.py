"""Real RNA and persistent Ho Aim metadata, without touching a user's model."""
import bpy, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bpy.props import PointerProperty, BoolProperty
from bpy.types import PropertyGroup
from BoneTools.boneProperty import PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo
from Exporter.ConstraintIRExporter import ConstraintIRExporter

class TestProps(PropertyGroup):
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)
    generateMCH: BoolProperty(default=False)
for c in (PG_Hotools_BoneRef,PG_Hotools_AuxBoneInfo,TestProps):bpy.utils.register_class(c)
bpy.types.Bone.hotools_boneprops=PointerProperty(type=TestProps)
rig=bpy.data.objects.new('V3Rig',bpy.data.armatures.new('V3Data'));bpy.context.scene.collection.objects.link(rig)
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
before=ConstraintIRExporter.export_to_dict(rig)
assert len(before['knownConstraints'])==1 and len(before['unknownConstraints'])==2
aux=owner.bone.hotools_boneprops.auxBone;aux.isAuxBone=True;aux.auxType='AIM';aux.aimVersion=1
for n in ('R','U'):aux.sourceBones.add().name=n
for n in ('Aim','Up'):aux.constraintNames.add().name=n
after=ConstraintIRExporter.export_to_dict(rig)
assert after['schemaVersion']==3 and after['unknownConstraints']==[]
assert len(after['knownConstraints'])==3
assert after['aimBindings'][0]['constraintStackIndices']==[1,2]
assert 'originBone' not in after['aimBindings'][0]
assert all(len(b['restMatrix'])==16 and len(b['poseBasis'])==16 for b in after['bindingContext']['bones'])
weighted=rig.pose.bones['Source'].constraints.new('ARMATURE')
for name,weight in [('P',.5),('R',.3)]:
    t=weighted.targets.new();t.target=rig;t.subtarget=name;t.weight=weight
raw=next(r['constraint'] for r in ConstraintIRExporter.export_to_dict(rig)['knownConstraints'] if r['ownerBone']=='Source')
assert len(raw['references']['targets'])==2
assert raw['references']['targets'][1]['properties']['subtarget']=='R'
from Exporter.FbxExporter import FBXExporter
rig.data.bones['R'].hotools_boneprops.generateMCH=True
FBXExporter.clear_armatures_bone_rotation([rig],[rig],rig)
mch=ConstraintIRExporter.export_to_dict(rig)
assert mch['aimBindings'][0]['targetBone']=='MCH_R'
assert rig.data.bones['Owner'].hotools_boneprops.auxBone.sourceBones[0].name=='MCH_R'
raw=next(r['constraint'] for r in mch['knownConstraints'] if r['ownerBone']=='Source')
assert raw['references']['targets'][1]['properties']['subtarget']=='MCH_R'
rig.pose.bones['Owner'].keyframe_insert(data_path='rotation_euler',frame=1)
animated=ConstraintIRExporter.export_to_dict(rig)
assert next(b for b in animated['bindingContext']['bones'] if b['boneName']=='Owner')['hasPoseAnimation']
print('BLENDER_IR_V3_OK',bpy.app.version_string)
