"""Blender properties exposed by the add-on."""

from __future__ import annotations

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Image, Material, Object, PropertyGroup


AXIS_ITEMS = (
    ("+X", "+X", "Positive X"),
    ("-X", "-X", "Negative X"),
    ("+Y", "+Y", "Positive Y"),
    ("-Y", "-Y", "Negative Y"),
    ("+Z", "+Z", "Positive Z"),
    ("-Z", "-Z", "Negative Z"),
)


def _mesh_object_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


class SBFViewSettings(PropertyGroup):
    image: PointerProperty(
        name="Image",
        description="RGBA projection image for this character view",
        type=Image,
    )
    enabled: BoolProperty(name="Enabled", default=True)
    flip_x: BoolProperty(name="Flip X", default=False)
    flip_y: BoolProperty(name="Flip Y", default=False)
    scale: FloatProperty(
        name="Scale",
        description="Scale the source around its center",
        default=1.0,
        min=0.1,
        max=5.0,
        soft_min=0.5,
        soft_max=2.0,
    )
    offset_x: FloatProperty(
        name="Horizontal",
        default=0.0,
        min=-2.0,
        max=2.0,
        soft_min=-0.25,
        soft_max=0.25,
    )
    offset_y: FloatProperty(
        name="Vertical",
        default=0.0,
        min=-2.0,
        max=2.0,
        soft_min=-0.25,
        soft_max=0.25,
    )
    alpha_threshold: FloatProperty(
        name="Alpha Threshold",
        default=0.01,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    weight: FloatProperty(
        name="Overall Weight",
        default=1.0,
        min=0.0,
        max=10.0,
        soft_max=2.0,
    )
    occlusion: BoolProperty(name="Occlusion", default=True)


class SBFSettings(PropertyGroup):
    target_object: PointerProperty(
        name="Target Mesh",
        description="SPAR3D mesh to process",
        type=Object,
        poll=_mesh_object_poll,
    )
    production_material: PointerProperty(
        name="Production Material",
        type=Material,
    )
    target_uv: StringProperty(name="Target UV", default="")
    base_color_node: StringProperty(name="Base Color Node", default="")
    normal_map_node: StringProperty(name="Normal Map Node", default="")

    forward_axis: EnumProperty(
        name="Forward Axis",
        description="Outward direction of the character's front",
        items=AXIS_ITEMS,
        default="+Y",
    )
    up_axis: EnumProperty(
        name="Up Axis",
        items=AXIS_ITEMS,
        default="+Z",
    )

    front: PointerProperty(type=SBFViewSettings)
    back: PointerProperty(type=SBFViewSettings)
    left: PointerProperty(type=SBFViewSettings)
    right: PointerProperty(type=SBFViewSettings)

    framing_ratio: FloatProperty(
        name="Framing Ratio",
        description="Fraction of the square projection frame occupied by the character",
        default=0.90,
        min=0.25,
        max=1.25,
    )
    show_projection_cameras: BoolProperty(
        name="Show Projection Cameras",
        default=False,
    )

    directional_exponent: FloatProperty(
        name="Directional Exponent",
        default=4.0,
        min=0.25,
        max=16.0,
    )
    minimum_weight: FloatProperty(
        name="Minimum Weight",
        default=0.001,
        min=0.0,
        max=0.1,
        precision=4,
    )
    lower_front_back_bias: FloatProperty(
        name="Lower Front/Back",
        default=3.0,
        min=0.0,
        max=100.0,
    )
    upper_front_back_bias: FloatProperty(
        name="Upper Front/Back",
        default=10.0,
        min=0.0,
        max=100.0,
    )
    head_front_back_bias: FloatProperty(
        name="Head Front/Back",
        default=40.0,
        min=0.0,
        max=200.0,
    )
    side_bias: FloatProperty(
        name="Side Bias",
        default=1.0,
        min=0.0,
        max=20.0,
    )
    upper_threshold: FloatProperty(
        name="Upper Threshold",
        default=0.58,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    head_threshold: FloatProperty(
        name="Head Threshold",
        default=0.75,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    top_surface_coverage: FloatProperty(
        name="Top Coverage",
        default=0.90,
        min=0.0,
        max=2.0,
    )
    fallback_threshold: FloatProperty(
        name="Fallback Threshold",
        default=0.01,
        min=0.0,
        max=1.0,
        precision=3,
    )

    occlusion_protection: BoolProperty(
        name="Occlusion Protection",
        description="Reject source views when the target point is not the first surface hit",
        default=True,
    )
    visibility_method: EnumProperty(
        name="Visibility Method",
        items=(
            (
                "RAY_CAST",
                "Ray Cast",
                "Check first-surface visibility at polygon centers and vertices",
            ),
        ),
        default="RAY_CAST",
    )
    visibility_samples: EnumProperty(
        name="Visibility Samples",
        items=(
            ("VERTEX", "Vertices", "Check loop vertices"),
            (
                "CENTER_VERTEX",
                "Centers + Vertices",
                "Conservatively require polygon center and vertex visibility",
            ),
        ),
        default="CENTER_VERTEX",
    )
    depth_tolerance_factor: FloatProperty(
        name="Depth Tolerance",
        description="First-hit tolerance relative to character height",
        default=0.003,
        min=0.00001,
        max=0.05,
        precision=5,
    )
    occlusion_feather: FloatProperty(
        name="Occlusion Feather",
        description="Soft transition beyond the strict depth tolerance",
        default=0.25,
        min=0.0,
        max=4.0,
    )

    texture_size: EnumProperty(
        name="Texture Size",
        items=(
            ("1024", "1024", "1024 x 1024"),
            ("2048", "2048", "2048 x 2048"),
            ("4096", "4096", "4096 x 4096"),
            ("8192", "8192", "8192 x 8192"),
        ),
        default="4096",
    )
    bake_margin: IntProperty(name="Bake Margin", default=24, min=0, max=256)
    roughness: FloatProperty(
        name="Roughness",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype="FACTOR",
    )
    normal_strength: FloatProperty(
        name="Normal Strength",
        default=0.25,
        min=0.0,
        max=5.0,
    )
    smooth_shading: BoolProperty(name="Smooth Shading", default=True)
    pack_baked_image: BoolProperty(name="Pack Baked Image", default=True)
    output_image_path: StringProperty(
        name="Base Color Path",
        subtype="FILE_PATH",
        default="//sbf_output/rebuilt_base_color.png",
    )
    save_blend_path: StringProperty(
        name="New Blender File",
        subtype="FILE_PATH",
        default="//sbf_output/character_sbf.blend",
    )
    export_glb_path: StringProperty(
        name="New GLB",
        subtype="FILE_PATH",
        default="//sbf_output/character_sbf.glb",
    )
    proof_render_dir: StringProperty(
        name="Proof Render Folder",
        subtype="DIR_PATH",
        default="//sbf_output/proof_renders/",
    )
    proof_resolution: IntProperty(
        name="Proof Resolution",
        default=1024,
        min=128,
        max=4096,
    )
    write_manifest: BoolProperty(name="Write Processing Manifest", default=True)
    allow_source_overwrite: BoolProperty(
        name="Allow Source Overwrite",
        description="Permit output paths to replace the currently open Blender file",
        default=False,
    )
    last_baked_image: PointerProperty(name="Last Baked Image", type=Image)
    status_message: StringProperty(name="Status", default="Ready")


PROPERTY_CLASSES = (SBFViewSettings, SBFSettings)


def register():
    for cls in PROPERTY_CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.sbf_settings = PointerProperty(type=SBFSettings)


def unregister():
    if hasattr(bpy.types.Scene, "sbf_settings"):
        del bpy.types.Scene.sbf_settings
    for cls in reversed(PROPERTY_CLASSES):
        bpy.utils.unregister_class(cls)
