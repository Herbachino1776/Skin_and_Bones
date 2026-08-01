"""Deterministic, non-destructive source-plate cleanup algorithms.

This module deliberately has no Blender dependency.  Blender ships NumPy and
uses the vectorized path for production plates; the small pure-Python fallback
keeps the image contracts directly unit-testable outside Blender.
"""

from __future__ import annotations

import math
import statistics

try:  # Blender provides NumPy; repository unit tests do not require it.
    import numpy as _np
except ModuleNotFoundError:  # pragma: no cover - exercised by pure tests.
    _np = None


REFERENCE_RESOLUTION = 2048.0


def scaled_pixel_distance(value, width, height):
    """Scale a UI pixel distance from a 2K reference, deterministically."""

    if not math.isfinite(float(value)) or value < 0:
        raise ValueError("Source Doctor pixel distances must be finite and non-negative.")
    scale = max(int(width), int(height)) / REFERENCE_RESOLUTION
    return max(0, int(round(float(value) * scale)))


def _shift_numpy(values, dy, dx, fill):
    result = _np.full_like(values, fill)
    source_y = slice(max(0, -dy), values.shape[0] - max(0, dy))
    source_x = slice(max(0, -dx), values.shape[1] - max(0, dx))
    target_y = slice(max(0, dy), values.shape[0] - max(0, -dy))
    target_x = slice(max(0, dx), values.shape[1] - max(0, -dx))
    result[target_y, target_x] = values[source_y, source_x]
    return result


def _erode_numpy(mask, radius):
    result = mask.copy()
    for _index in range(radius):
        result &= _shift_numpy(result, -1, 0, False)
        result &= _shift_numpy(result, 1, 0, False)
        result &= _shift_numpy(result, 0, -1, False)
        result &= _shift_numpy(result, 0, 1, False)
    return result


