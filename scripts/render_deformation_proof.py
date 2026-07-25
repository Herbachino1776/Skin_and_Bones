"""Render a deterministic proof frame from an already repaired Blender file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def _arguments():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesh", default="geometry_0")
    parser.add_argument("--armature", default="SBF_ProductionRig")
    parser.add_argument("--action", default="DSB_DRAFT_Walk")
    parser.add_argument("--frame", type=int, default=15)
    return parser.parse_args(argv)


def _look_at(obj, point):
    obj.rotation_euler = (point - obj.location).to_track_quat("-Z", "Y").to_euler()


args = _arguments()
mesh = bpy.data.objects.get(args.mesh)
armature = bpy.data.objects.get(args.armature)
action = bpy.data.actions.get(args.action)
if mesh is None or mesh.type != "MESH":
    raise RuntimeError(f"Proof mesh was not found: {args.mesh}")
if armature is None or armature.type != "ARMATURE":
    raise RuntimeError(f"Proof armature was not found: {args.armature}")
if action is None:
    raise RuntimeError(f"Proof Action was not found: {args.action}")

for obj in bpy.data.objects:
    if obj != mesh and obj.type in {"MESH", "ARMATURE", "EMPTY"}:
        obj.hide_render = True
mesh.hide_render = False
armature.hide_render = True

animation = armature.animation_data_create()
for track in animation.nla_tracks:
    track.mute = True
animation.action = action
armature.data.pose_position = "POSE"
bpy.context.scene.frame_set(args.frame)
bpy.context.view_layer.update()

corners = [mesh.matrix_world @ Vector(corner) for corner in mesh.bound_box]
minimum = Vector((min(p.x for p in corners), min(p.y for p in corners), min(p.z for p in corners)))
maximum = Vector((max(p.x for p in corners), max(p.y for p in corners), max(p.z for p in corners)))
center = (minimum + maximum) * 0.5
height = max(maximum.z - minimum.z, 0.1)

camera_data = bpy.data.cameras.new("SBF_ProofCamera")
camera = bpy.data.objects.new("SBF_ProofCamera", camera_data)
bpy.context.scene.collection.objects.link(camera)
camera.location = center + Vector((height * 1.35, -height * 2.8, height * 0.25))
camera.data.lens = 58
_look_at(camera, center + Vector((0.0, 0.0, height * 0.04)))
bpy.context.scene.camera = camera

for name, location, energy, size in (
    ("SBF_ProofKey", center + Vector((-height, -height * 1.5, height * 1.8)), 1100.0, 3.0),
    ("SBF_ProofFill", center + Vector((height * 1.8, height, height)), 700.0, 2.5),
):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    light = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(light)
    light.location = location
    _look_at(light, center)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 700
scene.render.resolution_y = 900
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = False
scene.render.filepath = str(args.output.resolve())
scene.world.color = (0.025, 0.025, 0.025)
args.output.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.render.render(write_still=True)
print("SBF_PROOF_RENDER", str(args.output.resolve()))
