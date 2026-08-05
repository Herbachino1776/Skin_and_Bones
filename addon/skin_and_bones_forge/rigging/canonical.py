"""Bundled canonical-rig discovery, metadata, and orientation migration."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

from ..constants import (
    CANONICAL_ASSET_COLLECTION,
    CANONICAL_ASSET_DIRECTORY,
    CANONICAL_ASSET_FILENAME,
    CANONICAL_ASSET_OBJECT,
    CANONICAL_ASSET_PROPERTY,
    CANONICAL_BONE_MAPPING_PROPERTY,
    CANONICAL_CONTRACT_VERSION,
    CANONICAL_CONTRACT_VERSION_PROPERTY,
    CANONICAL_CURRENT_ORIENTATION,
    CANONICAL_FORWARD_AXIS,
    CANONICAL_FORWARD_PROPERTY,
    CANONICAL_LEGACY_ORIENTATION,
    CANONICAL_MANIFEST_FILENAME,
    CANONICAL_ORIENTATION_PROPERTY,
    CANONICAL_ORIENTATION_REVISION,
    CANONICAL_ORIENTATION_STATE_PROPERTY,
    CANONICAL_RIG_VERSION,
    CANONICAL_RIG_VERSION_PROPERTY,
    CANONICAL_ROOT_BONE,
    CANONICAL_ROOT_PROPERTY,
    CANONICAL_UNIT_PROPERTY,
    CANONICAL_UNIT_SCALE_METERS,
    CANONICAL_UP_AXIS,
    CANONICAL_UP_PROPERTY,
    RIG_OWNER_PROPERTY,
)
from .analysis import axis_vector
from .contract import analyze_canonical_rig


CANONICAL_TEMPLATE_ROLE = "TEMPLATE"
CANONICAL_CHARACTER_ROLE = "CHARACTER"
CANONICAL_ASSET_ROLE_PROPERTY = "sbf_canonical_asset_role"
ORIENTATION_MIGRATION_PROPERTY = "sbf_orientation_migration"
ORIENTATION_REPORT_PROPERTY = "sbf_orientation_report"
LEGACY_SCHEMA1_FINGERPRINTS = {
    # Known 57-bone Animate Anything rest fixture used before the Y+ contract.
    "c2ef3bc4a07fa64fb4e0da8e0b566ce0fe5d718eddfec54efb601464450c16ba",
}

CANONICAL_BONE_MAPPING = {
    "root": "root",
    "pelvis": "body",
    "spine_lower": "body_top0",
    "spine_middle": "body_top1",
    "chest": "body_top2",
    "neck": "neck",
    "head": "head",
    "shoulder_left": "shoulder_left",
    "upper_arm_left": "arm_left_top",
    "lower_arm_left": "arm_left_bot",
    "hand_left": "arm_left_hand",
    "shoulder_right": "shoulder_right",
    "upper_arm_right": "arm_right_top",
    "lower_arm_right": "arm_right_bot",
    "hand_right": "arm_right_hand",
    "upper_leg_left": "leg_left_top",
    "lower_leg_left": "leg_left_bot",
    "foot_left": "leg_left_foot",
    "upper_leg_right": "leg_right_top",
    "lower_leg_right": "leg_right_bot",
    "foot_right": "leg_right_foot",
}


def canonical_asset_path():
    return (
        Path(__file__).resolve().parents[1]
        / CANONICAL_ASSET_DIRECTORY
        / CANONICAL_ASSET_FILENAME
    )


def canonical_manifest_path():
    return (
        Path(__file__).resolve().parents[1]
        / CANONICAL_ASSET_DIRECTORY
        / CANONICAL_MANIFEST_FILENAME
    )


def load_canonical_manifest():
    path = canonical_manifest_path()
    if not path.is_file():
        raise RuntimeError(
            f"Bundled canonical rig manifest is missing: {path.name}. "
            "Reinstall Skin & Bones Forge from a complete release ZIP."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("rig_version") != CANONICAL_RIG_VERSION:
        raise RuntimeError("Bundled canonical rig manifest has the wrong version.")
    return payload


def _metadata(role):
    return {
        CANONICAL_RIG_VERSION_PROPERTY: CANONICAL_RIG_VERSION,
        CANONICAL_CONTRACT_VERSION_PROPERTY: CANONICAL_CONTRACT_VERSION,
        CANONICAL_FORWARD_PROPERTY: CANONICAL_FORWARD_AXIS,
        CANONICAL_UP_PROPERTY: CANONICAL_UP_AXIS,
        CANONICAL_ROOT_PROPERTY: CANONICAL_ROOT_BONE,
        CANONICAL_UNIT_PROPERTY: CANONICAL_UNIT_SCALE_METERS,
        CANONICAL_ORIENTATION_PROPERTY: CANONICAL_ORIENTATION_REVISION,
        CANONICAL_ORIENTATION_STATE_PROPERTY: CANONICAL_CURRENT_ORIENTATION,
        CANONICAL_BONE_MAPPING_PROPERTY: json.dumps(
            CANONICAL_BONE_MAPPING, sort_keys=True, separators=(",", ":")
        ),
        CANONICAL_ASSET_ROLE_PROPERTY: role,
    }


def apply_canonical_metadata(armature, target=None, role=CANONICAL_CHARACTER_ROLE):
    """Stamp the machine-readable handoff contract on generated data."""

    values = _metadata(role)
    for key, value in values.items():
        armature[key] = value
        armature.data[key] = value
        if target is not None:
            target[key] = value
            target.data[key] = value
    if role == CANONICAL_TEMPLATE_ROLE:
        armature[CANONICAL_ASSET_PROPERTY] = True
        armature.data[CANONICAL_ASSET_PROPERTY] = True
    else:
        armature[CANONICAL_ASSET_PROPERTY] = False
        armature.data[CANONICAL_ASSET_PROPERTY] = False
        if target is not None:
            target[CANONICAL_ASSET_PROPERTY] = False
            target.data[CANONICAL_ASSET_PROPERTY] = False
    return armature


def _collection(scene):
    collection = bpy.data.collections.get(CANONICAL_ASSET_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(CANONICAL_ASSET_COLLECTION)
        scene.collection.children.link(collection)
    elif collection.name not in {
        child.name for child in scene.collection.children
    }:
        scene.collection.children.link(collection)
    collection.hide_render = True
    collection.hide_select = True
    collection.hide_viewport = True
    return collection


def _template_candidates():
    return [
        obj
        for obj in bpy.data.objects
        if obj.type == "ARMATURE"
        and obj.get(CANONICAL_ASSET_PROPERTY, False)
        and obj.get(CANONICAL_ASSET_ROLE_PROPERTY) == CANONICAL_TEMPLATE_ROLE
    ]


def _remove_loaded_object(obj):
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.armatures.remove(data)


def verify_canonical_template(context, armature):
    manifest = load_canonical_manifest()
    contract = analyze_canonical_rig(context, armature)
    errors = []
    if contract["fingerprint"] != manifest.get("fingerprint"):
        errors.append("rest fingerprint differs from the packaged manifest")
    if [bone["name"] for bone in contract["bones"]] != manifest.get(
        "bone_names"
    ):
        errors.append("bone order/names differ from the packaged manifest")
    if armature.get(CANONICAL_RIG_VERSION_PROPERTY) != CANONICAL_RIG_VERSION:
        errors.append("rig version metadata is missing or stale")
    if armature.get(CANONICAL_FORWARD_PROPERTY) != CANONICAL_FORWARD_AXIS:
        errors.append("forward-axis metadata is not +Y")
    if armature.get(CANONICAL_UP_PROPERTY) != CANONICAL_UP_AXIS:
        errors.append("up-axis metadata is not +Z")
    if armature.parent is not None:
        errors.append("template armature unexpectedly has a parent")
    identity = Matrix.Identity(4)
    if any(
        abs(float(armature.matrix_world[row][column] - identity[row][column]))
        > 1.0e-6
        for row in range(4)
        for column in range(4)
    ):
        errors.append("template object transform is not identity")
    if errors:
        raise RuntimeError("Bundled canonical rig failed validation: " + "; ".join(errors))
    return contract


def ensure_canonical_rig(context, settings=None):
    """Return the one verified bundled template, appending it when absent."""

    candidates = _template_candidates()
    if len(candidates) > 1:
        raise RuntimeError(
            "Multiple tagged canonical templates are present; remove duplicates "
            "before continuing."
        )
    if candidates:
        armature = candidates[0]
        collection = _collection(context.scene)
        if armature.name not in collection.objects:
            collection.objects.link(armature)
        verify_canonical_template(context, armature)
        if settings is not None:
            settings.canonical_armature = armature
        return armature

    asset = canonical_asset_path()
    if not asset.is_file():
        raise RuntimeError(
            f"Bundled canonical rig asset is missing: {asset.name}. "
            "Reinstall Skin & Bones Forge from a complete release ZIP."
        )
    loaded = None
    try:
        with bpy.data.libraries.load(str(asset), link=False) as (
            data_from,
            data_to,
        ):
            if CANONICAL_ASSET_OBJECT not in data_from.objects:
                raise RuntimeError(
                    f"Bundled asset does not contain '{CANONICAL_ASSET_OBJECT}'."
                )
            data_to.objects = [CANONICAL_ASSET_OBJECT]
        loaded_objects = [obj for obj in data_to.objects if obj is not None]
        if len(loaded_objects) != 1 or loaded_objects[0].type != "ARMATURE":
            raise RuntimeError("Bundled asset did not load exactly one armature.")
        loaded = loaded_objects[0]
        loaded.name = CANONICAL_ASSET_OBJECT
        loaded.data.name = f"{CANONICAL_ASSET_OBJECT}_Data"
        apply_canonical_metadata(loaded, role=CANONICAL_TEMPLATE_ROLE)
        loaded.data.pose_position = "REST"
        loaded.hide_render = True
        loaded.hide_viewport = True
        loaded.show_in_front = True
        _collection(context.scene).objects.link(loaded)
        verify_canonical_template(context, loaded)
    except Exception:
        if loaded is not None and loaded.name in bpy.data.objects:
            _remove_loaded_object(loaded)
        raise
    if settings is not None:
        settings.canonical_armature = loaded
    return loaded


def _legacy_schema1_fingerprint(contract):
    payload = {
        "schema": 1,
        "bones": [
            {
                "name": bone["name"],
                "parent": bone["parent"],
                "deform": bone["deform"],
                "connected": bone["connected"],
                "head": bone["head"],
                "tail": bone["tail"],
                "roll": bone["roll"],
                "matrix_local": bone["matrix_local"],
            }
            for bone in contract["bones"]
        ],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def rig_orientation_state(context, armature):
    state = armature.get(CANONICAL_ORIENTATION_STATE_PROPERTY)
    axis = armature.get(CANONICAL_FORWARD_PROPERTY)
    if state == CANONICAL_CURRENT_ORIENTATION and axis == "-Y":
        raise RuntimeError("Rig orientation metadata is internally inconsistent.")
    if state == CANONICAL_LEGACY_ORIENTATION and axis == CANONICAL_FORWARD_AXIS:
        raise RuntimeError("Rig orientation metadata is internally inconsistent.")
    if state == CANONICAL_CURRENT_ORIENTATION or axis == CANONICAL_FORWARD_AXIS:
        return CANONICAL_CURRENT_ORIENTATION
    if state == CANONICAL_LEGACY_ORIENTATION or axis == "-Y":
        return CANONICAL_LEGACY_ORIENTATION
    contract = analyze_canonical_rig(context, armature)
    if (
        len(contract["bones"]) == 57
        and _legacy_schema1_fingerprint(contract) in LEGACY_SCHEMA1_FINGERPRINTS
    ):
        return CANONICAL_LEGACY_ORIENTATION
    return "UNKNOWN"


def _basis(forward_axis, up_axis):
    forward = axis_vector(forward_axis).normalized()
    up = axis_vector(up_axis).normalized()
    if abs(forward.dot(up)) > 1.0e-6:
        raise ValueError("Forward and up axes must be perpendicular.")
    lateral = up.cross(forward).normalized()
    return Matrix((lateral, forward, up)).transposed()


def _axis_rotation(forward_axis, up_axis):
    source = _basis(forward_axis, up_axis)
    target = _basis(CANONICAL_FORWARD_AXIS, CANONICAL_UP_AXIS)
    rotation = target @ source.inverted()
    if rotation.determinant() < 0.999999:
        raise RuntimeError("Axis conversion would introduce a reflected basis.")
    return rotation.to_4x4()


def _mesh_data_transform(obj, world_matrix):
    local = obj.matrix_world.inverted_safe() @ world_matrix @ obj.matrix_world
    obj.data.transform(local, shape_keys=True)
    obj.data.update()


def _matrix_is_identity(matrix, tolerance=1.0e-7):
    identity = Matrix.Identity(4)
    return all(
        abs(float(matrix[row][column] - identity[row][column])) <= tolerance
        for row in range(4)
        for column in range(4)
    )


def _apply_unrigged_object_transform(target):
    if target.constraints:
        raise RuntimeError(
            "Canonical orientation requires an unrigged target without object constraints."
        )
    needs_apply = target.parent is not None or not _matrix_is_identity(
        target.matrix_world
    )
    if not needs_apply:
        return False
    if target.data.users != 1:
        raise RuntimeError(
            "Canonical orientation cannot apply a shared mesh datablock; make the "
            "production target single-user first."
        )
    world = target.matrix_world.copy()
    target.data.transform(world, shape_keys=True)
    target.parent = None
    target.matrix_parent_inverse = Matrix.Identity(4)
    target.location = (0.0, 0.0, 0.0)
    if target.rotation_mode == "QUATERNION":
        target.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    elif target.rotation_mode == "AXIS_ANGLE":
        target.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
    else:
        target.rotation_euler = (0.0, 0.0, 0.0)
    target.scale = (1.0, 1.0, 1.0)
    target.delta_location = (0.0, 0.0, 0.0)
    target.delta_rotation_euler = (0.0, 0.0, 0.0)
    target.delta_scale = (1.0, 1.0, 1.0)
    target.matrix_basis = Matrix.Identity(4)
    target.matrix_world = Matrix.Identity(4)
    target.data.update()
    return True


def ensure_unrigged_target_yplus(context, target, forward_axis, up_axis):
    """Normalize a new unrigged mesh to Y+/Z+ exactly once."""

    state = target.get(CANONICAL_ORIENTATION_STATE_PROPERTY)
    if state == CANONICAL_CURRENT_ORIENTATION:
        if (
            target.get(CANONICAL_FORWARD_PROPERTY) != CANONICAL_FORWARD_AXIS
            or target.get(CANONICAL_UP_PROPERTY) != CANONICAL_UP_AXIS
        ):
            raise RuntimeError("Target orientation metadata is internally inconsistent.")
        if not _matrix_is_identity(target.matrix_world):
            raise RuntimeError(
                "Canonical target metadata is present but its object transform "
                "is not identity: "
                + json.dumps([list(row) for row in target.matrix_world])
            )
        return {"status": "ALREADY_CANONICAL", "rotated": False}
    bound_armatures = {
        modifier.object
        for modifier in target.modifiers
        if modifier.type == "ARMATURE" and modifier.object is not None
    }
    if target.parent is not None and target.parent.type == "ARMATURE":
        bound_armatures.add(target.parent)
    if bound_armatures:
        raise RuntimeError(
            "This character is already rigged and has no Y+ orientation metadata. "
            "Use Convert Legacy Y- Character after reviewing its validation warning."
        )
    # Object transform properties can be newer than matrix_world until Blender's
    # dependency graph has evaluated the linked target.
    context.view_layer.update()
    transform_applied = _apply_unrigged_object_transform(target)
    context.view_layer.update()
    if not _matrix_is_identity(target.matrix_world):
        raise RuntimeError(
            "Failed to apply the unrigged target object transform before "
            "canonical axis conversion: "
            + json.dumps(
                {
                    "matrix_world": [list(row) for row in target.matrix_world],
                    "matrix_basis": [list(row) for row in target.matrix_basis],
                    "location": list(target.location),
                    "delta_location": list(target.delta_location),
                    "parent": target.parent.name if target.parent else None,
                }
            )
        )
    rotation = _axis_rotation(forward_axis, up_axis)
    rotated = any(
        abs(float(rotation[row][column] - Matrix.Identity(4)[row][column]))
        > 1.0e-7
        for row in range(4)
        for column in range(4)
    )
    if rotated:
        _mesh_data_transform(target, rotation)
    for key, value in _metadata(CANONICAL_CHARACTER_ROLE).items():
        target[key] = value
        target.data[key] = value
    target[ORIENTATION_MIGRATION_PROPERTY] = (
        f"UNRIGGED_{forward_axis}_{up_axis}_TO_YPLUS_ZPLUS"
        if rotated
        else "DECLARED_YPLUS_ZPLUS"
    )
    context.view_layer.update()
    return {
        "status": "NORMALIZED_TO_CANONICAL" if rotated else "TAGGED_CANONICAL",
        "rotated": rotated,
        "object_transform_applied": transform_applied,
        "source_forward_axis": forward_axis,
        "source_up_axis": up_axis,
        "forward_axis": CANONICAL_FORWARD_AXIS,
        "up_axis": CANONICAL_UP_AXIS,
    }


def _bound_meshes(armature, target=None):
    meshes = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and (
            obj.parent == armature
            or any(
                modifier.type == "ARMATURE" and modifier.object == armature
                for modifier in obj.modifiers
            )
        )
    ]
    if target is not None and target not in meshes:
        raise RuntimeError("Target mesh is not bound to the selected legacy armature.")
    return meshes


def convert_legacy_character_yminus(context, armature, target=None):
    """Rotate a static legacy rig and all bound meshes to Y+ exactly once."""

    state = rig_orientation_state(context, armature)
    if state == CANONICAL_CURRENT_ORIENTATION:
        return {"status": "ALREADY_CANONICAL", "rotated": False}
    if state != CANONICAL_LEGACY_ORIENTATION:
        raise RuntimeError(
            "Legacy conversion refused: the rig has no explicit -Y metadata and "
            "does not match the known 57-bone legacy fingerprint."
        )
    animation = armature.animation_data
    if animation is not None and (
        animation.action is not None or any(track.strips for track in animation.nla_tracks)
    ):
        raise RuntimeError(
            "Legacy conversion refused because the rig has Actions or NLA strips. "
            "Retarget those animations in Animation Forge; Skin & Bones will not "
            "rewrite animation-library data during an orientation migration."
        )
    meshes = _bound_meshes(armature, target)
    if not meshes:
        raise RuntimeError("Legacy conversion found no meshes bound to the armature.")
    non_identity = [
        obj.name
        for obj in [armature, *meshes]
        if not _matrix_is_identity(obj.matrix_world)
    ]
    if non_identity:
        raise RuntimeError(
            "Legacy conversion requires identity armature/mesh object transforms: "
            + ", ".join(non_identity)
        )
    rotation = Matrix.Rotation(math.pi, 4, "Z")
    armature_local = (
        armature.matrix_world.inverted_safe() @ rotation @ armature.matrix_world
    )
    armature.data.transform(armature_local)
    for mesh in meshes:
        _mesh_data_transform(mesh, rotation)
    apply_canonical_metadata(armature, target=None)
    armature[ORIENTATION_MIGRATION_PROPERTY] = "LEGACY_Y_MINUS_TO_CANONICAL_Y_PLUS_V1"
    for mesh in meshes:
        for key, value in _metadata(CANONICAL_CHARACTER_ROLE).items():
            mesh[key] = value
            mesh.data[key] = value
        mesh[ORIENTATION_MIGRATION_PROPERTY] = (
            "LEGACY_Y_MINUS_TO_CANONICAL_Y_PLUS_V1"
        )
    report = {
        "status": "LEGACY_CONVERSION_PASSED",
        "rotated": True,
        "migration": "LEGACY_Y_MINUS_TO_CANONICAL_Y_PLUS_V1",
        "armature": armature.name,
        "meshes": [mesh.name for mesh in meshes],
        "forward_axis": CANONICAL_FORWARD_AXIS,
        "up_axis": CANONICAL_UP_AXIS,
        "object_transforms_applied": False,
        "negative_scales": [
            obj.name
            for obj in [armature, *meshes]
            if any(float(value) < 0.0 for value in obj.scale)
        ],
    }
    if report["negative_scales"]:
        raise RuntimeError("Legacy conversion found a negative object scale.")
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    armature[ORIENTATION_REPORT_PROPERTY] = encoded
    for mesh in meshes:
        mesh[ORIENTATION_REPORT_PROPERTY] = encoded
    context.view_layer.update()
    return report
