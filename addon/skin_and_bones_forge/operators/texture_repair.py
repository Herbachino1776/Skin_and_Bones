"""Texture Repair Studio operators and viewport interaction."""

from __future__ import annotations

import json
import math

import bpy
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator
from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..baking.repair_service import (
    apply_repair_strokes,
    clear_repair_preview,
    clear_repairs,
    clone_source,
    commit_final_base_color,
    detect_color_seams,
    ensure_repair_compatible,
    heal_seams,
    set_clone_source,
    show_repair_preview,
    smart_fill,
    surface_sample_from_hit,
)
from ..projection import view_directions, world_bounds
from ..validation import ValidationError, validate_target
from ..variants.runtime import (
    mark_active_variant_dirty,
    sync_variant_from_settings,
)


def _settings(context):
    return context.scene.sbf_settings


def _fail(operator, settings, exc):
    message = str(exc)
    settings.repair_state = "FAILED" if settings.repair_state != "READY" else "READY"
    settings.repair_status = f"Error: {message}"
    settings.status_message = f"Texture Repair: {message}"
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


def _variant_changed(settings, reason):
    mark_active_variant_dirty(settings, reason)
    sync_variant_from_settings(settings)


def _require_repair(context):
    settings = _settings(context)
    info = validate_target(context, settings)
    if settings.repair_state != "READY":
        raise RuntimeError(
            "Bake a base-color texture before using Texture Repair Studio."
        )
    ensure_repair_compatible(info, settings)
    return info, settings


def _viewport_sample(context, event, info):
    if context.region is None or context.region_data is None:
        raise RuntimeError("Run surface repair from a 3D Viewport.")
    coordinate = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(
        context.region, context.region_data, coordinate
    )
    direction = view3d_utils.region_2d_to_vector_3d(
        context.region, context.region_data, coordinate
    )
    hit, location, _normal, polygon, hit_object, _matrix = context.scene.ray_cast(
        context.evaluated_depsgraph_get(), origin, direction
    )
    if not hit or hit_object is None:
        return None
    original = getattr(hit_object, "original", hit_object)
    if original != info.obj and hit_object != info.obj:
        return None
    uv_name = info.obj.get("sbf_repair_uv", "")
    return surface_sample_from_hit(info.obj, polygon, location, uv_name)


def _mirrored_sample(context, info, settings, sample):
    directions = view_directions(settings)
    bounds = world_bounds(info.obj, directions)
    lateral = directions["right"].normalized()
    point = Vector(sample["world"])
    mirrored_world = point - lateral * (2.0 * (point - bounds["center"]).dot(lateral))
    local = info.obj.matrix_world.inverted() @ mirrored_world
    tree = BVHTree.FromPolygons(
        [vertex.co for vertex in info.mesh.vertices],
        [tuple(polygon.vertices) for polygon in info.mesh.polygons],
        all_triangles=False,
    )
    nearest, _normal, polygon, _distance = tree.find_nearest(local)
    if nearest is None or polygon is None:
        return None
    world = info.obj.matrix_world @ nearest
    return surface_sample_from_hit(
        info.obj, polygon, world, info.obj.get("sbf_repair_uv", "")
    )


class SBF_OT_texture_repair_set_source(Operator):
    bl_idname = "sbf.texture_repair_set_source"
    bl_label = "Set Texture Repair Source"
    bl_description = "Click a mesh point to anchor Clone/Heal in surface tangent space"
    bl_options = {"REGISTER"}

    def invoke(self, context, _event):
        try:
            _require_repair(context)
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)
        if context.area is None or context.area.type != "VIEW_3D":
            return _fail(self, _settings(context), "Run SET SOURCE in a 3D Viewport.")
        context.window.cursor_modal_set("EYEDROPPER")
        context.window_manager.modal_handler_add(self)
        _settings(context).repair_status = "Click the source surface; Esc cancels."
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        settings = _settings(context)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.window.cursor_modal_restore()
            settings.repair_status = (
                "Source selection cancelled; previous source preserved."
            )
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            try:
                info, settings = _require_repair(context)
                sample = _viewport_sample(context, event, info)
                if sample is None:
                    raise RuntimeError("Click directly on the active target mesh.")
                set_clone_source(settings, sample)
                _variant_changed(settings, "Texture repair source changed")
                context.window.cursor_modal_restore()
                self.report({"INFO"}, settings.repair_source_status)
                return {"FINISHED"}
            except (ValidationError, RuntimeError, ValueError) as exc:
                context.window.cursor_modal_restore()
                return _fail(self, settings, exc)
        return {"RUNNING_MODAL"}


