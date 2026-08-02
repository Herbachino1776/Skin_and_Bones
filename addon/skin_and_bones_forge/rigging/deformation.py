"""Reusable rig, bind-space, and component deformation forensics."""

from __future__ import annotations

from collections import defaultdict
import math
import struct

import bpy
from mathutils import Matrix, Quaternion, Vector

from .analysis import evaluated_points


FORENSICS_SCHEMA = 2
DEFAULT_BOUNDS_RATIO = 1.8
DEFAULT_VERTEX_DISPLACEMENT_RATIO = 1.25
DEFAULT_COMPONENT_SEPARATION_RATIO = 0.55
DEFAULT_SEPARATION_BOUNDS_RATIO = 1.35
# Calibrated above the complete 45-degree isolated-bone stress suite.  The
# broken fixture produces 18x walk edges and 20-30x isolated-bone fans, so this
# remains a conservative detector for anchored/ghosting deformation.
DEFAULT_EDGE_STRETCH_RATIO = 4.5
# A ratio alone is unstable on millimeter-scale edges. Require the deformed
# edge to also span a material fraction of character height; the known pelvis
# fan reaches 8% height while the accepted collapse fold remains below 4%.
DEFAULT_EDGE_DEFORMED_LENGTH_RATIO = 0.04
DEFAULT_COINCIDENT_SEAM_SEPARATION_RATIO = 1.0e-5
MEANINGFUL_WEIGHT = 0.0001

ISOLATED_BONES = (
    "root",
    "body",
    "body_top0",
    "body_top1",
    "body_top2",
    "neck",
    "head",
    "shoulder_left",
    "shoulder_right",
    "arm_left_top",
    "arm_right_top",
    "arm_left_bot",
    "arm_right_bot",
    "arm_left_hand",
    "arm_right_hand",
    "leg_left_top",
    "leg_right_top",
    "leg_left_bot",
    "leg_right_bot",
    "leg_left_foot",
    "leg_right_foot",
)


def _number(value, digits=6):
    number = round(float(value), digits)
    return 0.0 if number == -0.0 else number


def _vector(value):
    return [_number(component) for component in value]


def _matrix(value):
    return [[_number(component, 8) for component in row] for row in value]


def _matrix_delta(first, second):
    return max(
        abs(float(a) - float(b))
        for first_row, second_row in zip(first, second)
        for a, b in zip(first_row, second_row)
    )


def _angle(first, second):
    if first.length <= 1.0e-8 or second.length <= 1.0e-8:
        return 180.0
    dot = max(-1.0, min(1.0, first.normalized().dot(second.normalized())))
    return math.degrees(math.acos(dot))


def _bounds(points):
    minimum = Vector(min(point[axis] for point in points) for axis in range(3))
    maximum = Vector(max(point[axis] for point in points) for axis in range(3))
    return minimum, maximum


def _bounds_payload(points):
    minimum, maximum = _bounds(points)
    return minimum, maximum, {
        "minimum": _vector(minimum),
        "maximum": _vector(maximum),
        "diagonal": _number((maximum - minimum).length),
    }


def connected_components(mesh):
    """Return deterministic connected vertex components and membership."""

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
    components = sorted(grouped.values(), key=lambda item: (-len(item), item[0]))
    membership = {
        vertex: component
        for component, indices in enumerate(components)
        for vertex in indices
    }
    return components, membership


def vertex_weights(target, index, threshold=0.0):
    weights = []
    for item in target.data.vertices[index].groups:
        if item.group >= len(target.vertex_groups):
            continue
        value = float(item.weight)
        if value < threshold:
            continue
        weights.append((target.vertex_groups[item.group].name, _number(value)))
    return sorted(weights, key=lambda item: (-item[1], item[0]))


def _bone_side(name):
    if "_left" in name:
        return "LEFT"
    if "_right" in name:
        return "RIGHT"
    return "CENTER"


def _bone_region(name):
    if name == "head":
        return "HEAD"
    if name == "neck":
        return "NECK"
    if "hand" in name:
        return "HAND"
    if name.startswith(("shoulder_", "arm_")):
        return "ARM"
    if "foot" in name:
        return "FOOT"
    if name.startswith("leg_"):
        return "LEG"
    if name in {"root", "body", "body_top0", "body_top1", "body_top2"}:
        return "TORSO"
    return "UNKNOWN"


def _region_for(fraction, lateral_fraction):
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


def point_anatomy(point, analysis):
    up = Vector(analysis["up_axis_world"])
    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    height = float(analysis["world_height"])
    ground = float(analysis["ground"])
    lateral_offset = (point - center).dot(lateral)
    region = _region_for(
        (point.dot(up) - ground) / max(height, 1.0e-8),
        abs(lateral_offset) / max(height, 1.0e-8),
    )
    side = (
        "CENTER"
        if abs(lateral_offset) <= height * 0.01
        else "LEFT"
        if lateral_offset > 0.0
        else "RIGHT"
    )
    return region, side


