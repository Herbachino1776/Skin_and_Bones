"""Transactional deterministic production weighting for fragmented SPAR3D meshes."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import heapq
import json
import math

import bmesh
import bpy
from mathutils import Vector, geometry
from mathutils.bvhtree import BVHTree
import numpy as np

from ..constants import (
    RIG_ARMATURE_MODIFIER,
    RIG_DONOR_OBJECT,
    RIG_OWNER_PROPERTY,
    RIG_PROXY_OBJECT,
    RIG_TEMP_COLLECTION,
    RIG_WEIGHT_REPORT_PROPERTY,
)
from .analysis import topology_snapshot
from .fitting import OWNER


WEIGHT_TOLERANCE = 1.0e-4
DEFAULT_WEIGHT_THRESHOLD = 1.0e-4
DEFAULT_INFLUENCE_LIMIT = 4
TRANSFER_METHOD = "NEAREST_DONOR_FACE_BARYCENTRIC"
FALLBACK_METHOD = "NEAREST_FITTED_BONE_SEGMENT_INVERSE_DISTANCE"
SPATIAL_BONE_MARGIN_RATIO = 0.04
SIDE_CENTER_TOLERANCE_RATIO = 0.02
CONTINUITY_SMOOTHING_ITERATIONS = 128
CONTINUITY_SMOOTHING_FACTOR = 0.65
MAX_FALLBACK_HIERARCHY_STEPS = 3
VOXEL_HEAT_RESOLUTION = 224
VOXEL_HEAT_SMOOTHING_ITERATIONS = 16
VOXEL_HEAT_SMOOTHING_FACTOR = 0.5
VOXEL_HEAT_INTERMEDIATE_INFLUENCES = 8
VOXEL_HEAT_NOISE_THRESHOLD = 0.002
VOXEL_HEAT_MAX_RIGID_COMPONENT_VERTICES = 64
NON_SURFACE_DEFORM_BONES = frozenset({"root"})

PRODUCTION_BONE_PARENTS = {
    "root": None,
    "body": "root",
    "body_top0": "body",
    "body_top1": "body_top0",
    "body_top2": "body_top1",
    "neck": "body_top2",
    "head": "neck",
    "shoulder_left": "body_top2",
    "shoulder_right": "body_top2",
    "arm_left_top": "shoulder_left",
    "arm_right_top": "shoulder_right",
    "arm_left_bot": "arm_left_top",
    "arm_right_bot": "arm_right_top",
    "arm_left_hand": "arm_left_bot",
    "arm_right_hand": "arm_right_bot",
    "leg_left_top": "body",
    "leg_right_top": "body",
    "leg_left_bot": "leg_left_top",
    "leg_right_bot": "leg_right_top",
    "leg_left_foot": "leg_left_bot",
    "leg_right_foot": "leg_right_bot",
}


def _is_owned_armature_modifier(modifier):
    return (
        modifier.type == "ARMATURE"
        and modifier.name == RIG_ARMATURE_MODIFIER
    )


def _temp_collection(scene):
    collection = bpy.data.collections.get(RIG_TEMP_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(RIG_TEMP_COLLECTION)
        scene.collection.children.link(collection)
    elif collection.get(RIG_OWNER_PROPERTY) != OWNER:
        raise RuntimeError(f"Temporary collection '{RIG_TEMP_COLLECTION}' is unowned.")
    collection[RIG_OWNER_PROPERTY] = OWNER
    return collection


def clean_weighting_temporary_data():
    removed = []
    collection = bpy.data.collections.get(RIG_TEMP_COLLECTION)
    if collection is None:
        return removed
    if collection.get(RIG_OWNER_PROPERTY) != OWNER:
        raise RuntimeError(f"Refusing to clean unowned '{RIG_TEMP_COLLECTION}'.")
    for obj in list(collection.objects):
        if obj.get(RIG_OWNER_PROPERTY) != OWNER:
            raise RuntimeError(f"Temporary collection contains unowned object {obj.name}.")
        data = obj.data
        name = obj.name
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
        removed.append(name)
    bpy.data.collections.remove(collection)
    return removed


def _reference_mesh(source_armature, contract):
    for record in contract.get("reference_meshes", []):
        obj = bpy.data.objects.get(record.get("object", ""))
        if obj is not None and obj.type == "MESH":
            return obj
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        if any(
            modifier.type == "ARMATURE" and modifier.object == source_armature
            for modifier in obj.modifiers
        ):
            return obj
    raise RuntimeError("Canonical contract has no available skinned reference mesh.")


def _vertex_group_weights(obj, deform_names):
    index_to_name = {
        group.index: group.name
        for group in obj.vertex_groups
        if group.name in deform_names
    }
    result = []
    for vertex in obj.data.vertices:
        weights = {
            index_to_name[item.group]: float(item.weight)
            for item in vertex.groups
            if item.group in index_to_name and item.weight > 0.0
        }
        total = sum(weights.values())
        if total > 0.0:
            weights = {name: value / total for name, value in weights.items()}
        result.append(weights)
    return result


def create_aligned_donor(
    context,
    source_armature,
    fitted_armature,
    contract,
):
    """Create an owned donor by rest-space LBS from canonical to fitted bones."""

    source = _reference_mesh(source_armature, contract)
    source_deform_names = {
        bone.name for bone in source_armature.data.bones if bone.use_deform
    }
    source_weights = _vertex_group_weights(source, source_deform_names)
    production_names = {
        bone["name"] for bone in contract["bones"] if bone["deform"]
    }
    removed_to_hand = contract.get("removed_to_hand", {})
    merged_weights = []
    merge_report = {
        side: {
            "retained_hand_bone": f"arm_{side}_hand",
            "vertices_merged": 0,
            "summed_weight": 0.0,
            "removed_groups": sorted(
                name
                for name, hand in removed_to_hand.items()
                if hand == f"arm_{side}_hand"
            ),
        }
        for side in ("left", "right")
    }
    for weights in source_weights:
        simplified = defaultdict(float)
        merged_sides = set()
        for name, value in weights.items():
            destination = removed_to_hand.get(name, name)
            if destination not in production_names:
                continue
            simplified[destination] += value
            if name in removed_to_hand:
                side = "left" if destination == "arm_left_hand" else "right"
                merge_report[side]["summed_weight"] += value
                merged_sides.add(side)
        for side in merged_sides:
            merge_report[side]["vertices_merged"] += 1
        total = sum(simplified.values())
        merged_weights.append(
            {
                name: value / total
                for name, value in simplified.items()
            }
            if total > 0.0
            else {}
        )
    mesh = source.data.copy()
    mesh.name = f"{RIG_DONOR_OBJECT}_Mesh"
    donor = source.copy()
    donor.data = mesh
    donor.name = RIG_DONOR_OBJECT
    donor.parent = None
    donor.matrix_world.identity()
    donor.animation_data_clear()
    for modifier in list(donor.modifiers):
        donor.modifiers.remove(modifier)
    donor.data.materials.clear()
    donor[RIG_OWNER_PROPERTY] = OWNER
    donor["sbf_weight_donor"] = True
    donor["sbf_donor_source"] = source.name
    donor["sbf_production_profile"] = contract.get("profile_id", "")
    donor["sbf_removed_finger_group_count"] = len(removed_to_hand)
    _temp_collection(context.scene).objects.link(donor)
    donor.vertex_groups.clear()
    donor_groups = {
        name: donor.vertex_groups.new(name=name)
        for name in sorted(production_names)
    }
    for index, values in enumerate(merged_weights):
        for name, value in values.items():
            donor_groups[name].add([index], float(value), "REPLACE")

    source_bone_matrices = {
        bone.name: source_armature.matrix_world @ bone.matrix_local
        for bone in source_armature.data.bones
        if bone.name in production_names
    }
    fitted_bone_matrices = {
        bone.name: fitted_armature.matrix_world @ bone.matrix_local
        for bone in fitted_armature.data.bones
        if bone.name in production_names
    }
    transforms = {
        name: fitted_bone_matrices[name] @ source_bone_matrices[name].inverted_safe()
        for name in production_names
        if name in fitted_bone_matrices
    }
    for vertex, weights in zip(mesh.vertices, merged_weights):
        world = source.matrix_world @ source.data.vertices[vertex.index].co
        if not weights:
            vertex.co = world
            continue
        fitted = Vector((0.0, 0.0, 0.0))
        total = 0.0
        for name, weight in weights.items():
            transform = transforms.get(name)
            if transform is None:
                continue
            fitted += (transform @ world) * weight
            total += weight
        vertex.co = fitted / total if total > 0.0 else world
    mesh.update()
    for values in merge_report.values():
        values["summed_weight"] = round(values["summed_weight"], 6)
    return donor, merged_weights, merge_report


def create_fallback_proxy(context, fitted_armature):
    vertices = []
    edges = []
    bone_names = []
    for bone in fitted_armature.data.bones:
        if not bone.use_deform:
            continue
        start = len(vertices)
        vertices.extend(
            (
                fitted_armature.matrix_world @ bone.head_local,
                fitted_armature.matrix_world @ bone.tail_local,
            )
        )
        edges.append((start, start + 1))
        bone_names.append(bone.name)
    mesh = bpy.data.meshes.new(f"{RIG_PROXY_OBJECT}_Mesh")
    mesh.from_pydata(vertices, edges, [])
    proxy = bpy.data.objects.new(RIG_PROXY_OBJECT, mesh)
    proxy[RIG_OWNER_PROPERTY] = OWNER
    proxy["sbf_weight_proxy"] = True
    proxy["sbf_proxy_bones"] = json.dumps(bone_names)
    _temp_collection(context.scene).objects.link(proxy)
    for edge_index, name in enumerate(bone_names):
        group = proxy.vertex_groups.new(name=name)
        group.add(
            [edge_index * 2, edge_index * 2 + 1],
            1.0,
            "REPLACE",
        )
    return proxy


def _repairable_unweighted_components(mesh, weights, max_vertices):
    unweighted = {
        index for index, assignments in enumerate(weights) if not assignments
    }
    return [
        component
        for component in _component_indices(mesh)
        if len(component) <= int(max_vertices)
        and all(index in unweighted for index in component)
    ]


def _repair_small_unweighted_proxy_components(
    proxy,
    fitted_armature,
    deform_names,
    weights,
):
    """Rigidly bind only tiny proxy islands that bone heat cannot reach."""

    repairable = _repairable_unweighted_components(
        proxy.data,
        weights,
        VOXEL_HEAT_MAX_RIGID_COMPONENT_VERTICES,
    )
    allowed_names = set(deform_names) - NON_SURFACE_DEFORM_BONES
    segments = {
        bone.name: (
            fitted_armature.matrix_world @ bone.head_local,
            fitted_armature.matrix_world @ bone.tail_local,
        )
        for bone in fitted_armature.data.bones
        if bone.use_deform and bone.name in allowed_names
    }
    repairs = []
    for component in repairable:
        world_centroid = Vector((0.0, 0.0, 0.0))
        for index in component:
            world_centroid += proxy.matrix_world @ proxy.data.vertices[index].co
        world_centroid /= len(component)
        distance, bone_name = min(
            (
                _point_segment_distance(world_centroid, head, tail),
                name,
            )
            for name, (head, tail) in segments.items()
        )
        group = proxy.vertex_groups.get(bone_name)
        if group is None:
            group = proxy.vertex_groups.new(name=bone_name)
        group.add(component, 1.0, "REPLACE")
        repairs.append(
            {
                "method": "RIGID_NEAREST_FITTED_BONE_SEGMENT",
                "bone": bone_name,
                "distance": round(float(distance), 6),
                "vertex_count": len(component),
            }
        )
    return _vertex_group_weights(proxy, set(deform_names)), repairs


def create_voxel_heat_proxy(
    context,
    target,
    fitted_armature,
    deform_names,
    target_height,
    resolution=VOXEL_HEAT_RESOLUTION,
):
    """Create and bone-heat a temporary watertight copy of the target surface."""

    source_mesh = target.data.copy()
    source_mesh.transform(target.matrix_world)
    proxy = bpy.data.objects.new(RIG_PROXY_OBJECT, source_mesh)
    proxy[RIG_OWNER_PROPERTY] = OWNER
    proxy["sbf_weight_proxy"] = True
    proxy["sbf_proxy_kind"] = "VOXEL_HEAT_SURFACE"
    _temp_collection(context.scene).objects.link(proxy)
    proxy.matrix_world.identity()
    proxy.vertex_groups.clear()
    for modifier in list(proxy.modifiers):
        proxy.modifiers.remove(modifier)

    remesh = proxy.modifiers.new("SBF_VoxelHeatSurface", "REMESH")
    remesh.mode = "VOXEL"
    voxel_size = float(target_height) / max(int(resolution), 32)
    remesh.voxel_size = voxel_size
    remesh.use_remove_disconnected = False
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = proxy.evaluated_get(depsgraph)
    remeshed = bpy.data.meshes.new_from_object(evaluated, depsgraph=depsgraph)
    proxy.modifiers.clear()
    proxy.data = remeshed
    if source_mesh.users == 0:
        bpy.data.meshes.remove(source_mesh)

    bm = bmesh.new()
    try:
        bm.from_mesh(remeshed)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.to_mesh(remeshed)
    finally:
        bm.free()
    remeshed.update()
    if not remeshed.vertices or not remeshed.polygons:
        raise RuntimeError("Voxel heat proxy generation produced no surface geometry.")

    if context.object is not None and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    fitted_armature.select_set(True)
    context.view_layer.objects.active = fitted_armature
    result = bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    if "FINISHED" not in result:
        raise RuntimeError("Blender automatic weights failed on the voxel heat proxy.")
    weights = _vertex_group_weights(proxy, set(deform_names))
    bone_heat_unweighted_vertices = sum(not values for values in weights)
    weights, component_repairs = _repair_small_unweighted_proxy_components(
        proxy,
        fitted_armature,
        deform_names,
        weights,
    )
    empty_vertices = sum(not values for values in weights)
    if empty_vertices:
        raise RuntimeError(
            "Blender bone heat left "
            f"{empty_vertices} voxel proxy vertices unweighted after repairing "
            f"{sum(item['vertex_count'] for item in component_repairs)} vertices "
            "on small isolated components."
        )
    missing_groups = sorted(
        name
        for name in deform_names
        if proxy.vertex_groups.get(name) is None
    )
    if missing_groups:
        raise RuntimeError(
            "Voxel heat proxy is missing deform groups: " + ", ".join(missing_groups)
        )
    return proxy, weights, {
        "method": "BLENDER_AUTOMATIC_WEIGHTS_ON_VOXEL_PROXY",
        "resolution": int(resolution),
        "voxel_size": voxel_size,
        "proxy_vertices": len(remeshed.vertices),
        "proxy_triangles": len(remeshed.polygons),
        "bone_heat_unweighted_vertices": bone_heat_unweighted_vertices,
        "rigid_proxy_component_repairs": component_repairs,
        "repaired_proxy_vertices": sum(
            item["vertex_count"] for item in component_repairs
        ),
        "empty_proxy_vertices": empty_vertices,
    }


def smooth_surface_weights(
    target,
    weights,
    iterations=VOXEL_HEAT_SMOOTHING_ITERATIONS,
    factor=VOXEL_HEAT_SMOOTHING_FACTOR,
    intermediate_limit=VOXEL_HEAT_INTERMEDIATE_INFLUENCES,
):
    """Diffuse transferred weights only across real production mesh edges."""

    adjacency = [[] for _vertex in target.data.vertices]
    for edge in target.data.edges:
        first, second = map(int, edge.vertices)
        adjacency[first].append(second)
        adjacency[second].append(first)
    current = [dict(values) for values in weights]
    blend = min(max(float(factor), 0.0), 1.0)
    for _iteration in range(max(int(iterations), 0)):
        updated = []
        for index, values in enumerate(current):
            neighbors = adjacency[index]
            if not neighbors:
                updated.append(dict(values))
                continue
            combined = defaultdict(float)
            for name, value in values.items():
                combined[name] += value * (1.0 - blend)
            neighbor_factor = blend / len(neighbors)
            for neighbor in neighbors:
                for name, value in current[neighbor].items():
                    combined[name] += value * neighbor_factor
            ranked = sorted(
                (
                    (name, value)
                    for name, value in combined.items()
                    if math.isfinite(value) and value >= 1.0e-6
                ),
                key=lambda item: (-item[1], item[0]),
            )[: max(int(intermediate_limit), 1)]
            total = math.fsum(value for _name, value in ranked)
            updated.append(
                {name: value / total for name, value in ranked}
                if total > 0.0
                else {}
            )
        current = updated
    return current


def enforce_anatomical_sides(target, analysis, weights):
    """Remove cross-body influences away from the anatomical centerline."""

    corrected = []
    removed_influences = 0
    corrected_vertices = 0
    for vertex, values in zip(target.data.vertices, weights):
        world = target.matrix_world @ vertex.co
        lateral = Vector(analysis["lateral_axis_world"])
        center = Vector(analysis["centerline_world"])
        height = float(analysis["world_height"])
        offset = (world - center).dot(lateral)
        point_side = (
            "CENTER"
            if abs(offset) <= height * SIDE_CENTER_TOLERANCE_RATIO
            else "LEFT"
            if offset > 0.0
            else "RIGHT"
        )
        if point_side == "CENTER":
            corrected.append(dict(values))
            continue
        retained = {
            name: value
            for name, value in values.items()
            if _bone_side(name) in {"CENTER", point_side}
        }
        removed = len(values) - len(retained)
        if removed:
            removed_influences += removed
            corrected_vertices += 1
        total = math.fsum(retained.values())
        corrected.append(
            {name: value / total for name, value in retained.items()}
            if total > 0.0
            else dict(values)
        )
    return corrected, {
        "anatomical_side_corrected_vertices": corrected_vertices,
        "anatomical_side_removed_influences": removed_influences,
    }


def attenuate_remote_limb_weights(
    target,
    fitted,
    analysis,
    weights,
    spatial_data=None,
):
    """Taper arm influence out of lower leg branches without a hard seam."""

    spatial_data = spatial_data or _spatial_weighting_data(
        target, fitted, analysis
    )
    points = spatial_data["points"]
    preferred_families = spatial_data["preferred_families"]
    branch_corrections = spatial_data["branch_corrections"]
    corrected = []
    corrected_vertices = 0
    removed_influences = 0
    up = Vector(analysis["up_axis_world"])
    ground = float(analysis["ground"])
    height = float(analysis["world_height"])
    for index, values in enumerate(weights):
        preferred = preferred_families[index]
        fraction = (points[index].dot(up) - ground) / max(height, 1.0e-8)
        transition = min(max((fraction - 0.46) / 0.16, 0.0), 1.0)
        arm_factor = transition * transition * (3.0 - 2.0 * transition)
        retained = dict(values)
        vertex_corrected = False
        if preferred.endswith("_LEG") and arm_factor < 1.0:
            for name in list(retained):
                if _bone_family(name).endswith("_ARM"):
                    original = retained[name]
                    retained[name] *= arm_factor
                    if retained[name] < 1.0e-6:
                        del retained[name]
                        removed_influences += 1
                    if retained.get(name, 0.0) != original:
                        vertex_corrected = True
        if vertex_corrected:
            corrected_vertices += 1
        total = math.fsum(retained.values())
        if total <= 0.0:
            retained = dict(values)
            total = math.fsum(retained.values())
        corrected.append(
            {name: value / total for name, value in retained.items()}
        )
    return corrected, {
        "remote_limb_tapered_vertices": corrected_vertices,
        "remote_limb_zeroed_influences": removed_influences,
        "topology_branch_label_corrections": branch_corrections,
    }


def remove_spatially_impossible_weights(
    target,
    fitted,
    analysis,
    weights,
    components,
    membership,
    influence_limit,
    spatial_data=None,
):
    """Remove exactly the influences that production validation would reject."""

    spatial_data = spatial_data or _spatial_weighting_data(
        target, fitted, analysis
    )
    points = spatial_data["points"]
    segments = spatial_data["segments"]
    contexts = spatial_data["contexts"]
    height = float(analysis["world_height"])
    preferred_families = spatial_data["preferred_families"]
    cleaned = []
    corrected_vertices = 0
    removed_influences = 0
    fallback_vertices = 0
    for index, values in enumerate(weights):
        component = components[membership[index]]
        tiny = component["classification"] == "TINY_FLOATING_FRAGMENT"
        side, distances, nearest = contexts[index]
        retained = {}
        for name, value in values.items():
            strict_plausible = _spatially_plausible(
                name,
                side,
                distances,
                nearest,
                height,
                max_hierarchy_steps=(None if tiny else MAX_FALLBACK_HIERARCHY_STEPS),
                preferred_family=(None if tiny else preferred_families[index]),
            )
            bridge_plausible = _spatially_plausible(
                name,
                side,
                distances,
                nearest,
                height,
                max_hierarchy_steps=None,
                margin_ratio=0.14,
            )
            if strict_plausible or bridge_plausible:
                retained[name] = value
            else:
                removed_influences += 1
        if len(retained) != len(values):
            corrected_vertices += 1
        if not retained:
            retained = _spatial_fallback_weights(
                points[index],
                analysis,
                segments,
                influence_limit,
                rigid=tiny,
                preferred_family=(None if tiny else preferred_families[index]),
            )
            fallback_vertices += 1
        total = math.fsum(retained.values())
        cleaned.append(
            {name: value / total for name, value in retained.items()}
        )
    return cleaned, {
        "spatial_validation_corrected_vertices": corrected_vertices,
        "spatial_validation_removed_influences": removed_influences,
        "spatial_validation_fallback_vertices": fallback_vertices,
    }


def _barycentric_weights(point, triangle):
    a, b, c = triangle
    result = geometry.barycentric_transform(
        point,
        a,
        b,
        c,
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    )
    values = [max(0.0, float(value)) for value in result]
    total = sum(values)
    if total <= 1.0e-12:
        return (1.0, 0.0, 0.0)
    return tuple(value / total for value in values)


def transfer_donor_weights(target, donor, donor_weights, target_height):
    donor_points = [donor.matrix_world @ vertex.co for vertex in donor.data.vertices]
    polygons = [tuple(polygon.vertices) for polygon in donor.data.polygons]
    bvh = BVHTree.FromPolygons(donor_points, polygons, all_triangles=True)
    weights = []
    distances = []
    confidences = []
    for vertex in target.data.vertices:
        world = target.matrix_world @ vertex.co
        location, _normal, polygon_index, distance = bvh.find_nearest(world)
        if location is None or polygon_index is None:
            weights.append({})
            distances.append(float("inf"))
            confidences.append(0.0)
            continue
        polygon = polygons[polygon_index]
        if len(polygon) < 3:
            weights.append({})
            distances.append(float(distance))
            confidences.append(0.0)
            continue
        indices = polygon[:3]
        barycentric = _barycentric_weights(
            location, [donor_points[index] for index in indices]
        )
        combined = defaultdict(float)
        for index, blend in zip(indices, barycentric):
            for name, weight in donor_weights[index].items():
                combined[name] += weight * blend
        total = sum(combined.values())
        weights.append(
            {name: value / total for name, value in combined.items()}
            if total > 0.0
            else {}
        )
        distances.append(float(distance))
        confidences.append(
            max(0.0, 1.0 - float(distance) / max(target_height * 0.12, 1.0e-8))
        )
    return weights, distances, confidences, bvh


def _component_indices(mesh):
    parent = list(range(len(mesh.vertices)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for edge in mesh.edges:
        first, second = map(int, edge.vertices)
        a, b = root(first), root(second)
        if a != b:
            parent[b] = a
    components = defaultdict(list)
    for index in range(len(parent)):
        components[root(index)].append(index)
    return sorted(components.values(), key=lambda values: (-len(values), values[0]))


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


def _point_anatomy(point, analysis):
    up = Vector(analysis["up_axis_world"])
    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    height = float(analysis["world_height"])
    ground = float(analysis["ground"])
    lateral_offset = (point - center).dot(lateral)
    return (
        _region_for(
            (point.dot(up) - ground) / max(height, 1.0e-8),
            abs(lateral_offset) / max(height, 1.0e-8),
        ),
        (
            "CENTER"
            if abs(lateral_offset) <= height * 0.01
            else "LEFT"
            if lateral_offset > 0.0
            else "RIGHT"
        ),
    )


def classify_components(target, analysis, raw_weights, distances):
    points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    up = Vector(analysis["up_axis_world"])
    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    height = float(analysis["world_height"])
    ground = float(analysis["ground"])
    records = []
    membership = {}
    for component_id, indices in enumerate(_component_indices(target.data)):
        component_points = [points[index] for index in indices]
        minimum = Vector(
            min(point[axis] for point in component_points) for axis in range(3)
        )
        maximum = Vector(
            max(point[axis] for point in component_points) for axis in range(3)
        )
        centroid = sum(component_points, Vector()) / len(component_points)
        height_fraction = (centroid.dot(up) - ground) / max(height, 1.0e-8)
        lateral_values = [(point - center).dot(lateral) for point in component_points]
        lateral_fraction = abs((centroid - center).dot(lateral)) / max(height, 1.0e-8)
        side = (
            "CENTER"
            if min(lateral_values) <= 0.0 <= max(lateral_values)
            else "LEFT"
            if sum(lateral_values) > 0.0
            else "RIGHT"
        )
        region = _region_for(height_fraction, lateral_fraction)
        aggregates = defaultdict(float)
        for index in indices:
            for name, value in raw_weights[index].items():
                aggregates[name] += value
        dominant = sorted(
            aggregates.items(), key=lambda item: (-item[1], item[0])
        )[:4]
        finite_distances = [distances[index] for index in indices if math.isfinite(distances[index])]
        mean_distance = (
            sum(finite_distances) / len(finite_distances)
            if finite_distances
            else float("inf")
        )
        if len(indices) <= 8:
            label = "TINY_FLOATING_FRAGMENT"
            confidence = 0.82
        elif region == "HAND":
            label = "HAND_DETAIL"
            confidence = 0.78
        elif region == "FOOT":
            label = "FOOT_DETAIL"
            confidence = 0.78
        elif region == "HEAD" and mean_distance > height * 0.015:
            label = "HAIR_OR_HEAD_ACCESSORY"
            confidence = 0.68
        elif mean_distance > height * 0.035:
            label = "ACCESSORY"
            confidence = 0.58
        elif mean_distance > height * 0.01:
            label = "CLOTHING"
            confidence = 0.62
        else:
            label = "BODY"
            confidence = 0.86
        record = {
            "component": component_id,
            "vertex_count": len(indices),
            "bounds": {
                "minimum": [round(float(value), 6) for value in minimum],
                "maximum": [round(float(value), 6) for value in maximum],
            },
            "centroid": [round(float(value), 6) for value in centroid],
            "nearest_body_region": region,
            "side": side,
            "crosses_centerline": side == "CENTER",
            "dominant_donor_bones": [
                {"bone": name, "weight": round(value / len(indices), 6)}
                for name, value in dominant
            ],
            "mean_donor_distance": (
                round(mean_distance, 6) if math.isfinite(mean_distance) else None
            ),
            "classification": label,
            "classification_confidence": confidence,
        }
        records.append(record)
        for index in indices:
            membership[index] = component_id
    return records, membership


def _bone_side(name):
    if "_left" in name:
        return "LEFT"
    if "_right" in name:
        return "RIGHT"
    return "CENTER"


def _bone_family(name):
    if name.startswith(("shoulder_left", "arm_left_")):
        return "LEFT_ARM"
    if name.startswith(("shoulder_right", "arm_right_")):
        return "RIGHT_ARM"
    if name.startswith("leg_left_"):
        return "LEFT_LEG"
    if name.startswith("leg_right_"):
        return "RIGHT_LEG"
    return "AXIAL"


def _region_allowed(name, region, side):
    bone_side = _bone_side(name)
    if side != "CENTER" and bone_side not in {"CENTER", side}:
        return False
    if region == "HEAD":
        return name in {"body_top1", "body_top2", "neck", "head"}
    if region == "HAND":
        if side == "CENTER":
            return name in {"arm_left_hand", "arm_right_hand"}
        return name == f"arm_{side.lower()}_hand"
    if region == "FOOT":
        token = side.lower() if side != "CENTER" else ""
        return name.startswith("leg_") and (not token or f"_{token}_" in name)
    if region == "ARM":
        return name.startswith(("shoulder_", "arm_"))
    if region == "LEG":
        return name.startswith("leg_") or name in {"body", "root"}
    return name in {
        "root",
        "body",
        "body_top0",
        "body_top1",
        "body_top2",
        "neck",
        "head",
    }


def _point_segment_distance(point, head, tail):
    direction = tail - head
    denominator = direction.length_squared
    if denominator <= 1.0e-12:
        return (point - head).length
    factor = max(0.0, min(1.0, (point - head).dot(direction) / denominator))
    return (point - head.lerp(tail, factor)).length


def _bone_segments(fitted):
    return {
        bone.name: (
            fitted.matrix_world @ bone.head_local,
            fitted.matrix_world @ bone.tail_local,
        )
        for bone in fitted.data.bones
        if bone.use_deform
    }


def _spatial_context(point, analysis, segments):
    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    height = float(analysis["world_height"])
    lateral_offset = (point - center).dot(lateral)
    side = (
        "CENTER"
        if abs(lateral_offset) <= height * SIDE_CENTER_TOLERANCE_RATIO
        else "LEFT"
        if lateral_offset > 0.0
        else "RIGHT"
    )
    distances = {
        name: _point_segment_distance(point, head, tail)
        for name, (head, tail) in segments.items()
    }
    nearest = min(distances.values(), default=float("inf"))
    return side, distances, nearest


def _topology_preferred_families(target, points, segments, contexts=None):
    """Partition touching limbs by geodesic distance from confident bone seeds."""

    adjacency = [[] for _vertex in target.data.vertices]
    for edge in target.data.edges:
        first, second = map(int, edge.vertices)
        length = (points[second] - points[first]).length
        adjacency[first].append((second, length))
        adjacency[second].append((first, length))
    height = max(point.z for point in points) - min(point.z for point in points)
    initial = []
    seeds = []
    for index, point in enumerate(points):
        by_family = defaultdict(lambda: float("inf"))
        if contexts is None:
            distances = {
                name: _point_segment_distance(point, head, tail)
                for name, (head, tail) in segments.items()
            }
        else:
            distances = contexts[index][1]
        for name, distance in distances.items():
            family = _bone_family(name)
            by_family[family] = min(by_family[family], distance)
        ranked = sorted(by_family.items(), key=lambda item: (item[1], item[0]))
        initial.append(ranked[0][0])
        seeds.append(
            ranked[0][0]
            if ranked[0][1] <= height * 0.055
            and ranked[1][1] - ranked[0][1] >= height * 0.012
            else None
        )
    best_distance = [float("inf")] * len(points)
    labels = [None] * len(points)
    queue = []
    for index, label in enumerate(seeds):
        if label is not None:
            heapq.heappush(queue, (0.0, label, index))
    while queue:
        distance, label, index = heapq.heappop(queue)
        if distance >= best_distance[index]:
            continue
        best_distance[index] = distance
        labels[index] = label
        for neighbor, length in adjacency[index]:
            candidate = distance + length
            if candidate < best_distance[neighbor]:
                heapq.heappush(queue, (candidate, label, neighbor))
    labels = [label or initial[index] for index, label in enumerate(labels)]
    return labels, sum(
        before != after for before, after in zip(initial, labels)
    )


def _spatial_weighting_data(target, fitted, analysis):
    """Build immutable world-space classification inputs once per bind."""

    points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    segments = _bone_segments(fitted)
    contexts = [
        _spatial_context(point, analysis, segments) for point in points
    ]
    preferred_families, branch_corrections = _topology_preferred_families(
        target,
        points,
        segments,
        contexts=contexts,
    )
    return {
        "points": points,
        "segments": segments,
        "contexts": contexts,
        "preferred_families": preferred_families,
        "branch_corrections": branch_corrections,
    }


@lru_cache(maxsize=None)
def _hierarchy_steps(first, second):
    if first == second:
        return 0
    neighbors = defaultdict(set)
    for child, parent in PRODUCTION_BONE_PARENTS.items():
        if parent is None:
            continue
        neighbors[child].add(parent)
        neighbors[parent].add(child)
    frontier = {first}
    visited = set()
    for steps in range(1, len(PRODUCTION_BONE_PARENTS) + 1):
        visited.update(frontier)
        frontier = {
            neighbor
            for name in frontier
            for neighbor in neighbors.get(name, ())
            if neighbor not in visited
        }
        if second in frontier:
            return steps
        if not frontier:
            break
    return len(PRODUCTION_BONE_PARENTS) + 1


def _family_reference_bone(distances, preferred_family):
    names = [
        name
        for name in distances
        if preferred_family is None or _bone_family(name) == preferred_family
    ]
    if not names:
        names = list(distances)
    return min(names, key=lambda name: (distances[name], name))


def _spatially_plausible(
    name,
    side,
    distances,
    nearest,
    height,
    max_hierarchy_steps=MAX_FALLBACK_HIERARCHY_STEPS,
    preferred_family=None,
    margin_ratio=SPATIAL_BONE_MARGIN_RATIO,
):
    bone_side = _bone_side(name)
    if side != "CENTER" and bone_side not in {"CENTER", side}:
        return False
    distance = distances.get(name, float("inf"))
    nearest_name = _family_reference_bone(distances, preferred_family)
    reference_distance = distances[nearest_name]
    candidate_family = _bone_family(name)
    family_compatible = (
        preferred_family is None
        or candidate_family == preferred_family
        or (
            "AXIAL" in {candidate_family, preferred_family}
            and _hierarchy_steps(nearest_name, name)
            <= MAX_FALLBACK_HIERARCHY_STEPS
        )
    )
    return (
        family_compatible
        and distance
        <= reference_distance + height * margin_ratio
        and (
            max_hierarchy_steps is None
            or _hierarchy_steps(nearest_name, name) <= max_hierarchy_steps
        )
    )


def _spatial_fallback_weights(
    point,
    analysis,
    segments,
    influence_limit,
    rigid=False,
    preferred_family=None,
):
    side, distances, nearest = _spatial_context(point, analysis, segments)
    height = float(analysis["world_height"])
    nearest_name = _family_reference_bone(distances, preferred_family)
    reference_distance = distances[nearest_name]
    candidates = [
        (distance, name)
        for name, distance in distances.items()
        if side == "CENTER" or _bone_side(name) in {"CENTER", side}
        if preferred_family is None
        or _bone_family(name) == preferred_family
        or (
            "AXIAL" in {_bone_family(name), preferred_family}
            and _hierarchy_steps(nearest_name, name)
            <= MAX_FALLBACK_HIERARCHY_STEPS
        )
    ]
    candidates = [
        item
        for item in candidates
        if item[0]
        <= reference_distance + height * SPATIAL_BONE_MARGIN_RATIO
        and _hierarchy_steps(nearest_name, item[1])
        <= MAX_FALLBACK_HIERARCHY_STEPS
    ]
    if not candidates:
        candidates = [
            (distance, name)
            for name, distance in distances.items()
            if preferred_family is None
            or _bone_family(name) == preferred_family
        ]
    if not candidates:
        candidates = [(distance, name) for name, distance in distances.items()]
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = candidates[: 1 if rigid else influence_limit]
    values = {
        name: 1.0 / max(distance, 0.002) ** 2 for distance, name in selected
    }
    total = sum(values.values())
    return {name: value / total for name, value in values.items()}


def _weight_edge_delta(first, second):
    return sum(
        abs(first.get(name, 0.0) - second.get(name, 0.0))
        for name in set(first).union(second)
    )


def _limit_and_normalize_rows(values, influence_limit):
    """Keep deterministic top influences in dense rows and normalize them."""

    source = np.asarray(values, dtype=np.float64)
    if source.ndim != 2:
        raise ValueError("Dense weight values must be a two-dimensional array.")
    if source.shape[0] == 0 or source.shape[1] == 0:
        return source.copy()
    limit = min(max(int(influence_limit), 1), source.shape[1])
    # Columns are ordered by bone name. Stable sorting therefore preserves the
    # existing (-weight, bone_name) tie break without a Python sort per row.
    ranked = np.argsort(-source, axis=1, kind="stable")[:, :limit]
    limited = np.zeros_like(source)
    ranked_values = np.take_along_axis(source, ranked, axis=1)
    np.put_along_axis(limited, ranked, ranked_values, axis=1)
    totals = np.sum(limited, axis=1)
    active = totals > 0.0
    limited[active] /= totals[active, None]
    return limited


def _accumulate_edge_values(values, edges, vertex_count):
    """Sum the opposite endpoint's dense values for every mesh vertex."""

    result = np.zeros((int(vertex_count), values.shape[1]), dtype=np.float64)
    if len(edges) == 0 or values.shape[1] == 0:
        return result
    destinations = np.concatenate((edges[:, 0], edges[:, 1]))
    sources = np.concatenate((edges[:, 1], edges[:, 0]))
    for column in range(values.shape[1]):
        result[:, column] = np.bincount(
            destinations,
            weights=values[sources, column],
            minlength=int(vertex_count),
        )
    return result


