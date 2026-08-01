"""Run the Folsom regression workflow inside Blender.

Example:
    blender reference_assets/folsomsavage_original.blend --background \
      --python scripts/run_reference_test.py -- \
      --output-dir build/reference_test --size 1024
"""

from __future__ import annotations

import argparse
from array import array
import hashlib
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
    parser.add_argument("--render-original", action="store_true")
    parser.add_argument("--require-diagonals", action="store_true")
    parser.add_argument("--cardinals-only", action="store_true")
    parser.add_argument("--exercise-landmarks", action="store_true")
    parser.add_argument("--use-best-preview", action="store_true")
    parser.add_argument("--front-left-head-offset-x", type=float)
    parser.add_argument("--front-right-head-offset-x", type=float)
    parser.add_argument("--source-edge-padding", type=float)
    parser.add_argument("--disable-black-key", action="store_true")
    parser.add_argument("--proof-resolution", type=int, default=512)
    parser.add_argument(
        "--prepare-spar3d",
        action="store_true",
        help="Run exact-weld intake on the selected fixture before projection.",
    )
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

existing_addon = sys.modules.get("skin_and_bones_forge")
if existing_addon is not None:
    try:
        existing_addon.unregister()
    except (AttributeError, RuntimeError):
        pass
    for module_name in tuple(sys.modules):
        if module_name == "skin_and_bones_forge" or module_name.startswith(
            "skin_and_bones_forge."
        ):
            del sys.modules[module_name]

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import (  # noqa: E402
    BASE_COLOR_UV_NAME,
    BODY_PART_ID_ATTRIBUTE,
    CARDINAL_VIEW_NAMES,
    PREVIEW_MATERIAL_PREFIX,
    PROJECTION_UV_PREFIX,
    REPAIR_BAKED_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_MASK_IMAGE,
    VIEW_NAMES,
    WEIGHT_ATTRIBUTE_PREFIX,
)
from skin_and_bones_forge.projection.body_alignment import BODY_PARTS  # noqa: E402
from skin_and_bones_forge.projection.source_processing import (  # noqa: E402
    generate_warped_sources,
    get_warped_atlas,
    get_warped_images,
    process_all_source_plates,
    validate_preview_source_parity,
)
from skin_and_bones_forge.projection.alignment import (  # noqa: E402
    _alpha_bounds,
    apply_face_calibration,
)

loaded_addon_path = Path(skin_and_bones_forge.__file__).resolve()
if not loaded_addon_path.is_relative_to(addon_path):
    raise RuntimeError(f"Regression imported the wrong add-on: {loaded_addon_path}")


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
intake_result = None
if args.prepare_spar3d:
    from skin_and_bones_forge.intake.core import prepare_selected_spar3d

    settings.intake_target_height = 1.50
    # The dedicated intake matrix proves protected-source behavior. Avoid
    # carrying a second hidden mesh into this texture-delivery regression.
    settings.intake_preserve_raw = False
    intake_report, target = prepare_selected_spar3d(bpy.context, target)
    if intake_report["readiness"] != "READY_FOR_SKIN":
        raise RuntimeError(
            f"SPAR3D preparation was not ready: {intake_report['readiness']}"
        )
    intake_result = {
        "readiness": intake_report["readiness"],
        "raw_vertices": intake_report["raw"]["counts"]["vertices"],
        "clean_vertices": intake_report["welded"]["counts"]["vertices"],
        "raw_components": intake_report["raw"]["connected_components"],
        "clean_components": intake_report["welded"]["connected_components"],
        "uv_preserved": intake_report["proof"]["uv_values_preserved"],
        "normal_preserved": intake_report["proof"]["corner_normals_preserved"],
        "watertight": intake_report["welded"]["watertight"],
        "final_height": intake_report["normalization"]["final_height"],
    }
mesh = target.data

