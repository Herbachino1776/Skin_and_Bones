"""Regression for the disconnected-component explosion fixture."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import bpy


addon = str((Path.cwd() / "addon").resolve())
if addon not in sys.path:
    sys.path.insert(0, addon)
existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    existing.unregister()
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.rigging.analysis import evaluated_points  # noqa: E402


skin_and_bones_forge.register()
try:
    settings = bpy.context.scene.sbf_settings
    target = bpy.data.objects["geometry_0"]
    armature = bpy.data.objects["SBF_ProductionRig"]
    settings.target_object = target
    settings.canonical_armature = bpy.data.objects["rig"]

    result = bpy.ops.sbf.bind_production_character()
    assert "FINISHED" in result, result
    report = json.loads(settings.rig_weight_report_json)
    assert report["status"] == "READY_FOR_POSE_TEST"
    assert report["unweighted_vertices"] == 0
    assert report["non_normalized_vertices"] == 0
    assert report["non_finite_or_negative_weights"] == 0
    assert report["non_deform_weights"] == 0
    assert report["maximum_influences"] <= 4
    assert report["anatomically_impossible_weights"] == 0
    assert not report["anatomically_impossible_components"]
    assert report["bind_matrices_consistent"]
    assert not report["left_right_inversion"]

    assert "FINISHED" in bpy.ops.sbf.run_pose_torture_tests()
    pose_report = json.loads(settings.rig_pose_test_json)
    assert pose_report["status"] == "POSE_TESTS_PASSED"
    assert "FINISHED" in bpy.ops.sbf.test_canonical_actions()
    action_report = json.loads(settings.rig_action_test_json)
    assert action_report["status"] == "CANONICAL_ACTIONS_PASSED"

    animation = armature.animation_data_create()
    animation.action = None
    armature.data.pose_position = "POSE"
    for bone in armature.pose.bones:
        bone.matrix_basis.identity()
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    rest = evaluated_points(bpy.context, target)
    animation.action = bpy.data.actions["DSB_DRAFT_Walk"]
    maximum_displacement = 0.0
    for frame in range(1, 30):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        posed = evaluated_points(bpy.context, target)
        maximum_displacement = max(
            maximum_displacement,
            max(
                (point - rest_point).length
                for point, rest_point in zip(posed, rest)
            ),
        )

    output = (Path.cwd() / "build" / "explosion_fixture" / "fixed.glb").resolve()
    assert "FINISHED" in bpy.ops.sbf.finalize_production_rig()
    settings.rigged_export_glb_path = str(output)
    settings.rig_export_actions = True
    assert "FINISHED" in bpy.ops.sbf.export_rigged_glb()
    try:
        reimport_result = bpy.ops.sbf.validate_clean_reimport()
    except RuntimeError:
        print("SBF_REIMPORT_FAILURE", settings.rig_reimport_json)
        raise
    assert "FINISHED" in reimport_result
    reimport = json.loads(settings.rig_reimport_json)
    assert reimport["status"] == "CLEAN_REIMPORT_PASSED"
    print(
        "SBF_EXPLOSION_FIXTURE_RESULT",
        json.dumps(
            {
                "status": "PASS",
                "maximum_displacement": round(maximum_displacement, 6),
                "weights": report["status"],
                "pose_tests": pose_report["status"],
                "canonical_actions": action_report["status"],
                "reimport": reimport["status"],
            },
            sort_keys=True,
        ),
    )
finally:
    skin_and_bones_forge.unregister()
