"""Blender 5.1.2 runtime regression for the Bones vertical slice.

Run with the canonical .blend already open:

    blender canonical.blend --background --python scripts/run_rig_fixture_test.py \
        -- --target target.glb --addon addon
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--reference-glb", type=Path)
    parser.add_argument(
        "--forge-repo",
        type=Path,
        default=Path(r"E:\DeVForge\dreadstone_animation_forge"),
    )
    return parser.parse_args(argv)


def _animation_snapshot(armature):
    animation = armature.animation_data
    return {
        "actions": [
            {
                "name": action.name,
                "frame_range": [float(value) for value in action.frame_range],
                "users": action.users,
                "slots": [slot.name_display for slot in action.slots],
            }
            for action in bpy.data.actions
        ],
        "active_action": (
            animation.action.name if animation and animation.action else None
        ),
        "nla": [
            {
                "name": track.name,
                "mute": track.mute,
                "solo": track.is_solo,
                "strips": [
                    {
                        "name": strip.name,
                        "action": strip.action.name if strip.action else None,
                        "start": strip.frame_start,
                        "end": strip.frame_end,
                    }
                    for strip in track.strips
                ],
            }
            for track in animation.nla_tracks
        ]
        if animation
        else [],
    }


def _assert_operator(result, name):
    assert "FINISHED" in result, f"{name} failed: {result}"


args = _args()
addon_path = str(args.addon.resolve())
if addon_path not in sys.path:
    sys.path.insert(0, addon_path)
existing_addon = sys.modules.get("skin_and_bones_forge")
if existing_addon is not None and hasattr(existing_addon, "unregister"):
    try:
        existing_addon.unregister()
    except RuntimeError:
        pass
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.constants import (  # noqa: E402
    RIG_ARMATURE_MODIFIER,
    RIG_CORRECTIONS_PROPERTY,
    RIG_PREVIEW_COLLECTION,
    RIG_PRODUCTION_ARMATURE,
    RIG_TEMP_COLLECTION,
)
from skin_and_bones_forge.rigging import (  # noqa: E402
    HAND_POSES,
    RESERVED_HAND_SHAPE_KEYS,
    SIMPLE_HANDS_PROFILE,
    analyze_canonical_rig,
    derive_simplified_contract,
    hand_metrics,
    iter_action_fcurves,
    pose_transforms_finite,
    topology_snapshot,
)


PROTECTED_TOPOLOGY_KEYS = (
    "vertices",
    "edges",
    "polygons",
    "loops",
    "vertex_positions",
    "polygon_vertices",
    "uv_layers",
    "materials",
)


def _protected_topology(snapshot):
    return {key: snapshot[key] for key in PROTECTED_TOPOLOGY_KEYS}


def _pose_matrices(armature):
    return {
        bone.name: [float(value) for row in bone.matrix_basis for value in row]
        for bone in armature.pose.bones
    }


def _assert_pose_equal(actual, expected, tolerance=1.0e-6):
    assert actual.keys() == expected.keys()
    assert max(
        abs(first - second)
        for name in actual
        for first, second in zip(actual[name], expected[name])
    ) <= tolerance


def _action_content_snapshot(actions):
    return {
        action.name: {
            "frame_range": [round(float(value), 6) for value in action.frame_range],
            "markers": [
                (marker.name, round(float(marker.frame), 6))
                for marker in action.pose_markers
            ],
            "curves": [
                {
                    "path": curve.data_path,
                    "index": int(curve.array_index),
                    "points": [
                        {
                            "co": [round(float(value), 6) for value in point.co],
                            "left": [
                                round(float(value), 6)
                                for value in point.handle_left
                            ],
                            "right": [
                                round(float(value), 6)
                                for value in point.handle_right
                            ],
                            "interpolation": point.interpolation,
                        }
                        for point in curve.keyframe_points
                    ],
                }
                for curve in iter_action_fcurves(action)
            ],
        }
        for action in actions
    }


source = next(obj for obj in bpy.data.objects if obj.type == "ARMATURE")
source_action_count = len(bpy.data.actions)
source_bone_names = [bone.name for bone in source.data.bones]
source_hierarchy = [
    (bone.name, bone.parent.name if bone.parent else None)
    for bone in source.data.bones
]
source_deform_flags = {
    bone.name: bone.use_deform for bone in source.data.bones
}

# Prove fingerprinting ignores evaluated animation and restores evaluation state.
base_contract = analyze_canonical_rig(bpy.context, source)
production_contract = derive_simplified_contract(base_contract)
repeat_production_contract = derive_simplified_contract(base_contract)
assert production_contract == repeat_production_contract
assert production_contract["profile_id"] == SIMPLE_HANDS_PROFILE
assert production_contract["source_fingerprint"] == base_contract["fingerprint"]
assert production_contract["source_bone_count"] == 57
assert production_contract["source_deform_bone_count"] == 57
assert production_contract["production_bone_count"] == 21
assert production_contract["production_deform_bone_count"] == 21
assert len(production_contract["removed_bones"]) == 36
production_bone_names = [
    bone["name"] for bone in production_contract["bones"]
]
production_hierarchy = [
    (bone["name"], bone["parent"]) for bone in production_contract["bones"]
]
production_deform_flags = {
    bone["name"]: bool(bone["deform"])
    for bone in production_contract["bones"]
}
removed_bones = set(production_contract["removed_bones"])
assert set(production_bone_names) == set(source_bone_names) - removed_bones
assert production_contract["retained_hand_bones"] == {
    "left": "arm_left_hand",
    "right": "arm_right_hand",
}
source_actions = [
    bpy.data.actions[item["name"]]
    for item in base_contract["animation_inventory"]["actions"]
]
source_action_contents = _action_content_snapshot(source_actions)
animation = source.animation_data_create()
animation.action = bpy.data.actions[0]
if animation.nla_tracks:
    animation.nla_tracks[0].mute = False
source.data.pose_position = "POSE"
pose_bone = source.pose.bones[0]
pose_bone.location = Vector((0.125, -0.25, 0.375))
bpy.context.scene.frame_set(17)
animated_state = {
    "frame": bpy.context.scene.frame_current,
    "pose_position": source.data.pose_position,
    "pose_location": list(pose_bone.location),
    "animation": _animation_snapshot(source),
}
animated_contract = analyze_canonical_rig(bpy.context, source)
assert animated_contract["fingerprint"] == base_contract["fingerprint"]
assert bpy.context.scene.frame_current == animated_state["frame"]
assert source.data.pose_position == animated_state["pose_position"]
assert list(pose_bone.location) == animated_state["pose_location"]
assert _animation_snapshot(source) == animated_state["animation"]

before_objects = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=str(args.target.resolve()))
new_meshes = [
    obj
    for obj in bpy.data.objects
    if obj not in before_objects and obj.type == "MESH"
]
assert len(new_meshes) == 1, f"Expected one imported target, found {len(new_meshes)}"
target = new_meshes[0]
target_before = topology_snapshot(target)
target_modifier_count = len(target.modifiers)
target_group_count = len(target.vertex_groups)

skin_and_bones_forge.register()
try:
    settings = bpy.context.scene.sbf_settings
    settings.canonical_armature = source
    settings.target_object = target
    settings.forward_axis = "+Y"
    settings.up_axis = "+Z"

    _assert_operator(bpy.ops.sbf.analyze_canonical_rig(), "canonical analysis")
    first_fingerprint = settings.canonical_fingerprint
    _assert_operator(bpy.ops.sbf.analyze_canonical_rig(), "repeat canonical analysis")
    assert settings.canonical_fingerprint == first_fingerprint
    settings.canonical_report_path = str(
        (Path.cwd() / "build" / "rig_fixture" / "canonical_report.json").resolve()
    )
    _assert_operator(bpy.ops.sbf.write_rig_report(), "canonical report")
    assert Path(settings.canonical_report_path).is_file()

    _assert_operator(bpy.ops.sbf.analyze_target_humanoid(), "target analysis")
    first_analysis = settings.target_analysis_json
    _assert_operator(bpy.ops.sbf.analyze_target_humanoid(), "repeat target analysis")
    assert settings.target_analysis_json == first_analysis

    _assert_operator(bpy.ops.sbf.generate_rig_landmarks(), "landmark preview")
    collection = bpy.data.collections[RIG_PREVIEW_COLLECTION]
    first_handle_count = len(
        [obj for obj in collection.objects if obj.type == "EMPTY"]
    )
    assert first_handle_count >= 16

    _assert_operator(bpy.ops.sbf.fit_skeleton_preview(), "skeleton fit")
    fitted = next(obj for obj in collection.objects if obj.type == "ARMATURE")
    assert [bone.name for bone in fitted.data.bones] == production_bone_names
    assert [
        (bone.name, bone.parent.name if bone.parent else None)
        for bone in fitted.data.bones
    ] == production_hierarchy
    assert {
        bone.name: bone.use_deform for bone in fitted.data.bones
    } == production_deform_flags
    assert not (removed_bones & {bone.name for bone in fitted.data.bones})
    assert fitted.data.bones["arm_left_hand"].parent.name == "arm_left_bot"
    assert fitted.data.bones["arm_right_hand"].parent.name == "arm_right_bot"
    assert fitted.parent is None

    # Repeating fit replaces only the armature and does not leak handles.
    _assert_operator(bpy.ops.sbf.fit_skeleton_preview(), "repeat skeleton fit")
    assert len([obj for obj in collection.objects if obj.type == "ARMATURE"]) == 1
    assert len([obj for obj in collection.objects if obj.type == "EMPTY"]) == first_handle_count

    pelvis = bpy.data.objects["SBF_Landmark_pelvis"]
    pelvis.location.x += 0.01
    _assert_operator(bpy.ops.sbf.refit_from_corrections(), "corrected refit")
    assert RIG_CORRECTIONS_PROPERTY in target
    correction_json = target[RIG_CORRECTIONS_PROPERTY]
    _assert_operator(bpy.ops.sbf.refit_from_corrections(), "correction reapply")
    assert target[RIG_CORRECTIONS_PROPERTY] == correction_json

    # Automatic side convention: anatomical left is up x forward (viewer-right
    # for a front-facing character). Reset corrections so every assertion below
    # exercises automatic landmarks only.
    _assert_operator(bpy.ops.sbf.reset_rig_landmarks(), "landmark reset")
    assert RIG_CORRECTIONS_PROPERTY not in target
    collection = bpy.data.collections[RIG_PREVIEW_COLLECTION]
    analysis = json.loads(settings.target_analysis_json)["analysis"]
    anatomical_left = Vector(analysis["up_axis_world"]).cross(
        Vector(analysis["forward_axis_world"])
    ).normalized()
    lateral = Vector(analysis["lateral_axis_world"]).normalized()
    assert lateral.dot(anatomical_left) > 0.999999
    handles = {
        obj["sbf_landmark_name"]: obj
        for obj in collection.objects
        if obj.type == "EMPTY" and "sbf_landmark_name" in obj
    }
    side_joints = ("shoulder", "elbow", "wrist", "hip", "knee", "ankle")
    for joint in side_joints:
        assert (
            handles[f"{joint}_left"].location
            - handles[f"{joint}_right"].location
        ).dot(anatomical_left) > 0.0

    _assert_operator(bpy.ops.sbf.fit_skeleton_preview(), "automatic side fit")
    fitted = next(obj for obj in collection.objects if obj.type == "ARMATURE")
    fitted_joints = {
        "shoulder": ("shoulder_left", "shoulder_right", "tail_local"),
        "elbow": ("arm_left_top", "arm_right_top", "tail_local"),
        "wrist": ("arm_left_bot", "arm_right_bot", "tail_local"),
        "hip": ("leg_left_top", "leg_right_top", "head_local"),
        "knee": ("leg_left_top", "leg_right_top", "tail_local"),
        "ankle": ("leg_left_bot", "leg_right_bot", "tail_local"),
    }
    for joint, (left_name, right_name, endpoint) in fitted_joints.items():
        left = fitted.matrix_world @ getattr(fitted.data.bones[left_name], endpoint)
        right = fitted.matrix_world @ getattr(fitted.data.bones[right_name], endpoint)
        assert (left - right).dot(anatomical_left) > 0.0, joint
    _assert_operator(
        bpy.ops.sbf.validate_fitted_skeleton(), "automatic side validation"
    )
    side_validation = json.loads(settings.rig_validation_json)
    assert not side_validation["left_right_inversion"]

    assert fitted.get("sbf_hand_pose") == "RELAXED"
    pose_metrics = {}
    pose_signatures = {}
    for pose_name in HAND_POSES:
        settings.rig_hand_pose = pose_name
        _assert_operator(bpy.ops.sbf.apply_hand_pose(), f"{pose_name} hand pose")
        bpy.context.view_layer.update()
        assert not pose_transforms_finite(fitted)
        metrics = hand_metrics(fitted, settings.target_height)
        assert metrics["pose"] == pose_name
        assert set(metrics["owned_presets"]) == set(HAND_POSES)
        assert set(metrics["reserved_shape_keys"]) == set(
            RESERVED_HAND_SHAPE_KEYS
        )
        pose_metrics[pose_name] = metrics
        pose_signatures[pose_name] = tuple(
            round(float(value), 5)
            for pose_bone in (
                fitted.pose.bones["arm_left_hand"],
                fitted.pose.bones["arm_right_hand"],
            )
            for row in pose_bone.matrix_basis
            for value in row
        )
    assert len(set(pose_signatures.values())) == len(HAND_POSES)
    settings.rig_hand_pose = "RELAXED"
    _assert_operator(bpy.ops.sbf.apply_hand_pose(), "restore RELAXED hand pose")
    relaxed_metrics = hand_metrics(fitted, settings.target_height)
    print("SBF_HAND_METRICS")
    print(json.dumps(relaxed_metrics, indent=2, sort_keys=True))
    assert relaxed_metrics["compact"], relaxed_metrics["warnings"]
    for side in ("left", "right"):
        assert relaxed_metrics[side]["parent"] == f"arm_{side}_bot"
        assert relaxed_metrics[side]["length_to_height"] <= 0.12

    validation_result = bpy.ops.sbf.validate_fitted_skeleton()
    assert "FINISHED" in validation_result, settings.rig_blocking_warnings
    assert settings.rig_validation_state in {
        "READY_FOR_BINDING",
        "NEEDS_ARTIST_CORRECTION",
    }
    fitted_validation = settings.rig_validation_state

    target_after = topology_snapshot(target)
    assert target_after == target_before
    assert len(target.modifiers) == target_modifier_count
    assert len(target.vertex_groups) == target_group_count
    assert len(bpy.data.actions) == source_action_count
    assert _animation_snapshot(source) == animated_state["animation"]

    # Forced transaction failure must restore the complete original binding state.
    rollback_parent = target.parent
    rollback_parent_inverse = target.matrix_parent_inverse.copy()
    rollback_world = target.matrix_world.copy()
    rollback_groups = [group.name for group in target.vertex_groups]
    rollback_modifiers = [
        (modifier.name, modifier.type) for modifier in target.modifiers
    ]
    settings.rig_force_binding_failure = True
    forced_error = ""
    try:
        forced_result = bpy.ops.sbf.bind_production_character()
        assert "CANCELLED" in forced_result
    except RuntimeError as exc:
        forced_error = str(exc)
    assert "Forced binding failure" in forced_error or "CANCELLED" in forced_result
    settings.rig_force_binding_failure = False
    assert target.parent == rollback_parent
    assert target.matrix_parent_inverse == rollback_parent_inverse
    assert target.matrix_world == rollback_world
    assert [group.name for group in target.vertex_groups] == rollback_groups
    assert [
        (modifier.name, modifier.type) for modifier in target.modifiers
    ] == rollback_modifiers
    assert _protected_topology(topology_snapshot(target)) == _protected_topology(
        target_before
    )
    assert bpy.data.collections.get(RIG_TEMP_COLLECTION) is None

    _assert_operator(
        bpy.ops.sbf.bind_production_character(), "production binding"
    )
    first_weight_report = json.loads(settings.rig_weight_report_json)
    assert first_weight_report["unweighted_vertices"] == 0
    assert first_weight_report["non_normalized_vertices"] == 0
    assert first_weight_report["maximum_influences"] <= 4
    assert first_weight_report["vertices_exceeding_influence_limit"] == 0
    assert first_weight_report["non_deform_weights"] == 0
    assert first_weight_report["non_finite_or_negative_weights"] == 0
    assert first_weight_report["anatomically_impossible_weights"] == 0
    assert not first_weight_report["anatomically_impossible_components"]
    assert first_weight_report["bind_matrices_consistent"]
    assert not first_weight_report["left_right_inversion"]
    assert not first_weight_report["empty_deform_groups"]
    assert first_weight_report["topology_unchanged"]
    assert first_weight_report["component_count"] == 2360
    assert not first_weight_report["removed_weight_groups_present"]
    assert first_weight_report["production_profile"] == SIMPLE_HANDS_PROFILE
    assert (
        first_weight_report["production_fingerprint"]
        == production_contract["fingerprint"]
    )
    for side in ("left", "right"):
        hand_summary = first_weight_report["hand_summary"][side]
        assert hand_summary["retained_bone"] == f"arm_{side}_hand"
        assert hand_summary["weighted_vertices"] > 0
        merge = first_weight_report["donor_hand_weight_merge"][side]
        assert merge["retained_hand_bone"] == f"arm_{side}_hand"
        assert merge["vertices_merged"] > 0
        assert merge["summed_weight"] > 0.0
        assert merge["removed_groups"]
        assert set(merge["removed_groups"]) <= removed_bones
    assert len(target.vertex_groups) == 21
    assert not (removed_bones & {group.name for group in target.vertex_groups})
    owned_armature_modifiers = [
        modifier
        for modifier in target.modifiers
        if modifier.type == "ARMATURE"
        and modifier.name == RIG_ARMATURE_MODIFIER
    ]
    assert len(owned_armature_modifiers) == 1
    assert target.parent == fitted
    assert bpy.data.collections.get(RIG_TEMP_COLLECTION) is None

    # A repeat bind updates in place without group or modifier duplication.
    _assert_operator(
        bpy.ops.sbf.bind_production_character(), "repeat production binding"
    )
    assert len(target.vertex_groups) == 21
    assert not (removed_bones & {group.name for group in target.vertex_groups})
    assert (
        len(
            [
                modifier
                for modifier in target.modifiers
                if modifier.type == "ARMATURE"
                and modifier.name == RIG_ARMATURE_MODIFIER
            ]
        )
        == 1
    )
    _assert_operator(
        bpy.ops.sbf.validate_production_weights(), "weight validation"
    )
    weight_report = json.loads(settings.rig_weight_report_json)
    assert settings.rig_weight_status == "READY_FOR_POSE_TEST"
    assert weight_report["unweighted_vertices"] == 0
    assert weight_report["non_normalized_vertices"] == 0
    assert weight_report["maximum_influences"] <= 4
    assert weight_report["non_deform_weights"] == 0
    assert not weight_report["empty_deform_groups"]
    assert not weight_report["removed_weight_groups_present"]

    production_animation_before = _animation_snapshot(fitted)
    production_pose_before = _pose_matrices(fitted)
    frame_before_pose_tests = bpy.context.scene.frame_current
    _assert_operator(
        bpy.ops.sbf.run_pose_torture_tests(), "pose torture tests"
    )
    pose_report = json.loads(settings.rig_pose_test_json)
    assert pose_report["status"] == "POSE_TESTS_PASSED"
    assert len(pose_report["tests"]) >= 14
    assert all(item["safe"] for item in pose_report["tests"])
    assert not any(
        action.get("sbf_temporary_pose_test", False)
        for action in bpy.data.actions
    )
    assert bpy.context.scene.frame_current == frame_before_pose_tests
    assert _animation_snapshot(fitted) == production_animation_before
    _assert_pose_equal(_pose_matrices(fitted), production_pose_before)

    try:
        action_operator_result = bpy.ops.sbf.test_canonical_actions()
    except RuntimeError:
        print("SBF_CANONICAL_ACTION_FAILURE")
        print(json.dumps(json.loads(settings.rig_action_test_json), indent=2))
        raise
    _assert_operator(action_operator_result, "canonical Action tests")
    action_report = json.loads(settings.rig_action_test_json)
    assert action_report["status"] == "CANONICAL_ACTIONS_PASSED"
    assert len(action_report["actions"]) == 5
    assert action_report["filtered_action_count"] == 5
    assert action_report["removed_finger_channel_count"] > 0
    assert all(item["deformation_safe"] for item in action_report["actions"])
    assert all(item["meaningful_deformation"] for item in action_report["actions"])
    assert all(not item["missing_bones"] for item in action_report["actions"])
    assert all(
        set(channel["bone"] for channel in item["removed_finger_channels"])
        <= removed_bones
        for item in action_report["actions"]
    )
    assert _animation_snapshot(fitted) == production_animation_before
    _assert_pose_equal(_pose_matrices(fitted), production_pose_before)
    assert _animation_snapshot(source) == animated_state["animation"]
    assert _action_content_snapshot(source_actions) == source_action_contents

    _assert_operator(
        bpy.ops.sbf.finalize_production_rig(), "production finalization"
    )
    assert fitted.name == RIG_PRODUCTION_ARMATURE
    assert [bone.name for bone in fitted.data.bones] == production_bone_names
    assert fitted["sbf_production_profile"] == SIMPLE_HANDS_PROFILE
    assert (
        fitted["sbf_production_fingerprint"]
        == production_contract["fingerprint"]
    )
    production_actions = [
        action
        for action in bpy.data.actions
        if action.get("sbf_production_action", False)
    ]
    assert len(production_actions) == 5
    assert all(
        not (_action_bones & removed_bones)
        for _action_bones in (
            {
                path.split('pose.bones["', 1)[1].split('"]', 1)[0]
                for curve in iter_action_fcurves(action)
                for path in (curve.data_path,)
                if 'pose.bones["' in path
            }
            for action in production_actions
        )
    )
    assert _action_content_snapshot(source_actions) == source_action_contents
    _assert_operator(
        bpy.ops.sbf.finalize_production_rig(), "repeat production finalization"
    )
    assert (
        len(
            [
                action
                for action in bpy.data.actions
                if action.get("sbf_production_action", False)
            ]
        )
        == 5
    )
    assert _action_content_snapshot(source_actions) == source_action_contents
    assert bpy.data.collections.get(RIG_PREVIEW_COLLECTION) is None
    assert bpy.data.collections.get(RIG_TEMP_COLLECTION) is None
    assert _protected_topology(topology_snapshot(target)) == _protected_topology(
        target_before
    )

    rigged_glb = (
        Path.cwd() / "build" / "rig_fixture" / "character_sbf_rigged.glb"
    ).resolve()
    settings.rigged_export_glb_path = str(rigged_glb)
    settings.rig_export_actions = True
    _assert_operator(bpy.ops.sbf.export_rigged_glb(), "rigged GLB export")
    assert rigged_glb.is_file()
    manifest_path = rigged_glb.with_suffix(rigged_glb.suffix + ".sbf.json")
    assert manifest_path.is_file()

    _assert_operator(
        bpy.ops.sbf.validate_clean_reimport(), "clean GLB reimport"
    )
    reimport_report = json.loads(settings.rig_reimport_json)
    assert reimport_report["status"] == "CLEAN_REIMPORT_PASSED"
    assert reimport_report["bone_names_match"]
    assert reimport_report["hierarchy_match"]
    assert reimport_report["deform_bone_count"] == 21
    assert reimport_report["profile_metadata_match"]
    assert not reimport_report["removed_finger_action_channels"]
    assert reimport_report["skinned_mesh_count"] == 1
    assert reimport_report["uv_maps"]
    assert reimport_report["materials"]
    assert reimport_report["action_deformation_meaningful"]

    settings.animation_forge_repository = str(args.forge_repo.resolve())
    _assert_operator(
        bpy.ops.sbf.run_animation_forge_acceptance(),
        "Animation Forge acceptance",
    )
    forge_report = json.loads(settings.rig_animation_forge_json)
    assert forge_report["status"] == "ANIMATION_FORGE_ACCEPTED"
    assert forge_report["actual_operator"] == "daf.analyze"
    assert forge_report["mesh_skinned"]
    assert forge_report["hierarchy_resolves"]
    assert forge_report["animation_generation_can_see_rig"]
    assert forge_report["filtered_actions_accepted"]
    assert not forge_report["missing_required_roles"]
    assert forge_report["mapping"]["hand_l"] == "arm_left_hand"
    assert forge_report["mapping"]["hand_r"] == "arm_right_hand"
    assert forge_report["depends_on_removed_finger_bones"] is False

    _assert_operator(
        bpy.ops.sbf.clean_temporary_rigging_data(), "temporary rigging cleanup"
    )
    assert bpy.data.collections.get(RIG_TEMP_COLLECTION) is None
    assert not any(
        action.get("sbf_temporary_pose_test", False)
        for action in bpy.data.actions
    )

    exported_reference = None
    if args.reference_glb:
        reference_before = set(bpy.data.objects)
        action_count_before_reference = len(bpy.data.actions)
        bpy.ops.import_scene.gltf(filepath=str(args.reference_glb.resolve()))
        imported_objects = [
            obj for obj in bpy.data.objects if obj not in reference_before
        ]
        imported_armatures = [
            obj for obj in imported_objects if obj.type == "ARMATURE"
        ]
        assert len(imported_armatures) == 1
        exported_armature = imported_armatures[0]
        assert [bone.name for bone in exported_armature.data.bones] == source_bone_names
        assert [
            (bone.name, bone.parent.name if bone.parent else None)
            for bone in exported_armature.data.bones
        ] == source_hierarchy
        imported_skinned_meshes = [
            obj
            for obj in imported_objects
            if obj.type == "MESH"
            and any(
                modifier.type == "ARMATURE"
                and modifier.object == exported_armature
                for modifier in obj.modifiers
            )
        ]
        assert len(imported_skinned_meshes) == 1
        exported_reference = {
            "armature": exported_armature.name,
            "bones": len(exported_armature.data.bones),
            "animations": len(bpy.data.actions) - action_count_before_reference,
            "skinned_mesh": imported_skinned_meshes[0].name,
            "parent": (
                exported_armature.parent.name
                if exported_armature.parent
                else None
            ),
        }

    result = {
        "status": "PASS",
        "blender": bpy.app.version_string,
        "canonical": {
            "armature": source.name,
            "bones": len(source_bone_names),
            "fingerprint": first_fingerprint,
            "actions": source_action_count,
            "nla_tracks": len(animation.nla_tracks),
        },
        "simplified_production_contract": {
            "profile": SIMPLE_HANDS_PROFILE,
            "fingerprint": production_contract["fingerprint"],
            "bones": len(production_bone_names),
            "removed_bones": production_contract["removed_bones"],
        },
        "target": {
            "object": target.name,
            "vertices": len(target.data.vertices),
            "polygons": len(target.data.polygons),
            "uv_layers": [layer.name for layer in target.data.uv_layers],
            "materials": [
                slot.material.name if slot.material else None
                for slot in target.material_slots
            ],
            "height": settings.target_height,
        },
        "landmark_confidence": settings.landmark_confidence_summary,
        "hand_validation": relaxed_metrics,
        "hand_poses_tested": list(pose_metrics),
        "validation": fitted_validation,
        "weight_report": weight_report,
        "pose_tests": pose_report,
        "canonical_action_tests": action_report,
        "rigged_glb": str(rigged_glb),
        "rigging_manifest": str(manifest_path),
        "clean_reimport": reimport_report,
        "animation_forge": forge_report,
        "target_protected_data_unchanged": True,
        "temporary_cleanup": True,
        "exported_reference_glb": exported_reference,
    }
    print("SBF_RIG_FIXTURE_RESULT")
    print(json.dumps(result, indent=2, sort_keys=True))
finally:
    if hasattr(bpy.types.Scene, "sbf_settings"):
        skin_and_bones_forge.unregister()
