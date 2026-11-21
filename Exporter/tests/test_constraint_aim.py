"""Strict Aim inspection and v4 explicit declaration/raw source boundaries."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent))
from test_constraint_export import BoneCollection, bone, constraint
from RigConstraints.source import capture_armature
from RigConstraints.semantics import inspect_aim_pair, translate


def fixture(marked=True):
    bones=BoneCollection([bone(n) for n in ('P','R','U','Aim','Raw','Weighted')])
    poses=BoneCollection([NS(name=b.name,bone=b,constraints=[]) for b in bones])
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


def declaration(owner):
    members = [NS(constraintName="Aim", constraintType="DAMPED_TRACK", role="aim", order=0),
               NS(constraintName="Up", constraintType="LOCKED_TRACK", role="up", order=1)]
    owner.bone.hotools_boneprops.constraintGroups = [NS(groupId="explicit_aim", semanticType="AIM", semanticVersion=1,
        generatorId="hotools.aux.aim", evidence="EXPLICIT", ownsBone=False, members=members)]


def test_explicit_aim_preserves_independent_copy_and_weighted_sources():
    rig=fixture()
    owner=rig.pose.bones.get('Aim')
    inspected=inspect_aim_pair(rig, owner)
    assert [index for index, _ in inspected['selected']] == [1, 2]
    assert inspected['sources'] == ['R', 'U'] and inspected['aim_axis'] == 'TRACK_X'
    before=capture_armature(rig)
    assert not before['declarations']  # Old aux data is not an explicit declaration.
    declaration(owner)
    data=translate(capture_armature(rig))
    aim=next(row for row in data['semantics'] if row['semanticType']=='AIM')
    assert aim['parameters']['targetBone']=='R' and aim['parameters']['upBone']=='U'
    assert 'originBone' not in aim['parameters']
    by_id={row['sourceId']:row for row in data['sources']}
    assert [by_id[sid]['constraint']['stackIndex'] for sid in aim['sourceIds']]==[1,2]
    assert any(row['semanticType']=='COPY_LOCATION' and row['ownerBone']=='Aim' for row in data['semantics'])
    arm=next(row['constraint'] for row in data['sources'] if row['ownerBone']=='Weighted')
    assert arm['references']['targets'][1]['properties']['weight']==.3
    assert arm['parameters']['use_deform_preserve_volume'] is False
    keys=[(row['ownerBone'],row['constraint']['stackIndex']) for row in data['sources']]
    assert len(keys)==len(set(keys))==7
    assert all(row['ownerBone']=='Raw' for row in data['diagnostics'] if row['status']=='UNKNOWN')


def test_invalid_aim_pair_does_not_claim_or_modify_tracking():
    for mutation in (
        lambda r:setattr(r.pose.bones.get('Aim').constraints[2],'lock_axis','LOCK_Y'),
        lambda r:setattr(r.pose.bones.get('Aim').constraints[1],'influence',.5),
        lambda r:setattr(r.pose.bones.get('Aim').constraints[1],'mute',True),
        lambda r:setattr(r.pose.bones.get('Aim').constraints[1],'target',None),
    ):
        rig=fixture();mutation(rig);owner=rig.pose.bones.get('Aim')
        before=[vars(c).copy() for c in owner.constraints]
        assert inspect_aim_pair(rig,owner) is None
        assert before==[vars(c).copy() for c in owner.constraints]
        declaration(owner)
        data=translate(capture_armature(rig))
        assert not any(row['semanticType']=='AIM' for row in data['semantics'])
        assert any(row['ownerBone']=='Aim' and row['status']=='BROKEN' for row in data['diagnostics'])


def test_raw_source_is_retained_even_when_not_executable():
    rig=fixture(False)
    rig.pose.bones.get('Weighted').constraints[0].targets=[]
    rig.pose.bones.get('Raw').constraints[0].target=None
    rig.pose.bones.get('Raw').constraints[0].owner_space='CUSTOM'
    data=translate(capture_armature(rig))
    assert any(row['ownerBone']=='Weighted' for row in data['sources'])
    raw=next(row['constraint'] for row in data['sources'] if row['ownerBone']=='Raw' and row['constraint']['stackIndex']==0)
    assert raw['parameters']['owner_space']=='CUSTOM' and raw['targetObjectName']==''
    assert any(row['status']=='BROKEN' and row['ownerBone']=='Weighted' for row in data['diagnostics'])


def test_aim_has_no_location_requirement_and_selection_is_exact():
    rig=fixture();owner=rig.pose.bones.get('Aim');owner.constraints.pop(0)
    pair=inspect_aim_pair(rig,owner,names=['Aim','Up'])
    assert [index for index,_ in pair['selected']]==[0,1]
    assert inspect_aim_pair(rig,owner,names=['Aim']) is None
    declaration(owner)
    data=translate(capture_armature(rig))
    assert any(row['semanticType']=='AIM' for row in data['semantics'])


if __name__=='__main__':
    test_explicit_aim_preserves_independent_copy_and_weighted_sources()
    test_invalid_aim_pair_does_not_claim_or_modify_tracking()
    test_raw_source_is_retained_even_when_not_executable()
    test_aim_has_no_location_requirement_and_selection_is_exact()
    print('CONSTRAINT_AIM_UNIT_OK')