class SBF_OT_texture_repair_paint(Operator):
    bl_idname = "sbf.texture_repair_paint"
    bl_label = "Apply / Paint Texture Repair"
    bl_description = "Paint an incremental surface-aware Clone or Heal stroke"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    _samples = None
    _painting = False
    _last_mouse = None
    _info = None

    def invoke(self, context, _event):
        settings = _settings(context)
        try:
            self._info, settings = _require_repair(context)
            if settings.repair_mode not in {"CLONE", "HEAL"}:
                raise RuntimeError("Choose Clone or Heal for viewport painting.")
            clone_source(settings)
        except (
            ValidationError,
            RuntimeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            return _fail(self, settings, exc)
        if context.area is None or context.area.type != "VIEW_3D":
            return _fail(
                self,
                settings,
                "Run APPLY / PAINT REPAIR in a 3D Viewport.",
            )
        self._samples = []
        self._painting = False
        self._last_mouse = None
        context.window.cursor_modal_set("PAINT_BRUSH")
        context.window_manager.modal_handler_add(self)
        settings.repair_status = (
            "Drag on the target surface; Esc cancels without changes."
        )
        return {"RUNNING_MODAL"}

    def _append_sample(self, context, event, info, settings):
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        minimum = max(2.0, settings.repair_spacing * 20.0)
        if (
            self._last_mouse is not None
            and (mouse - self._last_mouse).length < minimum
        ):
            return
        sample = _viewport_sample(context, event, info)
        if sample is None:
            return
        self._samples.append(sample)
        if settings.repair_symmetry:
            mirrored = _mirrored_sample(context, info, settings, sample)
            if (
                mirrored is not None
                and math.dist(mirrored["world"], sample["world"]) > 1.0e-5
            ):
                self._samples.append(mirrored)
        self._last_mouse = mouse

    def modal(self, context, event):
        settings = _settings(context)
        if event.type in {"ESC", "RIGHTMOUSE"}:
            context.window.cursor_modal_restore()
            settings.repair_status = (
                "Stroke cancelled; correction layer was not changed."
            )
            return {"CANCELLED"}
        try:
            info = self._info
            if info is None or info.obj.name not in context.view_layer.objects:
                raise RuntimeError(
                    "The active repair target changed during the stroke."
                )
            if event.type == "LEFTMOUSE" and event.value == "PRESS":
                self._painting = True
                self._append_sample(context, event, info, settings)
                return {"RUNNING_MODAL"}
            if event.type == "MOUSEMOVE" and self._painting:
                self._append_sample(context, event, info, settings)
                return {"RUNNING_MODAL"}
            if (
                event.type == "LEFTMOUSE"
                and event.value == "RELEASE"
                and self._painting
            ):
                self._painting = False
                if not self._samples:
                    raise RuntimeError("The stroke did not hit the active target mesh.")
                result = apply_repair_strokes(
                    info, settings, clone_source(settings), self._samples
                )
                _variant_changed(settings, "Texture repair stroke applied")
                context.window.cursor_modal_restore()
                self.report(
                    {"INFO"},
                    f"Changed {result['changed']:,} repair pixels.",
                )
                return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            context.window.cursor_modal_restore()
            return _fail(self, settings, exc)
        return {"RUNNING_MODAL"}


class SBF_OT_texture_smart_fill(Operator):
    bl_idname = "sbf.texture_smart_fill"
    bl_label = "Smart Fill Repair Mask"
    bl_description = "Deterministically synthesize only the configured explicit mask"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            metrics = smart_fill(info, settings)
            _variant_changed(settings, "Texture smart fill changed the appearance")
            self.report(
                {"INFO"},
                f"Filled {metrics['filled']:,}; unresolved {metrics['unresolved']:,}.",
            )
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)


