"""IR v3 direct classification, explicit Aim ownership, and raw data preservation."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent))
from test_constraint_export import BoneCollection, bone, constraint, ConstraintIRExporter


def fixture(marked=True):
    bones=BoneCollection([bone(n) for n in ('P','R','U','Aim','Raw','Weighted')])
    poses=BoneCollection([NS(name=b.name,constraints=[]) for b in bones])
    rig=NS(type='ARMATURE',name='Rig',data=NS(bones=bones),pose=NS(bones=poses))
    for owner in ('Aim','Raw'):
        poses.get(owner).constraints.extend([
            constraint(rig,'COPY_LOCATION','Origin','P',owner_space='WORLD',target_space='WORLD',head_tail=0.0,use_offset=False,use_x=True,use_y=True,use_z=True,invert_x=False,invert_y=False,invert_z=False),
            constraint(rig,'DAMPED_TRACK','Aim','R',owner_space='WORLD',target_space='WORLD',head_tail=0.0,track_axis='TRACK_X'),
            constraint(rig,'LOCKED_TRACK','Up','U',owner_space='WORLD',target_space='WORLD',head_tail=0.0,track_axis='TRACK_NEGATIVE_Z',lock_axis='LOCK_X'),
        ])
    if marked:
        aux=bones.get('Aim').hotools_boneprops.auxBone
        aux.isAuxBone=True;aux.auxType='AIM';aux.aimVersion=1
        aux.sourceBones=[NS(name=n) for n in ('R','U')]
        aux.constraintNames=[NS(name=n) for n in ('Aim','Up')]
    poses.get('Weighted').constraints.append(constraint(
        rig,'ARMATURE','Weighted','',targets=[NS(target=rig,subtarget='P',weight=.5),NS(target=rig,subtarget='R',weight=.3)],
        use_deform_preserve_volume=False,use_bone_envelopes=False,use_current_location=False))
    return rig


def test_v3_known_types_and_explicit_aim():
    data=ConstraintIRExporter.export_to_dict(fixture())
    assert data['schemaVersion']==3
    assert data['aimBindings']==[dict(ownerBone='Aim',semanticType='AIM',semanticVersion=1,targetBone='R',upBone='U',upMode='OBJECT_POSITION',aimAxis='TRACK_X',upAxis='TRACK_NEGATIVE_Z',muted=False,constraintStackIndices=[1,2])]
    assert len([r for r in data['knownConstraints'] if r['relationType']=='AIM_BINDING'])==2
    assert {r['constraint']['constraintType'] for r in data['unknownConstraints']}=={'DAMPED_TRACK','LOCKED_TRACK'}
    assert all(r['ownerBone']=='Raw' for r in data['unknownConstraints'])
    arm=next(r['constraint'] for r in data['knownConstraints'] if r['ownerBone']=='Weighted')
    assert arm['references']['targets'][1]['properties']['weight']==.3
    assert arm['parameters']['use_deform_preserve_volume'] is False
    keys=[(r['ownerBone'],r['constraint']['stackIndex']) for r in data['knownConstraints']+data['unknownConstraints']]
    assert len(keys)==len(set(keys))==7


def test_broken_aim_marker_does_not_claim_tracking():
    for mutation in (
        lambda r:setattr(r.data.bones.get('Aim').hotools_boneprops.auxBone,'aimVersion',2),
        lambda r:setattr(r.pose.bones.get('Aim').constraints[2],'lock_axis','LOCK_Y'),
        lambda r:setattr(r.pose.bones.get('Aim').constraints[1],'influence',.5),
        lambda r:setattr(r.pose.bones.get('Aim').constraints[1],'mute',True),
        lambda r:r.data.bones.get('Aim').hotools_boneprops.auxBone.constraintNames.append(NS(name='Aim')),
    ):
        rig=fixture();mutation(rig);data=ConstraintIRExporter.export_to_dict(rig)
        assert data['aimBindings']==[]
        assert any(r['ownerBone']=='Aim' and r['constraint']['constraintType']=='DAMPED_TRACK' for r in data['unknownConstraints'])
        assert any(r['ownerBone']=='Aim' and r['constraint']['constraintType']=='COPY_LOCATION' for r in data['knownConstraints'])


def test_known_is_not_backend_support_or_validity():
    rig=fixture(False)
    rig.pose.bones.get('Weighted').constraints[0].targets=[]
    rig.pose.bones.get('Raw').constraints[0].target=None
    rig.pose.bones.get('Raw').constraints[0].owner_space='CUSTOM'
    data=ConstraintIRExporter.export_to_dict(rig)
    assert data['aimBindings']==[]
    assert any(r['ownerBone']=='Weighted' for r in data['knownConstraints'])
    assert any(r['ownerBone']=='Raw' and r['constraint']['parameters']['owner_space']=='CUSTOM' for r in data['knownConstraints'])


def test_aim_has_no_location_or_lbs_requirement():
    rig=fixture()
    rig.pose.bones.get('Aim').constraints.pop(0)
    data=ConstraintIRExporter.export_to_dict(rig)
    assert data['aimBindings'][0]['constraintStackIndices']==[0,1]
    assert 'originBone' not in data['aimBindings'][0]
    assert {r['constraint']['constraintType'] for r in data['knownConstraints'] if r['ownerBone']=='Aim'}=={'DAMPED_TRACK','LOCKED_TRACK'}


def test_aim_ownership_can_include_independent_generated_copy():
    rig=fixture()
    rig.data.bones.get('Aim').hotools_boneprops.auxBone.constraintNames.append(NS(name='Origin'))
    data=ConstraintIRExporter.export_to_dict(rig)
    assert data['aimBindings'][0]['constraintStackIndices']==[1,2]
    location=next(r for r in data['knownConstraints'] if r['ownerBone']=='Aim' and r['constraint']['stackIndex']==0)
    assert location['relationType']=='DIRECT_CONSTRAINT'


if __name__=='__main__':
    test_v3_known_types_and_explicit_aim()
    test_broken_aim_marker_does_not_claim_tracking()
    test_known_is_not_backend_support_or_validity()
    test_aim_has_no_location_or_lbs_requirement()
    test_aim_ownership_can_include_independent_generated_copy()
    print('IR_V3_UNIT_OK')
