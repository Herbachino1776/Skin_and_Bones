"""Run the Folsom regression workflow inside Blender.

Example:
    blender reference_assets/folsomsavage_original.blend --background \
      --python scripts/run_reference_test.py -- \
      --output-dir build/reference_test --size 1024
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import bpy


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--size",
        choices=("1024", "2048", "4096", "8192"),
        default="1024",
    )
    parser.add_argument("--render-proofs", action="store_true")
    parser.add_argument("--render-preview", action="store_true")
    parser.add_argument("--proof-resolution", type=int, default=512)
    return parser.parse_args(argv)


def _require_finished(operator_name, result):
    if "FINISHED" not in result:
        raise RuntimeError(f"{operator_name} failed: {result}")


args = _parse_args()
repo_root = args.repo_root.resolve()
output_dir = args.output_dir.resolve()
output_dir.mkdir(parents=True, exist_ok=True)
addon_path = repo_root / "addon"
if str(addon_path) not in sys.path:
    sys.path.insert(0, str(addon_path))

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import (  # noqa: E402
    PROJECTION_UV_PREFIX,
    WEIGHT_ATTRIBUTE_PREFIX,
)


try:
    skin_and_bones_forge.register()
except ValueError:
    pass

started = time.perf_counter()
scene = bpy.context.scene
settings = scene.sbf_settings
mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
if len(mesh_objects) != 1:
    raise RuntimeError(f"Expected one reference mesh, found {len(mesh_objects)}")
target = mesh_objects[0]
mesh = target.data

original = {
    "vertices": len(mesh.vertices),
    "polygons": len(mesh.polygons),
    "uv_layers": [layer.name for layer in mesh.uv_layers],
    "normal_images": [
        node.image.name
        for material in bpy.data.materials
        if material.node_tree
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage"
        and node.image is not None
        and "NORMAL" in f"{node.label} {node.name}".upper()
    ],
}

settings.target_object = target
settings.texture_size = args.size
settings.output_image_path = str(output_dir / "folsomsavage_sbf_base_color.png")
settings.save_blend_path = str(output_dir / "folsomsavage_sbf.blend")
settings.export_glb_path = str(output_dir / "folsomsavage_sbf.glb")
settings.proof_render_dir = str(output_dir / "proof_renders")
settings.proof_resolution = args.proof_resolution
settings.write_manifest = True

_require_finished("load_preset", bpy.ops.sbf.load_preset())
settings.texture_size = args.size
projection_dir = repo_root / "reference_assets" / "projection_views"
for name in ("front", "back", "left", "right"):
    image_path = projection_dir / f"{name}_projection.png"
    if not image_path.exists():
        raise RuntimeError(f"Missing projection fixture: {image_path}")
    _require_finished(
        f"load_{name}_image",
        bpy.ops.sbf.load_view_image(
            view_name=name,
            filepath=str(image_path),
        ),
    )
    image = getattr(settings, name).image
    loaded_path = (
        Path(bpy.path.abspath(image.filepath)).resolve() if image else None
    )
    if loaded_path != image_path:
        raise RuntimeError(f"{name.title()} image picker did not assign its file")

_require_finished("validate", bpy.ops.sbf.validate())
_require_finished("create_preview", bpy.ops.sbf.create_preview())

if args.render_preview:
    settings.proof_render_dir = str(output_dir / "preview_proof_renders")
    _require_finished(
        "render_preview_verification",
        bpy.ops.sbf.render_verification(),
    )
    settings.proof_render_dir = str(output_dir / "proof_renders")

projection_stats = {}
for name in ("front", "back", "left", "right"):
    uv_layer = mesh.uv_layers.get(f"{PROJECTION_UV_PREFIX}{name}")
    if uv_layer is None:
        raise RuntimeError(f"Missing projection UV for {name}")
    uv_values = [item.uv.copy() for item in uv_layer.data]
    attribute = mesh.attributes.get(f"{WEIGHT_ATTRIBUTE_PREFIX}{name}")
    if attribute is None:
        raise RuntimeError(f"Missing weight attribute for {name}")
    values = [item.value for item in attribute.data]
    projection_stats[name] = {
        "positive_corners": sum(1 for value in values if value > 0.0),
        "max_weight": max(values),
        "uv_min": [
            min(value.x for value in uv_values),
            min(value.y for value in uv_values),
        ],
        "uv_max": [
            max(value.x for value in uv_values),
            max(value.y for value in uv_values),
        ],
    }
    if projection_stats[name]["positive_corners"] == 0:
        raise RuntimeError(f"Projection view {name} has no visible weighted corners")

_require_finished("bake_final", bpy.ops.sbf.bake_final())

base_image = settings.last_baked_image
if base_image is None or list(base_image.size) != [int(args.size), int(args.size)]:
    raise RuntimeError("Baked base-color image has the wrong dimensions")
if settings.pack_baked_image and base_image.packed_file is None:
    raise RuntimeError("Baked base-color image was not packed")
if len(mesh.vertices) != original["vertices"]:
    raise RuntimeError("Vertex count changed")
if len(mesh.polygons) != original["polygons"]:
    raise RuntimeError("Polygon count changed")
if [layer.name for layer in mesh.uv_layers] != original["uv_layers"]:
    raise RuntimeError("Production UV layer contract changed")
if any(
    layer.name.startswith(PROJECTION_UV_PREFIX) for layer in mesh.uv_layers
):
    raise RuntimeError("Temporary projection UV layers remain after baking")
if any(
    attribute.name.startswith(WEIGHT_ATTRIBUTE_PREFIX)
    for attribute in mesh.attributes
):
    raise RuntimeError("Temporary weight attributes remain after baking")

_require_finished("save_copy", bpy.ops.sbf.save_copy())
_require_finished("export_glb", bpy.ops.sbf.export_glb())
if args.render_proofs:
    _require_finished(
        "render_verification",
        bpy.ops.sbf.render_verification(),
    )

normal_images_after = [
    node.image.name
    for material in bpy.data.materials
    if material.node_tree
    for node in material.node_tree.nodes
    if node.bl_idname == "ShaderNodeTexImage"
    and node.image is not None
    and "NORMAL" in f"{node.label} {node.name}".upper()
]
if normal_images_after != original["normal_images"]:
    raise RuntimeError("Normal image assignment changed")

result = {
    "status": "PASS",
    "blender_version": bpy.app.version_string,
    "elapsed_seconds": round(time.perf_counter() - started, 3),
    "texture_size": int(args.size),
    "target": target.name,
    "geometry": {
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
    },
    "uv_layers": [layer.name for layer in mesh.uv_layers],
    "normal_images": normal_images_after,
    "projection_stats": projection_stats,
    "outputs": {
        "image": str(Path(settings.output_image_path).resolve()),
        "blend": str(Path(settings.save_blend_path).resolve()),
        "glb": str(Path(settings.export_glb_path).resolve()),
        "proof_dir": (
            str(Path(settings.proof_render_dir).resolve())
            if args.render_proofs
            else None
        ),
    },
}
result_path = output_dir / "reference_test_result.json"
result_path.write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("SBF_REFERENCE_TEST_RESULT")
print(json.dumps(result, indent=2, sort_keys=True))