original = {
    "vertices": len(mesh.vertices),
    "polygons": len(mesh.polygons),
    "uv_layers": [layer.name for layer in mesh.uv_layers],
    "uv_coordinates": {
        layer.name: [tuple(item.uv) for item in layer.data]
        for layer in mesh.uv_layers
    },
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
loaded_source_names = []
for name in VIEW_NAMES:
    if args.cardinals_only and name not in CARDINAL_VIEW_NAMES:
        continue
    image_path = projection_dir / f"{name}_projection.png"
    if not image_path.exists():
        if name in CARDINAL_VIEW_NAMES or args.require_diagonals:
            raise RuntimeError(f"Missing projection fixture: {image_path}")
        continue
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
    loaded_source_names.append(name)


def image_fingerprint(image):
    values = array("f", [0.0]) * (image.size[0] * image.size[1] * image.channels)
    image.pixels.foreach_get(values)
    return hashlib.sha256(values.tobytes()).hexdigest()


original_source_fingerprints = {
    name: image_fingerprint(getattr(settings, name).image)
    for name in loaded_source_names
}

landmark_regression = None
if args.exercise_landmarks:
    if "front" not in loaded_source_names or "right" not in loaded_source_names:
        raise RuntimeError("Landmark regression needs Front and Right sources")

    def set_landmarks(name, horizontal_shift=0.0, profile=False):
        view = getattr(settings, name)
        _bounds, head_bounds, _key = _alpha_bounds(
            view.image,
            threshold=max(0.02, view.alpha_threshold),
            head_threshold=settings.head_threshold,
        )
        minimum_x, minimum_y, maximum_x, maximum_y = head_bounds
        width = maximum_x - minimum_x
        height = maximum_y - minimum_y
        center_x = (minimum_x + maximum_x) * 0.5 + width * horizontal_shift
        view.eye_image_left = (
            center_x - width * 0.15,
            minimum_y + height * 0.66,
        )
        view.eye_image_right = (
            center_x + width * 0.15,
            minimum_y + height * 0.66,
        )
        view.mouth_image_left = (
            center_x - width * 0.08,
            minimum_y + height * 0.40,
        )
        view.mouth_image_right = (
            center_x + width * 0.08,
            minimum_y + height * 0.40,
        )
        view.facial_landmarks_set = (
            not profile,
            True,
            not profile,
            True,
        )
        view.facial_landmarks_skipped = (
            profile,
            False,
            profile,
            False,
        )

    set_landmarks("front")
    set_landmarks("right", horizontal_shift=0.08, profile=True)
    front_result = apply_face_calibration(settings, "front")
    right_view = settings.right
    body_before = (
        right_view.scale,
        right_view.horizontal_scale,
        right_view.offset_x,
        right_view.offset_y,
    )
    right_result = apply_face_calibration(settings, "right")
    first_head_transform = (
        right_view.head_scale,
        right_view.head_horizontal_scale,
        right_view.head_offset_x,
        right_view.head_offset_y,
    )
    apply_face_calibration(settings, "right")
    second_head_transform = (
        right_view.head_scale,
        right_view.head_horizontal_scale,
        right_view.head_offset_x,
        right_view.head_offset_y,
    )
    if first_head_transform != second_head_transform:
        raise RuntimeError("Facial calibration reapply is not idempotent")
    if body_before != (
        right_view.scale,
        right_view.horizontal_scale,
        right_view.offset_x,
        right_view.offset_y,
    ):
        raise RuntimeError("Facial calibration altered body alignment")
    if abs(right_result["delta_x"]) < 1.0e-5:
        raise RuntimeError("Facial calibration did not correct the shifted face")
    landmark_regression = {
        "front": front_result,
        "right": right_result,
        "head_transform": first_head_transform,
        "body_unchanged": True,
        "idempotent": True,
    }

for name in ("front_left", "front_right"):
    override = getattr(args, f"{name}_head_offset_x")
    if override is not None and name in loaded_source_names:
        getattr(settings, name).head_offset_x = override
if args.disable_black_key:
    for name in loaded_source_names:
        getattr(settings, name).key_black_background = False
if args.source_edge_padding is not None:
    settings.source_edge_padding = args.source_edge_padding

_require_finished("validate", bpy.ops.sbf.validate())
if args.render_original:
    settings.proof_render_dir = str(output_dir / "original_proof_renders")
    _require_finished(
        "render_original_verification",
        bpy.ops.sbf.render_verification(),
    )
    settings.proof_render_dir = str(output_dir / "proof_renders")

if args.use_best_preview:
    _require_finished("best_preview", bpy.ops.sbf.best_preview())
    settings.texture_size = args.size
else:
    _require_finished("create_preview", bpy.ops.sbf.create_preview())

preview_material = next(
    (
        slot.material
        for slot in target.material_slots
        if slot.material is not None
        and slot.material.name.startswith(PREVIEW_MATERIAL_PREFIX)
    ),
    None,
)
if preview_material is None or preview_material.node_tree is None:
    raise RuntimeError("Preview material was not assigned")

source_doctor = {}
cleaned_before_reuse = {}
for name in loaded_source_names:
    view = getattr(settings, name)
    if view.cleaned_image is None or view.cleaned_original_name != view.image.name:
        raise RuntimeError(f"{name} cleaned source was not created from its original")
    if tuple(view.cleaned_image.size) != tuple(view.image.size):
        raise RuntimeError(f"{name} cleaned source size differs from its original")
    warped = get_warped_images(view)
    atlas, atlas_metadata = get_warped_atlas(view)
    if set(warped) != set(BODY_PARTS) or set(atlas_metadata["parts"]) != set(BODY_PARTS):
        raise RuntimeError(f"{name} does not have all bounded atlas regions")
    for node_name in (f"SBF_WarpAtlas_{name}", f"SBF_WarpAtlasSafe_{name}"):
        node = preview_material.node_tree.nodes.get(node_name)
        if node is None or node.image != atlas:
            raise RuntimeError(f"Preview did not use {name} processed atlas")
    metrics = json.loads(view.source_doctor_metrics_json)
    if metrics["contamination_after"] > metrics["contamination_before"] + 1.0e-8:
        raise RuntimeError(f"{name} Source Plate Doctor increased contamination")
    source_doctor[name] = {
        **metrics,
        "pose_status": view.pose_mismatch_status,
        "worst_part": view.pose_mismatch_worst_part,
        "mismatch_before": view.pose_mismatch_error,
        "mismatch_after": 0.0,
        "warped_parts": sorted(warped),
        "warp_atlas_size": list(atlas.size),
    }
    cleaned_before_reuse[name] = (
        view.cleaned_image.name,
        image_fingerprint(view.cleaned_image),
    )
    if image_fingerprint(view.image) != original_source_fingerprints[name]:
        raise RuntimeError(f"{name} original source changed during processing")

reuse_results = process_all_source_plates(settings)
if any(item["changed"] for item in reuse_results.values()):
    raise RuntimeError("Repeated Source Plate Doctor processing was not idempotent")
for name, (cleaned_name, cleaned_fingerprint) in cleaned_before_reuse.items():
    view = getattr(settings, name)
    if view.cleaned_image.name != cleaned_name or image_fingerprint(view.cleaned_image) != cleaned_fingerprint:
        raise RuntimeError(f"{name} cleaned source was not reused idempotently")

owner_id = mesh.attributes.get(BODY_PART_ID_ATTRIBUTE)
if owner_id is None:
    raise RuntimeError("Missing compact body-part ownership ID")
for polygon in mesh.polygons:
    values = {round(owner_id.data[index].value, 6) for index in polygon.loop_indices}
    if len(values) != 1:
        raise RuntimeError("Body-part ownership interpolates across one polygon")
    value = next(iter(values))
    if value != round(value) or not 0 <= int(value) < len(BODY_PARTS):
        raise RuntimeError("A polygon has an invalid body-part ownership ID")

validate_preview_source_parity(preview_material, settings)
preview_textures = [
    node for node in preview_material.node_tree.nodes
    if node.bl_idname == "ShaderNodeTexImage"
]
preview_attributes = {
    node.attribute_name
    for node in preview_material.node_tree.nodes
    if node.bl_idname == "ShaderNodeAttribute" and node.attribute_name
}
preview_attributes.update(
    node.uv_map
    for node in preview_material.node_tree.nodes
    if node.bl_idname == "ShaderNodeUVMap" and node.uv_map
)
if len(preview_textures) > 13 or len(preview_attributes) > 12:
    raise RuntimeError("Projection preview exceeds the production GPU shader budget")

# Runtime-proof the severe contradiction status without changing owned images.
front_metadata_before = settings.front.body_landmarks_json
front_metadata = json.loads(front_metadata_before)
shoulder = front_metadata["points"]["shoulder_left"]
front_metadata["points"]["elbow_left"] = [shoulder[0] - 0.01, shoulder[1] + 0.20]
front_metadata["points"]["wrist_left"] = [shoulder[0] + 0.01, shoulder[1] + 0.30]
front_metadata["points"]["hand_left"] = [shoulder[0], shoulder[1] + 0.38]
settings.front.body_landmarks_json = json.dumps(front_metadata, sort_keys=True, separators=(",", ":"))
try:
    generate_warped_sources(bpy.context, settings)
except RuntimeError as exc:
    if "SOURCE_POSE_REVIEW_REQUIRED" not in str(exc):
        raise
else:
    raise RuntimeError("Severe pose contradiction did not block projection")
finally:
    settings.front.body_landmarks_json = front_metadata_before
    settings.source_pose_state = "READY"

front_view = settings.front
front_uv = mesh.uv_layers.get(f"{PROJECTION_UV_PREFIX}front")
front_uv_before = [item.uv.copy() for item in front_uv.data]
original_offset = front_view.offset_x
front_view.offset_x = original_offset + 0.037
offset_node = preview_material.node_tree.nodes.get("SBF_UVOffset_front")
if offset_node is None:
    raise RuntimeError("Live front alignment node is missing")
expected_translation = (
    0.5
    + front_view.offset_x
    - (-1.0 if front_view.flip_x else 1.0)
    * 0.5
    / max(front_view.scale * front_view.horizontal_scale, 1.0e-6)
)
if abs(offset_node.inputs[1].default_value[0] - expected_translation) > 1.0e-6:
    raise RuntimeError("Live alignment did not update the preview shader")
if any(
    (before - after.uv).length > 1.0e-8
    for before, after in zip(front_uv_before, front_uv.data, strict=True)
):
    raise RuntimeError("Live alignment rebuilt or altered projection UVs")
front_view.offset_x = original_offset
original_head_offset = front_view.head_offset_x
front_view.head_offset_x = original_head_offset + 0.019
head_offset_node = preview_material.node_tree.nodes.get(
    "SBF_HeadUVOffset_front"
)
if head_offset_node is None:
    raise RuntimeError("Live head landmark alignment node is missing")
expected_head_translation = (
    0.5
    + front_view.head_offset_x
    - 0.5
    / max(
        front_view.head_scale * front_view.head_horizontal_scale,
        1.0e-6,
    )
)
if (
    abs(
        head_offset_node.inputs[1].default_value[0]
        - expected_head_translation
    )
    > 1.0e-6
):
    raise RuntimeError("Live head alignment did not update the preview shader")
front_view.head_offset_x = original_head_offset
original_head_sharpness = settings.head_blend_sharpness
settings.head_blend_sharpness = original_head_sharpness + 0.5
head_confidence_node = preview_material.node_tree.nodes.get(
    "SBF_HeadConfidence_front"
)
if (
    head_confidence_node is None
    or abs(
        head_confidence_node.inputs[1].default_value
        - settings.head_blend_sharpness
    )
    > 1.0e-6
):
    raise RuntimeError("Head blend sharpness did not update live")
settings.head_blend_sharpness = original_head_sharpness

if args.render_preview:
    settings.proof_render_dir = str(output_dir / "preview_proof_renders")
    _require_finished(
        "render_preview_verification",
        bpy.ops.sbf.render_verification(),
    )
    preview_path = Path(settings.proof_render_dir) / "sbf_verify_front.png"
    if not preview_path.is_file():
        raise RuntimeError("Projection preview proof render was not created")
    preview_image = bpy.data.images.load(str(preview_path), check_existing=False)
    try:
        preview_pixels = array("f", [0.0]) * len(preview_image.pixels)
        preview_image.pixels.foreach_get(preview_pixels)
        opaque = magenta = 0
        for index in range(0, len(preview_pixels), preview_image.channels):
            red, green, blue, alpha = preview_pixels[index : index + 4]
            if alpha <= 0.05:
                continue
            opaque += 1
            if red > 0.8 and green < 0.2 and blue > 0.8:
                magenta += 1
        if opaque == 0:
            raise RuntimeError("Projection preview proof contains no visible character")
        if magenta / opaque > 0.01:
            raise RuntimeError("Projection preview proof contains Blender error magenta")
    finally:
        bpy.data.images.remove(preview_image)
    settings.proof_render_dir = str(output_dir / "proof_renders")

projection_stats = {}
for name in loaded_source_names:
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

head_mask = mesh.attributes.get(f"{WEIGHT_ATTRIBUTE_PREFIX}head_mask")
if head_mask is None:
    raise RuntimeError("Head identity mask is missing")
locked_head_corners = [
    index
    for index, item in enumerate(head_mask.data)
    if item.value > 0.999
]
if not locked_head_corners:
    raise RuntimeError("Head identity mask did not lock any corners")
if preview_material.node_tree.nodes.get("SBF_HeadProjection") is None:
    raise RuntimeError("Identity-safe head blending is missing")

_require_finished("bake_final", bpy.ops.sbf.bake_final())

base_image = settings.last_baked_image
if base_image is None or list(base_image.size) != [int(args.size), int(args.size)]:
    raise RuntimeError("Baked base-color image has the wrong dimensions")
if settings.pack_baked_image and base_image.packed_file is None:
    raise RuntimeError("Baked base-color image was not packed")
raw_bake = settings.last_raw_baked_image
if raw_bake is None or raw_bake.name != REPAIR_BAKED_IMAGE:
    raise RuntimeError("Texture Repair Studio did not preserve the original bake")
if base_image.name != REPAIR_FINAL_IMAGE or raw_bake == base_image:
    raise RuntimeError("Final composite does not use a distinct owned image")
owned_repair_names = {
    REPAIR_BAKED_IMAGE,
    REPAIR_CORRECTION_IMAGE,
    REPAIR_MASK_IMAGE,
    REPAIR_FINAL_IMAGE,
    REPAIR_CLASSIFICATION_IMAGE,
}
if not owned_repair_names.issubset({image.name for image in bpy.data.images}):
    raise RuntimeError("Texture Repair Studio owned image set is incomplete")
if any(
    bpy.data.images[name].packed_file is None for name in owned_repair_names
):
    raise RuntimeError("A Texture Repair Studio image was not packed")
repair_metrics = json.loads(target.get("sbf_repair_metrics", "{}"))
if not repair_metrics or repair_metrics.get("diagnostic_pixels") != 0:
    raise RuntimeError(f"Texture repair validation metrics failed: {repair_metrics}")
raw_bake_path = Path(raw_bake.filepath_raw)
if not raw_bake_path.is_file() or raw_bake_path == Path(settings.output_image_path):
    raise RuntimeError("Original bake was not saved to its separate sibling PNG")
if len(mesh.vertices) != original["vertices"]:
    raise RuntimeError("Vertex count changed")
if len(mesh.polygons) != original["polygons"]:
    raise RuntimeError("Polygon count changed")
expected_uv_layers = original["uv_layers"] + [BASE_COLOR_UV_NAME]
if [layer.name for layer in mesh.uv_layers] != expected_uv_layers:
    raise RuntimeError("Clean base-color UV contract changed")
for name, coordinates in original["uv_coordinates"].items():
    layer = mesh.uv_layers.get(name)
    if layer is None or [tuple(item.uv) for item in layer.data] != coordinates:
        raise RuntimeError(f"Original UV layer '{name}' changed")
base_uv_layer = mesh.uv_layers.get(BASE_COLOR_UV_NAME)
if base_uv_layer is None:
    raise RuntimeError("Clean base-color UV was not retained")
if any(
    layer.name.startswith(PROJECTION_UV_PREFIX) for layer in mesh.uv_layers
):
    raise RuntimeError("Temporary projection UV layers remain after baking")
if any(
    attribute.name.startswith(WEIGHT_ATTRIBUTE_PREFIX)
    for attribute in mesh.attributes
):
    raise RuntimeError("Temporary weight attributes remain after baking")
for name in loaded_source_names:
    if image_fingerprint(getattr(settings, name).image) != original_source_fingerprints[name]:
        raise RuntimeError(f"{name} original source changed during final bake")

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

production_material = target.material_slots[target.active_material_index].material
base_uv_node = production_material.node_tree.nodes.get(
    "SBF_BaseColorUVCoordinates"
)
if base_uv_node is None or base_uv_node.uv_map != BASE_COLOR_UV_NAME:
    raise RuntimeError("Baked base color is not bound to its clean UV")
base_vector = settings.last_baked_image and next(
    (
        node.inputs.get("Vector")
        for node in production_material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage"
        and node.image == settings.last_baked_image
    ),
    None,
)
if (
    base_vector is None
    or not base_vector.is_linked
    or base_vector.links[0].from_node != base_uv_node
):
    raise RuntimeError("Baked base-color image lost its explicit UV binding")

result = {
    "status": "PASS",
    "blender_version": bpy.app.version_string,
    "elapsed_seconds": round(time.perf_counter() - started, 3),
    "texture_size": int(args.size),
    "target": target.name,
    "spar3d_intake": intake_result,
    "geometry": {
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
    },
    "uv_layers": [layer.name for layer in mesh.uv_layers],
    "normal_images": normal_images_after,
    "projection_stats": projection_stats,
    "source_alignment": {
        name: {
            "scale": getattr(settings, name).scale,
            "horizontal_scale": getattr(settings, name).horizontal_scale,
            "offset_x": getattr(settings, name).offset_x,
            "offset_y": getattr(settings, name).offset_y,
            "head_scale": getattr(settings, name).head_scale,
            "head_horizontal_scale": getattr(
                settings,
                name,
            ).head_horizontal_scale,
            "head_offset_x": getattr(settings, name).head_offset_x,
            "head_offset_y": getattr(settings, name).head_offset_y,
        }
        for name in loaded_source_names
    },
    "source_doctor": source_doctor,
    "processed_source_parity": True,
    "texture_repair": {
        "architecture": "baked+corrections+mask=final",
        "owned_images": sorted(owned_repair_names),
        "raw_bake_path": str(raw_bake_path),
        "final_path": str(Path(settings.output_image_path).resolve()),
        "metrics": repair_metrics,
    },
    "body_part_ownership": "compact_owner_id_per_polygon",
    "severe_pose_status": "SOURCE_POSE_REVIEW_REQUIRED",
    "landmark_regression": landmark_regression,
    "loaded_source_views": loaded_source_names,
    "head_identity": {
        "locked_corners": len(locked_head_corners),
        "confidence_weighted_blend": True,
    },
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