def anatomically_plausible(bone_name, region, side):
    bone_side = _bone_side(bone_name)
    if side != "CENTER" and bone_side not in {"CENTER", side}:
        return False
    if region == "HEAD":
        return bone_name in {"body_top1", "body_top2", "neck", "head"}
    if region == "HAND":
        if side == "CENTER":
            return bone_name in {"arm_left_hand", "arm_right_hand"}
        return bone_name == f"arm_{side.lower()}_hand"
    if region == "FOOT":
        token = side.lower() if side != "CENTER" else ""
        return bone_name.startswith("leg_") and (
            not token or f"_{token}_" in bone_name
        )
    if region == "ARM":
        return bone_name.startswith(("shoulder_", "arm_"))
    if region == "LEG":
        return bone_name.startswith("leg_") or bone_name in {"body", "root"}
    return bone_name in {
        "root",
        "body",
        "body_top0",
        "body_top1",
        "body_top2",
        "neck",
        "head",
    }


def analysis_from_points(points, forward_axis="+Y"):
    """Create the minimal anatomical frame required by the scanner."""

    up = Vector((0.0, 0.0, 1.0))
    forward = {
        "+Y": Vector((0.0, 1.0, 0.0)),
        "-Y": Vector((0.0, -1.0, 0.0)),
        "+X": Vector((1.0, 0.0, 0.0)),
        "-X": Vector((-1.0, 0.0, 0.0)),
    }[forward_axis]
    lateral = up.cross(forward).normalized()
    up_values = [point.dot(up) for point in points]
    lateral_values = [point.dot(lateral) for point in points]
    forward_values = [point.dot(forward) for point in points]
    ground = min(up_values)
    top = max(up_values)
    center = (
        up * ((ground + top) * 0.5)
        + lateral * ((min(lateral_values) + max(lateral_values)) * 0.5)
        + forward * ((min(forward_values) + max(forward_values)) * 0.5)
    )
    return {
        "forward_axis": forward_axis,
        "forward_axis_world": _vector(forward),
        "up_axis_world": _vector(up),
        "lateral_axis_world": _vector(lateral),
        "centerline_world": _vector(center),
        "ground": _number(ground),
        "top": _number(top),
        "world_height": _number(top - ground),
    }


def _pose_snapshot(context, armature):
    scene = context.scene
    animation = armature.animation_data
    return {
        "frame": scene.frame_current,
        "action": animation.action if animation else None,
        "action_slot": animation.action_slot if animation else None,
        "nla": (
            [(track, bool(track.mute)) for track in animation.nla_tracks]
            if animation
            else []
        ),
        "pose_position": armature.data.pose_position,
        "basis": {
            bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones
        },
        "rotation_mode": {
            bone.name: bone.rotation_mode for bone in armature.pose.bones
        },
        "active": context.view_layer.objects.active,
        "selected": list(context.selected_objects),
    }


def _restore_pose(context, armature, snapshot):
    scene = context.scene
    animation = armature.animation_data
    armature.data.pose_position = snapshot["pose_position"]
    if animation is not None:
        animation.action = snapshot["action"]
        if snapshot["action"] is not None and snapshot["action_slot"] is not None:
            animation.action_slot = snapshot["action_slot"]
    for track, mute in snapshot["nla"]:
        try:
            track.mute = mute
        except ReferenceError:
            pass
    for bone in armature.pose.bones:
        if bone.name in snapshot["basis"]:
            bone.matrix_basis = snapshot["basis"][bone.name]
        if bone.name in snapshot["rotation_mode"]:
            bone.rotation_mode = snapshot["rotation_mode"][bone.name]
    scene.frame_set(snapshot["frame"])
    for obj in context.selected_objects:
        obj.select_set(False)
    for obj in snapshot["selected"]:
        if obj.name in context.view_layer.objects:
            obj.select_set(True)
    active = snapshot["active"]
    context.view_layer.objects.active = (
        active if active and active.name in context.view_layer.objects else None
    )
    context.view_layer.update()


def _reset_pose(armature):
    armature.data.pose_position = "POSE"
    for bone in armature.pose.bones:
        bone.matrix_basis.identity()


def _assign_action(animation, action):
    animation.action = action
    suitable = list(getattr(animation, "action_suitable_slots", []))
    if suitable:
        animation.action_slot = suitable[0]
        return suitable[0]
    slots = [
        slot
        for slot in getattr(action, "slots", [])
        if getattr(slot, "target_id_type", "") == "OBJECT"
    ]
    if slots:
        animation.action_slot = slots[0]
        return slots[0]
    return None


