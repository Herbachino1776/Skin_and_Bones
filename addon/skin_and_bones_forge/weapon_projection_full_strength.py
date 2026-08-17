"""One-pass full-strength coverage policy for the weapon projection baker.

Skin & Bones 2.2.1 intentionally feathered projection strength from the center
of the weapon depth volume all the way to the broad faces. On real generated
weapons that made even visually broad faces receive a fractional blend, so
rebaking the result repeatedly appeared to "build up" the projection.

This patch keeps the existing single-plate workflow and node graph intact while
replacing only its broad-face coverage term with a clamped plateau:

- broad source/opposite faces reach 1.0 coverage in one bake;
- Edge Wrap controls only the transition around rounded/perpendicular edges;
- Projection Strength remains an intentional final artist multiplier.
"""

from __future__ import annotations

from . import weapon_projection as wp


EDGE_START_NODE = "SBF_WP_EdgeFeatherStart"
EDGE_RAMP_NODE = "SBF_WP_EdgeFeatherRamp"


def _coverage_limits(edge_wrap):
    """Return (start, full) depth-distance thresholds for edge feathering.

    Depth distance is 0 at the weapon mid-plane and 1 at its generated-bounds
    front/back extremes. The full threshold deliberately sits well below 1 so
    broad surfaces with relief still receive complete plate color in one pass.
    """

    wrap = max(0.0, min(1.0, float(edge_wrap)))
    start = 0.65 - 0.50 * wrap
    full = 0.85 - 0.50 * wrap
    return start, max(full, start + 0.05)


def _ensure_math(nodes, name, operation):
    node = nodes.get(name)
    if node is not None and node.bl_idname != "ShaderNodeMath":
        nodes.remove(node)
        node = None
    if node is None:
        node = nodes.new("ShaderNodeMath")
        node.name = name
    node.operation = operation
    return node


def _patch_coverage_graph(material, settings):
    if material is None or material.node_tree is None:
        return False

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    distance = nodes.get("SBF_WP_NormalizedDepthDistance")
    coverage = nodes.get("SBF_WP_CoverageMask")
    if distance is None or coverage is None:
        return False

    start, full = _coverage_limits(settings.edge_wrap)

    feather_start = _ensure_math(nodes, EDGE_START_NODE, "SUBTRACT")
    feather_start.label = "Weapon edge feather start"
    feather_start.inputs[1].default_value = start

    feather_ramp = _ensure_math(nodes, EDGE_RAMP_NODE, "DIVIDE")
    feather_ramp.label = "Full-strength broad-face plateau"
    feather_ramp.inputs[1].default_value = max(full - start, 1.0e-6)
    feather_ramp.use_clamp = True

    for socket in (feather_start.inputs[0], feather_ramp.inputs[0]):
        for link in list(socket.links):
            links.remove(link)
    links.new(distance.outputs[0], feather_start.inputs[0])
    links.new(feather_start.outputs[0], feather_ramp.inputs[0])

    for link in list(coverage.inputs[1].links):
        links.remove(link)
    links.new(feather_ramp.outputs[0], coverage.inputs[1])

    material["sbf_weapon_full_strength_coverage"] = True
    material.node_tree.update_tag()
    return True


def _update_coverage_controls(settings):
    material = wp._active_preview_material(settings)
    if material is None or material.node_tree is None:
        return False
    nodes = material.node_tree.nodes
    start, full = _coverage_limits(settings.edge_wrap)
    start_node = nodes.get(EDGE_START_NODE)
    ramp_node = nodes.get(EDGE_RAMP_NODE)
    if start_node is None or ramp_node is None:
        return _patch_coverage_graph(material, settings)
    start_node.inputs[1].default_value = start
    ramp_node.inputs[1].default_value = max(full - start, 1.0e-6)
    material.node_tree.update_tag()
    return True


def install():
    """Install the surgical policy extension once per Blender module lifetime."""

    if getattr(wp, "_sbf_full_strength_coverage_installed", False):
        return

    original_apply = wp._apply_live_controls
    original_create = wp.create_weapon_preview

    def apply_live_controls(settings):
        updated = original_apply(settings)
        _update_coverage_controls(settings)
        return updated

    def create_weapon_preview(context, settings):
        material = original_create(context, settings)
        _patch_coverage_graph(material, settings)
        apply_live_controls(settings)
        settings.status = (
            "Mirrored weapon projection preview ready — broad faces bake at full strength."
        )
        return material

    wp._apply_live_controls = apply_live_controls
    wp.create_weapon_preview = create_weapon_preview
    wp._sbf_full_strength_coverage_installed = True
