"""Exercise automatic retained-hand fitting in the currently opened fixture."""

import json
import os
from pathlib import Path
import sys

import bpy


addon = str((Path.cwd() / "addon").resolve())
existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    existing.unregister()
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, addon)

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.rigging.deformation import (  # noqa: E402
    audit_rest_orientation,
)
from skin_and_bones_forge.rigging.analysis import evaluated_points  # noqa: E402


skin_and_bones_forge.register()
if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
    bpy.ops.object.mode_set(mode="OBJECT")

settings = bpy.context.scene.sbf_settings
fit_result = bpy.ops.sbf.fit_skeleton_preview()
fitted = bpy.data.objects["SBF_FittedSkeletonPreview"]
contract = json.loads(settings.rig_production_contract_json)
payload = json.loads(settings.target_analysis_json)
rest = audit_rest_orientation(
    settings.canonical_armature, fitted, contract, payload["analysis"]
)
validate_result = bpy.ops.sbf.validate_fitted_skeleton()
validation = json.loads(settings.rig_validation_json)

assert "FINISHED" in fit_result
assert rest["status"] == "READY_FOR_ANIMATION_TEST", rest["blocking_bones"]
assert not rest["blocking_bones"]
assert "FINISHED" in validate_result, validation["errors"]
assert validation["maximum_landmark_residual"] <= 1.0e-5
for side in ("left", "right"):
    hand = fitted.data.bones[f"arm_{side}_hand"]
    forearm = fitted.data.bones[f"arm_{side}_bot"]
    assert (hand.tail_local - hand.head_local).dot(
        forearm.tail_local - forearm.head_local
    ) > 0.0

