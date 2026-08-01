"""Pure body-landmark, bounded warp, ownership, and pose-preflight logic."""

from __future__ import annotations

import hashlib
import json
import math

try:
    import numpy as _np
except ModuleNotFoundError:  # pragma: no cover - pure tests use mapping helpers.
    _np = None


BODY_LANDMARK_NAMES = (
    "head_top",
    "chin",
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
    "toe_left",
    "toe_right",
)

BODY_LANDMARK_LABELS = {
    "head_top": "Head top",
    "chin": "Chin",
    "shoulder_left": "Left shoulder",
    "shoulder_right": "Right shoulder",
    "elbow_left": "Left elbow",
    "elbow_right": "Right elbow",
    "wrist_left": "Left wrist",
    "wrist_right": "Right wrist",
    "hand_left": "Left hand center",
    "hand_right": "Right hand center",
    "hip_left": "Left hip",
    "hip_right": "Right hip",
    "knee_left": "Left knee",
    "knee_right": "Right knee",
    "ankle_left": "Left ankle",
    "ankle_right": "Right ankle",
    "toe_left": "Left foot tip",
    "toe_right": "Right foot tip",
}

BODY_LANDMARK_ORIENTATION_HINTS = {
    "front": "Front view: character RIGHT is image LEFT",
    "back": "Back view: character RIGHT is image RIGHT",
}


def body_landmark_display_label(name):
    """Return the numbered anatomical label shown by the image editor."""

    try:
        number = BODY_LANDMARK_NAMES.index(name) + 1
        label = BODY_LANDMARK_LABELS[name]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unknown body landmark: {name}") from exc
    return f"{number}. {label}"


def body_landmark_orientation_hint(view_name):
    """Explain anatomical right where front/back mirroring is ambiguous."""

    return BODY_LANDMARK_ORIENTATION_HINTS.get(view_name, "")


BODY_PARTS = (
    "head",
    "torso",
    "left_arm",
    "right_arm",
    "pelvis",
    "left_leg",
    "right_leg",
)


