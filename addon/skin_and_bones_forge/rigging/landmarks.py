"""Deterministic humanoid landmark estimation and correction persistence."""

from __future__ import annotations

import json

from mathutils import Vector

from .analysis import axis_vector
from ..constants import RIG_CORRECTIONS_PROPERTY


LANDMARK_NAMES = (
    "pelvis",
    "lower_spine",
    "middle_spine",
    "upper_spine",
    "chest",
    "neck",
    "head_center",
    "head_top",
    "shoulder_left",
    "shoulder_right",
    "elbow_left",
    "elbow_right",
    "wrist_left",
    "wrist_right",
    "hand_left",
    "hand_right",
    "hip_left",
    "hip_right",
    "knee_left",
    "knee_right",
    "ankle_left",
    "ankle_right",
    "heel_left",
    "heel_right",
    "toe_left",
    "toe_right",
)

EDITABLE_LANDMARKS = (
    "pelvis",
    "chest",
    "neck",
    "head_center",
    "shoulder_left",
    "shoulder_right",
    "elbow_left",
    "elbow_right",
    "wrist_left",
    "wrist_right",
    "hand_left",
    "hand_right",
    "hip_left",
    "hip_right",
    "knee_left",
    "knee_right",
    "ankle_left",
    "ankle_right",
)


def _rounded(vector):
    return [round(float(value), 6) for value in vector]


def _rest_surface_points(obj):
    """Return authoritative undeformed production vertices in world space."""

    return [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]


def _slice(points, up, height, fraction, radius=0.025):
    return [
        point
        for point in points
        if abs((point.dot(up) - height[0]) / height[1] - fraction) <= radius
    ]


def _side_point(
    points,
    center,
    lateral,
    forward,
    up,
    ground,
    height,
    fraction,
    side,
    lateral_factor,
):
    samples = _slice(points, up, (ground, height), fraction)
    side_samples = [
        point
        for point in samples
        if (point - center).dot(lateral) * side > 0.0
    ]
    if side_samples:
        ordered = sorted(
            side_samples,
            key=lambda point: (point - center).dot(lateral) * side,
        )
        index = max(0, min(len(ordered) - 1, int(len(ordered) * lateral_factor)))
        point = ordered[index]
        front_coordinate = sum(item.dot(forward) for item in side_samples) / len(
            side_samples
        )
        return (
            lateral * point.dot(lateral)
            + forward * front_coordinate
            + up * (ground + fraction * height)
        )
    return center + lateral * side * height * 0.12 + up * (
        ground + fraction * height - center.dot(up)
    )


def _hand_endpoint(points, center, lateral, elbow, wrist, height, side):
    """Continue the forearm through a side-confined hand surface corridor."""

    forearm = wrist - elbow
    if forearm.length <= 1.0e-8:
        return wrist, 0.4, "degenerate forearm fallback"
    direction = forearm.normalized()
    wrist_lateral = (wrist - center).dot(lateral) * side
    candidates = []
    for point in points:
        offset = point - wrist
        projection = offset.dot(direction)
        radial = (offset - direction * projection).length
        point_lateral = (point - center).dot(lateral) * side
        if (
            0.0 < projection <= height * 0.14
            and radial <= height * 0.05
            and point_lateral >= wrist_lateral * 0.70
        ):
            candidates.append(projection)
    if len(candidates) >= 8:
        candidates.sort()
        projection = candidates[int((len(candidates) - 1) * 0.90)]
        length = min(max(projection, height * 0.055), height * 0.095)
        return (
            wrist + direction * length,
            0.88,
            "forearm continuation through side-confined hand corridor",
        )
    length = min(max(forearm.length * 0.52, height * 0.055), height * 0.09)
    return (
        wrist + direction * length,
        0.68,
        "forearm-proportion hand fallback",
    )