def _component_reference(points, components):
    records = []
    for component, indices in enumerate(components):
        component_points = [points[index] for index in indices]
        minimum, maximum = _bounds(component_points)
        records.append(
            {
                "component": component,
                "indices": indices,
                "centroid": sum(component_points, Vector()) / len(indices),
                "diagonal": (maximum - minimum).length,
            }
        )
    return records


def _edge_reference(mesh, points, membership, height):
    """Capture rest edge lengths for direct skin-stretch detection."""

    minimum_length = max(height * 1.0e-6, 1.0e-9)
    records = []
    for edge in mesh.edges:
        first, second = map(int, edge.vertices)
        rest_length = (points[second] - points[first]).length
        if rest_length <= minimum_length:
            continue
        records.append(
            {
                "edge": int(edge.index),
                "vertices": (first, second),
                "component": membership[first],
                "rest_length": rest_length,
                "rest_positions": (points[first].copy(), points[second].copy()),
            }
        )
    return records


def _coincident_vertex_groups(mesh):
    """Return exact local-position duplicates created by GLB vertex splits."""

    grouped = defaultdict(list)
    for vertex in mesh.vertices:
        values = tuple(
            0.0 if float(value) == 0.0 else float(value)
            for value in vertex.co
        )
        grouped[struct.pack("<3f", *values)].append(int(vertex.index))
    return [tuple(indices) for indices in grouped.values() if len(indices) > 1]


def _coincident_seam_metrics(points, groups, height, separation_limit):
    threshold = max(float(height) * float(separation_limit), 1.0e-8)
    seams = []
    for indices in groups:
        maximum = max(
            (points[first] - points[second]).length
            for offset, first in enumerate(indices)
            for second in indices[offset + 1 :]
        )
        if maximum > threshold:
            seams.append(
                {
                    "vertices": indices,
                    "separation": maximum,
                }
            )
    seams.sort(key=lambda item: item["separation"], reverse=True)
    return {
        "coincident_vertex_groups": len(groups),
        "separated_coincident_seams": len(seams),
        "maximum_coincident_seam_separation": max(
            (item["separation"] for item in seams), default=0.0
        ),
        "coincident_seams": seams,
    }


def _frame_metrics(
    rest_points,
    points,
    height,
    component_reference,
    edge_reference,
    bounds_limit,
    displacement_limit,
    separation_limit,
    edge_stretch_limit,
    edge_deformed_length_limit=DEFAULT_EDGE_DEFORMED_LENGTH_RATIO,
):
    rest_minimum, rest_maximum = _bounds(rest_points)
    minimum, maximum = _bounds(points)
    rest_diagonal = max((rest_maximum - rest_minimum).length, height)
    bounds_ratio = (maximum - minimum).length / max(rest_diagonal, 1.0e-8)
    displacements = [
        (point - rest).length for point, rest in zip(points, rest_points)
    ]
    non_finite = [
        index
        for index, point in enumerate(points)
        if any(not math.isfinite(float(value)) for value in point)
    ]
    rest_center = (rest_minimum + rest_maximum) * 0.5
    center = (minimum + maximum) * 0.5
    global_translation = center - rest_center
    relative_displacements = [
        (point - rest - global_translation).length
        for point, rest in zip(points, rest_points)
    ]
    components = []
    for reference in component_reference:
        indices = reference["indices"]
        component_points = [points[index] for index in indices]
        component_minimum, component_maximum = _bounds(component_points)
        centroid = sum(component_points, Vector()) / len(indices)
        relative_motion = (
            (centroid - center) - (reference["centroid"] - rest_center)
        ).length
        diagonal_ratio = (component_maximum - component_minimum).length / max(
            reference["diagonal"], height * 1.0e-5
        )
        components.append(
            {
                "component": reference["component"],
                "vertex_count": len(indices),
                "relative_centroid_displacement": relative_motion,
                "bounds_ratio": diagonal_ratio,
                "maximum_vertex_displacement": max(
                    displacements[index] for index in indices
                ),
            }
        )
    separated = [
        item
        for item in components
        if item["relative_centroid_displacement"] > height * separation_limit
    ]
    stretched = [
        item for item in components if item["bounds_ratio"] > bounds_limit
    ]
    stretched_component_ids = {item["component"] for item in stretched}
    blocking_separated = [
        item
        for item in separated
        if item["component"] in stretched_component_ids
        or bounds_ratio > DEFAULT_SEPARATION_BOUNDS_RATIO
    ]
    explosive = [
        index
        for index, displacement in enumerate(relative_displacements)
        if displacement > height * displacement_limit
    ]
    edge_strain = []
    for reference in edge_reference:
        first, second = reference["vertices"]
        deformed_length = (points[second] - points[first]).length
        stretch_ratio = deformed_length / reference["rest_length"]
        edge_strain.append(
            {
                "edge": reference["edge"],
                "vertices": reference["vertices"],
                "component": reference["component"],
                "rest_length": reference["rest_length"],
                "rest_positions": reference["rest_positions"],
                "deformed_length": deformed_length,
                "stretch_ratio": stretch_ratio,
            }
        )
    stretched_edges = [
        item
        for item in edge_strain
        if not math.isfinite(item["stretch_ratio"])
        or (
            item["stretch_ratio"] > edge_stretch_limit
            and item["deformed_length"]
            > height * edge_deformed_length_limit
        )
    ]
    safe = (
        not non_finite
        and not blocking_separated
        and not stretched_edges
        and not explosive
    )
    safe = safe and bounds_ratio <= bounds_limit
    return {
        "safe": safe,
        "non_finite_vertices": len(non_finite),
        "explosive_vertices": len(explosive),
        "separated_components": len(separated),
        "blocking_separated_components": len(blocking_separated),
        "stretched_components": len(stretched),
        "stretched_edges": len(stretched_edges),
        "maximum_edge_stretch_ratio": max(
            (item["stretch_ratio"] for item in edge_strain), default=1.0
        ),
        "maximum_displacement": max(displacements, default=0.0),
        "maximum_relative_displacement": max(
            relative_displacements, default=0.0
        ),
        "global_translation": _vector(global_translation),
        "bounds_ratio": bounds_ratio,
        "bounds": {"minimum": _vector(minimum), "maximum": _vector(maximum)},
        "displacements": displacements,
        "components": components,
        "edge_strain": edge_strain,
    }


