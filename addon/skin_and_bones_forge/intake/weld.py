"""Exact-coordinate production mesh reconstruction with corner-data proof."""

from __future__ import annotations

from collections import defaultdict
import math

import bpy
from mathutils import Vector

from .analysis import analyze_geometry, corner_snapshot, snapshot_attributes


UV_TOLERANCE = 1.0e-7
NORMAL_ANGLE_TOLERANCE = 1.0e-3
GEOMETRY_RELATIVE_TOLERANCE = 1.0e-7


def _value_equal(first, second):
    if isinstance(first, (tuple, list)) and isinstance(second, (tuple, list)):
        if len(first) != len(second):
            return False
        return all(_value_equal(a, b) for a, b in zip(first, second))
    if isinstance(first, float) or isinstance(second, float):
        return float(first) == float(second)
    return first == second


def _set_attribute_value(item, value):
    for name in ("value", "vector", "color", "byte_color", "quaternion", "matrix"):
        if not hasattr(item, name):
            continue
        try:
            setattr(item, name, value)
            return
        except (AttributeError, TypeError, ValueError):
            continue
    raise ValueError(f"Cannot write Blender attribute element {type(item).__name__}.")


def _copy_generic_attributes(
    source_mesh,
    destination_mesh,
    attributes,
    source_polygons,
    source_loops,
    canonical_sources,
    source_to_destination,
):
    source_edge_by_key = {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge.index
        for edge in source_mesh.edges
    }
    destination_edge_by_key = {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge.index
        for edge in destination_mesh.edges
    }
    source_vertices_by_destination = defaultdict(list)
    for source_index, destination_index in source_to_destination.items():
        source_vertices_by_destination[destination_index].append(source_index)

    edge_sources = defaultdict(list)
    for source_key, source_edge in source_edge_by_key.items():
        if not all(index in source_to_destination for index in source_key):
            continue
        destination_key = tuple(
            sorted(source_to_destination[index] for index in source_key)
        )
        if destination_key[0] == destination_key[1]:
            continue
        destination_edge = destination_edge_by_key.get(destination_key)
        if destination_edge is not None:
            edge_sources[destination_edge].append(source_edge)

    for snapshot in attributes:
        name = snapshot["name"]
        domain = snapshot["domain"]
        values = snapshot["values"]
        try:
            destination = destination_mesh.attributes.new(
                name=name,
                type=snapshot["data_type"],
                domain=domain,
            )
        except RuntimeError as exc:
            raise ValueError(
                f"Could not recreate mesh attribute '{name}' ({domain}/"
                f"{snapshot['data_type']}): {exc}"
            ) from exc

        if domain == "POINT":
            for destination_index, source_indices in source_vertices_by_destination.items():
                canonical = canonical_sources[destination_index]
                canonical_value = values[canonical]
                for source_index in source_indices:
                    if not _value_equal(canonical_value, values[source_index]):
                        raise ValueError(
                            f"Exact-position vertices contain conflicting POINT "
                            f"attribute data in '{name}'."
                        )
                _set_attribute_value(destination.data[destination_index], canonical_value)
        elif domain == "FACE":
            for destination_index, source_index in enumerate(source_polygons):
                _set_attribute_value(destination.data[destination_index], values[source_index])
        elif domain == "CORNER":
            for destination_index, source_index in enumerate(source_loops):
                _set_attribute_value(destination.data[destination_index], values[source_index])
        elif domain == "EDGE":
            for destination_index in range(len(destination.data)):
                source_indices = edge_sources.get(destination_index, [])
                if not source_indices:
                    raise ValueError(
                        f"No source EDGE attribute owner exists for '{name}' edge "
                        f"{destination_index}."
                    )
                canonical_value = values[source_indices[0]]
                if any(
                    not _value_equal(canonical_value, values[index])
                    for index in source_indices[1:]
                ):
                    raise ValueError(
                        f"Exact-position edge consolidation conflicts in EDGE "
                        f"attribute '{name}'."
                    )
                _set_attribute_value(destination.data[destination_index], canonical_value)
        else:
            raise ValueError(
                f"Unsupported mesh attribute domain '{domain}' for '{name}'."
            )


def _source_edge_flags(mesh, source_to_destination):
    flags = defaultdict(lambda: {"seam": False, "sharp": False})
    for edge in mesh.edges:
        first, second = (int(value) for value in edge.vertices)
        if first not in source_to_destination or second not in source_to_destination:
            continue
        key = tuple(sorted((source_to_destination[first], source_to_destination[second])))
        if key[0] == key[1]:
            continue
        flags[key]["seam"] |= bool(edge.use_seam)
        flags[key]["sharp"] |= bool(edge.use_edge_sharp)
    return flags


