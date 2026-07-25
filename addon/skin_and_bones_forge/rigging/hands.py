"""Singular production-hand alignments and numerical checks."""

from __future__ import annotations

import json
import math

from mathutils import Quaternion


HAND_POSES = ("RELAXED", "OPEN_MAGIC", "GRIP_SHAFT")
HAND_POSE_PROPERTY = "sbf_hand_pose"
HAND_PRESETS_PROPERTY = "sbf_owned_hand_presets"
RESERVED_HAND_SHAPE_KEYS = (
    "DSB_HAND_OPEN_MAGIC",
    "DSB_HAND_GRIP_SHAFT",
)

def apply_hand_pose(armature, pose_name):
    """Apply a whole-hand alignment preset without finger articulation."""

    if pose_name not in HAND_POSES:
        raise ValueError(f"Unknown hand pose '{pose_name}'.")
    for side in ("left", "right"):
        pose_bone = armature.pose.bones.get(f"arm_{side}_hand")
        if pose_bone is None:
            continue
        pose_bone.matrix_basis.identity()
        pose_bone.rotation_mode = "QUATERNION"
        sign = 1.0 if side == "left" else -1.0
        if pose_name == "OPEN_MAGIC":
            pose_bone.rotation_quaternion = (
                Quaternion((0.0, 0.0, 1.0), math.radians(sign * 10.0))
                @ Quaternion((1.0, 0.0, 0.0), math.radians(-6.0))
            )
        elif pose_name == "GRIP_SHAFT":
            pose_bone.rotation_quaternion = Quaternion(
                (0.0, 1.0, 0.0), math.radians(sign * 24.0)
            )
    armature.data.pose_position = "POSE"
    armature[HAND_POSE_PROPERTY] = pose_name
    armature[HAND_PRESETS_PROPERTY] = json.dumps(list(HAND_POSES))
    return pose_name


def pose_transforms_finite(armature):
    invalid = []
    for name in ("arm_left_hand", "arm_right_hand"):
        pose_bone = armature.pose.bones.get(name)
        if pose_bone is None:
            invalid.append(name)
            continue
        if any(
            not math.isfinite(float(value))
            for row in pose_bone.matrix
            for value in row
        ):
            invalid.append(pose_bone.name)
    return invalid


def _world_point(armature, point):
    return armature.matrix_world @ point


def hand_metrics(armature, target_height):
    """Validate the two retained singular hand bones."""

    per_side = {}
    for side in ("left", "right"):
        hand = armature.pose.bones.get(f"arm_{side}_hand")
        if hand is None:
            per_side[side] = {"missing": True}
            continue
        head = _world_point(armature, hand.head)
        tail = _world_point(armature, hand.tail)
        length = (tail - head).length
        per_side[side] = {
            "missing": False,
            "bone": hand.name,
            "parent": hand.parent.name if hand.parent else None,
            "world_head": [round(float(value), 6) for value in head],
            "world_tail": [round(float(value), 6) for value in tail],
            "length": round(length, 6),
            "length_to_height": round(length / max(target_height, 1e-8), 4),
        }

    warnings = []
    for side, metrics in per_side.items():
        if metrics.get("missing"):
            warnings.append(f"{side.title()} hand subrig is missing.")
            continue
        if metrics["parent"] != f"arm_{side}_bot":
            warnings.append(f"{side.title()} hand has the wrong forearm parent.")
        if metrics["length_to_height"] > 0.12:
            warnings.append(
                f"{side.title()} singular hand bone exceeds 12% of target height."
            )
    asymmetry = {}
    if not per_side["left"].get("missing") and not per_side["right"].get("missing"):
        left = per_side["left"]["length"]
        right = per_side["right"]["length"]
        asymmetry["length"] = round(
            abs(left - right) / max(left, right, 1e-8), 4
        )
        if asymmetry["length"] > 0.38:
            warnings.append("Left/right singular hand lengths are excessively asymmetric.")
    return {
        "pose": armature.get(HAND_POSE_PROPERTY, ""),
        "owned_presets": json.loads(
            armature.get(HAND_PRESETS_PROPERTY, "[]")
        ),
        "reserved_shape_keys": list(RESERVED_HAND_SHAPE_KEYS),
        "left": per_side["left"],
        "right": per_side["right"],
        "asymmetry": asymmetry,
        "invalid_pose_bones": pose_transforms_finite(armature),
        "warnings": warnings,
        "compact": not warnings,
    }
