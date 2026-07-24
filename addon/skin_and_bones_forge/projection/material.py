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


def _view_transform_values(view_settings):
    scale = max(view_settings.scale, 1.0e-6)
    horizontal_scale = max(view_settings.horizontal_scale, 1.0e-6)
    scale_x = scale * horizontal_scale
    sign_x = -1.0 if view_settings.flip_x else 1.0
    sign_y = -1.0 if view_settings.flip_y else 1.0
    multiplier = (sign_x / scale_x, sign_y / scale, 1.0)
    translation = (
        0.5 + view_settings.offset_x - sign_x * 0.5 / scale_x,
        0.5 + view_settings.offset_y - sign_y * 0.5 / scale,
        0.0,
    )
    return multiplier, translation


def _head_transform_values(view_settings):
    scale = max(view_settings.head_scale, 1.0e-6)
    horizontal_scale = max(view_settings.head_horizontal_scale, 1.0e-6)
    scale_x = scale * horizontal_scale
    multiplier = (1.0 / scale_x, 1.0 / scale, 1.0)
    translation = (
        0.5 + view_settings.head_offset_x - 0.5 / scale_x,
        0.5 + view_settings.head_offset_y - 0.5 / scale,
        0.0,
    )
    return multiplier, translation


def _apply_view_controls(nodes, name, view_settings):
    multiplier, translation = _view_transform_values(view_settings)
    head_multiplier, head_translation = _head_transform_values(view_settings)

    tex = nodes.get(f"SBF_Source_{name}")
    if tex is not None:
        tex.image = view_settings.image
    safe_tex = nodes.get(f"SBF_SafeSource_{name}")
    if safe_tex is not None:
        safe_tex.image = view_settings.image

    scale_node = nodes.get(f"SBF_UVScale_{name}")
    if scale_node is not None:
        scale_node.inputs[1].default_value = multiplier

    offset_node = nodes.get(f"SBF_UVOffset_{name}")
    if offset_node is not None:
        offset_node.inputs[1].default_value = translation

    head_scale_node = nodes.get(f"SBF_HeadUVScale_{name}")
    if head_scale_node is not None:
        head_scale_node.inputs[1].default_value = head_multiplier

    head_offset_node = nodes.get(f"SBF_HeadUVOffset_{name}")
    if head_offset_node is not None:
        head_offset_node.inputs[1].default_value = head_translation

    threshold = nodes.get(f"SBF_AlphaThreshold_{name}")
    if threshold is not None:
        threshold.inputs[1].default_value = view_settings.alpha_threshold
    safe_threshold = nodes.get(f"SBF_SafeAlphaThreshold_{name}")
    if safe_threshold is not None:
        safe_threshold.inputs[1].default_value = view_settings.alpha_threshold

    black_key = nodes.get(f"SBF_BlackKey_{name}")
    if black_key is not None:
        black_key.inputs[1].default_value = view_settings.black_key_threshold
    safe_black_key = nodes.get(f"SBF_SafeBlackKey_{name}")
    if safe_black_key is not None:
        safe_black_key.inputs[1].default_value = view_settings.black_key_threshold

    black_key_disabled = nodes.get(f"SBF_BlackKeyDisabled_{name}")
    if black_key_disabled is not None:
        black_key_disabled.inputs[1].default_value = (
            1.0 if view_settings.key_black_background else 0.0
        )

    live_weight = nodes.get(f"SBF_LiveWeight_{name}")
    if live_weight is not None:
        live_weight.inputs[1].default_value = (
            view_settings.weight if view_settings.enabled else 0.0
        )


def _apply_global_controls(nodes, settings):
    safe_factor = 1.0 - settings.source_edge_padding
    for name in VIEW_NAMES:
        confidence = nodes.get(f"SBF_HeadConfidence_{name}")
        if confidence is not None:
            confidence.inputs[1].default_value = settings.head_blend_sharpness
        safe_scale = nodes.get(f"SBF_SafeUVScale_{name}")
        if safe_scale is not None:
            safe_scale.inputs[1].default_value = (
                safe_factor,
                safe_factor,
                1.0,
            )
        safe_offset = nodes.get(f"SBF_SafeUVOffset_{name}")
        if safe_offset is not None:
            safe_offset.inputs[1].default_value = (
                settings.source_edge_padding * 0.5,
                settings.source_edge_padding * 0.5,
                0.0,
            )


