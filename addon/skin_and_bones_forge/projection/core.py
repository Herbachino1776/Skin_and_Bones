"""Camera projection UVs and identity/occlusion weight generation."""

from __future__ import annotations

import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

from ..constants import (
    ORIGINAL_MATERIAL_PROPERTY,
    ORIGINAL_SLOT_PROPERTY,
    ORIGINAL_UV_PROPERTY,
    PREVIEW_MATERIAL_PREFIX,
    PROJECTION_CAMERA_PREFIX,
    PROJECTION_UV_PREFIX,
    REPAIR_PREVIEW_MATERIAL_PROPERTY,
    REPAIR_PREVIEW_SLOT_PROPERTY,
    TEMP_COLLECTION,
    TEMPORARY_PROPERTY,
    VERIFY_PREFIX,
    VIEW_NAMES,
    VIEW_WEIGHT_PACK_PREFIX,
    WEIGHT_ATTRIBUTE_PREFIX,
    SOURCE_OWNER_PROPERTY,
)


def axis_vector(axis_name):
    sign = -1.0 if axis_name.startswith("-") else 1.0
    axis = axis_name[-1]
    return {
        "X": Vector((sign, 0.0, 0.0)),
        "Y": Vector((0.0, sign, 0.0)),
        "Z": Vector((0.0, 0.0, sign)),
    }[axis]


def view_directions(settings):
    forward = axis_vector(settings.forward_axis)
    up = axis_vector(settings.up_axis)
    if abs(forward.dot(up)) > 0.999:
        raise ValueError("Forward Axis and Up Axis cannot be parallel.")
    up = (up - forward * forward.dot(up)).normalized()
    right = forward.cross(up).normalized()
    left = -right
    return {
        "front": forward,
        "back": -forward,
        "left": left,
        "right": right,
        "front_left": (forward + left).normalized(),
        "front_right": (forward + right).normalized(),
        "up": up,
    }


def world_bounds(obj, directions=None):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    minimum = Vector(
        (
            min(point.x for point in points),
            min(point.y for point in points),
            min(point.z for point in points),
        )
    )
    maximum = Vector(
        (
            max(point.x for point in points),
            max(point.y for point in points),
            max(point.z for point in points),
        )
    )
    result = {
        "points": points,
        "minimum": minimum,
        "maximum": maximum,
        "center": (minimum + maximum) * 0.5,
        "max_dimension": max(maximum - minimum),
    }
    if directions:
        for key in ("up", "front", "right"):
            direction = directions[key]
            values = [point.dot(direction) for point in points]
            result[f"{key}_min"] = min(values)
            result[f"{key}_max"] = max(values)
            result[f"{key}_span"] = max(max(values) - min(values), 1.0e-8)
    return result