full_results = {}
if os.environ.get("SBF_FULL_RIG_REGRESSION") == "1":
    bind_result = bpy.ops.sbf.bind_production_character()
    target = settings.target_object
    root_group = target.vertex_groups.get("root")
    assert root_group is not None
    root_surface_vertices = (
        sum(
            1
            for vertex in target.data.vertices
            if root_group is not None
            and any(
                item.group == root_group.index and item.weight >= 1.0e-4
                for item in vertex.groups
            )
        )
        if root_group is not None
        else 0
    )
    assert root_surface_vertices == 0, root_surface_vertices
    audit_result = bpy.ops.sbf.validate_production_weights()
    assert "FINISHED" in audit_result
    assert settings.rig_weight_status == "READY_FOR_ANIMATION_TEST"
    for bone in fitted.pose.bones:
        bone.matrix_basis.identity()
    fitted.data.pose_position = "POSE"
    bpy.context.view_layer.update()
    manual_rest = evaluated_points(bpy.context, target)
    manual_bone = fitted.pose.bones["leg_right_top"]
    manual_matrix_before = [list(row) for row in manual_bone.matrix]
    manual_bone.rotation_mode = "XYZ"
    manual_bone.rotation_euler[0] = 0.35
    bpy.context.view_layer.update()
    manual_matrix_after = [list(row) for row in manual_bone.matrix]
    manual_pose = evaluated_points(bpy.context, target)
    manual_pose_displacement = max(
        (after - before).length
        for before, after in zip(manual_rest, manual_pose)
    )
    assert target.name in bpy.context.view_layer.objects
    assert manual_pose_displacement > settings.target_height * 1.0e-5
    manual_bone.matrix_basis.identity()
    bpy.context.view_layer.update()
    try:
        pose_result = bpy.ops.sbf.run_pose_torture_tests()
    except RuntimeError:
        pose_result = {"CANCELLED"}
    pose_report = json.loads(settings.rig_pose_test_json)
    if settings.rig_pose_test_status != "POSE_TESTS_PASSED":
        isolated = pose_report.get("isolated_bone_forensics", {})
        print(
            "SBF_HAND_FIT_POSE_FAILURE",
            json.dumps(
                {
                    "status": pose_report.get("status"),
                    "unsafe": [
                        {
                            "bone": item.get("bone"),
                            "axis": item.get("axis"),
                            "maximum_edge_stretch_ratio": item.get(
                                "maximum_edge_stretch_ratio"
                            ),
                            "maximum_displacement": item.get(
                                "maximum_displacement"
                            ),
                            "meaningful_deformation": item.get(
                                "meaningful_deformation"
                            ),
                            "worst_edges": item.get("worst_edges", [])[:5],
                        }
                        for item in isolated.get("tests", [])
                        if not item.get("safe", False)
                    ],
                },
                sort_keys=True,
            ),
        )
        raise RuntimeError("Pose regression failed before canonical Actions.")
    try:
        action_result = bpy.ops.sbf.test_canonical_actions()
    except RuntimeError:
        action_result = {"CANCELLED"}
    action_report = json.loads(settings.rig_action_test_json)
    gate = action_report.get("pre_animation_gate", {})
    assert "FINISHED" in bind_result
    assert settings.rig_weight_status == "READY_FOR_ANIMATION_TEST"
    assert "FINISHED" in pose_result
    assert settings.rig_pose_test_status == "POSE_TESTS_PASSED"
    assert gate.get("status") == "READY_FOR_ANIMATION_TEST", gate
    if os.environ.get("SBF_REQUIRE_ACTION_PASS") == "1":
        assert action_report.get("status") == "CANONICAL_ACTIONS_PASSED"
    full_results = {
        "bind": sorted(bind_result),
        "weight_audit": sorted(audit_result),
        "weights": settings.rig_weight_status,
        "root_surface_vertices": root_surface_vertices,
        "manual_pose_displacement": manual_pose_displacement,
        "manual_bone_matrix_changed": manual_matrix_before != manual_matrix_after,
        "target": {
            "parent": target.parent.name if target.parent else None,
            "parent_type": target.parent_type,
            "matrix_world": [list(row) for row in target.matrix_world],
            "matrix_parent_inverse": [
                list(row) for row in target.matrix_parent_inverse
            ],
            "show_only_shape_key": target.show_only_shape_key,
            "shape_keys": (
                [key.name for key in target.data.shape_keys.key_blocks]
                if target.data.shape_keys
                else []
            ),
            "modifiers": [
                {
                    "name": modifier.name,
                    "type": modifier.type,
                    "show_viewport": modifier.show_viewport,
                    "show_render": modifier.show_render,
                }
                for modifier in target.modifiers
            ],
        },
        "armature": {
            "pose_position": fitted.data.pose_position,
            "matrix_world": [list(row) for row in fitted.matrix_world],
            "deform_bones": [
                bone.name for bone in fitted.data.bones if bone.use_deform
            ],
            "hide_viewport": fitted.hide_viewport,
            "hide_get": fitted.hide_get(),
            "users_collection": [
                collection.name for collection in fitted.users_collection
            ],
        },
        "armature_modifiers": [
            {
                "name": modifier.name,
                "show_viewport": modifier.show_viewport,
                "show_render": modifier.show_render,
                "use_vertex_groups": modifier.use_vertex_groups,
                "use_bone_envelopes": modifier.use_bone_envelopes,
                "vertex_group": modifier.vertex_group,
                "invert_vertex_group": modifier.invert_vertex_group,
                "use_deform_preserve_volume": modifier.use_deform_preserve_volume,
                "object": modifier.object.name if modifier.object else None,
            }
            for modifier in target.modifiers
            if modifier.type == "ARMATURE"
        ],
        "pose": sorted(pose_result),
        "pose_status": settings.rig_pose_test_status,
        "action": sorted(action_result),
        "action_status": settings.rig_action_test_status,
        "action_gate": gate.get("status"),
        "missing_actions": action_report.get("missing_actions", []),
        "filtered_action_count": action_report.get("filtered_action_count", 0),
        "action_failures": [
            {
                "action": item.get("action"),
                "first_unsafe_frame": item.get(
                    "deformation_forensics", {}
                ).get("first_unsafe_frame"),
                "worst_frame": item.get("deformation_forensics", {}).get(
                    "worst_frame"
                ),
                "maximum_edge_stretch_ratio": item.get(
                    "deformation_forensics", {}
                ).get("maximum_edge_stretch_ratio"),
                "meaningful_deformation": item.get("meaningful_deformation"),
                "missing_bones": item.get("missing_bones", []),
                "assignment_error": item.get("assignment_error", ""),
                "resolved_animated_bones": item.get(
                    "resolved_animated_bones", []
                ),
                "sample_frames": item.get("sample_frames", []),
                "unsafe_frames": [
                    frame
                    for frame in item.get("deformation_forensics", {}).get(
                        "frames", []
                    )
                    if not frame.get("safe", False)
                ][:5],
                "worst_edges": item.get("deformation_forensics", {}).get(
                    "worst_edges", []
                )[:5],
                "worst_vertices": item.get(
                    "deformation_forensics", {}
                ).get("worst_vertices", [])[:5],
            }
            for item in action_report.get("actions", [])
            if not item.get("deformation_safe", False)
        ],
    }

print(
    "SBF_HAND_FIT_REGRESSION",
    json.dumps(
        {
            "fit": sorted(fit_result),
            "validation": validation["status"],
            "maximum_residual": validation["maximum_landmark_residual"],
            "expected_binding_state_change": validation[
                "expected_binding_state_change"
            ],
            "rest": rest["status"],
            "full_results": full_results,
            "hands": {
                side: {
                    "head": list(
                        fitted.data.bones[f"arm_{side}_hand"].head_local
                    ),
                    "tail": list(
                        fitted.data.bones[f"arm_{side}_hand"].tail_local
                    ),
                }
                for side in ("left", "right")
            },
        },
        sort_keys=True,
    ),
)
