"""Non-destructive evaluated target-mesh analysis."""

from __future__ import annotations

import hashlib
import json
import math

from mathutils import Vector
from mathutils.kdtree import KDTree


def axis_vector(axis):
    sign = -1.0 if axis.startswith("-") else 1.0
    vector = {
        "X": Vector((1.0, 0.0, 0.0)),
        "Y": Vector((0.0, 1.0, 0.0)),
        "Z": Vector((0.0, 0.0, 1.0)),
    }[axis[-1]]
    return vector * sign


def _quantized(value, digits=6):
    rounded = round(float(value), digits)
    return 0.0 if rounded == -0.0 else rounded


def _hash_values(values):
    digest = hashlib.sha256()
    for value in values:
        digest.update(f"{_quantized(value):.6f},".encode("ascii"))
    return digest.hexdigest()


def topology_snapshot(obj):
    mesh = obj.data
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "polygons": len(mesh.polygons),
        "loops": len(mesh.loops),
        "vertex_positions": _hash_values(
            component for vertex in mesh.vertices for component in vertex.co
        ),
        "polygon_vertices": hashlib.sha256(
            ",".join(
                str(index)
                for polygon in mesh.polygons
                for index in polygon.vertices
            ).encode("ascii")
        ).hexdigest(),
        "uv_layers": [
            {
                "name": layer.name,
                "active_render": bool(layer.active_render),
                "data": _hash_values(
                    component for loop in layer.uv for component in loop.vector
                ),
            }
            for layer in mesh.uv_layers
        ],
        "materials": [
            slot.material.name if slot.material else None for slot in obj.material_slots
        ],
        "vertex_groups": [group.name for group in obj.vertex_groups],
        "armature_modifiers": [
            modifier.name for modifier in obj.modifiers if modifier.type == "ARMATURE"
        ],
    }


def _components(mesh):
    parent = list(range(len(mesh.vertices)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for edge in mesh.edges:
        first, second = edge.vertices
        first_root, second_root = root(first), root(second)
        if first_root != second_root:
            parent[second_root] = first_root
    sizes = {}
    for index in range(len(parent)):
        item = root(index)
        sizes[item] = sizes.get(item, 0) + 1
    return sorted(sizes.values(), reverse=True)


def _symmetry(points, center, lateral):
    tree = KDTree(len(points))
    for index, point in enumerate(points):
        tree.insert(point, index)
    tree.balance()
    if not points:
        return 0.0
    stride = max(1, len(points) // 2000)
    distances = []
    for point in points[::stride]:
        offset = (point - center).dot(lateral)
        mirrored = point - lateral * (2.0 * offset)
        _co, _index, distance = tree.find(mirrored)
        distances.append(distance)
    diagonal = max((point - center).length for point in points)
    mean = sum(distances) / max(1, len(distances))
    return max(0.0, min(1.0, 1.0 - mean / max(diagonal * 0.04, 1e-8)))


def evaluated_points(context, obj):
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        return [evaluated.matrix_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def analyze_target(context, obj, forward_axis="+Y", up_axis="+Z"):
    if obj is None or obj.type != "MESH":
        raise ValueError("Choose a production target mesh.")
    if not obj.data.vertices or not obj.data.polygons:
        raise ValueError("The target mesh has no renderable geometry.")
    forward = axis_vector(forward_axis)
    up = axis_vector(up_axis)
    if abs(forward.dot(up)) > 1e-5:
        raise ValueError("Forward Axis and Up Axis must be perpendicular.")
    lateral = up.cross(forward).normalized()
    points = evaluated_points(context, obj)
    if not points:
        raise ValueError("The evaluated target has no vertices.")

    up_values = [point.dot(up) for point in points]
    side_values = [point.dot(lateral) for point in points]
    front_values = [point.dot(forward) for point in points]
    ground = min(up_values)
    top = max(up_values)
    center = (
        up * ((ground + top) * 0.5)
        + lateral * ((min(side_values) + max(side_values)) * 0.5)
        + forward * ((min(front_values) + max(front_values)) * 0.5)
    )
    component_sizes = _components(obj.data)
    warnings = []
    if len(component_sizes) > 1:
        small = sum(component_sizes[1:])
        warnings.append(
            f"Target has {len(component_sizes)} connected components "
            f"({small:,} vertices outside the largest); bone heat may leak or fail."
        )
    height = top - ground
    width = max(side_values) - min(side_values)
    depth = max(front_values) - min(front_values)
    if width / max(height, 1e-8) < 0.18:
        warnings.append("Limb separation is narrow; inspect arms, hands, and inner legs.")
    if len(component_sizes) > 64:
        warnings.append("Highly fragmented topology is a high-risk bone-heat target.")

    snapshot = topology_snapshot(obj)
    return {
        "schema": 1,
        "target_object": obj.name,
        "target_data": obj.data.name,
        "forward_axis": forward_axis,
        "up_axis": up_axis,
        "lateral_axis_world": [_quantized(value) for value in lateral],
        "forward_axis_world": [_quantized(value) for value in forward],
        "up_axis_world": [_quantized(value) for value in up],
        "world_height": _quantized(height),
        "ground": _quantized(ground),
        "top": _quantized(top),
        "centerline_world": [_quantized(value) for value in center],
        "world_width": _quantized(width),
        "world_depth": _quantized(depth),
        "symmetry": _quantized(_symmetry(points, center, lateral), 4),
        "connected_components": len(component_sizes),
        "component_sizes": component_sizes,
        "limb_separation_warning": width / max(height, 1e-8) < 0.18,
        "bone_heat_risk": (
            "HIGH"
            if len(component_sizes) > 64
            else "MEDIUM"
            if len(component_sizes) > 1
            else "LOW"
        ),
        "inventory": {
            "vertices": len(obj.data.vertices),
            "edges": len(obj.data.edges),
            "polygons": len(obj.data.polygons),
            "loops": len(obj.data.loops),
            "uv_layers": [layer.name for layer in obj.data.uv_layers],
            "materials": snapshot["materials"],
        },
        "topology_snapshot": snapshot,
        "warnings": warnings,
    }


def encode_analysis(analysis):
    return json.dumps(analysis, sort_keys=True, separators=(",", ":"))
