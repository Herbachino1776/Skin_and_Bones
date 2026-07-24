"""User-facing workflow operators."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from ..baking import bake_final_texture
from ..constants import PROCESSING_PRESET
from ..export import export_glb, render_verification_set, save_blend_copy
from ..projection import (
    cleanup_temporary_data,
    create_preview_material,
    create_projection_state,
)
from ..validation import ValidationError, validate_target


def _settings(context):
    return context.scene.sbf_settings


def _target_for_cleanup(context, settings):
    if settings.target_object is not None:
        return settings.target_object
    active = context.view_layer.objects.active
    return active if active is not None and active.type == "MESH" else None


def _fail(operator, settings, exc):
    message = str(exc)
    settings.status_message = f"Error: {message}"
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


class SBF_OT_load_view_image(Operator):
    bl_idname = "sbf.load_view_image"
    bl_label = "Open Projection Image"
    bl_description = "Load a projection image from disk into this source view"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(
        name="View",
        items=(
            ("front", "Front", "Front projection"),
            ("back", "Back", "Back projection"),
            ("left", "Character Left", "Character-left projection"),
            ("right", "Character Right", "Character-right projection"),
        ),
    )
    filepath: StringProperty(name="Image File", subtype="FILE_PATH")
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tif;*.tiff;*.bmp;*.tga;*.exr;*.webp",
        options={"HIDDEN"},
    )

    def invoke(self, context, _event):
        view = getattr(_settings(context), self.view_name)
        if view.image is not None and view.image.filepath:
            self.filepath = bpy.path.abspath(view.image.filepath)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = _settings(context)
        path = Path(bpy.path.abspath(self.filepath)).resolve()
        if not path.is_file():
            return _fail(self, settings, f"Image file does not exist: {path}")
        try:
            image = bpy.data.images.load(str(path), check_existing=True)
            image.colorspace_settings.name = "sRGB"
            image.alpha_mode = "STRAIGHT"
            getattr(settings, self.view_name).image = image
        except (RuntimeError, TypeError, ValueError) as exc:
            return _fail(self, settings, f"Could not load image: {exc}")

        label = self.view_name.replace("_", " ").title()
        settings.status_message = f"Loaded {label} image: {path.name}"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_load_preset(Operator):
    bl_idname = "sbf.load_preset"
    bl_label = "Load SPAR3D Preset"
    bl_description = PROCESSING_PRESET
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        settings.forward_axis = "+Y"
        settings.up_axis = "+Z"
        settings.framing_ratio = 0.90
        settings.directional_exponent = 4.0
        settings.minimum_weight = 0.001
        settings.lower_front_back_bias = 3.0
        settings.upper_front_back_bias = 10.0
        settings.head_front_back_bias = 40.0
        settings.side_bias = 1.0
        settings.upper_threshold = 0.58
        settings.head_threshold = 0.75
        settings.top_surface_coverage = 0.90
        settings.fallback_threshold = 0.01
        settings.occlusion_protection = True
        settings.visibility_method = "RAY_CAST"
        settings.visibility_samples = "CENTER_VERTEX"
        settings.depth_tolerance_factor = 0.003
        settings.occlusion_feather = 0.25
        settings.texture_size = "4096"
        settings.bake_margin = 24
        settings.roughness = 1.0
        settings.normal_strength = 0.25
        settings.smooth_shading = True
        for name in ("front", "back", "left", "right"):
            view = getattr(settings, name)
            view.enabled = True
            view.flip_x = False
            view.flip_y = False
            view.scale = 1.0
            view.offset_x = 0.0
            view.offset_y = 0.0
            view.alpha_threshold = 0.01
            view.weight = 1.0
            view.occlusion = True
        settings.status_message = f"Loaded: {PROCESSING_PRESET}"
        return {"FINISHED"}


class SBF_OT_validate(Operator):
    bl_idname = "sbf.validate"
    bl_label = "Validate Character"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            info = validate_target(context, settings)
            summary = (
                f"Valid: {info.obj.name}, {len(info.mesh.vertices):,} vertices, "
                f"UV '{info.uv_name}', material '{info.material.name}'"
            )
            if info.warnings:
                summary += " — " + " ".join(info.warnings)
                self.report({"WARNING"}, summary)
            else:
                self.report({"INFO"}, summary)
            settings.status_message = summary
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


def _execute_preview(operator, context):
    settings = _settings(context)
    target = _target_for_cleanup(context, settings)
    cleanup_temporary_data(context, target, settings.production_material)
    try:
        info = validate_target(context, settings, require_sources=True)
        create_projection_state(context, info, settings)
        create_preview_material(info, settings)
        settings.status_message = (
            "Projection preview ready. Inspect the material, adjust settings, "
            "then Refresh Preview or Bake Final Texture."
        )
        operator.report({"INFO"}, settings.status_message)
        return {"FINISHED"}
    except (ValidationError, RuntimeError, ValueError) as exc:
        cleanup_temporary_data(context, target, settings.production_material)
        return _fail(operator, settings, exc)


class SBF_OT_preview(Operator):
    bl_idname = "sbf.create_preview"
    bl_label = "Create Projection Preview"
    bl_description = "Fit cameras, build projection UVs and occlusion-safe weights"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _execute_preview(self, context)


class SBF_OT_refresh_preview(Operator):
    bl_idname = "sbf.refresh_preview"
    bl_label = "Refresh Preview"
    bl_description = "Rebuild projection UVs and weights from the current settings"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _execute_preview(self, context)


class SBF_OT_bake(Operator):
    bl_idname = "sbf.bake_final"
    bl_label = "Bake Final Texture"
    bl_description = "Bake the projection preview to the original production UV map"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            info = validate_target(context, settings, require_sources=True)
            image, path = bake_final_texture(context, info, settings)
            settings.status_message = (
                f"Baked {image.size[0]} x {image.size[1]} base color: {path}"
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_cleanup(Operator):
    bl_idname = "sbf.cleanup"
    bl_label = "Clean Temporary Data"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        target = _target_for_cleanup(context, settings)
        cleanup_temporary_data(context, target, settings.production_material)
        settings.status_message = "Temporary cameras, UVs, weights, and materials removed."
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_save_copy(Operator):
    bl_idname = "sbf.save_copy"
    bl_label = "Save New Base Asset"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            info = validate_target(context, settings)
            if not info.obj.get("sbf_processed", False):
                raise RuntimeError("Bake a final texture before saving the base asset.")
            path, _manifest = save_blend_copy(context, info, settings)
            settings.status_message = f"Saved clean Blender copy: {path}"
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, OSError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_export_glb(Operator):
    bl_idname = "sbf.export_glb"
    bl_label = "Export New GLB"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            info = validate_target(context, settings)
            if not info.obj.get("sbf_processed", False):
                raise RuntimeError("Bake a final texture before exporting the GLB.")
            path, _manifest = export_glb(context, info, settings)
            settings.status_message = f"Exported clean GLB: {path}"
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, OSError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_render_verification(Operator):
    bl_idname = "sbf.render_verification"
    bl_label = "Render Verification Set"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            info = validate_target(context, settings)
            paths = render_verification_set(context, info, settings)
            settings.status_message = f"Rendered {len(paths)} verification images."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, OSError) as exc:
            return _fail(self, settings, exc)


OPERATOR_CLASSES = (
    SBF_OT_load_view_image,
    SBF_OT_load_preset,
    SBF_OT_validate,
    SBF_OT_preview,
    SBF_OT_refresh_preview,
    SBF_OT_bake,
    SBF_OT_cleanup,
    SBF_OT_save_copy,
    SBF_OT_export_glb,
    SBF_OT_render_verification,
)