def _regularize_dense_weights(
    values,
    edges,
    palette_edges,
    smoothing_allowed,
    palette_allowed,
    tiny_vertices,
    influence_limit,
    smoothing_iterations,
    smoothing_factor,
    smoothing_threshold,
    palette_iterations,
    palette_edge_limit,
):
    """Run the existing synchronous smoothing and palette rules in batches."""

    current = np.asarray(values, dtype=np.float64).copy()
    edge_array = np.asarray(edges, dtype=np.int64).reshape((-1, 2))
    vertex_count = current.shape[0]
    degrees = np.bincount(
        edge_array.reshape(-1), minlength=vertex_count
    ).astype(np.float64) if len(edge_array) else np.zeros(vertex_count)
    smooth_vertices = (degrees > 0.0) & ~np.asarray(tiny_vertices, dtype=bool)
    blend = float(smoothing_factor)
    smoothing_executed = 0
    for _iteration in range(max(int(smoothing_iterations), 0)):
        neighbor_sums = _accumulate_edge_values(
            current, edge_array, vertex_count
        )
        candidates = current * (1.0 - blend)
        candidates[smooth_vertices] += (
            neighbor_sums[smooth_vertices]
            * (blend / degrees[smooth_vertices])[:, None]
        )
        candidates[~np.asarray(smoothing_allowed, dtype=bool)] = 0.0
        candidates[candidates < float(smoothing_threshold)] = 0.0
        totals = np.sum(candidates, axis=1)
        replace = smooth_vertices & (totals > 0.0)
        current[replace] = candidates[replace] / totals[replace, None]
        smoothing_executed += 1

    current = _limit_and_normalize_rows(current, influence_limit)
    palette_edges = np.asarray(palette_edges, dtype=np.int64).reshape((-1, 2))
    palette_executed = 0
    for _iteration in range(max(int(palette_iterations), 0)):
        if len(palette_edges) == 0:
            break
        deltas = np.sum(
            np.abs(
                current[palette_edges[:, 0]]
                - current[palette_edges[:, 1]]
            ),
            axis=1,
        )
        active_edges = palette_edges[deltas > float(palette_edge_limit)]
        if len(active_edges) == 0:
            break
        common = _limit_and_normalize_rows(
            (
                current[active_edges[:, 0]]
                + current[active_edges[:, 1]]
            )
            * 0.5,
            influence_limit,
        )
        proposal_sums = np.zeros_like(current)
        proposal_counts = np.bincount(
            active_edges.reshape(-1), minlength=vertex_count
        ).astype(np.float64)
        endpoints = np.concatenate(
            (active_edges[:, 0], active_edges[:, 1])
        )
        repeated_common = np.concatenate((common, common), axis=0)
        for column in range(current.shape[1]):
            proposal_sums[:, column] = np.bincount(
                endpoints,
                weights=repeated_common[:, column],
                minlength=vertex_count,
            )
        proposal_sums[~np.asarray(palette_allowed, dtype=bool)] = 0.0
        proposed_vertices = proposal_counts > 0.0
        combined = current[proposed_vertices] * 0.25
        combined += (
            proposal_sums[proposed_vertices]
            * (0.75 / proposal_counts[proposed_vertices])[:, None]
        )
        current[proposed_vertices] = _limit_and_normalize_rows(
            combined, influence_limit
        )
        palette_executed += 1
    return current, smoothing_executed, palette_executed


