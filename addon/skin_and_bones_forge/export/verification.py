"""Standardized proof-render generation."""

from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Matrix

from ..constants import VERIFY_PREFIX
from ..projection import view_directions, world_bounds


def _camera_rotation(outward, up):
    camera_z = outward.normalized()
    camera_y = up.normalized()
    camera_x = camera_y.cross(camera_z).normalized()
    return Matrix((camera_x, camera_y, camera_z)).transposed().to_euler()


def _look_at(obj, point):
    direction = point - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _point_at_height(bounds, up, ratio):
    desired = bounds["up_min"] + bounds["up_span"] * ratio
    center = bounds["center"]
    return center + up * (desired - center.dot(up))


def render_verification_set(context, info, settings):
    scene = context.scene
    directions = view_directions(settings)
    bounds = world_bounds(info.obj, directions)
    height = bounds["up_span"]
    distance = max(bounds["max_dimension"] * 3.0, height * 3.0, 0.1)

    output_dir = Path(bpy.path.abspath(settings.proof_render_dir)).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    render_snapshot = {
        "engine": scene.render.engine,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "filepath": scene.render.filepath,
        "file_format": scene.render.image_settings.file_format,
        "color_mode": scene.render.image_settings.color_mode,
        "film_transparent": scene.render.film_transparent,
        "camera": scene.camera,
        "world": scene.world,
        "look": scene.view_settings.look,
    }

    created_objects = []
    created_data = []
    temp_world = bpy.data.worlds.new(f"{VERIFY_PREFIX}World")
    temp_world.use_nodes = True
    background = temp_world.node_tree.nodes.get("Background")
    background.inputs["Color"].default_value = (0.03, 0.03, 0.03, 1.0)
    background.inputs["Strength"].default_value = 0.12

    camera_data = bpy.data.cameras.new(f"{VERIFY_PREFIX}Camera")
    camera = bpy.data.objects.new(f"{VERIFY_PREFIX}Camera", camera_data)
    context.collection.objects.link(camera)
    created_objects.append(camera)
    created_data.append((bpy.data.cameras, camera_data))
    camera_data.type = "ORTHO"
    scene.camera = camera

    light_specs = (
        (
            "Key",
            directions["front"] * distance * 0.7
            + directions["right"] * distance * 0.45
            + directions["up"] * height * 0.7,
            90.0,
            height * 2.0,
        ),
        (
            "Fill",
            directions["front"] * distance * 0.55
            - directions["right"] * distance * 0.45
            + directions["up"] * height * 0.35,
            55.0,
            height * 2.0,
        ),
        (
            "Rim",
            -directions["front"] * distance * 0.65
            + directions["up"] * height * 0.6,
            70.0,
            height * 1.5,
        ),
    )
    for name, offset, energy, size in light_specs:
        data = bpy.data.lights.new(f"{VERIFY_PREFIX}{name}", type="AREA")
        light = bpy.data.objects.new(f"{VERIFY_PREFIX}{name}", data)
        context.collection.objects.link(light)
        created_objects.append(light)
        created_data.append((bpy.data.lights, data))
        light.location = bounds["center"] + offset
        data.energy = energy
        data.shape = "DISK"
        data.size = max(size, 0.05)
        _look_at(light, bounds["center"])

    full_target = bounds["center"]
    upper_target = _point_at_height(bounds, directions["up"], 0.68)
    face_target = _point_at_height(bounds, directions["up"], 0.85)
    lower_target = _point_at_height(bounds, directions["up"], 0.30)
    three_right = (directions["front"] + directions["right"]).normalized()
    three_left = (directions["front"] + directions["left"]).normalized()

    views = (
        ("front", directions["front"], full_target, height / 0.90),
        ("back", directions["back"], full_target, height / 0.90),
        ("left", directions["left"], full_target, height / 0.90),
        ("right", directions["right"], full_target, height / 0.90),
        ("face_closeup", directions["front"], face_target, height * 0.30),
        ("threequarter_right", three_right, upper_target, height * 0.52),
        ("threequarter_left", three_left, upper_target, height * 0.52),
        ("lower_front", directions["front"], lower_target, height * 0.58),
        ("lower_threequarter", three_right, lower_target, height * 0.58),
    )

    output_paths = []
    try:
        scene.world = temp_world
        scene.render.engine = "BLENDER_EEVEE"
        scene.render.resolution_x = settings.proof_resolution
        scene.render.resolution_y = settings.proof_resolution
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        scene.render.film_transparent = True
        try:
            scene.view_settings.look = "AgX - Medium High Contrast"
        except TypeError:
            pass

        for name, outward, target_point, ortho_scale in views:
            camera_data.ortho_scale = ortho_scale
            camera.location = target_point + outward * distance
            camera.rotation_euler = _camera_rotation(outward, directions["up"])
            output_path = output_dir / f"sbf_verify_{name}.png"
            scene.render.filepath = str(output_path)
            bpy.ops.render.render(write_still=True)
            output_paths.append(output_path)
    finally:
        scene.render.engine = render_snapshot["engine"]
        scene.render.resolution_x = render_snapshot["resolution_x"]
        scene.render.resolution_y = render_snapshot["resolution_y"]
        scene.render.resolution_percentage = render_snapshot[
            "resolution_percentage"
        ]
        scene.render.filepath = render_snapshot["filepath"]
        scene.render.image_settings.file_format = render_snapshot["file_format"]
        scene.render.image_settings.color_mode = render_snapshot["color_mode"]
        scene.render.film_transparent = render_snapshot["film_transparent"]
        scene.camera = render_snapshot["camera"]
        scene.world = render_snapshot["world"]
        try:
            scene.view_settings.look = render_snapshot["look"]
        except TypeError:
            pass

        for obj in created_objects:
            if obj.name in bpy.data.objects:
                bpy.data.objects.remove(obj, do_unlink=True)
        for collection, data in created_data:
            if data.users == 0:
                collection.remove(data)
        if temp_world.users == 0:
            bpy.data.worlds.remove(temp_world)

    return output_paths
