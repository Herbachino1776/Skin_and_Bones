import bpy
from mathutils import Vector
from pathlib import Path


OUT = Path(r"E:\Dev\Dread_Stone_Black\output\blender_texture_rebuild")
scene = bpy.context.scene
mesh_obj = next(obj for obj in bpy.data.objects if obj.type == "MESH")


def look_at(obj, point):
    direction = Vector(point) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.film_transparent = True
scene.view_settings.look = "AgX - Medium High Contrast"

world = scene.world or bpy.data.worlds.new("VerifyWorld")
scene.world = world
world.use_nodes = True
background = world.node_tree.nodes.get("Background")
background.inputs["Color"].default_value = (0.03, 0.03, 0.03, 1.0)
background.inputs["Strength"].default_value = 0.12

camera_data = bpy.data.cameras.new("VerifyCamera")
camera = bpy.data.objects.new("VerifyCamera", camera_data)
bpy.context.collection.objects.link(camera)
camera.data.type = "ORTHO"
camera.data.ortho_scale = 1.12
scene.camera = camera

lights = [
    ("VerifyKey", (1.4, 2.2, 1.5), 90, 2.0),
    ("VerifyFill", (-1.4, 1.6, 0.8), 55, 2.0),
    ("VerifyRim", (0.0, -1.8, 1.3), 70, 1.5),
]
for name, location, energy, size in lights:
    data = bpy.data.lights.new(name, type="AREA")
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    look_at(obj, (0, 0, 0.05))

views = {
    "v7_verify_front": (0.0, 3.0, 0.0),
    "v7_verify_left": (-3.0, 0.0, 0.0),
    "v7_verify_back": (0.0, -3.0, 0.0),
    "v7_verify_right": (3.0, 0.0, 0.0),
}
for name, position in views.items():
    camera.data.ortho_scale = 1.12
    camera.location = position
    look_at(camera, (0, 0, 0.0))
    scene.render.filepath = str(OUT / f"{name}.png")
    bpy.ops.render.render(write_still=True)

camera.data.ortho_scale = 0.30
camera.location = (0.0, 3.0, 0.38)
look_at(camera, (0, 0, 0.38))
scene.render.filepath = str(OUT / "v7_verify_face_closeup.png")
bpy.ops.render.render(write_still=True)

camera.data.ortho_scale = 0.52
camera.location = (1.5, 2.598, 0.30)
look_at(camera, (0, 0, 0.28))
scene.render.filepath = str(OUT / "v7_verify_threequarter_right.png")
bpy.ops.render.render(write_still=True)

camera.location = (-1.5, 2.598, 0.30)
look_at(camera, (0, 0, 0.28))
scene.render.filepath = str(OUT / "v7_verify_threequarter_left.png")
bpy.ops.render.render(write_still=True)

camera.data.ortho_scale = 0.58
camera.location = (0.0, 3.0, -0.16)
look_at(camera, (0, 0, -0.16))
scene.render.filepath = str(OUT / "v7_verify_lower_front.png")
bpy.ops.render.render(write_still=True)

camera.location = (1.35, 2.68, -0.14)
look_at(camera, (0, 0, -0.16))
scene.render.filepath = str(OUT / "v7_verify_lower_threequarter.png")
bpy.ops.render.render(write_still=True)

print("Verification renders complete")
