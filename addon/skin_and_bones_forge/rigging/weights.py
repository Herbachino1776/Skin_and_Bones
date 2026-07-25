"""Transactional deterministic production weighting for fragmented SPAR3D meshes."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import heapq
import json
import math

import bpy
from mathutils import Vector, geometry
from mathutils.bvhtree import BVHTree

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


def _topology_preferred_families(target, points, segments):
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
    for point in points:
        by_family = defaultdict(lambda: float("inf"))
        for name, (head, tail) in segments.items():
            family = _bone_family(name)
            by_family[family] = min(
                by_family[family], _point_segment_distance(point, head, tail)
            )
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


def _regularize_weight_continuity(
    target,
    fitted,
    analysis,
    weights,
    components,
    membership,
    preferred_families,
    influence_limit,
):
    """Diffuse skin weights locally without crossing disconnected components."""

    adjacency = [set() for _vertex in target.data.vertices]
    edges = []
    for edge in target.data.edges:
        first, second = map(int, edge.vertices)
        adjacency[first].add(second)
        adjacency[second].add(first)
        edges.append((first, second))
    tiny_components = {
        record["component"]
        for record in components
        if record["classification"] == "TINY_FLOATING_FRAGMENT"
    }
    points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    segments = _bone_segments(fitted)
    height = float(analysis["world_height"])
    contexts = [
        _spatial_context(point, analysis, segments) for point in points
    ]
    def plausible(index, name):
        side, distances, nearest = contexts[index]
        return _spatially_plausible(
            name,
            side,
            distances,
            nearest,
            height,
            max_hierarchy_steps=None,
        )
    before_maximum = max(
        (_weight_edge_delta(weights[first], weights[second]) for first, second in edges),
        default=0.0,
    )
    current = [dict(values) for values in weights]
    for _iteration in range(CONTINUITY_SMOOTHING_ITERATIONS):
        updated = []
        for index, values in enumerate(current):
            neighbors = adjacency[index]
            if not neighbors or membership[index] in tiny_components:
                updated.append(dict(values))
                continue
            combined = defaultdict(float)
            for name, value in values.items():
                if plausible(index, name):
                    combined[name] += value * (
                        1.0 - CONTINUITY_SMOOTHING_FACTOR
                    )
            neighbor_factor = CONTINUITY_SMOOTHING_FACTOR / len(neighbors)
            for neighbor in neighbors:
                for name, value in current[neighbor].items():
                    if plausible(index, name):
                        combined[name] += value * neighbor_factor
            combined = {
                name: value
                for name, value in combined.items()
                if value >= DEFAULT_WEIGHT_THRESHOLD
                and plausible(index, name)
            }
            total = sum(combined.values())
            updated.append(
                {name: value / total for name, value in combined.items()}
                if total > 0.0
                else dict(values)
            )
        current = updated
    limited = []
    for values in current:
        ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))[
            :influence_limit
        ]
        total = sum(value for _name, value in ranked)
        limited.append({name: value / total for name, value in ranked})

    palette_iterations = 48
    palette_edge_limit = 0.10
    for _iteration in range(palette_iterations):
        proposals = [[] for _vertex in limited]
        for first, second in edges:
            if _weight_edge_delta(limited[first], limited[second]) <= (
                palette_edge_limit
            ):
                continue
            merged = defaultdict(float)
            for name, value in limited[first].items():
                merged[name] += value * 0.5
            for name, value in limited[second].items():
                merged[name] += value * 0.5
            ranked = sorted(
                merged.items(), key=lambda item: (-item[1], item[0])
            )[:influence_limit]
            total = sum(value for _name, value in ranked)
            common = {name: value / total for name, value in ranked}
            proposals[first].append(common)
            proposals[second].append(common)
        if not any(proposals):
            break
        reconciled = []
        for index, vertex_proposals in enumerate(proposals):
            if not vertex_proposals:
                reconciled.append(limited[index])
                continue
            combined = defaultdict(float)
            for name, value in limited[index].items():
                combined[name] += value * 0.25
            proposal_factor = 0.75 / len(vertex_proposals)
            side, distances, nearest = contexts[index]
            for proposal in vertex_proposals:
                for name, value in proposal.items():
                    if (
                        (side == "CENTER" or _bone_side(name) in {"CENTER", side})
                        and distances.get(name, float("inf"))
                        <= nearest + height * 0.14
                    ):
                        combined[name] += value * proposal_factor
            ranked = sorted(
                combined.items(), key=lambda item: (-item[1], item[0])
            )[:influence_limit]
            total = sum(value for _name, value in ranked)
            reconciled.append(
                {name: value / total for name, value in ranked}
                if total > 0.0
                else limited[index]
            )
        limited = reconciled
    after_maximum = max(
        (_weight_edge_delta(limited[first], limited[second]) for first, second in edges),
        default=0.0,
    )
    return limited, {
        "continuity_smoothing_iterations": CONTINUITY_SMOOTHING_ITERATIONS,
        "continuity_smoothing_factor": CONTINUITY_SMOOTHING_FACTOR,
        "maximum_edge_weight_delta_before": round(before_maximum, 6),
        "maximum_edge_weight_delta_after": round(after_maximum, 6),
        "palette_reconciliation_iterations": palette_iterations,
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
):
    deform_names = {bone.name for bone in fitted.data.bones if bone.use_deform}
    segments = _bone_segments(fitted)
    height = float(analysis["world_height"])
    points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    preferred_families, branch_corrections = _topology_preferred_families(
        target, points, segments
    )
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
        side, distances_by_bone, nearest_distance = _spatial_context(
            points[index], analysis, segments
        )
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
    )
    stats.update(continuity)
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
    vertices_per_group=3,
):
    """Seed structurally empty deform groups on nearby anatomical vertices."""

    usage = defaultdict(int)
    for values in weights:
        for name in values:
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
    points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
    segments = _bone_segments(fitted)
    height = float(analysis["world_height"])
    preferred_families, _branch_corrections = _topology_preferred_families(
        target, points, segments
    )
    for vertex in target.data.vertices:
        component = components[membership[vertex.index]]
        point_region, _coarse_side = _point_anatomy(
            points[vertex.index], analysis
        )
        point_side, bone_distances, nearest_distance = _spatial_context(
            points[vertex.index], analysis, segments
        )
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
                if not (strict_plausible or bridge_plausible):
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
    empty_groups = sorted(name for name in deform_names if usage[name] == 0)
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
    mode="CANONICAL_TRANSFER_WITH_PROXY_FALLBACK",
    threshold=DEFAULT_WEIGHT_THRESHOLD,
    influence_limit=DEFAULT_INFLUENCE_LIMIT,
    force_failure=False,
):
    """Bind transactionally; restore every changed target field on failure."""

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
    try:
        clean_weighting_temporary_data()
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
            )
        deform_names = [
            bone["name"] for bone in contract["bones"] if bone["deform"]
        ]
        coverage_repairs = _ensure_deform_group_coverage(
            target,
            fitted,
            deform_names,
            components,
            membership,
            cleaned,
            influence_limit,
        )
        cleanup["empty_group_repairs"] = len(coverage_repairs)
        cleanup["empty_group_repair_vertices"] = sum(
            len(indices) for indices in coverage_repairs.values()
        )
        cleanup["empty_group_repair_groups"] = sorted(coverage_repairs)
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
        )
        report["donor_source"] = donor.get("sbf_donor_source", "")
        report["binding_method"] = mode
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