def estimate_landmarks(context, obj, analysis):
    points = _rest_surface_points(obj)
    up = axis_vector(analysis["up_axis"])
    forward = axis_vector(analysis["forward_axis"])
    lateral = Vector(analysis["lateral_axis_world"])
    center = Vector(analysis["centerline_world"])
    height = float(analysis["world_height"])
    ground = float(analysis["ground"])

    def center_at(fraction, forward_offset=0.0):
        return (
            center
            + up * (ground + fraction * height - center.dot(up))
            + forward * forward_offset
        )

    definitions = {
        "pelvis": (0.515, 0.82, "centerline anthropometric proportion"),
        "lower_spine": (0.575, 0.76, "centerline interpolation"),
        "middle_spine": (0.65, 0.76, "centerline interpolation"),
        "upper_spine": (0.73, 0.73, "centerline interpolation"),
        "chest": (0.76, 0.72, "centerline chest estimate"),
        "neck": (0.825, 0.72, "upper-body slice estimate"),
        "head_center": (0.91, 0.78, "head vertical proportion"),
        "head_top": (0.995, 0.96, "evaluated world-space top"),
    }
    landmarks = {}
    inverse = obj.matrix_world.inverted_safe()

    def add(name, world, confidence, method, warning=""):
        landmarks[name] = {
            "object": _rounded(inverse @ world),
            "world": _rounded(world),
            "confidence": round(float(confidence), 3),
            "method": method,
            "warning": warning,
        }

    for name, (fraction, confidence, method) in definitions.items():
        warning = ""
        if confidence < 0.75:
            warning = "Anthropometric estimate; inspect and correct before binding."
        add(name, center_at(fraction), confidence, method, warning)

    side_specs = {
        "shoulder": (0.775, 0.72, 0.84),
        "elbow": (0.655, 0.58, 0.92),
        "wrist": (0.535, 0.50, 0.90),
        "hip": (0.505, 0.72, 0.82),
        "knee": (0.285, 0.64, 0.88),
        "ankle": (0.065, 0.58, 0.86),
    }
    for base, (fraction, quantile, confidence) in side_specs.items():
        for suffix, side in (("left", 1.0), ("right", -1.0)):
            world = _side_point(
                points,
                center,
                lateral,
                forward,
                up,
                ground,
                height,
                fraction,
                side,
                quantile,
            )
            warning = (
                "Surface-slice estimate; inspect this joint."
                if confidence < 0.85
                else ""
            )
            add(
                f"{base}_{suffix}",
                world,
                confidence,
                f"evaluated mesh slice at {fraction:.3f} height",
                warning,
            )

    for suffix, side in (("left", 1.0), ("right", -1.0)):
        elbow = Vector(landmarks[f"elbow_{suffix}"]["world"])
        wrist = Vector(landmarks[f"wrist_{suffix}"]["world"])
        hand, confidence, method = _hand_endpoint(
            points,
            center,
            lateral,
            elbow,
            wrist,
            height,
            side,
        )
        add(
            f"hand_{suffix}",
            hand,
            confidence,
            method,
            "Inspect palm direction before binding." if confidence < 0.75 else "",
        )

    for suffix, side in (("left", 1.0), ("right", -1.0)):
        ankle = Vector(landmarks[f"ankle_{suffix}"]["world"])
        heel = (
            ankle
            + up * (ground + height * 0.025 - ankle.dot(up))
            - forward * height * 0.025
        )
        toe = (
            ankle
            + up * (ground + height * 0.02 - ankle.dot(up))
            + forward * height * 0.105
        )
        add(
            f"heel_{suffix}",
            heel,
            0.62,
            "ankle-relative foot estimate",
            "Foot direction is axis-based; inspect heel placement.",
        )
        add(
            f"toe_{suffix}",
            toe,
            0.62,
            "ankle-relative foot estimate",
            "Foot direction is axis-based; inspect toe placement.",
        )
    return landmarks


def apply_saved_corrections(obj, landmarks):
    raw = obj.get(RIG_CORRECTIONS_PROPERTY, "")
    if not raw:
        return landmarks
    try:
        corrections = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return landmarks
    inverse = obj.matrix_world.inverted_safe()
    for name, world_values in corrections.items():
        if name not in landmarks or len(world_values) != 3:
            continue
        world = Vector(world_values)
        landmarks[name]["world"] = _rounded(world)
        landmarks[name]["object"] = _rounded(inverse @ world)
        landmarks[name]["method"] = "artist correction"
        landmarks[name]["confidence"] = 1.0
        landmarks[name]["warning"] = ""
    return landmarks


def refresh_hand_landmarks(context, obj, analysis, landmarks):
    """Recompute automatic hand endpoints after elbow/wrist corrections."""

    points = _rest_surface_points(obj)
    center = Vector(analysis["centerline_world"])
    lateral = Vector(analysis["lateral_axis_world"])
    height = float(analysis["world_height"])
    inverse = obj.matrix_world.inverted_safe()
    for suffix, side in (("left", 1.0), ("right", -1.0)):
        name = f"hand_{suffix}"
        if landmarks[name].get("method") == "artist correction":
            continue
        elbow = Vector(landmarks[f"elbow_{suffix}"]["world"])
        wrist = Vector(landmarks[f"wrist_{suffix}"]["world"])
        hand, confidence, method = _hand_endpoint(
            points,
            center,
            lateral,
            elbow,
            wrist,
            height,
            side,
        )
        landmarks[name] = {
            "object": _rounded(inverse @ hand),
            "world": _rounded(hand),
            "confidence": round(float(confidence), 3),
            "method": method,
            "warning": (
                "Inspect palm direction before binding."
                if confidence < 0.75
                else ""
            ),
        }
    return landmarks


def save_corrections(obj, corrections):
    stable = {
        name: _rounded(Vector(position))
        for name, position in sorted(corrections.items())
        if name in EDITABLE_LANDMARKS
    }
    obj[RIG_CORRECTIONS_PROPERTY] = json.dumps(
        stable, sort_keys=True, separators=(",", ":")
    )
    return stable


def reset_corrections(obj):
    if RIG_CORRECTIONS_PROPERTY in obj:
        del obj[RIG_CORRECTIONS_PROPERTY]


def confidence_summary(landmarks):
    values = [float(item["confidence"]) for item in landmarks.values()]
    low = [name for name, item in landmarks.items() if item["confidence"] < 0.7]
    return {
        "minimum": round(min(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "low_count": len(low),
        "low_landmarks": low,
    }
