"""Bake the temporary projection material into the production UV atlas."""

from __future__ import annotations

import math

import bpy
import bmesh

from ..constants import (
    ADDON_VERSION_STRING,
    BASE_COLOR_UV_NAME,
    BODY_PART_ID_ATTRIBUTE,
    PREVIEW_MATERIAL_PREFIX,
    PROJECTION_UV_PREFIX,
    VIEW_NAMES,
    WEIGHT_ATTRIBUTE_PREFIX,
)
from ..projection import cleanup_temporary_data
from ..projection.source_processing import (
    cleanup_warped_sources,
    validate_preview_source_parity,
)
from ..projection.body_alignment import BODY_PARTS
from ..variants.runtime import (
    active_variant,
    adopt_initial_bake_uv,
    mark_active_variant_dirty,
    sync_variant_from_settings,
    variant_texture_path,
)
from .repair_service import (
    begin_repair_session,
    validate_repair_name_availability,
)


def _set_material_output_values(info, settings):
    if info.principled_node is not None:
        roughness = info.principled_node.inputs.get("Roughness")
        if roughness is not None:
            roughness.default_value = settings.roughness
    if info.normal_map_node is not None:
        strength = info.normal_map_node.inputs.get("Strength")
        if strength is not None:
            strength.default_value = settings.normal_strength
    if settings.smooth_shading:
        for polygon in info.mesh.polygons:
            polygon.use_smooth = True


def _uv_vertex_split_fraction(mesh, layer):
    """Measure how often one mesh vertex is split into unrelated UV points."""

    coordinates = [[] for _vertex in mesh.vertices]
    for loop in mesh.loops:
        uv = layer.data[loop.index].uv
        coordinates[loop.vertex_index].append(
            (round(float(uv.x), 6), round(float(uv.y), 6))
        )
    used = [values for values in coordinates if len(values) > 1]
    if not used:
        return 0.0
    split = sum(len(set(values)) > 1 for values in used)
    return split / len(used)


def _single_face_vertex_fraction(mesh):
    """Detect soup-like meshes whose duplicated corners defeat Smart Project."""

    face_uses = [0] * len(mesh.vertices)
    for polygon in mesh.polygons:
        for vertex_index in polygon.vertices:
            face_uses[vertex_index] += 1
    used = [count for count in face_uses if count]
    if not used:
        return 0.0
    return sum(count == 1 for count in used) / len(used)


def _create_projection_base_color_uv(info, settings):
    """Create a compact view-space atlas for heavily fragmented meshes."""

    mesh = info.mesh
    existing = mesh.uv_layers.get(BASE_COLOR_UV_NAME)
    if existing is not None:
        mesh.uv_layers.remove(existing)
    layer = mesh.uv_layers.new(name=BASE_COLOR_UV_NAME)
    active_views = [
        name
        for name in VIEW_NAMES
        if getattr(settings, name).enabled
        and getattr(settings, name).image is not None
        and mesh.uv_layers.get(f"{PROJECTION_UV_PREFIX}{name}") is not None
        and mesh.attributes.get(f"{WEIGHT_ATTRIBUTE_PREFIX}{name}") is not None
    ]
    if not active_views:
        mesh.uv_layers.remove(layer)
        raise RuntimeError("Projection bake UV requires an active preview view.")

    part_id = mesh.attributes.get(BODY_PART_ID_ATTRIBUTE)
    if part_id is None:
        mesh.uv_layers.remove(layer)
        raise RuntimeError("Projection bake UV requires semantic body ownership.")
    assignments = {}
    tile_loops = {}
    for polygon in mesh.polygons:
        chosen = max(
            active_views,
            key=lambda name: (
                sum(
                    mesh.attributes[f"{WEIGHT_ATTRIBUTE_PREFIX}{name}"].data[
                        loop_index
                    ].value
                    for loop_index in polygon.loop_indices
                ),
                -active_views.index(name),
            ),
        )
        semantic = max(
            0,
            min(
                len(BODY_PARTS) - 1,
                int(
                    round(
                        sum(part_id.data[index].value for index in polygon.loop_indices)
                        / max(len(polygon.loop_indices), 1)
                    )
                ),
            ),
        )
        key = (chosen, semantic)
        assignments[polygon.index] = key
        tile_loops.setdefault(key, []).extend(polygon.loop_indices)

    bounds = {}
    for key, loop_indices in tile_loops.items():
        name, _semantic = key
        source = mesh.uv_layers[f"{PROJECTION_UV_PREFIX}{name}"]
        values = [source.data[index].uv for index in loop_indices]
        minimum_x = min(float(value.x) for value in values)
        minimum_y = min(float(value.y) for value in values)
        maximum_x = max(float(value.x) for value in values)
        maximum_y = max(float(value.y) for value in values)
        bounds[key] = (minimum_x, minimum_y, maximum_x, maximum_y)

    columns = len(active_views)
    texture_size = max(int(settings.texture_size), 1)
    row_heights = (0.25, 0.17, 0.10, 0.12, 0.12, 0.12, 0.12)
    row_origins = []
    cursor = 0.0
    for height in row_heights:
        row_origins.append(cursor)
        cursor += height
    tile_width = 1.0 / columns
    requested_padding = (max(int(settings.bake_margin), 0) + 2) / texture_size
    # Preserve useful cell area even when an unusually large margin is chosen
    # for a low-resolution bake.  Twenty-four percent on each side leaves at
    # least half of every semantic cell available for texture detail.
    padding = min(
        requested_padding,
        tile_width * 0.24,
        min(row_heights) * 0.24,
    )
    for polygon in mesh.polygons:
        name, semantic = assignments[polygon.index]
        column = active_views.index(name)
        row_origin = row_origins[semantic]
        row_height = row_heights[semantic]
        minimum_x, minimum_y, maximum_x, maximum_y = bounds[(name, semantic)]
        span_x = max(maximum_x - minimum_x, 1.0e-8)
        span_y = max(maximum_y - minimum_y, 1.0e-8)
        source = mesh.uv_layers[f"{PROJECTION_UV_PREFIX}{name}"]
        for loop_index in polygon.loop_indices:
            source_uv = source.data[loop_index].uv
            normalized_x = (float(source_uv.x) - minimum_x) / span_x
            normalized_y = (float(source_uv.y) - minimum_y) / span_y
            layer.data[loop_index].uv = (
                column * tile_width
                + padding
                + normalized_x * max(tile_width - padding * 2.0, 1.0e-8),
                row_origin
                + padding
                + normalized_y * max(row_height - padding * 2.0, 1.0e-8),
            )
    mesh.uv_layers.active = layer
    layer.active_render = True
    mesh.update()
    info.obj["sbf_bake_uv_strategy"] = "PROJECTION_ATLAS"
    info.obj["sbf_bake_uv_views"] = ",".join(active_views)
    return layer


