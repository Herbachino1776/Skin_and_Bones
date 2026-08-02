"""Render an unsaved projection-preview proof from an arbitrary user blend.

The input blend is opened by Blender before this script runs.  This helper
registers the checkout add-on, refreshes the best preview, writes the generated
processed view images, and renders the standard verification set without
saving or modifying the input blend on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy


def _arguments():
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--proof-resolution", type=int, default=512)
    parser.add_argument("--bake", action="store_true")
    parser.add_argument("--render-original", action="store_true")
    return parser.parse_args(values)


args = _arguments()
repo_root = args.repo_root.resolve()
output_dir = args.output_dir.resolve()
output_dir.mkdir(parents=True, exist_ok=True)
addon_path = repo_root / "addon"
sys.path.insert(0, str(addon_path))

existing = sys.modules.get("skin_and_bones_forge")
if existing is not None:
    try:
        existing.unregister()
    except (AttributeError, RuntimeError):
        pass
    for module_name in tuple(sys.modules):
        if module_name == "skin_and_bones_forge" or module_name.startswith(
            "skin_and_bones_forge."
        ):
            del sys.modules[module_name]

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import VIEW_NAMES  # noqa: E402
from skin_and_bones_forge.projection import cleanup_temporary_data  # noqa: E402
from skin_and_bones_forge.projection.source_processing import (  # noqa: E402
    get_warped_atlas,
)

skin_and_bones_forge.register()
scene = bpy.context.scene
settings = scene.sbf_settings
if settings.target_object is None:
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"Expected one target mesh, found {len(meshes)}")
    settings.target_object = meshes[0]

if args.render_original:
    cleanup_temporary_data(
        bpy.context,
        settings.target_object,
        settings.production_material,
    )
    settings.proof_render_dir = str(output_dir / "original_proofs")
    settings.proof_resolution = args.proof_resolution
    original_result = bpy.ops.sbf.render_verification()
    if "FINISHED" not in original_result:
        raise RuntimeError(
            "Original verification render failed: "
            f"{original_result}; {settings.status_message}"
        )

def _image_summary(image):
    if image is None:
        return None
    values = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(values)
    channels = max(int(image.channels), 1)
    alpha = values[3::channels] if channels >= 4 else numpy.ones(len(values) // channels)
    return {
        "name": image.name,
        "filepath": image.filepath,
        "size": list(image.size),
        "has_data": bool(image.has_data),
        "alpha_max": float(alpha.max()) if len(alpha) else 0.0,
        "alpha_visible_fraction": float((alpha > 1.0e-8).mean()) if len(alpha) else 0.0,
        "rgb_max": float(values.reshape((-1, channels))[:, : min(3, channels)].max())
        if len(values)
        else 0.0,
    }


before = {}
for name in VIEW_NAMES:
    view = getattr(settings, name)
    if not view.enabled or view.image is None:
        continue
    before[name] = {
        "original": _image_summary(view.image),
        "cleaned": _image_summary(view.cleaned_image),
        "confidence": _image_summary(view.source_confidence_image),
        "cleaned_fingerprint": view.cleaned_fingerprint,
        "landmarks_valid": bool(view.body_landmarks_valid),
        "landmark_image_name": view.body_landmark_image_name,
    }

try:
    result = bpy.ops.sbf.best_preview()
except RuntimeError as exc:
    (output_dir / "refresh_failure.json").write_text(
        json.dumps(
            {
                "error": str(exc),
                "status": settings.status_message,
                "before": before,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    raise
if "FINISHED" not in result:
    raise RuntimeError(f"Best preview failed: {result}; {settings.status_message}")

processed = {}
for name in VIEW_NAMES:
    view = getattr(settings, name)
    if not view.enabled or view.image is None:
        continue
    image, metadata = get_warped_atlas(view)
    image.filepath_raw = str(output_dir / f"{name}_processed.png")
    image.file_format = "PNG"
    image.save()
    processed[name] = {
        "image": image.name,
        "size": list(image.size),
        "metadata": metadata,
        "pose": json.loads(view.pose_mismatch_details_json or "{}"),
    }

settings.proof_render_dir = str(output_dir / "proofs")
settings.proof_resolution = args.proof_resolution
result = bpy.ops.sbf.render_verification()
if "FINISHED" not in result:
    raise RuntimeError(
        f"Verification render failed: {result}; {settings.status_message}"
    )

bake_result = None
if args.bake:
    settings.texture_size = "2048"
    settings.output_image_path = str(output_dir / "user_projection_baked_2k.png")
    result = bpy.ops.sbf.bake_final()
    if "FINISHED" not in result:
        raise RuntimeError(f"2K bake failed: {result}; {settings.status_message}")
    settings.proof_render_dir = str(output_dir / "baked_proofs")
    result = bpy.ops.sbf.render_verification()
    if "FINISHED" not in result:
        raise RuntimeError(
            f"Baked verification render failed: {result}; {settings.status_message}"
        )
    bake_result = {
        "path": settings.output_image_path,
        "size": [2048, 2048],
        "uv_strategy": settings.target_object.get("sbf_bake_uv_strategy", ""),
        "smart_fragmentation": settings.target_object.get(
            "sbf_bake_uv_smart_fragmentation", -1.0
        ),
        "topology_fragmentation": settings.target_object.get(
            "sbf_bake_uv_topology_fragmentation", -1.0
        ),
    }

(output_dir / "diagnostic.json").write_text(
    json.dumps(
        {
            "source_pose_state": settings.source_pose_state,
            "source_alignment_status": settings.source_alignment_status,
            "processed": processed,
            "bake": bake_result,
        },
        indent=2,
        sort_keys=True,
    ),
    encoding="utf-8",
)
print(f"USER_PROJECTION_DIAGNOSTIC={output_dir}")
