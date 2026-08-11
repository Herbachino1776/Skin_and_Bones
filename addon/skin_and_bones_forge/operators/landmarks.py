"""Interactive facial-landmark calibration in Blender's Image Editor."""

from __future__ import annotations

import math

import blf
import bpy
import gpu
from bpy.props import EnumProperty
from bpy.types import Operator
from gpu_extras.batch import batch_for_shader

from ..constants import (
    FACIAL_LANDMARK_LABELS,
    FACIAL_LANDMARK_NAMES,
    VIEW_LABELS,
    VIEW_NAMES,
)
from ..projection.alignment import (
    apply_face_calibration,
    facial_landmark_count,
    minimum_facial_landmarks,
)
from ..variants.runtime import mark_active_variant_dirty


VIEW_ITEMS = tuple(
    (name, VIEW_LABELS[name], f"Calibrate {VIEW_LABELS[name]}")
    for name in VIEW_NAMES
)


def _settings(context):
    return context.scene.sbf_settings


def _window_region(area):
    return next(
        (region for region in area.regions if region.type == "WINDOW"),
        None,
    )


def _point_position(region, point):
    return region.view2d.view_to_region(point[0], point[1], clip=False)


def _draw_landmarks(operator):
    context = bpy.context
    area = context.area
    region = context.region
    if (
        area is None
        or area != operator._area
        or region is None
        or region.type != "WINDOW"
    ):
        return

    view = getattr(_settings(context), operator.view_name)
    positions = []
    labels = []
    for index, name in enumerate(FACIAL_LANDMARK_NAMES):
        if not view.facial_landmarks_set[index]:
            continue
        x, y = _point_position(region, getattr(view, name))
        positions.append((x, y))
        labels.append((x, y, index + 1))

    if positions:
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "POINTS", {"pos": positions})
        gpu.state.blend_set("ALPHA")
        gpu.state.point_size_set(15.0)
        shader.bind()
        shader.uniform_float("color", (1.0, 0.03, 0.03, 1.0))
        batch.draw(shader)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set("NONE")

    font_id = 0
    blf.size(font_id, 14.0)
    blf.color(font_id, 1.0, 0.15, 0.10, 1.0)
    for x, y, number in labels:
        blf.position(font_id, x + 10.0, y + 8.0, 0.0)
        blf.draw(font_id, str(number))

    current = operator._next_unset(view)
    prompt = (
        FACIAL_LANDMARK_LABELS[current]
        if current is not None
        else "Click a red point to reposition it"
    )
    blf.size(font_id, 18.0)
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
    blf.position(font_id, 24.0, 54.0, 0.0)
    blf.draw(font_id, f"Place: {prompt}")
    blf.size(font_id, 13.0)
    blf.position(font_id, 24.0, 30.0, 0.0)
    blf.draw(
        font_id,
        "LMB place/move | Wheel zoom | MMB pan | S skip hidden point | "
        "Backspace undo | R reset | Enter apply | Esc cancel",
    )
    if operator.view_name in {"left", "right"}:
        blf.position(font_id, 24.0, 10.0, 0.0)
        blf.draw(
            font_id,
            "True profile: one visible eye + matching mouth corner is enough.",
        )