def _crosses_arm_leg_family(first_family, second_family):
    return (
        first_family.endswith("_ARM") and second_family.endswith("_LEG")
    ) or (
        first_family.endswith("_LEG") and second_family.endswith("_ARM")
    )


def _regularize_weight_continuity(
    target,
    fitted,
    analysis,
    weights,
    components,
    membership,
    preferred_families,
    influence_limit,
    spatial_data=None,
    smoothing_iterations=CONTINUITY_SMOOTHING_ITERATIONS,
    palette_iterations=48,
    palette_edge_limit=0.10,
):
    """Diffuse skin weights locally without crossing disconnected components."""

    edges = []
    for edge in target.data.edges:
        first, second = map(int, edge.vertices)
        edges.append((first, second))
    tiny_components = {
        record["component"]
        for record in components
        if record["classification"] == "TINY_FLOATING_FRAGMENT"
    }
    if spatial_data is None:
        points = [
            target.matrix_world @ vertex.co for vertex in target.data.vertices
        ]
        segments = _bone_segments(fitted)
        contexts = [
            _spatial_context(point, analysis, segments) for point in points
        ]
    else:
        points = spatial_data["points"]
        segments = spatial_data["segments"]
        contexts = spatial_data["contexts"]
    height = float(analysis["world_height"])
    up = Vector(analysis["up_axis_world"])
    ground = float(analysis["ground"])
    height_fractions = [
        (point.dot(up) - ground) / height for point in points
    ]
    bone_names = sorted(
        set(segments).union(
            name for values in weights for name in values
        )
    )
    bone_indices = {name: index for index, name in enumerate(bone_names)}
    dense = np.zeros((len(weights), len(bone_names)), dtype=np.float64)
    for vertex_index, values in enumerate(weights):
        for name, value in values.items():
            dense[vertex_index, bone_indices[name]] = float(value)

    smoothing_allowed = np.zeros(dense.shape, dtype=bool)
    palette_allowed = np.zeros(dense.shape, dtype=bool)
    bone_families = [_bone_family(name) for name in bone_names]
    for vertex_index, (side, distances, nearest) in enumerate(contexts):
        for bone_index, name in enumerate(bone_names):
            smoothing_allowed[vertex_index, bone_index] = _spatially_plausible(
                name,
                side,
                distances,
                nearest,
                height,
                max_hierarchy_steps=None,
            )
            crosses_lower_limb = (
                height_fractions[vertex_index] <= 0.50
                and _crosses_arm_leg_family(
                    preferred_families[vertex_index],
                    bone_families[bone_index],
                )
            )
            palette_allowed[vertex_index, bone_index] = (
                not crosses_lower_limb
                and (side == "CENTER" or _bone_side(name) in {"CENTER", side})
                and distances.get(name, float("inf"))
                <= nearest + height * 0.14
            )

    edge_array = np.asarray(edges, dtype=np.int64).reshape((-1, 2))
    if len(edge_array):
        before_maximum = float(
            np.max(
                np.sum(
                    np.abs(dense[edge_array[:, 0]] - dense[edge_array[:, 1]]),
                    axis=1,
                )
            )
        )
    else:
        before_maximum = 0.0
    palette_edges = [
        (first, second)
        for first, second in edges
        if not (
            min(height_fractions[first], height_fractions[second]) <= 0.50
            and _crosses_arm_leg_family(
                preferred_families[first], preferred_families[second]
            )
        )
    ]
    tiny_vertices = [
        membership[index] in tiny_components for index in range(len(weights))
    ]
    dense, smoothing_executed, palette_executed = _regularize_dense_weights(
        dense,
        edge_array,
        palette_edges,
        smoothing_allowed,
        palette_allowed,
        tiny_vertices,
        influence_limit,
        smoothing_iterations,
        CONTINUITY_SMOOTHING_FACTOR,
        DEFAULT_WEIGHT_THRESHOLD,
        palette_iterations,
        palette_edge_limit,
    )
    if len(edge_array):
        after_maximum = float(
            np.max(
                np.sum(
                    np.abs(dense[edge_array[:, 0]] - dense[edge_array[:, 1]]),
                    axis=1,
                )
            )
        )
    else:
        after_maximum = 0.0
    limited = [
        {
            name: float(value)
            for name, value in zip(bone_names, row, strict=True)
            if value > 0.0
        }
        for row in dense
    ]
    return limited, {
        "continuity_smoothing_iterations": int(smoothing_iterations),
        "continuity_smoothing_iterations_executed": smoothing_executed,
        "continuity_smoothing_factor": CONTINUITY_SMOOTHING_FACTOR,
        "maximum_edge_weight_delta_before": round(before_maximum, 6),
        "maximum_edge_weight_delta_after": round(after_maximum, 6),
        "palette_reconciliation_iterations": palette_iterations,
        "palette_reconciliation_iterations_executed": palette_executed,
        "palette_edge_delta_limit": palette_edge_limit,
    }


