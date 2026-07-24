"""3D Viewport sidebar interface."""

from __future__ import annotations

from bpy.types import Panel

from ..constants import VIEW_LABELS, VIEW_NAMES


def _draw_view(box, settings, name):
    view = getattr(settings, name)
    header = box.row(align=True)
    header.prop(view, "enabled", text="")
    header.label(text=VIEW_LABELS[name])
    header.prop(view, "occlusion", text="", icon="MOD_MASK")
    open_image = box.operator(
        "sbf.load_view_image",
        text="Open Image from Disk...",
        icon="FILE_FOLDER",
    )
    open_image.view_name = name
    box.prop(view, "image", text="Loaded")
    transforms = box.row(align=True)
    transforms.prop(view, "flip_x", text="Flip X")
    transforms.prop(view, "flip_y", text="Flip Y")
    box.prop(view, "scale")
    offsets = box.row(align=True)
    offsets.prop(view, "offset_x")
    offsets.prop(view, "offset_y")
    weights = box.row(align=True)
    weights.prop(view, "alpha_threshold")
    weights.prop(view, "weight")


class SBF_PT_main(Panel):
    bl_label = "Skin & Bones Forge"
    bl_idname = "SBF_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Skin & Bones Forge"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sbf_settings

        layout.operator("sbf.load_preset", icon="PRESET")

        target = layout.box()
        target.label(text="Target", icon="OUTLINER_OB_MESH")
        target.prop(settings, "target_object")
        target.prop(settings, "production_material")
        target.prop(settings, "target_uv")
        axes = target.row(align=True)
        axes.prop(settings, "forward_axis")
        axes.prop(settings, "up_axis")
        target.operator("sbf.validate", icon="CHECKMARK")

        sources = layout.box()
        sources.label(text="Source Views", icon="IMAGE_DATA")
        for name in VIEW_NAMES:
            view_box = sources.box()
            _draw_view(view_box, settings, name)

        fit = layout.box()
        fit.label(text="Fit & Preview", icon="VIEW_CAMERA")
        fit.prop(settings, "framing_ratio")
        fit.prop(settings, "show_projection_cameras")
        row = fit.row(align=True)
        row.operator("sbf.create_preview", icon="MATERIAL")
        row.operator("sbf.refresh_preview", icon="FILE_REFRESH")

        identity = layout.box()
        identity.label(text="Identity Blending", icon="MOD_VERTEX_WEIGHT")
        identity.prop(settings, "directional_exponent")
        identity.prop(settings, "minimum_weight")
        identity.prop(settings, "lower_front_back_bias")
        identity.prop(settings, "upper_front_back_bias")
        identity.prop(settings, "head_front_back_bias")
        identity.prop(settings, "side_bias")
        thresholds = identity.row(align=True)
        thresholds.prop(settings, "upper_threshold")
        thresholds.prop(settings, "head_threshold")
        identity.prop(settings, "top_surface_coverage")
        identity.prop(settings, "fallback_threshold")

        occlusion = layout.box()
        occlusion.label(text="Occlusion", icon="XRAY")
        occlusion.prop(settings, "occlusion_protection")
        column = occlusion.column()
        column.enabled = settings.occlusion_protection
        column.prop(settings, "visibility_method")
        column.prop(settings, "visibility_samples")
        column.prop(settings, "depth_tolerance_factor")
        column.prop(settings, "occlusion_feather")

        output = layout.box()
        output.label(text="Material Output", icon="TEXTURE")
        output.prop(settings, "texture_size")
        output.prop(settings, "bake_margin")
        output.prop(settings, "roughness")
        output.prop(settings, "normal_strength")
        output.prop(settings, "smooth_shading")
        output.prop(settings, "pack_baked_image")
        output.prop(settings, "output_image_path")
        output.operator("sbf.bake_final", icon="RENDER_STILL")

        delivery = layout.box()
        delivery.label(text="Delivery", icon="PACKAGE")
        delivery.prop(settings, "save_blend_path")
        delivery.operator("sbf.save_copy", icon="FILE_BLEND")
        delivery.prop(settings, "export_glb_path")
        delivery.operator("sbf.export_glb", icon="EXPORT")
        delivery.prop(settings, "proof_render_dir")
        delivery.prop(settings, "proof_resolution")
        delivery.operator("sbf.render_verification", icon="RENDERLAYERS")
        delivery.prop(settings, "write_manifest")
        delivery.prop(settings, "allow_source_overwrite")
        delivery.operator("sbf.cleanup", icon="TRASH")

        status = layout.box()
        status.label(text="Status")
        status.label(text=settings.status_message, icon="INFO")


PANEL_CLASSES = (SBF_PT_main,)
