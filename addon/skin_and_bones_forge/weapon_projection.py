"""Mirrored single-plate weapon projection and baking.

This utility is deliberately separate from the humanoid Source Doctor / landmark
pipeline. It accepts a prepared weapon mesh and one already-background-removed
RGBA plate, projects that plate onto one side, mirrors it onto the opposite side,
previews the result non-destructively, and bakes the composite into the weapon's
existing UV map.
"""

from __future__ import annotations

from array import array
import math
from pathlib import Path
import re

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Image, Material, Object, Operator, Panel, PropertyGroup
from bpy_extras.io_utils import ImportHelper

from .constants import EXPORT_TEXTURE_DIR


WEAPON_PREVIEW_PREFIX = "SBF_WeaponPreview_"
WEAPON_BAKE_NODE = "SBF_WeaponBakeTarget"
WEAPON_UV_NODE = "SBF_WeaponBakedUV"
WEAPON_IMAGE_NODE = "SBF_WeaponBakedBaseColor"


def _mesh_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


def _safe_name(value):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return value.strip("._") or "weapon"


def _active_preview_material(settings):
    target = settings.target_object
    if target is None or target.type != "MESH":
        return None
    for slot in target.material_slots:
        material = slot.material
        if material is not None and material.get("sbf_weapon_projection_preview", False):
            return material
    return None


