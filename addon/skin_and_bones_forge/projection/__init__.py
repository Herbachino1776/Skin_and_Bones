"""Projection setup, visibility, and preview material creation."""

from .core import (
    axis_vector,
    cleanup_temporary_data,
    create_projection_state,
    view_directions,
    world_bounds,
)
from .material import create_preview_material

__all__ = (
    "axis_vector",
    "cleanup_temporary_data",
    "create_preview_material",
    "create_projection_state",
    "view_directions",
    "world_bounds",
)
