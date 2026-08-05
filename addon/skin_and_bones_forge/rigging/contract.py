"""Canonical humanoid rest-skeleton contract extraction."""

from __future__ import annotations

from contextlib import AbstractContextManager
import hashlib
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

from ..constants import (
    CANONICAL_BONE_MAPPING_PROPERTY,
    CANONICAL_CONTRACT_VERSION_PROPERTY,
    CANONICAL_FORWARD_PROPERTY,
    CANONICAL_ORIENTATION_PROPERTY,
    CANONICAL_RIG_VERSION_PROPERTY,
    CANONICAL_ROOT_PROPERTY,
    CANONICAL_UNIT_PROPERTY,
    CANONICAL_UP_PROPERTY,
)


CONTRACT_SCHEMA = 2
QUANTIZE_DIGITS = 6


def _number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Canonical rig contains a non-finite numeric value.")
    rounded = round(value, QUANTIZE_DIGITS)
    return 0.0 if rounded == -0.0 else rounded


def _vector(value):
    return [_number(component) for component in value]


def _matrix(value):
    return [_vector(row) for row in value]


def _json_value(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "to_list"):
        return _json_value(value.to_list())
    return str(value)


def _custom_properties(item):
    return {
        key: _json_value(item[key])
        for key in sorted(item.keys())
        if key != "_RNA_UI"
    }


def _bone_roll(bone):
    try:
        _axis, roll = bone.AxisRollFromMatrix(bone.matrix_local.to_3x3())
        return _number(roll)
    except (AttributeError, TypeError, ValueError):
        # The rest matrix remains authoritative if a Blender build does not
        # expose AxisRollFromMatrix through the Bone RNA type.
        return _number(bone.matrix_local.to_3x3().to_euler("XYZ").y)


class RestEvaluationState(AbstractContextManager):
    """Temporarily make an armature evaluate in rest state, then restore it."""

    def __init__(self, context, armature):
        self.context = context
        self.armature = armature
        self.scene = context.scene
        self.frame = self.scene.frame_current
        self.pose_position = armature.data.pose_position
        self.action = None
        self.nla_mutes = []
        self.constraint_mutes = []

    def __enter__(self):
        animation = self.armature.animation_data
        if animation is not None:
            self.action = animation.action
            animation.action = None
            self.nla_mutes = [
                (track, bool(track.mute)) for track in animation.nla_tracks
            ]
            for track, _mute in self.nla_mutes:
                track.mute = True
        for pose_bone in self.armature.pose.bones:
            for constraint in pose_bone.constraints:
                self.constraint_mutes.append((constraint, bool(constraint.mute)))
                constraint.mute = True
        self.armature.data.pose_position = "REST"
        self.scene.frame_set(self.frame)
        self.context.view_layer.update()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.armature.data.pose_position = self.pose_position
        animation = self.armature.animation_data
        if animation is not None:
            animation.action = self.action
        for track, mute in self.nla_mutes:
            if track.id_data is not None:
                track.mute = mute
        for constraint, mute in self.constraint_mutes:
            try:
                constraint.mute = mute
            except ReferenceError:
                pass
        self.scene.frame_set(self.frame)
        self.context.view_layer.update()
        return False


