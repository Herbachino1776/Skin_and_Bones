"""Pure helpers shared by mesh landmark estimators."""

from __future__ import annotations

import math


def isolated_outer_cluster_indices(
    distances,
    *,
    minimum_gap,
    lower_search_fraction=0.15,
    upper_search_fraction=0.90,
    minimum_outer_fraction=0.08,
    minimum_outer_points=8,
):
    """Return indices in the isolated outer silhouette cluster.

    Cross-sections through a humanoid wrist or elbow usually contain a dense
    torso/clothing band near the center and a separate arm band near the side.
    Selecting a global percentile can land inside the torso.  The largest
    meaningful lateral gap separates those two bands deterministically.
    """

    values = [float(value) for value in distances]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("Outer-cluster distances must be finite and non-negative.")
    count = len(values)
    if count < minimum_outer_points * 2:
        return ()
    order = sorted(range(count), key=lambda index: (values[index], index))
    ordered = [values[index] for index in order]
    first_gap = max(0, min(count - 2, int(count * lower_search_fraction)))
    last_gap = max(
        first_gap,
        min(count - 2, int(count * upper_search_fraction) - 1),
    )
    split = max(
        range(first_gap, last_gap + 1),
        key=lambda index: (ordered[index + 1] - ordered[index], index),
    )
    gap = ordered[split + 1] - ordered[split]
    outer = order[split + 1 :]
    required = max(minimum_outer_points, math.ceil(count * minimum_outer_fraction))
    if gap < float(minimum_gap) or len(outer) < required:
        return ()
    return tuple(outer)
