"""Owned landmark handles and non-destructive fitted armature previews."""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

from ..constants import (
    RIG_CONTRACT_PROPERTY,
    RIG_LANDMARK_PREFIX,
    RIG_OWNER_PROPERTY,
    RIG_PREVIEW_ARMATURE,
    RIG_PREVIEW_COLLECTION,
    RIG_TARGET_PROPERTY,
)
from .hands import apply_hand_pose
from .landmarks import EDITABLE_LANDMARKS


OWNER = "AUTOMATIC_HUMANOID_RIG_PREVIEW"


def _collection(scene):
    collection = bpy.data.collections.get(RIG_PREVIEW_COLLECTION)
    if collection is not None and collection.get(RIG_OWNER_PROPERTY) != OWNER:
        raise RuntimeError(
            f"Collection '{RIG_PREVIEW_COLLECTION}' exists but is not owned "
            "by Skin & Bones Forge."
        )
    if collection is None:
        collection = bpy.data.collections.new(RIG_PREVIEW_COLLECTION)
        scene.collection.children.link(collection)
    elif collection.name not in {
        child.name for child in scene.collection.children
    }:
        scene.collection.children.link(collection)
    collection[RIG_OWNER_PROPERTY] = OWNER
    return collection


def _remove_object(obj):
    object_type = obj.type
    data = obj.data if obj.type in {"ARMATURE", "MESH"} else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        if object_type == "ARMATURE":
            bpy.data.armatures.remove(data)
        elif object_type == "MESH":
            bpy.data.meshes.remove(data)


def clean_rig_preview(scene):
    collection = bpy.data.collections.get(RIG_PREVIEW_COLLECTION)
    if collection is None:
        return 0
    if collection.get(RIG_OWNER_PROPERTY) != OWNER:
        raise RuntimeError(
            f"Refusing to clean unowned collection '{RIG_PREVIEW_COLLECTION}'."
        )
    unowned = [
        obj.name
        for obj in collection.objects
        if obj.get(RIG_OWNER_PROPERTY) != OWNER
    ]
    if unowned:
        raise RuntimeError(
            "Refusing to clean a rig-preview collection containing unowned "
            "objects: " + ", ".join(unowned)
        )
    owned = [
        obj
        for obj in list(collection.objects)
        if obj.get(RIG_OWNER_PROPERTY) == OWNER
    ]
    for obj in owned:
        _remove_object(obj)
    bpy.data.collections.remove(collection)
    return len(owned)


def landmark_objects(target=None):
    result = {}
    for obj in bpy.data.objects:
        if (
            obj.type == "EMPTY"
            and obj.get(RIG_OWNER_PROPERTY) == OWNER
            and obj.name.startswith(RIG_LANDMARK_PREFIX)
            and (target is None or obj.get(RIG_TARGET_PROPERTY) == target.data.name)
        ):
            name = obj.get("sbf_landmark_name", "")
            if name:
                result[name] = obj
    return result


def _remove_preview_armatures(collection):
    for obj in list(collection.objects):
        if obj.type == "ARMATURE" and obj.get(RIG_OWNER_PROPERTY) == OWNER:
            _remove_object(obj)


def create_landmark_preview(scene, target, landmarks, replace=True):
    if replace:
        clean_rig_preview(scene)
    collection = _collection(scene)
    size = max(0.008, float(target.dimensions.length) * 0.012)
    created = []
    try:
        for name in EDITABLE_LANDMARKS:
            if name not in landmarks:
                continue
            handle = bpy.data.objects.new(f"{RIG_LANDMARK_PREFIX}{name}", None)
            handle.empty_display_type = "SPHERE"
            handle.empty_display_size = size
            handle.show_in_front = True
            handle.color = (0.15, 0.8, 1.0, 1.0)
            handle.location = Vector(landmarks[name]["world"])
            handle[RIG_OWNER_PROPERTY] = OWNER
            handle[RIG_TARGET_PROPERTY] = target.data.name
            handle["sbf_landmark_name"] = name
            handle["sbf_landmark_confidence"] = landmarks[name]["confidence"]
            collection.objects.link(handle)
            created.append(handle)
    except Exception:
        for handle in created:
            _remove_object(handle)
        raise
    return landmark_objects(target)


def _point(landmarks, name):
    return Vector(landmarks[name]["world"])


