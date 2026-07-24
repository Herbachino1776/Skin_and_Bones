"""Alpha-silhouette alignment for source projection images."""

from __future__ import annotations

import numpy

from ..constants import FACIAL_LANDMARK_NAMES, VIEW_NAMES
from .core import view_directions, world_bounds


def _alpha_bounds(
    image,
    threshold=0.02,
    sample_limit=384,
    head_threshold=0.80,
):
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError(f"Image '{image.name}' has no pixel data.")
    if image.channels < 4:
        return (0.0, 0.0, 1.0, 1.0), (0.0, head_threshold, 1.0, 1.0), False

    step_x = max(1, width // sample_limit)
    step_y = max(1, height // sample_limit)
    pixels = numpy.empty(width * height * image.channels, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    pixel_grid = pixels.reshape((height, width, image.channels))
    sampled_pixels = pixel_grid[::step_y, ::step_x]
    sampled_alpha = sampled_pixels[:, :, 3]
    visible = sampled_alpha > threshold

    border = numpy.concatenate(
        (
            sampled_pixels[0, :, :3],
            sampled_pixels[-1, :, :3],
            sampled_pixels[:, 0, :3],
            sampled_pixels[:, -1, :3],
        ),
        axis=0,
    )
    background = numpy.median(border, axis=0)
    use_black_key = (
        float(visible.mean()) > 0.98 and float(background.max()) < 0.02
    )
    if use_black_key:
        color_distance = numpy.max(
            numpy.abs(sampled_pixels[:, :, :3] - background),
            axis=2,
        )
        visible &= color_distance > 0.01

    sampled_y, sampled_x = numpy.nonzero(visible)
    if sampled_x.size == 0:
        raise ValueError(f"Image '{image.name}' has no visible alpha silhouette.")

    minimum_x = int(sampled_x.min()) * step_x
    minimum_y = int(sampled_y.min()) * step_y
    maximum_x = int(sampled_x.max()) * step_x
    maximum_y = int(sampled_y.max()) * step_y

    bounds = (
        minimum_x / width,
        minimum_y / height,
        min(1.0, (maximum_x + step_x) / width),
        min(1.0, (maximum_y + step_y) / height),
    )
    head_cutoff = minimum_y + (maximum_y - minimum_y) * head_threshold
    sample_rows = (
        numpy.arange(visible.shape[0], dtype=numpy.int32) * step_y
    )[:, None]
    head_visible = visible & (sample_rows >= head_cutoff)
    head_y, head_x = numpy.nonzero(head_visible)
    if head_x.size:
        head_minimum_x = int(head_x.min()) * step_x
        head_minimum_y = int(head_y.min()) * step_y
        head_maximum_x = int(head_x.max()) * step_x
        head_maximum_y = int(head_y.max()) * step_y
        head_bounds = (
            head_minimum_x / width,
            head_minimum_y / height,
            min(1.0, (head_maximum_x + step_x) / width),
            min(1.0, (head_maximum_y + step_y) / height),
        )
    else:
        head_bounds = bounds
    return bounds, head_bounds, use_black_key


def _view_name(settings, changed_view):
    if isinstance(changed_view, str):
        if changed_view not in VIEW_NAMES:
            raise ValueError(f"Unknown source view: {changed_view}")
        return changed_view
    changed_pointer = changed_view.as_pointer()
    for name in VIEW_NAMES:
        if getattr(settings, name).as_pointer() == changed_pointer:
            return name
    raise ValueError("Source view does not belong to these scene settings.")


def facial_landmark_count(view):
    return sum(bool(value) for value in view.facial_landmarks_set)


def _facial_landmark_metrics(view, head_bounds):
    points = [
        tuple(getattr(view, name))
        for index, name in enumerate(FACIAL_LANDMARK_NAMES)
        if view.facial_landmarks_set[index]
    ]
    eye_points = [
        tuple(getattr(view, FACIAL_LANDMARK_NAMES[index]))
        for index in (0, 1)
        if view.facial_landmarks_set[index]
    ]
    mouth_points = [
        tuple(getattr(view, FACIAL_LANDMARK_NAMES[index]))
        for index in (2, 3)
        if view.facial_landmarks_set[index]
    ]
    if len(points) < 3 or not eye_points or not mouth_points:
        raise ValueError(
            "Facial calibration needs at least three points, including an "
            "eye and a mouth corner."
        )

    eye_center = (
        sum(point[0] for point in eye_points) / len(eye_points),
        sum(point[1] for point in eye_points) / len(eye_points),
    )
    mouth_center = (
        sum(point[0] for point in mouth_points) / len(mouth_points),
        sum(point[1] for point in mouth_points) / len(mouth_points),
    )
    center = (
        (eye_center[0] + mouth_center[0]) * 0.5,
        (eye_center[1] + mouth_center[1]) * 0.5,
    )
    minimum_x, minimum_y, maximum_x, maximum_y = head_bounds
    head_width = max(maximum_x - minimum_x, 1.0e-6)
    head_height = max(maximum_y - minimum_y, 1.0e-6)
    horizontal_span = max(point[0] for point in points) - min(
        point[0] for point in points
    )
    vertical_span = abs(eye_center[1] - mouth_center[1])
    return {
        "center_x": (center[0] - minimum_x) / head_width,
        "center_y": (center[1] - minimum_y) / head_height,
        "horizontal_ratio": horizontal_span / head_width,
        "vertical_ratio": vertical_span / head_height,
        "head_width": head_width,
        "head_height": head_height,
        "complete": facial_landmark_count(view) == 4,
    }


def apply_face_calibration(settings, changed_view):
    """Align one source's facial frame to the calibrated front reference."""

    name = _view_name(settings, changed_view)
    view = getattr(settings, name)
    if view.image is None:
        raise ValueError(f"{name.replace('_', ' ').title()} has no image.")
    if facial_landmark_count(view) < 3:
        raise ValueError(
            f"{name.replace('_', ' ').title()} needs at least three landmarks."
        )

    _bounds, head_bounds, _key = _alpha_bounds(
        view.image,
        threshold=max(0.02, view.alpha_threshold),
        head_threshold=settings.head_threshold,
    )
    if name == "front":
        _facial_landmark_metrics(view, head_bounds)
        view.facial_calibration_valid = True
        return {
            "name": name,
            "reference": True,
            "landmarks": facial_landmark_count(view),
        }

    reference = settings.front
    if reference.image is None or facial_landmark_count(reference) < 3:
        view.facial_calibration_valid = False
        raise ValueError(
            "Calibrate the Front source first; it defines the facial reference."
        )
    _reference_bounds, reference_head_bounds, _reference_key = _alpha_bounds(
        reference.image,
        threshold=max(0.02, reference.alpha_threshold),
        head_threshold=settings.head_threshold,
    )
    reference_metrics = _facial_landmark_metrics(
        reference,
        reference_head_bounds,
    )
    metrics = _facial_landmark_metrics(view, head_bounds)

    vertical_factor = 1.0
    if metrics["vertical_ratio"] > 1.0e-5:
        vertical_factor = (
            reference_metrics["vertical_ratio"] / metrics["vertical_ratio"]
        )
    vertical_factor = max(0.65, min(1.50, vertical_factor))

    horizontal_factor = 1.0
    if (
        metrics["complete"]
        and reference_metrics["complete"]
        and metrics["horizontal_ratio"] > 1.0e-5
    ):
        horizontal_factor = (
            reference_metrics["horizontal_ratio"]
            / metrics["horizontal_ratio"]
        )
        horizontal_factor = max(0.65, min(1.50, horizontal_factor))

    base_scale = view.auto_head_scale
    base_horizontal_scale = view.auto_head_horizontal_scale
    base_offset_x = view.auto_head_offset_x
    base_offset_y = view.auto_head_offset_y
    old_total_x = base_scale * base_horizontal_scale
    view.head_scale = max(
        0.25,
        min(4.0, base_scale * vertical_factor),
    )
    new_total_x = max(
        0.25,
        min(4.0, old_total_x * horizontal_factor),
    )
    view.head_horizontal_scale = max(
        0.25,
        min(4.0, new_total_x / view.head_scale),
    )

    delta_x = (
        metrics["center_x"] - reference_metrics["center_x"]
    ) * metrics["head_width"]
    delta_y = (
        metrics["center_y"] - reference_metrics["center_y"]
    ) * metrics["head_height"]
    view.head_offset_x = max(
        -1.0,
        min(1.0, base_offset_x + delta_x),
    )
    view.head_offset_y = max(
        -1.0,
        min(1.0, base_offset_y + delta_y),
    )
    view.facial_calibration_valid = True
    return {
        "name": name,
        "reference": False,
        "landmarks": facial_landmark_count(view),
        "horizontal_factor": horizontal_factor,
        "vertical_factor": vertical_factor,
        "delta_x": delta_x,
        "delta_y": delta_y,
    }


def auto_fit_view_image(settings, changed_view):
    """Fit one loaded view's alpha silhouette to the projection frame."""

    name = _view_name(settings, changed_view)
    view = getattr(settings, name)
    if view.image is None:
        return None

    bounds, source_head_bounds, use_black_key = _alpha_bounds(
        view.image,
        threshold=max(0.02, view.alpha_threshold),
        head_threshold=settings.head_threshold,
    )
    minimum_x, minimum_y, maximum_x, maximum_y = bounds
    source_height = max(maximum_y - minimum_y, 1.0e-6)
    source_center_x = (minimum_x + maximum_x) * 0.5
    source_center_y = (minimum_y + maximum_y) * 0.5

    view.scale = max(0.1, min(5.0, settings.framing_ratio / source_height))
    source_width = max(maximum_x - minimum_x, 1.0e-6)
    view.horizontal_scale = 1.0
    target = settings.target_object
    if target is not None and target.type == "MESH":
        directions = view_directions(settings)
        target_bounds = world_bounds(target, directions)
        screen_horizontal = directions["up"].cross(directions[name]).normalized()
        horizontal_values = [
            point.dot(screen_horizontal) for point in target_bounds["points"]
        ]
        horizontal_span = max(horizontal_values) - min(horizontal_values)
        target_width = (
            horizontal_span
            / target_bounds["up_span"]
            * settings.framing_ratio
        )
        # Give profile sources modest silhouette overscan. A side photograph
        # that only matches the exact orthographic width can expose a narrow
        # front-source strip when inspected from a 60-degree view.
        if name in {"left", "right"}:
            coverage_margin = 1.18
        elif name in {"front_left", "front_right"}:
            coverage_margin = 1.10
        else:
            coverage_margin = 1.03
        horizontal_total = target_width / source_width * coverage_margin
        view.horizontal_scale = max(
            0.1,
            min(5.0, horizontal_total / view.scale),
        )
    view.offset_x = source_center_x - 0.5
    view.offset_y = source_center_y - 0.5
    view.key_black_background = use_black_key

    view.head_scale = 1.0
    view.head_horizontal_scale = 1.0
    view.head_offset_x = 0.0
    view.head_offset_y = 0.0
    if target is not None and target.type == "MESH":
        up = directions["up"]
        screen_horizontal = up.cross(directions[name]).normalized()
        ortho_scale = target_bounds["up_span"] / max(
            settings.framing_ratio,
            1.0e-6,
        )
        head_points = [
            point
            for point in target_bounds["points"]
            if (
                point.dot(up) - target_bounds["up_min"]
            )
            / target_bounds["up_span"]
            >= settings.head_threshold
        ]
        if head_points:
            raw_u = [
                0.5
                + (
                    point.dot(screen_horizontal)
                    - target_bounds["center"].dot(screen_horizontal)
                )
                / ortho_scale
                for point in head_points
            ]
            raw_v = [
                0.5
                + (
                    point.dot(up) - target_bounds["center"].dot(up)
                )
                / ortho_scale
                for point in head_points
            ]
            sign_x = -1.0 if view.flip_x else 1.0
            sign_y = -1.0 if view.flip_y else 1.0
            global_scale_x = view.scale * view.horizontal_scale

            def global_x(value):
                return (
                    sign_x * (value - 0.5) / global_scale_x
                    + 0.5
                    + view.offset_x
                )

            def global_y(value):
                return (
                    sign_y * (value - 0.5) / view.scale
                    + 0.5
                    + view.offset_y
                )

            target_head_min_x = min(global_x(value) for value in raw_u)
            target_head_max_x = max(global_x(value) for value in raw_u)
            target_head_min_y = min(global_y(value) for value in raw_v)
            target_head_max_y = max(global_y(value) for value in raw_v)
            target_head_width = max(
                target_head_max_x - target_head_min_x,
                1.0e-6,
            )
            target_head_height = max(
                target_head_max_y - target_head_min_y,
                1.0e-6,
            )
            (
                source_head_min_x,
                source_head_min_y,
                source_head_max_x,
                source_head_max_y,
            ) = source_head_bounds
            source_head_width = max(
                source_head_max_x - source_head_min_x,
                1.0e-6,
            )
            source_head_height = max(
                source_head_max_y - source_head_min_y,
                1.0e-6,
            )
            view.head_scale = max(
                0.25,
                min(4.0, target_head_height / source_head_height),
            )
            total_head_scale_x = target_head_width / source_head_width
            view.head_horizontal_scale = max(
                0.25,
                min(4.0, total_head_scale_x / view.head_scale),
            )
            target_head_center_x = (
                target_head_min_x + target_head_max_x
            ) * 0.5
            target_head_center_y = (
                target_head_min_y + target_head_max_y
            ) * 0.5
            source_head_center_x = (
                source_head_min_x + source_head_max_x
            ) * 0.5
            source_head_center_y = (
                source_head_min_y + source_head_max_y
            ) * 0.5
            view.head_offset_x = (
                source_head_center_x
                - 0.5
                - (target_head_center_x - 0.5) / total_head_scale_x
            )
            view.head_offset_y = (
                source_head_center_y
                - 0.5
                - (target_head_center_y - 0.5) / view.head_scale
            )
    view.auto_head_scale = view.head_scale
    view.auto_head_horizontal_scale = view.head_horizontal_scale
    view.auto_head_offset_x = view.head_offset_x
    view.auto_head_offset_y = view.head_offset_y
    if facial_landmark_count(view) >= 3:
        try:
            apply_face_calibration(settings, name)
        except ValueError:
            view.facial_calibration_valid = False
    return {
        "name": name,
        "bounds": bounds,
        "head_bounds": source_head_bounds,
        "key_black_background": use_black_key,
        "scale": view.scale,
        "horizontal_scale": view.horizontal_scale,
        "offset_x": view.offset_x,
        "offset_y": view.offset_y,
        "head_scale": view.head_scale,
        "head_horizontal_scale": view.head_horizontal_scale,
        "head_offset_x": view.head_offset_x,
        "head_offset_y": view.head_offset_y,
    }


def auto_fit_loaded_images(settings):
    results = []
    for name in VIEW_NAMES:
        view = getattr(settings, name)
        if view.enabled and view.image is not None:
            results.append(auto_fit_view_image(settings, name))
    return results
