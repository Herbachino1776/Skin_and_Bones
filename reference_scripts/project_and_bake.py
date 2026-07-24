import bpy
import math
from pathlib import Path
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


ROOT = Path(r"E:\Dev\Dread_Stone_Black")
OUT = ROOT / "output" / "blender_texture_rebuild"
VIEW_DIR = OUT / "projection_views"
BAKED_PATH = OUT / "folsomsavage_rebuilt_base_color_4096_v7.png"
BLEND_PATH = OUT / "folsomsavage_retextured_v7.blend"
GLB_PATH = OUT / "folsomsavage_retextured_v7.glb"

scene = bpy.context.scene
mesh_obj = next(obj for obj in bpy.data.objects if obj.type == "MESH")
mesh = mesh_obj.data
original_material = mesh_obj.material_slots[0].material
original_base_node = next(
    node
    for node in original_material.node_tree.nodes
    if node.bl_idname == "ShaderNodeTexImage" and node.label == "BASE COLOR"
)
original_base_image = original_base_node.image
original_uv_name = mesh.uv_layers.active.name

scene.render.resolution_x = 2048
scene.render.resolution_y = 2048
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.film_transparent = True


def look_at(camera, point):
    direction = Vector(point) - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def load_projection(name):
    path = VIEW_DIR / f"{name}_projection.png"
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name = f"Projection_{name}"
    image.colorspace_settings.name = "sRGB"
    image.alpha_mode = "STRAIGHT"
    return image


height = mesh_obj.dimensions.z
ortho_scale = height / 0.90
center = mesh_obj.matrix_world @ Vector(
    (
        (min(v.co.x for v in mesh.vertices) + max(v.co.x for v in mesh.vertices)) * 0.5,
        (min(v.co.y for v in mesh.vertices) + max(v.co.y for v in mesh.vertices)) * 0.5,
        (min(v.co.z for v in mesh.vertices) + max(v.co.z for v in mesh.vertices)) * 0.5,
    )
)

view_specs = {
    "front": {
        "position": Vector((0.0, 3.0, 0.0)),
        "direction": Vector((0.0, 1.0, 0.0)),
    },
    "back": {
        "position": Vector((0.0, -3.0, 0.0)),
        "direction": Vector((0.0, -1.0, 0.0)),
    },
    "left": {
        "position": Vector((-3.0, 0.0, 0.0)),
        "direction": Vector((-1.0, 0.0, 0.0)),
    },
    "right": {
        "position": Vector((3.0, 0.0, 0.0)),
        "direction": Vector((1.0, 0.0, 0.0)),
    },
}