def _outlier_report(
    target,
    armature,
    rest_points,
    points,
    metrics,
    membership,
    analysis,
    limit=20,
):
    ranked = sorted(
        range(len(points)),
        key=lambda index: metrics["displacements"][index],
        reverse=True,
    )[:limit]
    result = []
    for index in ranked:
        weights = vertex_weights(target, index, MEANINGFUL_WEIGHT)
        dominant = weights[0][0] if weights else None
        region, side = point_anatomy(rest_points[index], analysis)
        pose_bone = armature.pose.bones.get(dominant) if dominant else None
        result.append(
            {
                "vertex": index,
                "component": membership[index],
                "rest": _vector(rest_points[index]),
                "deformed": _vector(points[index]),
                "displacement": _number(metrics["displacements"][index]),
                "weights": weights,
                "dominant_bone": dominant,
                "dominant_bone_region": _bone_region(dominant or ""),
                "dominant_bone_side": _bone_side(dominant or ""),
                "vertex_region": region,
                "vertex_side": side,
                "anatomically_plausible": (
                    anatomically_plausible(dominant, region, side)
                    if dominant
                    else False
                ),
                "dominant_bone_pose_matrix": (
                    _matrix(pose_bone.matrix) if pose_bone else None
                ),
            }
        )
    return result


def _worst_edge_report(target, metrics, points=None, limit=20):
    return [
        {
            "edge": item["edge"],
            "vertices": list(item["vertices"]),
            "component": item["component"],
            "rest_length": _number(item["rest_length"], 8),
            "rest_positions": [
                _vector(position) for position in item["rest_positions"]
            ],
            "deformed_length": _number(item["deformed_length"], 8),
            "stretch_ratio": _number(item["stretch_ratio"]),
            "endpoint_weights": [
                vertex_weights(target, index, MEANINGFUL_WEIGHT)
                for index in item["vertices"]
            ],
            "endpoint_positions": (
                [_vector(points[index]) for index in item["vertices"]]
                if points is not None
                else None
            ),
        }
        for item in sorted(
            metrics["edge_strain"],
            key=lambda edge: edge["stretch_ratio"],
            reverse=True,
        )[:limit]
    ]