def _create_clean_base_color_uv(context, info, settings):
    """Create a connected bake atlas without changing production geometry."""

    target = info.obj
    mesh = info.mesh
    existing = mesh.uv_layers.get(BASE_COLOR_UV_NAME)
    if existing is not None:
        mesh.uv_layers.remove(existing)

    # SPAR3D can duplicate vertices along nearly every generated fragment.
    # Smart Project interprets those duplicates as hundreds of independent
    # islands and the final bake becomes a low-resolution triangle mosaic.
    # Unwrap a temporary, exactly welded mesh and copy its loop UVs back.  Loop
    # order and the visible production geometry remain untouched.
    unwrap_mesh = mesh.copy()
    unwrap_mesh.name = "SBF_BaseColorUV_WorkMesh"
    polygon_index = unwrap_mesh.attributes.new(
        name="SBF_OriginalPolygonIndex",
        type="INT",
        domain="FACE",
    )
    for polygon in unwrap_mesh.polygons:
        polygon_index.data[polygon.index].value = polygon.index
    bm = bmesh.new()
    try:
        bm.from_mesh(unwrap_mesh)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1.0e-6)
        bm.to_mesh(unwrap_mesh)
    finally:
        bm.free()

    if (
        len(unwrap_mesh.polygons) != len(mesh.polygons)
        or len(unwrap_mesh.loops) != len(mesh.loops)
    ):
        bpy.data.meshes.remove(unwrap_mesh)
        raise RuntimeError(
            "Clean UV preparation changed the mesh face layout; bake cancelled."
        )

    unwrap_layer = unwrap_mesh.uv_layers.new(name=BASE_COLOR_UV_NAME)
    unwrap_mesh.uv_layers.active = unwrap_layer
    unwrap_layer.active_render = True
    unwrap_object = bpy.data.objects.new(
        "SBF_BaseColorUV_WorkObject",
        unwrap_mesh,
    )
    context.collection.objects.link(unwrap_object)
    try:
        for obj in context.selected_objects:
            obj.select_set(False)
        unwrap_object.select_set(True)
        context.view_layer.objects.active = unwrap_object
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            bpy.ops.mesh.select_all(action="SELECT")
            result = bpy.ops.uv.smart_project(
                # SPAR3D surfaces remain steeply faceted after exact welding.
                # A near-90-degree split keeps broad connected charts.
                angle_limit=math.radians(89.0),
                margin_method="SCALED",
                rotate_method="AXIS_ALIGNED_Y",
                island_margin=0.02,
                area_weight=0.0,
                correct_aspect=True,
                scale_to_bounds=True,
            )
            if "FINISHED" not in result:
                raise RuntimeError(
                    "Blender could not generate the clean base-color UV."
                )
        finally:
            if unwrap_object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

        layer = mesh.uv_layers.new(name=BASE_COLOR_UV_NAME)
        polygon_index = unwrap_mesh.attributes.get(
            "SBF_OriginalPolygonIndex"
        )
        if polygon_index is None:
            raise RuntimeError(
                "Clean UV preparation lost the polygon correspondence map."
            )
        unwrap_layer = unwrap_mesh.uv_layers[BASE_COLOR_UV_NAME]
        for unwrap_polygon in unwrap_mesh.polygons:
            original_index = polygon_index.data[
                unwrap_polygon.index
            ].value
            original_polygon = mesh.polygons[original_index]
            if len(unwrap_polygon.loop_indices) != len(
                original_polygon.loop_indices
            ):
                raise RuntimeError(
                    "Clean UV preparation changed a polygon corner count."
                )
            available = set(original_polygon.loop_indices)
            for source_index in unwrap_polygon.loop_indices:
                source_vertex = unwrap_mesh.loops[
                    source_index
                ].vertex_index
                source_co = unwrap_mesh.vertices[source_vertex].co
                destination_index = min(
                    available,
                    key=lambda loop_index: (
                        mesh.vertices[
                            mesh.loops[loop_index].vertex_index
                        ].co
                        - source_co
                    ).length_squared,
                )
                destination_vertex = mesh.loops[
                    destination_index
                ].vertex_index
                error = (
                    mesh.vertices[destination_vertex].co - source_co
                ).length_squared
                if error > 1.0e-12:
                    raise RuntimeError(
                        "Clean UV preparation could not match a face corner."
                    )
                layer.data[destination_index].uv = unwrap_layer.data[
                    source_index
                ].uv
                available.remove(destination_index)
        mesh.uv_layers.active = layer
        layer.active_render = True
    finally:
        bpy.data.objects.remove(unwrap_object, do_unlink=True)
        if unwrap_mesh.users == 0:
            bpy.data.meshes.remove(unwrap_mesh)
        target.select_set(True)
        context.view_layer.objects.active = target

    mesh.update()
    fragmentation = _uv_vertex_split_fraction(mesh, layer)
    target["sbf_bake_uv_smart_fragmentation"] = fragmentation
    topology_fragmentation = _single_face_vertex_fraction(mesh)
    target["sbf_bake_uv_topology_fragmentation"] = topology_fragmentation
    if max(fragmentation, topology_fragmentation) > 0.10:
        return _create_projection_base_color_uv(info, settings)
    target["sbf_bake_uv_strategy"] = "SMART_PROJECT"
    return layer