def _fallback_weights(
    point,
    fitted,
    region,
    side,
    influence_limit,
    rigid=False,
    proxy=None,
):
    candidates = []
    if proxy is not None:
        names = json.loads(proxy.get("sbf_proxy_bones", "[]"))
        for edge, name in zip(proxy.data.edges, names):
            if not _region_allowed(name, region, side):
                continue
            head = proxy.matrix_world @ proxy.data.vertices[edge.vertices[0]].co
            tail = proxy.matrix_world @ proxy.data.vertices[edge.vertices[1]].co
            candidates.append((_point_segment_distance(point, head, tail), name))
    else:
        for bone in fitted.data.bones:
            if not bone.use_deform or not _region_allowed(bone.name, region, side):
                continue
            head = fitted.matrix_world @ bone.head_local
            tail = fitted.matrix_world @ bone.tail_local
            distance = _point_segment_distance(point, head, tail)
            candidates.append((distance, bone.name))
    if not candidates:
        for bone in fitted.data.bones:
            if bone.use_deform:
                head = fitted.matrix_world @ bone.head_local
                tail = fitted.matrix_world @ bone.tail_local
                candidates.append((_point_segment_distance(point, head, tail), bone.name))
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = candidates[:1 if rigid else influence_limit]
    values = {
        name: 1.0 / max(distance, 0.002) ** 2 for distance, name in selected
    }
    total = sum(values.values())
    return {name: value / total for name, value in values.items()}


