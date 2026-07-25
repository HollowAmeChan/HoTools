"""Concrete Blender creation helpers shared by HoAux modules."""


def create_edit_bone(edit_bones, plan, actual_name):
    bone = edit_bones.new(actual_name)
    bone.head = plan.head
    bone.tail = plan.tail
    bone.parent = edit_bones.get(plan.parent_name)
    bone.use_connect = False
    bone.align_roll(plan.roll_reference)
    return bone


def write_bone_metadata(
    bone,
    *,
    rig_id,
    pipeline_id,
    module_id,
    module_type,
    generation_id,
    role_tag,
    part,
    function,
    marker,
    side,
    name_key,
    shared_key="",
):
    info = bone.hotools_boneprops.hoAux
    info.isHoAuxBone = True
    info.rigId = rig_id
    info.pipelineId = pipeline_id
    info.moduleId = module_id
    info.moduleType = module_type
    info.roleTag = role_tag
    info.part = part
    info.function = function
    info.marker = marker
    info.side = side
    info.generationId = generation_id
    info.sharedKey = shared_key
    info.nameKey = name_key
    bone.use_deform = role_tag == "DEF"


def add_copy_rotation(
    owner,
    target_object,
    target_bone,
    transaction,
    *,
    name="HoAux Copy Rotation",
    owner_space="LOCAL",
    target_space="LOCAL_OWNER_ORIENT",
    mix_mode="REPLACE",
    influence=1.0,
):
    constraint = owner.constraints.new("COPY_ROTATION")
    constraint.name = name
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = owner_space
    constraint.target_space = target_space
    constraint.mix_mode = mix_mode
    constraint.influence = influence
    transaction.track_constraint(owner.name, constraint)
    return constraint


def add_copy_location(
    owner,
    target_object,
    target_bone,
    transaction,
    *,
    name="HoAux Copy Location",
    owner_space="WORLD",
    target_space="WORLD",
    head_tail=1.0,
    influence=0.0,
):
    constraint = owner.constraints.new("COPY_LOCATION")
    constraint.name = name
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = owner_space
    constraint.target_space = target_space
    constraint.head_tail = head_tail
    constraint.influence = influence
    transaction.track_constraint(owner.name, constraint)
    return constraint


def add_stretch_to(
    owner,
    target_object,
    target_bone,
    transaction,
    *,
    name="HoAux Stretch To",
    owner_space="WORLD",
    target_space="WORLD",
    head_tail=0.0,
    rest_length=0.0,
    influence=1.0,
    volume="NO_VOLUME",
    keep_axis="SWING_Y",
    bulge=1.0,
    use_bulge_min=False,
    use_bulge_max=False,
    bulge_min=1.0,
    bulge_max=1.0,
    bulge_smooth=0.0,
):
    constraint = owner.constraints.new("STRETCH_TO")
    constraint.name = name
    constraint.target = target_object
    constraint.subtarget = target_bone
    constraint.owner_space = owner_space
    constraint.target_space = target_space
    constraint.head_tail = head_tail
    constraint.rest_length = rest_length
    constraint.influence = influence
    constraint.volume = volume
    constraint.keep_axis = keep_axis
    constraint.bulge = bulge
    constraint.use_bulge_min = use_bulge_min
    constraint.use_bulge_max = use_bulge_max
    constraint.bulge_min = bulge_min
    constraint.bulge_max = bulge_max
    constraint.bulge_smooth = bulge_smooth
    transaction.track_constraint(owner.name, constraint)
    return constraint


def response_expression(full_response_angle_degrees):
    scale = 180.0 / full_response_angle_degrees
    return f"abs(var*{scale:.9g}/pi)"


def add_transform_driver(
    driven_owner,
    driven_property,
    armature_object,
    source_bone,
    transform_type,
    expression,
    transaction,
    *,
    transform_space="LOCAL_SPACE",
    rotation_mode="AUTO",
):
    fcurve = driven_owner.driver_add(driven_property)
    driver = fcurve.driver
    driver.type = "SCRIPTED"
    driver.expression = expression
    variable = driver.variables.new()
    variable.name = "var"
    variable.type = "TRANSFORMS"
    target = variable.targets[0]
    target.id = armature_object
    target.bone_target = source_bone
    target.transform_type = transform_type
    target.transform_space = transform_space
    target.rotation_mode = rotation_mode
    transaction.track_driver(fcurve)
    return fcurve