def _uv_map_node(nodes, name, label, uv_name):
    node = nodes.get(name)
    if node is None or node.bl_idname != "ShaderNodeUVMap":
        node = nodes.new("ShaderNodeUVMap")
        node.name = name
    node.label = label
    node.uv_map = uv_name
    return node


def _bind_production_texture_uvs(info, base_uv_name):
    """Keep PBR maps on the source UV and bind base color to its bake UV."""

    material = info.material
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    original_uv = _uv_map_node(
        nodes,
        "SBF_OriginalUVCoordinates",
        "Original UV - Normal and PBR Maps",
        info.uv_name,
    )
    base_uv = _uv_map_node(
        nodes,
        "SBF_BaseColorUVCoordinates",
        "Clean Baked Base-Color UV",
        base_uv_name,
    )
    original_uv.location = (
        info.base_color_node.location.x - 420,
        info.base_color_node.location.y - 240,
    )
    base_uv.location = (
        info.base_color_node.location.x - 220,
        info.base_color_node.location.y,
    )

    for node in nodes:
        if (
            node.bl_idname != "ShaderNodeTexImage"
            or node == info.base_color_node
        ):
            continue
        vector = node.inputs.get("Vector")
        if vector is not None and not vector.is_linked:
            links.new(original_uv.outputs["UV"], vector)

    base_vector = info.base_color_node.inputs.get("Vector")
    if base_vector is not None:
        for link in list(base_vector.links):
            links.remove(link)
        links.new(base_uv.outputs["UV"], base_vector)


