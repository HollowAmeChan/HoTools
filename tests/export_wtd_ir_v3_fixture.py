"""Build the WTD regression fixture in background Blender; never save the .blend.

blender --background --factory-startup --disable-autoexec WTD-summer.blend
        --python tests/export_wtd_ir_v3_fixture.py -- ABSOLUTE_OUTPUT_DIRECTORY
"""
import json
import math
from pathlib import Path
import random
import sys

import bpy
from bpy.props import BoolProperty, PointerProperty
from bpy.types import PropertyGroup
from mathutils import Euler, Matrix, Vector

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from BoneTools.boneProperty import PG_Hotools_BoneRef, PG_Hotools_AuxBoneInfo
from Exporter.ConstraintIRExporter import ConstraintIRExporter

class FixtureBoneProps(PropertyGroup):
    generateMCH: BoolProperty(default=False)
    auxBone: PointerProperty(type=PG_Hotools_AuxBoneInfo)

for cls in (PG_Hotools_BoneRef,PG_Hotools_AuxBoneInfo,FixtureBoneProps):bpy.utils.register_class(cls)
bpy.types.Bone.hotools_boneprops=PointerProperty(type=FixtureBoneProps)
out=Path(sys.argv[sys.argv.index('--')+1]).resolve();out.mkdir(parents=True,exist_ok=True)
root='CTR_C1_ChestAddon'
rig=next(o for o in bpy.data.objects if o.type=='ARMATURE' and root in o.pose.bones)
mesh=bpy.data.objects['上衣蝴蝶结']
# Saved viewport visibility must not silently remove the actual mesh from the
# selected-object FBX fixture, or leave evaluated probes unevaluated.
wanted=set(mesh.users_collection)|set(rig.users_collection)
def paths(layer):
    result=[[layer]] if layer.collection in wanted else []
    for child in layer.children:
        result.extend([[layer]+p for p in paths(child)])
    return result
for path in paths(bpy.context.view_layer.layer_collection):
    for layer in path:
        layer.exclude=False;layer.hide_viewport=False;layer.collection.hide_viewport=False
for obj in (rig,mesh):
    obj.hide_select=False;obj.hide_viewport=False;obj.hide_set(False)
bpy.context.view_layer.update()
rig.animation_data_clear()
for p in rig.pose.bones:p.matrix_basis=Matrix.Identity(4)
rig.data.pose_position='POSE';bpy.context.view_layer.update()

