"""Print detailed armature and rig metadata for the currently open Blender file.

This diagnostic intentionally makes no data changes.  Run it with Blender's
``--background --python`` arguments when selecting a canonical rig source.
"""

from __future__ import annotations

import json

import bpy


def _json_value(value):
    if isinstance(value, (bool, float, int, str)) or value is None:
        return value
    try:
        return list(value)
    except TypeError:
        return str(value)


def _properties(data):
    return {key: _json_value(value) for key, value in data.items()}


def _transform(obj):
    return {
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "matrix_world": [list(row) for row in obj.matrix_world],
    }


def _armature(obj):
    pose_constraints = {}
    pose_properties = {}
    for pose_bone in obj.pose.bones:
        if pose_bone.constraints:
            pose_constraints[pose_bone.name] = [
                {
                    "name": constraint.name,
                    "type": constraint.type,
                    "mute": bool(constraint.mute),
                    "influence": float(constraint.influence),
                }
                for constraint in pose_bone.constraints
            ]
        custom = _properties(pose_bone)
        if custom:
            pose_properties[pose_bone.name] = custom
    return {
        "name": obj.name,
        "data": obj.data.name,
        "parent": obj.parent.name if obj.parent else None,
        "transform": _transform(obj),
        "object_properties": _properties(obj),
        "data_properties": _properties(obj.data),
        "pose_position": obj.data.pose_position,
        "bone_count": len(obj.data.bones),
        "deform_bone_count": sum(bone.use_deform for bone in obj.data.bones),
        "object_constraints": [
            {"name": constraint.name, "type": constraint.type}
            for constraint in obj.constraints
        ],
        "pose_constraints": pose_constraints,
        "pose_properties": pose_properties,
        "active_action": (
            obj.animation_data.action.name
            if obj.animation_data and obj.animation_data.action
            else None
        ),
        "nla_tracks": (
            [track.name for track in obj.animation_data.nla_tracks]
            if obj.animation_data
            else []
        ),
    }


def _mesh(obj):
    return {
        "name": obj.name,
        "data": obj.data.name,
        "parent": obj.parent.name if obj.parent else None,
        "transform": _transform(obj),
        "object_properties": _properties(obj),
        "data_properties": _properties(obj.data),
        "armature_modifiers": [
            {
                "name": modifier.name,
                "object": modifier.object.name if modifier.object else None,
                "use_vertex_groups": bool(modifier.use_vertex_groups),
                "use_bone_envelopes": bool(modifier.use_bone_envelopes),
            }
            for modifier in obj.modifiers
            if modifier.type == "ARMATURE"
        ],
    }


payload = {
    "blender": bpy.app.version_string,
    "filepath": bpy.data.filepath,
    "armatures": [
        _armature(obj) for obj in bpy.data.objects if obj.type == "ARMATURE"
    ],
    "meshes": [_mesh(obj) for obj in bpy.data.objects if obj.type == "MESH"],
}
print("SBF_CANONICAL_DETAIL_BEGIN")
print(json.dumps(payload, indent=2, sort_keys=True))
print("SBF_CANONICAL_DETAIL_END")
