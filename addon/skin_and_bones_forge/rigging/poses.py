"""Owned pose torture tests and canonical Action compatibility checks."""

from __future__ import annotations

import json
import math
import re

import bpy
from mathutils import Quaternion, Vector

from ..constants import RIG_OWNER_PROPERTY
from .analysis import evaluated_points
from .deformation import scan_action_deformation
from .fitting import OWNER
from .hands import apply_hand_pose


POSE_TEST_ACTION = "SBF_PoseTorture_Temporary"
PRODUCTION_ACTION_PREFIX = "SBF_Production_"
PRODUCTION_TRACK_PREFIX = "SBF_ProductionTrack_"


POSE_TESTS = {
    "ISOLATED_PELVIS": (("body", "X", 35.0),),
    "ISOLATED_SPINE_LOWER": (("body_top0", "Y", 30.0),),
    "ISOLATED_SPINE_MIDDLE": (("body_top1", "Y", 30.0),),
    "ISOLATED_SPINE_UPPER": (("body_top2", "Y", 30.0),),
    "ISOLATED_UPPER_ARM_LEFT": (("arm_left_top", "Z", -45.0),),
    "ISOLATED_UPPER_ARM_RIGHT": (("arm_right_top", "Z", 45.0),),
    "ISOLATED_FOREARM_LEFT": (("arm_left_bot", "X", 45.0),),
    "ISOLATED_FOREARM_RIGHT": (("arm_right_bot", "X", 45.0),),
    "ISOLATED_THIGH_LEFT": (("leg_left_top", "X", 45.0),),
    "ISOLATED_THIGH_RIGHT": (("leg_right_top", "X", 45.0),),
    "ISOLATED_SHIN_LEFT": (("leg_left_bot", "X", 45.0),),
    "ISOLATED_SHIN_RIGHT": (("leg_right_bot", "X", 45.0),),
    "ELBOW_LEFT": (("arm_left_bot", "X", 82.0),),
    "ELBOW_RIGHT": (("arm_right_bot", "X", 82.0),),
    "ARMS_RAISED": (
        ("arm_left_top", "Z", -72.0),
        ("arm_right_top", "Z", 72.0),
    ),
    "SHOULDER_REACH": (
        ("shoulder_left", "X", 24.0),
        ("shoulder_right", "X", 24.0),
        ("arm_left_top", "Z", -45.0),
        ("arm_right_top", "Z", 45.0),
    ),
    "WRIST_ROTATION": (
        ("arm_left_hand", "Y", 75.0),
        ("arm_right_hand", "Y", -75.0),
    ),
    "TORSO_TWIST": (
        ("body_top0", "Y", 12.0),
        ("body_top1", "Y", 18.0),
        ("body_top2", "Y", 24.0),
    ),
    "HEAD_TURN_TILT": (
        ("neck", "Y", 22.0),
        ("head", "Z", 28.0),
        ("head", "X", 12.0),
    ),
    "HIP_BEND": (
        ("leg_left_top", "X", 48.0),
        ("leg_right_top", "X", 48.0),
    ),
    "KNEE_LEFT": (("leg_left_bot", "X", 88.0),),
    "KNEE_RIGHT": (("leg_right_bot", "X", 88.0),),
    "ONE_LEG_STEP": (
        ("leg_left_top", "X", 42.0),
        ("leg_left_bot", "X", 52.0),
        ("leg_right_top", "X", -12.0),
    ),
    "CROUCH": (
        ("leg_left_top", "X", 38.0),
        ("leg_right_top", "X", 38.0),
        ("leg_left_bot", "X", 72.0),
        ("leg_right_bot", "X", 72.0),
        ("body", "X", -12.0),
    ),
    "ANKLE_BEND": (
        ("leg_left_foot", "X", 24.0),
        ("leg_right_foot", "X", 24.0),
    ),
    "RELAXED_FULL_BODY": (
        ("body_top1", "Y", 4.0),
        ("head", "Z", 4.0),
        ("arm_left_top", "Z", -5.0),
        ("arm_right_top", "Z", 5.0),
    ),
}