def update_preview_view_controls(settings, changed_view=None):
    """Update cheap source alignment controls without rebuilding projection state."""

    target = settings.target_object
    if target is None or target.type != "MESH":
        return False

    if changed_view is None:
        names = VIEW_NAMES
    else:
        try:
            changed_pointer = changed_view.as_pointer()
        except ReferenceError:
            return False
        names = tuple(
            name
            for name in VIEW_NAMES
            if getattr(settings, name).as_pointer() == changed_pointer
        )
        if not names:
            return False

    updated = False
    for slot in target.material_slots:
        material = slot.material
        if (
            material is None
            or not material.name.startswith(PREVIEW_MATERIAL_PREFIX)
            or material.node_tree is None
        ):
            continue
        for name in names:
            _apply_view_controls(
                material.node_tree.nodes,
                name,
                getattr(settings, name),
            )
        _apply_global_controls(material.node_tree.nodes, settings)
        material.node_tree.update_tag()
        updated = True
    if updated:
        target.data.update()
    return updated


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

    head_mask = nodes.new("ShaderNodeAttribute")
    head_mask.attribute_name = f"{WEIGHT_ATTRIBUTE_PREFIX}head_mask"
    head_mask.location = (-1100, 800)

    sum_vector = None
    sum_weight = None
    head_sum_vector = None
    head_sum_weight = None
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

        uv_scale = nodes.new("ShaderNodeVectorMath")
        uv_scale.name = f"SBF_UVScale_{name}"
        uv_scale.operation = "MULTIPLY"
        uv_scale.location = (-900, y)
        links.new(uv_node.outputs["UV"], uv_scale.inputs[0])

        uv_offset = nodes.new("ShaderNodeVectorMath")
        uv_offset.name = f"SBF_UVOffset_{name}"
        uv_offset.operation = "ADD"
        uv_offset.location = (-700, y)
        links.new(uv_scale.outputs["Vector"], uv_offset.inputs[0])

        head_uv_scale = nodes.new("ShaderNodeVectorMath")
        head_uv_scale.name = f"SBF_HeadUVScale_{name}"
        head_uv_scale.operation = "MULTIPLY"
        head_uv_scale.location = (-500, y + 80)
        links.new(uv_offset.outputs["Vector"], head_uv_scale.inputs[0])

        head_uv_offset = nodes.new("ShaderNodeVectorMath")
        head_uv_offset.name = f"SBF_HeadUVOffset_{name}"
        head_uv_offset.operation = "ADD"
        head_uv_offset.location = (-300, y + 80)
        links.new(head_uv_scale.outputs["Vector"], head_uv_offset.inputs[0])

        head_uv_mix = nodes.new("ShaderNodeMixRGB")
        head_uv_mix.blend_type = "MIX"
        head_uv_mix.location = (-100, y + 80)
        links.new(head_mask.outputs["Fac"], head_uv_mix.inputs[0])
        links.new(uv_offset.outputs["Vector"], head_uv_mix.inputs[1])
        links.new(head_uv_offset.outputs["Vector"], head_uv_mix.inputs[2])

        tex = nodes.new("ShaderNodeTexImage")
        tex.name = f"SBF_Source_{name}"
        tex.label = name.title()
        tex.image = view_settings.image
        tex.interpolation = "Linear"
        tex.extension = "CLIP"
        tex.location = (100, y)
        links.new(head_uv_mix.outputs["Color"], tex.inputs["Vector"])

        safe_factor = 1.0 - settings.source_edge_padding
        safe_uv_scale = nodes.new("ShaderNodeVectorMath")
        safe_uv_scale.name = f"SBF_SafeUVScale_{name}"
        safe_uv_scale.operation = "MULTIPLY"
        safe_uv_scale.inputs[1].default_value = (
            safe_factor,
            safe_factor,
            1.0,
        )
        safe_uv_scale.location = (-100, y + 180)
        links.new(head_uv_mix.outputs["Color"], safe_uv_scale.inputs[0])

        safe_uv_offset = nodes.new("ShaderNodeVectorMath")
        safe_uv_offset.name = f"SBF_SafeUVOffset_{name}"
        safe_uv_offset.operation = "ADD"
        safe_uv_offset.inputs[1].default_value = (
            settings.source_edge_padding * 0.5,
            settings.source_edge_padding * 0.5,
            0.0,
        )
        safe_uv_offset.location = (100, y + 180)
        links.new(safe_uv_scale.outputs["Vector"], safe_uv_offset.inputs[0])

        safe_tex = nodes.new("ShaderNodeTexImage")
        safe_tex.name = f"SBF_SafeSource_{name}"
        safe_tex.label = f"{name.title()} Source Edge Fill"
        safe_tex.image = view_settings.image
        safe_tex.interpolation = "Linear"
        safe_tex.extension = "CLIP"
        safe_tex.location = (300, y + 180)
        links.new(safe_uv_offset.outputs["Vector"], safe_tex.inputs["Vector"])

        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = f"{WEIGHT_ATTRIBUTE_PREFIX}{name}"
        attr.location = (-500, y - 140)

        threshold = nodes.new("ShaderNodeMath")
        threshold.name = f"SBF_AlphaThreshold_{name}"
        threshold.operation = "GREATER_THAN"
        threshold.inputs[1].default_value = view_settings.alpha_threshold
        threshold.location = (-250, y - 80)
        links.new(tex.outputs["Alpha"], threshold.inputs[0])

        luminance = nodes.new("ShaderNodeRGBToBW")
        luminance.location = (-250, y - 170)
        links.new(tex.outputs["Color"], luminance.inputs["Color"])

        black_key = nodes.new("ShaderNodeMath")
        black_key.name = f"SBF_BlackKey_{name}"
        black_key.operation = "GREATER_THAN"
        black_key.inputs[1].default_value = view_settings.black_key_threshold
        black_key.location = (-50, y - 170)
        links.new(luminance.outputs["Val"], black_key.inputs[0])

        black_key_disabled = nodes.new("ShaderNodeMath")
        black_key_disabled.name = f"SBF_BlackKeyDisabled_{name}"
        black_key_disabled.operation = "SUBTRACT"
        black_key_disabled.inputs[0].default_value = 1.0
        black_key_disabled.location = (-50, y - 260)

        black_key_mask = nodes.new("ShaderNodeMath")
        black_key_mask.operation = "MAXIMUM"
        black_key_mask.location = (150, y - 170)
        links.new(black_key.outputs[0], black_key_mask.inputs[0])
        links.new(black_key_disabled.outputs[0], black_key_mask.inputs[1])

        source_mask = nodes.new("ShaderNodeMath")
        source_mask.operation = "MULTIPLY"
        source_mask.location = (150, y - 80)
        links.new(threshold.outputs[0], source_mask.inputs[0])
        links.new(black_key_mask.outputs[0], source_mask.inputs[1])

        safe_threshold = nodes.new("ShaderNodeMath")
        safe_threshold.name = f"SBF_SafeAlphaThreshold_{name}"
        safe_threshold.operation = "GREATER_THAN"
        safe_threshold.inputs[1].default_value = view_settings.alpha_threshold
        safe_threshold.location = (500, y + 140)
        links.new(safe_tex.outputs["Alpha"], safe_threshold.inputs[0])

        safe_luminance = nodes.new("ShaderNodeRGBToBW")
        safe_luminance.location = (500, y + 50)
        links.new(safe_tex.outputs["Color"], safe_luminance.inputs["Color"])

        safe_black_key = nodes.new("ShaderNodeMath")
        safe_black_key.name = f"SBF_SafeBlackKey_{name}"
        safe_black_key.operation = "GREATER_THAN"
        safe_black_key.inputs[1].default_value = (
            view_settings.black_key_threshold
        )
        safe_black_key.location = (700, y + 50)
        links.new(safe_luminance.outputs["Val"], safe_black_key.inputs[0])

        safe_black_key_mask = nodes.new("ShaderNodeMath")
        safe_black_key_mask.operation = "MAXIMUM"
        safe_black_key_mask.location = (700, y + 140)
        links.new(safe_black_key.outputs[0], safe_black_key_mask.inputs[0])
        links.new(
            black_key_disabled.outputs[0],
            safe_black_key_mask.inputs[1],
        )

        safe_source_mask = nodes.new("ShaderNodeMath")
        safe_source_mask.operation = "MULTIPLY"
        safe_source_mask.location = (900, y + 140)
        links.new(safe_threshold.outputs[0], safe_source_mask.inputs[0])
        links.new(safe_black_key_mask.outputs[0], safe_source_mask.inputs[1])

        primary_invalid = nodes.new("ShaderNodeMath")
        primary_invalid.operation = "SUBTRACT"
        primary_invalid.inputs[0].default_value = 1.0
        primary_invalid.location = (350, y - 10)
        links.new(source_mask.outputs[0], primary_invalid.inputs[1])

        safe_fill_factor = nodes.new("ShaderNodeMath")
        safe_fill_factor.operation = "MULTIPLY"
        safe_fill_factor.location = (550, y - 10)
        links.new(primary_invalid.outputs[0], safe_fill_factor.inputs[0])
        links.new(safe_source_mask.outputs[0], safe_fill_factor.inputs[1])

        filled_color = nodes.new("ShaderNodeMixRGB")
        filled_color.blend_type = "MIX"
        filled_color.location = (750, y - 10)
        links.new(safe_fill_factor.outputs[0], filled_color.inputs[0])
        links.new(tex.outputs["Color"], filled_color.inputs[1])
        links.new(safe_tex.outputs["Color"], filled_color.inputs[2])

        clipped_alpha = nodes.new("ShaderNodeMath")
        clipped_alpha.operation = "MULTIPLY"
        clipped_alpha.location = (350, y - 80)
        links.new(tex.outputs["Alpha"], clipped_alpha.inputs[0])
        links.new(source_mask.outputs[0], clipped_alpha.inputs[1])

        safe_clipped_alpha = nodes.new("ShaderNodeMath")
        safe_clipped_alpha.operation = "MULTIPLY"
        safe_clipped_alpha.location = (1100, y + 50)
        links.new(safe_tex.outputs["Alpha"], safe_clipped_alpha.inputs[0])
        links.new(safe_source_mask.outputs[0], safe_clipped_alpha.inputs[1])

        effective_alpha = nodes.new("ShaderNodeMath")
        effective_alpha.operation = "MAXIMUM"
        effective_alpha.location = (550, y - 80)
        links.new(clipped_alpha.outputs[0], effective_alpha.inputs[0])
        links.new(safe_clipped_alpha.outputs[0], effective_alpha.inputs[1])

        live_weight = nodes.new("ShaderNodeMath")
        live_weight.name = f"SBF_LiveWeight_{name}"
        live_weight.operation = "MULTIPLY"
        live_weight.inputs[1].default_value = view_settings.weight
        live_weight.location = (350, y - 170)
        links.new(attr.outputs["Fac"], live_weight.inputs[0])

        alpha_weight = nodes.new("ShaderNodeMath")
        alpha_weight.operation = "MULTIPLY"
        alpha_weight.location = (650, y - 80)
        links.new(effective_alpha.outputs[0], alpha_weight.inputs[0])
        links.new(live_weight.outputs[0], alpha_weight.inputs[1])

        head_confidence = nodes.new("ShaderNodeMath")
        head_confidence.name = f"SBF_HeadConfidence_{name}"
        head_confidence.operation = "POWER"
        head_confidence.inputs[1].default_value = settings.head_blend_sharpness
        head_confidence.location = (550, y - 260)
        links.new(alpha_weight.outputs[0], head_confidence.inputs[0])

        scaled_color = nodes.new("ShaderNodeVectorMath")
        scaled_color.operation = "SCALE"
        scaled_color.location = (750, y)
        links.new(filled_color.outputs["Color"], scaled_color.inputs[0])
        links.new(alpha_weight.outputs[0], _scale_socket(scaled_color))

        head_scaled_color = nodes.new("ShaderNodeVectorMath")
        head_scaled_color.operation = "SCALE"
        head_scaled_color.location = (750, y - 180)
        links.new(filled_color.outputs["Color"], head_scaled_color.inputs[0])
        links.new(
            head_confidence.outputs[0],
            _scale_socket(head_scaled_color),
        )

        _apply_view_controls(nodes, name, view_settings)

        if sum_vector is None:
            sum_vector = scaled_color.outputs["Vector"]
            sum_weight = alpha_weight.outputs[0]
            head_sum_vector = head_scaled_color.outputs["Vector"]
            head_sum_weight = head_confidence.outputs[0]
        else:
            add_vector = nodes.new("ShaderNodeVectorMath")
            add_vector.operation = "ADD"
            add_vector.location = (950, y)
            links.new(sum_vector, add_vector.inputs[0])
            links.new(scaled_color.outputs["Vector"], add_vector.inputs[1])
            sum_vector = add_vector.outputs["Vector"]

            add_weight = nodes.new("ShaderNodeMath")
            add_weight.operation = "ADD"
            add_weight.location = (950, y - 100)
            links.new(sum_weight, add_weight.inputs[0])
            links.new(alpha_weight.outputs[0], add_weight.inputs[1])
            sum_weight = add_weight.outputs[0]

            add_head_vector = nodes.new("ShaderNodeVectorMath")
            add_head_vector.operation = "ADD"
            add_head_vector.location = (950, y - 180)
            links.new(head_sum_vector, add_head_vector.inputs[0])
            links.new(
                head_scaled_color.outputs["Vector"],
                add_head_vector.inputs[1],
            )
            head_sum_vector = add_head_vector.outputs["Vector"]

            add_head_weight = nodes.new("ShaderNodeMath")
            add_head_weight.operation = "ADD"
            add_head_weight.location = (950, y - 280)
            links.new(head_sum_weight, add_head_weight.inputs[0])
            links.new(head_confidence.outputs[0], add_head_weight.inputs[1])
            head_sum_weight = add_head_weight.outputs[0]

    if active_views == 0:
        bpy.data.materials.remove(material, do_unlink=True)
        raise RuntimeError("No enabled projection images are available.")

    safe_weight = nodes.new("ShaderNodeMath")
    safe_weight.operation = "MAXIMUM"
    safe_weight.inputs[1].default_value = 0.0001
    safe_weight.location = (750, -120)
    links.new(sum_weight, safe_weight.inputs[0])

    reciprocal = nodes.new("ShaderNodeMath")
    reciprocal.operation = "DIVIDE"
    reciprocal.inputs[0].default_value = 1.0
    reciprocal.location = (900, -120)
    links.new(safe_weight.outputs[0], reciprocal.inputs[1])

    normalized = nodes.new("ShaderNodeVectorMath")
    normalized.operation = "SCALE"
    normalized.location = (750, 80)
    links.new(sum_vector, normalized.inputs[0])
    links.new(reciprocal.outputs[0], _scale_socket(normalized))

    safe_head_weight = nodes.new("ShaderNodeMath")
    safe_head_weight.operation = "MAXIMUM"
    safe_head_weight.inputs[1].default_value = 0.0001
    safe_head_weight.location = (750, 250)
    links.new(head_sum_weight, safe_head_weight.inputs[0])

    head_reciprocal = nodes.new("ShaderNodeMath")
    head_reciprocal.operation = "DIVIDE"
    head_reciprocal.inputs[0].default_value = 1.0
    head_reciprocal.location = (900, 250)
    links.new(safe_head_weight.outputs[0], head_reciprocal.inputs[1])

    head_normalized = nodes.new("ShaderNodeVectorMath")
    head_normalized.operation = "SCALE"
    head_normalized.location = (750, 400)
    links.new(head_sum_vector, head_normalized.inputs[0])
    links.new(
        head_reciprocal.outputs[0],
        _scale_socket(head_normalized),
    )

    head_projection = nodes.new("ShaderNodeMixRGB")
    head_projection.name = "SBF_HeadProjection"
    head_projection.blend_type = "MIX"
    head_projection.location = (950, 80)
    links.new(head_mask.outputs["Fac"], head_projection.inputs[0])
    links.new(normalized.outputs["Vector"], head_projection.inputs[1])
    links.new(head_normalized.outputs["Vector"], head_projection.inputs[2])

    has_projection = nodes.new("ShaderNodeMath")
    has_projection.operation = "GREATER_THAN"
    has_projection.inputs[1].default_value = settings.fallback_threshold
    has_projection.location = (920, 200)
    links.new(sum_weight, has_projection.inputs[0])

    fallback = nodes.new("ShaderNodeMixRGB")
    fallback.blend_type = "MIX"
    fallback.location = (1050, 0)
    links.new(has_projection.outputs[0], fallback.inputs[0])
    links.new(old_tex.outputs["Color"], fallback.inputs[1])
    links.new(head_projection.outputs["Color"], fallback.inputs[2])
    links.new(fallback.outputs["Color"], emission.inputs["Color"])

    info.obj.material_slots[info.material_slot].material = material
    return material
