"""Skin & Bones Forge Blender add-on."""

from __future__ import annotations

import bpy
from .operators import OPERATOR_CLASSES
from .panels import PANEL_CLASSES
from . import properties, weapon_projection, weapon_projection_full_strength


bl_info = {
    "name": "Skin & Bones Forge",
    "author": "Skin & Bones Forge contributors",
    # Blender's add-on scanner parses bl_info with ast.literal_eval.
    "version": (2, 2, 2),
    "blender": (5, 1, 2),
    "location": "3D Viewport > Sidebar > Skin & Bones Forge",
    "description": (
        "Visual finishing, mirrored weapon texture baking, and production humanoid rigging for SPAR3D meshes"
    ),
    "category": "Material",
}


CLASSES = OPERATOR_CLASSES + PANEL_CLASSES


def register():
    properties.register()
    weapon_projection_full_strength.install()
    weapon_projection.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    from .variants.runtime import register_handlers

    register_handlers()


def unregister():
    from .variants.runtime import unregister_handlers

    unregister_handlers()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    weapon_projection.unregister()
    from .baking.repair_service import clear_runtime_cache

    clear_runtime_cache()
    properties.unregister()


if __name__ == "__main__":
    register()