def _pose_snapshot(armature, scene):
    animation = armature.animation_data
    return {
        "frame": scene.frame_current,
        "action": animation.action if animation else None,
        "action_slot": animation.action_slot if animation else None,
        "nla": (
            [(track, bool(track.mute)) for track in animation.nla_tracks]
            if animation
            else []
        ),
        "pose_position": armature.data.pose_position,
        "matrix_basis": {
            bone.name: bone.matrix_basis.copy() for bone in armature.pose.bones
        },
        "rotation_mode": {
            bone.name: bone.rotation_mode for bone in armature.pose.bones
        },
    }


def _restore_pose(armature, scene, snapshot):
    armature.data.pose_position = snapshot["pose_position"]
    animation = armature.animation_data
    if animation is not None:
        animation.action = snapshot["action"]
        if snapshot["action"] is not None and snapshot["action_slot"] is not None:
            animation.action_slot = snapshot["action_slot"]
    for track, mute in snapshot["nla"]:
        try:
            track.mute = mute
        except ReferenceError:
            pass
    scene.frame_set(snapshot["frame"])
    for bone in armature.pose.bones:
        matrix = snapshot["matrix_basis"].get(bone.name)
        if matrix is not None:
            bone.matrix_basis = matrix
        mode = snapshot["rotation_mode"].get(bone.name)
        if mode is not None:
            bone.rotation_mode = mode


def _reset_pose(armature):
    armature.data.pose_position = "POSE"
    for bone in armature.pose.bones:
        bone.matrix_basis.identity()


def _apply_rotations(armature, rotations):
    axes = {
        "X": Vector((1.0, 0.0, 0.0)),
        "Y": Vector((0.0, 1.0, 0.0)),
        "Z": Vector((0.0, 0.0, 1.0)),
    }
    for name, axis, degrees in rotations:
        bone = armature.pose.bones.get(name)
        if bone is None:
            continue
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion = (
            Quaternion(axes[axis], math.radians(degrees))
            @ bone.rotation_quaternion
        )


def _bounds(points):
    minimum = Vector(min(point[index] for point in points) for index in range(3))
    maximum = Vector(max(point[index] for point in points) for index in range(3))
    return minimum, maximum


def _evaluate_safety(context, target, rest_points, height, safety_ratio):
    points = evaluated_points(context, target)
    non_finite = sum(
        1
        for point in points
        if any(not math.isfinite(float(value)) for value in point)
    )
    rest_min, rest_max = _bounds(rest_points)
    minimum, maximum = _bounds(points)
    rest_diagonal = max((rest_max - rest_min).length, height)
    diagonal = (maximum - minimum).length
    displacements = [
        (point - rest).length for point, rest in zip(points, rest_points)
    ]
    max_displacement = max(displacements, default=0.0)
    rest_center = (rest_min + rest_max) * 0.5
    center = (minimum + maximum) * 0.5
    global_translation = center - rest_center
    max_relative_displacement = max(
        (
            point - rest - global_translation
        ).length
        for point, rest in zip(points, rest_points)
    )
    meaningful_deformation = max_displacement > height * 1.0e-5
    explosive = sum(
        (point - rest - global_translation).length > height * 1.25
        for point, rest in zip(points, rest_points)
    )
    safe = (
        not non_finite
        and not explosive
        and meaningful_deformation
        and diagonal <= rest_diagonal * safety_ratio
        and max_relative_displacement <= height * 1.5
    )
    return {
        "safe": safe,
        "non_finite_vertices": non_finite,
        "explosive_vertices": explosive,
        "maximum_displacement": round(max_displacement, 6),
        "maximum_relative_displacement": round(
            max_relative_displacement, 6
        ),
        "meaningful_deformation": meaningful_deformation,
        "bounds_ratio": round(diagonal / max(rest_diagonal, 1.0e-8), 6),
        "bounds": {
            "minimum": [round(float(value), 6) for value in minimum],
            "maximum": [round(float(value), 6) for value in maximum],
        },
    }


