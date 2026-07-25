"""Transactional one-click SPAR3D import and mesh preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import uuid

import bpy
from mathutils import Matrix, Vector

from .analysis import analyze_geometry, geometry_fingerprint
from .weld import copy_vertex_groups, exact_position_weld


INTAKE_SCHEMA = 1
PREPARATION_VERSION = "0.6.0"
OWNER_PROPERTY = "sbf_intake_owner"
OWNER_VALUE = "skin_and_bones_forge"
ROLE_PROPERTY = "sbf_intake_role"
TOKEN_PROPERTY = "sbf_intake_token"
SOURCE_PATH_PROPERTY = "sbf_source_path"
SOURCE_COLLECTION = "SBF_SOURCE_RAW_PROTECTED"
CLEAN_COLLECTION = "SBF_CLEAN_CHARACTER"
CLEAN_OBJECT = "SBF_CLEAN_CHARACTER"
CLEAN_MESH = "SBF_CLEAN_CHARACTER_MESH"
REPORT_TEXT = "SBF_SPAR3D_INTAKE_REPORT"
READY_ACTION = "Load source views and run One-Click Best Preview"

_DATA_COLLECTIONS = (
    "objects",
    "meshes",
    "materials",
    "images",
    "collections",
    "texts",
    "node_groups",
    "armatures",
    "curves",
    "cameras",
    "lights",
    "actions",
)
_RAW_MUTATED_PROPERTIES = (
    OWNER_PROPERTY,
    ROLE_PROPERTY,
    TOKEN_PROPERTY,
    SOURCE_PATH_PROPERTY,
    "sbf_original_collections",
    "sbf_raw_geometry_fingerprint",
)


def _owned(item, role=None, token=None):
    if item is None or item.get(OWNER_PROPERTY) != OWNER_VALUE:
        return False
    if role is not None and item.get(ROLE_PROPERTY) != role:
        return False
    if token is not None and item.get(TOKEN_PROPERTY) != token:
        return False
    return True


def _mark(item, role, token, source_path=""):
    item[OWNER_PROPERTY] = OWNER_VALUE
    item[ROLE_PROPERTY] = role
    item[TOKEN_PROPERTY] = token
    if source_path:
        item[SOURCE_PATH_PROPERTY] = source_path


def _inventory():
    return {
        name: {item.as_pointer() for item in getattr(bpy.data, name)}
        for name in _DATA_COLLECTIONS
    }


def _new_items(before, name):
    return [
        item
        for item in getattr(bpy.data, name)
        if item.as_pointer() not in before[name]
    ]


def _remove_datablock(item, collection):
    try:
        collection.remove(item, do_unlink=True)
    except (ReferenceError, RuntimeError, TypeError):
        try:
            collection.remove(item)
        except (ReferenceError, RuntimeError, TypeError):
            pass


def _rollback_new_data(before):
    for name in _DATA_COLLECTIONS:
        collection = getattr(bpy.data, name)
        for item in list(collection):
            if item.as_pointer() in before[name]:
                continue
            _remove_datablock(item, collection)


@dataclass
class SceneState:
    active: object
    selected: tuple
    mode: str
    cursor_location: Vector
    cursor_rotation: Vector
    cursor_mode: str
    unit_system: str
    unit_scale: float
    length_unit: str
    target: object
    production_material: object
    target_uv: str
    base_color_node: str
    normal_map_node: str
    output_state: dict

    @classmethod
    def capture(cls, context):
        scene = context.scene
        settings = scene.sbf_settings
        active = context.view_layer.objects.active
        output_names = (
            "output_image_path",
            "save_blend_path",
            "export_glb_path",
            "proof_render_dir",
            "rigged_export_glb_path",
        )
        return cls(
            active=active,
            selected=tuple(context.selected_objects),
            mode=active.mode if active is not None else "OBJECT",
            cursor_location=scene.cursor.location.copy(),
            cursor_rotation=scene.cursor.rotation_euler.copy(),
            cursor_mode=scene.cursor.rotation_mode,
            unit_system=scene.unit_settings.system,
            unit_scale=scene.unit_settings.scale_length,
            length_unit=scene.unit_settings.length_unit,
            target=settings.target_object,
            production_material=settings.production_material,
            target_uv=settings.target_uv,
            base_color_node=settings.base_color_node,
            normal_map_node=settings.normal_map_node,
            output_state={name: getattr(settings, name) for name in output_names},
        )

    def restore(self, context):
        scene = context.scene
        settings = scene.sbf_settings
        scene.cursor.location = self.cursor_location
        scene.cursor.rotation_mode = self.cursor_mode
        scene.cursor.rotation_euler = self.cursor_rotation
        scene.unit_settings.system = self.unit_system
        scene.unit_settings.scale_length = self.unit_scale
        scene.unit_settings.length_unit = self.length_unit
        settings.target_object = self.target if _object_exists(self.target) else None
        settings.production_material = (
            self.production_material
            if self.production_material is not None
            and self.production_material.name in bpy.data.materials
            else None
        )
        settings.target_uv = self.target_uv
        settings.base_color_node = self.base_color_node
        settings.normal_map_node = self.normal_map_node
        for name, value in self.output_state.items():
            setattr(settings, name, value)
        _ensure_object_mode(context)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in self.selected:
            if _object_exists(obj):
                try:
                    obj.hide_set(False)
                    obj.select_set(True)
                except (ReferenceError, RuntimeError):
                    pass
        if _object_exists(self.active):
            context.view_layer.objects.active = self.active
            if self.mode != "OBJECT":
                try:
                    bpy.ops.object.mode_set(mode=self.mode)
                except RuntimeError:
                    pass


def _object_exists(obj):
    if obj is None:
        return False
    try:
        return obj.name in bpy.data.objects and bpy.data.objects[obj.name] == obj
    except ReferenceError:
        return False


def _ensure_object_mode(context):
    active = context.view_layer.objects.active
    if active is not None and active.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except RuntimeError as exc:
            raise RuntimeError("Leave the current Blender mode before SPAR3D intake.") from exc


def _property_state(item):
    return {
        key: (True, item[key]) if key in item else (False, None)
        for key in _RAW_MUTATED_PROPERTIES
    }


def _restore_properties(item, state):
    for key, (existed, value) in state.items():
        if existed:
            item[key] = value
        elif key in item:
            del item[key]


def _capture_source_state(objects):
    return [
        {
            "object": obj,
            "collections": tuple(obj.users_collection),
            "hide_render": bool(obj.hide_render),
            "hide_select": bool(obj.hide_select),
            "hide_viewport": bool(obj.hide_viewport),
            "hidden": bool(obj.hide_get()),
            "properties": _property_state(obj),
            "data": obj.data,
            "data_properties": _property_state(obj.data) if obj.data else None,
        }
        for obj in objects
        if _object_exists(obj)
    ]


def _restore_source_state(source_state):
    for item in source_state:
        obj = item["object"]
        if not _object_exists(obj):
            continue
        original_collections = [
            collection
            for collection in item["collections"]
            if collection.name in bpy.data.collections
        ]
        for collection in original_collections:
            if obj.name not in collection.objects:
                collection.objects.link(obj)
        for collection in list(obj.users_collection):
            if collection not in original_collections and _owned(
                collection, "raw_collection"
            ):
                collection.objects.unlink(obj)
        obj.hide_render = item["hide_render"]
        obj.hide_select = item["hide_select"]
        obj.hide_viewport = item["hide_viewport"]
        try:
            obj.hide_set(item["hidden"])
        except RuntimeError:
            pass
        _restore_properties(obj, item["properties"])
        data = item["data"]
        if data is not None and item["data_properties"] is not None:
            try:
                _restore_properties(data, item["data_properties"])
            except ReferenceError:
                pass


def _hierarchy_from_root(root):
    result = []
    stack = [root]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.append(current)
        stack.extend(reversed(list(current.children)))
    return result


def _root_of(obj):
    current = obj
    while current.parent is not None:
        current = current.parent
    return current


def _hierarchy_for_selected(obj):
    return _hierarchy_from_root(_root_of(obj))


def _world_extents(obj):
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    if not points:
        return (0.0, 0.0, 0.0)
    return tuple(
        max(point[axis] for point in points) - min(point[axis] for point in points)
        for axis in range(3)
    )


def resolve_production_mesh(objects, preferred=None):
    meshes = [
        obj
        for obj in objects
        if obj.type == "MESH" and obj.data is not None and obj.data.polygons
    ]
    if preferred is not None and preferred in meshes and len(meshes) == 1:
        return preferred
    if len(meshes) == 1:
        return meshes[0]
    if not meshes:
        raise ValueError("The imported hierarchy contains no renderable mesh.")
    ranked = sorted(
        meshes,
        key=lambda obj: (
            len(obj.data.polygons),
            len(obj.data.vertices),
            max(_world_extents(obj)),
        ),
        reverse=True,
    )
    first, second = ranked[0], ranked[1]
    if len(first.data.polygons) >= max(4 * len(second.data.polygons), 100):
        return first
    candidates = ", ".join(
        f"{obj.name} ({len(obj.data.vertices):,} verts/"
        f"{len(obj.data.polygons):,} faces)"
        for obj in ranked
    )
    raise ValueError(
        "AMBIGUOUS_SPAR3D_TARGET: several plausible production meshes exist: "
        + candidates
    )


def _validate_unrigged(objects, source):
    armatures = [obj.name for obj in objects if obj.type == "ARMATURE"]
    modifiers = [
        modifier.name for modifier in source.modifiers if modifier.type == "ARMATURE"
    ]
    if armatures or modifiers or source.find_armature() is not None:
        details = ", ".join(armatures + modifiers) or "armature relationship"
        raise ValueError(
            "UNSUPPORTED_RIGGED_INPUT: SPAR3D intake runs before rigging; found "
            + details
        )
    if source.data.shape_keys is not None:
        raise ValueError(
            "UNSUPPORTED_SHAPE_KEYS: prepare the raw SPAR3D mesh before adding shape keys."
        )
    if source.modifiers:
        raise ValueError(
            "UNSUPPORTED_MODIFIERS: apply or remove non-SPAR3D modifiers before intake."
        )


def _collection_name(base, token):
    existing = bpy.data.collections.get(base)
    if existing is None or _owned(existing):
        return base
    return f"{base}_{token[:8]}"


def _object_name(base, token):
    existing = bpy.data.objects.get(base)
    if existing is None or _owned(existing):
        return base
    return f"{base}_{token[:8]}"


def _mesh_name(base, token):
    existing = bpy.data.meshes.get(base)
    if existing is None or _owned(existing):
        return base
    return f"{base}_{token[:8]}"


def _link_clean(context, source, destination_mesh, token, source_path, weld):
    clean_collection = bpy.data.collections.new(_collection_name(CLEAN_COLLECTION, token))
    _mark(clean_collection, "clean_collection", token, source_path)
    context.scene.collection.children.link(clean_collection)
    clean = source.copy()
    clean.data = destination_mesh
    clean.animation_data_clear()
    clean.parent = None
    clean.parent_type = "OBJECT"
    clean.matrix_parent_inverse = Matrix.Identity(4)
    for constraint in list(clean.constraints):
        clean.constraints.remove(constraint)
    for modifier in list(clean.modifiers):
        clean.modifiers.remove(modifier)
    clean.name = _object_name(CLEAN_OBJECT, token)
    destination_mesh.name = _mesh_name(CLEAN_MESH, token)
    clean_collection.objects.link(clean)
    clean.matrix_world = source.matrix_world.copy()
    while clean.vertex_groups:
        clean.vertex_groups.remove(clean.vertex_groups[0])
    _mark(clean, "clean_object", token, source_path)
    _mark(destination_mesh, "clean_mesh", token, source_path)
    copy_vertex_groups(source, clean, weld["source_to_destination"])
    return clean, clean_collection


def _normalize(clean, target_height):
    if target_height <= 0.0:
        raise ValueError("Target Height must be greater than zero.")
    original_matrix = clean.matrix_world.copy()
    clean.data.calc_loop_triangles()
    corner_normals = [item.vector.copy() for item in clean.data.corner_normals]
    normal_matrix = original_matrix.to_3x3().inverted_safe().transposed()
    for vertex in clean.data.vertices:
        vertex.co = original_matrix @ vertex.co
    clean.matrix_world = Matrix.Identity(4)
    transformed_normals = []
    for normal in corner_normals:
        transformed = normal_matrix @ normal
        if transformed.length_squared:
            transformed.normalize()
        transformed_normals.append(transformed)
    clean.data.normals_split_custom_set(transformed_normals)
    clean.data.update()
    clean.data.calc_loop_triangles()
    maximum_normal_angle = 0.0
    for expected, actual_item in zip(
        transformed_normals, clean.data.corner_normals, strict=True
    ):
        actual = actual_item.vector
        if not expected.length_squared and not actual.length_squared:
            continue
        if not expected.length_squared or not actual.length_squared:
            raise ValueError("Corner normals were lost while applying source transforms.")
        dot = max(-1.0, min(1.0, expected.normalized().dot(actual.normalized())))
        maximum_normal_angle = max(maximum_normal_angle, math.acos(dot))
    if maximum_normal_angle > 1.0e-3:
        raise ValueError("Corner normals changed while applying source transforms.")
    points = [vertex.co.copy() for vertex in clean.data.vertices]
    minimum = Vector(min(point[axis] for point in points) for axis in range(3))
    maximum = Vector(max(point[axis] for point in points) for axis in range(3))
    extents = maximum - minimum
    longest = max(range(3), key=lambda index: extents[index])
    next_largest = sorted(extents, reverse=True)[1]
    if longest != 2 or extents.z < next_largest * 1.05:
        return {
            "orientation_confident": False,
            "readiness": "ORIENTATION_REVIEW_REQUIRED",
            "original_matrix_world": [list(row) for row in original_matrix],
            "original_height": extents.z,
            "extents_before": list(extents),
            "message": (
                "The longest imported extent is not confidently vertical in Blender Z-up."
            ),
            "corner_normal_transform_max_angle_radians": maximum_normal_angle,
        }
    original_height = extents.z
    if original_height <= 1.0e-12:
        raise ValueError("The imported mesh has zero measurable height.")
    factor = target_height / original_height
    center_x = (minimum.x + maximum.x) * 0.5
    center_y = (minimum.y + maximum.y) * 0.5
    for vertex in clean.data.vertices:
        vertex.co = Vector(
            (
                (vertex.co.x - center_x) * factor,
                (vertex.co.y - center_y) * factor,
                (vertex.co.z - minimum.z) * factor,
            )
        )
    clean.data.update()
    clean.location = (0.0, 0.0, 0.0)
    clean.rotation_mode = "XYZ"
    clean.rotation_euler = (0.0, 0.0, 0.0)
    clean.scale = (1.0, 1.0, 1.0)
    final_points = [vertex.co for vertex in clean.data.vertices]
    final_minimum = Vector(
        min(point[axis] for point in final_points) for axis in range(3)
    )
    final_maximum = Vector(
        max(point[axis] for point in final_points) for axis in range(3)
    )
    final_height = final_maximum.z - final_minimum.z
    tolerance = max(target_height * 1.0e-5, 1.0e-6)
    if abs(final_height - target_height) > tolerance or abs(final_minimum.z) > tolerance:
        raise ValueError("Normalized height or grounding validation failed.")
    return {
        "orientation_confident": True,
        "readiness": "READY_FOR_SKIN",
        "original_matrix_world": [list(row) for row in original_matrix],
        "original_height": original_height,
        "target_height": target_height,
        "scale_factor": factor,
        "extents_before": list(extents),
        "ground_correction": -minimum.z,
        "lateral_center_correction": -center_x,
        "depth_center_correction": -center_y,
        "final_height": final_height,
        "final_ground_z": final_minimum.z,
        "normalized_matrix_world": [list(row) for row in clean.matrix_world],
        "normalized_scale": list(clean.scale),
        "normalized_rotation": list(clean.rotation_euler),
        "corner_normal_transform_max_angle_radians": maximum_normal_angle,
    }


def _protect_raw(context, objects, source, token, source_path, raw_fingerprint):
    collection = bpy.data.collections.new(_collection_name(SOURCE_COLLECTION, token))
    _mark(collection, "raw_collection", token, source_path)
    context.scene.collection.children.link(collection)
    for obj in objects:
        original_collections = [item.name for item in obj.users_collection]
        obj["sbf_original_collections"] = json.dumps(original_collections)
        if obj.name not in collection.objects:
            collection.objects.link(obj)
        for original in list(obj.users_collection):
            if original != collection:
                original.objects.unlink(obj)
        _mark(obj, "raw_mesh" if obj == source else "raw_object", token, source_path)
        obj.hide_render = True
        obj.hide_select = True
        try:
            obj.hide_set(True)
        except RuntimeError:
            pass
        if obj.data is not None:
            _mark(obj.data, "raw_data", token, source_path)
    collection.hide_render = True
    collection.hide_select = True
    collection.hide_viewport = True
    source["sbf_raw_geometry_fingerprint"] = raw_fingerprint
    return collection


def _find_reusable_raw(source_path):
    normalized = os.path.normcase(os.path.abspath(source_path))
    for collection in bpy.data.collections:
        if not _owned(collection, "raw_collection"):
            continue
        stored = collection.get(SOURCE_PATH_PROPERTY, "")
        if stored and os.path.normcase(os.path.abspath(stored)) != normalized:
            continue
        meshes = [obj for obj in collection.objects if _owned(obj, "raw_mesh")]
        if len(meshes) == 1:
            return meshes[0], list(collection.objects), collection
    return None


def _raw_for_clean(clean):
    token = clean.get("sbf_raw_token", clean.get(TOKEN_PROPERTY, ""))
    for obj in bpy.data.objects:
        if _owned(obj, "raw_mesh") and (not token or obj.get(TOKEN_PROPERTY) == token):
            return obj, _hierarchy_for_selected(obj)
    raw_meshes = [obj for obj in bpy.data.objects if _owned(obj, "raw_mesh")]
    if len(raw_meshes) == 1:
        return raw_meshes[0], _hierarchy_for_selected(raw_meshes[0])
    raise ValueError("No unique protected raw SPAR3D source is available.")


def _remove_objects(objects):
    data = []
    for obj in objects:
        if not _object_exists(obj):
            continue
        if obj.data is not None:
            data.append(obj.data)
        bpy.data.objects.remove(obj, do_unlink=True)
    for item in data:
        if item.users == 0:
            collection_name = {
                "Mesh": "meshes",
                "Armature": "armatures",
                "Camera": "cameras",
                "Light": "lights",
                "Curve": "curves",
            }.get(type(item).__name__)
            if collection_name:
                _remove_datablock(item, getattr(bpy.data, collection_name))


def _remove_collection(collection):
    if collection is not None and collection.name in bpy.data.collections:
        bpy.data.collections.remove(collection)


def _purge_unused_owned_data(exclude_token=None):
    for name in ("meshes", "materials", "images", "node_groups", "actions"):
        collection = getattr(bpy.data, name)
        for item in list(collection):
            if not _owned(item) or item.users != 0:
                continue
            if exclude_token and item.get(TOKEN_PROPERTY) == exclude_token:
                continue
            _remove_datablock(item, collection)


def _remove_previous_owned(current_token, preserve_raw_collection=None):
    old_objects = [
        obj
        for obj in bpy.data.objects
        if _owned(obj)
        and obj.get(TOKEN_PROPERTY) != current_token
        and (
            preserve_raw_collection is None
            or obj.name not in preserve_raw_collection.objects
        )
    ]
    _remove_objects(old_objects)
    for collection in list(bpy.data.collections):
        if not _owned(collection) or collection.get(TOKEN_PROPERTY) == current_token:
            continue
        if preserve_raw_collection is not None and collection == preserve_raw_collection:
            continue
        _remove_collection(collection)
    for text in list(bpy.data.texts):
        if _owned(text) and text.get(TOKEN_PROPERTY) != current_token:
            bpy.data.texts.remove(text)
    _purge_unused_owned_data(exclude_token=current_token)


def _delete_unpreserved_source(objects, clean):
    removable = [obj for obj in objects if obj != clean]
    _remove_objects(removable)


def _assign_pipeline_target(context, clean):
    settings = context.scene.sbf_settings
    settings.target_object = clean
    settings.production_material = next(
        (slot.material for slot in clean.material_slots if slot.material is not None),
        None,
    )
    if clean.data.uv_layers:
        active = clean.data.uv_layers.active or clean.data.uv_layers[0]
        settings.target_uv = active.name
    else:
        settings.target_uv = ""
    settings.base_color_node = ""
    settings.normal_map_node = ""
    if settings.production_material is not None and settings.target_uv:
        from ..validation import validate_target

        validate_target(context, settings)


def _readiness(clean_analysis, proof, normalization):
    if not normalization["orientation_confident"]:
        return "ORIENTATION_REVIEW_REQUIRED", normalization["message"]
    mandatory_surface = (
        clean_analysis["connected_components"] == 1
        and clean_analysis["boundary_edge_count"] == 0
        and clean_analysis["non_manifold_edge_count"] == 0
        and clean_analysis["watertight"]
        and clean_analysis["winding_consistent"]
        and clean_analysis["signed_volume_world"] > 0.0
        and not clean_analysis["loose_vertices"]
        and not clean_analysis["loose_edges"]
        and not clean_analysis["zero_area_faces"]
        and not clean_analysis["repeated_index_faces"]
    )
    if not mandatory_surface:
        return (
            "NEEDS_GEOMETRY_REVIEW",
            "Exact welding preserved the source, but the result is not one closed, "
            "positive-volume manifold component.",
        )
    if not all(
        proof[name]
        for name in (
            "material_assignments_preserved",
            "uv_values_preserved",
            "corner_normals_preserved",
            "surface_area_world_preserved",
            "signed_volume_world_preserved",
        )
    ):
        return "FAILED", "Mandatory attribute or geometry proof failed."
    return "READY_FOR_SKIN", READY_ACTION


def _attach_metadata(clean, source, source_path, token, raw, welded, normalized, report):
    timestamp = datetime.now(timezone.utc).isoformat()
    properties = {
        OWNER_PROPERTY: OWNER_VALUE,
        ROLE_PROPERTY: "clean_object",
        TOKEN_PROPERTY: token,
        "sbf_intake_schema": INTAKE_SCHEMA,
        "sbf_preparation_version": PREPARATION_VERSION,
        "sbf_raw_geometry_fingerprint": raw["fingerprint"],
        "sbf_clean_geometry_fingerprint": welded["fingerprint"],
        "sbf_normalized_geometry_fingerprint": normalized["fingerprint"],
        "sbf_exact_weld_count": report["exact_vertices_welded"],
        "sbf_source_file": Path(source_path).name if source_path else "selected_scene_object",
        "sbf_source_path": source_path,
        "sbf_source_object": source.name,
        "sbf_original_height": report["normalization"].get("original_height", 0.0),
        "sbf_normalized_height": report["normalization"].get("final_height", 0.0),
        "sbf_prepared_at": timestamp,
        "sbf_readiness": report["readiness"],
    }
    for key, value in properties.items():
        clean[key] = value
    clean["sbf_raw_token"] = source.get(TOKEN_PROPERTY, token)
    for key, value in properties.items():
        if key not in {"sbf_source_object", "sbf_prepared_at"}:
            clean.data[key] = value


def write_intake_report(context, report=None, token=None):
    settings = context.scene.sbf_settings
    if report is None:
        if not settings.intake_report_json:
            raise ValueError("No SPAR3D intake report is available.")
        report = json.loads(settings.intake_report_json)
    existing = bpy.data.texts.get(REPORT_TEXT)
    if existing is not None and (
        not _owned(existing)
        or (token and existing.get(TOKEN_PROPERTY) != token)
    ):
        name = f"{REPORT_TEXT}_{(token or uuid.uuid4().hex)[:8]}"
        text = bpy.data.texts.new(name)
    else:
        text = existing or bpy.data.texts.new(REPORT_TEXT)
        text.clear()
    token = token or report.get("transaction_token", "")
    _mark(text, "intake_report", token, report.get("source_path", ""))
    text.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return text


def _select_clean(context, clean):
    bpy.ops.object.select_all(action="DESELECT")
    clean.hide_select = False
    clean.hide_viewport = False
    clean.hide_render = False
    try:
        clean.hide_set(False)
    except RuntimeError:
        pass
    clean.select_set(True)
    context.view_layer.objects.active = clean


def _run_prepare(
    context,
    *,
    source_path="",
    import_file=False,
    selected_object=None,
):
    settings = context.scene.sbf_settings
    state = SceneState.capture(context)
    before = _inventory()
    token = uuid.uuid4().hex
    normalized_source_path = (
        str(Path(source_path).resolve()) if source_path else ""
    )
    imported_objects = []
    source_objects = []
    source = None
    reusable_collection = None
    raw_already_protected = False
    source_state = []
    try:
        _ensure_object_mode(context)
        if import_file:
            path = Path(source_path).resolve()
            if not path.is_file() or path.suffix.lower() not in {".glb", ".gltf"}:
                raise ValueError(f"Choose an existing GLB or glTF file: {path}")
            reusable = _find_reusable_raw(str(path)) if settings.intake_preserve_raw else None
            if reusable:
                source, source_objects, reusable_collection = reusable
                raw_already_protected = True
            else:
                object_pointers = {obj.as_pointer() for obj in bpy.data.objects}
                result = bpy.ops.import_scene.gltf(filepath=str(path))
                if "FINISHED" not in result:
                    raise RuntimeError("Blender's glTF importer did not finish.")
                imported_objects = [
                    obj for obj in bpy.data.objects if obj.as_pointer() not in object_pointers
                ]
                source_objects = imported_objects
                source = resolve_production_mesh(imported_objects)
                for name in _DATA_COLLECTIONS:
                    for item in _new_items(before, name):
                        if hasattr(item, "keys"):
                            _mark(item, "imported_data", token, normalized_source_path)
        else:
            source = selected_object
            if source is None:
                active = context.view_layer.objects.active
                selected_meshes = [obj for obj in context.selected_objects if obj.type == "MESH"]
                if active is not None and active.type == "MESH" and active in selected_meshes:
                    source = active
                elif len(selected_meshes) == 1:
                    source = selected_meshes[0]
            if source is None or source.type != "MESH":
                raise ValueError("Select one imported SPAR3D mesh to prepare.")
            if _owned(source, "clean_object"):
                source, source_objects = _raw_for_clean(source)
                reusable_collection = next(
                    (
                        collection
                        for collection in bpy.data.collections
                        if _owned(collection, "raw_collection")
                        and source.name in collection.objects
                    ),
                    None,
                )
                raw_already_protected = reusable_collection is not None
            else:
                source_objects = _hierarchy_for_selected(source)
                source = resolve_production_mesh(source_objects, preferred=source)

        source_state = _capture_source_state(source_objects)
        _validate_unrigged(source_objects, source)
        raw_fingerprint_before = geometry_fingerprint(source)
        raw = analyze_geometry(source, include_corner_data=True)
        if raw["fingerprint"] != raw_fingerprint_before:
            raise RuntimeError("Raw geometry changed during non-mutating analysis.")

        destination_mesh, weld = exact_position_weld(
            source, _mesh_name(CLEAN_MESH, token)
        )
        clean, clean_collection = _link_clean(
            context,
            source,
            destination_mesh,
            token,
            normalized_source_path,
            weld,
        )
        if settings.intake_test_failure_stage == "AFTER_CLEAN":
            raise RuntimeError("Injected intake rollback test failure.")

        clean_fingerprint = geometry_fingerprint(clean)
        clean_before_normalization = analyze_geometry(
            clean, include_corner_data=False, include_near_duplicates=False
        )
        normalization = _normalize(clean, settings.intake_target_height)
        normalized_fingerprint = geometry_fingerprint(clean)
        normalized = analyze_geometry(
            clean, include_corner_data=False, include_near_duplicates=False
        )
        readiness, recommendation = _readiness(
            normalized, weld["proof"], normalization
        )
        if readiness == "FAILED":
            raise RuntimeError(recommendation)

        _assign_pipeline_target(context, clean)
        if settings.intake_preserve_raw:
            if raw_already_protected:
                raw_collection = reusable_collection
                raw_collection.hide_render = True
                raw_collection.hide_select = True
                raw_collection.hide_viewport = True
            else:
                raw_collection = _protect_raw(
                    context,
                    source_objects,
                    source,
                    token,
                    normalized_source_path,
                    raw_fingerprint_before,
                )
            if geometry_fingerprint(source) != raw_fingerprint_before:
                raise RuntimeError("Protected raw source geometry changed during preparation.")
        else:
            raw_collection = None
        if settings.intake_test_failure_stage == "AFTER_RAW_PROTECTION":
            raise RuntimeError("Injected intake raw-protection rollback test failure.")

        report = {
            "schema": INTAKE_SCHEMA,
            "preparation_version": PREPARATION_VERSION,
            "transaction_token": token,
            "source_path": normalized_source_path,
            "source_object": source.name,
            "raw": raw,
            "welded": clean_before_normalization,
            "normalized": normalized,
            "proof": weld["proof"],
            "cleanup": weld["cleanup"],
            "exact_vertices_welded": weld["exact_vertices_welded"],
            "normalization": normalization,
            "fingerprints": {
                "raw": raw_fingerprint_before,
                "clean_welded": clean_fingerprint,
                "normalized": normalized_fingerprint,
            },
            "readiness": readiness,
            "recommended_next_action": recommendation,
            "approximate_merge_performed": False,
        }
        _attach_metadata(
            clean,
            source,
            normalized_source_path,
            token,
            raw,
            {"fingerprint": clean_fingerprint},
            {"fingerprint": normalized_fingerprint},
            report,
        )
        clean["sbf_raw_token"] = source.get(TOKEN_PROPERTY, token)
        report_text = write_intake_report(context, report=report, token=token)

        if not settings.intake_preserve_raw:
            _delete_unpreserved_source(source_objects, clean)
        _remove_previous_owned(
            token,
            preserve_raw_collection=raw_collection if raw_already_protected else None,
        )
        report_text.name = REPORT_TEXT
        clean.name = _object_name(CLEAN_OBJECT, token)
        clean.data.name = _mesh_name(CLEAN_MESH, token)
        clean_collection.name = _collection_name(CLEAN_COLLECTION, token)
        if raw_collection is not None:
            raw_collection.name = _collection_name(SOURCE_COLLECTION, token)

        settings.intake_readiness = readiness
        settings.intake_report_json = json.dumps(
            report, sort_keys=True, separators=(",", ":")
        )
        settings.intake_status_summary = (
            f"Vertices {raw['counts']['vertices']:,} → "
            f"{clean_before_normalization['counts']['vertices']:,}; components "
            f"{raw['connected_components']:,} → "
            f"{clean_before_normalization['connected_components']:,}; welded "
            f"{weld['exact_vertices_welded']:,}."
        )
        settings.intake_validation_summary = (
            f"Faces {normalized['counts']['polygons']:,}; "
            f"boundary {normalized['boundary_edge_count']}; "
            f"non-manifold {normalized['non_manifold_edge_count']}; "
            f"UV {'preserved' if weld['proof']['uv_values_preserved'] else 'FAILED'}; "
            f"normals {'preserved' if weld['proof']['corner_normals_preserved'] else 'FAILED'}."
        )
        settings.intake_recommended_action = recommendation
        settings.intake_source_path = normalized_source_path
        settings.status_message = f"SPAR3D intake: {readiness.replace('_', ' ').title()}."
        _select_clean(context, clean)
        return report, clean
    except Exception:
        _rollback_new_data(before)
        _restore_source_state(source_state)
        state.restore(context)
        settings.intake_readiness = "FAILED"
        settings.intake_recommended_action = "Review the intake error and source mesh."
        raise


def prepare_imported_spar3d(context, filepath):
    return _run_prepare(context, source_path=filepath, import_file=True)


def prepare_selected_spar3d(context, selected_object=None):
    return _run_prepare(context, import_file=False, selected_object=selected_object)


def _raw_collection():
    collections = [
        collection
        for collection in bpy.data.collections
        if _owned(collection, "raw_collection")
    ]
    if len(collections) != 1:
        raise ValueError("A unique protected raw SPAR3D collection is not available.")
    return collections[0]


def restore_raw_source(context):
    collection = _raw_collection()
    raw_meshes = [obj for obj in collection.objects if _owned(obj, "raw_mesh")]
    if len(raw_meshes) != 1:
        raise ValueError("The protected collection does not contain one raw mesh.")
    clean_objects = [obj for obj in bpy.data.objects if _owned(obj, "clean_object")]
    _remove_objects(clean_objects)
    for clean_collection in list(bpy.data.collections):
        if _owned(clean_collection, "clean_collection"):
            _remove_collection(clean_collection)
    for obj in list(collection.objects):
        destinations = []
        try:
            names = json.loads(obj.get("sbf_original_collections", "[]"))
        except (TypeError, json.JSONDecodeError):
            names = []
        for name in names:
            destination = bpy.data.collections.get(name)
            if destination is not None and destination != collection:
                destinations.append(destination)
        if not destinations:
            restored = bpy.data.collections.get("SPAR3D_RESTORED_SOURCE")
            if restored is None:
                restored = bpy.data.collections.new("SPAR3D_RESTORED_SOURCE")
                context.scene.collection.children.link(restored)
            destinations = [restored]
        for destination in destinations:
            if obj.name not in destination.objects:
                destination.objects.link(obj)
        collection.objects.unlink(obj)
        obj.hide_render = False
        obj.hide_select = False
        try:
            obj.hide_set(False)
        except RuntimeError:
            pass
    _remove_collection(collection)
    for text in list(bpy.data.texts):
        if _owned(text, "intake_report"):
            bpy.data.texts.remove(text)
    raw = raw_meshes[0]
    settings = context.scene.sbf_settings
    settings.target_object = raw
    settings.production_material = next(
        (slot.material for slot in raw.material_slots if slot.material is not None), None
    )
    settings.target_uv = raw.data.uv_layers.active.name if raw.data.uv_layers.active else ""
    settings.intake_readiness = "NOT_RUN"
    settings.intake_status_summary = "Protected raw SPAR3D hierarchy restored."
    settings.intake_validation_summary = "No prepared clean character is active."
    settings.intake_recommended_action = "Run Prepare Selected SPAR3D Character."
    _select_clean(context, raw)
    _purge_unused_owned_data()
    return raw


def remove_protected_raw_source(context):
    collection = _raw_collection()
    objects = list(collection.objects)
    _remove_objects(objects)
    _remove_collection(collection)
    _purge_unused_owned_data()
    settings = context.scene.sbf_settings
    settings.intake_status_summary = "Protected raw SPAR3D source removed."
    return len(objects)


def compare_raw_and_clean(context):
    settings = context.scene.sbf_settings
    clean = settings.target_object
    if clean is None or not _owned(clean, "clean_object"):
        raise ValueError("The current target is not an owned prepared character.")
    collection = _raw_collection()
    raw_meshes = [obj for obj in collection.objects if _owned(obj, "raw_mesh")]
    if len(raw_meshes) != 1:
        raise ValueError("A unique raw mesh is not available for comparison.")
    raw = analyze_geometry(raw_meshes[0], include_corner_data=False)
    prepared = analyze_geometry(clean, include_corner_data=False)
    return {
        "raw_vertices": raw["counts"]["vertices"],
        "clean_vertices": prepared["counts"]["vertices"],
        "raw_components": raw["connected_components"],
        "clean_components": prepared["connected_components"],
        "raw_faces": raw["counts"]["polygons"],
        "clean_faces": prepared["counts"]["polygons"],
        "clean_watertight": prepared["watertight"],
        "raw_fingerprint_unchanged": raw["fingerprint"]
        == raw_meshes[0].get("sbf_raw_geometry_fingerprint", raw["fingerprint"]),
    }
