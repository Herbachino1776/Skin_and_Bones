"""Fit the bundled Y+ rig to an open humanoid fixture and render proof."""

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
    parser.add_argument("--addon", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--render", type=Path, required=True)
    return parser.parse_args(argv)


def _finished(result, label):
    if "FINISHED" not in result:
        raise RuntimeError(f"{label} did not finish: {sorted(result)}")


def _detach_target(target):
    matrix_world = target.matrix_world.copy()
    if target.parent is not None and target.parent.type == "ARMATURE":
        target.parent.data.pose_position = "REST"
        if target.parent.animation_data is not None:
            target.parent.animation_data_clear()
    for modifier in list(target.modifiers):
        if modifier.type == "ARMATURE":
            target.modifiers.remove(modifier)
    target.parent = None
    target.matrix_world = matrix_world
    for obj in list(bpy.data.objects):
        if obj != target:
            bpy.data.objects.remove(obj, do_unlink=True)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action, do_unlink=True)


def _bounds(obj):
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = Vector(min(point[index] for point in points) for index in range(3))
    maximum = Vector(max(point[index] for point in points) for index in range(3))
    return minimum, maximum


def _proof_render(target, armature, output):
    minimum, maximum = _bounds(target)
    center = (minimum + maximum) * 0.5
    height = maximum.z - minimum.z
    depth = max(maximum.y - minimum.y, height * 0.2)
    camera_data = bpy.data.cameras.new("SBF_YPlus_ProofCamera")
    camera = bpy.data.objects.new("SBF_YPlus_ProofCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = (
        center.x + height * 0.9,
        maximum.y + max(height * 1.8, depth * 4.0),
        center.z + height * 0.12,
    )
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = height * 1.18
    bpy.context.scene.camera = camera

    curve_data = bpy.data.curves.new("SBF_YPlus_RigProof", "CURVE")
    curve_data.dimensions = "3D"
    curve_data.bevel_depth = max(height * 0.0022, 0.001)
    curve_data.bevel_resolution = 2
    for bone in armature.data.bones:
        spline = curve_data.splines.new("POLY")
        spline.points.add(1)
        head = armature.matrix_world @ bone.head_local
        tail = armature.matrix_world @ bone.tail_local
        spline.points[0].co = (*head, 1.0)
        spline.points[1].co = (*tail, 1.0)
    curve = bpy.data.objects.new("SBF_YPlus_RigProof", curve_data)
    curve.color = (1.0, 0.18, 0.03, 1.0)
    bpy.context.scene.collection.objects.link(curve)

    arrow_data = bpy.data.meshes.new("SBF_YPlus_Arrow_Data")
    arrow_z = minimum.z + max(height * 0.008, 0.002)
    arrow_length = height * 0.28
    arrow_width = height * 0.018
    x = maximum.x + height * 0.08
    y0 = center.y - arrow_length * 0.5
    y1 = y0 + arrow_length * 0.72
    y2 = y0 + arrow_length
    arrow_data.from_pydata(
        [
            (x - arrow_width, y0, arrow_z),
            (x + arrow_width, y0, arrow_z),
            (x + arrow_width, y1, arrow_z),
            (x + arrow_width * 2.4, y1, arrow_z),
            (x, y2, arrow_z),
            (x - arrow_width * 2.4, y1, arrow_z),
            (x - arrow_width, y1, arrow_z),
        ],
        [],
        [(0, 1, 2, 3, 4, 5, 6)],
    )
    arrow = bpy.data.objects.new("SBF_World_YPlus_Arrow", arrow_data)
    arrow.color = (0.05, 0.8, 0.1, 1.0)
    bpy.context.scene.collection.objects.link(arrow)

    label_data = bpy.data.curves.new("SBF_YPlus_ProofLabel", "FONT")
    label_data.body = (
        "VIEW: WORLD +Y FRONT\n"
        "GREEN: +Y FORWARD   ORANGE: FITTED RIG"
    )
    label_data.align_x = "LEFT"
    label_data.align_y = "BOTTOM"
    label_data.size = height * 0.032
    label_data.extrude = height * 0.0002
    label = bpy.data.objects.new("SBF_YPlus_ProofLabel", label_data)
    label.parent = camera
    label.location = (
        -camera.data.ortho_scale * 0.48,
        -camera.data.ortho_scale * 0.48,
        -1.0,
    )
    label.color = (0.15, 0.9, 0.25, 1.0)
    bpy.context.scene.collection.objects.link(label)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.display.shading.cavity_type = "WORLD"
    target.color = (0.36, 0.48, 0.68, 1.0)
    scene.render.resolution_x = 768
    scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.035, 0.035, 0.035)
    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)