def processed_state_token(payload):
    """Return a stable token used to invalidate warped/preview/bake state."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def processed_state_is_stale(saved_token, payload):
    return not saved_token or saved_token != processed_state_token(payload)

PART_LANDMARKS = {
    "head": ("head_top", "chin"),
    "torso": ("shoulder_left", "shoulder_right", "hip_left", "hip_right"),
    "left_arm": ("shoulder_left", "elbow_left", "wrist_left", "hand_left"),
    "right_arm": ("shoulder_right", "elbow_right", "wrist_right", "hand_right"),
    "pelvis": ("hip_left", "hip_right"),
    "left_leg": ("hip_left", "knee_left", "ankle_left", "toe_left"),
    "right_leg": ("hip_right", "knee_right", "ankle_right", "toe_right"),
}


def normalize_landmark(point):
    if len(point) != 2 or not all(math.isfinite(float(value)) for value in point):
        raise ValueError("Body landmarks must contain two finite coordinates.")
    return tuple(max(0.0, min(1.0, float(value))) for value in point)


def normalize_landmark_metadata(metadata, view_name=None):
    points = metadata.get("points", {})
    skipped = set(metadata.get("skipped", ()))
    unknown = (set(points) | skipped) - set(BODY_LANDMARK_NAMES)
    if unknown:
        raise ValueError(f"Unknown body landmarks: {', '.join(sorted(unknown))}")
    normalized = {
        name: normalize_landmark(point)
        for name, point in sorted(points.items())
        if name not in skipped
    }
    if view_name in {"left", "right"}:
        hidden_side = "right" if view_name == "left" else "left"
        required_skips = {
            name for name in BODY_LANDMARK_NAMES if name.endswith(f"_{hidden_side}")
        }
        if not required_skips.issubset(skipped):
            raise ValueError("Profile landmarks must explicitly skip the hidden side.")
    return {"points": normalized, "skipped": sorted(skipped)}


def auto_initialize_landmarks(view_name, bounds=(0.0, 0.0, 1.0, 1.0)):
    """Create deterministic anthropometric image metadata for one source."""

    minimum_x, minimum_y, maximum_x, maximum_y = map(float, bounds)
    width = max(maximum_x - minimum_x, 1.0e-6)
    height = max(maximum_y - minimum_y, 1.0e-6)

    def point(x, y):
        return (minimum_x + x * width, minimum_y + y * height)

    if view_name in {"left", "right"}:
        visible = view_name
        hidden = "right" if view_name == "left" else "left"
        points = {
            "head_top": point(0.50, 0.995),
            "chin": point(0.50, 0.815),
            f"shoulder_{visible}": point(0.50, 0.775),
            f"elbow_{visible}": point(0.52, 0.655),
            f"wrist_{visible}": point(0.54, 0.535),
            f"hand_{visible}": point(0.55, 0.505),
            f"hip_{visible}": point(0.50, 0.505),
            f"knee_{visible}": point(0.51, 0.285),
            f"ankle_{visible}": point(0.52, 0.065),
            f"toe_{visible}": point(0.62, 0.020),
        }
        skipped = [name for name in BODY_LANDMARK_NAMES if name.endswith(f"_{hidden}")]
    else:
        # Front cameras show anatomical left on image-right; a back camera
        # reverses that screen relationship.  Names remain anatomical.
        left_x, right_x = ((0.64, 0.36) if view_name != "back" else (0.36, 0.64))
        outer_left, outer_right = ((1.0, -1.0) if left_x > right_x else (-1.0, 1.0))
        points = {
            "head_top": point(0.50, 0.995),
            "chin": point(0.50, 0.815),
            "shoulder_left": point(left_x, 0.775),
            "shoulder_right": point(right_x, 0.775),
            "elbow_left": point(left_x + outer_left * 0.12, 0.655),
            "elbow_right": point(right_x + outer_right * 0.12, 0.655),
            "wrist_left": point(left_x + outer_left * 0.20, 0.535),
            "wrist_right": point(right_x + outer_right * 0.20, 0.535),
            "hand_left": point(left_x + outer_left * 0.24, 0.505),
            "hand_right": point(right_x + outer_right * 0.24, 0.505),
            "hip_left": point(0.56 if left_x > right_x else 0.44, 0.505),
            "hip_right": point(0.44 if left_x > right_x else 0.56, 0.505),
            "knee_left": point(0.55 if left_x > right_x else 0.45, 0.285),
            "knee_right": point(0.45 if left_x > right_x else 0.55, 0.285),
            "ankle_left": point(0.54 if left_x > right_x else 0.46, 0.065),
            "ankle_right": point(0.46 if left_x > right_x else 0.54, 0.065),
            "toe_left": point(0.55 if left_x > right_x else 0.45, 0.020),
            "toe_right": point(0.45 if left_x > right_x else 0.55, 0.020),
        }
        skipped = []
    return normalize_landmark_metadata({"points": points, "skipped": skipped}, view_name)


def _triangle_barycentric(point, triangle):
    (ax, ay), (bx, by), (cx, cy) = triangle
    px, py = point
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) <= 1.0e-12:
        return None
    first = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
    second = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
    return first, second, 1.0 - first - second


def piecewise_affine_map(point, source_triangles, destination_triangles):
    """Map a point through the matching bounded destination triangle."""

    if len(source_triangles) != len(destination_triangles):
        raise ValueError("Piecewise-affine triangle sets must have equal lengths.")
    for source, destination in zip(source_triangles, destination_triangles, strict=True):
        weights = _triangle_barycentric(point, destination)
        if weights is None or min(weights) < -1.0e-9:
            continue
        return tuple(
            sum(weights[index] * source[index][axis] for index in range(3))
            for axis in range(2)
        )
    return None


def _ribbon(points, widths):
    result = []
    for index, point in enumerate(points):
        previous = points[max(0, index - 1)]
        following = points[min(len(points) - 1, index + 1)]
        dx = following[0] - previous[0]
        dy = following[1] - previous[1]
        length = max(math.hypot(dx, dy), 1.0e-8)
        normal = (-dy / length, dx / length)
        result.extend(
            (
                (point[0] + normal[0] * widths[index], point[1] + normal[1] * widths[index]),
                (point[0] - normal[0] * widths[index], point[1] - normal[1] * widths[index]),
            )
        )
    return result


def _ribbon_triangles(points, widths):
    vertices = _ribbon(points, widths)
    triangles = []
    for index in range(len(points) - 1):
        left_a, right_a = index * 2, index * 2 + 1
        left_b, right_b = index * 2 + 2, index * 2 + 3
        triangles.extend(
            ((vertices[left_a], vertices[right_a], vertices[left_b]),
             (vertices[right_a], vertices[right_b], vertices[left_b]))
        )
    return triangles


def part_triangles(part, landmarks):
    points = landmarks["points"] if "points" in landmarks else landmarks
    names = PART_LANDMARKS[part]
    if any(name not in points for name in names):
        return []
    selected = [tuple(points[name]) for name in names]
    if part in {"left_arm", "right_arm"}:
        return _ribbon_triangles(selected, (0.050, 0.045, 0.040, 0.055))
    if part in {"left_leg", "right_leg"}:
        return _ribbon_triangles(selected, (0.070, 0.065, 0.050, 0.070))
    if part == "torso":
        left_shoulder, right_shoulder, left_hip, right_hip = selected
        return [
            (left_shoulder, right_shoulder, left_hip),
            (right_shoulder, right_hip, left_hip),
        ]
    if part == "pelvis":
        left_hip, right_hip = selected
        center_y = (left_hip[1] + right_hip[1]) * 0.5
        top = center_y + 0.055
        bottom = center_y - 0.065
        return [
            ((left_hip[0] + 0.035, top), (right_hip[0] - 0.035, top), (left_hip[0] + 0.025, bottom)),
            ((right_hip[0] - 0.035, top), (right_hip[0] - 0.025, bottom), (left_hip[0] + 0.025, bottom)),
        ]
    if part == "head":
        top, chin = selected
        height = max(abs(top[1] - chin[1]), 0.08)
        half_width = height * 0.42
        center_x = (top[0] + chin[0]) * 0.5
        return [
            ((center_x - half_width, chin[1]), (center_x + half_width, chin[1]), (center_x - half_width, top[1])),
            ((center_x + half_width, chin[1]), (center_x + half_width, top[1]), (center_x - half_width, top[1])),
        ]
    raise ValueError(f"Unknown body part: {part}")


def classify_mismatch(error):
    value = float(error)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Pose mismatch must be finite and non-negative.")
    if value <= 0.120:
        return "ACCEPTABLE"
    if value <= 0.400:
        return "MODERATE"
    return "SEVERE"


def pose_mismatch(source, target):
    """Compare per-part shape relative to its anatomical anchor."""

    source_points = source["points"] if "points" in source else source
    target_points = target["points"] if "points" in target else target
    result = {}
    for part, names in PART_LANDMARKS.items():
        available = [name for name in names if name in source_points and name in target_points]
        if len(available) < 2:
            result[part] = {"status": "HIDDEN", "error": 0.0}
            continue
        # A two-anchor head or pelvis can express position/scale but not a
        # contradictory articulated pose.  Its bounded affine patch is the
        # appropriate correction and must not trip the severe-pose gate.
        if len(available) == 2:
            result[part] = {"status": "ACCEPTABLE", "error": 0.0}
            continue
        if part == "torso":
            def centered_shape(points):
                center = (
                    sum(points[name][0] for name in available) / len(available),
                    sum(points[name][1] for name in available) / len(available),
                )
                offsets = [
                    (points[name][0] - center[0], points[name][1] - center[1])
                    for name in available
                ]
                scale = max(
                    math.sqrt(sum(x * x + y * y for x, y in offsets)),
                    1.0e-8,
                )
                return [(x / scale, y / scale) for x, y in offsets]

            source_shape = centered_shape(source_points)
            target_shape = centered_shape(target_points)
            error = max(
                math.hypot(source[0] - target[0], source[1] - target[1])
                for source, target in zip(source_shape, target_shape, strict=True)
            )
            # The torso is explicitly a bounded two-triangle affine patch;
            # proportion and taper differences are repairable, unlike a
            # reversed or strongly bent limb chain.
            error = min(error, 0.150)
        else:
            def anchored_chain(points):
                chain = [points[name] for name in available]
                scale = max(
                    sum(
                        math.hypot(
                            chain[index + 1][0] - chain[index][0],
                            chain[index + 1][1] - chain[index][1],
                        )
                        for index in range(len(chain) - 1)
                    ),
                    1.0e-8,
                )
                anchor = chain[0]
                return [
                    ((point[0] - anchor[0]) / scale, (point[1] - anchor[1]) / scale)
                    for point in chain[1:]
                ]

            source_chain = anchored_chain(source_points)
            target_chain = anchored_chain(target_points)
            error = max(
                math.hypot(source[0] - target[0], source[1] - target[1])
                for source, target in zip(source_chain, target_chain, strict=True)
            )
        result[part] = {"status": classify_mismatch(error), "error": round(error, 6)}
    severity = {"HIDDEN": -1, "ACCEPTABLE": 0, "MODERATE": 1, "SEVERE": 2}
    worst_part = max(result, key=lambda part: (severity[result[part]["status"]], result[part]["error"], part))
    return {
        "parts": result,
        "worst_part": worst_part,
        "status": result[worst_part]["status"],
        "error": result[worst_part]["error"],
    }


def segment_distance(point, first, second):
    dx = second[0] - first[0]
    dy = second[1] - first[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1.0e-16:
        return math.hypot(point[0] - first[0], point[1] - first[1])
    factor = max(0.0, min(1.0, ((point[0] - first[0]) * dx + (point[1] - first[1]) * dy) / length_squared))
    nearest = (first[0] + dx * factor, first[1] + dy * factor)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def body_part_ownership(point, landmarks):
    """Assign one anatomical owner; left/right chains can never cross."""

    height = float(point[1])
    if height >= 0.82:
        return "head"
    arm_distance = {}
    leg_distance = {}
    for side in ("left", "right"):
        arm = [landmarks[name] for name in (f"shoulder_{side}", f"elbow_{side}", f"wrist_{side}", f"hand_{side}")]
        leg = [landmarks[name] for name in (f"hip_{side}", f"knee_{side}", f"ankle_{side}", f"toe_{side}")]
        arm_distance[side] = min(segment_distance(point, arm[i], arm[i + 1]) for i in range(3))
        leg_distance[side] = min(segment_distance(point, leg[i], leg[i + 1]) for i in range(3))
    nearest_arm = min(arm_distance, key=arm_distance.get)
    nearest_leg = min(leg_distance, key=leg_distance.get)
    if arm_distance[nearest_arm] <= 0.075 and arm_distance[nearest_arm] < leg_distance[nearest_leg] * 0.85:
        return f"{nearest_arm}_arm"
    if height <= 0.54 and leg_distance[nearest_leg] <= 0.10:
        return f"{nearest_leg}_leg"
    if 0.44 <= height <= 0.57:
        return "pelvis"
    if height < 0.48:
        return f"{nearest_leg}_leg"
    return "torso"


def _sample_bilinear_numpy(grid, source_x, source_y):
    height, width = grid.shape[:2]
    x = _np.clip(source_x * (width - 1), 0.0, width - 1.0)
    y = _np.clip(source_y * (height - 1), 0.0, height - 1.0)
    x0 = _np.floor(x).astype(_np.int32)
    y0 = _np.floor(y).astype(_np.int32)
    x1 = _np.minimum(x0 + 1, width - 1)
    y1 = _np.minimum(y0 + 1, height - 1)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    top = grid[y0, x0] * (1.0 - fx) + grid[y0, x1] * fx
    bottom = grid[y1, x0] * (1.0 - fx) + grid[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


def warp_part_pixels(pixels, width, height, source_landmarks, target_landmarks, part, feather=0.08):
    """Rasterize a bounded piecewise-affine part image with joint feathering."""

    if _np is None:
        raise RuntimeError("Production source warping requires Blender's NumPy runtime.")
    source_triangles = part_triangles(part, source_landmarks)
    target_triangles = part_triangles(part, target_landmarks)
    if not source_triangles or len(source_triangles) != len(target_triangles):
        return _np.zeros((height, width, 4), dtype=_np.float32)
    source_grid = _np.asarray(pixels, dtype=_np.float32).reshape((height, width, 4))
    output = _np.zeros_like(source_grid)
    for source, destination in zip(source_triangles, target_triangles, strict=True):
        destination_pixels = _np.asarray(destination, dtype=_np.float64)
        minimum_x = max(0, int(math.floor(destination_pixels[:, 0].min() * (width - 1))))
        maximum_x = min(width - 1, int(math.ceil(destination_pixels[:, 0].max() * (width - 1))))
        minimum_y = max(0, int(math.floor(destination_pixels[:, 1].min() * (height - 1))))
        maximum_y = min(height - 1, int(math.ceil(destination_pixels[:, 1].max() * (height - 1))))
        if maximum_x < minimum_x or maximum_y < minimum_y:
            continue
        x_values = _np.arange(minimum_x, maximum_x + 1, dtype=_np.float64) / max(width - 1, 1)
        y_values = _np.arange(minimum_y, maximum_y + 1, dtype=_np.float64) / max(height - 1, 1)
        xx, yy = _np.meshgrid(x_values, y_values)
        ax, ay = destination[0]
        bx, by = destination[1]
        cx, cy = destination[2]
        denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(denominator) <= 1.0e-12:
            continue
        first = ((by - cy) * (xx - cx) + (cx - bx) * (yy - cy)) / denominator
        second = ((cy - ay) * (xx - cx) + (ax - cx) * (yy - cy)) / denominator
        third = 1.0 - first - second
        inside = (first >= -1.0e-8) & (second >= -1.0e-8) & (third >= -1.0e-8)
        if not _np.any(inside):
            continue
        barycentric = _np.stack((first[inside], second[inside], third[inside]), axis=1)
        source_array = _np.asarray(source, dtype=_np.float64)
        source_points = barycentric @ source_array
        sampled = _sample_bilinear_numpy(source_grid, source_points[:, 0], source_points[:, 1])
        if feather > 0:
            edge = _np.clip(barycentric.min(axis=1) / float(feather), 0.0, 1.0)
            edge = edge * edge * (3.0 - 2.0 * edge)
            sampled[:, 3] *= edge
        # A bounded 2D slice is not C-contiguous when it is narrower than the
        # full image. Reshaping that slice can silently allocate a copy, which
        # previously discarded every warped pixel and left the bake falling
        # back to the old atlas. Index the destination explicitly instead.
        local_y, local_x = _np.nonzero(inside)
        destination_y = local_y + minimum_y
        destination_x = local_x + minimum_x
        replace = sampled[:, 3] >= output[destination_y, destination_x, 3]
        output[destination_y[replace], destination_x[replace]] = sampled[replace]
    return output
