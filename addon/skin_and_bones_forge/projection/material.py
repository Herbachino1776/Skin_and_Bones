"""Temporary processed-source projection-preview material."""

from __future__ import annotations

import bpy

from ..constants import (
    BODY_PART_ID_ATTRIBUTE,
    PREVIEW_MATERIAL_PREFIX,
    PROJECTION_UV_PREFIX,
    TEMPORARY_PROPERTY,
    VIEW_NAMES,
    VIEW_WEIGHT_PACK_PREFIX,
    WEIGHT_ATTRIBUTE_PREFIX,
)
from .body_alignment import BODY_PARTS
from .source_processing import get_warped_atlas, stamp_preview_source_state


def _scale_socket(node):
    return node.inputs.get("Scale") or node.inputs[-1]


def _view_transform_values(view_settings):
    scale = max(view_settings.scale, 1.0e-6)
    horizontal_scale = max(view_settings.horizontal_scale, 1.0e-6)
    scale_x = scale * horizontal_scale
    sign_x = -1.0 if view_settings.flip_x else 1.0
    sign_y = -1.0 if view_settings.flip_y else 1.0
    return (
        (sign_x / scale_x, sign_y / scale, 1.0),
        (
            0.5 + view_settings.offset_x - sign_x * 0.5 / scale_x,
            0.5 + view_settings.offset_y - sign_y * 0.5 / scale,
            0.0,
        ),
    )


def _head_transform_values(view_settings):
    scale = max(view_settings.head_scale, 1.0e-6)
    horizontal_scale = max(view_settings.head_horizontal_scale, 1.0e-6)
    scale_x = scale * horizontal_scale
    return (
        (1.0 / scale_x, 1.0 / scale, 1.0),
        (
            0.5 + view_settings.head_offset_x - 0.5 / scale_x,
            0.5 + view_settings.head_offset_y - 0.5 / scale,
            0.0,
        ),
    )


