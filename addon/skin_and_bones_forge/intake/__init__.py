"""SPAR3D source intake and production-mesh preparation."""

from .analysis import analyze_geometry, geometry_fingerprint
from .core import (
    compare_raw_and_clean,
    prepare_imported_spar3d,
    prepare_selected_spar3d,
    remove_protected_raw_source,
    restore_raw_source,
    write_intake_report,
)

__all__ = (
    "analyze_geometry",
    "compare_raw_and_clean",
    "geometry_fingerprint",
    "prepare_imported_spar3d",
    "prepare_selected_spar3d",
    "remove_protected_raw_source",
    "restore_raw_source",
    "write_intake_report",
)
