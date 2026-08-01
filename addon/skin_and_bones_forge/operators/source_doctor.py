"""Source Plate Doctor and interactive body-landmark operators."""

from __future__ import annotations

import json
import math

import blf
import bpy
import gpu
from bpy.props import EnumProperty
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader

from ..constants import (
    SOURCE_DIAGNOSTIC_PREFIX,
    VIEW_LABELS,
    VIEW_NAMES,
)
from ..projection import cleanup_temporary_data
from ..projection.body_alignment import BODY_LANDMARK_LABELS, BODY_LANDMARK_NAMES
from ..projection.source_processing import (
    auto_initialize_body_landmarks,
    body_landmarks,
    generate_warped_sources,
    process_all_source_plates,
    process_source_plate,
    reset_body_landmarks,
    restore_original_source,
)


VIEW_ITEMS = tuple(
    (name, VIEW_LABELS[name], f"Process {VIEW_LABELS[name]}") for name in VIEW_NAMES
)


def _settings(context):
    return context.scene.sbf_settings


def _fail(operator, settings, exc):
    message = str(exc)
    settings.status_message = f"Source Doctor: {message}"
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


class SBF_OT_process_all_source_plates(Operator):
    bl_idname = "sbf.process_all_source_plates"
    bl_label = "PROCESS ALL SOURCE PLATES"
    bl_description = "Non-destructively clean every enabled projection source"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            results = process_all_source_plates(settings, force=True)
        except (RuntimeError, ValueError) as exc:
            settings.source_doctor_state = "FAILED"
            return _fail(self, settings, exc)
        before = sum(item["contamination_before"] for item in results.values())
        after = sum(item["contamination_after"] for item in results.values())
        settings.source_alignment_status = (
            f"Cleaned {len(results)} plates; edge contamination {before:.4f} -> {after:.4f}."
        )
        settings.status_message = settings.source_alignment_status
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_process_source_plate(Operator):
    bl_idname = "sbf.process_source_plate"
    bl_label = "PROCESS SOURCE"
    bl_description = "Non-destructively clean this projection source"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)

    def execute(self, context):
        settings = _settings(context)
        try:
            image, metrics, _changed = process_source_plate(
                settings, self.view_name, force=True
            )
        except (RuntimeError, ValueError) as exc:
            settings.source_doctor_state = "FAILED"
            return _fail(self, settings, exc)
        settings.status_message = (
            f"{VIEW_LABELS[self.view_name]} cleaned as {image.name}; contamination "
            f"{metrics['contamination_before']:.4f} -> {metrics['contamination_after']:.4f}."
        )
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_auto_body_landmarks(Operator):
    bl_idname = "sbf.auto_body_landmarks"
    bl_label = "AUTO INITIALIZE BODY LANDMARKS"
    bl_description = "Initialize per-view anatomical image landmarks from each silhouette"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            names = auto_initialize_body_landmarks(settings, context=context)
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)
        settings.status_message = f"Initialized body landmarks for {len(names)} source views."
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_reset_body_landmarks(Operator):
    bl_idname = "sbf.reset_body_landmarks"
    bl_label = "RESET BODY LANDMARKS"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)

    def execute(self, context):
        settings = _settings(context)
        reset_body_landmarks(settings, self.view_name)
        settings.status_message = f"Reset {VIEW_LABELS[self.view_name]} body landmarks."
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_generate_warped_sources(Operator):
    bl_idname = "sbf.generate_warped_sources"
    bl_label = "GENERATE WARPED SOURCES"
    bl_description = (
        "Run pose preflight and create GPU-safe bounded body-part warp atlases"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            results = generate_warped_sources(context, settings)
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)
        moderate = sum(item["status"] == "MODERATE" for item in results.values())
        settings.status_message = (
            f"Generated {len(results)} atlases with seven bounded body-part "
            "regions each; "
            f"{moderate} views required moderate pose correction."
        )
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


