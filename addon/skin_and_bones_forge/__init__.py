"""Skin & Bones Forge Blender add-on."""

from __future__ import annotations

import bpy
from .operators import OPERATOR_CLASSES
from .panels import PANEL_CLASSES
from . import properties


bl_info = {
    "name": "Skin & Bones Forge",
    "author": "Skin & Bones Forge contributors",
    # Blender's add-on scanner parses bl_info with ast.literal_eval.
    "version": (0, 6, 6),
    "blender": (5, 1, 2),
    "location": "3D Viewport > Sidebar > Skin & Bones Forge",
    "description": (
        "Visual finishing and production humanoid rigging for SPAR3D meshes"
    ),
    "category": "Material",
}


CLASSES = OPERATOR_CLASSES + PANEL_CLASSES


def register():
    properties.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    properties.unregister()


if __name__ == "__main__":
    register()