def remove_root_surface_weights(
    target,
    fitted,
    analysis,
    weights,
    influence_limit,
    preferred_families=None,
    spatial_data=None,
):
    """Keep the root bone for hierarchy while removing direct surface anchoring."""

    points = (
        spatial_data["points"]
        if spatial_data is not None
        else [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    )
    source_segments = (
        spatial_data["segments"]
        if spatial_data is not None
        else _bone_segments(fitted)
    )
    segments = {
        name: segment
        for name, segment in source_segments.items()
        if name not in NON_SURFACE_DEFORM_BONES
    }
    if preferred_families is None:
        preferred_families, _corrections = _topology_preferred_families(
            target, points, segments
        )
    cleaned = []
    affected_vertices = 0
    affected_indices = []
    fallback_vertices = 0
    removed_weight = 0.0
    for index, source_values in enumerate(weights):
        values = {
            name: float(value)
            for name, value in source_values.items()
            if name not in NON_SURFACE_DEFORM_BONES and value > 0.0
        }
        root_weight = sum(
            float(value)
            for name, value in source_values.items()
            if name in NON_SURFACE_DEFORM_BONES and value > 0.0
        )
        if root_weight > 0.0:
            affected_vertices += 1
            affected_indices.append(index)
            removed_weight += root_weight
            values["body"] = values.get("body", 0.0) + root_weight
        if not values:
            values = _spatial_fallback_weights(
                points[index],
                analysis,
                segments,
                influence_limit,
                preferred_family=preferred_families[index],
            )
            fallback_vertices += 1
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))[
            :influence_limit
        ]
        total = math.fsum(value for _name, value in ranked)
        cleaned.append({name: value / total for name, value in ranked})
    return cleaned, {
        "root_surface_vertices_cleared": affected_vertices,
        "root_surface_weight_removed": round(removed_weight, 6),
        "root_surface_fallback_vertices": fallback_vertices,
        "non_surface_deform_bones": sorted(NON_SURFACE_DEFORM_BONES),
        "_root_surface_successor_vertices": affected_indices,
    }


def stabilize_bilateral_leg_bridges(target, fitted, analysis, weights):
    """Keep center cloth/groin bridges from being torn by both thigh chains."""

    body = fitted.data.bones.get("body")
    left_hip = fitted.data.bones.get("leg_left_top")
    right_hip = fitted.data.bones.get("leg_right_top")
    if body is None or left_hip is None or right_hip is None:
        return weights, {
            "bilateral_leg_bridge_vertices": 0,
            "bilateral_leg_bridge_weight_moved": 0.0,
            "_bilateral_leg_bridge_vertex_indices": [],
        }
    height = float(analysis["world_height"])
    lateral = Vector(analysis["lateral_axis_world"]).normalized()
    up = Vector(analysis["up_axis_world"]).normalized()
    center = Vector(analysis["centerline_world"])
    ground = float(analysis["ground"])
    hip_height = (
        (fitted.matrix_world @ left_hip.head_local).dot(up)
        + (fitted.matrix_world @ right_hip.head_local).dot(up)
    ) * 0.5
    bridge_seeds = []
    for index, source_values in enumerate(weights):
        point = target.matrix_world @ target.data.vertices[index].co
        lateral_offset = abs((point - center).dot(lateral))
        point_height = point.dot(up)
        left_weight = math.fsum(
            value
            for name, value in source_values.items()
            if name.startswith("leg_left_")
        )
        right_weight = math.fsum(
            value
            for name, value in source_values.items()
            if name.startswith("leg_right_")
        )
        is_center_bridge = (
            lateral_offset <= height * 0.12
            and ground + height * 0.12 <= point_height <= hip_height + height * 0.03
            and min(left_weight, right_weight) >= 0.02
        )
        if is_center_bridge:
            bridge_seeds.append(index)

    # Feather the pelvis influence over neighboring topology.  A hard body/
    # thigh boundary merely moves the fan to the first edge outside the bridge.
    adjacency = [set() for _vertex in target.data.vertices]
    for edge in target.data.edges:
        first, second = map(int, edge.vertices)
        adjacency[first].add(second)
        adjacency[second].add(first)
    distance = {index: 0 for index in bridge_seeds}
    frontier = set(bridge_seeds)
    feather_rings = 8
    for ring in range(1, feather_rings + 1):
        next_frontier = {
            neighbor
            for index in frontier
            for neighbor in adjacency[index]
            if neighbor not in distance
        }
        for index in next_frontier:
            distance[index] = ring
        frontier = next_frontier
        if not frontier:
            break

    cleaned = []
    moved = 0.0
    for index, source_values in enumerate(weights):
        ring = distance.get(index)
        if ring is None:
            cleaned.append(dict(source_values))
            continue
        body_blend = 0.9 * (1.0 - ring / (feather_rings + 1.0))
        values = {
            name: value * (1.0 - body_blend)
            for name, value in source_values.items()
        }
        moved_here = math.fsum(source_values.values()) * body_blend
        values["body"] = values.get("body", 0.0) + moved_here
        total = math.fsum(values.values())
        cleaned.append({name: value / total for name, value in values.items()})
        moved += moved_here
    return cleaned, {
        "bilateral_leg_bridge_vertices": len(bridge_seeds),
        "bilateral_leg_bridge_feathered_vertices": len(distance),
        "bilateral_leg_bridge_weight_moved": round(moved, 6),
        "_bilateral_leg_bridge_vertex_indices": sorted(distance),
    }


