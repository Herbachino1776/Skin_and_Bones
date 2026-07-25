"""Regression for the disconnected-component explosion fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


def _arguments():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-glb", type=Path)
    parser.add_argument("--output-blend", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--forge-repo",
        type=Path,
        default=Path(r"E:\DeVForge\dreadstone_animation_forge"),
    )
    return parser.parse_args(argv)


args = _arguments()
source_fixture = Path(bpy.data.filepath).resolve()


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
    assert report["status"] == "READY_FOR_ANIMATION_TEST"
    assert report["unweighted_vertices"] == 0
    assert report["non_normalized_vertices"] == 0
    assert report["non_finite_or_negative_weights"] == 0
    assert report["non_deform_weights"] == 0
    assert report["maximum_influences"] <= 4
    assert report["anatomically_impossible_weights"] == 0
    assert not report["anatomically_impossible_components"]
    assert report["bind_matrices_consistent"]
    assert not report["left_right_inversion"]
    print(
        "SBF_WEIGHT_RESULT",
        json.dumps(
            {
                key: report.get(key)
                for key in (
                    "status",
                    "proxy_fallback_vertex_count",
                    "repaired_component_count",
                    "tiny_rigid_component_assignments",
                    "anatomically_impossible_weights",
                    "opposite_side_contamination",
                    "maximum_bone_distance_excess",
                    "per_region_influences",
                    "cleanup",
                )
            },
            sort_keys=True,
        ),
    )

    try:
        pose_result = bpy.ops.sbf.run_pose_torture_tests()
    except RuntimeError:
        failed_pose = json.loads(settings.rig_pose_test_json)
        print(
            "SBF_POSE_FAILURE",
            json.dumps(
                {
                    "status": failed_pose.get("status"),
                    "isolated": [
                        {
                            key: item.get(key)
                            for key in (
                                "bone",
                                "axis",
                                "safe",
                                "maximum_edge_stretch_ratio",
                                "stretched_edges",
                                "worst_edges",
                            )
                        }
                        for item in failed_pose.get(
                            "isolated_bone_forensics", {}
                        ).get("tests", [])
                        if not item.get("safe", False)
                    ],
                },
                sort_keys=True,
            ),
        )
        raise
    assert "FINISHED" in pose_result
    pose_report = json.loads(settings.rig_pose_test_json)
    assert pose_report["status"] == "POSE_TESTS_PASSED"
    try:
        canonical_result = bpy.ops.sbf.test_canonical_actions()
    except RuntimeError:
        failed_actions = json.loads(settings.rig_action_test_json)
        print(
            "SBF_CANONICAL_FAILURE",
            json.dumps(
                [
                    {
                        "action": item.get("action"),
                        "safe": item.get("deformation_safe"),
                        "first_unsafe_frame": item.get(
                            "deformation_forensics", {}
                        ).get("first_unsafe_frame"),
                        "worst_frame": item.get(
                            "deformation_forensics", {}
                        ).get("worst_frame"),
                        "maximum_edge_stretch_ratio": item.get(
                            "deformation_forensics", {}
                        ).get("maximum_edge_stretch_ratio"),
                        "maximum_bounds_ratio": item.get(
                            "deformation_forensics", {}
                        ).get("maximum_bounds_ratio"),
                        "maximum_separated_components": max(
                            (
                                frame.get("separated_components", 0)
                                for frame in item.get(
                                    "deformation_forensics", {}
                                ).get("frames", [])
                            ),
                            default=0,
                        ),
                        "maximum_explosive_vertices": max(
                            (
                                frame.get("explosive_vertices", 0)
                                for frame in item.get(
                                    "deformation_forensics", {}
                                ).get("frames", [])
                            ),
                            default=0,
                        ),
                        "worst_edges": item.get(
                            "deformation_forensics", {}
                        ).get("worst_edges", [])[:5],
                    }
                    for item in failed_actions.get("actions", [])
                    if not item.get("deformation_safe", False)
                ],
                sort_keys=True,
            ),
        )
        raise
    assert "FINISHED" in canonical_result
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

    output = (
        args.output_glb.resolve()
        if args.output_glb
        else (Path.cwd() / "build" / "explosion_fixture" / "fixed.glb").resolve()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
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
    settings.animation_forge_repository = str(args.forge_repo.resolve())
    assert "FINISHED" in bpy.ops.sbf.run_animation_forge_acceptance()
    forge = json.loads(settings.rig_animation_forge_json)
    assert forge["status"] == "ANIMATION_FORGE_ACCEPTED"
    assert forge["walk_deformation"]["status"] == "READY_FOR_ANIMATION_TEST"
    assert (
        forge["additional_draft_deformation"]["status"]
        == "READY_FOR_ANIMATION_TEST"
    )
    if args.output_blend:
        args.output_blend.parent.mkdir(parents=True, exist_ok=True)
        assert "FINISHED" in bpy.ops.wm.save_as_mainfile(
            filepath=str(args.output_blend.resolve()),
            copy=True,
        )
    result_report = {
        "status": "PASS",
        "source_fixture": str(source_fixture),
        "output_glb": str(output),
        "output_blend": (
            str(args.output_blend.resolve()) if args.output_blend else None
        ),
        "maximum_displacement": round(maximum_displacement, 6),
        "weights": report,
        "pose_tests": pose_report,
        "canonical_actions": action_report,
        "reimport": reimport,
        "animation_forge": forge,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(result_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
                "animation_forge": forge["status"],
                "walk_edge_stretch": forge["walk_deformation"][
                    "maximum_edge_stretch_ratio"
                ],
                "hurt_edge_stretch": forge[
                    "additional_draft_deformation"
                ]["maximum_edge_stretch_ratio"],
                "report": str(args.report.resolve()) if args.report else None,
            },
            sort_keys=True,
        ),
    )
finally:
    skin_and_bones_forge.unregister()
