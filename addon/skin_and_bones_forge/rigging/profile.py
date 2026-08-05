"""Versioned simplified production contract derived from the full source rig."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re


SIMPLE_HANDS_PROFILE = "DSB_SIMPLE_HANDS_V1"
HAND_BONES = {
    "left": "arm_left_hand",
    "right": "arm_right_hand",
}
PRODUCTION_BONE_NAMES = (
    "root",
    "body",
    "body_top0",
    "body_top1",
    "body_top2",
    "shoulder_right",
    "arm_right_top",
    "arm_right_bot",
    "arm_right_hand",
    "neck",
    "head",
    "shoulder_left",
    "arm_left_top",
    "arm_left_bot",
    "arm_left_hand",
    "leg_right_top",
    "leg_right_bot",
    "leg_right_foot",
    "leg_left_top",
    "leg_left_bot",
    "leg_left_foot",
)
FINGER_ROOT_PATTERN = re.compile(
    r"^(thumb|index|middle|ring|little|pinky)_(left|right)(?:[._-]?\d+)?"
    r"(?:[._-]?(?:end|tip))?$",
    re.IGNORECASE,
)


def _children(contract):
    result = {bone["name"]: [] for bone in contract["bones"]}
    for bone in contract["bones"]:
        if bone["parent"] in result:
            result[bone["parent"]].append(bone["name"])
    return result


def _descendants(children, root):
    result = []
    stack = list(reversed(children.get(root, [])))
    while stack:
        name = stack.pop()
        result.append(name)
        stack.extend(reversed(children.get(name, [])))
    return result


def identify_finger_descendants(full_contract):
    names = {bone["name"] for bone in full_contract["bones"]}
    parents = {
        bone["name"]: bone["parent"] for bone in full_contract["bones"]
    }
    children = _children(full_contract)
    removed_to_hand = {}
    roots = {"left": [], "right": []}
    for side, hand_name in HAND_BONES.items():
        if hand_name not in names:
            raise ValueError(f"Canonical source is missing retained hand bone '{hand_name}'.")
        expected_parent = f"arm_{side}_bot"
        if parents[hand_name] != expected_parent:
            raise ValueError(
                f"Retained hand bone '{hand_name}' is not parented to "
                f"'{expected_parent}'."
            )
        for child_name in children[hand_name]:
            match = FINGER_ROOT_PATTERN.fullmatch(child_name)
            if match is None or match.group(2).lower() != side:
                continue
            roots[side].append(child_name)
            removed_to_hand[child_name] = hand_name
            for descendant in _descendants(children, child_name):
                removed_to_hand[descendant] = hand_name

    named_fingers = {
        name for name in names if FINGER_ROOT_PATTERN.fullmatch(name)
    }
    unclassified = sorted(named_fingers - set(removed_to_hand))
    if unclassified:
        raise ValueError(
            "Finger-like canonical bones are outside verified hand subtrees: "
            + ", ".join(unclassified)
        )
    if not roots["left"] or not roots["right"]:
        raise ValueError("Could not verify finger roots beneath both retained hands.")
    return {
        "removed_to_hand": dict(sorted(removed_to_hand.items())),
        "finger_roots": {
            side: sorted(values) for side, values in roots.items()
        },
    }


def _fingerprint_payload(contract):
    return {
        "schema": 1,
        "profile_id": contract["profile_id"],
        "source_fingerprint": contract["source_fingerprint"],
        "bones": [
            {
                "name": bone["name"],
                "parent": bone["parent"],
                "deform": bone["deform"],
                "connected": bone["connected"],
                "head": bone["head"],
                "tail": bone["tail"],
                "roll": bone["roll"],
                "matrix_local": bone["matrix_local"],
            }
            for bone in contract["bones"]
        ],
    }


def simplified_fingerprint(contract):
    encoded = json.dumps(
        _fingerprint_payload(contract),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_simplified_contract(full_contract):
    names = tuple(bone["name"] for bone in full_contract["bones"])
    direct_profile = names == PRODUCTION_BONE_NAMES
    if direct_profile:
        discovery = {
            "removed_to_hand": {},
            "finger_roots": {"left": [], "right": []},
        }
    else:
        discovery = identify_finger_descendants(full_contract)
    removed_to_hand = discovery["removed_to_hand"]
    removed = set(removed_to_hand)
    result = deepcopy(full_contract)
    result["schema"] = 1
    result["profile_id"] = SIMPLE_HANDS_PROFILE
    result["source_fingerprint"] = full_contract["fingerprint"]
    result["source_bone_count"] = len(full_contract["bones"])
    result["source_deform_bone_count"] = sum(
        bool(bone["deform"]) for bone in full_contract["bones"]
    )
    result["source_action_count"] = len(
        full_contract["animation_inventory"]["actions"]
    )
    result["source_nla_track_count"] = len(
        full_contract["animation_inventory"]["nla_tracks"]
    )
    result["retained_hand_bones"] = dict(HAND_BONES)
    result["source_bones"] = deepcopy(full_contract["bones"])
    result["canonical_template_is_production_profile"] = direct_profile
    result["finger_roots"] = discovery["finger_roots"]
    result["removed_to_hand"] = removed_to_hand
    result["removed_bones"] = [
        bone["name"] for bone in full_contract["bones"] if bone["name"] in removed
    ]
    result["bones"] = [
        bone for bone in result["bones"] if bone["name"] not in removed
    ]
    result["production_bone_count"] = len(result["bones"])
    result["production_deform_bone_count"] = sum(
        bool(bone["deform"]) for bone in result["bones"]
    )
    result["reserved_hand_shape_keys"] = [
        "DSB_HAND_OPEN_MAGIC",
        "DSB_HAND_GRIP_SHAFT",
    ]
    result["fingerprint"] = simplified_fingerprint(result)
    validation = validate_simplified_contract(full_contract, result)
    if not validation["valid"]:
        raise ValueError(
            "Simplified production contract is invalid: "
            + " | ".join(validation["errors"])
        )
    result["profile_validation"] = validation
    return result


def validate_simplified_contract(full_contract, production_contract):
    errors = []
    full = {bone["name"]: bone for bone in full_contract["bones"]}
    production = {
        bone["name"]: bone for bone in production_contract["bones"]
    }
    removed = set(production_contract.get("removed_bones", []))
    direct_profile = bool(
        production_contract.get("canonical_template_is_production_profile")
    )
    if direct_profile:
        expected = {}
        if tuple(full) != PRODUCTION_BONE_NAMES:
            errors.append(
                "Direct canonical template does not match the 21-bone profile."
            )
    else:
        expected = identify_finger_descendants(full_contract)[
            "removed_to_hand"
        ]
    expected_removed = set(expected)
    if production_contract.get("profile_id") != SIMPLE_HANDS_PROFILE:
        errors.append("Unexpected simplified production profile identifier.")
    if production_contract.get("source_fingerprint") != full_contract["fingerprint"]:
        errors.append("Simplified contract does not reference the full source fingerprint.")
    if removed != expected_removed:
        errors.append("Simplified contract finger exclusion set is incomplete or excessive.")
    if set(production) != set(full) - expected_removed:
        errors.append("Simplified contract removed unrelated bones or retained finger bones.")
    hierarchy_mismatches = [
        name
        for name, bone in production.items()
        if bone["parent"] != full[name]["parent"]
    ]
    if hierarchy_mismatches:
        errors.append("Remaining production hierarchy differs from the source.")
    deform_mismatches = [
        name
        for name, bone in production.items()
        if bool(bone["deform"]) != bool(full[name]["deform"])
    ]
    if deform_mismatches:
        errors.append("Remaining production deform flags differ from the source.")
    for side, hand_name in HAND_BONES.items():
        hand = production.get(hand_name)
        if hand is None:
            errors.append(f"Retained {side} hand bone is missing.")
        elif hand["parent"] != f"arm_{side}_bot":
            errors.append(f"Retained {side} hand has the wrong forearm parent.")
    fingerprint_match = (
        production_contract.get("fingerprint")
        == simplified_fingerprint(production_contract)
    )
    if not fingerprint_match:
        errors.append("Simplified production fingerprint is stale.")
    return {
        "valid": not errors,
        "profile_id": production_contract.get("profile_id"),
        "source_fingerprint": full_contract["fingerprint"],
        "production_fingerprint": production_contract.get("fingerprint"),
        "original_bone_count": len(full),
        "original_deform_bone_count": sum(
            bool(bone["deform"]) for bone in full.values()
        ),
        "removed_bone_count": len(expected_removed),
        "removed_bones": [
            bone["name"]
            for bone in full_contract["bones"]
            if bone["name"] in expected_removed
        ],
        "remaining_bone_count": len(production),
        "remaining_deform_bone_count": sum(
            bool(bone["deform"]) for bone in production.values()
        ),
        "retained_hand_bones": dict(HAND_BONES),
        "canonical_template_is_production_profile": direct_profile,
        "hierarchy_mismatches": hierarchy_mismatches,
        "deform_flag_mismatches": deform_mismatches,
        "fingerprint_match": fingerprint_match,
        "errors": errors,
    }
