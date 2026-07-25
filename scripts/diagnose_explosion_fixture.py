"""Focused deformation diagnostics for an already-open failing production blend."""

from __future__ import annotations

from collections import defaultdict
import json
import math

import bpy
from mathutils import Quaternion, Vector


TARGET = "geometry_0"
ARMATURE = "SBF_ProductionRig"
WALK = "DSB_DRAFT_Walk"
ISOLATED_BONES = (
    "body",
    "body_top0",
    "body_top1",
    "body_top2",
    "arm_left_top",
    "arm_right_top",
    "arm_left_bot",
    "arm_right_bot",
    "leg_left_top",
    "leg_right_top",
    "leg_left_bot",
    "leg_right_bot",
)


def evaluated_points(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def components(mesh):
    parent = list(range(len(mesh.vertices)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for edge in mesh.edges:
        first, second = map(int, edge.vertices)
        first_root, second_root = root(first), root(second)
        if first_root != second_root:
            parent[second_root] = first_root
    grouped = defaultdict(list)
    for index in range(len(parent)):
        grouped[root(index)].append(index)
    return sorted(grouped.values(), key=lambda values: (-len(values), values[0]))


def weights(obj, index):
    vertex = obj.data.vertices[index]
    return sorted(
        (
            (obj.vertex_groups[item.group].name, round(float(item.weight), 6))
            for item in vertex.groups
        ),
        key=lambda item: (-item[1], item[0]),
    )


def matrix_values(matrix):
    return [[round(float(value), 8) for value in row] for row in matrix]


def point_region(point, center, ground, height):
    fraction = (point.z - ground) / height
    lateral_fraction = abs(point.x - center.x) / height
    if fraction >= 0.82:
        return "HEAD"
    if 0.42 <= fraction <= 0.64 and lateral_fraction >= 0.18:
        return "HAND"
    if fraction <= 0.12:
        return "FOOT"
    if fraction >= 0.70 and lateral_fraction >= 0.12:
        return "ARM"
    if fraction <= 0.52 and lateral_fraction >= 0.06:
        return "LEG"
    return "TORSO"


def bone_allowed(name, region, side):
    bone_side = "left" if "_left" in name else "right" if "_right" in name else "center"
    if side != "center" and bone_side not in {"center", side}:
        return False
    if region == "HEAD":
        return name in {"body_top1", "body_top2", "neck", "head"}
    if region == "HAND":
        return name == f"arm_{side}_hand"
    if region == "FOOT":
        return name.startswith(f"leg_{side}_")
    if region == "ARM":
        return name.startswith(("shoulder_", f"arm_{side}_"))
    if region == "LEG":
        return name.startswith(f"leg_{side}_") or name in {"body", "root"}
    return not name.startswith(("arm_", "shoulder_", "leg_"))


target = bpy.data.objects[TARGET]
armature = bpy.data.objects[ARMATURE]
action = bpy.data.actions[WALK]
scene = bpy.context.scene
animation = armature.animation_data_create()
component_list = components(target.data)
membership = {
    vertex: component_id
    for component_id, indices in enumerate(component_list)
    for vertex in indices
}
snapshot = {
    "frame": scene.frame_current,
    "action": animation.action,
    "pose_position": armature.data.pose_position,
    "basis": {
        bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones
    },
}

try:
    animation.action = None
    armature.data.pose_position = "POSE"
    for bone in armature.pose.bones:
        bone.matrix_basis.identity()
    scene.frame_set(1)
    bpy.context.view_layer.update()
    rest = evaluated_points(target)
    minimum = Vector(min(point[axis] for point in rest) for axis in range(3))
    maximum = Vector(max(point[axis] for point in rest) for axis in range(3))
    height = maximum.z - minimum.z
    center = (minimum + maximum) * 0.5

    invalid_vertices = {}
    invalid_components = defaultdict(float)
    for index, point in enumerate(rest):
        region = point_region(point, center, minimum.z, height)
        side = (
            "left"
            if point.x < center.x - height * 0.01
            else "right"
            if point.x > center.x + height * 0.01
            else "center"
        )
        invalid_weights = [
            (name, value)
            for name, value in weights(target, index)
            if not bone_allowed(name, region, side)
        ]
        if invalid_weights:
            invalid_vertices[index] = {
                "region": region,
                "side": side,
                "invalid_weights": invalid_weights,
            }
            invalid_components[membership[index]] += sum(
                value for _name, value in invalid_weights
            )

    animation.action = action
    frame_summaries = []
    first_bad = None
    worst_frame = None
    for frame in range(math.floor(action.frame_range[0]), math.ceil(action.frame_range[1]) + 1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        posed = evaluated_points(target)
        displacements = [
            (point - rest_point).length
            for point, rest_point in zip(posed, rest)
        ]
        maximum_displacement = max(displacements)
        explosive = sum(value > height * 1.25 for value in displacements)
        summary = {
            "frame": frame,
            "maximum_displacement": round(maximum_displacement, 6),
            "explosive_vertices": explosive,
        }
        frame_summaries.append(summary)
        if first_bad is None and (
            explosive or maximum_displacement > height * 0.2
        ):
            first_bad = frame
        if worst_frame is None or maximum_displacement > worst_frame[0]:
            worst_frame = (maximum_displacement, frame)

    evidence_frame = first_bad if first_bad is not None else worst_frame[1]
    scene.frame_set(evidence_frame)
    bpy.context.view_layer.update()
    deformed = evaluated_points(target)
    ranked = sorted(
        range(len(rest)),
        key=lambda index: (deformed[index] - rest[index]).length,
        reverse=True,
    )
    dominant_invalid_vertices = [
        index
        for index, audit in invalid_vertices.items()
        if weights(target, index)
        and weights(target, index)[0][0]
        in {name for name, _value in audit["invalid_weights"]}
    ]
    worst_invalid_index = max(
        dominant_invalid_vertices,
        key=lambda index: (deformed[index] - rest[index]).length,
    )
    component_worst = {}
    for index in ranked:
        component_id = membership[index]
        if component_id not in component_worst:
            component_worst[component_id] = index
    worst_components = []
    anatomical_left = Vector((-1.0, 0.0, 0.0))
    for component_id, index in list(component_worst.items())[:12]:
        vertex_weights = weights(target, index)
        dominant = vertex_weights[0][0] if vertex_weights else None
        centroid = sum((rest[item] for item in component_list[component_id]), Vector())
        centroid /= len(component_list[component_id])
        side = (
            "left"
            if centroid.dot(anatomical_left) > 1.0e-5
            else "right"
            if centroid.dot(anatomical_left) < -1.0e-5
            else "center"
        )
        bone_side = (
            "left"
            if dominant and "_left" in dominant
            else "right"
            if dominant and "_right" in dominant
            else "center"
        )
        worst_components.append(
            {
                "component_id": component_id,
                "vertex": index,
                "component_vertices": len(component_list[component_id]),
                "rest": [round(float(value), 6) for value in rest[index]],
                "deformed": [round(float(value), 6) for value in deformed[index]],
                "displacement": round((deformed[index] - rest[index]).length, 6),
                "weights": vertex_weights,
                "dominant_bone": dominant,
                "anatomical_side": side,
                "dominant_bone_side": bone_side,
                "anatomically_valid": bone_side in {"center", side},
            }
        )

    animation.action = None
    isolated = []
    for name in ISOLATED_BONES:
        bone = armature.pose.bones[name]
        axis_results = []
        for axis_name, axis in (
            ("X", Vector((1.0, 0.0, 0.0))),
            ("Y", Vector((0.0, 1.0, 0.0))),
            ("Z", Vector((0.0, 0.0, 1.0))),
        ):
            for item in armature.pose.bones:
                item.matrix_basis.identity()
            bone.rotation_mode = "QUATERNION"
            bone.rotation_quaternion = Quaternion(axis, math.radians(45.0))
            bpy.context.view_layer.update()
            points = evaluated_points(target)
            maximum_displacement = max(
                (point - rest_point).length
                for point, rest_point in zip(points, rest)
            )
            invalid_ranked = sorted(
                (
                    ((points[index] - rest[index]).length, index)
                    for index, audit in invalid_vertices.items()
                    if any(weight_name == name for weight_name, _value in audit["invalid_weights"])
                ),
                reverse=True,
            )
            axis_results.append(
                (
                    axis_name,
                    maximum_displacement,
                    invalid_ranked[0] if invalid_ranked else (0.0, None),
                )
            )
        worst_axis, maximum_displacement, worst_invalid = max(
            axis_results, key=lambda item: item[2][0]
        )
        isolated.append(
            {
                "bone": name,
                "worst_axis": worst_axis,
                "maximum_displacement": round(maximum_displacement, 6),
                "maximum_anatomically_invalid_displacement": round(
                    worst_invalid[0], 6
                ),
                "worst_anatomically_invalid_vertex": worst_invalid[1],
                "catastrophic": maximum_displacement > height * 1.5,
            }
        )

    modifier = next(
        modifier for modifier in target.modifiers if modifier.type == "ARMATURE"
    )
    report = {
        "height": round(height, 6),
        "anatomically_invalid_weighted_vertices": len(invalid_vertices),
        "anatomically_invalid_components": len(invalid_components),
        "worst_invalid_components": [
            {
                "component_id": component_id,
                "invalid_weight_sum": round(value, 6),
                "vertices": len(component_list[component_id]),
            }
            for component_id, value in sorted(
                invalid_components.items(), key=lambda item: item[1], reverse=True
            )[:12]
        ],
        "first_bad_frame": first_bad,
        "worst_frame": worst_frame[1],
        "frame_summaries": frame_summaries,
        "worst_components_at_evidence_frame": worst_components,
        "worst_invalid_vertex_at_evidence_frame": {
            "vertex": worst_invalid_index,
            "component_id": membership[worst_invalid_index],
            "rest": [round(float(value), 6) for value in rest[worst_invalid_index]],
            "deformed": [
                round(float(value), 6) for value in deformed[worst_invalid_index]
            ],
            "displacement": round(
                (deformed[worst_invalid_index] - rest[worst_invalid_index]).length,
                6,
            ),
            "weights": weights(target, worst_invalid_index),
            **invalid_vertices[worst_invalid_index],
        },
        "isolated_bones": isolated,
        "matrices": {
            "mesh_world": matrix_values(target.matrix_world),
            "armature_world": matrix_values(armature.matrix_world),
            "mesh_parent_inverse": matrix_values(target.matrix_parent_inverse),
            "parent": target.parent.name if target.parent else None,
        },
        "modifier": {
            "name": modifier.name,
            "target": modifier.object.name if modifier.object else None,
            "use_vertex_groups": modifier.use_vertex_groups,
            "use_bone_envelopes": modifier.use_bone_envelopes,
        },
    }
    print("SBF_EXPLOSION_DIAGNOSTIC")
    print(json.dumps(report, indent=2, sort_keys=True))
finally:
    animation.action = snapshot["action"]
    armature.data.pose_position = snapshot["pose_position"]
    for name, matrix in snapshot["basis"].items():
        armature.pose.bones[name].matrix_basis = matrix
    scene.frame_set(snapshot["frame"])
    bpy.context.view_layer.update()