def clean_weights(
    target,
    fitted,
    analysis,
    raw_weights,
    components,
    membership,
    confidences,
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    influence_limit=DEFAULT_INFLUENCE_LIMIT,
    use_proxy_fallback=True,
    fallback_proxy=None,
    spatial_data=None,
):
    deform_names = {bone.name for bone in fitted.data.bones if bone.use_deform}
    spatial_data = spatial_data or _spatial_weighting_data(
        target, fitted, analysis
    )
    segments = spatial_data["segments"]
    height = float(analysis["world_height"])
    points = spatial_data["points"]
    contexts = spatial_data["contexts"]
    preferred_families = spatial_data["preferred_families"]
    branch_corrections = spatial_data["branch_corrections"]
    cleaned = []
    stats = defaultdict(int)
    repaired_components = set()
    component_indices = defaultdict(list)
    for index, component_id in membership.items():
        component_indices[component_id].append(index)
    rigid_assignments = {}
    for component in components:
        if component["classification"] != "TINY_FLOATING_FRAGMENT":
            continue
        indices = component_indices[component["component"]]
        centroid = sum((points[index] for index in indices), Vector()) / len(indices)
        rigid_assignments[component["component"]] = _spatial_fallback_weights(
            centroid,
            analysis,
            segments,
            influence_limit,
            rigid=True,
        )
    for index, values in enumerate(raw_weights):
        component = components[membership[index]]
        rigid = component["classification"] == "TINY_FLOATING_FRAGMENT"
        side, distances_by_bone, nearest_distance = contexts[index]
        filtered = {}
        for name, value in values.items():
            if name not in deform_names:
                stats["non_deform_removed"] += 1
                continue
            if not math.isfinite(value) or value < 0.0:
                stats["invalid_removed"] += 1
                continue
            if value < threshold:
                stats["tiny_removed"] += 1
                continue
            if not _spatially_plausible(
                name,
                side,
                distances_by_bone,
                nearest_distance,
                height,
                preferred_family=preferred_families[index],
            ):
                if (
                    side != "CENTER"
                    and _bone_side(name) not in {"CENTER", side}
                ):
                    stats["opposite_side_removed"] += 1
                stats["impossible_removed"] += 1
                repaired_components.add(component["component"])
                continue
            filtered[name] = value
        low_confidence = confidences[index] < 0.22
        if rigid:
            filtered = rigid_assignments[component["component"]]
            stats["tiny_rigid_assignments"] += 1
            repaired_components.add(component["component"])
        elif not filtered:
            filtered = _spatial_fallback_weights(
                points[index],
                analysis,
                segments,
                influence_limit,
                preferred_family=preferred_families[index],
            )
            stats["proxy_fallback_vertices"] += 1
            repaired_components.add(component["component"])
        elif low_confidence:
            # A low BVH confidence score does not invalidate a donor weight
            # that agrees with the fitted skeleton. Replacing these wholesale
            # created hard torso/limb boundaries and the anchored fan artifacts.
            stats["low_confidence_spatially_preserved"] += 1
        limited = sorted(filtered.items(), key=lambda item: (-item[1], item[0]))
        if len(limited) > influence_limit:
            stats["limited_vertices"] += 1
        limited = limited[:influence_limit]
        final_limited = [
            (name, value) for name, value in limited if value >= threshold
        ]
        stats["tiny_removed"] += len(limited) - len(final_limited)
        limited = final_limited
        total = sum(value for _name, value in limited)
        if total <= 0.0:
            fallback = _spatial_fallback_weights(
                points[index],
                analysis,
                segments,
                influence_limit,
                preferred_family=preferred_families[index],
            )
            limited = sorted(
                fallback.items(), key=lambda item: (-item[1], item[0])
            )
            limited = [
                (name, value) for name, value in limited if value >= threshold
            ] or [max(fallback.items(), key=lambda item: item[1])]
            total = sum(value for _name, value in limited)
            stats["unweighted_repairs"] += 1
            repaired_components.add(component["component"])
        cleaned.append({name: value / total for name, value in limited})
    cleaned, continuity = _regularize_weight_continuity(
        target,
        fitted,
        analysis,
        cleaned,
        components,
        membership,
        preferred_families,
        influence_limit,
        spatial_data=spatial_data,
    )
    cleaned, root_cleanup = remove_root_surface_weights(
        target,
        fitted,
        analysis,
        cleaned,
        influence_limit,
        preferred_families,
        spatial_data=spatial_data,
    )
    stats.update(continuity)
    stats.update(root_cleanup)
    stats["topology_branch_label_corrections"] = branch_corrections
    stats["repaired_components"] = len(repaired_components)
    return cleaned, dict(stats)


def _ensure_deform_group_coverage(
    target,
    fitted,
    deform_names,
    components,
    membership,
    weights,
    influence_limit,
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    vertices_per_group=3,
):
    """Seed structurally empty deform groups on nearby anatomical vertices."""

    usage = defaultdict(int)
    for values in weights:
        for name, value in values.items():
            if value >= threshold:
                usage[name] += 1
    points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    used_vertices = set()
    repaired = {}
    for name in deform_names:
        if usage[name]:
            continue
        bone = fitted.data.bones.get(name)
        if bone is None:
            continue
        head = fitted.matrix_world @ bone.head_local
        tail = fitted.matrix_world @ bone.tail_local
        candidates = []
        for index, point in enumerate(points):
            component = components[membership[index]]
            if not _region_allowed(
                name,
                component["nearest_body_region"],
                component["side"],
            ):
                continue
            candidates.append(
                (
                    index in used_vertices,
                    _point_segment_distance(point, head, tail),
                    index,
                )
            )
        candidates.sort()
        selected = [item[2] for item in candidates[:vertices_per_group]]
        for index in selected:
            used_vertices.add(index)
            existing = sorted(
                weights[index].items(),
                key=lambda item: (-item[1], item[0]),
            )
            retained = [
                item for item in existing if item[0] != name
            ][: max(0, influence_limit - 1)]
            seeded = [(name, 0.25)] + retained
            total = sum(value for _bone_name, value in seeded)
            weights[index] = {
                bone_name: value / total for bone_name, value in seeded
            }
        if selected:
            repaired[name] = selected
    return repaired


def _canonicalize_final_weights(
    weights,
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    influence_limit=DEFAULT_INFLUENCE_LIMIT,
):
    """Make the written weights obey the validator's exact visibility rules."""

    cutoff = max(float(threshold), 0.0)
    limit = max(int(influence_limit), 1)
    canonical = []
    pruned_influences = 0
    pruned_vertices = 0
    renormalized_vertices = 0
    for values in weights:
        valid = [
            (name, float(value))
            for name, value in values.items()
            if math.isfinite(value) and value > 0.0
        ]
        ranked = sorted(valid, key=lambda item: (-item[1], item[0]))[:limit]
        retained = [item for item in ranked if item[1] >= cutoff]
        if not retained and ranked:
            retained = [ranked[0]]
        removed = len(valid) - len(retained)
        if removed:
            pruned_influences += removed
            pruned_vertices += 1
        total = math.fsum(value for _name, value in retained)
        if total <= 0.0:
            canonical.append({})
            continue
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            renormalized_vertices += 1
        canonical.append(
            {name: value / total for name, value in retained}
        )
    return canonical, {
        "final_threshold_pruned_influences": pruned_influences,
        "final_threshold_pruned_vertices": pruned_vertices,
        "final_renormalized_vertices": renormalized_vertices,
    }


def _snapshot_vertex_groups(target):
    groups = []
    for group in target.vertex_groups:
        weights = {}
        for vertex in target.data.vertices:
            try:
                value = group.weight(vertex.index)
            except RuntimeError:
                continue
            weights[vertex.index] = value
        groups.append(
            {
                "name": group.name,
                "lock_weight": bool(group.lock_weight),
                "weights": weights,
            }
        )
    return groups


def _restore_vertex_groups(target, snapshot):
    target.vertex_groups.clear()
    for record in snapshot:
        group = target.vertex_groups.new(name=record["name"])
        group.lock_weight = record["lock_weight"]
        for index, value in record["weights"].items():
            group.add([index], value, "REPLACE")


def _apply_weights(target, deform_names, weights, removed_names=()):
    for name in set(deform_names).union(removed_names):
        existing = target.vertex_groups.get(name)
        if existing is not None:
            target.vertex_groups.remove(existing)
    groups = {name: target.vertex_groups.new(name=name) for name in deform_names}
    for index, values in enumerate(weights):
        for name, value in values.items():
            groups[name].add([index], float(value), "REPLACE")