class SBF_OT_calibrate_face_landmarks(Operator):
    bl_idname = "sbf.calibrate_face_landmarks"
    bl_label = "Calibrate Facial Landmarks"
    bl_description = (
        "Open this source large and place head-only eye and mouth landmarks"
    )
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)

    _area = None
    _draw_handle = None
    _original_area_type = "VIEW_3D"
    _snapshot = None

    @staticmethod
    def _next_unset(view):
        for index, is_set in enumerate(view.facial_landmarks_set):
            if not is_set and not view.facial_landmarks_skipped[index]:
                return index
        return None

    def _save_snapshot(self, view):
        return {
            "points": [
                tuple(getattr(view, name)) for name in FACIAL_LANDMARK_NAMES
            ],
            "set": tuple(view.facial_landmarks_set),
            "skipped": tuple(view.facial_landmarks_skipped),
            "valid": view.facial_calibration_valid,
            "image_name": view.landmark_image_name,
        }

    def _restore_snapshot(self, view):
        for name, point in zip(
            FACIAL_LANDMARK_NAMES,
            self._snapshot["points"],
            strict=True,
        ):
            setattr(view, name, point)
        view.facial_landmarks_set = self._snapshot["set"]
        view.facial_landmarks_skipped = self._snapshot["skipped"]
        view.facial_calibration_valid = self._snapshot["valid"]
        view.landmark_image_name = self._snapshot["image_name"]

    def _close_editor(self, context):
        if self._draw_handle is not None:
            bpy.types.SpaceImageEditor.draw_handler_remove(
                self._draw_handle,
                "WINDOW",
            )
            self._draw_handle = None
        if self._area is not None:
            self._area.header_text_set(None)
            self._area.type = self._original_area_type
            self._area.tag_redraw()
        context.window.cursor_modal_restore()

    def _fit_head(self, context, view):
        area = self._area
        region = _window_region(area)
        if region is None:
            return
        space = area.spaces.active
        set_points = [
            tuple(getattr(view, name))
            for index, name in enumerate(FACIAL_LANDMARK_NAMES)
            if view.facial_landmarks_set[index]
        ]
        center = (
            (
                sum(point[0] for point in set_points) / len(set_points),
                sum(point[1] for point in set_points) / len(set_points),
            )
            if set_points
            else (0.5, 0.86)
        )
        space.cursor_location = center
        try:
            with context.temp_override(
                area=area,
                region=region,
                space_data=space,
            ):
                bpy.ops.image.view_all(fit_view=True)
                bpy.ops.image.view_center_cursor()
                for _index in range(3):
                    bpy.ops.image.view_zoom_in(
                        location=(region.width // 2, region.height // 2)
                    )
        except RuntimeError:
            pass

    def invoke(self, context, _event):
        view = getattr(_settings(context), self.view_name)
        if view.image is None:
            self.report({"ERROR"}, "Load an image for this source first.")
            return {"CANCELLED"}
        if context.area is None:
            self.report({"ERROR"}, "Facial calibration needs an editor area.")
            return {"CANCELLED"}

        self._area = context.area
        self._original_area_type = self._area.type
        self._snapshot = self._save_snapshot(view)
        self._area.type = "IMAGE_EDITOR"
        self._area.spaces.active.image = view.image
        self._area.header_text_set(
            f"{VIEW_LABELS[self.view_name]} facial calibration"
        )
        self._draw_handle = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_landmarks,
            (self,),
            "WINDOW",
            "POST_PIXEL",
        )
        context.window.cursor_modal_set("CROSSHAIR")
        context.window_manager.modal_handler_add(self)
        self._fit_head(context, view)
        self._area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _nearest_landmark(self, region, view, mouse_x, mouse_y):
        nearest = None
        nearest_distance = math.inf
        for index, name in enumerate(FACIAL_LANDMARK_NAMES):
            if not view.facial_landmarks_set[index]:
                continue
            x, y = _point_position(region, getattr(view, name))
            distance = math.hypot(x - mouse_x, y - mouse_y)
            if distance < nearest_distance:
                nearest = index
                nearest_distance = distance
        return nearest if nearest_distance <= 40.0 else None

    def _finish(self, context, view):
        count = facial_landmark_count(view)
        minimum_points = minimum_facial_landmarks(self.view_name)
        has_eye = any(view.facial_landmarks_set[:2])
        has_mouth = any(view.facial_landmarks_set[2:])
        if count < minimum_points or not has_eye or not has_mouth:
            self.report(
                {"WARNING"},
                f"Place at least {minimum_points} points, including an eye "
                "and mouth corner.",
            )
            return {"RUNNING_MODAL"}

        message = f"Saved {count}-point {VIEW_LABELS[self.view_name]} calibration."
        view.landmark_image_name = view.image.name
        try:
            result = apply_face_calibration(
                _settings(context),
                self.view_name,
            )
            if result["reference"]:
                message += " Front is now the facial reference."
            else:
                message += (
                    f" Applied head-only offset "
                    f"({result['delta_x']:+.3f}, {result['delta_y']:+.3f})."
                )
        except ValueError as exc:
            view.facial_calibration_valid = False
            message += f" {exc}"
        settings = _settings(context)
        settings.status_message = message
        mark_active_variant_dirty(settings, "Facial calibration changed")
        self.report({"INFO"}, message)
        self._close_editor(context)
        return {"FINISHED"}

    def modal(self, context, event):
        view = getattr(_settings(context), self.view_name)
        if event.type == "ESC" and event.value == "PRESS":
            self._restore_snapshot(view)
            self._close_editor(context)
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            return self._finish(context, view)
        if event.type == "R" and event.value == "PRESS":
            view.facial_landmarks_set = (False, False, False, False)
            view.facial_landmarks_skipped = (False, False, False, False)
            view.facial_calibration_valid = False
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "BACK_SPACE" and event.value == "PRESS":
            completed_indices = [
                index
                for index in range(4)
                if (
                    view.facial_landmarks_set[index]
                    or view.facial_landmarks_skipped[index]
                )
            ]
            if completed_indices:
                index = completed_indices[-1]
                view.facial_landmarks_set[index] = False
                view.facial_landmarks_skipped[index] = False
            view.facial_calibration_valid = False
            self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type == "S" and event.value == "PRESS":
            current = self._next_unset(view)
            if current is not None:
                view.facial_landmarks_skipped[current] = True
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
            index = self._next_unset(view)
            if index is None:
                index = self._nearest_landmark(
                    region,
                    view,
                    mouse_x,
                    mouse_y,
                )
            if index is not None:
                setattr(view, FACIAL_LANDMARK_NAMES[index], (x, y))
                view.facial_landmarks_set[index] = True
                view.facial_landmarks_skipped[index] = False
                view.facial_calibration_valid = False
                self._area.tag_redraw()
            return {"RUNNING_MODAL"}
        if event.type in {
            "MIDDLEMOUSE",
            "WHEELUPMOUSE",
            "WHEELDOWNMOUSE",
            "TRACKPADPAN",
            "TRACKPADZOOM",
        }:
            return {"PASS_THROUGH"}
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._snapshot is not None:
            view = getattr(_settings(context), self.view_name)
            self._restore_snapshot(view)
        self._close_editor(context)


class SBF_OT_apply_face_calibration(Operator):
    bl_idname = "sbf.apply_face_calibration"
    bl_label = "Apply Facial Calibration"
    bl_description = "Reapply saved facial landmarks to this head-only transform"
    bl_options = {"REGISTER", "UNDO"}

    view_name: EnumProperty(name="View", items=VIEW_ITEMS)

    def execute(self, context):
        settings = _settings(context)
        try:
            result = apply_face_calibration(settings, self.view_name)
        except ValueError as exc:
            settings.status_message = f"Calibration error: {exc}"
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        settings.status_message = (
            f"Applied {result['landmarks']}-point "
            f"{VIEW_LABELS[self.view_name]} facial calibration."
        )
        mark_active_variant_dirty(settings, "Facial calibration reapplied")
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


LANDMARK_OPERATOR_CLASSES = (
    SBF_OT_calibrate_face_landmarks,
    SBF_OT_apply_face_calibration,
)
