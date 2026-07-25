"""User-facing SPAR3D intake operators."""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from bpy.types import Operator
from bpy_extras.io_utils import ImportHelper

from ..intake import (
    analyze_geometry,
    compare_raw_and_clean,
    prepare_imported_spar3d,
    prepare_selected_spar3d,
    remove_protected_raw_source,
    restore_raw_source,
    write_intake_report,
)


def _settings(context):
    return context.scene.sbf_settings


def _failure(operator, settings, exc):
    message = str(exc)
    settings.intake_readiness = "FAILED"
    settings.intake_status_summary = f"Intake failed: {message}"
    settings.intake_validation_summary = "The previous Blender state was restored."
    settings.intake_recommended_action = "Review the error and source GLB."
    settings.status_message = f"SPAR3D intake error: {message}"
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


class SBF_OT_import_and_prepare_spar3d(Operator, ImportHelper):
    bl_idname = "sbf.import_and_prepare_spar3d"
    bl_label = "Import + Prepare SPAR3D Character"
    bl_description = (
        "Choose a raw SPAR3D GLB, import it, exact-weld seam duplicates, prove "
        "corner data, normalize it, and assign the production target"
    )
    bl_options = {"REGISTER"}

    filename_ext = ".glb"
    filter_glob: bpy.props.StringProperty(
        default="*.glb;*.gltf", options={"HIDDEN"}
    )

    def execute(self, context):
        settings = _settings(context)
        try:
            report, _clean = prepare_imported_spar3d(context, self.filepath)
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            return _failure(self, settings, exc)
        self.report(
            {"INFO" if report["readiness"] == "READY_FOR_SKIN" else "WARNING"},
            f"SPAR3D preparation: {report['readiness']}",
        )
        return {"FINISHED"}


class SBF_OT_prepare_selected_spar3d(Operator):
    bl_idname = "sbf.prepare_selected_spar3d"
    bl_label = "Prepare Selected SPAR3D Character"
    bl_description = (
        "Prepare an already imported raw SPAR3D character using exact-position welding"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            report, _clean = prepare_selected_spar3d(context)
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            return _failure(self, settings, exc)
        self.report(
            {"INFO" if report["readiness"] == "READY_FOR_SKIN" else "WARNING"},
            f"SPAR3D preparation: {report['readiness']}",
        )
        return {"FINISHED"}


def _selected_mesh(context):
    active = context.view_layer.objects.active
    if active is not None and active.type == "MESH":
        return active
    selected = [obj for obj in context.selected_objects if obj.type == "MESH"]
    if len(selected) == 1:
        return selected[0]
    target = _settings(context).target_object
    if target is not None and target.type == "MESH":
        return target
    raise ValueError("Select one mesh for intake diagnostics.")


class SBF_OT_analyze_spar3d(Operator):
    bl_idname = "sbf.analyze_spar3d"
    bl_label = "Analyze Selected Raw Mesh"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            obj = _selected_mesh(context)
            analysis = analyze_geometry(obj, include_corner_data=True)
            report = {
                "schema": 1,
                "kind": "SPAR3D_RAW_ANALYSIS",
                "source_object": obj.name,
                "raw": analysis,
            }
            settings.intake_report_json = json.dumps(
                report, sort_keys=True, separators=(",", ":")
            )
            write_intake_report(context, report=report)
            settings.intake_status_summary = (
                f"Raw: {analysis['counts']['vertices']:,} vertices, "
                f"{analysis['connected_components']:,} components, "
                f"{analysis['exact_duplicate_vertices']:,} exact duplicates."
            )
            settings.intake_validation_summary = (
                f"Boundary {analysis['boundary_edge_count']:,}; "
                f"non-manifold {analysis['non_manifold_edge_count']:,}."
            )
            self.report({"INFO"}, settings.intake_status_summary)
            return {"FINISHED"}
        except (RuntimeError, TypeError, ValueError) as exc:
            return _failure(self, settings, exc)


class SBF_OT_preview_exact_weld(Operator):
    bl_idname = "sbf.preview_exact_weld"
    bl_label = "Preview Exact Weld Statistics"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            analysis = analyze_geometry(
                _selected_mesh(context), include_corner_data=False
            )
            predicted = (
                analysis["counts"]["vertices"]
                - analysis["exact_duplicate_vertices"]
                - len(analysis["loose_vertices"])
            )
            settings.intake_status_summary = (
                f"Exact-only preview: {analysis['counts']['vertices']:,} → "
                f"approximately {predicted:,} vertices; "
                f"{analysis['exact_duplicate_vertices']:,} exact welds."
            )
            thresholds = analysis["near_duplicate_statistics"]
            settings.intake_validation_summary = "; ".join(
                f"{item['distance']:.3g} m: {item['non_exact_pairs']:,} near pairs"
                for item in thresholds
            ) or "No near-coordinate diagnostics."
            self.report({"INFO"}, settings.intake_status_summary)
            return {"FINISHED"}
        except (RuntimeError, TypeError, ValueError) as exc:
            return _failure(self, settings, exc)


class SBF_OT_write_intake_report(Operator):
    bl_idname = "sbf.write_intake_report"
    bl_label = "Write Intake Report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            text = write_intake_report(context)
            settings.status_message = f"Wrote Blender text report: {text.name}"
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _failure(self, settings, exc)


class SBF_OT_compare_raw_clean(Operator):
    bl_idname = "sbf.compare_raw_clean"
    bl_label = "Compare Raw and Clean"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            result = compare_raw_and_clean(context)
            settings.intake_status_summary = (
                f"Raw → clean: {result['raw_vertices']:,} → "
                f"{result['clean_vertices']:,} vertices; "
                f"{result['raw_components']:,} → {result['clean_components']:,} components."
            )
            settings.intake_validation_summary = (
                f"Faces {result['raw_faces']:,} → {result['clean_faces']:,}; "
                f"watertight {result['clean_watertight']}; raw unchanged "
                f"{result['raw_fingerprint_unchanged']}."
            )
            self.report({"INFO"}, settings.intake_validation_summary)
            return {"FINISHED"}
        except (RuntimeError, TypeError, ValueError) as exc:
            return _failure(self, settings, exc)


class SBF_OT_restore_raw_spar3d(Operator):
    bl_idname = "sbf.restore_raw_spar3d"
    bl_label = "Restore Raw SPAR3D Source"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            raw = restore_raw_source(context)
            self.report({"INFO"}, f"Restored protected raw source: {raw.name}")
            return {"FINISHED"}
        except (RuntimeError, TypeError, ValueError) as exc:
            return _failure(self, settings, exc)


class SBF_OT_remove_raw_spar3d(Operator):
    bl_idname = "sbf.remove_raw_spar3d"
    bl_label = "Remove Protected Raw Source"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            count = remove_protected_raw_source(context)
            self.report({"INFO"}, f"Removed {count} protected raw objects.")
            return {"FINISHED"}
        except (RuntimeError, TypeError, ValueError) as exc:
            return _failure(self, settings, exc)


INTAKE_OPERATOR_CLASSES = (
    SBF_OT_import_and_prepare_spar3d,
    SBF_OT_prepare_selected_spar3d,
    SBF_OT_analyze_spar3d,
    SBF_OT_preview_exact_weld,
    SBF_OT_write_intake_report,
    SBF_OT_compare_raw_clean,
    SBF_OT_restore_raw_spar3d,
    SBF_OT_remove_raw_spar3d,
)