def validate_production_weights(
    target,
    fitted,
    analysis,
    transfer,
    cleanup,
    components,
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    influence_limit=DEFAULT_INFLUENCE_LIMIT,
    root_successor_vertices=(),
    spatial_data=None,
):
    deform_names = {bone.name for bone in fitted.data.bones if bone.use_deform}
    group_by_index = {group.index: group.name for group in target.vertex_groups}
    weighted = 0
    unweighted = 0
    normalized = 0
    non_normalized = 0
    maximum = 0
    total_influences = 0
    above_limit = 0
    invalid = 0
    non_deform = 0
    opposite = 0
    impossible = 0
    impossible_components = set()
    impossible_examples = []
    maximum_spatial_excess = 0.0
    usage = defaultdict(int)
    region_summary = defaultdict(lambda: defaultdict(float))
    membership = transfer["component_membership"]
    spatial_data = spatial_data or _spatial_weighting_data(
        target, fitted, analysis
    )
    points = spatial_data["points"]
    contexts = spatial_data["contexts"]
    height = float(analysis["world_height"])
    preferred_families = spatial_data["preferred_families"]
    root_successor_vertices = set(root_successor_vertices)
    for vertex in target.data.vertices:
        component = components[membership[vertex.index]]
        point_region, _coarse_side = _point_anatomy(
            points[vertex.index], analysis
        )
        point_side, bone_distances, nearest_distance = contexts[vertex.index]
        values = []
        for item in vertex.groups:
            name = group_by_index.get(item.group)
            value = float(item.weight)
            if not math.isfinite(value) or value < 0.0:
                invalid += 1
            if name not in deform_names:
                non_deform += 1
            if value >= threshold:
                values.append((name, value))
                usage[name] += 1
                region = component["nearest_body_region"]
                region_summary[region][name] += value
                spatial_excess = max(
                    0.0,
                    bone_distances.get(name, float("inf"))
                    - nearest_distance,
                )
                if math.isfinite(spatial_excess):
                    maximum_spatial_excess = max(
                        maximum_spatial_excess, spatial_excess
                    )
                strict_plausible = _spatially_plausible(
                    name,
                    point_side,
                    bone_distances,
                    nearest_distance,
                    height,
                    (
                        None
                        if component["classification"]
                        == "TINY_FLOATING_FRAGMENT"
                        else MAX_FALLBACK_HIERARCHY_STEPS
                    ),
                    preferred_family=(
                        None
                        if component["classification"]
                        == "TINY_FLOATING_FRAGMENT"
                        else preferred_families[vertex.index]
                    ),
                )
                bridge_plausible = _spatially_plausible(
                    name,
                    point_side,
                    bone_distances,
                    nearest_distance,
                    height,
                    max_hierarchy_steps=None,
                    margin_ratio=0.14,
                )
                intentional_root_successor = (
                    name == "body" and vertex.index in root_successor_vertices
                )
                if not (
                    strict_plausible
                    or bridge_plausible
                    or intentional_root_successor
                ):
                    impossible += 1
                    impossible_components.add(membership[vertex.index])
                    if len(impossible_examples) < 20:
                        impossible_examples.append(
                            {
                                "vertex": vertex.index,
                                "component": membership[vertex.index],
                                "bone": name,
                                "weight": round(value, 6),
                                "side": point_side,
                                "bone_side": _bone_side(name),
                                "bone_distance": round(
                                    bone_distances.get(name, float("inf")), 6
                                ),
                                "nearest_bone_distance": round(
                                    nearest_distance, 6
                                ),
                                "position": [
                                    round(float(item), 6)
                                    for item in points[vertex.index]
                                ],
                            }
                        )
                if (
                    point_side != "CENTER"
                    and _bone_side(name)
                    not in {"CENTER", point_side}
                ):
                    opposite += 1
        count = len(values)
        maximum = max(maximum, count)
        total_influences += count
        total = sum(value for _name, value in values)
        if count:
            weighted += 1
            if abs(total - 1.0) <= WEIGHT_TOLERANCE:
                normalized += 1
            else:
                non_normalized += 1
        else:
            unweighted += 1
        if count > influence_limit:
            above_limit += 1
    missing_groups = sorted(
        name for name in deform_names if target.vertex_groups.get(name) is None
    )
    empty_groups = sorted(
        name
        for name in deform_names - NON_SURFACE_DEFORM_BONES
        if usage[name] == 0
    )
    prohibited_surface_weight_vertices = sum(
        1
        for vertex in target.data.vertices
        if any(
            group_by_index.get(item.group) in NON_SURFACE_DEFORM_BONES
            and float(item.weight) >= threshold
            for item in vertex.groups
        )
    )
    armature_modifiers = [
        modifier
        for modifier in target.modifiers
        if _is_owned_armature_modifier(modifier) and modifier.object == fitted
    ]
    bind_matrices_consistent = (
        target.parent == fitted
        and target.parent_type == "OBJECT"
        and max(
            abs(float(value))
            for row in (
                target.matrix_parent_inverse
                - fitted.matrix_world.inverted_safe()
            )
            for value in row
        )
        <= 1.0e-5
    )
    lateral = Vector(analysis["lateral_axis_world"])
    left_right_inversion = [
        base
        for base in ("shoulder", "arm", "leg")
        if (
            fitted.data.bones[
                "shoulder_left"
                if base == "shoulder"
                else f"{base}_left_top"
            ].head_local
            - fitted.data.bones[
                "shoulder_right"
                if base == "shoulder"
                else f"{base}_right_top"
            ].head_local
        ).dot(lateral)
        <= 0.0
    ]
    failures = (
        unweighted
        or non_normalized
        or invalid
        or non_deform
        or above_limit
        or missing_groups
        or len(armature_modifiers) != 1
        or impossible
        or not bind_matrices_consistent
        or left_right_inversion
        or prohibited_surface_weight_vertices
    )
    review = bool(empty_groups or opposite)
    status = (
        "FAILED"
        if failures
        else "NEEDS_WEIGHT_REVIEW"
        if review
        else "READY_FOR_ANIMATION_TEST"
    )
    confidence_values = transfer["confidences"]
    current_topology = topology_snapshot(target)
    protected_topology_unchanged = all(
        current_topology[key] == analysis["topology_snapshot"][key]
        for key in (
            "vertices",
            "edges",
            "polygons",
            "loops",
            "vertex_positions",
            "polygon_vertices",
            "uv_layers",
            "materials",
        )
    )
    if not protected_topology_unchanged:
        status = "FAILED"
    return {
        "status": status,
        "method": TRANSFER_METHOD,
        "fallback_method": FALLBACK_METHOD,
        "total_vertices": len(target.data.vertices),
        "weighted_vertices": weighted,
        "unweighted_vertices": unweighted,
        "normalized_vertices": normalized,
        "non_normalized_vertices": non_normalized,
        "normalization_tolerance": WEIGHT_TOLERANCE,
        "maximum_influences": maximum,
        "average_influences": round(
            total_influences / max(len(target.data.vertices), 1), 4
        ),
        "vertices_exceeding_influence_limit": above_limit,
        "influence_limit": influence_limit,
        "non_finite_or_negative_weights": invalid,
        "non_deform_weights": non_deform,
        "missing_required_deform_groups": missing_groups,
        "empty_deform_groups": empty_groups,
        "non_surface_deform_bones": sorted(NON_SURFACE_DEFORM_BONES),
        "prohibited_surface_weight_vertices": (
            prohibited_surface_weight_vertices
        ),
        "root_surface_successor_vertices": len(root_successor_vertices),
        "root_surface_successor_vertex_indices": sorted(
            root_successor_vertices
        ),
        "opposite_side_contamination": opposite,
        "anatomically_impossible_weights": impossible,
        "anatomically_impossible_components": sorted(impossible_components),
        "anatomically_impossible_examples": impossible_examples,
        "spatial_bone_margin_ratio": SPATIAL_BONE_MARGIN_RATIO,
        "maximum_bone_distance_excess": round(maximum_spatial_excess, 6),
        "bind_matrices_consistent": bind_matrices_consistent,
        "left_right_inversion": left_right_inversion,
        "donor_transfer_confidence": {
            "minimum": round(min(confidence_values, default=0.0), 6),
            "mean": round(
                sum(confidence_values) / max(len(confidence_values), 1), 6
            ),
            "low_count": sum(value < 0.22 for value in confidence_values),
        },
        "proxy_fallback_vertex_count": cleanup.get("proxy_fallback_vertices", 0),
        "repaired_component_count": cleanup.get("repaired_components", 0),
        "tiny_rigid_component_assignments": cleanup.get(
            "tiny_rigid_assignments", 0
        ),
        "cleanup": cleanup,
        "component_count": len(components),
        "components": components,
        "per_region_influences": {
            region: dict(
                sorted(values.items(), key=lambda item: (-item[1], item[0]))[:8]
            )
            for region, values in region_summary.items()
        },
        "hand_summary": {
            side: {
                "retained_bone": f"arm_{side}_hand",
                "weighted_vertices": usage[f"arm_{side}_hand"],
            }
            for side in ("left", "right")
        },
        "foot_summary": {
            side: sum(
                usage[name]
                for name in deform_names
                if name.startswith(f"leg_{side}_foot")
            )
            for side in ("left", "right")
        },
        "intended_armature_modifiers": len(armature_modifiers),
        "topology_unchanged": protected_topology_unchanged,
    }


def audit_production_weights(
    target,
    fitted,
    analysis,
    prior_report,
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    influence_limit=DEFAULT_INFLUENCE_LIMIT,
):
    components = prior_report.get("components") or []
    component_lists = _component_indices(target.data)
    if len(components) != len(component_lists):
        raise RuntimeError("Component inventory changed after production binding.")
    membership = {}
    for component_id, indices in enumerate(component_lists):
        for index in indices:
            membership[index] = component_id
    confidence_summary = prior_report.get("donor_transfer_confidence") or {}
    confidence = float(confidence_summary.get("mean", 0.0))
    transfer = {
        "confidences": [confidence] * len(target.data.vertices),
        "distances": [],
        "component_membership": membership,
    }
    report = validate_production_weights(
        target,
        fitted,
        analysis,
        transfer,
        prior_report.get("cleanup") or {},
        components,
        threshold,
        influence_limit,
        prior_report.get("root_surface_successor_vertex_indices") or [],
    )
    for key in (
        "donor_source",
        "binding_method",
        "donor_transfer_confidence",
        "production_profile",
        "source_canonical_fingerprint",
        "production_fingerprint",
        "removed_finger_bones",
        "donor_hand_weight_merge",
        "voxel_heat_proxy",
        "proxy_fallback_vertex_count",
        "repaired_component_count",
        "tiny_rigid_component_assignments",
    ):
        if key in prior_report:
            report[key] = prior_report[key]
    report["removed_weight_groups_present"] = sorted(
        name
        for name in report.get("removed_finger_bones", [])
        if target.vertex_groups.get(name) is not None
    )
    if report["removed_weight_groups_present"]:
        report["status"] = "FAILED"
    target[RIG_WEIGHT_REPORT_PROPERTY] = json.dumps(
        report, sort_keys=True, separators=(",", ":")
    )
    return report