def run_pose_torture_tests(
    context,
    target,
    armature,
    height,
    safety_ratio=1.8,
):
    scene = context.scene
    snapshot = _pose_snapshot(armature, scene)
    action = bpy.data.actions.get(POSE_TEST_ACTION)
    if action is not None:
        bpy.data.actions.remove(action, do_unlink=True)
    action = bpy.data.actions.new(POSE_TEST_ACTION)
    action[RIG_OWNER_PROPERTY] = OWNER
    action["sbf_temporary_pose_test"] = True
    animation = armature.animation_data_create()
    reports = []
    try:
        for track in animation.nla_tracks:
            track.mute = True
        animation.action = action
        _reset_pose(armature)
        context.view_layer.update()
        rest_points = evaluated_points(context, target)
        for name, rotations in POSE_TESTS.items():
            _reset_pose(armature)
            _apply_rotations(armature, rotations)
            if name == "RELAXED_FULL_BODY":
                apply_hand_pose(armature, "RELAXED")
                _apply_rotations(armature, rotations)
            context.view_layer.update()
            safety = _evaluate_safety(
                context, target, rest_points, height, safety_ratio
            )
            reports.append({"test": name, **safety})
        status = (
            "POSE_TESTS_PASSED"
            if all(report["safe"] for report in reports)
            else "POSE_TESTS_FAILED"
        )
        return {
            "status": status,
            "safety_ratio": safety_ratio,
            "tests": reports,
            "temporary_action": POSE_TEST_ACTION,
        }
    finally:
        _restore_pose(armature, scene, snapshot)
        context.view_layer.update()
        if action.name in bpy.data.actions:
            bpy.data.actions.remove(action, do_unlink=True)


def iter_action_fcurves(action):
    curves = []
    seen = set()
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        try:
            for curve in legacy:
                pointer = curve.as_pointer()
                if pointer not in seen:
                    seen.add(pointer)
                    curves.append(curve)
        except (AttributeError, TypeError, RuntimeError):
            pass
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                for curve in getattr(channelbag, "fcurves", []):
                    pointer = curve.as_pointer()
                    if pointer not in seen:
                        seen.add(pointer)
                        curves.append(curve)
    return curves


def _animated_bones(action):
    names = set()
    pattern = re.compile(r'pose\.bones\["([^"]+)"\]')
    for curve in iter_action_fcurves(action):
        match = pattern.search(curve.data_path)
        if match:
            names.add(match.group(1))
    return sorted(names)


def _assign_action(animation, action):
    animation.action = action
    suitable = list(getattr(animation, "action_suitable_slots", []))
    if suitable:
        animation.action_slot = suitable[0]
        return suitable[0]
    slots = [
        slot
        for slot in getattr(action, "slots", [])
        if getattr(slot, "target_id_type", "") == "OBJECT"
    ]
    if slots:
        animation.action_slot = slots[0]
        return slots[0]
    return None


def _remove_fcurve(action, curve):
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        try:
            legacy.remove(curve)
            return
        except (RuntimeError, TypeError, ValueError):
            pass
    pointer = curve.as_pointer()
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for channelbag in getattr(strip, "channelbags", []):
                for candidate in list(getattr(channelbag, "fcurves", [])):
                    if candidate.as_pointer() == pointer:
                        channelbag.fcurves.remove(candidate)
                        return
    raise RuntimeError(f"Could not remove filtered F-curve '{curve.data_path}'.")


