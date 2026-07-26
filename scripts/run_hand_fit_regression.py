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
    pose_result = bpy.ops.sbf.run_pose_torture_tests()
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
    full_results = {
        "bind": sorted(bind_result),
        "weights": settings.rig_weight_status,
        "pose": sorted(pose_result),
        "pose_status": settings.rig_pose_test_status,
        "action": sorted(action_result),
        "action_status": settings.rig_action_test_status,
        "action_gate": gate.get("status"),
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
