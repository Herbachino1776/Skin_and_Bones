"""Factory-clean Blender runner for rigged GLB reimport acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--height", type=float, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


args = _args()
report = {"status": "CLEAN_REIMPORT_FAILED"}
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(addon_root))
    from skin_and_bones_forge.rigging.production import (  # noqa: E402
        _validate_clean_reimport_in_process,
    )

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    report = _validate_clean_reimport_in_process(
        bpy.context,
        args.glb,
        contract,
        args.height,
    )
except Exception as exc:
    report["error"] = str(exc)
finally:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

print("SBF_CLEAN_REIMPORT")
print(json.dumps(report, indent=2, sort_keys=True))
if report["status"] != "CLEAN_REIMPORT_PASSED":
    raise RuntimeError(report.get("error", "Clean reimport validation failed."))
