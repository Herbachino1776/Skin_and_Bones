"""Print a machine-readable summary of the currently open Blender file.

Run with:
    blender file.blend --background --python scripts/inspect_blend.py
"""

from __future__ import annotations

import json

import bpy


def _vector(values):
    return [round(float(value), 8) for value in values]


def _socket_value(node, socket_name):
    socket = node.inputs.get(socket_name)
    if socket is None:
        return None
    value = socket.default_value
    if hasattr(value, "__len__") and not isinstance(value, str):
        return _vector(value)
    return round(float(value), 8)


def _image_summary(image):
    return {
        "name": image.name,
        "size": [int(image.size[0]), int(image.size[1])],
        "filepath": image.filepath,
        "packed": image.packed_file is not None,
        "colorspace": image.colorspace_settings.name,
        "alpha_mode": image.alpha_mode,
        "source": image.source,
    }


def _material_summary(material):
    summary = {
        "name": material.name,
        "use_nodes": material.use_nodes,
        "nodes": [],
    }
    if not material.use_nodes or material.node_tree is None:
        return summary

    for node in material.node_tree.nodes:
        node_data = {
            "name": node.name,
            "label": node.label,
            "type": node.bl_idname,
        }
        if node.bl_idname == "ShaderNodeTexImage":
            node_data["image"] = node.image.name if node.image else None
        elif node.bl_idname == "ShaderNodeBsdfPrincipled":
            node_data["roughness"] = _socket_value(node, "Roughness")
            node_data["metallic"] = _socket_value(node, "Metallic")
        elif node.bl_idname == "ShaderNodeNormalMap":
            node_data["strength"] = _socket_value(node, "Strength")
            node_data["uv_map"] = node.uv_map
        summary["nodes"].append(node_data)
    return summary


def _object_summary(obj):
    summary = {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "location": _vector(obj.location),
        "rotation_euler": _vector(obj.rotation_euler),
        "scale": _vector(obj.scale),
        "dimensions": _vector(obj.dimensions),
        "material_slots": [
            slot.material.name if slot.material else None for slot in obj.material_slots
        ],
    }
    if obj.type == "MESH":
        mesh = obj.data
        summary["mesh"] = {
            "name": mesh.name,
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "loops": len(mesh.loops),
            "uv_layers": [
                {
                    "name": layer.name,
                    "active": layer == mesh.uv_layers.active,
                    "active_render": layer.active_render,
                }
                for layer in mesh.uv_layers
            ],
            "attributes": [
                {
                    "name": attribute.name,
                    "data_type": attribute.data_type,
                    "domain": attribute.domain,
                }
                for attribute in mesh.attributes
            ],
        }
    return summary


summary = {
    "blender_version": bpy.app.version_string,
    "filepath": bpy.data.filepath,
    "scene": bpy.context.scene.name,
    "render_engine": bpy.context.scene.render.engine,
    "objects": [_object_summary(obj) for obj in bpy.data.objects],
    "materials": [_material_summary(material) for material in bpy.data.materials],
    "images": [_image_summary(image) for image in bpy.data.images],
}

print("SBF_INSPECTION_JSON_BEGIN")
print(json.dumps(summary, indent=2, sort_keys=True))
print("SBF_INSPECTION_JSON_END")