class SBF_OT_texture_detect_seams(Operator):
    bl_idname = "sbf.texture_detect_seams"
    bl_label = "Detect Color Seams"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            detect_color_seams(info, settings)
            _variant_changed(settings, "Texture seam diagnostics changed")
            self.report({"INFO"}, settings.repair_status)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)


class SBF_OT_texture_heal_seams(Operator):
    bl_idname = "sbf.texture_heal_seams"
    bl_label = "Heal Texture Seams"
    bl_options = {"REGISTER", "UNDO"}

    all_safe: BoolProperty(name="Heal All Safe", default=False)

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            heal_seams(info, settings, all_safe=self.all_safe)
            _variant_changed(settings, "Texture seams were repaired")
            self.report({"INFO"}, settings.repair_status)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)


class SBF_OT_texture_clear(Operator):
    bl_idname = "sbf.texture_clear"
    bl_label = "Clear Texture Repairs"
    bl_options = {"REGISTER", "UNDO"}

    selected: BoolProperty(name="Selected Faces Only", default=False)

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            clear_repairs(info, settings, selected=self.selected)
            _variant_changed(settings, "Texture repairs were cleared")
            self.report({"INFO"}, settings.repair_status)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)


class SBF_OT_texture_commit_final(Operator):
    bl_idname = "sbf.texture_commit_final"
    bl_label = "Save Blender Paint + Commit"
    bl_description = (
        "Capture native Blender paint on SBF_BaseColor_Final, then save, "
        "pack, and bind the production texture"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            _image, path, metrics = commit_final_base_color(info, settings)
            _variant_changed(settings, "Final base color was committed")
            settings.status_message = f"Committed final base color: {path}"
            self.report(
                {"INFO"},
                f"Saved {metrics['captured_blender_paint']:,} Blender-painted "
                f"pixels; committed {metrics['correction_pixels']:,} corrections "
                f"to {path}.",
            )
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, OSError) as exc:
            return _fail(self, _settings(context), exc)


class SBF_OT_texture_display(Operator):
    bl_idname = "sbf.texture_display"
    bl_label = "Texture Repair Inspection"
    bl_options = {"REGISTER"}

    display: EnumProperty(
        items=(
            ("FINAL", "After", "Final composite"),
            ("BEFORE", "Before", "Original bake"),
            ("UNRESOLVED", "Unresolved", "Unresolved overlay"),
            ("SEAM_HEATMAP", "Seam Heatmap", "Color seam heatmap"),
            ("CORRECTION_MASK", "Correction Mask", "Correction mask"),
            ("CLASSIFICATION", "Classification", "Source classification"),
            (
                "SOURCE_CONTAMINATION",
                "Source Contamination",
                "Source Doctor low-confidence overlay",
            ),
            ("TARGET_MASK", "Target Mask", "Artist Smart Fill target mask"),
            ("DONOR_MASK", "Donor Mask", "Artist safe donor mask"),
            ("FORBIDDEN_MASK", "Forbidden Mask", "Forbidden donor mask"),
            ("UNLIT_FINAL", "Unlit Final", "Unlit final base color"),
        )
    )

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            settings.repair_display = self.display
            show_repair_preview(context, info, settings)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)


class SBF_OT_texture_clear_preview(Operator):
    bl_idname = "sbf.texture_clear_preview"
    bl_label = "Clear Repair Preview"
    bl_description = "Restore the production material without deleting corrections"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            info, settings = _require_repair(context)
            clear_repair_preview(info)
            settings.repair_display = "FINAL"
            info.base_color_node.image = settings.repair_final_image
            settings.repair_status = (
                "Repair diagnostic preview cleared; corrections preserved."
            )
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, _settings(context), exc)


TEXTURE_REPAIR_OPERATOR_CLASSES = (
    SBF_OT_texture_repair_set_source,
    SBF_OT_texture_repair_paint,
    SBF_OT_texture_smart_fill,
    SBF_OT_texture_detect_seams,
    SBF_OT_texture_heal_seams,
    SBF_OT_texture_clear,
    SBF_OT_texture_commit_final,
    SBF_OT_texture_display,
    SBF_OT_texture_clear_preview,
)


__all__ = ("TEXTURE_REPAIR_OPERATOR_CLASSES",)
