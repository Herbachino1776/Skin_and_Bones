"""Install the repository add-on into the running Blender user profile.

Run in Blender:
    blender --background --python scripts/install_addon.py

This development helper copies the module directly. End users should install
the versioned ZIP through Edit > Preferences > Add-ons > Install from Disk.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import addon_utils
import bpy


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "addon" / "skin_and_bones_forge"
ADDONS = Path(bpy.utils.user_resource("SCRIPTS", path="addons", create=True))
DESTINATION = ADDONS / "skin_and_bones_forge"

if DESTINATION.exists():
    shutil.rmtree(DESTINATION)
shutil.copytree(SOURCE, DESTINATION)
addon_utils.modules_refresh()
bpy.ops.preferences.addon_enable(module="skin_and_bones_forge")
bpy.ops.wm.save_userpref()
print(f"Installed Skin & Bones Forge from {SOURCE} to {DESTINATION}")
