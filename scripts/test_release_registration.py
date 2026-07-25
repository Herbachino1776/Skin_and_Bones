"""Register and unregister an add-on directly from its release ZIP."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--zip", type=Path, required=True)
args = parser.parse_args(argv)

existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    try:
        existing.unregister()
    except RuntimeError:
        pass
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, str(args.zip.resolve()))

import skin_and_bones_forge  # noqa: E402


skin_and_bones_forge.register()
print("SBF_ZIP_REGISTER_OK", skin_and_bones_forge.bl_info["version"])
skin_and_bones_forge.unregister()
print("SBF_ZIP_UNREGISTER_OK")