def scan_action_deformation(
    context,
    target,
    armature,
    action,
    analysis=None,
    frames=None,
    bounds_limit=DEFAULT_BOUNDS_RATIO,
    displacement_limit=DEFAULT_VERTEX_DISPLACEMENT_RATIO,
    separation_limit=DEFAULT_COMPONENT_SEPARATION_RATIO,
    edge_stretch_limit=DEFAULT_EDGE_STRETCH_RATIO,
    edge_deformed_length_limit=DEFAULT_EDGE_DEFORMED_LENGTH_RATIO,
    coincident_seam_limit=DEFAULT_COINCIDENT_SEAM_SEPARATION_RATIO,
):
    """Evaluate every requested Action frame and restore all touched state."""

    if target is None or target.type != "MESH":
        raise ValueError("Deformation forensics requires one mesh target.")
    if armature is None or armature.type != "ARMATURE":
        raise ValueError("Deformation forensics requires one armature.")
    if action is None:
        raise ValueError("Deformation forensics requires an Action.")

    snapshot = _pose_snapshot(context, armature)
    animation = armature.animation_data_create()
    components, membership = connected_components(target.data)
    report = None
    try:
        for track in animation.nla_tracks:
            track.mute = True
        animation.action = None
        _reset_pose(armature)
        context.scene.frame_set(1)
        context.view_layer.update()
        rest_points = evaluated_points(context, target)
        if not rest_points:
            raise RuntimeError("The evaluated target mesh has no vertices.")
        effective_analysis = analysis or analysis_from_points(rest_points)
        height = float(effective_analysis["world_height"])
        references = _component_reference(rest_points, components)
        edges = _edge_reference(target.data, rest_points, membership, height)
        coincident_groups = _coincident_vertex_groups(target.data)
        assigned_slot = _assign_action(animation, action)
        if frames is None:
            first, last = action.frame_range
            frames = range(math.floor(first), math.ceil(last) + 1)
        frame_reports = []
        worst = None
        first_unsafe = None
        for frame in sorted(set(int(value) for value in frames)):
            context.scene.frame_set(frame)
            context.view_layer.update()
            points = evaluated_points(context, target)
            metrics = _frame_metrics(
                rest_points,
                points,
                height,
                references,
                edges,
                bounds_limit,
                displacement_limit,
                separation_limit,
                edge_stretch_limit,
                edge_deformed_length_limit,
            )
            metrics.update(
                _coincident_seam_metrics(
                    points, coincident_groups, height, coincident_seam_limit
                )
            )
            metrics["safe"] = (
                metrics["safe"]
                and not metrics["separated_coincident_seams"]
            )
            score = max(
                metrics["bounds_ratio"],
                metrics["maximum_edge_stretch_ratio"]
                / max(edge_stretch_limit, 1.0e-8),
                metrics["maximum_displacement"] / max(height, 1.0e-8),
                metrics["maximum_coincident_seam_separation"]
                / max(height * coincident_seam_limit, 1.0e-8),
                max(
                    (
                        item["relative_centroid_displacement"]
                        / max(height, 1.0e-8)
                        for item in metrics["components"]
                    ),
                    default=0.0,
                ),
            )
            summary = {
                "frame": frame,
                "safe": metrics["safe"],
                "maximum_displacement": _number(
                    metrics["maximum_displacement"]
                ),
                "displacement_height_ratio": _number(
                    metrics["maximum_displacement"] / max(height, 1.0e-8)
                ),
                "bounds_ratio": _number(metrics["bounds_ratio"]),
                "non_finite_vertices": metrics["non_finite_vertices"],
                "explosive_vertices": metrics["explosive_vertices"],
                "separated_components": metrics["separated_components"],
                "blocking_separated_components": metrics[
                    "blocking_separated_components"
                ],
                "stretched_components": metrics["stretched_components"],
                "stretched_edges": metrics["stretched_edges"],
                "maximum_edge_stretch_ratio": _number(
                    metrics["maximum_edge_stretch_ratio"]
                ),
                "separated_coincident_seams": metrics[
                    "separated_coincident_seams"
                ],
                "maximum_coincident_seam_separation": _number(
                    metrics["maximum_coincident_seam_separation"], 8
                ),
            }
            frame_reports.append(summary)
            if first_unsafe is None and not metrics["safe"]:
                first_unsafe = frame
            if worst is None or score > worst[0]:
                worst = (score, frame, points, metrics)
        if worst is None:
            raise RuntimeError(f"Action '{action.name}' contains no evaluable frames.")

        _score, worst_frame, worst_points, worst_metrics = worst
        context.scene.frame_set(worst_frame)
        context.view_layer.update()
        component_outliers = sorted(
            worst_metrics["components"],
            key=lambda item: (
                item["relative_centroid_displacement"],
                item["bounds_ratio"],
                item["maximum_vertex_displacement"],
            ),
            reverse=True,
        )[:20]
        report = {
            "schema": FORENSICS_SCHEMA,
            "status": (
                "READY_FOR_ANIMATION_TEST"
                if all(item["safe"] for item in frame_reports)
                else "FAILED"
            ),
            "action": action.name,
            "assigned_action_slot": (
                assigned_slot.name_display if assigned_slot else None
            ),
            "height": _number(height),
            "vertex_count": len(rest_points),
            "component_count": len(components),
            "thresholds": {
                "bounds_ratio": bounds_limit,
                "vertex_displacement_height_ratio": displacement_limit,
                "component_separation_height_ratio": separation_limit,
                "separation_bounds_ratio": DEFAULT_SEPARATION_BOUNDS_RATIO,
                "edge_stretch_ratio": edge_stretch_limit,
                "edge_deformed_length_height_ratio": (
                    edge_deformed_length_limit
                ),
                "coincident_seam_separation_height_ratio": coincident_seam_limit,
            },
            "first_unsafe_frame": first_unsafe,
            "worst_frame": worst_frame,
            "maximum_displacement": max(
                item["maximum_displacement"] for item in frame_reports
            ),
            "maximum_bounds_ratio": max(
                item["bounds_ratio"] for item in frame_reports
            ),
            "maximum_edge_stretch_ratio": max(
                item["maximum_edge_stretch_ratio"] for item in frame_reports
            ),
            "coincident_vertex_groups": len(coincident_groups),
            "maximum_coincident_seam_separation": max(
                item["maximum_coincident_seam_separation"]
                for item in frame_reports
            ),
            "worst_coincident_seams": [
                {
                    "vertices": list(item["vertices"]),
                    "separation": _number(item["separation"], 8),
                    "weights": [
                        vertex_weights(target, index, MEANINGFUL_WEIGHT)
                        for index in item["vertices"]
                    ],
                }
                for item in worst_metrics["coincident_seams"][:20]
            ],
            "frames": frame_reports,
            "worst_components": [
                {
                    "component": item["component"],
                    "vertex_count": item["vertex_count"],
                    "relative_centroid_displacement": _number(
                        item["relative_centroid_displacement"]
                    ),
                    "bounds_ratio": _number(item["bounds_ratio"]),
                    "maximum_vertex_displacement": _number(
                        item["maximum_vertex_displacement"]
                    ),
                }
                for item in component_outliers
            ],
            "worst_vertices": _outlier_report(
                target,
                armature,
                rest_points,
                worst_points,
                worst_metrics,
                membership,
                effective_analysis,
            ),
            "worst_edges": _worst_edge_report(
                target, worst_metrics, worst_points
            ),
        }
    finally:
        _restore_pose(context, armature, snapshot)

    report["state_restored"] = (
        context.scene.frame_current == snapshot["frame"]
        and armature.data.pose_position == snapshot["pose_position"]
        and (
            armature.animation_data.action if armature.animation_data else None
        )
        == snapshot["action"]
        and {
            obj.name for obj in context.selected_objects
        }
        == {obj.name for obj in snapshot["selected"]}
    )
    if not report["state_restored"]:
        report["status"] = "FAILED"
    return report