args = _args()
existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    try:
        existing.unregister()
    except RuntimeError:
        pass
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, str(args.addon.resolve()))
import skin_and_bones_forge  # noqa: E402


skin_and_bones_forge.register()
try:
    target = bpy.data.objects.get(args.target)
    if target is None or target.type != "MESH":
        raise RuntimeError(f"Target mesh not found: {args.target}")
    _detach_target(target)
    settings = bpy.context.scene.sbf_settings
    settings.target_object = target
    settings.forward_axis = "+Y"
    settings.up_axis = "+Z"
    settings.target_analysis_json = ""
    settings.canonical_contract_json = ""
    settings.rig_production_contract_json = ""
    _finished(bpy.ops.sbf.load_canonical_rig(), "canonical load")
    _finished(bpy.ops.sbf.load_canonical_rig(), "repeat canonical load")
    _finished(bpy.ops.sbf.analyze_target_humanoid(), "target analysis")
    _finished(bpy.ops.sbf.fit_skeleton_preview(), "skeleton fit")
    fitted = bpy.data.objects.get("SBF_FittedSkeletonPreview")
    if fitted is None:
        raise RuntimeError("Fitted skeleton preview was not created.")
    bone_names = [bone.name for bone in fitted.data.bones]
    foot_deltas = {
        side: round(
            float(
                fitted.data.bones[f"leg_{side}_foot"].tail_local.y
                - fitted.data.bones[f"leg_{side}_foot"].head_local.y
            ),
            6,
        )
        for side in ("left", "right")
    }
    if len(bone_names) != 21 or min(foot_deltas.values()) <= 0.0:
        raise RuntimeError("Fitted skeleton did not preserve the Y+ 21-bone contract.")
    templates = [
        obj
        for obj in bpy.data.objects
        if obj.get("sbf_canonical_asset", False)
    ]
    if len(templates) != 1:
        raise RuntimeError("Canonical template loading was not idempotent.")
    if fitted.get("sbf_forward_axis") != "+Y":
        raise RuntimeError("Fitted skeleton lacks +Y metadata.")
    _proof_render(target, fitted, args.render.resolve())
    report = {
        "status": "CANONICAL_FIT_FIXTURE_PASSED",
        "label": args.label,
        "source_blend": Path(bpy.data.filepath).name,
        "target": target.name,
        "template_count": len(templates),
        "fitted_armature": fitted.name,
        "bone_names": bone_names,
        "bone_count": len(bone_names),
        "rig_version": fitted.get("sbf_canonical_rig_version", ""),
        "forward_axis": fitted.get("sbf_forward_axis", ""),
        "up_axis": fitted.get("sbf_up_axis", ""),
        "unit_scale_meters": fitted.get("sbf_unit_scale_meters", 0.0),
        "foot_forward_y_deltas": foot_deltas,
        "object_transform": [list(row) for row in fitted.matrix_world],
        "target_transform": [list(row) for row in target.matrix_world],
        "proof_render": str(args.render.resolve()),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("SBF_CANONICAL_FIT_FIXTURE")
    print(json.dumps(report, indent=2, sort_keys=True))
finally:
    skin_and_bones_forge.unregister()
