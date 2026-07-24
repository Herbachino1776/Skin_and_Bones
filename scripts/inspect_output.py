"""Validate a cleaned Skin & Bones Forge .blend or exported GLB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--glb", type=Path)
    parser.add_argument("--expected-size", type=int, default=4096)
    return parser.parse_args(argv)


args = _args()
kind = "BLEND"
if args.glb:
    kind = "GLB"
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.glb.resolve()))

meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
errors = []
if len(meshes) != 1:
    errors.append(f"Expected exactly one mesh, found {len(meshes)}")

summary = {
    "status": "PASS",
    "kind": kind,
    "blender_version": bpy.app.version_string,
    "meshes": [],
}
for obj in meshes:
    mesh = obj.data
    material = obj.material_slots[0].material if obj.material_slots else None
    image_nodes = (
        [
            node
            for node in material.node_tree.nodes
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None
        ]
        if material and material.node_tree
        else []
    )
    base_nodes = [
        node
        for node in image_nodes
        if "BASE" in f"{node.label} {node.name}".upper()
        and "COLOR" in f"{node.label} {node.name}".upper()
    ]
    normal_nodes = [
        node
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeNormalMap"
    ] if material and material.node_tree else []
    principled_nodes = [
        node
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeBsdfPrincipled"
    ] if material and material.node_tree else []

    if not mesh.uv_layers:
        errors.append(f"{obj.name}: missing production UV")
    if any(layer.name.startswith("SBF_PROJ_") for layer in mesh.uv_layers):
        errors.append(f"{obj.name}: temporary projection UV remains")
    if any(attr.name.startswith("SBF_WEIGHT_") for attr in mesh.attributes):
        errors.append(f"{obj.name}: temporary weight attribute remains")
    if not base_nodes:
        errors.append(f"{obj.name}: no labeled base-color image node")
    elif list(base_nodes[0].image.size) != [
        args.expected_size,
        args.expected_size,
    ]:
        errors.append(
            f"{obj.name}: base-color size is {list(base_nodes[0].image.size)}"
        )
    if not normal_nodes:
        errors.append(f"{obj.name}: normal map node missing")
    if not principled_nodes:
        errors.append(f"{obj.name}: Principled BSDF missing")

    summary["meshes"].append(
        {
            "name": obj.name,
            "vertices": len(mesh.vertices),
            "polygons": len(mesh.polygons),
            "uv_layers": [layer.name for layer in mesh.uv_layers],
            "materials": [
                slot.material.name if slot.material else None
                for slot in obj.material_slots
            ],
            "images": [
                {
                    "name": node.image.name,
                    "size": list(node.image.size),
                    "packed": node.image.packed_file is not None,
                }
                for node in image_nodes
            ],
            "roughness": (
                principled_nodes[0].inputs["Roughness"].default_value
                if principled_nodes
                else None
            ),
            "normal_strength": (
                normal_nodes[0].inputs["Strength"].default_value
                if normal_nodes
                else None
            ),
        }
    )

temporary_objects = [
    obj.name
    for obj in bpy.data.objects
    if obj.name.startswith("SBF_ProjectionCamera_")
    or obj.name.startswith("SBF_Verify_")
]
if temporary_objects:
    errors.append(f"Temporary objects remain: {temporary_objects}")

if errors:
    summary["status"] = "FAIL"
    summary["errors"] = errors
print("SBF_OUTPUT_INSPECTION")
print(json.dumps(summary, indent=2, sort_keys=True))
if errors:
    raise RuntimeError("; ".join(errors))
