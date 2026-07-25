"""Production rig finalization, rigged GLB export, and clean-reimport checks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess

import bpy
from mathutils import Vector

from ..constants import (
    ADDON_VERSION_STRING,
    RIG_OWNER_PROPERTY,
    RIG_PREVIEW_COLLECTION,
    RIG_PRODUCTION_ARMATURE,
    RIG_PRODUCTION_PROPERTY,
)
from .analysis import evaluated_points
from .fitting import OWNER
from .poses import (
    PRODUCTION_TRACK_PREFIX,
    create_production_actions,
    iter_action_fcurves,
)
from .weights import clean_weighting_temporary_data, load_weight_report


def production_armature(target=None):
    candidates = [
        obj
        for obj in bpy.data.objects
        if obj.type == "ARMATURE"
        and obj.get(RIG_OWNER_PROPERTY) == OWNER
        and (
            obj.get(RIG_PRODUCTION_PROPERTY, False)
            or obj.name in {"SBF_FittedSkeletonPreview", RIG_PRODUCTION_ARMATURE}
        )
    ]
    if target is not None:
        candidates = [
            obj
            for obj in candidates
            if target.parent == obj
            or any(
                modifier.type == "ARMATURE" and modifier.object == obj
                for modifier in target.modifiers
            )
        ]
    return candidates[0] if len(candidates) == 1 else None


def finalize_production_rig(target, armature, contract, pose_report, action_report):
    weight_report = load_weight_report(target)
    if weight_report is None or weight_report["status"] == "FAILED":
        raise RuntimeError("Production weights must validate before finalization.")
    if pose_report.get("status") != "POSE_TESTS_PASSED":
        raise RuntimeError("Pose torture tests must pass before finalization.")
    if action_report.get("status") != "CANONICAL_ACTIONS_PASSED":
        raise RuntimeError("Canonical Action compatibility must pass before finalization.")
    production_names = [bone["name"] for bone in contract["bones"]]
    if [bone.name for bone in armature.data.bones] != production_names:
        raise RuntimeError(
            "Production armature no longer matches the simplified contract."
        )

    preview = bpy.data.collections.get(RIG_PREVIEW_COLLECTION)
    if preview is not None:
        for obj in list(preview.objects):
            if obj == armature:
                continue
            if obj.get(RIG_OWNER_PROPERTY) == OWNER:
                bpy.data.objects.remove(obj, do_unlink=True)
            else:
                raise RuntimeError(
                    f"Rig preview contains unowned object '{obj.name}'."
                )
        if armature.name in preview.objects:
            preview.objects.unlink(armature)
        if not preview.objects:
            bpy.data.collections.remove(preview)
    target_collection = (
        target.users_collection[0]
        if target.users_collection
        else bpy.context.scene.collection
    )
    if target_collection != bpy.context.scene.collection:
        if armature.name not in target_collection.objects:
            target_collection.objects.link(armature)
    elif armature.name not in bpy.context.scene.collection.objects:
        bpy.context.scene.collection.objects.link(armature)
    armature.name = RIG_PRODUCTION_ARMATURE
    armature.data.name = f"{RIG_PRODUCTION_ARMATURE}_Data"
    armature[RIG_PRODUCTION_PROPERTY] = True
    armature["sbf_rig_stage"] = "PRODUCTION"
    armature["sbf_canonical_fingerprint"] = contract.get(
        "source_fingerprint", ""
    )
    armature["sbf_production_profile"] = contract.get("profile_id", "")
    armature["sbf_production_fingerprint"] = contract["fingerprint"]
    armature["sbf_removed_finger_bones"] = json.dumps(
        contract.get("removed_bones", [])
    )
    target[RIG_PRODUCTION_PROPERTY] = True
    target["sbf_rig_stage"] = "PRODUCTION"
    target["sbf_pose_test_status"] = pose_report["status"]
    target["sbf_canonical_action_status"] = action_report["status"]
    production_actions = create_production_actions(armature, contract)
    armature["sbf_production_action_count"] = len(production_actions)
    armature["sbf_removed_finger_channel_count"] = sum(
        int(action.get("sbf_removed_finger_channel_count", 0))
        for action in production_actions
    )
    return armature


def _operator_kwargs(operator, values):
    identifiers = {
        item.identifier for item in operator.get_rna_type().properties
    }
    return {key: value for key, value in values.items() if key in identifiers}


def _animation_state(armature, scene):
    animation = armature.animation_data
    return {
        "frame": scene.frame_current,
        "action": animation.action if animation else None,
        "action_slot": animation.action_slot if animation else None,
        "nla": (
            [(track, bool(track.mute)) for track in animation.nla_tracks]
            if animation
            else []
        ),
        "pose": {
            bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones
        },
    }


def _restore_animation_state(armature, scene, state):
    for bone in armature.pose.bones:
        matrix = state["pose"].get(bone.name)
        if matrix is not None:
            bone.matrix_basis = matrix
    if armature.animation_data is not None:
        armature.animation_data.action = state["action"]
        if state["action"] is not None and state["action_slot"] is not None:
            armature.animation_data.action_slot = state["action_slot"]
    for track, mute in state["nla"]:
        try:
            track.mute = mute
        except ReferenceError:
            pass
    scene.frame_set(state["frame"])


def _rigging_manifest(
    path,
    target,
    armature,
    contract,
    settings,
    weight_report,
):
    def load(name):
        raw = getattr(settings, name, "")
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    payload = {
        "schema": "skin-and-bones-forge-rigging-v2",
        "addon_version": ADDON_VERSION_STRING,
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_path": str(path),
        "canonical_fingerprint": contract.get("source_fingerprint"),
        "canonical_bone_count": contract.get("source_bone_count"),
        "canonical_deform_bone_count": contract.get(
            "source_deform_bone_count"
        ),
        "canonical_action_count": contract.get("source_action_count"),
        "canonical_nla_track_count": contract.get("source_nla_track_count"),
        "production_profile": contract.get("profile_id"),
        "production_fingerprint": contract["fingerprint"],
        "production_bone_count": len(contract["bones"]),
        "production_deform_bone_count": sum(
            bone["deform"] for bone in contract["bones"]
        ),
        "removed_finger_bone_count": len(
            contract.get("removed_bones", [])
        ),
        "removed_finger_bones": contract.get("removed_bones", []),
        "retained_hand_bones": contract.get("retained_hand_bones", {}),
        "reserved_hand_shape_keys": contract.get(
            "reserved_hand_shape_keys", []
        ),
        "target_height": settings.target_height,
        "fitted_rig_validation_state": settings.rig_validation_state,
        "binding_method": settings.rig_binding_method,
        "donor_source": weight_report.get("donor_source"),
        "disconnected_component_count": weight_report.get("component_count"),
        "unweighted_count": weight_report.get("unweighted_vertices"),
        "maximum_influences": weight_report.get("maximum_influences"),
        "normalization_result": weight_report.get("non_normalized_vertices") == 0,
        "fallback_count": weight_report.get("proxy_fallback_vertex_count"),
        "pose_test_result": load("rig_pose_test_json"),
        "canonical_action_results": load("rig_action_test_json"),
        "filtered_action_count": settings.rig_filtered_action_count,
        "removed_finger_channel_count": (
            settings.rig_removed_finger_channel_count
        ),
        "glb_export_result": {
            "status": "EXPORTED",
            "mesh": target.name,
            "armature": armature.name,
        },
        "glb_reimport_result": load("rig_reimport_json"),
        "animation_forge_acceptance": load("rig_animation_forge_json"),
        "deferred_hand_tuning_warning": (
            "Hand-pose aesthetics are deferred and are not a structural blocker."
        ),
        "weight_report": weight_report,
    }
    manifest_path = path.with_suffix(path.suffix + ".sbf.json")
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def refresh_rigging_manifest(
    filepath,
    target,
    armature,
    contract,
    settings,
):
    report = load_weight_report(target)
    if report is None:
        raise RuntimeError("Production weight report is unavailable.")
    return _rigging_manifest(
        Path(bpy.path.abspath(str(filepath))).resolve(),
        target,
        armature,
        contract,
        settings,
        report,
    )


def export_rigged_glb(
    context,
    target,
    armature,
    contract,
    settings,
):
    weight_report = load_weight_report(target)
    if weight_report is None or weight_report["status"] == "FAILED":
        raise RuntimeError("Validate production weights before rigged export.")
    output = Path(bpy.path.abspath(settings.rigged_export_glb_path)).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    clean_weighting_temporary_data()
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    state = _animation_state(armature, context.scene)
    try:
        if armature.animation_data is not None:
            for track in armature.animation_data.nla_tracks:
                if track.name.startswith(PRODUCTION_TRACK_PREFIX):
                    track.mute = False
        for obj in context.selected_objects:
            obj.select_set(False)
        target.select_set(True)
        armature.select_set(True)
        context.view_layer.objects.active = armature
        values = {
            "filepath": str(output),
            "export_format": "GLB",
            "use_selection": True,
            "export_apply": False,
            "export_texcoords": True,
            "export_normals": True,
            "export_tangents": True,
            "export_materials": "EXPORT",
            "export_skins": True,
            "export_extras": True,
            "export_animations": bool(settings.rig_export_actions),
            "export_animation_mode": "NLA_TRACKS",
            "export_force_sampling": True,
        }
        result = bpy.ops.export_scene.gltf(
            **_operator_kwargs(bpy.ops.export_scene.gltf, values)
        )
        if "FINISHED" not in result or not output.is_file():
            raise RuntimeError("Blender did not produce the rigged GLB.")
    finally:
        _restore_animation_state(armature, context.scene, state)
        for obj in list(context.selected_objects):
            obj.select_set(False)
        for obj in selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if active and active.name in context.view_layer.objects:
            context.view_layer.objects.active = active
    manifest = _rigging_manifest(
        output, target, armature, contract, settings, weight_report
    )
    return output, manifest


def _world_bounds(context, obj):
    points = evaluated_points(context, obj)
    minimum = Vector(min(point[index] for point in points) for index in range(3))
    maximum = Vector(max(point[index] for point in points) for index in range(3))
    return minimum, maximum


def _action_bone_names(action):
    names = set()
    for curve in iter_action_fcurves(action):
        path = curve.data_path
        if 'pose.bones["' in path:
            names.add(path.split('pose.bones["', 1)[1].split('"]', 1)[0])
    return names


def _validate_clean_reimport_in_process(
    context,
    filepath,
    contract,
    expected_height,
):
    before_objects = set(bpy.data.objects)
    before_actions = set(bpy.data.actions)
    before_meshes = set(bpy.data.meshes)
    before_armatures = set(bpy.data.armatures)
    before_materials = set(bpy.data.materials)
    before_images = set(bpy.data.images)
    try:
        result = bpy.ops.import_scene.gltf(filepath=str(Path(filepath).resolve()))
        if "FINISHED" not in result:
            raise RuntimeError("Rigged GLB clean reimport failed.")
        objects = [obj for obj in bpy.data.objects if obj not in before_objects]
        armatures = [obj for obj in objects if obj.type == "ARMATURE"]
        meshes = [obj for obj in objects if obj.type == "MESH"]
        if len(armatures) != 1:
            raise RuntimeError(f"Expected one imported armature, found {len(armatures)}.")
        armature = armatures[0]
        skinned = [
            obj
            for obj in meshes
            if any(
                modifier.type == "ARMATURE" and modifier.object == armature
                for modifier in obj.modifiers
            )
        ]
        if len(skinned) != 1:
            raise RuntimeError(f"Expected one skinned production mesh, found {len(skinned)}.")
        mesh = skinned[0]
        expected_names = [bone["name"] for bone in contract["bones"]]
        names = [bone.name for bone in armature.data.bones]
        hierarchy = {
            bone.name: bone.parent.name if bone.parent else None
            for bone in armature.data.bones
        }
        expected_hierarchy = {
            bone["name"]: bone["parent"] for bone in contract["bones"]
        }
        pose_before = armature.data.pose_position
        armature.data.pose_position = "REST"
        context.view_layer.update()
        rest_points = evaluated_points(context, mesh)
        minimum, maximum = _world_bounds(context, mesh)
        height = maximum.z - minimum.z
        armature.data.pose_position = pose_before
        new_actions = [action for action in bpy.data.actions if action not in before_actions]
        removed_bones = set(contract.get("removed_bones", []))
        removed_action_channels = {
            action.name: sorted(_action_bone_names(action).intersection(removed_bones))
            for action in new_actions
            if _action_bone_names(action).intersection(removed_bones)
        }
        action_safe = True
        action_meaningful = False
        action_test = None
        if new_actions:
            animation = armature.animation_data_create()
            prior = animation.action
            try:
                animation.action = new_actions[0]
                suitable = list(
                    getattr(animation, "action_suitable_slots", [])
                )
                if suitable:
                    animation.action_slot = suitable[0]
                context.scene.frame_set(
                    int(round(sum(new_actions[0].frame_range) * 0.5))
                )
                context.view_layer.update()
                points = evaluated_points(context, mesh)
                action_safe = all(
                    math.isfinite(float(value))
                    for point in points
                    for value in point
                )
                action_meaningful = any(
                    (point - rest).length > expected_height * 1.0e-5
                    for point, rest in zip(points, rest_points)
                )
                action_test = new_actions[0].name
            finally:
                animation.action = prior
        images = [
            image.name for image in bpy.data.images if image not in before_images
        ]
        materials = [
            material.name
            for material in bpy.data.materials
            if material not in before_materials
        ]
        deform_count = sum(
            1 for bone in armature.data.bones if bone.use_deform
        )
        modifier_count = sum(
            modifier.type == "ARMATURE" for modifier in mesh.modifiers
        )
        uv_maps = [layer.name for layer in mesh.data.uv_layers]
        expected_action_count = len(
            contract["animation_inventory"]["actions"]
        )
        profile_metadata_match = (
            armature.get("sbf_production_profile")
            == contract.get("profile_id")
            and armature.get("sbf_production_fingerprint")
            == contract["fingerprint"]
        )
        accepted = (
            names == expected_names
            and hierarchy == expected_hierarchy
            and deform_count
            == sum(bool(bone["deform"]) for bone in contract["bones"])
            and modifier_count == 1
            and bool(materials)
            and bool(images)
            and bool(uv_maps)
            and len(new_actions) == expected_action_count
            and not removed_action_channels
            and profile_metadata_match
            and abs(float(height) - expected_height)
            <= max(expected_height * 0.02, 1.0e-4)
            and action_safe
            and action_meaningful
        )
        report = {
            "status": (
                "CLEAN_REIMPORT_PASSED" if accepted else "CLEAN_REIMPORT_FAILED"
            ),
            "bone_names_match": names == expected_names,
            "hierarchy_match": hierarchy == expected_hierarchy,
            "production_profile": contract.get("profile_id"),
            "production_fingerprint": contract["fingerprint"],
            "profile_metadata_match": profile_metadata_match,
            "removed_finger_bones": sorted(removed_bones),
            "removed_finger_action_channels": removed_action_channels,
            "deform_bone_count": deform_count,
            "skinned_mesh_count": len(skinned),
            "armature_modifier_count": modifier_count,
            "materials": materials,
            "textures": images,
            "uv_maps": uv_maps,
            "animation_inventory": [action.name for action in new_actions],
            "character_height": round(float(height), 6),
            "height_delta": round(abs(float(height) - expected_height), 6),
            "mesh_world_bounds": {
                "minimum": [round(float(value), 6) for value in minimum],
                "maximum": [round(float(value), 6) for value in maximum],
            },
            "evaluated_action": action_test,
            "action_deformation_finite": action_safe,
            "action_deformation_meaningful": action_meaningful,
            "hierarchy_scale_notes": [
                {
                    "object": obj.name,
                    "parent": obj.parent.name if obj.parent else None,
                    "scale": [round(float(value), 6) for value in obj.scale],
                }
                for obj in objects
                if obj.type in {"EMPTY", "ARMATURE"}
            ],
        }
        return report
    finally:
        for obj in [obj for obj in bpy.data.objects if obj not in before_objects]:
            bpy.data.objects.remove(obj, do_unlink=True)
        for action in [item for item in bpy.data.actions if item not in before_actions]:
            bpy.data.actions.remove(action, do_unlink=True)
        for mesh in [item for item in bpy.data.meshes if item not in before_meshes]:
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        for armature in [
            item for item in bpy.data.armatures if item not in before_armatures
        ]:
            if armature.users == 0:
                bpy.data.armatures.remove(armature)
        for material in [
            item for item in bpy.data.materials if item not in before_materials
        ]:
            if material.users == 0:
                bpy.data.materials.remove(material)
        for image in [item for item in bpy.data.images if item not in before_images]:
            if image.users == 0:
                bpy.data.images.remove(image)


def validate_clean_reimport(context, filepath, contract, expected_height):
    """Validate in a separate factory-clean Blender process."""

    glb = Path(bpy.path.abspath(str(filepath))).resolve()
    if not glb.is_file():
        raise RuntimeError(f"Rigged GLB does not exist: {glb}")
    contract_path = glb.with_suffix(glb.suffix + ".contract.tmp.json")
    report_path = glb.with_suffix(glb.suffix + ".reimport.json")
    contract_path.write_text(
        json.dumps(contract, sort_keys=True),
        encoding="utf-8",
    )
    runner = Path(__file__).with_name("reimport_runner.py").resolve()
    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--python",
        str(runner),
        "--",
        "--glb",
        str(glb),
        "--contract",
        str(contract_path),
        "--height",
        str(float(expected_height)),
        "--report",
        str(report_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )
    finally:
        contract_path.unlink(missing_ok=True)
    if not report_path.is_file():
        raise RuntimeError(
            "Clean reimport did not produce a report. "
            + completed.stderr[-1000:]
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["clean_factory_process"] = True
    report["process_return_code"] = completed.returncode
    report["process_stdout_tail"] = completed.stdout[-2000:]
    report["process_stderr_tail"] = completed.stderr[-2000:]
    if completed.returncode:
        report["status"] = "CLEAN_REIMPORT_FAILED"
    return report