def _apply_view_controls(nodes, name, view_settings):
    multiplier, translation = _view_transform_values(view_settings)
    head_multiplier, head_translation = _head_transform_values(view_settings)
    for node_name, value in (
        (f"SBF_UVScale_{name}", multiplier),
        (f"SBF_UVOffset_{name}", translation),
        (f"SBF_HeadUVScale_{name}", head_multiplier),
        (f"SBF_HeadUVOffset_{name}", head_translation),
    ):
        node = nodes.get(node_name)
        if node is not None:
            node.inputs[1].default_value = value
    threshold = nodes.get(f"SBF_AlphaThreshold_{name}")
    if threshold is not None:
        threshold.inputs[1].default_value = view_settings.alpha_threshold
    black_key = nodes.get(f"SBF_BlackKey_{name}")
    if black_key is not None:
        black_key.inputs[1].default_value = view_settings.black_key_threshold
    black_disabled = nodes.get(f"SBF_BlackKeyDisabled_{name}")
    if black_disabled is not None:
        black_disabled.inputs[1].default_value = (
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
        scale = nodes.get(f"SBF_SafeUVScale_{name}")
        if scale is not None:
            scale.inputs[1].default_value = (safe_factor, safe_factor, 1.0)
        offset = nodes.get(f"SBF_SafeUVOffset_{name}")
        if offset is not None:
            offset.inputs[1].default_value = (
                settings.source_edge_padding * 0.5,
                settings.source_edge_padding * 0.5,
                0.0,
            )


def update_preview_view_controls(settings, changed_view=None):
    """Update cheap controls only while the processed state is still current."""

    target = settings.target_object
    if target is None or target.type != "MESH" or not settings.source_preview_ready:
        return False
    if changed_view is None:
        names = VIEW_NAMES
    else:
        try:
            pointer = changed_view.as_pointer()
        except ReferenceError:
            return False
        names = tuple(
            name for name in VIEW_NAMES
            if getattr(settings, name).as_pointer() == pointer
        )
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
            _apply_view_controls(material.node_tree.nodes, name, getattr(settings, name))
        _apply_global_controls(material.node_tree.nodes, settings)
        material.node_tree.update_tag()
        updated = True
    if updated:
        target.data.update()
    return updated


def _math(nodes, operation, first=None, second=None, location=(0, 0), name=""):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    node.location = location
    if name:
        node.name = name
    if first is not None:
        if hasattr(first, "bl_idname"):
            raise TypeError("Pass sockets, not nodes, to _math.")
        if isinstance(first, (float, int)):
            node.inputs[0].default_value = first
    if second is not None and isinstance(second, (float, int)):
        node.inputs[1].default_value = second
    return node


def _add_socket(nodes, links, first, second, *, vector=False, location=(0, 0)):
    node = nodes.new("ShaderNodeVectorMath" if vector else "ShaderNodeMath")
    node.operation = "ADD"
    node.location = location
    links.new(first, node.inputs[0])
    links.new(second, node.inputs[1])
    return node.outputs["Vector"] if vector else node.outputs[0]


def _guarded_view_source(
    nodes,
    links,
    name,
    view_settings,
    global_uv,
    head_uv,
    settings,
    y,
    part_id,
):
    """Sample one native-resolution atlas through one compact part-owner ID."""

    image, metadata = get_warped_atlas(view_settings)
    source_width, source_height = metadata["source_size"]
    atlas_width, atlas_height = metadata["atlas_size"]

    owner_masks = {}
    selected_source_uv = None
    selected_offset = None
    for index, part in enumerate(BODY_PARTS):
        owner = nodes.new("ShaderNodeMath")
        owner.operation = "COMPARE"
        owner.inputs[1].default_value = float(index)
        owner.inputs[2].default_value = 0.25
        links.new(part_id, owner.inputs[0])
        owner_masks[part] = owner.outputs[0]

        source_uv = head_uv if part == "head" else global_uv
        owned_uv = nodes.new("ShaderNodeVectorMath")
        owned_uv.operation = "SCALE"
        links.new(source_uv, owned_uv.inputs[0])
        links.new(owner.outputs[0], _scale_socket(owned_uv))
        selected_source_uv = (
            owned_uv.outputs["Vector"]
            if selected_source_uv is None
            else _add_socket(
                nodes,
                links,
                selected_source_uv,
                owned_uv.outputs["Vector"],
                vector=True,
            )
        )

        minimum_x, minimum_y, _maximum_x, _maximum_y = metadata["parts"][part][
            "source_bounds"
        ]
        atlas_x, atlas_y = metadata["parts"][part]["atlas_origin"]
        offset_value = (
            (atlas_x - minimum_x) / max(atlas_width - 1, 1),
            (atlas_y - minimum_y) / max(atlas_height - 1, 1),
            0.0,
        )
        owned_offset = nodes.new("ShaderNodeVectorMath")
        owned_offset.operation = "SCALE"
        owned_offset.inputs[0].default_value = offset_value
        links.new(owner.outputs[0], _scale_socket(owned_offset))
        selected_offset = (
            owned_offset.outputs["Vector"]
            if selected_offset is None
            else _add_socket(
                nodes,
                links,
                selected_offset,
                owned_offset.outputs["Vector"],
                vector=True,
            )
        )

    atlas_scale_value = (
        (source_width - 1) / max(atlas_width - 1, 1),
        (source_height - 1) / max(atlas_height - 1, 1),
        1.0,
    )

    def atlas_uv(source_uv):
        scale = nodes.new("ShaderNodeVectorMath")
        scale.operation = "MULTIPLY"
        scale.inputs[1].default_value = atlas_scale_value
        links.new(source_uv, scale.inputs[0])
        offset = nodes.new("ShaderNodeVectorMath")
        offset.operation = "ADD"
        links.new(scale.outputs["Vector"], offset.inputs[0])
        links.new(selected_offset, offset.inputs[1])
        return offset.outputs["Vector"]

    def inside_owned_bounds(source_uv):
        separate = nodes.new("ShaderNodeSeparateXYZ")
        links.new(source_uv, separate.inputs[0])
        inside_sum = None
        for part in BODY_PARTS:
            minimum_x, minimum_y, maximum_x, maximum_y = metadata["parts"][part][
                "source_bounds"
            ]
            checks = []
            for socket, operation, threshold in (
                (
                    separate.outputs["X"],
                    "GREATER_THAN",
                    (minimum_x - 0.5) / max(source_width - 1, 1),
                ),
                (
                    separate.outputs["X"],
                    "LESS_THAN",
                    (maximum_x + 0.5) / max(source_width - 1, 1),
                ),
                (
                    separate.outputs["Y"],
                    "GREATER_THAN",
                    (minimum_y - 0.5) / max(source_height - 1, 1),
                ),
                (
                    separate.outputs["Y"],
                    "LESS_THAN",
                    (maximum_y + 0.5) / max(source_height - 1, 1),
                ),
            ):
                check = nodes.new("ShaderNodeMath")
                check.operation = operation
                check.inputs[1].default_value = threshold
                links.new(socket, check.inputs[0])
                checks.append(check.outputs[0])
            inside = checks[0]
            for check in checks[1:]:
                product = nodes.new("ShaderNodeMath")
                product.operation = "MULTIPLY"
                links.new(inside, product.inputs[0])
                links.new(check, product.inputs[1])
                inside = product.outputs[0]
            owned = nodes.new("ShaderNodeMath")
            owned.operation = "MULTIPLY"
            links.new(inside, owned.inputs[0])
            links.new(owner_masks[part], owned.inputs[1])
            inside_sum = (
                owned.outputs[0]
                if inside_sum is None
                else _add_socket(nodes, links, inside_sum, owned.outputs[0])
            )
        return inside_sum

    primary_uv = atlas_uv(selected_source_uv)
    safe_factor = 1.0 - settings.source_edge_padding
    safe_scale = nodes.new("ShaderNodeVectorMath")
    safe_scale.name = f"SBF_SafeUVScale_{name}"
    safe_scale.operation = "MULTIPLY"
    safe_scale.inputs[1].default_value = (safe_factor, safe_factor, 1.0)
    links.new(selected_source_uv, safe_scale.inputs[0])
    safe_offset = nodes.new("ShaderNodeVectorMath")
    safe_offset.name = f"SBF_SafeUVOffset_{name}"
    safe_offset.operation = "ADD"
    safe_offset.inputs[1].default_value = (
        settings.source_edge_padding * 0.5,
        settings.source_edge_padding * 0.5,
        0.0,
    )
    links.new(safe_scale.outputs["Vector"], safe_offset.inputs[0])
    safe_source_uv = safe_offset.outputs["Vector"]
    safe_uv = atlas_uv(safe_source_uv)

    texture = nodes.new("ShaderNodeTexImage")
    texture.name = f"SBF_WarpAtlas_{name}"
    texture.label = f"{name.title()} Body-Part Warp Atlas"
    texture.image = image
    texture.interpolation = "Linear"
    texture.extension = "CLIP"
    texture.location = (40, y)
    links.new(primary_uv, texture.inputs["Vector"])
    safe_texture = nodes.new("ShaderNodeTexImage")
    safe_texture.name = f"SBF_WarpAtlasSafe_{name}"
    safe_texture.label = f"{name.title()} Safe Warp Atlas"
    safe_texture.image = image
    safe_texture.interpolation = "Linear"
    safe_texture.extension = "CLIP"
    safe_texture.location = (40, y - 80)
    links.new(safe_uv, safe_texture.inputs["Vector"])

    primary_alpha = nodes.new("ShaderNodeMath")
    primary_alpha.operation = "MULTIPLY"
    links.new(texture.outputs["Alpha"], primary_alpha.inputs[0])
    links.new(inside_owned_bounds(selected_source_uv), primary_alpha.inputs[1])
    safe_alpha = nodes.new("ShaderNodeMath")
    safe_alpha.operation = "MULTIPLY"
    links.new(safe_texture.outputs["Alpha"], safe_alpha.inputs[0])
    links.new(inside_owned_bounds(safe_source_uv), safe_alpha.inputs[1])

    primary_valid = nodes.new("ShaderNodeMath")
    primary_valid.operation = "GREATER_THAN"
    primary_valid.inputs[1].default_value = view_settings.alpha_threshold
    links.new(primary_alpha.outputs[0], primary_valid.inputs[0])
    primary_invalid = nodes.new("ShaderNodeMath")
    primary_invalid.operation = "SUBTRACT"
    primary_invalid.inputs[0].default_value = 1.0
    links.new(primary_valid.outputs[0], primary_invalid.inputs[1])
    safe_valid = nodes.new("ShaderNodeMath")
    safe_valid.operation = "GREATER_THAN"
    safe_valid.inputs[1].default_value = view_settings.alpha_threshold
    links.new(safe_alpha.outputs[0], safe_valid.inputs[0])
    fill = nodes.new("ShaderNodeMath")
    fill.operation = "MULTIPLY"
    links.new(primary_invalid.outputs[0], fill.inputs[0])
    links.new(safe_valid.outputs[0], fill.inputs[1])
    color = nodes.new("ShaderNodeMixRGB")
    color.blend_type = "MIX"
    links.new(fill.outputs[0], color.inputs[0])
    links.new(texture.outputs["Color"], color.inputs[1])
    links.new(safe_texture.outputs["Color"], color.inputs[2])
    alpha = nodes.new("ShaderNodeMath")
    alpha.operation = "MAXIMUM"
    links.new(primary_alpha.outputs[0], alpha.inputs[0])
    links.new(safe_alpha.outputs[0], alpha.inputs[1])
    return color.outputs["Color"], alpha.outputs[0]


def _fallback_uv_name(info):
    vector = info.base_color_node.inputs.get("Vector")
    if vector is not None and vector.is_linked:
        source = vector.links[0].from_node
        if (
            source.bl_idname == "ShaderNodeUVMap"
            and info.mesh.uv_layers.get(source.uv_map)
        ):
            return source.uv_map
    return info.uv_name


def create_preview_material(info, settings):
    material = bpy.data.materials.new(f"{PREVIEW_MATERIAL_PREFIX}{info.obj.name}")
    material.use_nodes = True
    material[TEMPORARY_PROPERTY] = True
    material["sbf_original_material"] = info.material.name
    material["sbf_original_slot"] = info.material_slot
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (1500, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (1280, 0)
    emission.inputs["Strength"].default_value = 1.0
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    old_uv = nodes.new("ShaderNodeUVMap")
    old_uv.uv_map = _fallback_uv_name(info)
    old_tex = nodes.new("ShaderNodeTexImage")
    old_tex.image = info.original_base_image
    old_tex.interpolation = "Linear"
    links.new(old_uv.outputs["UV"], old_tex.inputs["Vector"])
    head_mask = nodes.new("ShaderNodeAttribute")
    head_mask.attribute_name = f"{WEIGHT_ATTRIBUTE_PREFIX}head_mask"
    part_id = nodes.new("ShaderNodeAttribute")
    part_id.name = "SBF_BodyPartOwnerID"
    part_id.attribute_name = BODY_PART_ID_ATTRIBUTE

    view_weight_sockets = {}
    for pack_index in range(0, len(VIEW_NAMES), 3):
        names = VIEW_NAMES[pack_index : pack_index + 3]
        active_names = [
            name
            for name in names
            if getattr(settings, name).enabled
            and getattr(settings, name).image is not None
        ]
        if not active_names:
            continue
        packed = nodes.new("ShaderNodeAttribute")
        packed.name = f"SBF_ViewWeightPack_{pack_index // 3}"
        packed.attribute_name = f"{VIEW_WEIGHT_PACK_PREFIX}{pack_index // 3}"
        separate = nodes.new("ShaderNodeSeparateXYZ")
        links.new(packed.outputs["Vector"], separate.inputs[0])
        for component, name in enumerate(names):
            view_weight_sockets[name] = separate.outputs[component]

    sum_vector = sum_weight = head_sum_vector = head_sum_weight = None
    active_views = 0
    for row, name in enumerate(VIEW_NAMES):
        view = getattr(settings, name)
        if not view.enabled or view.image is None:
            continue
        active_views += 1
        y = 600 - row * 330
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = f"{PROJECTION_UV_PREFIX}{name}"
        uv_scale = nodes.new("ShaderNodeVectorMath")
        uv_scale.name = f"SBF_UVScale_{name}"
        uv_scale.operation = "MULTIPLY"
        links.new(uv.outputs["UV"], uv_scale.inputs[0])
        uv_offset = nodes.new("ShaderNodeVectorMath")
        uv_offset.name = f"SBF_UVOffset_{name}"
        uv_offset.operation = "ADD"
        links.new(uv_scale.outputs["Vector"], uv_offset.inputs[0])
        head_scale = nodes.new("ShaderNodeVectorMath")
        head_scale.name = f"SBF_HeadUVScale_{name}"
        head_scale.operation = "MULTIPLY"
        links.new(uv_offset.outputs["Vector"], head_scale.inputs[0])
        head_offset = nodes.new("ShaderNodeVectorMath")
        head_offset.name = f"SBF_HeadUVOffset_{name}"
        head_offset.operation = "ADD"
        links.new(head_scale.outputs["Vector"], head_offset.inputs[0])

        color, alpha = _guarded_view_source(
            nodes,
            links,
            name,
            view,
            uv_offset.outputs["Vector"],
            head_offset.outputs["Vector"],
            settings,
            y,
            part_id.outputs["Fac"],
        )
        threshold = nodes.new("ShaderNodeMath")
        threshold.name = f"SBF_AlphaThreshold_{name}"
        threshold.operation = "GREATER_THAN"
        threshold.inputs[1].default_value = view.alpha_threshold
        links.new(alpha, threshold.inputs[0])
        luminance = nodes.new("ShaderNodeRGBToBW")
        links.new(color, luminance.inputs["Color"])
        black_key = nodes.new("ShaderNodeMath")
        black_key.name = f"SBF_BlackKey_{name}"
        black_key.operation = "GREATER_THAN"
        black_key.inputs[1].default_value = view.black_key_threshold
        links.new(luminance.outputs["Val"], black_key.inputs[0])
        black_disabled = nodes.new("ShaderNodeMath")
        black_disabled.name = f"SBF_BlackKeyDisabled_{name}"
        black_disabled.operation = "SUBTRACT"
        black_disabled.inputs[0].default_value = 1.0
        black_disabled.inputs[1].default_value = 1.0 if view.key_black_background else 0.0
        black_mask = nodes.new("ShaderNodeMath")
        black_mask.operation = "MAXIMUM"
        links.new(black_key.outputs[0], black_mask.inputs[0])
        links.new(black_disabled.outputs[0], black_mask.inputs[1])
        source_mask = nodes.new("ShaderNodeMath")
        source_mask.operation = "MULTIPLY"
        links.new(threshold.outputs[0], source_mask.inputs[0])
        links.new(black_mask.outputs[0], source_mask.inputs[1])
        masked_alpha = nodes.new("ShaderNodeMath")
        masked_alpha.operation = "MULTIPLY"
        links.new(alpha, masked_alpha.inputs[0])
        links.new(source_mask.outputs[0], masked_alpha.inputs[1])

        live = nodes.new("ShaderNodeMath")
        live.name = f"SBF_LiveWeight_{name}"
        live.operation = "MULTIPLY"
        live.inputs[1].default_value = view.weight
        links.new(view_weight_sockets[name], live.inputs[0])
        alpha_weight = nodes.new("ShaderNodeMath")
        alpha_weight.operation = "MULTIPLY"
        links.new(masked_alpha.outputs[0], alpha_weight.inputs[0])
        links.new(live.outputs[0], alpha_weight.inputs[1])
        weighted_color = nodes.new("ShaderNodeVectorMath")
        weighted_color.operation = "SCALE"
        links.new(color, weighted_color.inputs[0])
        links.new(alpha_weight.outputs[0], _scale_socket(weighted_color))
        head_confidence = nodes.new("ShaderNodeMath")
        head_confidence.name = f"SBF_HeadConfidence_{name}"
        head_confidence.operation = "POWER"
        head_confidence.inputs[1].default_value = settings.head_blend_sharpness
        links.new(alpha_weight.outputs[0], head_confidence.inputs[0])
        head_color = nodes.new("ShaderNodeVectorMath")
        head_color.operation = "SCALE"
        links.new(color, head_color.inputs[0])
        links.new(head_confidence.outputs[0], _scale_socket(head_color))
        _apply_view_controls(nodes, name, view)

        if sum_vector is None:
            sum_vector = weighted_color.outputs["Vector"]
            sum_weight = alpha_weight.outputs[0]
            head_sum_vector = head_color.outputs["Vector"]
            head_sum_weight = head_confidence.outputs[0]
        else:
            sum_vector = _add_socket(nodes, links, sum_vector, weighted_color.outputs["Vector"], vector=True)
            sum_weight = _add_socket(nodes, links, sum_weight, alpha_weight.outputs[0])
            head_sum_vector = _add_socket(nodes, links, head_sum_vector, head_color.outputs["Vector"], vector=True)
            head_sum_weight = _add_socket(nodes, links, head_sum_weight, head_confidence.outputs[0])

    if not active_views:
        bpy.data.materials.remove(material, do_unlink=True)
        raise RuntimeError("No enabled projection images are available.")

    def normalized_color(vector, weight):
        safe = nodes.new("ShaderNodeMath")
        safe.operation = "MAXIMUM"
        safe.inputs[1].default_value = 0.0001
        links.new(weight, safe.inputs[0])
        reciprocal = nodes.new("ShaderNodeMath")
        reciprocal.operation = "DIVIDE"
        reciprocal.inputs[0].default_value = 1.0
        links.new(safe.outputs[0], reciprocal.inputs[1])
        normalized = nodes.new("ShaderNodeVectorMath")
        normalized.operation = "SCALE"
        links.new(vector, normalized.inputs[0])
        links.new(reciprocal.outputs[0], _scale_socket(normalized))
        return normalized.outputs["Vector"]

    body_color = normalized_color(sum_vector, sum_weight)
    identity_color = normalized_color(head_sum_vector, head_sum_weight)
    head_projection = nodes.new("ShaderNodeMixRGB")
    head_projection.name = "SBF_HeadProjection"
    head_projection.blend_type = "MIX"
    links.new(head_mask.outputs["Fac"], head_projection.inputs[0])
    links.new(body_color, head_projection.inputs[1])
    links.new(identity_color, head_projection.inputs[2])
    has_projection = nodes.new("ShaderNodeMath")
    has_projection.operation = "GREATER_THAN"
    has_projection.inputs[1].default_value = settings.fallback_threshold
    links.new(sum_weight, has_projection.inputs[0])
    fallback = nodes.new("ShaderNodeMixRGB")
    fallback.blend_type = "MIX"
    links.new(has_projection.outputs[0], fallback.inputs[0])
    links.new(old_tex.outputs["Color"], fallback.inputs[1])
    links.new(head_projection.outputs["Color"], fallback.inputs[2])
    links.new(fallback.outputs["Color"], emission.inputs["Color"])
    _apply_global_controls(nodes, settings)
    stamp_preview_source_state(material, settings)
    info.obj.material_slots[info.material_slot].material = material
    return material