def fingerprint_payload(contract):
    """Return only stable canonical rest data used by the SHA-256 contract."""

    return {
        "schema": CONTRACT_SCHEMA,
        "rig_version": contract.get("rig_version", ""),
        "contract_version": contract.get("contract_version", 0),
        "forward_axis": contract.get("forward_axis", ""),
        "up_axis": contract.get("up_axis", ""),
        "root_bone": contract.get("root_bone", ""),
        "unit_scale_meters": contract.get("unit_scale_meters", 0.0),
        "orientation_revision": contract.get("orientation_revision", 0),
        "bone_mapping": contract.get("bone_mapping", ""),
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


def canonical_fingerprint(contract):
    encoded = json.dumps(
        fingerprint_payload(contract),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _object_hierarchy(armature):
    hierarchy = []
    current = armature
    while current is not None:
        hierarchy.append(
            {
                "object": current.name,
                "data": current.data.name if current.data else None,
                "type": current.type,
                "parent": current.parent.name if current.parent else None,
                "parent_type": current.parent_type,
                "matrix_local": _matrix(current.matrix_local),
                "matrix_world": _matrix(current.matrix_world),
                "location": _vector(current.location),
                "rotation_mode": current.rotation_mode,
                "rotation_euler": _vector(current.rotation_euler),
                "scale": _vector(current.scale),
                "custom_properties": _custom_properties(current),
            }
        )
        current = current.parent
    return hierarchy


def _evaluated_world_bounds(context, obj):
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        points = [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()
    if not points:
        return None
    minimum = Vector(min(point[index] for point in points) for index in range(3))
    maximum = Vector(max(point[index] for point in points) for index in range(3))
    return {
        "minimum": _vector(minimum),
        "maximum": _vector(maximum),
        "height_z": _number(maximum.z - minimum.z),
    }


def _reference_meshes(context, armature):
    references = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        modifiers = [
            modifier
            for modifier in obj.modifiers
            if modifier.type == "ARMATURE" and modifier.object == armature
        ]
        if obj.parent != armature and not modifiers:
            continue
        references.append(
            {
                "object": obj.name,
                "data": obj.data.name,
                "parent": obj.parent.name if obj.parent else None,
                "parent_type": obj.parent_type,
                "matrix_world": _matrix(obj.matrix_world),
                "evaluated_world_bounds_rest": _evaluated_world_bounds(
                    context, obj
                ),
                "vertex_groups": [group.name for group in obj.vertex_groups],
                "armature_modifiers": [
                    {
                        "name": modifier.name,
                        "object": modifier.object.name if modifier.object else None,
                        "use_vertex_groups": modifier.use_vertex_groups,
                        "use_bone_envelopes": modifier.use_bone_envelopes,
                    }
                    for modifier in modifiers
                ],
            }
        )
    return references


def _action_inventory(armature):
    animation = armature.animation_data
    active = animation.action.name if animation and animation.action else None
    referenced = {}
    if animation is not None:
        if animation.action is not None:
            referenced[animation.action.name] = animation.action
        for track in animation.nla_tracks:
            for strip in track.strips:
                if strip.action is not None:
                    referenced[strip.action.name] = strip.action
    actions = [
        {
            "name": action.name,
            "frame_range": _vector(action.frame_range),
            "users": int(action.users),
            "slots": [slot.name_display for slot in action.slots],
        }
        for action in sorted(referenced.values(), key=lambda item: item.name)
    ]
    nla = []
    if animation is not None:
        for track in animation.nla_tracks:
            nla.append(
                {
                    "name": track.name,
                    "mute": bool(track.mute),
                    "solo": bool(track.is_solo),
                    "strips": [
                        {
                            "name": strip.name,
                            "action": strip.action.name if strip.action else None,
                            "frame_start": _number(strip.frame_start),
                            "frame_end": _number(strip.frame_end),
                        }
                        for strip in track.strips
                    ],
                }
            )
    return {"active_action": active, "actions": actions, "nla_tracks": nla}


def analyze_canonical_rig(context, armature):
    if armature is None or armature.type != "ARMATURE":
        raise ValueError("Choose a canonical armature object.")
    if armature.library is not None or armature.data.library is not None:
        raise ValueError("Make the canonical armature local before analysis.")

    with RestEvaluationState(context, armature):
        bones = []
        for bone in armature.data.bones:
            matrix = bone.matrix_local
            bones.append(
                {
                    "name": bone.name,
                    "parent": bone.parent.name if bone.parent else None,
                    "deform": bool(bone.use_deform),
                    "connected": bool(bone.use_connect),
                    "head": _vector(bone.head_local),
                    "tail": _vector(bone.tail_local),
                    "length": _number(bone.length),
                    "roll": _bone_roll(bone),
                    "matrix_local": _matrix(matrix),
                    "local_axes": {
                        "x": _vector(matrix.to_3x3().col[0]),
                        "y": _vector(matrix.to_3x3().col[1]),
                        "z": _vector(matrix.to_3x3().col[2]),
                    },
                    "inherit_scale": bone.inherit_scale,
                    "use_local_location": bool(bone.use_local_location),
                    "use_relative_parent": bool(bone.use_relative_parent),
                    "custom_properties": _custom_properties(bone),
                }
            )
        contract = {
            "schema": CONTRACT_SCHEMA,
            "rig_version": armature.get(CANONICAL_RIG_VERSION_PROPERTY, ""),
            "contract_version": armature.get(
                CANONICAL_CONTRACT_VERSION_PROPERTY, 0
            ),
            "forward_axis": armature.get(CANONICAL_FORWARD_PROPERTY, ""),
            "up_axis": armature.get(CANONICAL_UP_PROPERTY, ""),
            "root_bone": armature.get(CANONICAL_ROOT_PROPERTY, ""),
            "unit_scale_meters": armature.get(CANONICAL_UNIT_PROPERTY, 0.0),
            "orientation_revision": armature.get(
                CANONICAL_ORIENTATION_PROPERTY, 0
            ),
            "bone_mapping": armature.get(CANONICAL_BONE_MAPPING_PROPERTY, ""),
            "armature_object": armature.name,
            "armature_data": armature.data.name,
            "armature_object_transform": {
                "matrix_local": _matrix(armature.matrix_local),
                "matrix_world": _matrix(armature.matrix_world),
                "location": _vector(armature.location),
                "rotation_euler": _vector(armature.rotation_euler),
                "scale": _vector(armature.scale),
            },
            "object_hierarchy": _object_hierarchy(armature),
            "bones": bones,
            "armature_custom_properties": _custom_properties(armature.data),
            "reference_meshes": _reference_meshes(context, armature),
            "animation_inventory": _action_inventory(armature),
        }
    contract["fingerprint"] = canonical_fingerprint(contract)
    return contract


def write_contract_report(contract, filepath):
    path = Path(bpy.path.abspath(filepath)).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