def bone_endpoint_map(landmarks):
    chest = _point(landmarks, "chest")
    mapping = {
        "root": (
            (_point(landmarks, "heel_left") + _point(landmarks, "heel_right")) * 0.5,
            _point(landmarks, "pelvis"),
        ),
        "body": (
            _point(landmarks, "pelvis"),
            _point(landmarks, "lower_spine"),
        ),
        "body_top0": (
            _point(landmarks, "lower_spine"),
            _point(landmarks, "middle_spine"),
        ),
        "body_top1": (
            _point(landmarks, "middle_spine"),
            _point(landmarks, "upper_spine"),
        ),
        "body_top2": (
            _point(landmarks, "upper_spine"),
            _point(landmarks, "neck"),
        ),
        "neck": (
            _point(landmarks, "neck"),
            _point(landmarks, "head_center"),
        ),
        "head": (
            _point(landmarks, "head_center"),
            _point(landmarks, "head_top"),
        ),
    }
    for side in ("left", "right"):
        shoulder = _point(landmarks, f"shoulder_{side}")
        mapping[f"shoulder_{side}"] = (
            chest.lerp(shoulder, 0.45),
            shoulder,
        )
        mapping[f"arm_{side}_top"] = (
            shoulder,
            _point(landmarks, f"elbow_{side}"),
        )
        mapping[f"arm_{side}_bot"] = (
            _point(landmarks, f"elbow_{side}"),
            _point(landmarks, f"wrist_{side}"),
        )
        mapping[f"arm_{side}_hand"] = (
            _point(landmarks, f"wrist_{side}"),
            _point(landmarks, f"hand_{side}"),
        )
        mapping[f"leg_{side}_top"] = (
            _point(landmarks, f"hip_{side}"),
            _point(landmarks, f"knee_{side}"),
        )
        mapping[f"leg_{side}_bot"] = (
            _point(landmarks, f"knee_{side}"),
            _point(landmarks, f"ankle_{side}"),
        )
        mapping[f"leg_{side}_foot"] = (
            _point(landmarks, f"ankle_{side}"),
            _point(landmarks, f"toe_{side}"),
        )
    return mapping


def _safe_tail(head, tail):
    if (tail - head).length > 1e-6:
        return tail
    return head + Vector((0.0, 0.0, 0.001))


def fit_skeleton_preview(
    context,
    source,
    target,
    contract,
    landmarks,
):
    if source is None or source.type != "ARMATURE":
        raise ValueError("Choose a canonical armature before fitting.")
    collection = _collection(context.scene)
    _remove_preview_armatures(collection)

    armature_data = source.data.copy()
    armature_data.name = f"{RIG_PREVIEW_ARMATURE}_Data"
    fitted = source.copy()
    fitted.data = armature_data
    fitted.name = RIG_PREVIEW_ARMATURE
    fitted.animation_data_clear()
    fitted.parent = None
    fitted.matrix_world = Matrix.Identity(4)
    fitted.show_in_front = True
    fitted.display_type = "WIRE"
    fitted.data.pose_position = "REST"
    fitted[RIG_OWNER_PROPERTY] = OWNER
    fitted[RIG_TARGET_PROPERTY] = target.data.name
    fitted[RIG_CONTRACT_PROPERTY] = contract["fingerprint"]
    fitted.data[RIG_OWNER_PROPERTY] = OWNER
    fitted.data[RIG_CONTRACT_PROPERTY] = contract["fingerprint"]
    collection.objects.link(fitted)

    for constraint in list(fitted.constraints):
        fitted.constraints.remove(constraint)
    for pose_bone in fitted.pose.bones:
        for constraint in list(pose_bone.constraints):
            pose_bone.constraints.remove(constraint)
        pose_bone.matrix_basis.identity()

    canonical = {
        bone.name: {
            "head": bone.head_local.copy(),
            "tail": bone.tail_local.copy(),
            "x": bone.matrix_local.to_3x3().col[0].copy(),
            "z": bone.matrix_local.to_3x3().col[2].copy(),
        }
        for bone in source.data.bones
    }
    mapping = bone_endpoint_map(landmarks)
    previous_active = context.view_layer.objects.active
    previous_selected = list(context.selected_objects)
    for obj in previous_selected:
        obj.select_set(False)
    fitted.select_set(True)
    context.view_layer.objects.active = fitted
    failure = None
    try:
        bpy.ops.object.mode_set(mode="EDIT")
        for name in contract.get("removed_bones", []):
            edit_bone = fitted.data.edit_bones.get(name)
            if edit_bone is not None:
                fitted.data.edit_bones.remove(edit_bone)
        for name, edit_bone in list(fitted.data.edit_bones.items()):
            roll_reference = canonical[name]["z"]
            if name in mapping:
                head, tail = mapping[name]
                old_direction = canonical[name]["tail"] - canonical[name]["head"]
                new_direction = tail - head
                rotation = old_direction.rotation_difference(new_direction)
                roll_reference = rotation @ roll_reference
            else:
                head = canonical[name]["head"]
                tail = canonical[name]["tail"]
            edit_bone.head = head
            edit_bone.tail = _safe_tail(head, tail)
            try:
                edit_bone.align_roll(roll_reference)
            except ValueError:
                pass
    except Exception as exc:
        failure = exc
    finally:
        if fitted.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        fitted.select_set(False)
        for obj in previous_selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if previous_active and previous_active.name in context.view_layer.objects:
            context.view_layer.objects.active = previous_active
    if failure is not None:
        _remove_object(fitted)
        raise failure

    fitted["sbf_production_profile"] = contract.get("profile_id", "")
    fitted["sbf_source_canonical_fingerprint"] = contract.get(
        "source_fingerprint", ""
    )
    fitted["sbf_removed_finger_bones"] = len(
        contract.get("removed_bones", [])
    )
    apply_hand_pose(fitted, "RELAXED")
    context.view_layer.update()
    return fitted