def bind_production_character(
    context,
    target,
    source_armature,
    fitted,
    contract,
    analysis,
    mode="VOXEL_HEAT_PROXY",
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    influence_limit=DEFAULT_INFLUENCE_LIMIT,
    force_failure=False,
):
    """Bind transactionally; restore every changed target field on failure."""

    if target.name not in context.view_layer.objects:
        raise ValueError(
            f"Target Mesh '{target.name}' is not in the active scene; choose the "
            "visible production mesh before binding."
        )

    topology_before = topology_snapshot(target)
    groups_before = _snapshot_vertex_groups(target)
    parent_before = target.parent
    parent_type_before = target.parent_type
    parent_inverse_before = target.matrix_parent_inverse.copy()
    matrix_world_before = target.matrix_world.copy()
    owned_modifiers_before = [
        {
            "object": modifier.object,
            "use_vertex_groups": modifier.use_vertex_groups,
            "use_bone_envelopes": modifier.use_bone_envelopes,
        }
        for modifier in target.modifiers
        if _is_owned_armature_modifier(modifier)
    ]
    foreign_armatures = [
        modifier.name
        for modifier in target.modifiers
        if modifier.type == "ARMATURE"
        and not _is_owned_armature_modifier(modifier)
    ]
    if foreign_armatures:
        raise RuntimeError(
            "Remove or explicitly migrate foreign Armature modifiers before binding: "
            + ", ".join(foreign_armatures)
        )
    metadata_before = {
        key: target[key]
        for key in target.keys()
        if key.startswith("sbf_")
    }
    donor = None
    proxy = None
    donor_source = ""
    donor_merge_report = {}
    voxel_heat_report = None
    spatial_data = None
    try:
        clean_weighting_temporary_data()
        deform_names = [
            bone["name"] for bone in contract["bones"] if bone["deform"]
        ]
        if mode == "VOXEL_HEAT_PROXY":
            proxy, proxy_weights, voxel_heat_report = create_voxel_heat_proxy(
                context,
                target,
                fitted,
                deform_names,
                float(analysis["world_height"]),
            )
            raw, distances, confidences, _bvh = transfer_donor_weights(
                target,
                proxy,
                proxy_weights,
                float(analysis["world_height"]),
            )
            components, membership = classify_components(
                target, analysis, raw, distances
            )
            spatial_data = _spatial_weighting_data(target, fitted, analysis)
            cleaned, first_side_cleanup = enforce_anatomical_sides(
                target, analysis, raw
            )
            cleaned = smooth_surface_weights(target, cleaned)
            cleaned, final_side_cleanup = enforce_anatomical_sides(
                target, analysis, cleaned
            )
            cleaned, remote_limb_cleanup = attenuate_remote_limb_weights(
                target,
                fitted,
                analysis,
                cleaned,
                spatial_data=spatial_data,
            )
            cleaned, spatial_cleanup = remove_spatially_impossible_weights(
                target,
                fitted,
                analysis,
                cleaned,
                components,
                membership,
                influence_limit,
                spatial_data=spatial_data,
            )
            preferred_families = spatial_data["preferred_families"]
            cleaned, continuity_cleanup = _regularize_weight_continuity(
                target,
                fitted,
                analysis,
                cleaned,
                components,
                membership,
                preferred_families,
                influence_limit,
                spatial_data=spatial_data,
                smoothing_iterations=0,
                palette_iterations=128,
                palette_edge_limit=0.015,
            )
            cleaned, root_cleanup = remove_root_surface_weights(
                target,
                fitted,
                analysis,
                cleaned,
                influence_limit,
                preferred_families,
                spatial_data=spatial_data,
            )
            cleaned, bridge_cleanup = stabilize_bilateral_leg_bridges(
                target, fitted, analysis, cleaned
            )
            cleanup = {
                "voxel_heat_proxy_vertices": voxel_heat_report["proxy_vertices"],
                "voxel_heat_proxy_triangles": voxel_heat_report["proxy_triangles"],
                "voxel_heat_smoothing_iterations": VOXEL_HEAT_SMOOTHING_ITERATIONS,
                "anatomical_side_corrected_vertices": (
                    first_side_cleanup["anatomical_side_corrected_vertices"]
                    + final_side_cleanup["anatomical_side_corrected_vertices"]
                ),
                "anatomical_side_removed_influences": (
                    first_side_cleanup["anatomical_side_removed_influences"]
                    + final_side_cleanup["anatomical_side_removed_influences"]
                ),
                **remote_limb_cleanup,
                **spatial_cleanup,
                **root_cleanup,
                **bridge_cleanup,
                **continuity_cleanup,
            }
            donor_source = voxel_heat_report["method"]
        else:
            donor, donor_weights, donor_merge_report = create_aligned_donor(
                context, source_armature, fitted, contract
            )
            proxy = create_fallback_proxy(context, fitted)
            raw, distances, confidences, _bvh = transfer_donor_weights(
                target, donor, donor_weights, float(analysis["world_height"])
            )
            components, membership = classify_components(
                target, analysis, raw, distances
            )
            spatial_data = _spatial_weighting_data(target, fitted, analysis)
            if mode == "AUTOMATIC_WEIGHTS_DIAGNOSTIC":
                cleaned, cleanup = clean_weights(
                    target,
                    fitted,
                    analysis,
                    [{} for _ in raw],
                    components,
                    membership,
                    [0.0 for _ in raw],
                    threshold,
                    influence_limit,
                    use_proxy_fallback=True,
                    fallback_proxy=proxy,
                    spatial_data=spatial_data,
                )
            else:
                cleaned, cleanup = clean_weights(
                    target,
                    fitted,
                    analysis,
                    raw,
                    components,
                    membership,
                    confidences,
                    threshold,
                    influence_limit,
                    use_proxy_fallback=(
                        mode == "CANONICAL_TRANSFER_WITH_PROXY_FALLBACK"
                    ),
                    fallback_proxy=proxy,
                    spatial_data=spatial_data,
                )
            donor_source = donor.get("sbf_donor_source", "")
        root_successor_vertices = cleanup.pop(
            "_root_surface_successor_vertices", []
        )
        root_successor_vertices = sorted(
            set(root_successor_vertices).union(
                cleanup.pop("_bilateral_leg_bridge_vertex_indices", [])
            )
        )
        final_threshold = (
            max(float(threshold), VOXEL_HEAT_NOISE_THRESHOLD)
            if mode == "VOXEL_HEAT_PROXY"
            else threshold
        )
        coverage_repairs = _ensure_deform_group_coverage(
            target,
            fitted,
            [
                name
                for name in deform_names
                if name not in NON_SURFACE_DEFORM_BONES
            ],
            components,
            membership,
            cleaned,
            influence_limit,
            threshold=final_threshold,
        )
        cleanup["empty_group_repairs"] = len(coverage_repairs)
        cleanup["empty_group_repair_vertices"] = sum(
            len(indices) for indices in coverage_repairs.values()
        )
        cleanup["empty_group_repair_groups"] = sorted(coverage_repairs)
        cleaned, final_cleanup = _canonicalize_final_weights(
            cleaned,
            final_threshold,
            influence_limit,
        )
        cleanup["final_weight_threshold"] = final_threshold
        cleanup.update(final_cleanup)
        for modifier in list(target.modifiers):
            if _is_owned_armature_modifier(modifier):
                target.modifiers.remove(modifier)
        _apply_weights(
            target,
            deform_names,
            cleaned,
            removed_names=contract.get("removed_bones", []),
        )
        if force_failure:
            raise RuntimeError("Forced binding failure for rollback regression.")
        modifier = target.modifiers.new(RIG_ARMATURE_MODIFIER, "ARMATURE")
        modifier.object = fitted
        modifier.use_vertex_groups = True
        modifier.use_bone_envelopes = False
        world = target.matrix_world.copy()
        target.parent = fitted
        target.parent_type = "OBJECT"
        target.matrix_parent_inverse = fitted.matrix_world.inverted_safe()
        target.matrix_world = world
        target["sbf_bound"] = True
        target["sbf_binding_method"] = mode
        target["sbf_canonical_fingerprint"] = contract["fingerprint"]
        transfer = {
            "confidences": confidences,
            "distances": distances,
            "component_membership": membership,
        }
        report = validate_production_weights(
            target,
            fitted,
            analysis,
            transfer,
            cleanup,
            components,
            threshold,
            influence_limit,
            root_successor_vertices,
            spatial_data=spatial_data,
        )
        report["donor_source"] = donor_source
        report["binding_method"] = mode
        if voxel_heat_report is not None:
            report["voxel_heat_proxy"] = voxel_heat_report
        report["production_profile"] = contract.get("profile_id", "")
        report["source_canonical_fingerprint"] = contract.get(
            "source_fingerprint", ""
        )
        report["production_fingerprint"] = contract["fingerprint"]
        report["removed_finger_bones"] = contract.get("removed_bones", [])
        report["donor_hand_weight_merge"] = donor_merge_report
        report["removed_weight_groups_present"] = sorted(
            name
            for name in contract.get("removed_bones", [])
            if target.vertex_groups.get(name) is not None
        )
        if report["removed_weight_groups_present"]:
            report["status"] = "FAILED"
        if report["status"] == "FAILED":
            raise RuntimeError(
                "Production weight validation failed: "
                f"{report['unweighted_vertices']} unweighted, "
                f"{report['non_normalized_vertices']} non-normalized, "
                f"{report['anatomically_impossible_weights']} spatially "
                f"impossible, {report['opposite_side_contamination']} "
                f"opposite-side, {len(report['empty_deform_groups'])} empty "
                f"deform groups; bind matrices consistent: "
                f"{report['bind_matrices_consistent']}; examples: "
                f"{report['anatomically_impossible_examples'][:3]}."
            )
        target[RIG_WEIGHT_REPORT_PROPERTY] = json.dumps(
            report, sort_keys=True, separators=(",", ":")
        )
        if topology_snapshot(target) != {
            **topology_before,
            "vertex_groups": [group.name for group in target.vertex_groups],
            "armature_modifiers": [RIG_ARMATURE_MODIFIER],
        }:
            current = topology_snapshot(target)
            for key in (
                "vertices",
                "edges",
                "polygons",
                "loops",
                "vertex_positions",
                "polygon_vertices",
                "uv_layers",
                "materials",
            ):
                if current[key] != topology_before[key]:
                    raise RuntimeError(f"Binding changed protected target field '{key}'.")
        return report
    except Exception:
        for modifier in list(target.modifiers):
            if _is_owned_armature_modifier(modifier):
                target.modifiers.remove(modifier)
        _restore_vertex_groups(target, groups_before)
        for record in owned_modifiers_before:
            modifier = target.modifiers.new(RIG_ARMATURE_MODIFIER, "ARMATURE")
            modifier.object = record["object"]
            modifier.use_vertex_groups = record["use_vertex_groups"]
            modifier.use_bone_envelopes = record["use_bone_envelopes"]
        target.parent = parent_before
        target.parent_type = parent_type_before
        target.matrix_parent_inverse = parent_inverse_before
        target.matrix_world = matrix_world_before
        for key in list(target.keys()):
            if key.startswith("sbf_"):
                del target[key]
        for key, value in metadata_before.items():
            target[key] = value
        raise
    finally:
        clean_weighting_temporary_data()


def load_weight_report(target):
    raw = target.get(RIG_WEIGHT_REPORT_PROPERTY, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
