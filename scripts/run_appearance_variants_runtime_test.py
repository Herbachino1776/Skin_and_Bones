"""Blender runtime regression for shared-body appearance variant families."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

import bpy


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon"
if str(ADDON) not in sys.path:
    sys.path.insert(0, str(ADDON))
existing_addon = sys.modules.get("skin_and_bones_forge")
if existing_addon is not None:
    loaded_path = Path(existing_addon.__file__).resolve()
    if ADDON.resolve() not in loaded_path.parents:
        for module_name in tuple(sys.modules):
            if module_name == "skin_and_bones_forge" or module_name.startswith(
                "skin_and_bones_forge."
            ):
                del sys.modules[module_name]

import skin_and_bones_forge as addon  # noqa: E402
from skin_and_bones_forge.constants import (  # noqa: E402
    REPAIR_OWNER_PROPERTY,
    RIG_PRODUCTION_PROPERTY,
    RIG_WEIGHT_REPORT_PROPERTY,
)
from skin_and_bones_forge.rigging import (  # noqa: E402
    apply_canonical_metadata,
    derive_simplified_contract,
    ensure_canonical_rig,
    export_rigged_glb,
    run_animation_forge_acceptance,
)
from skin_and_bones_forge.rigging.contract import (  # noqa: E402
    analyze_canonical_rig,
)
from skin_and_bones_forge.variants.runtime import (  # noqa: E402
    active_variant,
    add_variant,
    appearance_content_fingerprint,
    create_family,
    delete_variant,
    handoff_for_variant,
    mark_active_variant_dirty,
    restore_variant_to_settings,
    stamp_image_owner,
    sync_variant_from_settings,
    technical_body_record,
    validate_active_variant_for_export,
    validate_family_compatibility,
)


argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument(
    "--forge-repo",
    type=Path,
    help="Optional Dreadstone Animation Forge checkout for downstream acceptance",
)
args = parser.parse_args(argv)


def _image(name, color, settings):
    image = bpy.data.images.new(name, width=2, height=2, alpha=True)
    image.pixels[:] = list(color) * 4
    image[REPAIR_OWNER_PROPERTY] = True
    stamp_image_owner(settings, image)
    return image


def _source(name, color):
    image = bpy.data.images.new(name, width=2, height=2, alpha=True)
    image.pixels[:] = list(color) * 4
    return image


def _scene_fixture():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    mesh = bpy.data.meshes.new("VariantMesh")
    mesh.from_pydata(
        [(-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.0, 1.0)],
        [],
        [(0, 1, 2)],
    )
    uv = mesh.uv_layers.new(name="UVMap")
    for item, value in zip(uv.data, ((0.0, 0.0), (1.0, 0.0), (0.5, 1.0))):
        item.uv = value
    target = bpy.data.objects.new("VariantTarget", mesh)
    bpy.context.scene.collection.objects.link(target)

    material = bpy.data.materials.new("VariantMaterial")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    image_node = nodes.new("ShaderNodeTexImage")
    image_node.name = "BaseColor"
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    output = nodes.new("ShaderNodeOutputMaterial")
    material.node_tree.links.new(image_node.outputs["Color"], principled.inputs["Base Color"])
    material.node_tree.links.new(principled.outputs["BSDF"], output.inputs["Surface"])
    target.data.materials.append(material)

    settings = bpy.context.scene.sbf_settings
    canonical = ensure_canonical_rig(bpy.context, settings)
    full_contract = analyze_canonical_rig(bpy.context, canonical)
    contract = derive_simplified_contract(full_contract)
    armature = canonical.copy()
    armature.data = canonical.data.copy()
    armature.name = "VariantRig"
    armature.data.name = "VariantRigData"
    armature.hide_viewport = False
    armature.hide_render = False
    armature.hide_set(False)
    bpy.context.scene.collection.objects.link(armature)
    armature[RIG_PRODUCTION_PROPERTY] = True
    apply_canonical_metadata(armature, target=target)
    armature["sbf_production_profile"] = contract["profile_id"]
    armature["sbf_production_fingerprint"] = contract["fingerprint"]
    armature["sbf_canonical_fingerprint"] = contract["source_fingerprint"]

    target.parent = armature
    modifier = target.modifiers.new("SBF_ProductionArmature", "ARMATURE")
    modifier.object = armature
    group = target.vertex_groups.new(name="body")
    group.add([0, 1, 2], 1.0, "REPLACE")
    target[RIG_WEIGHT_REPORT_PROPERTY] = json.dumps(
        {
            "status": "READY_FOR_ANIMATION_TEST",
            "total_vertices": 3,
            "weighted_vertices": 3,
            "unweighted_vertices": 0,
            "maximum_influences": 1,
            "non_normalized_vertices": 0,
            "component_count": 1,
            "proxy_fallback_vertex_count": 0,
            "donor_source": "synthetic",
        },
        sort_keys=True,
    )

    settings.target_object = target
    settings.production_material = material
    settings.target_uv = "UVMap"
    settings.base_color_node = image_node.name
    settings.forward_axis = "+Y"
    settings.up_axis = "+Z"
    settings.rig_export_actions = False
    settings.rig_production_contract_json = json.dumps(contract, sort_keys=True)
    settings.canonical_fingerprint = full_contract["fingerprint"]
    settings.rig_production_fingerprint = contract["fingerprint"]
    settings.rig_production_profile = contract["profile_id"]
    settings.target_height = 1.0
    return target, armature, material, image_node, settings, contract


def _set_variant_image(settings, color, source_color):
    variant = active_variant(settings)
    layers = {
        "final": _image(f"Final_{variant.display_name}", color, settings),
        "baked": _image(f"Baked_{variant.display_name}", color, settings),
        "correction": _image(
            f"Correction_{variant.display_name}", color, settings
        ),
        "mask": _image(f"Mask_{variant.display_name}", color, settings),
        "classification": _image(
            f"Classification_{variant.display_name}", color, settings
        ),
    }
    source = _source(f"Source_{variant.display_name}", source_color)
    settings.repair_final_image = layers["final"]
    settings.last_baked_image = layers["final"]
    settings.last_raw_baked_image = layers["baked"]
    settings.repair_correction_image = layers["correction"]
    settings.repair_mask_image = layers["mask"]
    settings.repair_classification_image = layers["classification"]
    settings.front.image = source
    variant.final_image = layers["final"]
    variant.baked_image = layers["baked"]
    variant.correction_image = layers["correction"]
    variant.mask_image = layers["mask"]
    variant.classification_image = layers["classification"]
    variant.bake_state = "READY"
    sync_variant_from_settings(settings, variant)
    restore_variant_to_settings(settings, variant)
    return layers, source


def main():
    addon.register()
    target, armature, material, image_node, settings, contract = _scene_fixture()
    baseline = technical_body_record(target, settings, create_identity=True)
    first = create_family(settings, target, "shared_humanoid")
    first.display_name = "Red"
    red, red_source = _set_variant_image(
        settings, (1.0, 0.0, 0.0, 1.0), (0.8, 0.1, 0.1, 1.0)
    )

    second = add_variant(settings, display_name="Blue")
    blue, blue_source = _set_variant_image(
        settings, (0.0, 0.0, 1.0, 1.0), (0.1, 0.1, 0.8, 1.0)
    )
    third = add_variant(settings, display_name="Green")
    green, _green_source = _set_variant_image(
        settings, (0.0, 1.0, 0.0, 1.0), (0.1, 0.8, 0.1, 1.0)
    )

    expected = ((0, red, red_source), (1, blue, blue_source), (2, green, None))
    for index, layers, source in expected:
        settings.active_variant_index = index
        restore_variant_to_settings(settings, active_variant(settings))
        assert image_node.image == layers["final"]
        assert settings.last_raw_baked_image == layers["baked"]
        assert settings.repair_correction_image == layers["correction"]
        assert settings.repair_mask_image == layers["mask"]
        assert settings.repair_classification_image == layers["classification"]
        if source is not None:
            assert settings.front.image == source
        current = technical_body_record(target, settings)
        assert current["fingerprint"] == baseline["fingerprint"]

    settings.active_variant_index = 0
    restore_variant_to_settings(settings, first)
    first.approval_state = "APPROVED"
    first.dirty = False
    first.approved_revision = first.revision
    first.approval_fingerprint = "synthetic-approval"
    mark_active_variant_dirty(settings, "runtime approval invalidation")
    assert first.approval_state == "DIRTY" and first.dirty

    body_group = target.vertex_groups["body"]
    body_group.add([0], 0.5, "REPLACE")
    assert not validate_family_compatibility(settings)
    assert all(item.technical_state == "STALE" for item in settings.appearance_variants)
    body_group.add([0], 1.0, "REPLACE")
    assert validate_family_compatibility(settings)

    settings.active_variant_index = 1
    restore_variant_to_settings(settings, second)
    second_id = second.variant_id
    blue_final_name = blue["final"].name
    deleted = delete_variant(settings, 1)
    assert deleted == second_id
    assert target.name in bpy.data.objects and armature.name in bpy.data.objects
    assert red["final"].name in bpy.data.images
    assert green["final"].name in bpy.data.images
    assert blue_final_name not in bpy.data.images
    assert len(settings.appearance_variants) == 2

    settings.active_variant_index = 1
    third = active_variant(settings)
    assert third.display_name == "Green"
    restore_variant_to_settings(settings, third)
    with tempfile.TemporaryDirectory(prefix="sbf_variant_runtime_") as temporary:
        temporary_path = Path(temporary)
        blend_path = temporary_path / "variants.blend"
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        bpy.ops.wm.open_mainfile(filepath=str(blend_path))
        settings = bpy.context.scene.sbf_settings
        assert len(settings.appearance_variants) == 2
        assert active_variant(settings).display_name == "Green"
        material = settings.production_material
        image_node = material.node_tree.nodes[settings.base_color_node]
        assert image_node.image == active_variant(settings).final_image
        assert image_node.image.packed_file is not None

        target = settings.target_object
        armature = target.parent
        contract = json.loads(settings.rig_production_contract_json)
        exports = []
        for index in range(len(settings.appearance_variants)):
            settings.active_variant_index = index
            variant = active_variant(settings)
            restore_variant_to_settings(settings, variant)
            variant.approval_state = "APPROVED"
            variant.dirty = False
            variant.approved_revision = variant.revision
            variant.approval_fingerprint = appearance_content_fingerprint(
                settings, variant
            )
            validate_active_variant_for_export(settings)
            handoff = handoff_for_variant(settings, variant)
            output = temporary_path / f"{variant.export_name}.glb"
            output, manifest = export_rigged_glb(
                bpy.context,
                target,
                armature,
                contract,
                settings,
                output_path=output,
                appearance_handoff=handoff,
            )
            assert output.is_file()
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            assert payload["appearance_family"]["family_id"] == (
                settings.appearance_family_id
            )
            assert payload["appearance_family"]["variant_id"] == variant.variant_id
            assert settings.appearance_family_id.encode("utf-8") in output.read_bytes()
            exports.append((output, payload))

        assert len({output.name for output, _payload in exports}) == 2
        assert len(
            {
                payload["appearance_family"]["variant_id"]
                for _output, payload in exports
            }
        ) == 2
        assert len(
            {
                payload["appearance_family"]["technical_body_fingerprint"]
                for _output, payload in exports
            }
        ) == 1

        if args.forge_repo is not None:
            acceptance, _acceptance_path = run_animation_forge_acceptance(
                exports[-1][0],
                args.forge_repo.resolve(),
                temporary_path / "animation_forge.json",
            )
            assert acceptance["status"] == "ANIMATION_FORGE_ACCEPTED", acceptance
        else:
            print("Animation Forge acceptance skipped; pass --forge-repo to enable.")

    addon.unregister()
    print("Appearance variant runtime regression passed.")


if __name__ == "__main__":
    main()
