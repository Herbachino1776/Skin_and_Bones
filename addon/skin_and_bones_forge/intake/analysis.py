"""Deterministic topology, attribute, and shading analysis for SPAR3D meshes."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import struct

from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


FINGERPRINT_SCHEMA = 1
ANALYSIS_SCHEMA = 1


def _finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Mesh contains a non-finite numeric value.")
    return number


def _vector(value):
    return [_finite(component) for component in value]


def _matrix(value):
    return [_vector(row) for row in value]


def _bounds(points):
    if not points:
        return {"minimum": None, "maximum": None, "extents": None}
    minimum = [min(point[axis] for point in points) for axis in range(3)]
    maximum = [max(point[axis] for point in points) for axis in range(3)]
    return {
        "minimum": minimum,
        "maximum": maximum,
        "extents": [maximum[index] - minimum[index] for index in range(3)],
    }


def _face_edges(vertices):
    for index, first in enumerate(vertices):
        yield first, vertices[(index + 1) % len(vertices)]


def _topology(mesh):
    edge_faces = defaultdict(list)
    oriented_edges = defaultdict(list)
    used_vertices = set()
    repeated_faces = []
    zero_area_faces = []
    duplicate_faces = []
    seen_faces = {}
    if mesh.vertices:
        minimum = Vector(
            min(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)
        )
        maximum = Vector(
            max(vertex.co[axis] for vertex in mesh.vertices) for axis in range(3)
        )
        diagonal = maximum - minimum
    else:
        diagonal = Vector()
    strict_area = max(diagonal.length_squared * 1.0e-18, 1.0e-30)

    for polygon in mesh.polygons:
        vertices = tuple(polygon.vertices)
        used_vertices.update(vertices)
        if len(set(vertices)) != len(vertices):
            repeated_faces.append(polygon.index)
        if not math.isfinite(float(polygon.area)) or polygon.area <= strict_area:
            zero_area_faces.append(polygon.index)
        if vertices:
            rotations = [vertices[offset:] + vertices[:offset] for offset in range(len(vertices))]
            face_key = (min(rotations), int(polygon.material_index))
            if face_key in seen_faces:
                duplicate_faces.append(
                    {"polygon": polygon.index, "duplicate_of": seen_faces[face_key]}
                )
            else:
                seen_faces[face_key] = polygon.index
        for first, second in _face_edges(vertices):
            key = tuple(sorted((first, second)))
            edge_faces[key].append(polygon.index)
            oriented_edges[key].append((first, second))

    boundary = [edge for edge, faces in edge_faces.items() if len(faces) == 1]
    non_manifold = [edge for edge, faces in edge_faces.items() if len(faces) > 2]
    winding_conflicts = []
    for edge, orientations in oriented_edges.items():
        if len(orientations) != 2:
            continue
        first, second = orientations
        if first == second:
            winding_conflicts.append(edge)

    mesh_edge_keys = {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge
        for edge in mesh.edges
    }
    loose_edges = [
        edge.index for key, edge in mesh_edge_keys.items() if key not in edge_faces
    ]
    loose_vertices = [
        vertex.index for vertex in mesh.vertices if vertex.index not in used_vertices
    ]
    zero_length_edges = [
        edge.index
        for edge in mesh.edges
        if (mesh.vertices[edge.vertices[0]].co - mesh.vertices[edge.vertices[1]].co).length_squared
        == 0.0
    ]
    return {
        "edge_faces": edge_faces,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "winding_conflicts": winding_conflicts,
        "loose_edges": loose_edges,
        "loose_vertices": loose_vertices,
        "zero_length_edges": zero_length_edges,
        "zero_area_faces": zero_area_faces,
        "repeated_index_faces": repeated_faces,
        "duplicate_faces": duplicate_faces,
    }


def _component_sizes(mesh):
    count = len(mesh.vertices)
    parent = list(range(count))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for polygon in mesh.polygons:
        vertices = polygon.vertices
        if not vertices:
            continue
        first_root = root(vertices[0])
        for vertex in vertices[1:]:
            other_root = root(vertex)
            if first_root != other_root:
                parent[other_root] = first_root
                first_root = root(first_root)
    sizes = defaultdict(int)
    for index in range(count):
        sizes[root(index)] += 1
    return sorted(sizes.values(), reverse=True)


def _boundary_loops(boundary_edges):
    adjacency = defaultdict(list)
    for first, second in boundary_edges:
        adjacency[first].append(second)
        adjacency[second].append(first)
    remaining = {tuple(sorted(edge)) for edge in boundary_edges}
    loops = []
    while remaining:
        first_edge = min(remaining)
        remaining.remove(first_edge)
        path = [first_edge[0], first_edge[1]]
        previous, current = first_edge
        while True:
            choices = [
                vertex
                for vertex in adjacency[current]
                if tuple(sorted((current, vertex))) in remaining
            ]
            if not choices:
                break
            following = min(
                choices,
                key=lambda vertex: (vertex == previous, vertex),
            )
            remaining.remove(tuple(sorted((current, following))))
            path.append(following)
            previous, current = current, following
            if current == path[0]:
                break
        loops.append(
            {
                "vertices": path,
                "edge_count": len(path) - 1,
                "closed": len(path) > 2 and path[0] == path[-1],
            }
        )
    loops.sort(key=lambda item: item["edge_count"], reverse=True)
    return loops


def _duplicate_positions(mesh):
    groups = defaultdict(list)
    for vertex in mesh.vertices:
        groups[tuple(float(component) for component in vertex.co)].append(vertex.index)
    duplicates = [indices for indices in groups.values() if len(indices) > 1]
    duplicates.sort(key=lambda indices: indices[0])
    return duplicates


def _near_duplicate_statistics(mesh, diagonal):
    points = [vertex.co.copy() for vertex in mesh.vertices]
    if not points:
        return []
    tree = KDTree(len(points))
    for index, point in enumerate(points):
        tree.insert(point, index)
    tree.balance()
    statistics = []
    for factor in (1.0e-7, 1.0e-6, 1.0e-5):
        threshold = max(diagonal * factor, 1.0e-12)
        pairs = 0
        affected = set()
        for index, point in enumerate(points):
            for _co, other, distance in tree.find_range(point, threshold):
                if other <= index or distance == 0.0:
                    continue
                pairs += 1
                affected.add(index)
                affected.add(other)
        statistics.append(
            {
                "relative_factor": factor,
                "distance": threshold,
                "non_exact_pairs": pairs,
                "affected_vertices": len(affected),
            }
        )
    return statistics


def _triangle_metrics(mesh, matrix):
    area = 0.0
    volume = 0.0
    for polygon in mesh.polygons:
        vertices = [matrix @ mesh.vertices[index].co for index in polygon.vertices]
        if len(vertices) < 3:
            continue
        origin = vertices[0]
        for index in range(1, len(vertices) - 1):
            first, second = vertices[index], vertices[index + 1]
            area += (first - origin).cross(second - origin).length * 0.5
            volume += origin.dot(first.cross(second)) / 6.0
    return area, volume


def _attribute_value(item):
    for name in ("value", "vector", "color", "byte_color", "quaternion", "matrix"):
        if not hasattr(item, name):
            continue
        value = getattr(item, name)
        if isinstance(value, (bool, int, float, str)):
            return value
        try:
            return tuple(float(component) for component in value)
        except (TypeError, ValueError):
            try:
                return tuple(
                    tuple(float(component) for component in row) for row in value
                )
            except (TypeError, ValueError):
                continue
    raise ValueError(f"Unsupported Blender attribute element: {type(item).__name__}")


def snapshot_attributes(mesh):
    """Capture generic mesh attributes without duplicating UV-layer payloads."""

    uv_names = {layer.name for layer in mesh.uv_layers}
    ignored = {
        "position",
        ".edge_verts",
        "material_index",
        "sharp_face",
        "sharp_edge",
        "custom_normal",
        "uv_seam",
    }
    snapshots = []
    for attribute in mesh.attributes:
        if (
            attribute.name in uv_names
            or attribute.name in ignored
            or attribute.name.startswith(".")
        ):
            continue
        snapshots.append(
            {
                "name": attribute.name,
                "data_type": attribute.data_type,
                "domain": attribute.domain,
                "values": [_attribute_value(item) for item in attribute.data],
            }
        )
    return snapshots


def corner_snapshot(mesh):
    mesh.calc_loop_triangles()
    normals = [tuple(float(value) for value in item.vector) for item in mesh.corner_normals]
    return {
        "polygon_vertices": [list(polygon.vertices) for polygon in mesh.polygons],
        "material_indices": [int(polygon.material_index) for polygon in mesh.polygons],
        "polygon_smooth": [bool(polygon.use_smooth) for polygon in mesh.polygons],
        "uv_layers": [
            {
                "name": layer.name,
                "active_render": bool(layer.active_render),
                "uv": [tuple(float(value) for value in item.vector) for item in layer.uv],
            }
            for layer in mesh.uv_layers
        ],
        "corner_normals": normals,
    }


def _texture_inventory(obj):
    materials = []
    images = {}
    for slot_index, slot in enumerate(obj.material_slots):
        material = slot.material
        entry = {
            "slot": slot_index,
            "material": material.name if material else None,
            "use_nodes": bool(material and material.use_nodes),
            "images": [],
        }
        if material and material.node_tree:
            for node in material.node_tree.nodes:
                if node.bl_idname != "ShaderNodeTexImage" or node.image is None:
                    continue
                image = node.image
                entry["images"].append(
                    {
                        "node": node.name,
                        "image": image.name,
                        "colorspace": image.colorspace_settings.name,
                    }
                )
                images[image.name] = {
                    "name": image.name,
                    "source": image.source,
                    "size": [int(value) for value in image.size],
                    "packed": image.packed_file is not None,
                    "filepath": image.filepath,
                }
        materials.append(entry)
    return {"materials": materials, "images": list(images.values())}


def _hash_string(digest, value):
    encoded = str(value).encode("utf-8")
    digest.update(struct.pack("<I", len(encoded)))
    digest.update(encoded)


def geometry_fingerprint(obj):
    """Hash authoritative ordered geometry and face-corner production data."""

    mesh = obj.data
    corner = corner_snapshot(mesh)
    digest = hashlib.sha256()
    digest.update(struct.pack("<I", FINGERPRINT_SCHEMA))
    for vertex in mesh.vertices:
        digest.update(struct.pack("<3f", *(float(value) for value in vertex.co)))
    digest.update(b"FACES")
    for polygon in mesh.polygons:
        digest.update(struct.pack("<II", len(polygon.vertices), polygon.material_index))
        for index in polygon.vertices:
            digest.update(struct.pack("<I", int(index)))
    digest.update(b"UVS")
    for layer in corner["uv_layers"]:
        _hash_string(digest, layer["name"])
        digest.update(struct.pack("<?", layer["active_render"]))
        for uv in layer["uv"]:
            digest.update(struct.pack("<2f", *uv))
    digest.update(b"NORMALS")
    for normal in corner["corner_normals"]:
        digest.update(struct.pack("<3f", *normal))
    digest.update(b"MATERIALS")
    for slot in obj.material_slots:
        material = slot.material
        _hash_string(digest, material.name if material else "")
    return digest.hexdigest()


def analyze_geometry(obj, include_corner_data=True, include_near_duplicates=True):
    """Return a complete non-mutating raw or production mesh analysis."""

    if obj is None or obj.type != "MESH":
        raise ValueError("Choose a mesh object for SPAR3D analysis.")
    mesh = obj.data
    if not mesh.vertices or not mesh.polygons:
        raise ValueError("The SPAR3D mesh has no renderable geometry.")
    mesh.calc_loop_triangles()
    local_points = [vertex.co.copy() for vertex in mesh.vertices]
    world_points = [obj.matrix_world @ point for point in local_points]
    local_bounds = _bounds(local_points)
    world_bounds = _bounds(world_points)
    diagonal = Vector(local_bounds["extents"]).length
    topology = _topology(mesh)
    components = _component_sizes(mesh)
    boundary_loops = _boundary_loops(topology["boundary_edges"])
    duplicates = _duplicate_positions(mesh)
    local_area, local_volume = _triangle_metrics(mesh, Matrix.Identity(4))
    world_area, world_volume = _triangle_metrics(mesh, obj.matrix_world)
    corner = corner_snapshot(mesh)
    hierarchy = []
    current = obj
    while current is not None:
        hierarchy.append(
            {
                "object": current.name,
                "type": current.type,
                "data": current.data.name if current.data else None,
                "parent": current.parent.name if current.parent else None,
                "matrix_local": _matrix(current.matrix_local),
                "matrix_world": _matrix(current.matrix_world),
            }
        )
        current = current.parent
    report = {
        "schema": ANALYSIS_SCHEMA,
        "object": obj.name,
        "mesh": mesh.name,
        "hierarchy": hierarchy,
        "transform": {
            "matrix_local": _matrix(obj.matrix_local),
            "matrix_world": _matrix(obj.matrix_world),
            "location": _vector(obj.location),
            "rotation_mode": obj.rotation_mode,
            "rotation_euler": _vector(obj.rotation_euler),
            "scale": _vector(obj.scale),
        },
        "counts": {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "loops": len(mesh.loops),
            "polygons": len(mesh.polygons),
            "triangles": len(mesh.loop_triangles),
        },
        "material_slots": [
            slot.material.name if slot.material else None for slot in obj.material_slots
        ],
        "face_material_indices": corner["material_indices"],
        "uv_layers": [layer["name"] for layer in corner["uv_layers"]],
        "color_attributes": [
            {
                "name": attribute.name,
                "domain": attribute.domain,
                "data_type": attribute.data_type,
            }
            for attribute in mesh.color_attributes
        ],
        "generic_attributes": snapshot_attributes(mesh),
        "vertex_normals": [_vector(vertex.normal) for vertex in mesh.vertices],
        "polygon_normals": [_vector(polygon.normal) for polygon in mesh.polygons],
        "sharp_edges": [edge.index for edge in mesh.edges if edge.use_edge_sharp],
        "seams": [edge.index for edge in mesh.edges if edge.use_seam],
        "bounds_local": local_bounds,
        "bounds_world": world_bounds,
        "surface_area_local": local_area,
        "surface_area_world": world_area,
        "signed_volume_local": local_volume,
        "signed_volume_world": world_volume,
        "winding_consistent": not topology["winding_conflicts"],
        "winding_conflict_edges": [list(edge) for edge in topology["winding_conflicts"]],
        "connected_components": len(components),
        "component_sizes": components,
        "loose_vertices": topology["loose_vertices"],
        "loose_edges": topology["loose_edges"],
        "zero_length_edges": topology["zero_length_edges"],
        "zero_area_faces": topology["zero_area_faces"],
        "repeated_index_faces": topology["repeated_index_faces"],
        "exact_duplicate_position_groups": duplicates,
        "exact_duplicate_position_group_count": len(duplicates),
        "exact_duplicate_vertices": sum(len(group) - 1 for group in duplicates),
        "boundary_edges": [list(edge) for edge in topology["boundary_edges"]],
        "boundary_edge_count": len(topology["boundary_edges"]),
        "boundary_loops": boundary_loops,
        "boundary_loop_count": len(boundary_loops),
        "non_manifold_edges": [list(edge) for edge in topology["non_manifold_edges"]],
        "non_manifold_edge_count": len(topology["non_manifold_edges"]),
        "duplicate_faces": topology["duplicate_faces"],
        "watertight": not topology["boundary_edges"] and not topology["non_manifold_edges"],
        "euler_characteristic": len(mesh.vertices) - len(mesh.edges) + len(mesh.polygons),
        "textures": _texture_inventory(obj),
        "self_overlap_warning": "NOT_EVALUATED_DIAGNOSTIC_ONLY",
        "fingerprint": geometry_fingerprint(obj),
    }
    if include_corner_data:
        report["corner_data"] = corner
    else:
        report["corner_data_hash"] = hashlib.sha256(
            json.dumps(corner, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    report["near_duplicate_statistics"] = (
        _near_duplicate_statistics(mesh, diagonal) if include_near_duplicates else []
    )
    return report
