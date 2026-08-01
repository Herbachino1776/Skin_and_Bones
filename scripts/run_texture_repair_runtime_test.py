"""Blender 5.1.2 runtime regression for Texture Repair Studio."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import bpy
import numpy as np


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def set_pixels(image, values):
    image.pixels.foreach_set(np.asarray(values, dtype=np.float32).reshape(-1))
    image.update()


def get_pixels(image):
    values = np.empty(int(image.size[0]) * int(image.size[1]) * 4, dtype=np.float32)
    image.pixels.foreach_get(values)
    return values.reshape(int(image.size[1]), int(image.size[0]), 4)


def fingerprint(image):
    return hashlib.sha256(get_pixels(image).tobytes()).hexdigest()


def make_bake(name, size, variant=0.0):
    image = bpy.data.images.new(name, width=size, height=size, alpha=True)
    yy, xx = np.mgrid[:size, :size]
    values = np.empty((size, size, 4), dtype=np.float32)
    values[:] = (0.04, 0.04, 0.04, 1.0)
    uv_x = xx / max(size - 1, 1)
    uv_y = yy / max(size - 1, 1)
    left_leg = (uv_x >= 0.05) & (uv_x <= 0.30) & (uv_y >= 0.05) & (uv_y <= 0.95)
    right_leg = (uv_x >= 0.70) & (uv_x <= 0.95) & (uv_y >= 0.05) & (uv_y <= 0.95)
    hand = (uv_x >= 0.40) & (uv_x <= 0.60) & (uv_y >= 0.60) & (uv_y <= 0.92)
    checker = ((xx + yy) % 2).astype(np.float32) * 0.08
    values[left_leg, 0] = 0.12 + checker[left_leg] + variant
    values[left_leg, 1] = 0.62 + checker[left_leg]
    values[left_leg, 2] = 0.20
    values[right_leg, :3] = (1.0, 1.0, 1.0)
    values[hand, :3] = (0.95, 0.05, 0.05)
    set_pixels(image, np.clip(values, 0.0, 1.0))
    return image


args = parse_args()
repo_root = args.repo_root.resolve()
output_dir = args.output_dir.resolve()
output_dir.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(repo_root / "addon"))

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.baking.core import _bind_production_texture_uvs  # noqa: E402
from skin_and_bones_forge.baking.repair_service import (  # noqa: E402
    apply_repair_strokes,
    atlas_data,
    begin_repair_session,
    clear_repairs,
    commit_final_base_color,
    detect_color_seams,
    heal_seams,
    repair_images,
    smart_fill,
    validate_repair_for_delivery,
)
from skin_and_bones_forge.constants import (  # noqa: E402
    BASE_COLOR_UV_NAME,
    BODY_PART_ATTRIBUTE_PREFIX,
    ORIGINAL_MATERIAL_PROPERTY,
    ORIGINAL_SLOT_PROPERTY,
    ORIGINAL_UV_PROPERTY,
    PREVIEW_MATERIAL_PREFIX,
    REPAIR_BAKED_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_MASK_IMAGE,
    REPAIR_PREVIEW_MATERIAL_PROPERTY,
    REPAIR_PREVIEW_SLOT_PROPERTY,
    TEMPORARY_PROPERTY,
    WEIGHT_ATTRIBUTE_PREFIX,
)
from skin_and_bones_forge.export.core import export_glb  # noqa: E402
from skin_and_bones_forge.projection.body_alignment import BODY_PARTS  # noqa: E402
from skin_and_bones_forge.validation import validate_target  # noqa: E402


skin_and_bones_forge.register()
scene = bpy.context.scene
settings = scene.sbf_settings
size = 128

# Faces 0 and 1 share the real geometric edge (0, 2), but occupy separated UV
# islands. Face 2 is an unrelated same-material arm/hand donor.
mesh = bpy.data.meshes.new("SBF_RepairRuntimeMesh")
mesh.from_pydata(
    (
        (-1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 1.0),
        (-1.0, 0.0, 1.0),
        (1.0, 0.0, 0.4),
        (1.4, 0.0, 0.4),
        (1.2, 0.0, 0.8),
    ),
    (),
    ((0, 1, 2), (0, 2, 3), (4, 5, 6)),
)
target = bpy.data.objects.new("SBF_RepairRuntimeTarget", mesh)
scene.collection.objects.link(target)
target.select_set(True)
bpy.context.view_layer.objects.active = target

original_uv = mesh.uv_layers.new(name="OriginalUV")
base_uv = mesh.uv_layers.new(name=BASE_COLOR_UV_NAME)
face_uvs = (
    ((0.05, 0.05), (0.30, 0.05), (0.30, 0.95)),
    ((0.70, 0.05), (0.95, 0.95), (0.70, 0.95)),
    ((0.40, 0.60), (0.60, 0.60), (0.50, 0.92)),
)
for polygon, uvs in zip(mesh.polygons, face_uvs, strict=True):
    for loop_index, uv in zip(polygon.loop_indices, uvs, strict=True):
        original_uv.data[loop_index].uv = uv
        base_uv.data[loop_index].uv = uv
base_uv.active_render = True
mesh.uv_layers.active = base_uv

owners = (
    BODY_PARTS.index("left_leg"),
    BODY_PARTS.index("right_leg"),
    BODY_PARTS.index("left_arm"),
)
for part_index, part in enumerate(BODY_PARTS):
    attribute = mesh.attributes.new(
        name=f"{BODY_PART_ATTRIBUTE_PREFIX}{part}",
        type="FLOAT",
        domain="CORNER",
    )
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            attribute.data[loop_index].value = (
                1.0 if owners[polygon.index] == part_index else 0.0
            )
projection_weight = mesh.attributes.new(
    name=f"{WEIGHT_ATTRIBUTE_PREFIX}front", type="FLOAT", domain="CORNER"
)
for item in projection_weight.data:
    item.value = 1.0

material = bpy.data.materials.new("SBF_RepairRuntimeMaterial")
material.use_nodes = True
nodes = material.node_tree.nodes
links = material.node_tree.links
principled = nodes.get("Principled BSDF")
base_node = nodes.new("ShaderNodeTexImage")
base_node.name = "BASE COLOR"
original_image = bpy.data.images.new(
    "RuntimeOriginalBase", width=4, height=4, alpha=True
)
original_image.generated_color = (0.2, 0.2, 0.2, 1.0)
base_node.image = original_image
links.new(base_node.outputs["Color"], principled.inputs["Base Color"])
normal_image = bpy.data.images.new(
    "RuntimeNormal", width=4, height=4, alpha=True
)
normal_image.colorspace_settings.name = "Non-Color"
normal_texture = nodes.new("ShaderNodeTexImage")
normal_texture.name = "NORMAL MAP IMAGE"
normal_texture.image = normal_image
normal_map = nodes.new("ShaderNodeNormalMap")
links.new(normal_texture.outputs["Color"], normal_map.inputs["Color"])
links.new(normal_map.outputs["Normal"], principled.inputs["Normal"])
target.data.materials.append(material)

settings.target_object = target
settings.production_material = material
settings.target_uv = "OriginalUV"
settings.base_color_node = base_node.name
settings.normal_map_node = normal_map.name
settings.texture_size = (
    str(size) if str(size) in {"1024", "2048", "4096", "8192"} else "1024"
)
settings.output_image_path = str(output_dir / "texture_repair_final.png")
settings.export_glb_path = str(output_dir / "texture_repair.glb")
settings.save_blend_path = str(output_dir / "texture_repair.blend")
settings.pack_baked_image = True
settings.repair_unresolved_threshold = 0
info = validate_target(bpy.context, settings)
normal_before = normal_texture.image
normal_uv_before = settings.target_uv

raw = make_bake("SBF_RepairRuntimeBakeWork", size)
session = begin_repair_session(
    bpy.context,
    info,
    settings,
    raw,
    Path(settings.output_image_path),
    BASE_COLOR_UV_NAME,
)
_bind_production_texture_uvs(info, BASE_COLOR_UV_NAME)
target.material_slots[0].material = material
raw_hash = fingerprint(session["baked"])
if len(json.loads(target["sbf_repair_seam_pairs"])) != 1:
    raise RuntimeError("Runtime mesh did not produce one real shared-edge UV seam pair")

# Follow the real operator path from an active projection preview. This is the
# state that previously left production characters fully pink after repair.
projection_preview = bpy.data.materials.new(
    f"{PREVIEW_MATERIAL_PREFIX}RuntimeProjection"
)
projection_preview.use_nodes = True
projection_preview[TEMPORARY_PROPERTY] = True
target[ORIGINAL_MATERIAL_PROPERTY] = material.name
target[ORIGINAL_SLOT_PROPERTY] = 0
target[ORIGINAL_UV_PROPERTY] = "OriginalUV"
target.material_slots[0].material = projection_preview

if bpy.ops.sbf.texture_display(display="UNLIT_FINAL") != {"FINISHED"}:
    raise RuntimeError("Repair inspection failed from a projection preview")
if not target.material_slots[0].material.name.startswith("SBF_Preview_TextureRepair_"):
    raise RuntimeError("Unlit final inspection did not use an owned preview material")
if bpy.ops.sbf.texture_display(display="UNLIT_FINAL") != {"FINISHED"}:
    raise RuntimeError("Repeated repair inspection failed after target revalidation")
if len(
    [
        item
        for item in bpy.data.materials
        if item.name.startswith("SBF_Preview_TextureRepair_")
    ]
) != 1:
    raise RuntimeError("Repeated repair preview leaked materials")
if bpy.ops.sbf.texture_display(display="FINAL") != {"FINISHED"}:
    raise RuntimeError("Final display failed to leave the repair preview")
if target.material_slots[0].material != material:
    raise RuntimeError("Final display did not restore the production material")
if any(
    key in target
    for key in (REPAIR_PREVIEW_SLOT_PROPERTY, REPAIR_PREVIEW_MATERIAL_PROPERTY)
):
    raise RuntimeError("Final display retained stale repair-preview ownership")
if target.get(ORIGINAL_MATERIAL_PROPERTY, "") != material.name:
    raise RuntimeError("Repair preview destroyed the projection preview's ownership state")

# Geometry-aware Seam Heal must reduce the paired-edge metric and leave the raw
# bake untouched.
settings.repair_seam_detection_threshold = 0.001
settings.repair_seam_max_correction = 1.5
detect = detect_color_seams(info, settings)
seam_metrics = heal_seams(info, settings, all_safe=True)
if not seam_metrics["after"] < seam_metrics["before"]:
    raise RuntimeError("Seam Heal did not reduce the measured shared-edge error")
if fingerprint(repair_images(target)["baked"]) != raw_hash:
    raise RuntimeError("Seam Heal changed the original bake")
clear_repairs(info, settings)

# Clone across a 90-degree rotated target basis. Symmetry explicitly permits
# the opposite semantic leg while same-part/material restrictions stay enabled.
settings.repair_mode = "CLONE"
settings.repair_symmetry = True
settings.repair_brush_size = 8
source = {
    "uv": [0.18, 0.35],
    "basis": [1.0, 0.0, 0.0, 1.0],
    "part": BODY_PARTS.index("left_leg"),
    "part_name": "left_leg",
    "material": 0,
}
target_sample = {
    "uv": [0.82, 0.35],
    "basis": [0.0, -1.0, 1.0, 0.0],
    "part": BODY_PARTS.index("right_leg"),
    "part_name": "right_leg",
    "material": 0,
}
# Service writes are transactional: a later singular target invalidates the
# whole in-memory stroke before any Blender image is synchronized.
rollback_hash = fingerprint(repair_images(target)["corrections"])
invalid_target = dict(target_sample)
invalid_target["basis"] = [0.0, 0.0, 0.0, 0.0]
try:
    apply_repair_strokes(info, settings, source, [target_sample, invalid_target])
except ValueError:
    pass
else:
    raise RuntimeError("Invalid stroke did not fail transactionally")
if fingerprint(repair_images(target)["corrections"]) != rollback_hash:
    raise RuntimeError("Failed stroke did not roll back correction pixels")
clone_metrics = apply_repair_strokes(info, settings, source, [target_sample])
if clone_metrics["changed"] <= 0:
    raise RuntimeError("Surface-aware Clone changed no pixels")
if fingerprint(repair_images(target)["baked"]) != raw_hash:
    raise RuntimeError("Clone changed the original bake")

settings.repair_mode = "HEAL"
target_sample["uv"] = [0.84, 0.60]
heal_metrics = apply_repair_strokes(info, settings, source, [target_sample])
if heal_metrics["changed"] <= 0:
    raise RuntimeError("Heal changed no pixels")
clear_repairs(info, settings)

# Smart Fill is restricted to the selected right-leg face and can use only the
# opposite left leg. The bright red unrelated arm/hand region is never eligible.
for polygon in mesh.polygons:
    polygon.select = polygon.index == 1
settings.repair_smart_fill_target = "SELECTED_FACES"
settings.repair_source_policy = "OPPOSITE_SYMMETRIC_PART"
smart_metrics = smart_fill(info, settings)
if smart_metrics["filled"] <= 0 or smart_metrics["unresolved"] != 0:
    raise RuntimeError(f"Masked Smart Fill failed: {smart_metrics}")
owned = repair_images(target)
correction_values = get_pixels(owned["corrections"])
mask_values = get_pixels(owned["mask"])[:, :, 0]
yy, xx = np.mgrid[:size, :size]
filled_right = (mask_values > 0.99) & (xx >= int(size * 0.68))
mean_right = correction_values[filled_right, :3].mean(axis=0)
if not (mean_right[1] > mean_right[0] * 2.0 and mean_right[1] > mean_right[2]):
    raise RuntimeError(f"Smart Fill used an unrelated red hand donor: {mean_right}")

# A correction commit must also escape a stale projection preview while
# retaining every correction byte. This guards the user's recovered file path.
correction_hash_before_preview_exit = fingerprint(repair_images(target)["corrections"])
mask_hash_before_preview_exit = fingerprint(repair_images(target)["mask"])
target.material_slots[0].material = projection_preview
fresh_info = validate_target(bpy.context, settings)
_final, _path, preview_exit_metrics = commit_final_base_color(fresh_info, settings)
if target.material_slots[0].material != material:
    raise RuntimeError("Correction commit left the projection preview material active")
if fingerprint(repair_images(target)["corrections"]) != correction_hash_before_preview_exit:
    raise RuntimeError("Projection-preview exit changed correction pixels")
if fingerprint(repair_images(target)["mask"]) != mask_hash_before_preview_exit:
    raise RuntimeError("Projection-preview exit changed the correction mask")
if preview_exit_metrics["correction_pixels"] <= 0:
    raise RuntimeError("Projection-preview exit discarded active corrections")

# Compatible rebake must replace the raw layer while preserving correction work.
correction_hash_before = fingerprint(repair_images(target)["corrections"])
second_raw = make_bake("SBF_RepairRuntimeBakeWork2", size, variant=0.015)
second = begin_repair_session(
    bpy.context,
    info,
    settings,
    second_raw,
    Path(settings.output_image_path),
    BASE_COLOR_UV_NAME,
)
if not second["preserved"]:
    raise RuntimeError("Compatible rebake did not preserve correction layers")
if fingerprint(repair_images(target)["corrections"]) != correction_hash_before:
    raise RuntimeError("Compatible rebake changed correction pixels")
_bind_production_texture_uvs(info, BASE_COLOR_UV_NAME)
target.material_slots[0].material = material
commit_final_base_color(info, settings)
validation_metrics = validate_repair_for_delivery(info, settings)

if base_node.image.name != REPAIR_FINAL_IMAGE:
    raise RuntimeError("Production material does not use SBF_BaseColor_Final")
if normal_texture.image != normal_before or settings.target_uv != normal_uv_before:
    raise RuntimeError("Normal/PBR UV or image binding changed")
base_uv_node = nodes.get("SBF_BaseColorUVCoordinates")
original_uv_node = nodes.get("SBF_OriginalUVCoordinates")
if base_uv_node is None or base_uv_node.uv_map != BASE_COLOR_UV_NAME:
    raise RuntimeError("Final base color lost its dedicated production UV")
if original_uv_node is None or original_uv_node.uv_map != "OriginalUV":
    raise RuntimeError("Normal/PBR maps lost their original UV")
for name in (
    REPAIR_BAKED_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_MASK_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
):
    matches = [image for image in bpy.data.images if image.name == name]
    if len(matches) != 1:
        raise RuntimeError(f"Repeated repair session leaked or duplicated {name}")
    if matches[0].packed_file is None:
        raise RuntimeError(f"Owned repair image is not packed: {name}")
if not Path(settings.output_image_path).is_file():
    raise RuntimeError("Committed final PNG was not saved")

target["sbf_processed"] = True
glb_path, _manifest = export_glb(bpy.context, info, settings)
glb_bytes = Path(glb_path).read_bytes()
magic, version, _length = struct.unpack_from("<4sII", glb_bytes, 0)
if magic != b"glTF" or version != 2:
    raise RuntimeError("Texture Repair runtime export is not a valid GLB 2 file")
json_length, json_type = struct.unpack_from("<I4s", glb_bytes, 12)
if json_type != b"JSON":
    raise RuntimeError("Texture Repair GLB does not start with a JSON chunk")
glb_json = json.loads(glb_bytes[20 : 20 + json_length].decode("utf-8"))
base_texture = glb_json["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]
texture = glb_json["textures"][base_texture["index"]]
exported_image = glb_json["images"][texture["source"]]
if exported_image.get("mimeType") != "image/png" or "bufferView" not in exported_image:
    raise RuntimeError(
        f"GLB did not embed the final PNG: {exported_image}"
    )
binary_header = 20 + json_length
_binary_length, binary_type = struct.unpack_from("<I4s", glb_bytes, binary_header)
if binary_type != b"BIN\x00":
    raise RuntimeError("Texture Repair GLB is missing its binary image chunk")
binary_start = binary_header + 8
view = glb_json["bufferViews"][exported_image["bufferView"]]
image_start = binary_start + int(view.get("byteOffset", 0))
image_end = image_start + int(view["byteLength"])
embedded_png = glb_bytes[image_start:image_end]
saved_png = Path(settings.output_image_path).read_bytes()
if hashlib.sha256(embedded_png).digest() != hashlib.sha256(saved_png).digest():
    raise RuntimeError("Packed GLB pixels do not match the committed final PNG")

# A production-UV change is an explicit invalidation boundary. It must create
# empty correction layers rather than applying stale pixels to a changed atlas.
base_uv.data[0].uv.x += 0.01
invalidated_raw = make_bake("SBF_RepairRuntimeBakeWork3", size, variant=0.02)
invalidated = begin_repair_session(
    bpy.context,
    info,
    settings,
    invalidated_raw,
    Path(settings.output_image_path),
    BASE_COLOR_UV_NAME,
)
if invalidated["preserved"]:
    raise RuntimeError("Production UV change did not invalidate corrections")
if np.count_nonzero(get_pixels(repair_images(target)["mask"])[:, :, 0]) != 0:
    raise RuntimeError("Invalidated correction mask was not cleared")

# Delivery gates reject both unresolved pixels and known diagnostic colors.
invalidated_images = repair_images(target)
coverage = atlas_data(target)["coverage"]
test_y, test_x = np.argwhere(coverage)[0]
gate_corrections = get_pixels(invalidated_images["corrections"])
gate_mask = get_pixels(invalidated_images["mask"])
gate_corrections[test_y, test_x] = (1.0, 1.0, 1.0, 1.0)
gate_mask[test_y, test_x] = (1.0, 1.0, 1.0, 1.0)
set_pixels(invalidated_images["corrections"], gate_corrections)
set_pixels(invalidated_images["mask"], gate_mask)
commit_final_base_color(info, settings)
try:
    validate_repair_for_delivery(info, settings)
except RuntimeError as exc:
    if "unresolved" not in str(exc).lower():
        raise
else:
    raise RuntimeError("Delivery did not block an unresolved final pixel")
gate_corrections[test_y, test_x] = (1.0, 0.0, 1.0, 1.0)
set_pixels(invalidated_images["corrections"], gate_corrections)
commit_final_base_color(info, settings)
settings.repair_unresolved_threshold = 10_000_000
try:
    validate_repair_for_delivery(info, settings)
except RuntimeError as exc:
    if "diagnostic" not in str(exc).lower():
        raise
else:
    raise RuntimeError("Delivery did not block a known diagnostic color")

# Delivery validation is the same gate called by Blender copy and GLB export.
result = {
    "status": "PASS",
    "blender": bpy.app.version_string,
    "original_bake_unchanged": True,
    "compatible_rebake_preserved": True,
    "uv_change_invalidated": True,
    "failed_stroke_rolled_back": True,
    "preview_leak_free": True,
    "projection_preview_exit_safe": True,
    "projection_preview_corrections_preserved": True,
    "delivery_gates_blocked": True,
    "clone": clone_metrics,
    "heal": heal_metrics,
    "smart_fill": smart_metrics,
    "seam_detect": detect,
    "seam_heal": seam_metrics,
    "delivery": validation_metrics,
    "normal_pbr_uv_preserved": True,
    "owned_images": [
        REPAIR_BAKED_IMAGE,
        REPAIR_CORRECTION_IMAGE,
        REPAIR_MASK_IMAGE,
        REPAIR_FINAL_IMAGE,
        REPAIR_CLASSIFICATION_IMAGE,
    ],
    "output_png": settings.output_image_path,
    "output_glb": str(glb_path),
    "glb_final_image": exported_image.get("name"),
    "glb_png_matches_final": True,
}
(output_dir / "texture_repair_runtime_result.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print("SBF_TEXTURE_REPAIR_RUNTIME_RESULT")
print(json.dumps(result, indent=2, sort_keys=True))