def _mark_preview_stale(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_weapon_projection", None)
    if settings is None:
        return
    if settings.preview_ready:
        settings.preview_ready = False
        settings.status = "Weapon source changed. Rebuild the preview."


def _set_math_value(nodes, name, value):
    node = nodes.get(name)
    if node is not None and len(node.inputs) > 1:
        node.inputs[1].default_value = float(value)


def _apply_live_controls(settings):
    material = _active_preview_material(settings)
    if material is None or material.node_tree is None:
        return False

    nodes = material.node_tree.nodes
    scale = max(float(settings.scale), 1.0e-6)
    width = max(float(settings.horizontal_scale), 1.0e-6)
    sign_x = -1.0 if settings.flip_x else 1.0
    sign_y = -1.0 if settings.flip_y else 1.0
    angle = float(settings.rotation)

    _set_math_value(nodes, "SBF_WP_UScale", sign_x / (scale * width))
    _set_math_value(nodes, "SBF_WP_VScale", sign_y / scale)
    _set_math_value(nodes, "SBF_WP_UCos", math.cos(angle))
    _set_math_value(nodes, "SBF_WP_VSin", math.sin(angle))
    _set_math_value(nodes, "SBF_WP_USin", math.sin(angle))
    _set_math_value(nodes, "SBF_WP_VCos", math.cos(angle))
    _set_math_value(
        nodes,
        "SBF_WP_BackMirrorScale",
        -1.0 if settings.mirror_opposite else 1.0,
    )
    _set_math_value(
        nodes,
        "SBF_WP_BackMirrorOffset",
        1.0 if settings.mirror_opposite else 0.0,
    )
    _set_math_value(nodes, "SBF_WP_UOffset", 0.5 + float(settings.offset_x))
    _set_math_value(nodes, "SBF_WP_VOffset", 0.5 + float(settings.offset_y))
    _set_math_value(nodes, "SBF_WP_AlphaThreshold", settings.alpha_threshold)
    _set_math_value(nodes, "SBF_WP_Opacity", settings.opacity)
    # High power = side-only. Low power = more coverage around rounded edges.
    _set_math_value(
        nodes,
        "SBF_WP_SurfacePower",
        8.0 - 7.5 * float(settings.edge_wrap),
    )

    for name in ("SBF_WP_FrontImage", "SBF_WP_BackImage"):
        image_node = nodes.get(name)
        if image_node is not None:
            image_node.image = settings.source_image

    material.node_tree.update_tag()
    settings.target_object.data.update()
    return True


def _update_live(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_weapon_projection", None)
    if settings is None:
        return
    if _apply_live_controls(settings):
        settings.preview_ready = True
        settings.status = "Weapon projection preview updated."


def _rebuild_preview(_settings, context):
    if context is None or context.scene is None:
        return
    settings = getattr(context.scene, "sbf_weapon_projection", None)
    if settings is None or not settings.preview_ready:
        return
    try:
        create_weapon_preview(context, settings)
    except (RuntimeError, ValueError, ReferenceError) as exc:
        settings.preview_ready = False
        settings.status = f"Preview rebuild required: {exc}"


class SBFWeaponProjectionSettings(PropertyGroup):
    target_object: PointerProperty(
        name="Weapon Mesh",
        description="Mesh that receives the single-plate mirrored texture",
        type=Object,
        poll=_mesh_poll,
        update=_mark_preview_stale,
    )
    source_image: PointerProperty(
        name="Projection Plate",
        description="Already background-removed RGBA weapon image",
        type=Image,
        update=_mark_preview_stale,
    )
    projection_axis: EnumProperty(
        name="Projection Depth",
        description="Local axis separating the two broad weapon sides",
        items=(
            ("X", "Local X", "Project across the Y/Z silhouette"),
            ("Y", "Local Y", "Project across the X/Z silhouette"),
            ("Z", "Local Z", "Project across the X/Y silhouette"),
        ),
        default="Y",
        update=_rebuild_preview,
    )
    source_side: EnumProperty(
        name="Source Side",
        description="Side that receives the unmirrored plate",
        items=(
            ("POSITIVE", "Positive", "Positive side of the depth axis"),
            ("NEGATIVE", "Negative", "Negative side of the depth axis"),
        ),
        default="POSITIVE",
        update=_rebuild_preview,
    )
    mirror_opposite: BoolProperty(
        name="Mirror Opposite Side",
        default=True,
        description="Mirror the same plate horizontally on the opposite side",
        update=_update_live,
    )
    scale: FloatProperty(
        name="Scale",
        description="Uniform plate zoom around its center",
        default=1.0,
        min=0.1,
        max=10.0,
        soft_min=0.5,
        soft_max=3.0,
        update=_update_live,
    )
    horizontal_scale: FloatProperty(
        name="Width Fit",
        description="Independent horizontal fit multiplier",
        default=1.0,
        min=0.1,
        max=10.0,
        soft_min=0.5,
        soft_max=3.0,
        update=_update_live,
    )
    offset_x: FloatProperty(
        name="Horizontal",
        default=0.0,
        min=-2.0,
        max=2.0,
        soft_min=-0.25,
        soft_max=0.25,
        update=_update_live,
    )
    offset_y: FloatProperty(
        name="Vertical",
        default=0.0,
        min=-2.0,
        max=2.0,
        soft_min=-0.25,
        soft_max=0.25,
        update=_update_live,
    )
    rotation: FloatProperty(
        name="Rotation",
        subtype="ANGLE",
        default=0.0,
        min=-math.pi,
        max=math.pi,
        update=_update_live,
    )
    flip_x: BoolProperty(name="Flip X", default=False, update=_update_live)
    flip_y: BoolProperty(name="Flip Y", default=False, update=_update_live)
    edge_wrap: FloatProperty(
        name="Edge Wrap",
        description="Allow the broad-side plate to continue farther around rounded edges",
        default=0.20,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update_live,
    )
    alpha_threshold: FloatProperty(
        name="Alpha Cut",
        description="Reject faint transparent edge pixels from the prepared source plate",
        default=0.01,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update_live,
    )
    opacity: FloatProperty(
        name="Projection Strength",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
        update=_update_live,
    )
    texture_size: EnumProperty(
        name="Bake Size",
        items=(
            ("512", "512", "512 x 512"),
            ("1024", "1024", "1024 x 1024"),
            ("2048", "2048", "2048 x 2048"),
            ("4096", "4096", "4096 x 4096"),
        ),
        default="1024",
    )
    bake_margin: IntProperty(name="Bake Margin", default=16, min=0, max=256)
    output_image_path: StringProperty(
        name="Baked Base Color",
        subtype="FILE_PATH",
        default=rf"{EXPORT_TEXTURE_DIR}\weapon_baked_base_color.png",
    )
    pack_baked_image: BoolProperty(name="Pack Baked Image", default=True)
    preview_ready: BoolProperty(default=False, options={"HIDDEN"})
    original_material: PointerProperty(type=Material, options={"HIDDEN"})
    original_slot_index: IntProperty(default=0, options={"HIDDEN"})
    last_baked_image: PointerProperty(type=Image, options={"HIDDEN"})
    status: StringProperty(
        name="Status",
        default="Choose a weapon mesh and its background-removed plate.",
    )


def _active_uv_name(target):
    if not target.data.uv_layers:
        raise RuntimeError(
            "Weapon mesh has no UV map. The weapon baker preserves an existing UV."
        )
    layer = target.data.uv_layers.active or target.data.uv_layers[0]
    return layer.name


def _ensure_original_material(target, settings):
    if not target.material_slots:
        material = bpy.data.materials.new(f"SBF_WeaponBase_{target.name}")
        material.use_nodes = True
        target.data.materials.append(material)
        target.active_material_index = 0

    slot_index = min(
        max(int(target.active_material_index), 0),
        len(target.material_slots) - 1,
    )
    current = target.material_slots[slot_index].material
    if current is not None and current.get("sbf_weapon_projection_preview", False):
        original = settings.original_material
        if original is None:
            original = bpy.data.materials.get(
                current.get("sbf_weapon_original_material", "")
            )
        if original is None:
            raise RuntimeError("Weapon preview lost its original material.")
        return original, slot_index, current

    if current is None:
        current = bpy.data.materials.new(f"SBF_WeaponBase_{target.name}")
        current.use_nodes = True
        target.material_slots[slot_index].material = current
    current.use_nodes = True
    return current, slot_index, None


def _math(nodes, operation, name, first=None, second=None):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    node.name = name
    if isinstance(first, (int, float)):
        node.inputs[0].default_value = float(first)
    if isinstance(second, (int, float)):
        node.inputs[1].default_value = float(second)
    return node


def _axis_socket(nodes, links, generated, axis, name):
    separate = nodes.new("ShaderNodeSeparateXYZ")
    separate.name = name
    links.new(generated, separate.inputs[0])
    return separate.outputs[{"X": 0, "Y": 1, "Z": 2}[axis]]


def _projection_axes(axis):
    if axis == "X":
        return "Y", "Z"
    if axis == "Z":
        return "X", "Y"
    return "X", "Z"


def _base_color_source(nodes):
    principled = next(
        (node for node in nodes if node.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )
    if principled is not None:
        socket = principled.inputs.get("Base Color")
        if socket is not None and socket.is_linked:
            return socket.links[0].from_socket
        if socket is not None:
            color = nodes.new("ShaderNodeRGB")
            color.name = "SBF_WP_OriginalBaseColor"
            color.outputs[0].default_value = tuple(socket.default_value)
            return color.outputs[0]

    color = nodes.new("ShaderNodeRGB")
    color.name = "SBF_WP_OriginalBaseColor"
    color.outputs[0].default_value = (0.18, 0.18, 0.18, 1.0)
    return color.outputs[0]


def _build_transformed_uv(nodes, links, u_socket, v_socket):
    u_center = _math(nodes, "SUBTRACT", "SBF_WP_UCenter", second=0.5)
    v_center = _math(nodes, "SUBTRACT", "SBF_WP_VCenter", second=0.5)
    links.new(u_socket, u_center.inputs[0])
    links.new(v_socket, v_center.inputs[0])

    u_scale = _math(nodes, "MULTIPLY", "SBF_WP_UScale", second=1.0)
    v_scale = _math(nodes, "MULTIPLY", "SBF_WP_VScale", second=1.0)
    links.new(u_center.outputs[0], u_scale.inputs[0])
    links.new(v_center.outputs[0], v_scale.inputs[0])

    u_cos = _math(nodes, "MULTIPLY", "SBF_WP_UCos", second=1.0)
    v_sin = _math(nodes, "MULTIPLY", "SBF_WP_VSin", second=0.0)
    u_sin = _math(nodes, "MULTIPLY", "SBF_WP_USin", second=0.0)
    v_cos = _math(nodes, "MULTIPLY", "SBF_WP_VCos", second=1.0)
    links.new(u_scale.outputs[0], u_cos.inputs[0])
    links.new(v_scale.outputs[0], v_sin.inputs[0])
    links.new(u_scale.outputs[0], u_sin.inputs[0])
    links.new(v_scale.outputs[0], v_cos.inputs[0])

    rot_u = _math(nodes, "SUBTRACT", "SBF_WP_RotU")
    rot_v = _math(nodes, "ADD", "SBF_WP_RotV")
    links.new(u_cos.outputs[0], rot_u.inputs[0])
    links.new(v_sin.outputs[0], rot_u.inputs[1])
    links.new(u_sin.outputs[0], rot_v.inputs[0])
    links.new(v_cos.outputs[0], rot_v.inputs[1])

    u_offset = _math(nodes, "ADD", "SBF_WP_UOffset", second=0.5)
    v_offset = _math(nodes, "ADD", "SBF_WP_VOffset", second=0.5)
    links.new(rot_u.outputs[0], u_offset.inputs[0])
    links.new(rot_v.outputs[0], v_offset.inputs[0])

    front_uv = nodes.new("ShaderNodeCombineXYZ")
    front_uv.name = "SBF_WP_FrontUV"
    links.new(u_offset.outputs[0], front_uv.inputs["X"])
    links.new(v_offset.outputs[0], front_uv.inputs["Y"])

    mirror_scale = _math(
        nodes,
        "MULTIPLY",
        "SBF_WP_BackMirrorScale",
        second=-1.0,
    )
    mirror_offset = _math(
        nodes,
        "ADD",
        "SBF_WP_BackMirrorOffset",
        second=1.0,
    )
    links.new(u_offset.outputs[0], mirror_scale.inputs[0])
    links.new(mirror_scale.outputs[0], mirror_offset.inputs[0])

    back_uv = nodes.new("ShaderNodeCombineXYZ")
    back_uv.name = "SBF_WP_BackUV"
    links.new(mirror_offset.outputs[0], back_uv.inputs["X"])
    links.new(v_offset.outputs[0], back_uv.inputs["Y"])
    return front_uv.outputs["Vector"], back_uv.outputs["Vector"]


def create_weapon_preview(context, settings):
    target = settings.target_object
    if target is None or target.type != "MESH":
        raise RuntimeError("Choose a weapon mesh.")
    if settings.source_image is None:
        raise RuntimeError("Choose the background-removed weapon projection plate.")
    _active_uv_name(target)

    original, slot_index, old_preview = _ensure_original_material(target, settings)
    if old_preview is not None:
        target.material_slots[slot_index].material = original
        bpy.data.materials.remove(old_preview)

    preview = original.copy()
    preview.name = f"{WEAPON_PREVIEW_PREFIX}{target.name}"
    preview.use_nodes = True
    preview["sbf_weapon_projection_preview"] = True
    preview["sbf_weapon_original_material"] = original.name
    preview["sbf_weapon_original_slot"] = slot_index

    settings.original_material = original
    settings.original_slot_index = slot_index

    nodes = preview.node_tree.nodes
    links = preview.node_tree.links
    original_color = _base_color_source(nodes)

    output = next(
        (node for node in nodes if node.bl_idname == "ShaderNodeOutputMaterial"),
        None,
    )
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
    for link in list(output.inputs["Surface"].links):
        links.remove(link)

    texcoord = nodes.new("ShaderNodeTexCoord")
    texcoord.name = "SBF_WP_TexCoord"
    generated = texcoord.outputs["Generated"]
    u_axis, v_axis = _projection_axes(settings.projection_axis)
    u_socket = _axis_socket(nodes, links, generated, u_axis, "SBF_WP_UAxis")
    v_socket = _axis_socket(nodes, links, generated, v_axis, "SBF_WP_VAxis")
    depth_socket = _axis_socket(
        nodes,
        links,
        generated,
        settings.projection_axis,
        "SBF_WP_DepthAxis",
    )
    front_uv, back_uv = _build_transformed_uv(nodes, links, u_socket, v_socket)

    front_image = nodes.new("ShaderNodeTexImage")
    front_image.name = "SBF_WP_FrontImage"
    front_image.label = "Single Weapon Plate"
    front_image.image = settings.source_image
    front_image.interpolation = "Linear"
    front_image.extension = "CLIP"
    links.new(front_uv, front_image.inputs["Vector"])

    back_image = nodes.new("ShaderNodeTexImage")
    back_image.name = "SBF_WP_BackImage"
    back_image.label = "Mirrored Opposite Side"
    back_image.image = settings.source_image
    back_image.interpolation = "Linear"
    back_image.extension = "CLIP"
    links.new(back_uv, back_image.inputs["Vector"])

    positive_side = _math(nodes, "GREATER_THAN", "SBF_WP_PositiveSide", second=0.5)
    links.new(depth_socket, positive_side.inputs[0])

    side_color = nodes.new("ShaderNodeMixRGB")
    side_color.name = "SBF_WP_SideColor"
    links.new(positive_side.outputs[0], side_color.inputs[0])
    if settings.source_side == "POSITIVE":
        links.new(back_image.outputs["Color"], side_color.inputs[1])
        links.new(front_image.outputs["Color"], side_color.inputs[2])
    else:
        links.new(front_image.outputs["Color"], side_color.inputs[1])
        links.new(back_image.outputs["Color"], side_color.inputs[2])

    side_alpha = nodes.new("ShaderNodeMixRGB")
    side_alpha.name = "SBF_WP_SideAlpha"
    links.new(positive_side.outputs[0], side_alpha.inputs[0])
    if settings.source_side == "POSITIVE":
        links.new(back_image.outputs["Alpha"], side_alpha.inputs[1])
        links.new(front_image.outputs["Alpha"], side_alpha.inputs[2])
    else:
        links.new(front_image.outputs["Alpha"], side_alpha.inputs[1])
        links.new(back_image.outputs["Alpha"], side_alpha.inputs[2])

    alpha_threshold = _math(
        nodes,
        "GREATER_THAN",
        "SBF_WP_AlphaThreshold",
        second=settings.alpha_threshold,
    )
    links.new(side_alpha.outputs[0], alpha_threshold.inputs[0])

    center = _math(nodes, "SUBTRACT", "SBF_WP_DepthCenter", second=0.5)
    links.new(depth_socket, center.inputs[0])
    distance = _math(nodes, "ABSOLUTE", "SBF_WP_DepthDistance")
    links.new(center.outputs[0], distance.inputs[0])
    normalized_distance = _math(
        nodes,
        "MULTIPLY",
        "SBF_WP_NormalizedDepthDistance",
        second=2.0,
    )
    links.new(distance.outputs[0], normalized_distance.inputs[0])
    surface_power = _math(
        nodes,
        "POWER",
        "SBF_WP_SurfacePower",
        second=8.0 - 7.5 * settings.edge_wrap,
    )
    links.new(normalized_distance.outputs[0], surface_power.inputs[0])

    alpha_mask = _math(nodes, "MULTIPLY", "SBF_WP_AlphaMask")
    links.new(side_alpha.outputs[0], alpha_mask.inputs[0])
    links.new(alpha_threshold.outputs[0], alpha_mask.inputs[1])
    coverage_mask = _math(nodes, "MULTIPLY", "SBF_WP_CoverageMask")
    links.new(alpha_mask.outputs[0], coverage_mask.inputs[0])
    links.new(surface_power.outputs[0], coverage_mask.inputs[1])
    opacity = _math(nodes, "MULTIPLY", "SBF_WP_Opacity", second=settings.opacity)
    links.new(coverage_mask.outputs[0], opacity.inputs[0])

    composite = nodes.new("ShaderNodeMixRGB")
    composite.name = "SBF_WP_Composite"
    links.new(opacity.outputs[0], composite.inputs[0])
    links.new(original_color, composite.inputs[1])
    links.new(side_color.outputs[0], composite.inputs[2])

    emission = nodes.new("ShaderNodeEmission")
    emission.name = "SBF_WP_PreviewEmission"
    emission.inputs["Strength"].default_value = 1.0
    links.new(composite.outputs[0], emission.inputs["Color"])
    links.new(emission.outputs[0], output.inputs["Surface"])

    target.material_slots[slot_index].material = preview
    settings.preview_ready = True
    settings.status = "Mirrored weapon projection preview ready."
    _apply_live_controls(settings)
    target.data.update()
    return preview


def clear_weapon_preview(settings):
    target = settings.target_object
    if target is None or target.type != "MESH":
        settings.preview_ready = False
        return False

    restored = False
    for index, slot in enumerate(target.material_slots):
        material = slot.material
        if material is None or not material.get("sbf_weapon_projection_preview", False):
            continue
        original = settings.original_material or bpy.data.materials.get(
            material.get("sbf_weapon_original_material", "")
        )
        if original is not None:
            target.material_slots[index].material = original
            restored = True
        bpy.data.materials.remove(material)
    settings.preview_ready = False
    if restored:
        settings.status = "Weapon preview cleared; original material restored."
    return restored


def _alpha_bounds(image, threshold):
    width = int(image.size[0])
    height = int(image.size[1])
    if width <= 0 or height <= 0:
        raise RuntimeError("Projection plate has no loaded pixel data.")

    values = array("f", [0.0]) * (width * height * 4)
    image.pixels.foreach_get(values)
    min_x = width
    min_y = height
    max_x = -1
    max_y = -1
    for pixel_index in range(width * height):
        if values[pixel_index * 4 + 3] <= threshold:
            continue
        x = pixel_index % width
        y = pixel_index // width
        min_x = min(min_x, x)
        max_x = max(max_x, x)
        min_y = min(min_y, y)
        max_y = max(max_y, y)
    if max_x < min_x or max_y < min_y:
        raise RuntimeError("Projection plate contains no visible alpha silhouette.")

    # A small safety border keeps antialiased silhouette pixels inside the sample.
    pad_x = max(1, int(round((max_x - min_x + 1) * 0.015)))
    pad_y = max(1, int(round((max_y - min_y + 1) * 0.015)))
    min_x = max(0, min_x - pad_x)
    max_x = min(width - 1, max_x + pad_x)
    min_y = max(0, min_y - pad_y)
    max_y = min(height - 1, max_y + pad_y)

    minimum_u = min_x / width
    maximum_u = (max_x + 1) / width
    minimum_v = min_y / height
    maximum_v = (max_y + 1) / height
    return minimum_u, minimum_v, maximum_u, maximum_v


def auto_fit_plate(settings):
    image = settings.source_image
    if image is None:
        raise RuntimeError("Load the background-removed weapon plate first.")
    minimum_u, minimum_v, maximum_u, maximum_v = _alpha_bounds(
        image,
        max(0.001, settings.alpha_threshold),
    )
    span_u = max(maximum_u - minimum_u, 1.0e-6)
    span_v = max(maximum_v - minimum_v, 1.0e-6)
    settings.scale = 1.0 / span_v
    settings.horizontal_scale = span_v / span_u
    settings.offset_x = (minimum_u + maximum_u) * 0.5 - 0.5
    settings.offset_y = (minimum_v + maximum_v) * 0.5 - 0.5
    settings.rotation = 0.0
    settings.flip_x = False
    settings.flip_y = False
    settings.status = "Plate alpha silhouette auto-fit. Fine-tune with the live controls."


def _find_or_create_principled(material):
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = next(
        (node for node in nodes if node.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )
    if principled is None:
        principled = nodes.new("ShaderNodeBsdfPrincipled")
        output = next(
            (node for node in nodes if node.bl_idname == "ShaderNodeOutputMaterial"),
            None,
        )
        if output is None:
            output = nodes.new("ShaderNodeOutputMaterial")
        for link in list(output.inputs["Surface"].links):
            links.remove(link)
        links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    return principled


def _bind_baked_base_color(material, image, uv_name):
    principled = _find_or_create_principled(material)
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    uv_node = nodes.get(WEAPON_UV_NODE)
    if uv_node is None or uv_node.bl_idname != "ShaderNodeUVMap":
        uv_node = nodes.new("ShaderNodeUVMap")
        uv_node.name = WEAPON_UV_NODE
    uv_node.uv_map = uv_name
    uv_node.label = "Weapon Existing UV"

    image_node = nodes.get(WEAPON_IMAGE_NODE)
    if image_node is None or image_node.bl_idname != "ShaderNodeTexImage":
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.name = WEAPON_IMAGE_NODE
    image_node.image = image
    image_node.interpolation = "Linear"
    image_node.extension = "REPEAT"
    image_node.label = "Mirrored Weapon Base Color"

    vector = image_node.inputs.get("Vector")
    if vector is not None:
        for link in list(vector.links):
            links.remove(link)
        links.new(uv_node.outputs["UV"], vector)

    base = principled.inputs.get("Base Color")
    if base is None:
        raise RuntimeError("Production material has no Principled Base Color input.")
    for link in list(base.links):
        links.remove(link)
    links.new(image_node.outputs["Color"], base)


def bake_weapon_texture(context, settings):
    target = settings.target_object
    preview = _active_preview_material(settings)
    if target is None or target.type != "MESH":
        raise RuntimeError("Choose a weapon mesh.")
    if preview is None or not settings.preview_ready:
        raise RuntimeError("Create the weapon projection preview before baking.")
    uv_name = _active_uv_name(target)
    original = settings.original_material
    if original is None:
        original = bpy.data.materials.get(preview.get("sbf_weapon_original_material", ""))
    if original is None:
        raise RuntimeError("Weapon preview lost the original production material.")

    size = int(settings.texture_size)
    image = bpy.data.images.new(
        f"SBF_WeaponBaked_{_safe_name(target.name)}_{size}",
        width=size,
        height=size,
        alpha=True,
        float_buffer=False,
    )
    image.colorspace_settings.name = "sRGB"
    image.alpha_mode = "STRAIGHT"
    image.generated_color = (0.0, 0.0, 0.0, 0.0)

    nodes = preview.node_tree.nodes
    bake_node = nodes.get(WEAPON_BAKE_NODE)
    if bake_node is not None:
        nodes.remove(bake_node)
    bake_node = nodes.new("ShaderNodeTexImage")
    bake_node.name = WEAPON_BAKE_NODE
    bake_node.label = "Weapon Bake Target"
    bake_node.image = image
    nodes.active = bake_node
    for node in nodes:
        node.select = False
    bake_node.select = True

    selected_before = list(context.selected_objects)
    active_before = context.view_layer.objects.active
    mode_before = target.mode
    scene = context.scene
    engine_before = scene.render.engine
    samples_before = scene.cycles.samples
    device_before = scene.cycles.device
    margin_before = scene.render.bake.margin
    margin_type_before = scene.render.bake.margin_type
    clear_before = scene.render.bake.use_clear

    try:
        if target.mode != "OBJECT":
            context.view_layer.objects.active = target
            bpy.ops.object.mode_set(mode="OBJECT")
        for obj in context.selected_objects:
            obj.select_set(False)
        target.select_set(True)
        context.view_layer.objects.active = target
        target.data.uv_layers.active = target.data.uv_layers[uv_name]
        target.data.uv_layers[uv_name].active_render = True

        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.render.bake.margin = settings.bake_margin
        scene.render.bake.margin_type = "ADJACENT_FACES"
        scene.render.bake.use_clear = True
        bpy.ops.object.bake(type="EMIT")
    except Exception:
        if image.users == 0:
            bpy.data.images.remove(image)
        raise
    finally:
        if nodes.get(WEAPON_BAKE_NODE) is not None:
            nodes.remove(nodes[WEAPON_BAKE_NODE])
        scene.render.engine = engine_before
        scene.cycles.samples = samples_before
        scene.cycles.device = device_before
        scene.render.bake.margin = margin_before
        scene.render.bake.margin_type = margin_type_before
        scene.render.bake.use_clear = clear_before

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

    output = Path(bpy.path.abspath(settings.output_image_path))
    if output.suffix.lower() != ".png":
        output = output.with_suffix(".png")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.filepath_raw = str(output)
    image.file_format = "PNG"
    image.save()
    if settings.pack_baked_image:
        image.pack()

    slot_index = min(settings.original_slot_index, len(target.material_slots) - 1)
    target.material_slots[slot_index].material = original
    _bind_baked_base_color(original, image, uv_name)
    if preview.users == 0:
        bpy.data.materials.remove(preview)

    settings.last_baked_image = image
    settings.preview_ready = False
    settings.status = f"Weapon texture baked and bound: {output.name}"
    target["sbf_weapon_projection_baked"] = True
    target["sbf_weapon_projection_source"] = settings.source_image.name
    target["sbf_weapon_projection_axis"] = settings.projection_axis
    target["sbf_weapon_projection_mirrored"] = bool(settings.mirror_opposite)
    target["sbf_weapon_base_color_path"] = str(output)
    target.data.update()
    return image, output


class SBF_OT_weapon_use_selected(Operator):
    bl_idname = "sbf.weapon_use_selected"
    bl_label = "Use Selected Weapon Mesh"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        target = context.active_object
        if target is None or target.type != "MESH":
            self.report({"ERROR"}, "Select one weapon mesh first.")
            return {"CANCELLED"}
        settings = context.scene.sbf_weapon_projection
        if settings.target_object is not target:
            clear_weapon_preview(settings)
        settings.target_object = target
        settings.output_image_path = str(
            Path(EXPORT_TEXTURE_DIR) / f"{_safe_name(target.name)}_base_color.png"
        )
        settings.status = "Weapon mesh selected. Load its transparent projection plate."
        return {"FINISHED"}


class SBF_OT_weapon_load_plate(Operator, ImportHelper):
    bl_idname = "sbf.weapon_load_plate"
    bl_label = "Load Weapon Projection Plate"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.png;*.tif;*.tiff;*.exr;*.jpg;*.jpeg", options={"HIDDEN"})

    def execute(self, context):
        try:
            image = bpy.data.images.load(self.filepath, check_existing=True)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings = context.scene.sbf_weapon_projection
        settings.source_image = image
        settings.status = "Projection plate loaded. Auto-fit or create preview."
        return {"FINISHED"}


class SBF_OT_weapon_auto_fit(Operator):
    bl_idname = "sbf.weapon_auto_fit"
    bl_label = "Auto Fit Plate"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.sbf_weapon_projection
        try:
            auto_fit_plate(settings)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class SBF_OT_weapon_preview(Operator):
    bl_idname = "sbf.weapon_preview"
    bl_label = "Create / Refresh Weapon Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.sbf_weapon_projection
        try:
            create_weapon_preview(context, settings)
        except RuntimeError as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class SBF_OT_weapon_bake(Operator):
    bl_idname = "sbf.weapon_bake"
    bl_label = "Bake + Bind Weapon Texture"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.sbf_weapon_projection
        try:
            _image, output = bake_weapon_texture(context, settings)
        except (RuntimeError, OSError) as exc:
            settings.status = str(exc)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Baked {output.name}")
        return {"FINISHED"}


class SBF_OT_weapon_clear_preview(Operator):
    bl_idname = "sbf.weapon_clear_preview"
    bl_label = "Clear Weapon Preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        clear_weapon_preview(context.scene.sbf_weapon_projection)
        return {"FINISHED"}


class SBF_PT_weapon_projection(Panel):
    bl_label = "WEAPON — Single-Plate Bake"
    bl_idname = "SBF_PT_weapon_projection"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Skin & Bones Forge"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 50

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_weapon_projection

        setup = layout.box()
        setup.label(text="Mass-Production Weapon Finish", icon="MESH_DATA")
        setup.operator("sbf.weapon_use_selected", icon="EYEDROPPER")
        setup.prop(settings, "target_object")
        setup.operator("sbf.weapon_load_plate", icon="FILE_FOLDER")
        setup.prop(settings, "source_image")

        projection = layout.box()
        projection.label(text="Projection", icon="IMAGE_DATA")
        row = projection.row(align=True)
        row.prop(settings, "projection_axis")
        row.prop(settings, "source_side")
        projection.prop(settings, "mirror_opposite", icon="MOD_MIRROR")
        fit = projection.row(align=True)
        fit.operator("sbf.weapon_auto_fit", icon="FULLSCREEN_ENTER")
        fit.operator("sbf.weapon_preview", icon="MATERIAL")

        alignment = layout.box()
        alignment.label(text="Live Fit", icon="ORIENTATION_VIEW")
        alignment.prop(settings, "scale")
        alignment.prop(settings, "horizontal_scale")
        offsets = alignment.row(align=True)
        offsets.prop(settings, "offset_x")
        offsets.prop(settings, "offset_y")
        alignment.prop(settings, "rotation")
        flips = alignment.row(align=True)
        flips.prop(settings, "flip_x")
        flips.prop(settings, "flip_y")
        alignment.prop(settings, "edge_wrap")
        fine = alignment.row(align=True)
        fine.prop(settings, "alpha_threshold")
        fine.prop(settings, "opacity")

        bake = layout.box()
        bake.label(text="Bake Into Existing Weapon UV", icon="RENDER_STILL")
        bake.prop(settings, "texture_size")
        bake.prop(settings, "output_image_path")
        bake.prop(settings, "bake_margin")
        bake.prop(settings, "pack_baked_image")
        action = bake.row()
        action.scale_y = 1.4
        action.enabled = settings.preview_ready
        action.operator("sbf.weapon_bake", text="BAKE + BIND TEXTURE", icon="CHECKMARK")
        bake.operator("sbf.weapon_clear_preview", icon="LOOP_BACK")

        status = layout.box()
        status.label(text=settings.status, icon="INFO")
        status.label(text="One RGBA plate → source side + mirrored opposite side.")
        status.label(text="Existing weapon UV, normal and PBR maps stay intact.")


WEAPON_CLASSES = (
    SBFWeaponProjectionSettings,
    SBF_OT_weapon_use_selected,
    SBF_OT_weapon_load_plate,
    SBF_OT_weapon_auto_fit,
    SBF_OT_weapon_preview,
    SBF_OT_weapon_bake,
    SBF_OT_weapon_clear_preview,
    SBF_PT_weapon_projection,
)


def register():
    for cls in WEAPON_CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sbf_weapon_projection = PointerProperty(
        type=SBFWeaponProjectionSettings
    )


def unregister():
    if hasattr(bpy.types.Scene, "sbf_weapon_projection"):
        del bpy.types.Scene.sbf_weapon_projection
    for cls in reversed(WEAPON_CLASSES):
        bpy.utils.unregister_class(cls)