class SBF_OT_show_source_doctor_image(Operator):
    bl_idname = "sbf.show_source_doctor_image"
    bl_label = "SHOW CLEANED SOURCE"
    bl_options = {"REGISTER"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)
    image_kind: EnumProperty(
        name="Diagnostic",
        items=(
            ("CLEANED", "Cleaned Source", "Show the cleaned owned image"),
            ("CONTAMINATION", "Edge Contamination", "Show detected edge contamination in red"),
            ("ORIGINAL", "Original", "Show the untouched original source"),
        ),
        default="CLEANED",
    )

    def execute(self, context):
        settings = _settings(context)
        view = getattr(settings, self.view_name)
        if self.image_kind == "CLEANED":
            image = view.cleaned_image
        elif self.image_kind == "CONTAMINATION":
            image = bpy.data.images.get(
                f"{SOURCE_DIAGNOSTIC_PREFIX}{self.view_name.upper()}"
            )
        else:
            image = view.image
        if image is None:
            return _fail(self, settings, "Process this source before opening its diagnostic.")
        if context.area is None:
            return _fail(self, settings, "An editor area is required to show the source.")
        context.area.type = "IMAGE_EDITOR"
        context.area.spaces.active.image = image
        settings.status_message = f"Showing {image.name}."
        return {"FINISHED"}


class SBF_OT_restore_original_source(Operator):
    bl_idname = "sbf.restore_original_source"
    bl_label = "RESTORE ORIGINAL SOURCE"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)

    def execute(self, context):
        settings = _settings(context)
        cleanup_temporary_data(
            context, settings.target_object, settings.production_material
        )
        restore_original_source(settings, self.view_name)
        settings.status_message = settings.source_alignment_status
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


def _window_region(area):
    return next((region for region in area.regions if region.type == "WINDOW"), None)


def _point_position(region, point):
    return region.view2d.view_to_region(point[0], point[1], clip=False)


def _draw_body_landmarks(operator):
    context = bpy.context
    area = context.area
    region = context.region
    if area is None or area != operator._area or region is None or region.type != "WINDOW":
        return
    positions = []
    labels = []
    for index, name in enumerate(BODY_LANDMARK_NAMES):
        if name not in operator._metadata["points"]:
            continue
        x, y = _point_position(region, operator._metadata["points"][name])
        positions.append((x, y))
        labels.append((x, y, index + 1))
    if positions:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "POINTS", {"pos": positions})
        gpu.state.blend_set("ALPHA")
        gpu.state.point_size_set(12.0)
        shader.bind()
        shader.uniform_float("color", (0.05, 0.75, 1.0, 1.0))
        batch.draw(shader)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set("NONE")
    font_id = 0
    blf.size(font_id, 12.0)
    blf.color(font_id, 0.05, 0.75, 1.0, 1.0)
    for x, y, number in labels:
        blf.position(font_id, x + 7.0, y + 5.0, 0.0)
        blf.draw(font_id, str(number))
    current = operator._next_unset()
    prompt = BODY_LANDMARK_LABELS[current] if current else "Click a cyan point to reposition"
    blf.size(font_id, 18.0)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, 24.0, 54.0, 0.0)
    blf.draw(font_id, f"Place: {prompt}")
    blf.size(font_id, 13.0)
    blf.position(font_id, 24.0, 30.0, 0.0)
    blf.draw(
        font_id,
        "LMB place/move | Wheel zoom | MMB pan | S skip hidden | "
        "Backspace undo | R reset | Enter accept | Esc cancel",
    )