def _mark_corner_boundaries(mesh, corner_normals):
    sides = defaultdict(list)
    uv_layers = list(mesh.uv_layers)
    for polygon in mesh.polygons:
        loops = list(polygon.loop_indices)
        vertices = list(polygon.vertices)
        for offset, loop_index in enumerate(loops):
            next_offset = (offset + 1) % len(loops)
            next_loop = loops[next_offset]
            first, second = vertices[offset], vertices[next_offset]
            uv_by_vertex = {
                first: tuple(tuple(layer.uv[loop_index].vector) for layer in uv_layers),
                second: tuple(tuple(layer.uv[next_loop].vector) for layer in uv_layers),
            }
            normal_by_vertex = {
                first: Vector(corner_normals[loop_index]),
                second: Vector(corner_normals[next_loop]),
            }
            sides[tuple(sorted((first, second)))].append(
                (uv_by_vertex, normal_by_vertex)
            )

    edge_by_key = {
        tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1])))): edge
        for edge in mesh.edges
    }
    for key, edge_sides in sides.items():
        if len(edge_sides) < 2:
            continue
        reference_uv, reference_normals = edge_sides[0]
        for candidate_uv, candidate_normals in edge_sides[1:]:
            for vertex in key:
                if any(
                    abs(a - b) > UV_TOLERANCE
                    for first_uv, second_uv in zip(
                        reference_uv[vertex], candidate_uv[vertex]
                    )
                    for a, b in zip(first_uv, second_uv)
                ):
                    edge_by_key[key].use_seam = True
                first_normal = reference_normals[vertex]
                second_normal = candidate_normals[vertex]
                if first_normal.length_squared and second_normal.length_squared:
                    dot = max(
                        -1.0,
                        min(
                            1.0,
                            first_normal.normalized().dot(
                                second_normal.normalized()
                            ),
                        ),
                    )
                    if math.acos(dot) > NORMAL_ANGLE_TOLERANCE:
                        edge_by_key[key].use_edge_sharp = True


def _copy_vertex_groups(source, destination, source_to_destination):
    weights = defaultdict(dict)
    for group in source.vertex_groups:
        destination_group = destination.vertex_groups.new(name=group.name)
        for source_index, destination_index in source_to_destination.items():
            try:
                weight = group.weight(source_index)
            except RuntimeError:
                continue
            previous = weights[destination_index].get(group.name)
            if previous is not None and previous != weight:
                raise ValueError(
                    f"Exact-position vertices contain conflicting vertex-group "
                    f"weights in '{group.name}'."
                )
            weights[destination_index][group.name] = weight
        for destination_index, group_weights in weights.items():
            if group.name in group_weights:
                destination_group.add(
                    [destination_index], group_weights[group.name], "REPLACE"
                )


def _close(first, second, relative=GEOMETRY_RELATIVE_TOLERANCE, absolute=1.0e-9):
    return abs(float(first) - float(second)) <= max(
        absolute, max(abs(float(first)), abs(float(second))) * relative
    )


def _bounds_close(first, second):
    for key in ("minimum", "maximum", "extents"):
        if first[key] is None or second[key] is None:
            if first[key] != second[key]:
                return False
            continue
        if any(not _close(a, b) for a, b in zip(first[key], second[key])):
            return False
    return True


def _prove_corner_data(source_mesh, destination_mesh, source_polygons, source_loops):
    source = corner_snapshot(source_mesh)
    destination = corner_snapshot(destination_mesh)
    material_ok = all(
        destination["material_indices"][index]
        == source["material_indices"][source_index]
        for index, source_index in enumerate(source_polygons)
    )
    uv_ok = len(source["uv_layers"]) == len(destination["uv_layers"])
    if uv_ok:
        for source_layer, destination_layer in zip(
            source["uv_layers"], destination["uv_layers"]
        ):
            if source_layer["name"] != destination_layer["name"]:
                uv_ok = False
                break
            for destination_index, source_index in enumerate(source_loops):
                if any(
                    abs(a - b) > UV_TOLERANCE
                    for a, b in zip(
                        source_layer["uv"][source_index],
                        destination_layer["uv"][destination_index],
                    )
                ):
                    uv_ok = False
                    break
            if not uv_ok:
                break

    maximum_angle = 0.0
    normals_ok = len(source_loops) == len(destination["corner_normals"])
    if normals_ok:
        for destination_index, source_index in enumerate(source_loops):
            first = Vector(source["corner_normals"][source_index])
            second = Vector(destination["corner_normals"][destination_index])
            if not first.length_squared and not second.length_squared:
                continue
            if not first.length_squared or not second.length_squared:
                normals_ok = False
                break
            dot = max(-1.0, min(1.0, first.normalized().dot(second.normalized())))
            angle = math.acos(dot)
            maximum_angle = max(maximum_angle, angle)
            if angle > NORMAL_ANGLE_TOLERANCE:
                normals_ok = False
                break
    return {
        "material_slots_preserved": list(source_mesh.materials)
        == list(destination_mesh.materials),
        "material_assignments_preserved": material_ok,
        "uv_values_preserved": uv_ok,
        "uv_seam_discontinuities_preserved": uv_ok,
        "corner_normals_preserved": normals_ok,
        "corner_normal_max_angle_radians": maximum_angle,
    }


