"""Temporary projection-preview material."""

from __future__ import annotations

import bpy

from ..constants import (
    PREVIEW_MATERIAL_PREFIX,
    PROJECTION_UV_PREFIX,
    TEMPORARY_PROPERTY,
    VIEW_NAMES,
    WEIGHT_ATTRIBUTE_PREFIX,
)


def _scale_socket(node):
    return node.inputs.get("Scale") or node.inputs[-1]


def create_preview_material(info, settings):
    material = bpy.data.materials.new(
        f"{PREVIEW_MATERIAL_PREFIX}{info.obj.name}"
    )
    material.use_nodes = True
    material[TEMPORARY_PROPERTY] = True
    material["sbf_original_material"] = info.material.name
    material["sbf_original_slot"] = info.material_slot

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (1100, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (850, 0)
    emission.inputs["Strength"].default_value = 1.0
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    old_uv = nodes.new("ShaderNodeUVMap")
    old_uv.uv_map = info.uv_name
    old_uv.location = (-1000, -600)
    old_tex = nodes.new("ShaderNodeTexImage")
    old_tex.image = info.original_base_image
    old_tex.interpolation = "Linear"
    old_tex.location = (-800, -600)
    links.new(old_uv.outputs["UV"], old_tex.inputs["Vector"])

    sum_vector = None
    sum_weight = None
    active_views = 0

    for row, name in enumerate(VIEW_NAMES):
        view_settings = getattr(settings, name)
        if not view_settings.enabled or view_settings.image is None:
            continue
        active_views += 1
        y = 450 - row * 260

        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = f"{PROJECTION_UV_PREFIX}{name}"
        uv_node.location = (-1100, y)

        tex = nodes.new("ShaderNodeTexImage")
        tex.name = f"SBF_Source_{name}"
        tex.label = name.title()
        tex.image = view_settings.image
        tex.interpolation = "Linear"
        tex.extension = "CLIP"
        tex.location = (-900, y)
        links.new(uv_node.outputs["UV"], tex.inputs["Vector"])

        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = f"{WEIGHT_ATTRIBUTE_PREFIX}{name}"
        attr.location = (-900, y - 140)

        threshold = nodes.new("ShaderNodeMath")
        threshold.operation = "GREATER_THAN"
        threshold.inputs[1].default_value = view_settings.alpha_threshold
        threshold.location = (-650, y - 80)
        links.new(tex.outputs["Alpha"], threshold.inputs[0])

        clipped_alpha = nodes.new("ShaderNodeMath")
        clipped_alpha.operation = "MULTIPLY"
        clipped_alpha.location = (-450, y - 80)
        links.new(tex.outputs["Alpha"], clipped_alpha.inputs[0])
        links.new(threshold.outputs[0], clipped_alpha.inputs[1])

        alpha_weight = nodes.new("ShaderNodeMath")
        alpha_weight.operation = "MULTIPLY"
        alpha_weight.location = (-250, y - 80)
        links.new(clipped_alpha.outputs[0], alpha_weight.inputs[0])
        links.new(attr.outputs["Fac"], alpha_weight.inputs[1])

        scaled_color = nodes.new("ShaderNodeVectorMath")
        scaled_color.operation = "SCALE"
        scaled_color.location = (-50, y)
        links.new(tex.outputs["Color"], scaled_color.inputs[0])
        links.new(alpha_weight.outputs[0], _scale_socket(scaled_color))

        if sum_vector is None:
            sum_vector = scaled_color.outputs["Vector"]
            sum_weight = alpha_weight.outputs[0]
        else:
            add_vector = nodes.new("ShaderNodeVectorMath")
            add_vector.operation = "ADD"
            add_vector.location = (150, y)
            links.new(sum_vector, add_vector.inputs[0])
            links.new(scaled_color.outputs["Vector"], add_vector.inputs[1])
            sum_vector = add_vector.outputs["Vector"]

            add_weight = nodes.new("ShaderNodeMath")
            add_weight.operation = "ADD"
            add_weight.location = (150, y - 100)
            links.new(sum_weight, add_weight.inputs[0])
            links.new(alpha_weight.outputs[0], add_weight.inputs[1])
            sum_weight = add_weight.outputs[0]

    if active_views == 0:
        bpy.data.materials.remove(material, do_unlink=True)
        raise RuntimeError("No enabled projection images are available.")

    safe_weight = nodes.new("ShaderNodeMath")
    safe_weight.operation = "MAXIMUM"
    safe_weight.inputs[1].default_value = 0.0001
    safe_weight.location = (350, -120)
    links.new(sum_weight, safe_weight.inputs[0])

    reciprocal = nodes.new("ShaderNodeMath")
    reciprocal.operation = "DIVIDE"
    reciprocal.inputs[0].default_value = 1.0
    reciprocal.location = (500, -120)
    links.new(safe_weight.outputs[0], reciprocal.inputs[1])

    normalized = nodes.new("ShaderNodeVectorMath")
    normalized.operation = "SCALE"
    normalized.location = (350, 80)
    links.new(sum_vector, normalized.inputs[0])
    links.new(reciprocal.outputs[0], _scale_socket(normalized))

    has_projection = nodes.new("ShaderNodeMath")
    has_projection.operation = "GREATER_THAN"
    has_projection.inputs[1].default_value = settings.fallback_threshold
    has_projection.location = (520, 200)
    links.new(sum_weight, has_projection.inputs[0])

    fallback = nodes.new("ShaderNodeMixRGB")
    fallback.blend_type = "MIX"
    fallback.location = (650, 0)
    links.new(has_projection.outputs[0], fallback.inputs[0])
    links.new(old_tex.outputs["Color"], fallback.inputs[1])
    links.new(normalized.outputs["Vector"], fallback.inputs[2])
    links.new(fallback.outputs["Color"], emission.inputs["Color"])

    info.obj.material_slots[info.material_slot].material = material
    return material