def flat(m):return [float(v) for row in m for v in row]
def xyz(v):return dict(zip(('x','y','z'),v))
def save(name,data):(out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

pending=[root];names=set()
while pending:
    name=pending.pop()
    if name in names:continue
    names.add(name);owner=rig.pose.bones[name]
    if owner.parent:pending.append(owner.parent.name)
    for c in owner.constraints:
        if getattr(c,'target',None)==rig and getattr(c,'subtarget',''):pending.append(c.subtarget)
        pending.extend(t.subtarget for t in getattr(c,'targets',()) if t.target==rig and t.subtarget)
names=sorted(names)

def scoped(ir):
    # Other authoring experiments in the same .blend are not part of this fixture.
    for key in ('knownConstraints','unknownConstraints','aimBindings'):
        ir[key]=[r for r in ir[key] if r['ownerBone'] in names]
    ir['auxBones']=[r for r in ir['auxBones'] if r['boneName'] in names]
    ir['mchBindings']=[r for r in ir['mchBindings'] if r['mchBone'] in names and r['sourceBone'] in names]
    ir['mchEnabledBones']=[n for n in ir['mchEnabledBones'] if n in names]
    ir['bindingContext']['bones']=[b for b in ir['bindingContext']['bones'] if b['boneName'] in names]
    return ir

save('unmarked_constraint_ir.json',scoped(ConstraintIRExporter.export_to_dict(rig)))
for name in ('DIR_C1_ChestAddon_L','DIR_C1_ChestAddon_R'):
    owner=rig.pose.bones[name];aux=owner.bone.hotools_boneprops.auxBone
    aux.isAuxBone=True;aux.auxType='AIM';aux.aimVersion=1
    aux.sourceBones.clear();aux.constraintNames.clear()
    for c in owner.constraints:
        if c.type in {'DAMPED_TRACK','LOCKED_TRACK'}:
            aux.sourceBones.add().name=c.subtarget;aux.constraintNames.add().name=c.name
ir=scoped(ConstraintIRExporter.export_to_dict(rig))
ir['bindingContext']['fbxBoneAxes']='Y_X'
assert len(ir['aimBindings'])==2 and not ir['unknownConstraints'], (ir['aimBindings'], [(x['ownerBone'],x['constraint']['constraintType'],x['constraint']['parameters']) for x in ir['unknownConstraints']])
save('original_constraint_ir.json',ir)

rests={n:rig.data.bones[n].matrix_local.copy() for n in names}
sources=['hips','spine','chest','breast_L','breast_R']
probes=set(random.Random(23).sample(range(len(mesh.data.vertices)),18))
for axis in range(3):
    probes.add(min(range(len(mesh.data.vertices)),key=lambda i:mesh.data.vertices[i].co[axis]))
    probes.add(max(range(len(mesh.data.vertices)),key=lambda i:mesh.data.vertices[i].co[axis]))
probes=sorted(probes)
cases=[('rest',{}),('chest_bend',{'chest':((25,0,0),(0,0,0),(1,1,1))}),
       ('chest_twist',{'chest':((0,30,0),(0,0,0),(1,1,1))}),
       ('breast_left',{'breast_L':((18,12,-8),(.005,.002,0),(1,1,1))}),
       ('breast_right',{'breast_R':((-15,-10,7),(-.003,.002,0),(1,1,1))}),
       ('breast_opposed',{'breast_L':((18,12,-8),(0,0,0),(1,1,1)),'breast_R':((-15,-10,7),(0,0,0),(1,1,1))}),
       ('chest_and_breasts',{'chest':((15,20,-12),(0,0,0),(1,1,1)),'breast_L':((10,-8,5),(.002,0,0),(1,1,1)),'breast_R':((-12,6,-4),(-.002,0,0),(1,1,1))}),
       ('root_motion',{'hips':((10,35,-8),(.2,.1,-.05),(1,1,1))}),
       ('uniform_scale',{'hips':((0,0,0),(0,0,0),(1.2,1.2,1.2))}),
       ('nonuniform_scale',{'chest':((12,15,-7),(0,0,0),(1.08,.94,1.03))})]
rng=random.Random(20261025)
for i in range(50):
    transforms={}
    for name,amplitude in [('hips',15),('spine',10),('chest',20),('breast_L',15),('breast_R',15)]:
        transforms[name]=(tuple(rng.uniform(-amplitude,amplitude) for _ in range(3)),tuple(rng.uniform(-.003,.003) for _ in range(3)) if name.startswith('breast') else (0,0,0),(1,1,1))
    cases.append((f'random_{i:02}',transforms))
samples=[]
for label,transforms in cases:
    for p in rig.pose.bones:p.matrix_basis=Matrix.Identity(4)
    for name,(angles,position,scale) in transforms.items():
        rig.pose.bones[name].matrix_basis=Matrix.LocRotScale(Vector(position),Euler(tuple(math.radians(v) for v in angles),'XYZ').to_quaternion(),Vector(scale))
    bpy.context.view_layer.update()
    evaluated=mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    samples.append({'name':label,'inputs':[{'name':n,'matrix':flat(rig.pose.bones[n].matrix)} for n in sources],
        'expected':[{'name':n,'matrix':flat(rig.pose.bones[n].matrix)} for n in names],
        'meshProbes':[xyz(evaluated.matrix_world@evaluated.data.vertices[i].co) for i in probes]})
save('samples.json',{'source':bpy.data.filepath,'blenderVersion':bpy.app.version_string,'root':root,'meshName':mesh.name,
    'bones':[{'name':n,'matrix':flat(rests[n])} for n in names],
    'authoredSamples':samples,'meshRestProbes':[xyz(mesh.matrix_world@mesh.data.vertices[i].co) for i in probes]})

for p in rig.pose.bones:
    p.matrix_basis=Matrix.Identity(4)
    for c in list(p.constraints):p.constraints.remove(c)
for obj in bpy.context.view_layer.objects:obj.select_set(False)
rig.hide_set(False);rig.hide_viewport=False;rig.select_set(True);bpy.context.view_layer.objects.active=rig
bpy.ops.object.mode_set(mode='EDIT')
for b in list(rig.data.edit_bones):
    if b.name not in names:rig.data.edit_bones.remove(b)
bpy.ops.object.mode_set(mode='OBJECT');bpy.context.view_layer.update()
mesh.hide_set(False);mesh.hide_viewport=False;mesh.hide_select=False
bpy.context.view_layer.update();mesh.select_set(True)
assert mesh in bpy.context.selected_objects, 'Fixture mesh is not selectable/visible'
bpy.ops.export_scene.fbx(filepath=str(out/'ChestAddon.fbx'),use_selection=True,object_types={'ARMATURE','MESH'},
    global_scale=1,apply_unit_scale=True,apply_scale_options='FBX_SCALE_ALL',use_space_transform=True,bake_space_transform=False,
    add_leaf_bones=False,primary_bone_axis='Y',secondary_bone_axis='X',use_armature_deform_only=False,
    armature_nodetype='NULL',bake_anim=False,axis_forward='-Z',axis_up='Y')
print('WTD_IR_V3_FIXTURE_OK',len(names),len(samples),len(probes))
