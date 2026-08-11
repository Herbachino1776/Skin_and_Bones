"""User-facing workflow operators."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator

from ..baking import bake_final_texture
from ..constants import (
    CARDINAL_VIEW_NAMES,
    DEFAULT_PROJECTION_PACKS_DIR,
    PROCESSING_PRESET,
    VIEW_LABELS,
    VIEW_NAMES,
)
from ..export import export_glb, render_verification_set, save_blend_copy
from ..projection import (
    cleanup_temporary_data,
    create_preview_material,
    create_projection_state,
)
from ..projection.alignment import auto_fit_loaded_images
from ..projection.source_files import find_cardinal_view_images
from ..projection.source_processing import (
    auto_initialize_body_landmarks,
    cleanup_warped_sources,
    generate_warped_sources,
    process_all_source_plates,
)
from ..validation import ValidationError, validate_target


VIEW_PICKER_ITEMS = tuple(
    (name, VIEW_LABELS[name], f"{VIEW_LABELS[name]} projection")
    for name in VIEW_NAMES
)


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


def _apply_spar3d_preset(settings):
    """Apply the exact settings used by the visual acceptance harness."""

    settings.forward_axis = "+Y"
    settings.up_axis = "+Z"
    settings.framing_ratio = 0.90
    settings.directional_exponent = 4.0
    settings.minimum_weight = 0.001
    settings.lower_front_back_bias = 3.0
    settings.upper_front_back_bias = 10.0
    # Keep the identity-bearing front/back plates authoritative across the
    # broad facial hemisphere.  A near-side-equivalent value lets cheek
    # normals alternate between front, profile, and diagonal plates, which
    # appears as repeated vertical facial bands on the baked texture.
    settings.head_front_back_bias = 10.0
    settings.head_identity_lock = True
    settings.head_blend_sharpness = 3.0
    settings.source_edge_padding = 0.05
    settings.head_lock_transition = 0.025
    settings.side_bias = 1.0
    settings.upper_threshold = 0.58
    settings.head_threshold = 0.80
    settings.top_surface_coverage = 0.90
    settings.fallback_threshold = 0.01
    settings.occlusion_protection = True
    settings.visibility_method = "RAY_CAST"
    settings.visibility_samples = "CENTER_VERTEX"
    settings.depth_tolerance_factor = 0.003
    settings.occlusion_feather = 0.25
    settings.live_preview = True
    settings.auto_fit_source_images = True
    settings.texture_size = "4096"
    settings.bake_margin = 24
    settings.generate_bake_uv = True
    settings.roughness = 1.0
    settings.normal_strength = 0.25
    settings.smooth_shading = True
    for name in VIEW_NAMES:
        view = getattr(settings, name)
        view.enabled = name in CARDINAL_VIEW_NAMES or view.image is not None
        view.flip_x = False
        view.flip_y = False
        view.scale = 1.0
        view.horizontal_scale = 1.0
        view.offset_x = 0.0
        view.offset_y = 0.0
        view.head_scale = 1.0
        view.head_horizontal_scale = 1.0
        view.head_offset_x = 0.0
        view.head_offset_y = 0.0
        view.auto_head_scale = 1.0
        view.auto_head_horizontal_scale = 1.0
        view.auto_head_offset_x = 0.0
        view.auto_head_offset_y = 0.0
        view.alpha_threshold = 0.01
        view.key_black_background = False
        view.black_key_threshold = 0.01
        view.weight = 1.0
        view.occlusion = True
    return auto_fit_loaded_images(settings)


class SBF_OT_load_view_image(Operator):
    bl_idname = "sbf.load_view_image"
    bl_label = "Open Projection Image"
    bl_description = "Load a projection image from disk into this source view"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(
        name="View",
        items=VIEW_PICKER_ITEMS,
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
            view = getattr(settings, self.view_name)
            if view.image != image:
                view.facial_landmarks_set = (False, False, False, False)
                view.facial_landmarks_skipped = (
                    False,
                    False,
                    False,
                    False,
                )
                view.facial_calibration_valid = False
                view.landmark_image_name = ""
            view.enabled = True
            view.image = image
        except (RuntimeError, TypeError, ValueError) as exc:
            return _fail(self, settings, f"Could not load image: {exc}")

        label = self.view_name.replace("_", " ").title()
        settings.status_message = f"Loaded {label} image: {path.name}"
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_load_perspective_folder(Operator):
    bl_idname = "sbf.load_perspective_folder"
    bl_label = "Select Character Perspective Folder"
    bl_description = (
        "Load front, back, character-left, and character-right images from "
        "their filename keys"
    )
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(name="Perspective Folder", subtype="DIR_PATH")
    filter_folder: BoolProperty(default=True, options={"HIDDEN"})

    def invoke(self, context, _event):
        root = Path(DEFAULT_PROJECTION_PACKS_DIR)
        self.directory = str(root.resolve() if root.is_dir() else root)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        settings = _settings(context)
        folder = Path(bpy.path.abspath(self.directory)).resolve()
        try:
            paths = find_cardinal_view_images(folder)
        except (OSError, ValueError) as exc:
            return _fail(self, settings, exc)

        images_before = set(bpy.data.images)
        loaded = {}
        try:
            for name in CARDINAL_VIEW_NAMES:
                image = bpy.data.images.load(str(paths[name]), check_existing=True)
                image.colorspace_settings.name = "sRGB"
                image.alpha_mode = "STRAIGHT"
                loaded[name] = image
        except (RuntimeError, TypeError, ValueError) as exc:
            for image in [item for item in bpy.data.images if item not in images_before]:
                if image.users == 0:
                    bpy.data.images.remove(image)
            return _fail(self, settings, f"Could not load perspective folder: {exc}")

        for name in CARDINAL_VIEW_NAMES:
            view = getattr(settings, name)
            image = loaded[name]
            if view.image != image:
                view.facial_landmarks_set = (False, False, False, False)
                view.facial_landmarks_skipped = (False, False, False, False)
                view.facial_calibration_valid = False
                view.landmark_image_name = ""
            view.enabled = True
            view.image = image

        settings.status_message = (
            f"Loaded 4 perspective images from: {folder.name}"
        )
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_load_preset(Operator):
    bl_idname = "sbf.load_preset"
    bl_label = "Load SPAR3D Preset"
    bl_description = PROCESSING_PRESET
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        _apply_spar3d_preset(settings)
        settings.status_message = (
            f"Loaded: {PROCESSING_PRESET}. Four cardinal views are supported; "
            "45 deg views are optional."
        )
        return {"FINISHED"}


class SBF_OT_auto_fit_sources(Operator):
    bl_idname = "sbf.auto_fit_sources"
    bl_label = "Auto-Fit Source Images"
    bl_description = (
        "Center and scale loaded sources from their visible alpha silhouettes"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            results = auto_fit_loaded_images(settings)
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)
        if not results:
            return _fail(self, settings, "No enabled source images are loaded.")
        summary = ", ".join(
            f"{result['name']} x={result['offset_x']:+.3f}"
            for result in results
        )
        settings.status_message = f"Auto-fit {len(results)} sources: {summary}"
        self.report({"INFO"}, settings.status_message)
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
        process_all_source_plates(settings)
        missing_landmarks = any(
            getattr(settings, name).enabled
            and getattr(settings, name).image is not None
            and not getattr(settings, name).body_landmarks_valid
            for name in VIEW_NAMES
        )
        if missing_landmarks:
            auto_initialize_body_landmarks(settings, context=context)
        generate_warped_sources(context, settings)
        create_projection_state(context, info, settings)
        create_preview_material(info, settings)
        settings.status_message = (
            "Production preview ready from cleaned, pose-aligned, body-guarded "
            "sources. Refresh after changing alignment or occlusion settings."
        )
        operator.report({"INFO"}, settings.status_message)
        return {"FINISHED"}
    except (ValidationError, RuntimeError, ValueError) as exc:
        cleanup_temporary_data(context, target, settings.production_material)
        cleanup_warped_sources(settings)
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


class SBF_OT_best_preview(Operator):
    bl_idname = "sbf.best_preview"
    bl_label = "One-Click Best Preview"
    bl_description = (
        "Apply the tested SPAR3D preset, auto-fit every loaded source, "
        "reapply saved facial calibration, and build the projection preview"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            results = _apply_spar3d_preset(settings)
            if not results:
                return _fail(self, settings, "No enabled source images are loaded.")
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)
        return _execute_preview(self, context)


class SBF_OT_bake(Operator):
    bl_idname = "sbf.bake_final"
    bl_label = "Bake Final Texture"
    bl_description = (
        "Bake the projection preview to a clean base-color UV while preserving "
        "the original UV for normal and PBR maps"
    )
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
        cleanup_warped_sources(settings)
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
            if settings.appearance_family_id:
                raise RuntimeError(
                    "Use Appearance Variants > EXPORT ACTIVE so family identity "
                    "is included in the GLB."
                )
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
    SBF_OT_load_perspective_folder,
    SBF_OT_load_preset,
    SBF_OT_auto_fit_sources,
    SBF_OT_validate,
    SBF_OT_preview,
    SBF_OT_refresh_preview,
    SBF_OT_best_preview,
    SBF_OT_bake,
    SBF_OT_cleanup,
    SBF_OT_save_copy,
    SBF_OT_export_glb,
    SBF_OT_render_verification,
)
