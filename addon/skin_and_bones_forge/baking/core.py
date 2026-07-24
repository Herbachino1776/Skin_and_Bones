"""Bake the temporary projection material into the production UV atlas."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..constants import ADDON_VERSION_STRING, PREVIEW_MATERIAL_PREFIX
from ..projection import cleanup_temporary_data


def _absolute_path(path_value):
    return Path(bpy.path.abspath(path_value)).resolve()


def _set_material_output_values(info, settings):
    if info.principled_node is not None:
        roughness = info.principled_node.inputs.get("Roughness")
        if roughness is not None:
            roughness.default_value = settings.roughness
    if info.normal_map_node is not None:
        strength = info.normal_map_node.inputs.get("Strength")
        if strength is not None:
            strength.default_value = settings.normal_strength
    if settings.smooth_shading:
        for polygon in info.mesh.polygons:
            polygon.use_smooth = True


def bake_final_texture(context, info, settings):
    target = info.obj
    slot_material = target.material_slots[info.material_slot].material
    if (
        slot_material is None
        or not slot_material.name.startswith(PREVIEW_MATERIAL_PREFIX)
        or slot_material.node_tree is None
    ):
        raise RuntimeError("Create a projection preview before baking.")

    preview_material = slot_material
    nodes = preview_material.node_tree.nodes
    for node in list(nodes):
        if node.name.startswith("SBF_BakeTarget"):
            nodes.remove(node)

    output_path = _absolute_path(settings.output_image_path)
    original_path = info.original_base_image.filepath
    if original_path and not settings.allow_source_overwrite:
        resolved_original = Path(bpy.path.abspath(original_path)).resolve()
        if output_path == resolved_original:
            raise RuntimeError(
                "Base-color output matches the original source image. Choose a "
                "new path or explicitly enable Allow Source Overwrite."
            )

    size = int(settings.texture_size)
    image_name = f"SBF_{target.name}_BaseColor_{size}"
    baked_image = bpy.data.images.new(
        image_name,
        width=size,
        height=size,
        alpha=True,
        float_buffer=False,
    )
    baked_image.colorspace_settings.name = "sRGB"
    baked_image.alpha_mode = "STRAIGHT"
    baked_image.generated_color = (0.03, 0.03, 0.03, 1.0)

    bake_target = nodes.new("ShaderNodeTexImage")
    bake_target.name = "SBF_BakeTarget"
    bake_target.label = "SBF Bake Target"
    bake_target.image = baked_image
    nodes.active = bake_target
    for node in nodes:
        node.select = False
    bake_target.select = True

    target.data.uv_layers.active = target.data.uv_layers[info.uv_name]
    target.data.uv_layers[info.uv_name].active_render = True

    selected_before = list(context.selected_objects)
    active_before = context.view_layer.objects.active
    mode_before = target.mode
    if target.mode != "OBJECT":
        context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in context.selected_objects:
        obj.select_set(False)
    target.select_set(True)
    context.view_layer.objects.active = target

    scene = context.scene
    engine_before = scene.render.engine
    samples_before = scene.cycles.samples
    device_before = scene.cycles.device
    margin_before = scene.render.bake.margin
    use_clear_before = scene.render.bake.use_clear

    try:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.render.bake.margin = settings.bake_margin
        scene.render.bake.use_clear = True
        bpy.ops.object.bake(type="EMIT")
    except Exception:
        if baked_image.users == 0:
            bpy.data.images.remove(baked_image)
        raise
    finally:
        scene.render.engine = engine_before
        scene.cycles.samples = samples_before
        scene.cycles.device = device_before
        scene.render.bake.margin = margin_before
        scene.render.bake.use_clear = use_clear_before

        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected_before:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        context.view_layer.objects.active = active_before
        if mode_before != "OBJECT" and target.name in context.view_layer.objects:
            context.view_layer.objects.active = target
            try:
                bpy.ops.object.mode_set(mode=mode_before)
            except RuntimeError:
                pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    baked_image.filepath_raw = str(output_path)
    baked_image.file_format = "PNG"
    baked_image.save()
    if settings.pack_baked_image:
        baked_image.pack()

    info.base_color_node.image = baked_image
    target.material_slots[info.material_slot].material = info.material
    _set_material_output_values(info, settings)

    settings.last_baked_image = baked_image
    target["sbf_processed"] = True
    target["sbf_version"] = ADDON_VERSION_STRING
    target["sbf_base_color_image"] = baked_image.name
    target["sbf_base_color_path"] = str(output_path)

    cleanup_temporary_data(context, target, info.material)
    return baked_image, output_path
