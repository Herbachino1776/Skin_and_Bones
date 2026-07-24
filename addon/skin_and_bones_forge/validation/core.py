"""Target discovery and validation."""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy

from ..constants import (
    ORIGINAL_MATERIAL_PROPERTY,
    ORIGINAL_SLOT_PROPERTY,
    PREVIEW_MATERIAL_PREFIX,
)


class ValidationError(RuntimeError):
    """Raised when an asset does not satisfy the processing contract."""


@dataclass
class TargetInfo:
    obj: bpy.types.Object
    mesh: bpy.types.Mesh
    material: bpy.types.Material
    material_slot: int
    uv_name: str
    base_color_node: bpy.types.Node
    original_base_image: bpy.types.Image
    principled_node: bpy.types.Node | None
    normal_map_node: bpy.types.Node | None
    normal_image_node: bpy.types.Node | None
    warnings: list[str] = field(default_factory=list)


def _selected_mesh(context, settings):
    if settings.target_object is not None:
        return settings.target_object
    active = context.view_layer.objects.active
    if active is not None and active.type == "MESH":
        return active
    selected = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if len(selected) == 1:
        return selected[0]
    return None


def _find_principled(material):
    if material.node_tree is None:
        return None
    return next(
        (
            node
            for node in material.node_tree.nodes
            if node.bl_idname == "ShaderNodeBsdfPrincipled"
        ),
        None,
    )


def _image_node_from_socket(socket, visited=None):
    if socket is None:
        return None
    visited = visited or set()
    for link in socket.links:
        node = link.from_node
        if node in visited:
            continue
        visited.add(node)
        if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
            return node
        for input_socket in node.inputs:
            found = _image_node_from_socket(input_socket, visited)
            if found is not None:
                return found
    return None


def _find_base_color_node(material, principled, preferred_name):
    nodes = material.node_tree.nodes
    if preferred_name:
        preferred = nodes.get(preferred_name)
        if (
            preferred is not None
            and preferred.bl_idname == "ShaderNodeTexImage"
            and preferred.image is not None
        ):
            return preferred

    if principled is not None:
        connected = _image_node_from_socket(principled.inputs.get("Base Color"))
        if connected is not None:
            return connected

    labeled = next(
        (
            node
            for node in nodes
            if node.bl_idname == "ShaderNodeTexImage"
            and node.image is not None
            and "BASE" in f"{node.label} {node.name}".upper()
            and "COLOR" in f"{node.label} {node.name}".upper()
        ),
        None,
    )
    if labeled is not None:
        return labeled

    image_nodes = [
        node
        for node in nodes
        if node.bl_idname == "ShaderNodeTexImage" and node.image is not None
    ]
    return image_nodes[0] if len(image_nodes) == 1 else None


def _find_normal_nodes(material, principled, preferred_name):
    nodes = material.node_tree.nodes
    normal_map = nodes.get(preferred_name) if preferred_name else None
    if normal_map is None or normal_map.bl_idname != "ShaderNodeNormalMap":
        normal_map = None
        if principled is not None:
            normal_socket = principled.inputs.get("Normal")
            if normal_socket is not None:
                for link in normal_socket.links:
                    if link.from_node.bl_idname == "ShaderNodeNormalMap":
                        normal_map = link.from_node
                        break
        if normal_map is None:
            normal_map = next(
                (
                    node
                    for node in nodes
                    if node.bl_idname == "ShaderNodeNormalMap"
                ),
                None,
            )

    image_node = None
    if normal_map is not None:
        image_node = _image_node_from_socket(normal_map.inputs.get("Color"))
    return normal_map, image_node


def validate_target(context, settings, require_sources=False):
    obj = _selected_mesh(context, settings)
    if obj is None:
        raise ValidationError("Select one mesh or choose a Target Mesh.")
    if obj.type != "MESH":
        raise ValidationError("The target must be a mesh object.")
    if obj.library is not None or obj.data.library is not None:
        raise ValidationError("Linked library meshes must be made local before processing.")

    mesh = obj.data
    if not mesh.vertices or not mesh.polygons:
        raise ValidationError("The target mesh has no renderable geometry.")
    if not mesh.uv_layers:
        raise ValidationError("The target mesh requires an existing production UV map.")

    uv_name = settings.target_uv or (
        mesh.uv_layers.active.name if mesh.uv_layers.active else ""
    )
    if not uv_name or mesh.uv_layers.get(uv_name) is None:
        raise ValidationError(f"Target UV map '{uv_name}' does not exist.")

    material = settings.production_material
    material_slot = -1
    if material is not None:
        material_slot = next(
            (
                index
                for index, slot in enumerate(obj.material_slots)
                if slot.material == material
            ),
            -1,
        )
        if material_slot < 0:
            remembered_name = obj.get(ORIGINAL_MATERIAL_PROPERTY, "")
            remembered_slot = int(obj.get(ORIGINAL_SLOT_PROPERTY, -1))
            preview_active = (
                0 <= remembered_slot < len(obj.material_slots)
                and remembered_name == material.name
                and obj.material_slots[remembered_slot].material is not None
                and obj.material_slots[remembered_slot].material.name.startswith(
                    PREVIEW_MATERIAL_PREFIX
                )
            )
            if preview_active:
                material_slot = remembered_slot
            else:
                raise ValidationError(
                    "Production Material is not assigned to the target."
                )
    else:
        if not obj.material_slots:
            raise ValidationError("The target has no material slots.")
        material_slot = min(obj.active_material_index, len(obj.material_slots) - 1)
        material = obj.material_slots[material_slot].material

    if material is None:
        raise ValidationError("The target material slot is empty.")
    if not material.use_nodes or material.node_tree is None:
        raise ValidationError("The production material must use shader nodes.")

    principled = _find_principled(material)
    base_node = _find_base_color_node(
        material, principled, settings.base_color_node
    )
    if base_node is None or base_node.image is None:
        raise ValidationError(
            "Could not identify a base-color image node. Label it 'BASE COLOR' "
            "or connect it to Principled Base Color."
        )

    normal_map, normal_image = _find_normal_nodes(
        material, principled, settings.normal_map_node
    )
    warnings = []
    if principled is None:
        warnings.append("No Principled BSDF was found; roughness will not be adjusted.")
    if normal_map is None or normal_image is None:
        warnings.append("No connected normal map was found; base color can still be baked.")

    if require_sources:
        missing = [
            name.title()
            for name in ("front", "back", "left", "right")
            if getattr(settings, name).enabled and getattr(settings, name).image is None
        ]
        enabled_count = sum(
            1
            for name in ("front", "back", "left", "right")
            if getattr(settings, name).enabled and getattr(settings, name).image is not None
        )
        if missing:
            raise ValidationError(
                "Enabled source views are missing images: " + ", ".join(missing)
            )
        if enabled_count < 2:
            raise ValidationError("Enable at least two source images.")

    settings.target_object = obj
    settings.production_material = material
    settings.target_uv = uv_name
    settings.base_color_node = base_node.name
    settings.normal_map_node = normal_map.name if normal_map else ""

    return TargetInfo(
        obj=obj,
        mesh=mesh,
        material=material,
        material_slot=material_slot,
        uv_name=uv_name,
        base_color_node=base_node,
        original_base_image=base_node.image,
        principled_node=principled,
        normal_map_node=normal_map,
        normal_image_node=normal_image,
        warnings=warnings,
    )