def _scaled_action_copy(action, armature, contract, name, temporary):
    result = action.copy()
    result.name = name
    result[RIG_OWNER_PROPERTY] = OWNER
    result["sbf_source_action"] = action.name
    result["sbf_production_action"] = not temporary
    result["sbf_temporary_action_test"] = temporary
    removed_bones = set(contract.get("removed_bones", []))
    bone_pattern = re.compile(r'pose\.bones\["([^"]+)"\]')
    removed_channels = []
    for curve in list(iter_action_fcurves(result)):
        match = bone_pattern.search(curve.data_path)
        if match and match.group(1) in removed_bones:
            removed_channels.append(
                {
                    "bone": match.group(1),
                    "data_path": curve.data_path,
                    "array_index": int(curve.array_index),
                }
            )
            _remove_fcurve(result, curve)
    result["sbf_removed_finger_channel_count"] = len(removed_channels)
    result["sbf_removed_finger_channels"] = json.dumps(
        removed_channels, sort_keys=True, separators=(",", ":")
    )
    source_lengths = {
        record["name"]: (
            Vector(record["tail"]) - Vector(record["head"])
        ).length
        for record in contract["bones"]
    }
    ratios = {}
    pattern = re.compile(r'pose\.bones\["([^"]+)"\]\.location$')
    for curve in iter_action_fcurves(result):
        match = pattern.search(curve.data_path)
        if not match:
            continue
        bone_name = match.group(1)
        bone = armature.data.bones.get(bone_name)
        source_length = source_lengths.get(bone_name, 0.0)
        ratio = bone.length / source_length if bone and source_length > 1.0e-8 else 1.0
        ratios[bone_name] = ratio
        for point in curve.keyframe_points:
            point.co.y *= ratio
            point.handle_left.y *= ratio
            point.handle_right.y *= ratio
    result["sbf_location_scale_min"] = min(ratios.values(), default=1.0)
    result["sbf_location_scale_max"] = max(ratios.values(), default=1.0)
    return result


def clean_owned_production_actions(armature=None):
    removed = []
    if armature is not None and armature.animation_data is not None:
        for track in list(armature.animation_data.nla_tracks):
            if track.name.startswith(PRODUCTION_TRACK_PREFIX):
                removed.append(track.name)
                armature.animation_data.nla_tracks.remove(track)
    for action in list(bpy.data.actions):
        if action.get("sbf_production_action", False):
            removed.append(action.name)
            bpy.data.actions.remove(action, do_unlink=True)
    return removed


def _semantic_action_name(name):
    return re.sub(r"(?:\.\d{3})+$", "", name)


def canonical_expected_action_names(contract):
    """Return semantic Action names from the immutable saved contract."""

    return sorted(
        {
            _semantic_action_name(item["name"])
            for item in contract["animation_inventory"]["actions"]
        }
    )


def production_action_semantic_name(name):
    """Map an exported/imported production Action back to its contract name."""

    for prefix in (PRODUCTION_TRACK_PREFIX, PRODUCTION_ACTION_PREFIX):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return _semantic_action_name(name)


def canonical_source_actions(contract):
    """Resolve one live Action per canonical semantic name.

    Blender appends numeric suffixes when an Action is duplicated. Canonical
    analysis may therefore inventory both a source name and its transient
    duplicate even though they represent one animation fixture.
    """

    expected = set(canonical_expected_action_names(contract))
    available = {}
    for action in sorted(bpy.data.actions, key=lambda item: item.name):
        base = _semantic_action_name(action.name)
        if base not in expected:
            continue
        current = available.get(base)
        if current is None or action.name == base:
            available[base] = action
    return [available[name] for name in sorted(available)], sorted(
        expected - set(available)
    )


def create_production_actions(armature, contract):
    animation = armature.animation_data_create()
    clean_owned_production_actions(armature)
    sources, _missing = canonical_source_actions(contract)
    created = []
    for source in sources:
        action = _scaled_action_copy(
            source,
            armature,
            contract,
            f"{PRODUCTION_ACTION_PREFIX}{source.name}",
            temporary=False,
        )
        track = animation.nla_tracks.new()
        track.name = f"{PRODUCTION_TRACK_PREFIX}{source.name}"
        strip = track.strips.new(
            source.name,
            int(round(action.frame_range[0])),
            action,
        )
        slots = list(getattr(action, "slots", []))
        if slots and hasattr(strip, "action_slot"):
            strip.action_slot = slots[0]
        track.mute = True
        created.append(action)
    return created