class SBF_OT_place_body_landmarks(Operator):
    bl_idname = "sbf.place_body_landmarks"
    bl_label = "PLACE BODY LANDMARKS"
    bl_description = "Place pose-alignment metadata in the source Image Editor"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)

    _area = None
    _draw_handle = None
    _original_area_type = "VIEW_3D"
    _snapshot = None
    _metadata = None

    def _next_unset(self):
        skipped = set(self._metadata["skipped"])
        for name in BODY_LANDMARK_NAMES:
            if name not in self._metadata["points"] and name not in skipped:
                return name
        return None

    def _close(self, context):
        if self._draw_handle is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        if self._area is not None:
            self._area.header_text_set(None)
            self._area.type = self._original_area_type
            self._area.tag_redraw()
        context.window.cursor_modal_restore()

    def invoke(self, context, _event):
        settings = _settings(context)
        view = getattr(settings, self.view_name)
        if view.image is None:
            return _fail(self, settings, "Load an image for this source first.")
        if context.area is None:
            return _fail(self, settings, "Body landmark placement needs an editor area.")
        if view.body_landmarks_json:
            try:
                self._metadata = body_landmarks(view, self.view_name)
            except ValueError:
                self._metadata = {"points": {}, "skipped": []}
        else:
            self._metadata = {"points": {}, "skipped": []}
        self._metadata = json.loads(json.dumps(self._metadata))
        self._snapshot = view.body_landmarks_json
        self._area = context.area
        self._original_area_type = self._area.type
        self._area.type = "IMAGE_EDITOR"
        self._area.spaces.active.image = view.cleaned_image or view.image
        self._area.header_text_set(f"{VIEW_LABELS[self.view_name]} body landmarks")
        self._draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_body_landmarks, (self,), "WINDOW", "POST_PIXEL"
        )
        context.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        self._area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _nearest(self, region, mouse_x, mouse_y):
        nearest = None
        distance = math.inf
        for name, point in self._metadata["points"].items():
            x, y = _point_position(region, point)
            candidate = math.hypot(x - mouse_x, y - mouse_y)
            if candidate < distance:
                nearest, distance = name, candidate
        return nearest if distance <= 35.0 else None

    def _finish(self, context):
        settings = _settings(context)
        view = getattr(settings, self.view_name)
        if len(self._metadata["points"]) + len(self._metadata["skipped"]) != len(BODY_LANDMARK_NAMES):
            self.report({"WARNING"}, "Place or explicitly skip every body landmark.")
            return {"RUNNING_MODAL"}
        view.body_landmarks_json = json.dumps(
            self._metadata, sort_keys=True, separators=(",", ":")
        )
        view.body_landmarks_valid = True
        view.body_landmark_image_name = view.image.name
        view.warp_images_json = ""
        view.warp_fingerprint = ""
        settings.source_preview_ready = False
        settings.source_alignment_status = "Body landmarks changed; regenerate warped sources."
        settings.status_message = f"Saved {VIEW_LABELS[self.view_name]} body landmarks."
        self._close(context)
        return {"FINISHED"}

    def modal(self, context, event):
        view = getattr(_settings(context), self.view_name)
        if event.type == "ESC" and event.value == "PRESS":
            view.body_landmarks_json = self._snapshot
            self._close(context)
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._finish(context)
        if event.type == "R" and event.value == "PRESS":
            self._metadata = {"points": {}, "skipped": []}
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "BACK_SPACE" and event.value == "PRESS":
            completed = [
                name for name in BODY_LANDMARK_NAMES
                if name in self._metadata["points"] or name in self._metadata["skipped"]
            ]
            if completed:
                name = completed[-1]
                self._metadata["points"].pop(name, None)
                if name in self._metadata["skipped"]:
                    self._metadata["skipped"].remove(name)
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "S" and event.value == "PRESS":
            name = self._next_unset()
            if name:
                self._metadata["skipped"].append(name)
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            region = _window_region(self._area)
            if region is None:
                return {"RUNNING_MODAL"}
            mouse_x = event.mouse_x - region.x
            mouse_y = event.mouse_y - region.y
            x, y = region.view2d.region_to_view(mouse_x, mouse_y)
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                return {"RUNNING_MODAL"}
            name = self._next_unset() or self._nearest(region, mouse_x, mouse_y)
            if name:
                self._metadata["points"][name] = [x, y]
                if name in self._metadata["skipped"]:
                    self._metadata["skipped"].remove(name)
                self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type in {
            "MIDDLEMOUSE", "WHEELUPMOUSE", "WHEELDOWNMOUSE", "TRACKPADPAN", "TRACKPADZOOM"
        }:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._snapshot is not None:
            getattr(_settings(context), self.view_name).body_landmarks_json = self._snapshot
        self._close(context)


SOURCE_DOCTOR_OPERATOR_CLASSES = (
    SBF_OT_process_all_source_plates,
    SBF_OT_process_source_plate,
    SBF_OT_auto_body_landmarks,
    SBF_OT_reset_body_landmarks,
    SBF_OT_generate_warped_sources,
    SBF_OT_show_source_doctor_image,
    SBF_OT_restore_original_source,
    SBF_OT_place_body_landmarks,
)