def run_isolated_bone_forensics(
    context,
    target,
    armature,
    analysis=None,
    degrees=45.0,
):
    """Rotate each production chain independently around all three local axes."""

    snapshot = _pose_snapshot(context, armature)
    animation = armature.animation_data_create()
    components, membership = connected_components(target.data)
    tests = []
    try:
        for track in animation.nla_tracks:
            track.mute = True
        animation.action = None
        _reset_pose(armature)
        context.scene.frame_set(1)
        context.view_layer.update()
        rest = evaluated_points(context, target)
        effective_analysis = analysis or analysis_from_points(rest)
        height = float(effective_analysis["world_height"])
        references = _component_reference(rest, components)
        edges = _edge_reference(target.data, rest, membership, height)
        anatomy = [point_anatomy(point, effective_analysis) for point in rest]
        for name in ISOLATED_BONES:
            bone = armature.pose.bones.get(name)
            if bone is None:
                tests.append({"bone": name, "safe": False, "missing": True})
                continue
            bone_results = []
            for axis_name, axis in (
                ("X", Vector((1.0, 0.0, 0.0))),
                ("Y", Vector((0.0, 1.0, 0.0))),
                ("Z", Vector((0.0, 0.0, 1.0))),
            ):
                _reset_pose(armature)
                bone.rotation_mode = "QUATERNION"
                bone.rotation_quaternion = Quaternion(axis, math.radians(degrees))
                context.view_layer.update()
                points = evaluated_points(context, target)
                metrics = _frame_metrics(
                    rest,
                    points,
                    height,
                    references,
                    edges,
                    DEFAULT_BOUNDS_RATIO,
                    DEFAULT_VERTEX_DISPLACEMENT_RATIO,
                    DEFAULT_COMPONENT_SEPARATION_RATIO,
                    DEFAULT_EDGE_STRETCH_RATIO,
                )
                affected = [
                    index
                    for index, value in enumerate(metrics["displacements"])
                    if value > height * 0.01
                ]
                regions = sorted({anatomy[index][0] for index in affected})
                side = _bone_side(name)
                opposite = (
                    "RIGHT" if side == "LEFT" else "LEFT" if side == "RIGHT" else None
                )
                unexpected = sum(
                    metrics["displacements"][index] > height * 0.05
                    and anatomy[index][1] == opposite
                    for index in affected
                )
                # Per-vertex side labels are diagnostic only: a connected torso or
                # garment fragment can legitimately cross the centerline. Direct
                # edge strain is the blocking anchored-fan signal.
                safe = metrics["safe"]
                bone_results.append(
                    {
                        "axis": axis_name,
                        "safe": safe,
                        "maximum_displacement": _number(
                            metrics["maximum_displacement"]
                        ),
                        "bounds_ratio": _number(metrics["bounds_ratio"]),
                        "affected_component_count": len(
                            {
                                component
                                for component, reference in enumerate(references)
                                if any(index in affected for index in reference["indices"])
                            }
                        ),
                        "affected_anatomical_regions": regions,
                        "unexpected_opposite_side_vertices": unexpected,
                        "separated_components": metrics["separated_components"],
                        "stretched_components": metrics["stretched_components"],
                        "stretched_edges": metrics["stretched_edges"],
                        "maximum_edge_stretch_ratio": _number(
                            metrics["maximum_edge_stretch_ratio"]
                        ),
                        "worst_edges": _worst_edge_report(
                            target, metrics, points, limit=5
                        ),
                    }
                )
            tests.extend(
                {"bone": name, "missing": False, **result}
                for result in bone_results
            )
    finally:
        _restore_pose(context, armature, snapshot)
    state_restored = (
        context.scene.frame_current == snapshot["frame"]
        and armature.data.pose_position == snapshot["pose_position"]
        and (
            armature.animation_data.action if armature.animation_data else None
        )
        == snapshot["action"]
        and {obj.name for obj in context.selected_objects}
        == {obj.name for obj in snapshot["selected"]}
    )
    return {
        "schema": FORENSICS_SCHEMA,
        "status": (
            "READY_FOR_ANIMATION_TEST"
            if tests and all(item["safe"] for item in tests) and state_restored
            else "FAILED"
        ),
        "degrees": degrees,
        "tests": tests,
        "state_restored": state_restored,
    }


