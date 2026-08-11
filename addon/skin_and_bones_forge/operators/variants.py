"""Artist operators for appearance variant families."""

from __future__ import annotations

import json

from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from ..baking.repair_service import validate_repair_for_delivery
from ..rigging.production import export_rigged_glb, production_armature
from ..validation import ValidationError, validate_target
from ..variants.runtime import (
    active_variant,
    add_variant,
    approve_active_variant,
    create_family,
    delete_variant,
    handoff_for_variant,
    rename_active_variant,
    restore_variant_to_settings,
    switch_active_variant,
    unapprove_active_variant,
    validate_active_variant_for_export,
    validate_family_compatibility,
    variant_glb_path,
)


def _settings(context):
    return context.scene.sbf_settings


def _fail(operator, settings, exc):
    message = str(exc)
    settings.status_message = f"Appearance Variants: {message}"
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


def _production_contract(settings):
    try:
        contract = json.loads(settings.rig_production_contract_json or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Production rig contract is unreadable.") from exc
    if not contract.get("fingerprint"):
        raise RuntimeError("Finalize the production rig before variant export.")
    return contract


def _export_active(context, settings):
    variant = validate_active_variant_for_export(settings)
    if sum(
        item.export_name == variant.export_name
        for item in settings.appearance_variants
    ) != 1:
        raise RuntimeError("Appearance export identities must be unique.")
    info = validate_target(context, settings)
    validate_repair_for_delivery(info, settings)
    armature = production_armature(info.obj)
    if armature is None or not armature.get("sbf_production_rig", False):
        raise RuntimeError("Finalize the shared production rig before export.")
    output = variant_glb_path(settings, variant)
    output, manifest = export_rigged_glb(
        context,
        info.obj,
        armature,
        _production_contract(settings),
        settings,
        output_path=output,
        appearance_handoff=handoff_for_variant(settings, variant),
    )
    variant.last_export_path = str(output)
    return variant, output, manifest


class SBF_OT_create_appearance_family(Operator):
    bl_idname = "sbf.create_appearance_family"
    bl_label = "Create Variant Family From Current Appearance"
    bl_description = (
        "Adopt the current prepared character and appearance as one shared-body "
        "variant family"
    )
    bl_options = {"REGISTER", "UNDO"}

    display_name: StringProperty(name="Family Name", default="")

    def execute(self, context):
        settings = _settings(context)
        try:
            info = validate_target(context, settings)
            variant = create_family(settings, info.obj, self.display_name)
            settings.status_message = (
                f"Created family '{settings.appearance_family_name}' with "
                f"'{variant.display_name}'."
            )
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_add_appearance_variant(Operator):
    bl_idname = "sbf.add_appearance_variant"
    bl_label = "Add Appearance Variant"
    bl_description = "Add a blank appearance without duplicating the technical body"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            variant = add_variant(settings, duplicate=False)
            settings.status_message = f"Added blank variant '{variant.display_name}'."
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_duplicate_appearance_variant(Operator):
    bl_idname = "sbf.duplicate_appearance_variant"
    bl_label = "Duplicate Appearance Settings"
    bl_description = (
        "Copy source selections and calibration only; bake, repair, and approval "
        "remain empty"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            variant = add_variant(settings, duplicate=True)
            settings.status_message = (
                f"Duplicated settings into unapproved '{variant.display_name}'."
            )
            return {"FINISHED"}
        except (RuntimeError, ValueError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_cycle_appearance_variant(Operator):
    bl_idname = "sbf.cycle_appearance_variant"
    bl_label = "Cycle Appearance Variant"
    bl_options = {"REGISTER"}

    direction: IntProperty(default=1, min=-1, max=1)

    def execute(self, context):
        settings = _settings(context)
        count = len(settings.appearance_variants)
        if not count:
            return _fail(self, settings, "Create an appearance family first.")
        settings.active_variant_index = (
            settings.active_variant_index + self.direction
        ) % count
        switch_active_variant(context.scene, context)
        return {"FINISHED"}


class SBF_OT_rename_appearance_variant(Operator):
    bl_idname = "sbf.rename_appearance_variant"
    bl_label = "Rename Appearance Variant"
    bl_options = {"REGISTER", "UNDO"}

    display_name: StringProperty(name="Appearance Name", default="")

    def invoke(self, context, _event):
        variant = active_variant(_settings(context))
        self.display_name = variant.display_name if variant else ""
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        settings = _settings(context)
        try:
            variant = rename_active_variant(settings, self.display_name)
            settings.status_message = f"Renamed active appearance to '{variant.display_name}'."
            return {"FINISHED"}
        except RuntimeError as exc:
            return _fail(self, settings, exc)


class SBF_OT_delete_appearance_variant(Operator):
    bl_idname = "sbf.delete_appearance_variant"
    bl_label = "Delete Appearance Variant"
    bl_description = "Delete only the active variant-owned images and settings"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)

    def execute(self, context):
        settings = _settings(context)
        try:
            deleted = delete_variant(settings, settings.active_variant_index)
            settings.status_message = (
                f"Deleted appearance {deleted[:8]}; shared body and rig preserved."
            )
            return {"FINISHED"}
        except RuntimeError as exc:
            return _fail(self, settings, exc)


class SBF_OT_validate_appearance_family(Operator):
    bl_idname = "sbf.validate_appearance_family"
    bl_label = "Validate Shared Technical Body"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            if not validate_family_compatibility(settings):
                raise RuntimeError(
                    "Technical mesh, rig, weights, UV contract, scale, or axes changed."
                )
            settings.status_message = "Appearance family technical body is compatible."
            return {"FINISHED"}
        except RuntimeError as exc:
            return _fail(self, settings, exc)


class SBF_OT_approve_appearance_variant(Operator):
    bl_idname = "sbf.approve_appearance_variant"
    bl_label = "Approve Appearance Variant"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            variant = approve_active_variant(context)
            settings.status_message = f"Approved '{variant.display_name}'."
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, OSError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_unapprove_appearance_variant(Operator):
    bl_idname = "sbf.unapprove_appearance_variant"
    bl_label = "Unapprove Appearance Variant"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _settings(context)
        try:
            variant = unapprove_active_variant(settings)
            settings.status_message = f"Removed approval from '{variant.display_name}'."
            return {"FINISHED"}
        except RuntimeError as exc:
            return _fail(self, settings, exc)


class SBF_OT_export_active_appearance(Operator):
    bl_idname = "sbf.export_active_appearance"
    bl_label = "Export Active Appearance"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        try:
            variant, output, _manifest = _export_active(context, settings)
            settings.status_message = f"Exported '{variant.display_name}' to {output}."
            self.report({"INFO"}, settings.status_message)
            return {"FINISHED"}
        except (ValidationError, RuntimeError, ValueError, KeyError, OSError) as exc:
            return _fail(self, settings, exc)


class SBF_OT_export_approved_appearances(Operator):
    bl_idname = "sbf.export_approved_appearances"
    bl_label = "Export All Approved Appearances"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _settings(context)
        original_index = settings.active_variant_index
        approved = [
            index
            for index, variant in enumerate(settings.appearance_variants)
            if variant.approval_state == "APPROVED"
        ]
        if not approved:
            return _fail(self, settings, "No approved appearance variants exist.")
        exported = []
        names = [settings.appearance_variants[index].export_name for index in approved]
        if len(names) != len(set(names)):
            return _fail(self, settings, "Approved export identities must be unique.")
        try:
            for index in approved:
                settings.active_variant_index = index
                switch_active_variant(context.scene, context)
                variant, output, _manifest = _export_active(context, settings)
                exported.append((variant.display_name, output))
        except (ValidationError, RuntimeError, ValueError, KeyError, OSError) as exc:
            return _fail(self, settings, exc)
        finally:
            if len(settings.appearance_variants):
                settings.active_variant_index = min(
                    original_index, len(settings.appearance_variants) - 1
                )
                restore_variant_to_settings(settings, active_variant(settings))
        settings.status_message = f"Exported {len(exported)} approved appearances."
        self.report({"INFO"}, settings.status_message)
        return {"FINISHED"}


VARIANT_OPERATOR_CLASSES = (
    SBF_OT_create_appearance_family,
    SBF_OT_add_appearance_variant,
    SBF_OT_duplicate_appearance_variant,
    SBF_OT_cycle_appearance_variant,
    SBF_OT_rename_appearance_variant,
    SBF_OT_delete_appearance_variant,
    SBF_OT_validate_appearance_family,
    SBF_OT_approve_appearance_variant,
    SBF_OT_unapprove_appearance_variant,
    SBF_OT_export_active_appearance,
    SBF_OT_export_approved_appearances,
)


__all__ = ("VARIANT_OPERATOR_CLASSES",)