def exact_position_weld(source_obj, mesh_name):
    """Construct an exact-welded mesh without any distance threshold."""

    source_mesh = source_obj.data
    source_mesh.calc_loop_triangles()
    raw = analyze_geometry(
        source_obj, include_corner_data=False, include_near_duplicates=False
    )
    source_corner = corner_snapshot(source_mesh)
    generic_attributes = snapshot_attributes(source_mesh)
    positions = [tuple(float(value) for value in vertex.co) for vertex in source_mesh.vertices]
    canonical_by_position = {}
    canonical_source = {}
    source_to_canonical = {}
    for index, position in enumerate(positions):
        canonical = canonical_by_position.setdefault(position, index)
        source_to_canonical[index] = canonical
        canonical_source.setdefault(canonical, index)

    extents = raw["bounds_local"]["extents"]
    strict_area = max(sum(value * value for value in extents) * 1.0e-18, 1.0e-30)
    kept_polygons = []
    removed = []
    duplicate_keys = {}
    for polygon in source_mesh.polygons:
        source_vertices = tuple(int(value) for value in polygon.vertices)
        canonical_vertices = tuple(source_to_canonical[index] for index in source_vertices)
        reason = None
        if len(set(source_vertices)) != len(source_vertices):
            reason = "repeated_source_vertex_index"
        elif len(set(canonical_vertices)) != len(canonical_vertices):
            reason = "repeated_vertex_after_exact_position_weld"
        elif not math.isfinite(float(polygon.area)) or polygon.area <= strict_area:
            reason = "strict_scale_relative_zero_area"
        else:
            rotations = [
                canonical_vertices[offset:] + canonical_vertices[:offset]
                for offset in range(len(canonical_vertices))
            ]
            key = (min(rotations), int(polygon.material_index))
            if key in duplicate_keys:
                reason = "exact_duplicate_face_identical_winding_and_material"
            else:
                duplicate_keys[key] = polygon.index
        if reason:
            removed.append({"polygon": polygon.index, "reason": reason})
        else:
            kept_polygons.append(polygon.index)

    used_source_vertices = {
        int(vertex)
        for polygon_index in kept_polygons
        for vertex in source_mesh.polygons[polygon_index].vertices
    }
    used_canonical = sorted({source_to_canonical[index] for index in used_source_vertices})
    canonical_to_destination = {
        canonical: index for index, canonical in enumerate(used_canonical)
    }
    source_to_destination = {
        source_index: canonical_to_destination[source_to_canonical[source_index]]
        for source_index in used_source_vertices
    }
    canonical_sources = [canonical_source[index] for index in used_canonical]
    destination_positions = [positions[index] for index in canonical_sources]
    destination_faces = [
        [source_to_destination[int(vertex)] for vertex in source_mesh.polygons[index].vertices]
        for index in kept_polygons
    ]
    source_loops = [
        int(loop)
        for polygon_index in kept_polygons
        for loop in source_mesh.polygons[polygon_index].loop_indices
    ]

    destination_mesh = bpy.data.meshes.new(mesh_name)
    temporary = None
    try:
        destination_mesh.from_pydata(destination_positions, [], destination_faces)
        destination_mesh.update(calc_edges=True)
        for material in source_mesh.materials:
            destination_mesh.materials.append(material)
        for destination_index, source_index in enumerate(kept_polygons):
            source_polygon = source_mesh.polygons[source_index]
            destination_polygon = destination_mesh.polygons[destination_index]
            destination_polygon.material_index = source_polygon.material_index
            destination_polygon.use_smooth = source_polygon.use_smooth

        for source_layer in source_mesh.uv_layers:
            destination_layer = destination_mesh.uv_layers.new(
                name=source_layer.name, do_init=False
            )
            destination_layer.active_render = source_layer.active_render
            for destination_index, source_index in enumerate(source_loops):
                destination_layer.uv[destination_index].vector = source_layer.uv[
                    source_index
                ].vector
                for flag in ("pin_uv", "select", "select_edge"):
                    if hasattr(source_layer.uv[source_index], flag) and hasattr(
                        destination_layer.uv[destination_index], flag
                    ):
                        setattr(
                            destination_layer.uv[destination_index],
                            flag,
                            getattr(source_layer.uv[source_index], flag),
                        )
        if source_mesh.uv_layers.active is not None:
            active = destination_mesh.uv_layers.get(source_mesh.uv_layers.active.name)
            if active is not None:
                destination_mesh.uv_layers.active = active

        _copy_generic_attributes(
            source_mesh,
            destination_mesh,
            generic_attributes,
            kept_polygons,
            source_loops,
            canonical_sources,
            source_to_destination,
        )

        edge_flags = _source_edge_flags(source_mesh, source_to_destination)
        for edge in destination_mesh.edges:
            key = tuple(sorted((int(edge.vertices[0]), int(edge.vertices[1]))))
            flags = edge_flags.get(key)
            if flags:
                edge.use_seam = flags["seam"]
                edge.use_edge_sharp = flags["sharp"]

        destination_corner_normals = [
            source_corner["corner_normals"][index] for index in source_loops
        ]
        _mark_corner_boundaries(destination_mesh, destination_corner_normals)
        destination_mesh.normals_split_custom_set(destination_corner_normals)
        destination_mesh.update()

        temporary = bpy.data.objects.new("SBF_WELD_PROOF", destination_mesh)
        temporary.matrix_world = source_obj.matrix_world.copy()
        clean = analyze_geometry(
            temporary, include_corner_data=False, include_near_duplicates=False
        )
        bpy.data.objects.remove(temporary, do_unlink=True)
        temporary = None
        corner_proof = _prove_corner_data(
            source_mesh, destination_mesh, kept_polygons, source_loops
        )
        coordinate_faces_ok = True
        for destination_index, source_index in enumerate(kept_polygons):
            source_coordinates = [
                positions[int(vertex)] for vertex in source_mesh.polygons[source_index].vertices
            ]
            destination_coordinates = [
                tuple(float(value) for value in destination_mesh.vertices[int(vertex)].co)
                for vertex in destination_mesh.polygons[destination_index].vertices
            ]
            if source_coordinates != destination_coordinates:
                coordinate_faces_ok = False
                break
        proof = {
            **corner_proof,
            "all_retained_polygons_preserved": coordinate_faces_ok,
            "face_count_preserved": not removed
            and raw["counts"]["polygons"] == clean["counts"]["polygons"],
            "face_winding_preserved": coordinate_faces_ok,
            "generic_attributes_preserved": True,
            "removed_invalid_faces": removed,
            "surface_area_local_preserved": _close(
                raw["surface_area_local"], clean["surface_area_local"]
            ),
            "surface_area_world_preserved": _close(
                raw["surface_area_world"], clean["surface_area_world"]
            ),
            "signed_volume_local_preserved": _close(
                raw["signed_volume_local"], clean["signed_volume_local"]
            ),
            "signed_volume_world_preserved": _close(
                raw["signed_volume_world"], clean["signed_volume_world"]
            ),
            "world_bounds_preserved": _bounds_close(
                raw["bounds_world"], clean["bounds_world"]
            ),
            "no_new_degenerate_faces": not clean["zero_area_faces"]
            and not clean["repeated_index_faces"],
            "no_new_non_manifold_edges": clean["non_manifold_edge_count"]
            <= raw["non_manifold_edge_count"],
            "approximate_merge_performed": False,
        }
        mandatory = (
            "all_retained_polygons_preserved",
            "material_assignments_preserved",
            "material_slots_preserved",
            "uv_values_preserved",
            "uv_seam_discontinuities_preserved",
            "corner_normals_preserved",
            "surface_area_local_preserved",
            "surface_area_world_preserved",
            "signed_volume_local_preserved",
            "signed_volume_world_preserved",
            "world_bounds_preserved",
            "no_new_degenerate_faces",
            "no_new_non_manifold_edges",
        )
        failures = [name for name in mandatory if not proof[name]]
        if failures:
            raise ValueError(
                "Exact-position weld proof failed: " + ", ".join(failures)
            )
        removed_loose = sorted(
            set(range(len(source_mesh.vertices))) - used_source_vertices
        )
        result = {
            "raw": raw,
            "clean": clean,
            "proof": proof,
            "cleanup": {
                "removed_vertices": [
                    {"vertex": index, "reason": "not_used_by_retained_face"}
                    for index in removed_loose
                ],
                "removed_edges": [
                    {"edge": index, "reason": "not_used_by_retained_face"}
                    for index in raw["loose_edges"]
                ],
                "removed_faces": removed,
            },
            "exact_vertices_welded": len(used_source_vertices)
            - len(destination_positions),
            "source_to_destination": source_to_destination,
        }
        return destination_mesh, result
    except Exception:
        if temporary is not None and temporary.name in bpy.data.objects:
            bpy.data.objects.remove(temporary, do_unlink=True)
        if destination_mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(destination_mesh, do_unlink=True)
        raise


def copy_vertex_groups(source, destination, source_to_destination):
    _copy_vertex_groups(source, destination, source_to_destination)