def audit_bind_space(context, target, armature):
    """Record and validate the complete object/modifier binding transaction."""

    modifiers = [
        modifier for modifier in target.modifiers if modifier.type == "ARMATURE"
    ]
    intended = [modifier for modifier in modifiers if modifier.object == armature]
    expected_inverse = armature.matrix_world.inverted_safe()
    inverse_delta = _matrix_delta(target.matrix_parent_inverse, expected_inverse)
    evaluated = target.evaluated_get(context.evaluated_depsgraph_get())
    rest_points = evaluated_points(context, target)
    _minimum, _maximum, bounds = _bounds_payload(rest_points)
    consistent = (
        target.parent == armature
        and target.parent_type == "OBJECT"
        and len(modifiers) == 1
        and len(intended) == 1
        and intended[0].use_vertex_groups
        and not intended[0].use_bone_envelopes
        and inverse_delta <= 1.0e-5
    )
    return {
        "status": "READY_FOR_ANIMATION_TEST" if consistent else "NEEDS_REBIND",
        "consistent": consistent,
        "mesh": {
            "object": target.name,
            "parent": target.parent.name if target.parent else None,
            "parent_type": target.parent_type,
            "location": _vector(target.location),
            "rotation_euler": _vector(target.rotation_euler),
            "scale": _vector(target.scale),
            "matrix_local": _matrix(target.matrix_local),
            "matrix_world": _matrix(target.matrix_world),
            "matrix_parent_inverse": _matrix(target.matrix_parent_inverse),
            "evaluated_matrix_world": _matrix(evaluated.matrix_world),
            "rest_bounds": bounds,
        },
        "armature": {
            "object": armature.name,
            "parent": armature.parent.name if armature.parent else None,
            "location": _vector(armature.location),
            "rotation_euler": _vector(armature.rotation_euler),
            "scale": _vector(armature.scale),
            "matrix_local": _matrix(armature.matrix_local),
            "matrix_world": _matrix(armature.matrix_world),
        },
        "parent_inverse_expected": _matrix(expected_inverse),
        "parent_inverse_max_delta": _number(inverse_delta, 8),
        "armature_modifiers": [
            {
                "name": modifier.name,
                "target": modifier.object.name if modifier.object else None,
                "use_vertex_groups": bool(modifier.use_vertex_groups),
                "use_bone_envelopes": bool(modifier.use_bone_envelopes),
                "use_deform_preserve_volume": bool(
                    modifier.use_deform_preserve_volume
                ),
            }
            for modifier in modifiers
        ],
    }


