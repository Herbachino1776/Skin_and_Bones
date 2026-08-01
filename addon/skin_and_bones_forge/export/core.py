"""Save clean Blender copies, GLBs, and processing metadata."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import bpy

from ..baking.repair_service import validate_repair_for_delivery
from ..constants import (
    ADDON_VERSION_STRING,
    BASE_COLOR_UV_NAME,
    PROCESSING_PRESET,
)
from ..projection import cleanup_temporary_data


def _absolute_path(path_value):
    return Path(bpy.path.abspath(path_value)).resolve()


def _guard_source_overwrite(path, settings):
    source = Path(bpy.data.filepath).resolve() if bpy.data.filepath else None
    if (
        source is not None
        and path == source
        and not settings.allow_source_overwrite
    ):
        raise RuntimeError(
            "Output matches the open source file. Choose a new path or explicitly "
            "enable Allow Source Overwrite."
        )


def _manifest_payload(info, settings, output_type, output_path):
    source = str(Path(bpy.data.filepath).resolve()) if bpy.data.filepath else ""
    repair_metrics = json.loads(
        info.obj.get("sbf_repair_metrics", "{}") or "{}"
    )
    return {
        "schema": "skin-and-bones-forge-processing-v1",
        "addon": "Skin & Bones Forge",
        "version": ADDON_VERSION_STRING,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "preset": PROCESSING_PRESET,
        "source_blend": source,
        "output_type": output_type,
        "output_path": str(output_path),
        "target_object": info.obj.name,
        "mesh": info.mesh.name,
        "geometry": {
            "vertices": len(info.mesh.vertices),
            "polygons": len(info.mesh.polygons),
        },
        "material": info.material.name,
        "target_uv": info.uv_name,
        "base_color_uv": (
            BASE_COLOR_UV_NAME
            if info.mesh.uv_layers.get(BASE_COLOR_UV_NAME)
            else info.uv_name
        ),
        "base_color_image": (
            info.base_color_node.image.name if info.base_color_node.image else None
        ),
        "base_color_size": (
            list(info.base_color_node.image.size)
            if info.base_color_node.image
            else None
        ),
        "roughness": settings.roughness,
        "normal_strength": settings.normal_strength,
        "packed_base_color": bool(
            info.base_color_node.image
            and info.base_color_node.image.packed_file is not None
        ),
        "texture_repair": repair_metrics,
    }


def _write_manifest(info, settings, output_type, output_path):
    if not settings.write_manifest:
        return None
    manifest_path = output_path.with_suffix(output_path.suffix + ".sbf.json")
    payload = _manifest_payload(info, settings, output_type, output_path)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def save_blend_copy(context, info, settings):
    output_path = _absolute_path(settings.save_blend_path)
    _guard_source_overwrite(output_path, settings)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    validate_repair_for_delivery(info, settings)
    cleanup_temporary_data(context, info.obj, info.material)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path), copy=True)
    manifest = _write_manifest(info, settings, "BLEND", output_path)
    return output_path, manifest


def _selection_with_parents(target):
    selected = [target]
    parent = target.parent
    while parent is not None:
        selected.append(parent)
        parent = parent.parent
    return selected


def export_glb(context, info, settings):
    output_path = _absolute_path(settings.export_glb_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    validate_repair_for_delivery(info, settings)
    cleanup_temporary_data(context, info.obj, info.material)

    selected_before = list(context.selected_objects)
    active_before = context.view_layer.objects.active
    for obj in context.selected_objects:
        obj.select_set(False)
    export_objects = _selection_with_parents(info.obj)
    for obj in export_objects:
        obj.select_set(True)
    context.view_layer.objects.active = info.obj

    try:
        bpy.ops.export_scene.gltf(
            filepath=str(output_path),
            export_format="GLB",
            use_selection=True,
            export_apply=True,
            export_texcoords=True,
            export_normals=True,
            export_materials="EXPORT",
            export_animations=False,
        )
    finally:
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected_before:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        context.view_layer.objects.active = active_before

    manifest = _write_manifest(info, settings, "GLB", output_path)
    return output_path, manifest