def bake_final_texture(context, info, settings):
    target = info.obj
    slot_material = target.material_slots[info.material_slot].material
    if (
        slot_material is None
        or not slot_material.name.startswith(PREVIEW_MATERIAL_PREFIX)
        or slot_material.node_tree is None
    ):
        raise RuntimeError("Create a projection preview before baking.")

    preview_material = slot_material
    validate_preview_source_parity(preview_material, settings)
    nodes = preview_material.node_tree.nodes
    for node in list(nodes):
        if node.name.startswith("SBF_BakeTarget"):
            nodes.remove(node)

    output_path = variant_texture_path(settings, settings.output_image_path)
    original_path = info.original_base_image.filepath
    original_is_owned_repair = info.original_base_image.get(
        "sbf_texture_repair_owned", False
    )
    if (
        original_path
        and not original_is_owned_repair
        and not settings.allow_source_overwrite
    ):
        resolved_original = Path(bpy.path.abspath(original_path)).resolve()
        raw_output_path = output_path.with_name(
            f"{output_path.stem}.baked{output_path.suffix or '.png'}"
        )
        if output_path == resolved_original or raw_output_path == resolved_original:
            raise RuntimeError(
                "Final or raw-bake output matches the original source image. "
                "Choose a new path or explicitly enable Allow Source Overwrite."
            )

    validate_repair_name_availability(settings)
    size = int(settings.texture_size)
    image_name = f"SBF_BaseColor_BakeWork_{target.name}_{size}"
    baked_image = bpy.data.images.new(
        image_name,
        width=size,
        height=size,
        alpha=True,
        float_buffer=False,
    )
    baked_image.colorspace_settings.name = "sRGB"
    baked_image.alpha_mode = "STRAIGHT"
    baked_image.generated_color = (0.03, 0.03, 0.03, 1.0)

    bake_target = nodes.new("ShaderNodeTexImage")
    bake_target.name = "SBF_BakeTarget"
    bake_target.label = "SBF Bake Target"
    bake_target.image = baked_image
    nodes.active = bake_target
    for node in nodes:
        node.select = False
    bake_target.select = True

    target.data.uv_layers.active = target.data.uv_layers[info.uv_name]
    target.data.uv_layers[info.uv_name].active_render = True

    selected_before = list(context.selected_objects)
    active_before = context.view_layer.objects.active
    mode_before = target.mode
    if target.mode != "OBJECT":
        context.view_layer.objects.active = target
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in context.selected_objects:
        obj.select_set(False)
    target.select_set(True)
    context.view_layer.objects.active = target
    if settings.generate_bake_uv:
        _create_clean_base_color_uv(context, info, settings)
        bake_uv_name = BASE_COLOR_UV_NAME
    else:
        bake_uv = target.data.uv_layers[info.uv_name]
        target.data.uv_layers.active = bake_uv
        bake_uv.active_render = True
        bake_uv_name = info.uv_name

    scene = context.scene
    engine_before = scene.render.engine
    samples_before = scene.cycles.samples
    device_before = scene.cycles.device
    margin_before = scene.render.bake.margin
    margin_type_before = scene.render.bake.margin_type
    use_clear_before = scene.render.bake.use_clear

    try:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 1
        scene.render.bake.margin = settings.bake_margin
        scene.render.bake.margin_type = "ADJACENT_FACES"
        scene.render.bake.use_clear = True
        bpy.ops.object.bake(type="EMIT")
    except Exception:
        if baked_image.users == 0:
            bpy.data.images.remove(baked_image)
        raise
    finally:
        scene.render.engine = engine_before
        scene.cycles.samples = samples_before
        scene.cycles.device = device_before
        scene.render.bake.margin = margin_before
        scene.render.bake.margin_type = margin_type_before
        scene.render.bake.use_clear = use_clear_before

        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected_before:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        context.view_layer.objects.active = active_before
        if mode_before != "OBJECT" and target.name in context.view_layer.objects:
            context.view_layer.objects.active = target
            try:
                bpy.ops.object.mode_set(mode=mode_before)
            except RuntimeError:
                pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    repair_session = begin_repair_session(
        context,
        info,
        settings,
        baked_image,
        output_path,
        bake_uv_name,
    )
    final_image = repair_session["final"]
    info.base_color_node.image = final_image
    _bind_production_texture_uvs(info, bake_uv_name)
    target.material_slots[info.material_slot].material = info.material
    _set_material_output_values(info, settings)

    settings.last_baked_image = final_image
    settings.last_raw_baked_image = baked_image
    target["sbf_processed"] = True
    target["sbf_version"] = ADDON_VERSION_STRING
    target["sbf_base_color_image"] = final_image.name
    target["sbf_base_color_path"] = str(output_path)

    cleanup_temporary_data(context, target, info.material)
    cleanup_warped_sources(settings)
    variant = active_variant(settings)
    if variant is not None:
        variant.bake_output_path = str(output_path)
        mark_active_variant_dirty(settings, "Appearance was baked or rebaked")
        adopt_initial_bake_uv(settings)
        sync_variant_from_settings(settings, variant)
    return final_image, output_path