def audit_rest_orientation(canonical, fitted, contract, analysis=None):
    """Compare proportional fit direction separately from roll-axis residual."""

    records = []
    blocking = []
    risks = []
    source_records = {
        item["name"]: item
        for item in contract.get("source_bones", contract.get("bones", []))
    }
    for production in contract.get("bones", []):
        name = production["name"]
        source = canonical.data.bones.get(name)
        target = fitted.data.bones.get(name)
        if source is None or target is None:
            blocking.append(name)
            records.append({"bone": name, "classification": "BLOCKING_MISSING_BONE"})
            continue
        source_direction = source.tail_local - source.head_local
        target_direction = target.tail_local - target.head_local
        fit_rotation = source_direction.rotation_difference(target_direction)
        source_x = source.matrix_local.to_3x3().col[0]
        source_z = source.matrix_local.to_3x3().col[2]
        target_x = target.matrix_local.to_3x3().col[0]
        target_z = target.matrix_local.to_3x3().col[2]
        roll_residual = max(
            _angle(fit_rotation @ source_x, target_x),
            _angle(fit_rotation @ source_z, target_z),
        )
        direction_delta = _angle(source_direction, target_direction)
        matrix_delta = _matrix_delta(source.matrix_local, target.matrix_local)
        source_record = source_records.get(name, {})
        parent = target.parent.name if target.parent else None
        parent_mismatch = parent != production.get("parent")
        metadata_mismatch = any(
            (
                bool(target.use_deform) != bool(production.get("deform")),
                bool(target.use_connect) != bool(production.get("connected")),
                target.inherit_scale
                != source_record.get("inherit_scale", target.inherit_scale),
                bool(target.use_local_location)
                != bool(
                    source_record.get(
                        "use_local_location", target.use_local_location
                    )
                ),
                bool(target.use_relative_parent)
                != bool(
                    source_record.get(
                        "use_relative_parent", target.use_relative_parent
                    )
                ),
            )
        )
        if parent_mismatch or roll_residual > 5.0:
            classification = "BLOCKING_REST_ORIENTATION_MISMATCH"
            blocking.append(name)
        elif metadata_mismatch or roll_residual > 2.0:
            classification = "ACTION_COMPATIBILITY_RISK"
            risks.append(name)
        elif direction_delta > 0.01 or abs(target.length - source.length) > 1.0e-6:
            classification = "EXPECTED_PROPORTIONAL_FITTING"
        else:
            classification = "HARMLESS_METADATA_DIFFERENCE"
        records.append(
            {
                "bone": name,
                "parent": parent,
                "expected_parent": production.get("parent"),
                "deform": bool(target.use_deform),
                "connected": bool(target.use_connect),
                "head": _vector(target.head_local),
                "tail": _vector(target.tail_local),
                "length": _number(target.length),
                "source_length": _number(source.length),
                "length_ratio": _number(
                    target.length / max(source.length, 1.0e-8)
                ),
                "direction_angle_degrees": _number(direction_delta),
                "roll_axis_residual_degrees": _number(roll_residual),
                "matrix_max_abs_delta": _number(matrix_delta, 8),
                "matrix_local": _matrix(target.matrix_local),
                "local_axes": {
                    "x": _vector(target_x),
                    "y": _vector(target.matrix_local.to_3x3().col[1]),
                    "z": _vector(target_z),
                },
                "inherit_scale": target.inherit_scale,
                "use_local_location": bool(target.use_local_location),
                "use_relative_parent": bool(target.use_relative_parent),
                "constraint_count": len(fitted.pose.bones[name].constraints),
                "custom_properties": {
                    key: str(target[key]) for key in sorted(target.keys())
                },
                "classification": classification,
            }
        )
    left_right = []
    if analysis:
        lateral = Vector(analysis["lateral_axis_world"])
        for base in ("shoulder", "arm", "leg"):
            left_name = (
                "shoulder_left" if base == "shoulder" else f"{base}_left_top"
            )
            right_name = (
                "shoulder_right" if base == "shoulder" else f"{base}_right_top"
            )
            left = fitted.data.bones.get(left_name)
            right = fitted.data.bones.get(right_name)
            if left and right and (left.head_local - right.head_local).dot(lateral) <= 0:
                left_right.append(base)
    if left_right:
        blocking.extend(f"left_right:{name}" for name in left_right)
    return {
        "status": "READY_FOR_ANIMATION_TEST" if not blocking else "NEEDS_REBIND",
        "compatible": not blocking,
        "blocking_bones": sorted(blocking),
        "action_compatibility_risks": sorted(risks),
        "left_right_inversion": left_right,
        "bones": records,
    }