def test_canonical_actions(
    context,
    target,
    armature,
    contract,
    height,
    safety_ratio=2.0,
):
    scene = context.scene
    snapshot = _pose_snapshot(armature, scene)
    actions, missing_actions = canonical_source_actions(contract)
    animation = armature.animation_data_create()
    reports = []
    temporary_actions = []
    try:
        for track in animation.nla_tracks:
            track.mute = True
        _reset_pose(armature)
        animation.action = None
        context.view_layer.update()
        rest_points = evaluated_points(context, target)
        for action in sorted(actions, key=lambda item: item.name):
            evaluated_action = _scaled_action_copy(
                action,
                armature,
                contract,
                f"SBF_ActionTest_{action.name}",
                temporary=True,
            )
            temporary_actions.append(evaluated_action)
            source_animated = _animated_bones(action)
            animated = _animated_bones(evaluated_action)
            removed_channels = json.loads(
                evaluated_action.get("sbf_removed_finger_channels", "[]")
            )
            missing = [
                name for name in animated if armature.pose.bones.get(name) is None
            ]
            frame_start, frame_end = map(float, action.frame_range)
            samples = sorted(
                {
                    int(round(frame_start)),
                    int(round((frame_start + frame_end) * 0.5)),
                    int(round(frame_end)),
                }
            )
            frame_reports = []
            assignment_error = ""
            assigned_slot = None
            deformation_forensics = None
            try:
                assigned_slot = _assign_action(animation, evaluated_action)
                for frame in samples:
                    scene.frame_set(frame)
                    context.view_layer.update()
                    frame_reports.append(
                        {
                            "frame": frame,
                            **_evaluate_safety(
                                context,
                                target,
                                rest_points,
                                height,
                                safety_ratio,
                            ),
                        }
                    )
                deformation_forensics = scan_action_deformation(
                    context,
                    target,
                    armature,
                    evaluated_action,
                    frames=range(
                        math.floor(frame_start), math.ceil(frame_end) + 1
                    ),
                )
            except (RuntimeError, TypeError) as exc:
                assignment_error = str(exc)
            safe = (
                not missing
                and not assignment_error
                and bool(animated)
                and any(
                    item["maximum_displacement"] > height * 1.0e-5
                    for item in frame_reports
                )
                and all(item["safe"] for item in frame_reports)
                and deformation_forensics is not None
                and deformation_forensics["status"]
                == "READY_FOR_ANIMATION_TEST"
                and deformation_forensics["state_restored"]
            )
            reports.append(
                {
                    "action": action.name,
                    "source_animated_bones": source_animated,
                    "resolved_animated_bones": [
                        name for name in animated if name not in missing
                    ],
                    "intentionally_removed_finger_bones": sorted(
                        set(source_animated) - set(animated)
                    ),
                    "removed_finger_channels": removed_channels,
                    "removed_finger_channel_count": len(removed_channels),
                    "missing_bones": missing,
                    "evaluated_frame_range": [frame_start, frame_end],
                    "sample_frames": frame_reports,
                    "assignment_error": assignment_error,
                    "production_location_scale": [
                        evaluated_action.get("sbf_location_scale_min", 1.0),
                        evaluated_action.get("sbf_location_scale_max", 1.0),
                    ],
                    "assigned_action_slot": (
                        assigned_slot.name_display if assigned_slot else None
                    ),
                    "meaningful_deformation": any(
                        item["maximum_displacement"] > height * 1.0e-5
                        for item in frame_reports
                    ),
                    "deformation_safe": safe,
                    "deformation_forensics": deformation_forensics,
                    "warnings": (
                        ["Action contains no pose-bone channels."] if not animated else []
                    ),
                }
            )
        status = (
            "CANONICAL_ACTIONS_PASSED"
            if not missing_actions
            and reports
            and all(report["deformation_safe"] for report in reports)
            else "CANONICAL_ACTIONS_FAILED"
        )
        return {
            "status": status,
            "production_profile": contract.get("profile_id", ""),
            "expected_actions": sorted(
                [action.name for action in actions] + missing_actions
            ),
            "missing_actions": missing_actions,
            "filtered_action_count": len(reports),
            "removed_finger_channel_count": sum(
                report["removed_finger_channel_count"] for report in reports
            ),
            "actions": reports,
        }
    finally:
        _restore_pose(armature, scene, snapshot)
        context.view_layer.update()
        for action in temporary_actions:
            if action.name in bpy.data.actions:
                bpy.data.actions.remove(action, do_unlink=True)