def _background_numpy(grid):
    border = _np.concatenate(
        (grid[0], grid[-1], grid[:, 0], grid[:, -1]), axis=0
    )
    finite = border[_np.isfinite(border).all(axis=1)]
    if not len(finite):
        raise ValueError("Source plate border contains no finite pixels.")
    transparent = finite[finite[:, 3] <= 0.05]
    samples = transparent if len(transparent) >= max(4, len(finite) // 10) else finite
    return _np.median(samples[:, :3], axis=0)


def _extend_numpy(rgb, seed, distance):
    filled = rgb.copy()
    known = seed.copy()
    fill_distance = _np.full(seed.shape, distance + 1, dtype=_np.int32)
    fill_distance[known] = 0
    for step in range(1, distance + 1):
        count = _np.zeros(seed.shape, dtype=_np.float32)
        total = _np.zeros(rgb.shape, dtype=_np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbor_known = _shift_numpy(known, dy, dx, False)
            count += neighbor_known
            total += _shift_numpy(filled, dy, dx, 0.0) * neighbor_known[:, :, None]
        new = (~known) & (count > 0)
        if not _np.any(new):
            break
        filled[new] = total[new] / count[new, None]
        fill_distance[new] = step
        known |= new
    return filled, known, fill_distance


def _contamination_numpy(rgb, alpha, background):
    distance = _np.linalg.norm(rgb - background[None, None, :], axis=2)
    transparent = alpha <= 0.01
    near_transparent = transparent.copy()
    for dy, dx in (
        (-1, -1), (-1, 0), (-1, 1),
        (0, -1), (0, 1),
        (1, -1), (1, 0), (1, 1),
    ):
        near_transparent |= _shift_numpy(transparent, dy, dx, True)
    partial = (alpha > 0.01) & (alpha < 0.999) & near_transparent
    similarity = _np.clip(1.0 - distance / 0.18, 0.0, 1.0)
    score = float(similarity[partial].mean()) if _np.any(partial) else 0.0
    strong = partial & (distance < 0.075)
    return score, strong, distance


def _push_away_numpy(colors, background, minimum_distance=0.08):
    """Move stubborn despill colors just beyond the background-match gate."""

    values = colors.copy()
    delta = values - background[None, :]
    length = _np.linalg.norm(delta, axis=1)
    fallback = _np.where(background < 0.5, 1.0, -1.0)
    fallback /= max(float(_np.linalg.norm(fallback)), 1.0e-8)
    direction = _np.empty_like(delta)
    usable = length > 1.0e-8
    direction[usable] = delta[usable] / length[usable, None]
    direction[~usable] = fallback
    required = _np.maximum(minimum_distance, length)
    values = _np.clip(background[None, :] + direction * required[:, None], 0.0, 1.0)
    remaining = _np.linalg.norm(values - background[None, :], axis=1) < 0.075
    for index in _np.flatnonzero(remaining):
        channel = max(
            range(3),
            key=lambda item: max(float(background[item]), 1.0 - float(background[item])),
        )
        sign = -1.0 if background[channel] >= 0.5 else 1.0
        values[index, channel] = max(
            0.0,
            min(1.0, float(background[channel]) + sign * minimum_distance),
        )
    return values


def _process_numpy(
    pixels,
    width,
    height,
    erosion,
    extension,
    despill_strength,
    confidence_width,
):
    grid = _np.asarray(pixels, dtype=_np.float32).reshape((height, width, 4)).copy()
    if not _np.isfinite(grid).all():
        raise ValueError("Source plate contains non-finite pixels.")
    background = _background_numpy(grid)
    rgb = grid[:, :, :3]
    alpha = grid[:, :, 3]
    before_score, before_strong, color_distance = _contamination_numpy(
        rgb, alpha, background
    )

    border_alpha = _np.concatenate((alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))
    opaque_background = float((border_alpha >= 0.98).mean()) >= 0.80
    visible = alpha > 0.01
    if opaque_background:
        foreground = visible & (color_distance > 0.055)
    else:
        foreground = visible
    trusted_seed = foreground & (alpha >= 0.90) & (color_distance > 0.035)
    if not _np.any(trusted_seed):
        trusted_seed = foreground & (alpha >= 0.50)
    trusted = _erode_numpy(trusted_seed, erosion)
    if not _np.any(trusted):
        trusted = trusted_seed
    if not _np.any(trusted):
        raise ValueError("Source plate has no trusted foreground pixels.")

    color_seed = _erode_numpy(foreground & (alpha >= 0.90), erosion)
    if not _np.any(color_seed):
        color_seed = trusted

    # Despill may need a wider foreground search than the user-visible hidden
    # RGB extension.  Only transparent RGB within ``extension`` is written;
    # this bounded 2K-relative search solely supplies edge replacement color.
    fill_limit = max(
        extension,
        confidence_width,
        erosion + 1,
        scaled_pixel_distance(32.0, width, height),
    )
    extended_rgb, extended_mask, fill_distance = _extend_numpy(
        rgb, color_seed, fill_limit
    )

    partial = (alpha > 0.0) & (alpha < 0.999)
    suspect_edge = visible & (~trusted) & (color_distance < 0.22)
    edge = partial | suspect_edge
    # Partial alpha is most vulnerable to straight-alpha background RGB.  A
    # small minimum blend also handles antialiased pixels with alpha near one.
    edge_factor = _np.maximum(1.0 - alpha, 0.20)
    blend = _np.clip(despill_strength * edge_factor, 0.0, 1.0)
    blend *= edge & extended_mask
    rgb[:] = rgb * (1.0 - blend[:, :, None]) + extended_rgb * blend[:, :, None]

    hidden = (alpha <= 0.0) & extended_mask & (fill_distance <= extension)
    rgb[hidden] = extended_rgb[hidden]
    grid[:, :, :3] = _np.clip(rgb, 0.0, 1.0)
    # Alpha is intentionally byte-for-byte equivalent in value.
    grid[:, :, 3] = alpha

    after_score, after_strong, _after_distance = _contamination_numpy(
        grid[:, :, :3], alpha, background
    )
    stubborn = after_strong
    if _np.any(stubborn):
        replacement = grid[stubborn, :3].copy()
        has_extension = extended_mask[stubborn]
        replacement[has_extension] = extended_rgb[stubborn][has_extension]
        grid[stubborn, :3] = _push_away_numpy(replacement, background)
        after_score, after_strong, _after_distance = _contamination_numpy(
            grid[:, :, :3], alpha, background
        )
    confidence = _np.zeros(alpha.shape, dtype=_np.float32)
    confidence[trusted] = 1.0
    if confidence_width > 0:
        band = extended_mask & (~trusted) & (fill_distance <= confidence_width)
        confidence[band] = _np.clip(
            1.0 - fill_distance[band] / float(confidence_width + 1),
            0.05,
            0.95,
        )
    confidence[visible & (confidence == 0.0)] = 0.05

    return {
        "pixels": grid,
        "trusted_mask": trusted,
        "confidence": confidence,
        "contamination_mask": before_strong,
        "background": tuple(float(value) for value in background),
        "diagnostics": {
            "trusted_pixels": int(trusted.sum()),
            "visible_pixels": int(visible.sum()),
            "background_opaque": bool(opaque_background),
            "contamination_before": round(before_score, 6),
            "contamination_after": round(after_score, 6),
            "strong_matches_before": int(before_strong.sum()),
            "strong_matches_after": int(after_strong.sum()),
            "improvement": round(before_score - after_score, 6),
        },
    }


def _index(width, x, y):
    return (y * width + x) * 4


def _background_python(pixels, width, height):
    indices = []
    for x in range(width):
        indices.extend((_index(width, x, 0), _index(width, x, height - 1)))
    for y in range(height):
        indices.extend((_index(width, 0, y), _index(width, width - 1, y)))
    finite = [
        tuple(float(pixels[index + channel]) for channel in range(4))
        for index in indices
        if all(math.isfinite(float(pixels[index + channel])) for channel in range(4))
    ]
    if not finite:
        raise ValueError("Source plate border contains no finite pixels.")
    transparent = [pixel for pixel in finite if pixel[3] <= 0.05]
    samples = transparent if len(transparent) >= max(4, len(finite) // 10) else finite
    return tuple(statistics.median(pixel[channel] for pixel in samples) for channel in range(3))


def _erode_python(mask, width, height, radius):
    result = list(mask)
    for _step in range(radius):
        old = result
        result = [False] * (width * height)
        for y in range(1, height - 1):
            for x in range(1, width - 1):
                item = y * width + x
                result[item] = (
                    old[item]
                    and old[item - 1]
                    and old[item + 1]
                    and old[item - width]
                    and old[item + width]
                )
    return result


def _process_python(
    pixels,
    width,
    height,
    erosion,
    extension,
    despill_strength,
    confidence_width,
):
    values = [float(value) for value in pixels]
    if len(values) != width * height * 4:
        raise ValueError("Source plate pixel count does not match its dimensions.")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Source plate contains non-finite pixels.")
    background = _background_python(values, width, height)
    count = width * height
    alpha = [values[item * 4 + 3] for item in range(count)]
    distance = []
    for item in range(count):
        base = item * 4
        distance.append(math.sqrt(sum((values[base + c] - background[c]) ** 2 for c in range(3))))
    border_items = (
        [x for x in range(width)]
        + [(height - 1) * width + x for x in range(width)]
        + [y * width for y in range(height)]
        + [y * width + width - 1 for y in range(height)]
    )
    opaque_background = sum(alpha[item] >= 0.98 for item in border_items) / len(border_items) >= 0.80
    visible = [value > 0.01 for value in alpha]
    foreground = [
        visible[item] and (not opaque_background or distance[item] > 0.055)
        for item in range(count)
    ]
    trusted_seed = [
        foreground[item] and alpha[item] >= 0.90 and distance[item] > 0.035
        for item in range(count)
    ]
    if not any(trusted_seed):
        trusted_seed = [foreground[item] and alpha[item] >= 0.50 for item in range(count)]
    trusted = _erode_python(trusted_seed, width, height, erosion)
    if not any(trusted):
        trusted = trusted_seed
    if not any(trusted):
        raise ValueError("Source plate has no trusted foreground pixels.")

    color_seed = _erode_python(
        [foreground[item] and alpha[item] >= 0.90 for item in range(count)],
        width,
        height,
        erosion,
    )
    if not any(color_seed):
        color_seed = list(trusted)

    rgb = [[values[item * 4 + c] for c in range(3)] for item in range(count)]
    filled = [list(color) for color in rgb]
    known = list(color_seed)
    fill_limit = max(
        extension,
        confidence_width,
        erosion + 1,
        scaled_pixel_distance(32.0, width, height),
    )
    fill_distance = [fill_limit + 1] * count
    for item, state in enumerate(known):
        if state:
            fill_distance[item] = 0
    for step in range(1, fill_limit + 1):
        additions = []
        for y in range(height):
            for x in range(width):
                item = y * width + x
                if known[item]:
                    continue
                neighbors = []
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        neighbor = ny * width + nx
                        if known[neighbor]:
                            neighbors.append(neighbor)
                if neighbors:
                    additions.append((item, [sum(filled[n][c] for n in neighbors) / len(neighbors) for c in range(3)]))
        if not additions:
            break
        for item, color in additions:
            filled[item] = color
            known[item] = True
            fill_distance[item] = step

    def contamination(colors):
        similarities = []
        strong = []
        for item in range(count):
            x = item % width
            y = item // width
            near_transparent = any(
                alpha[ny * width + nx] <= 0.01
                for nx, ny in (
                    (x - 1, y - 1), (x, y - 1), (x + 1, y - 1),
                    (x - 1, y), (x + 1, y),
                    (x - 1, y + 1), (x, y + 1), (x + 1, y + 1),
                )
                if 0 <= nx < width and 0 <= ny < height
            )
            partial = 0.01 < alpha[item] < 0.999 and near_transparent
            dist = math.sqrt(sum((colors[item][c] - background[c]) ** 2 for c in range(3)))
            if partial:
                similarities.append(max(0.0, min(1.0, 1.0 - dist / 0.18)))
            strong.append(partial and dist < 0.075)
        return (sum(similarities) / len(similarities) if similarities else 0.0), strong

    def push_away(color):
        delta = [color[channel] - background[channel] for channel in range(3)]
        length = math.sqrt(sum(value * value for value in delta))
        if length <= 1.0e-8:
            delta = [1.0 if value < 0.5 else -1.0 for value in background]
            length = math.sqrt(sum(value * value for value in delta))
        scale = max(0.08, length) / length
        result = [
            max(0.0, min(1.0, background[channel] + delta[channel] * scale))
            for channel in range(3)
        ]
        result_distance = math.sqrt(
            sum((result[channel] - background[channel]) ** 2 for channel in range(3))
        )
        if result_distance < 0.075:
            channel = max(
                range(3),
                key=lambda item: max(background[item], 1.0 - background[item]),
            )
            sign = -1.0 if background[channel] >= 0.5 else 1.0
            result[channel] = max(0.0, min(1.0, background[channel] + sign * 0.08))
        return result

    before_score, before_strong = contamination(rgb)
    for item in range(count):
        edge = (0.0 < alpha[item] < 0.999) or (
            visible[item] and not trusted[item] and distance[item] < 0.22
        )
        if edge and known[item]:
            blend = max(1.0 - alpha[item], 0.20) * despill_strength
            blend = max(0.0, min(1.0, blend))
            rgb[item] = [rgb[item][c] * (1.0 - blend) + filled[item][c] * blend for c in range(3)]
        if alpha[item] <= 0.0 and known[item] and fill_distance[item] <= extension:
            rgb[item] = list(filled[item])
    after_score, after_strong = contamination(rgb)
    for item in range(count):
        if after_strong[item]:
            rgb[item] = push_away(filled[item] if known[item] else rgb[item])
    after_score, after_strong = contamination(rgb)
    output = []
    confidence = []
    for item in range(count):
        output.extend(max(0.0, min(1.0, component)) for component in rgb[item])
        output.append(alpha[item])
        if trusted[item]:
            confidence.append(1.0)
        elif visible[item] and fill_distance[item] <= confidence_width and confidence_width > 0:
            confidence.append(max(0.05, 1.0 - fill_distance[item] / (confidence_width + 1.0)))
        elif visible[item]:
            confidence.append(0.05)
        else:
            confidence.append(0.0)
    return {
        "pixels": output,
        "trusted_mask": trusted,
        "confidence": confidence,
        "contamination_mask": before_strong,
        "background": background,
        "diagnostics": {
            "trusted_pixels": sum(trusted),
            "visible_pixels": sum(visible),
            "background_opaque": opaque_background,
            "contamination_before": round(before_score, 6),
            "contamination_after": round(after_score, 6),
            "strong_matches_before": sum(before_strong),
            "strong_matches_after": sum(after_strong),
            "improvement": round(before_score - after_score, 6),
        },
    }


def process_source_plate_pixels(
    pixels,
    width,
    height,
    *,
    trusted_mask_erosion=1.5,
    rgb_extension_distance=12.0,
    despill_strength=0.85,
    silhouette_confidence_width=8.0,
):
    """Clean one flat RGBA source without changing its dimensions or alpha."""

    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError("Source plate dimensions must be positive.")
    if not 0.0 <= float(despill_strength) <= 1.0:
        raise ValueError("Despill strength must be between zero and one.")
    erosion = scaled_pixel_distance(trusted_mask_erosion, width, height)
    extension = scaled_pixel_distance(rgb_extension_distance, width, height)
    confidence = scaled_pixel_distance(silhouette_confidence_width, width, height)
    if _np is not None:
        return _process_numpy(
            pixels,
            width,
            height,
            erosion,
            extension,
            float(despill_strength),
            confidence,
        )
    return _process_python(
        pixels,
        width,
        height,
        erosion,
        extension,
        float(despill_strength),
        confidence,
    )


def validate_cleaned_pixels(result, width, height):
    """Validate numerical and contamination invariants of a doctor result."""

    pixels = result.get("pixels")
    if pixels is None:
        raise ValueError("Cleaned source has no pixel data.")
    if _np is not None and hasattr(pixels, "shape"):
        if tuple(pixels.shape) != (int(height), int(width), 4):
            raise ValueError("Owned cleaned source size does not match its original.")
        if not _np.isfinite(pixels).all():
            raise ValueError("Cleaned source contains non-finite pixels.")
    else:
        if len(pixels) != int(width) * int(height) * 4:
            raise ValueError("Owned cleaned source size does not match its original.")
        if not all(math.isfinite(float(value)) for value in pixels):
            raise ValueError("Cleaned source contains non-finite pixels.")
    diagnostics = result.get("diagnostics", {})
    before = int(diagnostics.get("strong_matches_before", 0))
    after = int(diagnostics.get("strong_matches_after", 0))
    if after:
        raise ValueError(
            "Visible partial-alpha edge pixels still strongly match the detected "
            f"background ({after} pixels)."
        )
    return True