def _projection_collection(scene):
    collection = bpy.data.collections.get(TEMP_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(TEMP_COLLECTION)
    if collection.name not in {child.name for child in scene.collection.children}:
        scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _camera_rotation(outward, up):
    camera_z = outward.normalized()
    camera_y = up.normalized()
    camera_x = camera_y.cross(camera_z).normalized()
    return Matrix((camera_x, camera_y, camera_z)).transposed().to_euler()


def _remove_datablock_if_unused(datablock_collection, datablock):
    if datablock is not None and datablock.users == 0:
        datablock_collection.remove(datablock)


def cleanup_temporary_data(context, target=None, production_material=None):
    """Restore production state and remove add-on-owned temporary datablocks."""

    if target is not None and target.type == "MESH":
        original_name = target.get(ORIGINAL_MATERIAL_PROPERTY, "")
        slot_index = int(target.get(ORIGINAL_SLOT_PROPERTY, -1))
        if slot_index < 0:
            slot_index = int(target.get(REPAIR_PREVIEW_SLOT_PROPERTY, -1))
        original = production_material or bpy.data.materials.get(original_name)
        if 0 <= slot_index < len(target.material_slots) and original is not None:
            target.material_slots[slot_index].material = original

        original_uv = target.get(ORIGINAL_UV_PROPERTY, "")
        if original_uv and target.data.uv_layers.get(original_uv):
            target.data.uv_layers.active = target.data.uv_layers[original_uv]
            target.data.uv_layers[original_uv].active_render = True

        for uv_layer in list(target.data.uv_layers):
            if uv_layer.name.startswith(PROJECTION_UV_PREFIX):
                target.data.uv_layers.remove(uv_layer)
        for attribute in list(target.data.attributes):
            if attribute.name.startswith(WEIGHT_ATTRIBUTE_PREFIX):
                target.data.attributes.remove(attribute)

        for key in (
            ORIGINAL_MATERIAL_PROPERTY,
            ORIGINAL_SLOT_PROPERTY,
            ORIGINAL_UV_PROPERTY,
            REPAIR_PREVIEW_SLOT_PROPERTY,
            REPAIR_PREVIEW_MATERIAL_PROPERTY,
        ):
            if key in target:
                del target[key]

    for obj in list(bpy.data.objects):
        if (
            obj.name.startswith(PROJECTION_CAMERA_PREFIX)
            or obj.name.startswith(VERIFY_PREFIX)
            or obj.get(TEMPORARY_PROPERTY, False)
        ):
            data = obj.data
            data_collection = None
            if obj.type == "CAMERA":
                data_collection = bpy.data.cameras
            elif obj.type == "LIGHT":
                data_collection = bpy.data.lights
            bpy.data.objects.remove(obj, do_unlink=True)
            if data_collection is not None:
                _remove_datablock_if_unused(data_collection, data)

    for material in list(bpy.data.materials):
        if material.name.startswith(PREVIEW_MATERIAL_PREFIX) or material.get(
            TEMPORARY_PROPERTY, False
        ):
            bpy.data.materials.remove(material, do_unlink=True)

    for image in list(bpy.data.images):
        if image.get(SOURCE_OWNER_PROPERTY, False) and image.get(
            TEMPORARY_PROPERTY, False
        ):
            bpy.data.images.remove(image, do_unlink=True)

    collection = bpy.data.collections.get(TEMP_COLLECTION)
    if collection is not None and not collection.objects:
        bpy.data.collections.remove(collection)

    if target is not None:
        context.view_layer.objects.active = target


def _create_projection_cameras(scene, settings, bounds, directions):
    collection = _projection_collection(scene)
    height = bounds["up_span"]
    ortho_scale = height / max(settings.framing_ratio, 1.0e-4)
    distance = max(bounds["max_dimension"] * 4.0, height * 2.0, 0.1)
    cameras = {}

    for name in VIEW_NAMES:
        direction = directions[name]
        data = bpy.data.cameras.new(f"{PROJECTION_CAMERA_PREFIX}{name}")
        camera = bpy.data.objects.new(f"{PROJECTION_CAMERA_PREFIX}{name}", data)
        collection.objects.link(camera)
        camera[TEMPORARY_PROPERTY] = True
        camera["sbf_view"] = name
        data.type = "ORTHO"
        data.ortho_scale = ortho_scale
        camera.location = bounds["center"] + direction * distance
        camera.rotation_euler = _camera_rotation(direction, directions["up"])
        # Keep cameras evaluated until world_to_camera_view has consumed their
        # transforms. A camera hidden before the view-layer update can retain an
        # identity matrix in background mode.
        camera.hide_viewport = False
        camera.hide_render = True
        cameras[name] = camera
    bpy.context.view_layer.update()
    return cameras


def _smoothstep(edge_0, edge_1, value):
    if edge_1 <= edge_0:
        return 1.0 if value >= edge_1 else 0.0
    factor = max(0.0, min(1.0, (value - edge_0) / (edge_1 - edge_0)))
    return factor * factor * (3.0 - 2.0 * factor)


def _projection_normals(mesh, world_points, normal_matrix, max_dimension):
    """Average weight normals across exact SPAR3D fragment duplicates."""

    normals = [
        (normal_matrix @ vertex.normal).normalized()
        for vertex in mesh.vertices
    ]
    tolerance = max(max_dimension * 1.0e-6, 1.0e-9)
    groups = {}
    for index, point in enumerate(world_points):
        key = tuple(round(component / tolerance) for component in point)
        groups.setdefault(key, []).append(index)

    for indices in groups.values():
        if len(indices) < 2:
            continue
        average = Vector((0.0, 0.0, 0.0))
        for index in indices:
            average += normals[index]
        if average.length_squared <= 1.0e-12:
            continue
        average.normalize()
        for index in indices:
            normals[index] = average.copy()
    return normals


def _target_hit(hit_object, target):
    if hit_object is None:
        return False
    if hit_object == target or hit_object.name == target.name:
        return True
    original = getattr(hit_object, "original", None)
    return original == target


def _visibility_function(
    scene,
    depsgraph,
    target,
    ray_distance,
    tolerance,
    feather,
):
    outer_tolerance = tolerance * (1.0 + max(feather, 0.0))

    def visibility(world_point, outward_direction):
        ray_origin = world_point + outward_direction * ray_distance
        hit, location, _normal, _face, hit_object, _matrix = scene.ray_cast(
            depsgraph,
            ray_origin,
            -outward_direction,
            distance=ray_distance * 1.25,
        )
        if not hit or not _target_hit(hit_object, target):
            return 0.0
        error = (location - world_point).length
        if error <= tolerance:
            return 1.0
        if outer_tolerance <= tolerance or error >= outer_tolerance:
            return 0.0
        return 1.0 - ((error - tolerance) / (outer_tolerance - tolerance))

    return visibility


def create_projection_state(context, info, settings):
    """Create cameras, camera UV maps, and per-corner geometric view weights."""

    target = info.obj
    mesh = info.mesh
    scene = context.scene
    directions = view_directions(settings)
    directions["right"] = directions["right"]
    bounds = world_bounds(target, directions)
    height = bounds["up_span"]

    # Semantic ownership extends the existing corner-weight architecture.  It
    # never changes topology, UVs, materials, normals, or vertex order.
    from .source_processing import create_body_part_attributes

    body_part_attributes = create_body_part_attributes(context, target, settings)

    target[ORIGINAL_MATERIAL_PROPERTY] = info.material.name
    target[ORIGINAL_SLOT_PROPERTY] = info.material_slot
    target[ORIGINAL_UV_PROPERTY] = info.uv_name

    cameras = _create_projection_cameras(scene, settings, bounds, directions)

    old_render = (
        scene.render.resolution_x,
        scene.render.resolution_y,
        scene.render.resolution_percentage,
        scene.render.pixel_aspect_x,
        scene.render.pixel_aspect_y,
    )
    scene.render.resolution_x = 1024
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0

    attributes = {}
    try:
        for name in VIEW_NAMES:
            uv_name = f"{PROJECTION_UV_PREFIX}{name}"
            existing_uv = mesh.uv_layers.get(uv_name)
            if existing_uv:
                mesh.uv_layers.remove(existing_uv)
            uv_layer = mesh.uv_layers.new(name=uv_name)

            attr_name = f"{WEIGHT_ATTRIBUTE_PREFIX}{name}"
            existing_attr = mesh.attributes.get(attr_name)
            if existing_attr:
                mesh.attributes.remove(existing_attr)
            attributes[name] = mesh.attributes.new(
                name=attr_name,
                type="FLOAT",
                domain="CORNER",
            )

            camera = cameras[name]
            for loop in mesh.loops:
                world_co = bounds["points"][loop.vertex_index]
                projected = world_to_camera_view(scene, camera, world_co)
                # Source alignment remains in shader nodes so flip/scale/offset
                # edits can update live without rebuilding ray-cast weights.
                uv_layer.data[loop.index].uv = (projected.x, projected.y)
    finally:
        (
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.resolution_percentage,
            scene.render.pixel_aspect_x,
            scene.render.pixel_aspect_y,
        ) = old_render
        for camera in cameras.values():
            camera.hide_viewport = not settings.show_projection_cameras

    normal_matrix = target.matrix_world.to_3x3().inverted().transposed()
    world_normals = _projection_normals(
        mesh,
        bounds["points"],
        normal_matrix,
        bounds["max_dimension"],
    )
    height_ratios = [
        (point.dot(directions["up"]) - bounds["up_min"]) / bounds["up_span"]
        for point in bounds["points"]
    ]

    crown_threshold = min(0.95, settings.head_threshold + 0.10)
    crown_right_values = [
        point.dot(directions["right"])
        for point, ratio in zip(bounds["points"], height_ratios, strict=True)
        if ratio >= crown_threshold
    ]
    if crown_right_values:
        head_right_center = (
            min(crown_right_values) + max(crown_right_values)
        ) * 0.5
        head_right_radius = max(
            (max(crown_right_values) - min(crown_right_values)) * 0.75,
            1.0e-8,
        )
    else:
        head_right_center = (
            bounds["right_min"] + bounds["right_max"]
        ) * 0.5
        head_right_radius = bounds["right_span"] * 0.25

    lateral_masks = []
    for point in bounds["points"]:
        lateral_distance = abs(
            point.dot(directions["right"]) - head_right_center
        )
        lateral_masks.append(
            1.0
            - _smoothstep(
                head_right_radius,
                head_right_radius * 1.20,
                lateral_distance,
            )
        )

    head_mask_name = f"{WEIGHT_ATTRIBUTE_PREFIX}head_mask"
    existing_head_mask = mesh.attributes.get(head_mask_name)
    if existing_head_mask:
        mesh.attributes.remove(existing_head_mask)
    head_mask = mesh.attributes.new(
        name=head_mask_name,
        type="FLOAT",
        domain="CORNER",
    )
    transition_start = settings.head_threshold - settings.head_lock_transition
    for loop in mesh.loops:
        mask = 0.0
        if settings.head_identity_lock:
            mask = _smoothstep(
                transition_start,
                settings.head_threshold,
                height_ratios[loop.vertex_index],
            )
            mask *= lateral_masks[loop.vertex_index]
        head_mask.data[loop.index].value = mask

    use_occlusion = settings.occlusion_protection
    depsgraph = context.evaluated_depsgraph_get()
    ray_distance = max(bounds["max_dimension"] * 4.0, height * 4.0, 0.1)
    tolerance = max(height * settings.depth_tolerance_factor, 1.0e-7)
    visibility_at = _visibility_function(
        scene,
        depsgraph,
        target,
        ray_distance,
        tolerance,
        settings.occlusion_feather,
    )

    loop_polygon_indices = [0] * len(mesh.loops)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            loop_polygon_indices[loop_index] = polygon.index

    view_position_bounds = {}
    for name in VIEW_NAMES:
        values = [point.dot(directions[name]) for point in bounds["points"]]
        view_position_bounds[name] = (
            min(values),
            max(max(values) - min(values), 1.0e-8),
        )

    wm = context.window_manager
    wm.progress_begin(0, len(VIEW_NAMES))
    try:
        for view_index, name in enumerate(VIEW_NAMES):
            view_settings = getattr(settings, name)
            direction = directions[name]
            view_is_active = view_settings.enabled and view_settings.image is not None
            use_view_occlusion = (
                view_is_active and use_occlusion and view_settings.occlusion
            )

            if use_view_occlusion:
                vertex_visibility = [
                    visibility_at(point, direction) for point in bounds["points"]
                ]
                if settings.visibility_samples == "CENTER_VERTEX":
                    polygon_visibility = [
                        visibility_at(
                            target.matrix_world @ polygon.center,
                            direction,
                        )
                        for polygon in mesh.polygons
                    ]
                else:
                    polygon_visibility = [1.0] * len(mesh.polygons)
            else:
                fill = 1.0 if view_is_active else 0.0
                vertex_visibility = [fill] * len(mesh.vertices)
                polygon_visibility = [fill] * len(mesh.polygons)

            for loop in mesh.loops:
                vertex_index = loop.vertex_index
                world_co = bounds["points"][vertex_index]
                world_normal = world_normals[vertex_index]
                height_ratio = height_ratios[vertex_index]
                head_lock = head_mask.data[loop.index].value

                if height_ratio >= settings.head_threshold:
                    identity_bias = settings.head_front_back_bias
                elif height_ratio >= settings.upper_threshold:
                    identity_bias = settings.upper_front_back_bias
                else:
                    identity_bias = settings.lower_front_back_bias

                directional = max(0.0, world_normal.dot(direction))
                surface_fill_visibility = 0.0
                if name in {
                    "front",
                    "back",
                    "front_left",
                    "front_right",
                }:
                    position_min, position_span = view_position_bounds[name]
                    hemisphere = (
                        world_co.dot(direction) - position_min
                    ) / position_span
                    top_coverage = (
                        abs(world_normal.dot(directions["up"]))
                        * hemisphere
                        * settings.top_surface_coverage
                    )
                    surface_fill_visibility = min(
                        1.0,
                        top_coverage * head_lock,
                    )
                    directional = max(directional, top_coverage)
                    bias = identity_bias
                else:
                    bias = settings.side_bias

                visibility = vertex_visibility[vertex_index]
                polygon_sample = polygon_visibility[
                    loop_polygon_indices[loop.index]
                ]
                # Polygon-center rejection is intentionally faded out inside
                # the identity-locked head.  A constant polygon sample creates
                # visible triangular ownership islands on coarse SPAR3D faces,
                # while per-vertex visibility interpolates continuously and is
                # still conservative around genuine self-occlusion.
                polygon_gate = (
                    polygon_sample * (1.0 - head_lock) + head_lock
                )
                visibility *= polygon_gate
                # Horizontal camera rays are tangent to the crown and
                # underside of the jaw. Give those small head surfaces a
                # conservative alpha-gated source fallback instead of exposing
                # the old SPAR3D texture through a white or stretched hole.
                visibility = max(visibility, surface_fill_visibility)
                weight = (
                    settings.minimum_weight
                    + bias * math.pow(directional, settings.directional_exponent)
                )
                attributes[name].data[loop.index].value = weight * visibility
            wm.progress_update(view_index + 1)
    finally:
        wm.progress_end()

    packed_weight_attributes = {}
    for pack_index in range(0, len(VIEW_NAMES), 3):
        packed_name = f"{VIEW_WEIGHT_PACK_PREFIX}{pack_index // 3}"
        existing_packed = mesh.attributes.get(packed_name)
        if existing_packed is not None:
            mesh.attributes.remove(existing_packed)
        packed = mesh.attributes.new(
            name=packed_name,
            type="FLOAT_VECTOR",
            domain="CORNER",
        )
        names = VIEW_NAMES[pack_index : pack_index + 3]
        for loop in mesh.loops:
            values = [attributes[name].data[loop.index].value for name in names]
            values.extend([0.0] * (3 - len(values)))
            packed.data[loop.index].vector = values
        packed_weight_attributes[pack_index // 3] = packed

    mesh.uv_layers.active = mesh.uv_layers[info.uv_name]
    mesh.uv_layers[info.uv_name].active_render = True
    mesh.update()

    return {
        "cameras": cameras,
        "directions": directions,
        "bounds": bounds,
        "attributes": attributes,
        "packed_weight_attributes": packed_weight_attributes,
        "head_mask": head_mask,
        "body_part_attributes": body_part_attributes,
    }
