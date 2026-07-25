"""Run the exact-weld SPAR3D intake matrix inside Blender 5.1.2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy


argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--addon", type=Path, required=True)
parser.add_argument("--fixture", action="append", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--save-first-blend", type=Path)
args = parser.parse_args(argv)

ADDON = args.addon.resolve()
sys.path.insert(0, str(ADDON))

import skin_and_bones_forge  # noqa: E402
from skin_and_bones_forge.intake.analysis import geometry_fingerprint  # noqa: E402
from skin_and_bones_forge.intake.core import (  # noqa: E402
    OWNER_PROPERTY,
    OWNER_VALUE,
    ROLE_PROPERTY,
    prepare_imported_spar3d,
    prepare_selected_spar3d,
    restore_raw_source,
)
from skin_and_bones_forge.rigging.analysis import analyze_target  # noqa: E402
from skin_and_bones_forge.validation import validate_target  # noqa: E402


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def owned(role):
    return [
        obj
        for obj in bpy.data.objects
        if obj.get(OWNER_PROPERTY) == OWNER_VALUE and obj.get(ROLE_PROPERTY) == role
    ]


def owned_collections(role):
    return [
        collection
        for collection in bpy.data.collections
        if collection.get(OWNER_PROPERTY) == OWNER_VALUE
        and collection.get(ROLE_PROPERTY) == role
    ]


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    require(hasattr(bpy.context.scene, "sbf_settings"), "Settings were not registered.")


def assert_preparation(report, clean, fixture):
    raw = report["raw"]
    welded = report["welded"]
    normalized = report["normalized"]
    proof = report["proof"]
    normalization = report["normalization"]
    require(report["readiness"] == "READY_FOR_SKIN", f"{fixture}: not ready")
    require(raw["counts"]["vertices"] > welded["counts"]["vertices"], f"{fixture}: no weld")
    require(raw["exact_duplicate_vertices"] > 0, f"{fixture}: no exact duplicates")
    require(welded["connected_components"] == 1, f"{fixture}: welded components")
    require(welded["boundary_edge_count"] == 0, f"{fixture}: boundary edges")
    require(welded["non_manifold_edge_count"] == 0, f"{fixture}: non-manifold edges")
    require(welded["watertight"], f"{fixture}: not watertight")
    require(welded["winding_consistent"], f"{fixture}: winding")
    require(welded["signed_volume_world"] > 0.0, f"{fixture}: non-positive volume")
    require(proof["face_count_preserved"], f"{fixture}: face count")
    require(proof["surface_area_world_preserved"], f"{fixture}: surface area")
    require(proof["signed_volume_world_preserved"], f"{fixture}: signed volume")
    require(proof["material_assignments_preserved"], f"{fixture}: materials")
    require(proof["material_slots_preserved"], f"{fixture}: material slots")
    require(proof["face_winding_preserved"], f"{fixture}: face winding")
    require(proof["generic_attributes_preserved"], f"{fixture}: attributes")
    require(proof["uv_values_preserved"], f"{fixture}: UV values")
    require(proof["uv_seam_discontinuities_preserved"], f"{fixture}: UV seams")
    require(proof["corner_normals_preserved"], f"{fixture}: corner normals")
    require(proof["no_new_degenerate_faces"], f"{fixture}: degenerates")
    require(not report["approximate_merge_performed"], f"{fixture}: approximate merge")
    require(abs(normalization["final_height"] - 1.5) <= 1.5e-5, f"{fixture}: height")
    require(abs(normalization["final_ground_z"]) <= 1.0e-6, f"{fixture}: ground")
    require(tuple(clean.scale) == (1.0, 1.0, 1.0), f"{fixture}: scale")
    require(bpy.context.scene.sbf_settings.target_object == clean, f"{fixture}: target")
    require(len(raw["material_slots"]) == len(normalized["material_slots"]), f"{fixture}: slots")


def run_fixture(fixture, index):
    reset_scene()
    settings = bpy.context.scene.sbf_settings
    settings.intake_target_height = 1.5
    settings.intake_preserve_raw = True
    report, clean = prepare_imported_spar3d(bpy.context, str(fixture))
    assert_preparation(report, clean, fixture)

    raw_objects = owned("raw_mesh")
    require(len(raw_objects) == 1, f"{fixture}: protected raw mesh count")
    raw = raw_objects[0]
    require(
        geometry_fingerprint(raw) == report["fingerprints"]["raw"],
        f"{fixture}: protected raw changed",
    )
    require(len(owned("clean_object")) == 1, f"{fixture}: clean object count")
    require(len(owned_collections("raw_collection")) == 1, f"{fixture}: raw collection count")
    require(len(owned_collections("clean_collection")) == 1, f"{fixture}: clean collection count")

    target_info = validate_target(bpy.context, settings)
    rig_analysis = analyze_target(
        bpy.context, clean, settings.forward_axis, settings.up_axis
    )
    require(target_info.obj == clean, f"{fixture}: downstream target validation")
    require(rig_analysis["connected_components"] == 1, f"{fixture}: rig components")
    require(rig_analysis["bone_heat_risk"] == "LOW", f"{fixture}: rig risk")

    repeat = None
    rollback = None
    restore = None
    if index == 0:
        stable_counts = {
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "raw_collections": len(owned_collections("raw_collection")),
        }
        first_normalized_fingerprint = report["fingerprints"]["normalized"]
        repeated_report, repeated_clean = prepare_imported_spar3d(
            bpy.context, str(fixture)
        )
        assert_preparation(repeated_report, repeated_clean, fixture)
        require(
            repeated_report["fingerprints"]["normalized"]
            == first_normalized_fingerprint,
            f"{fixture}: repeated fingerprint",
        )
        require(len(owned("clean_object")) == 1, f"{fixture}: duplicate clean")
        require(len(owned("raw_mesh")) == 1, f"{fixture}: duplicate raw")
        require(
            len(bpy.data.materials) == stable_counts["materials"],
            f"{fixture}: materials accumulated",
        )
        require(len(bpy.data.images) == stable_counts["images"], f"{fixture}: images accumulated")
        repeat = {"passed": True, "normalized_fingerprint_stable": True}

        before_objects = {obj.as_pointer() for obj in bpy.data.objects}
        before_target = settings.target_object
        settings.intake_test_failure_stage = "AFTER_CLEAN"
        try:
            prepare_imported_spar3d(bpy.context, str(fixture))
        except RuntimeError as exc:
            require("Injected intake rollback" in str(exc), f"{fixture}: wrong rollback error")
        else:
            raise AssertionError(f"{fixture}: injected rollback did not fail")
        finally:
            settings.intake_test_failure_stage = ""
        require(
            {obj.as_pointer() for obj in bpy.data.objects} == before_objects,
            f"{fixture}: rollback object inventory",
        )
        require(settings.target_object == before_target, f"{fixture}: rollback target")
        require(
            geometry_fingerprint(owned("raw_mesh")[0]) == report["fingerprints"]["raw"],
            f"{fixture}: rollback raw changed",
        )
        rollback = {"passed": True, "object_inventory_restored": True}

        restored = restore_raw_source(bpy.context)
        require(not owned("clean_object"), f"{fixture}: restore left clean")
        require(
            not owned_collections("raw_collection"),
            f"{fixture}: restore left protected collection",
        )
        require(settings.target_object == restored, f"{fixture}: restore target")
        restored_collections = tuple(
            sorted(collection.name for collection in restored.users_collection)
        )
        restored_visibility = (
            restored.hide_render,
            restored.hide_select,
            restored.hide_viewport,
            restored.hide_get(),
        )
        settings.intake_test_failure_stage = "AFTER_RAW_PROTECTION"
        try:
            prepare_selected_spar3d(bpy.context, restored)
        except RuntimeError as exc:
            require(
                "raw-protection rollback" in str(exc),
                f"{fixture}: wrong source-state rollback error",
            )
        else:
            raise AssertionError(f"{fixture}: source-state rollback did not fail")
        finally:
            settings.intake_test_failure_stage = ""
        require(
            tuple(sorted(collection.name for collection in restored.users_collection))
            == restored_collections,
            f"{fixture}: source collections not restored",
        )
        require(
            (
                restored.hide_render,
                restored.hide_select,
                restored.hide_viewport,
                restored.hide_get(),
            )
            == restored_visibility,
            f"{fixture}: source visibility not restored",
        )
        require(settings.target_object == restored, f"{fixture}: source rollback target")
        restored_report, restored_clean = prepare_selected_spar3d(
            bpy.context, restored
        )
        assert_preparation(restored_report, restored_clean, fixture)
        restore = {
            "passed": True,
            "source_state_rollback_passed": True,
            "reprepare_selected_passed": True,
        }
        clean = restored_clean
        report = restored_report

        if args.save_first_blend:
            args.save_first_blend.parent.mkdir(parents=True, exist_ok=True)
            bpy.ops.wm.save_as_mainfile(filepath=str(args.save_first_blend.resolve()))

    return {
        "fixture": str(fixture),
        "raw_vertices": report["raw"]["counts"]["vertices"],
        "clean_vertices": report["welded"]["counts"]["vertices"],
        "raw_components": report["raw"]["connected_components"],
        "clean_components": report["welded"]["connected_components"],
        "exact_vertices_welded": report["exact_vertices_welded"],
        "faces": report["welded"]["counts"]["polygons"],
        "uv_preserved": report["proof"]["uv_values_preserved"],
        "normal_preserved": report["proof"]["corner_normals_preserved"],
        "maximum_normal_angle_radians": report["proof"]["corner_normal_max_angle_radians"],
        "watertight": report["welded"]["watertight"],
        "boundary_edges": report["welded"]["boundary_edge_count"],
        "non_manifold_edges": report["welded"]["non_manifold_edge_count"],
        "final_height": report["normalization"]["final_height"],
        "final_ground_z": report["normalization"]["final_ground_z"],
        "readiness": report["readiness"],
        "downstream": {
            "target_validation": "PASSED",
            "rigging_geometry_analysis": "PASSED",
            "rigging_components": rig_analysis["connected_components"],
            "bone_heat_risk": rig_analysis["bone_heat_risk"],
            "texture_preview": "NOT_RUN_NO_SOURCE_VIEW_FIXTURES",
            "texture_bake": "NOT_RUN_NO_SOURCE_VIEW_FIXTURES",
            "fitted_skeleton_preview": "NOT_RUN_NO_CANONICAL_RIG_IN_THIS_HARNESS",
        },
        "idempotence": repeat,
        "rollback": rollback,
        "restore": restore,
    }


for fixture in args.fixture:
    require(fixture.resolve().is_file(), f"Fixture does not exist: {fixture}")

bpy.ops.wm.read_factory_settings(use_empty=True)
skin_and_bones_forge.register()
try:
    results = [run_fixture(path.resolve(), index) for index, path in enumerate(args.fixture)]
finally:
    try:
        skin_and_bones_forge.unregister()
    except RuntimeError:
        pass

payload = {
    "schema": 1,
    "blender_version": list(bpy.app.version),
    "fixture_count": len(results),
    "results": results,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print("SBF_SPAR3D_FIXTURE_MATRIX_OK", len(results), args.output.resolve())