cameras = {}
images = {}
for name, spec in view_specs.items():
    camera_data = bpy.data.cameras.new(f"ProjectionCamera_{name}")
    camera = bpy.data.objects.new(f"ProjectionCamera_{name}", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = ortho_scale
    camera.location = center + spec["position"]
    look_at(camera, center)
    cameras[name] = camera
    images[name] = load_projection(name)

# Ensure world_to_camera_view sees the newly-created camera transforms.
bpy.context.view_layer.update()

# Create camera-projection UV maps.
normal_matrix = mesh_obj.matrix_world.to_3x3()
weight_attrs = {}
for name, spec in view_specs.items():
    uv_name = f"PROJ_{name}"
    old_uv = mesh.uv_layers.get(uv_name)
    if old_uv:
        mesh.uv_layers.remove(old_uv)
    uv_layer = mesh.uv_layers.new(name=uv_name)

    attr_name = f"weight_{name}"
    old_attr = mesh.attributes.get(attr_name)
    if old_attr:
        mesh.attributes.remove(old_attr)
    weight_attrs[name] = mesh.attributes.new(
        name=attr_name, type="FLOAT", domain="CORNER"
    )

    camera = cameras[name]
    for loop in mesh.loops:
        vertex = mesh.vertices[loop.vertex_index]
        world_co = mesh_obj.matrix_world @ vertex.co
        projected = world_to_camera_view(scene, camera, world_co)
        uv_layer.data[loop.index].uv = (projected.x, projected.y)

# Blend smoothly around the body so projection silhouettes cannot create hard
# bands. The upper torso and head strongly prefer the front/back identity views,
# preventing profile-generated eyes, noses, and collars from ghosting into
# three-quarter angles while still allowing true side-facing surfaces to use
# their profile images.
world_z_values = [
    (mesh_obj.matrix_world @ vertex.co).z for vertex in mesh.vertices
]
world_y_values = [
    (mesh_obj.matrix_world @ vertex.co).y for vertex in mesh.vertices
]
world_z_min = min(world_z_values)
world_z_span = max(world_z_values) - world_z_min
world_y_min = min(world_y_values)
world_y_span = max(world_y_values) - world_y_min

# Projection depth protection. Camera UV projection alone has no concept of
# occlusion, so an arm visible in a side image can otherwise be stamped through
# the real arm and onto the torso or thigh behind it. For every view, ray-cast
# from outside the model toward both polygon centers and loop vertices. Only
# points that are the first surface reached are allowed to receive that view.
depsgraph = bpy.context.evaluated_depsgraph_get()
ray_distance = max(mesh_obj.dimensions) * 4.0
visibility_tolerance = max(height * 0.003, 0.00001)


def is_first_visible_surface(world_point, outward_direction):
    ray_origin = world_point + outward_direction * ray_distance
    ray_direction = -outward_direction
    hit, location, _normal, _face_index, hit_object, _matrix = scene.ray_cast(
        depsgraph,
        ray_origin,
        ray_direction,
        distance=ray_distance * 1.25,
    )
    if not hit or hit_object is None or hit_object.name != mesh_obj.name:
        return 0.0
    return (
        1.0
        if (location - world_point).length <= visibility_tolerance
        else 0.0
    )


loop_polygon_indices = [0] * len(mesh.loops)
for polygon in mesh.polygons:
    for loop_index in polygon.loop_indices:
        loop_polygon_indices[loop_index] = polygon.index

polygon_visibility = {name: [0.0] * len(mesh.polygons) for name in view_specs}
for name, spec in view_specs.items():
    outward_direction = spec["direction"]
    for polygon in mesh.polygons:
        world_center = mesh_obj.matrix_world @ polygon.center
        polygon_visibility[name][polygon.index] = is_first_visible_surface(
            world_center, outward_direction
        )

for loop in mesh.loops:
    vertex = mesh.vertices[loop.vertex_index]
    world_co = mesh_obj.matrix_world @ vertex.co
    world_normal = (normal_matrix @ vertex.normal).normalized()
    height_ratio = (world_co.z - world_z_min) / max(world_z_span, 0.0001)

    if height_ratio >= 0.75:
        identity_bias = 40.0
    elif height_ratio >= 0.58:
        identity_bias = 10.0
    else:
        identity_bias = 3.0

    for name, spec in view_specs.items():
        directional = max(0.0, world_normal.dot(spec["direction"]))
        if name in {"front", "back"}:
            front_position = (world_co.y - world_y_min) / max(
                world_y_span, 0.0001
            )
            hemisphere = (
                front_position if name == "front" else 1.0 - front_position
            )
            top_surface_coverage = abs(world_normal.z) * hemisphere * 0.9
            directional = max(directional, top_surface_coverage)
        bias = identity_bias if name in {"front", "back"} else 1.0
        vertex_visibility = is_first_visible_surface(
            world_co, spec["direction"]
        )
        center_visibility = polygon_visibility[name][
            loop_polygon_indices[loop.index]
        ]
        visibility = vertex_visibility * center_visibility
        weight_attrs[name].data[loop.index].value = (
            (0.001 + bias * directional**4) * visibility
        )

mesh.uv_layers.active = mesh.uv_layers[original_uv_name]

# Build a temporary material that blends all camera projections by direction
# and alpha. Existing SPAR3D color is retained only where every projection is
# transparent, preventing black gaps around imperfect silhouettes.
bake_material = bpy.data.materials.new("ProjectionBakeMaterial")
bake_material.use_nodes = True
nodes = bake_material.node_tree.nodes
links = bake_material.node_tree.links
nodes.clear()

output = nodes.new("ShaderNodeOutputMaterial")
emission = nodes.new("ShaderNodeEmission")
links.new(emission.outputs["Emission"], output.inputs["Surface"])

old_tex = nodes.new("ShaderNodeTexImage")
old_tex.image = original_base_image
old_tex.interpolation = "Linear"
old_uv = nodes.new("ShaderNodeUVMap")
old_uv.uv_map = original_uv_name
links.new(old_uv.outputs["UV"], old_tex.inputs["Vector"])

sum_vector = None
sum_weight = None

for name in ("front", "back", "left", "right"):
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = f"PROJ_{name}"

    tex = nodes.new("ShaderNodeTexImage")
    tex.image = images[name]
    tex.interpolation = "Linear"
    tex.extension = "CLIP"
    links.new(uv_node.outputs["UV"], tex.inputs["Vector"])

    attr = nodes.new("ShaderNodeAttribute")
    attr.attribute_name = f"weight_{name}"

    alpha_weight = nodes.new("ShaderNodeMath")
    alpha_weight.operation = "MULTIPLY"
    links.new(tex.outputs["Alpha"], alpha_weight.inputs[0])
    links.new(attr.outputs["Fac"], alpha_weight.inputs[1])

    scaled_color = nodes.new("ShaderNodeVectorMath")
    scaled_color.operation = "SCALE"
    links.new(tex.outputs["Color"], scaled_color.inputs[0])
    links.new(alpha_weight.outputs[0], scaled_color.inputs[3])

    if sum_vector is None:
        sum_vector = scaled_color.outputs["Vector"]
        sum_weight = alpha_weight.outputs[0]
    else:
        add_vector = nodes.new("ShaderNodeVectorMath")
        add_vector.operation = "ADD"
        links.new(sum_vector, add_vector.inputs[0])
        links.new(scaled_color.outputs["Vector"], add_vector.inputs[1])
        sum_vector = add_vector.outputs["Vector"]

        add_weight = nodes.new("ShaderNodeMath")
        add_weight.operation = "ADD"
        links.new(sum_weight, add_weight.inputs[0])
        links.new(alpha_weight.outputs[0], add_weight.inputs[1])
        sum_weight = add_weight.outputs[0]

safe_weight = nodes.new("ShaderNodeMath")
safe_weight.operation = "MAXIMUM"
safe_weight.inputs[1].default_value = 0.0001
links.new(sum_weight, safe_weight.inputs[0])

reciprocal = nodes.new("ShaderNodeMath")
reciprocal.operation = "DIVIDE"
reciprocal.inputs[0].default_value = 1.0
links.new(safe_weight.outputs[0], reciprocal.inputs[1])

normalized_color = nodes.new("ShaderNodeVectorMath")
normalized_color.operation = "SCALE"
links.new(sum_vector, normalized_color.inputs[0])
links.new(reciprocal.outputs[0], normalized_color.inputs[3])

has_projection = nodes.new("ShaderNodeMath")
has_projection.operation = "GREATER_THAN"
has_projection.inputs[1].default_value = 0.01
links.new(sum_weight, has_projection.inputs[0])

fallback_mix = nodes.new("ShaderNodeMixRGB")
fallback_mix.blend_type = "MIX"
links.new(has_projection.outputs[0], fallback_mix.inputs[0])
links.new(old_tex.outputs["Color"], fallback_mix.inputs[1])
links.new(normalized_color.outputs["Vector"], fallback_mix.inputs[2])
links.new(fallback_mix.outputs["Color"], emission.inputs["Color"])
emission.inputs["Strength"].default_value = 1.0

# Bake target node must be active and disconnected from the shader.
baked_image = bpy.data.images.new(
    "FolsomSavage_Rebuilt_BaseColor",
    width=4096,
    height=4096,
    alpha=True,
    float_buffer=False,
)
baked_image.colorspace_settings.name = "sRGB"
baked_image.generated_color = (0.03, 0.03, 0.03, 1.0)
bake_target = nodes.new("ShaderNodeTexImage")
bake_target.image = baked_image
nodes.active = bake_target
bake_target.select = True

mesh_obj.material_slots[0].material = bake_material
if mesh_obj.mode != "OBJECT":
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.mode_set(mode="OBJECT")
for obj in bpy.context.selected_objects:
    obj.select_set(False)
mesh_obj.select_set(True)
bpy.context.view_layer.objects.active = mesh_obj

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 1
scene.render.bake.margin = 24
scene.render.bake.use_clear = True
bpy.ops.object.bake(type="EMIT")

baked_image.filepath_raw = str(BAKED_PATH)
baked_image.file_format = "PNG"
baked_image.save()

# Restore the production material, replace only its base color, and preserve
# SPAR3D's packed normal map and all original UVs.
original_base_node.image = baked_image
mesh_obj.material_slots[0].material = original_material
mesh.uv_layers.active = mesh.uv_layers[original_uv_name]
normal_node = original_material.node_tree.nodes.get("Normal Map")
if normal_node:
    normal_node.inputs["Strength"].default_value = 0.25
principled_node = next(
    (
        node
        for node in original_material.node_tree.nodes
        if node.bl_idname == "ShaderNodeBsdfPrincipled"
    ),
    None,
)
if principled_node and "Roughness" in principled_node.inputs:
    principled_node.inputs["Roughness"].default_value = 1.0
for polygon in mesh.polygons:
    polygon.use_smooth = True
scene.render.engine = "BLENDER_EEVEE"

baked_image.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(BLEND_PATH), copy=True)

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

print(f"Saved baked texture: {BAKED_PATH}")
print(f"Saved Blender copy: {BLEND_PATH}")
print(f"Saved GLB: {GLB_PATH}")
