import bpy
from pathlib import Path


OUT = Path(r"E:\Dev\Dread_Stone_Black\output\blender_texture_rebuild")
BLEND_PATH = OUT / "folsomsavage_retextured_v7.blend"
GLB_PATH = OUT / "folsomsavage_retextured_v7.glb"

mesh_obj = next(obj for obj in bpy.data.objects if obj.type == "MESH")
mesh = mesh_obj.data

for layer in list(mesh.uv_layers):
    if layer.name != "UVMap":
        mesh.uv_layers.remove(layer)
mesh.uv_layers.active = mesh.uv_layers["UVMap"]
mesh.uv_layers["UVMap"].active_render = True

for attribute in list(mesh.attributes):
    if attribute.name.startswith("weight_"):
        mesh.attributes.remove(attribute)

for obj in list(bpy.data.objects):
    if obj.name.startswith("ProjectionCamera_"):
        bpy.data.objects.remove(obj, do_unlink=True)

for material in list(bpy.data.materials):
    if material.name.startswith("ProjectionBakeMaterial"):
        bpy.data.materials.remove(material, do_unlink=True)

for image in list(bpy.data.images):
    if image.name.startswith("Projection_"):
        bpy.data.images.remove(image, do_unlink=True)

bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH))

for obj in bpy.context.selected_objects:
    obj.select_set(False)
mesh_obj.select_set(True)
bpy.context.view_layer.objects.active = mesh_obj
bpy.ops.export_scene.gltf(
    filepath=str(GLB_PATH),
    export_format="GLB",
    use_selection=True,
    export_apply=True,
    export_texcoords=True,
    export_normals=True,
    export_materials="EXPORT",
)

print(f"Cleaned {BLEND_PATH}")
print(f"Re-exported {GLB_PATH}")
