"""Runtime regression for universal voxel auto-skin on a prepared Blender file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--addon", type=Path, default=Path("addon"))
parser.add_argument("--save-copy", type=Path)
args = parser.parse_args(argv)

existing = sys.modules.get("skin_and_bones_forge")
if existing is not None and hasattr(existing, "unregister"):
    existing.unregister()
for module_name in list(sys.modules):
    if module_name == "skin_and_bones_forge" or module_name.startswith(
        "skin_and_bones_forge."
    ):
        del sys.modules[module_name]
sys.path.insert(0, str(args.addon.resolve()))

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.rigging.analysis import (  # noqa: E402
    evaluated_points,
    topology_snapshot,
)
from skin_and_bones_forge.rigging.weights import (  # noqa: E402
    _bone_segments,
    _point_anatomy,
    _topology_preferred_families,
)


skin_and_bones_forge.register()
settings = bpy.context.scene.sbf_settings
target = settings.target_object
assert target is not None and target.type == "MESH"
protected_before = topology_snapshot(target)
settings.rig_binding_method = "VOXEL_HEAT_PROXY"
assert "FINISHED" in bpy.ops.sbf.bind_production_character()
report = json.loads(settings.rig_weight_report_json)
assert report["status"] == "READY_FOR_ANIMATION_TEST", report
assert report["binding_method"] == "VOXEL_HEAT_PROXY"
assert report["unweighted_vertices"] == 0
assert report["non_normalized_vertices"] == 0
assert report["maximum_influences"] <= 4
assert report["anatomically_impossible_weights"] == 0
assert report["opposite_side_contamination"] == 0
assert report["topology_unchanged"]
for key in (
    "vertices",
    "edges",
    "polygons",
    "loops",
    "vertex_positions",
    "polygon_vertices",
    "uv_layers",
    "materials",
):
    assert topology_snapshot(target)[key] == protected_before[key], key

contract = json.loads(settings.rig_production_contract_json)
removed = set(contract.get("removed_bones", []))
groups = {group.name for group in target.vertex_groups}
armature = target.parent
deform = {bone.name for bone in armature.data.bones if bone.use_deform}
assert len(deform) == 21
assert not (removed & groups)
assert not (removed & deform)

analysis = json.loads(settings.target_analysis_json)["analysis"]
up = Vector(analysis["up_axis_world"])
ground = float(analysis["ground"])
height = float(analysis["world_height"])
world_points = [target.matrix_world @ vertex.co for vertex in target.data.vertices]
preferred, _corrections = _topology_preferred_families(
    target, world_points, _bone_segments(armature)
)
group_names = {group.index: group.name for group in target.vertex_groups}
for bone in armature.pose.bones:
    bone.matrix_basis.identity()
bpy.context.view_layer.update()
rest = evaluated_points(bpy.context, target)
remote = {}
for side in ("left", "right"):
    pose_bone = armature.pose.bones[f"arm_{side}_top"]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler[1] = 1.0471975512
    bpy.context.view_layer.update()
    posed = evaluated_points(bpy.context, target)
    candidates = []
    for vertex, before, after in zip(target.data.vertices, rest, posed):
        fraction = (world_points[vertex.index].dot(up) - ground) / height
        region, _point_side = _point_anatomy(
            world_points[vertex.index], analysis
        )
        if (
            fraction > 0.48
            or region != "LEG"
            or preferred[vertex.index] in {"LEFT_ARM", "RIGHT_ARM"}
        ):
            continue
        arm_weight = sum(
            item.weight
            for item in vertex.groups
            if group_names.get(item.group, "").startswith("arm_")
        )
        candidates.append(((after - before).length, arm_weight))
    maximum_displacement = max((item[0] for item in candidates), default=0.0)
    maximum_arm_weight = max((item[1] for item in candidates), default=0.0)
    assert maximum_displacement <= height * 0.0015, maximum_displacement
    remote[side] = {
        "maximum_lower_leg_displacement": maximum_displacement,
        "maximum_lower_leg_arm_weight": maximum_arm_weight,
    }
    pose_bone.matrix_basis.identity()
    bpy.context.view_layer.update()

assert bpy.data.collections.get("SBF_RiggingTemporary") is None
if args.save_copy:
    args.save_copy.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.save_copy.resolve()), copy=True)
print(
    "SBF_VOXEL_HEAT_FIXTURE_RESULT",
    json.dumps(
        {
            "status": "PASS",
            "proxy": report["voxel_heat_proxy"],
            "remote_arm": remote,
            "excluded_finger_bones": len(removed),
            "topology_unchanged": True,
        },
        sort_keys=True,
    ),
)
