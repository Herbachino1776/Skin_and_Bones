"""Automatic humanoid skeleton fitting public API."""

from .analysis import analyze_target, encode_analysis, topology_snapshot
from .compatibility import run_animation_forge_acceptance
from .contract import (
    analyze_canonical_rig,
    canonical_fingerprint,
    write_contract_report,
)
from .fitting import (
    clean_rig_preview,
    create_landmark_preview,
    fit_skeleton_preview,
    landmark_objects,
)
from .hands import (
    HAND_POSES,
    RESERVED_HAND_SHAPE_KEYS,
    apply_hand_pose,
    hand_metrics,
    pose_transforms_finite,
)
from .landmarks import (
    EDITABLE_LANDMARKS,
    LANDMARK_NAMES,
    apply_saved_corrections,
    confidence_summary,
    estimate_landmarks,
    reset_corrections,
    save_corrections,
)
from .poses import (
    clean_owned_production_actions,
    create_production_actions,
    iter_action_fcurves,
    run_pose_torture_tests,
    test_canonical_actions,
)
from .profile import (
    HAND_BONES,
    SIMPLE_HANDS_PROFILE,
    derive_simplified_contract,
    identify_finger_descendants,
    simplified_fingerprint,
    validate_simplified_contract,
)
from .production import (
    export_rigged_glb,
    finalize_production_rig,
    production_armature,
    refresh_rigging_manifest,
    validate_clean_reimport,
)
from .validation import validate_fitted_rig
from .weights import (
    audit_production_weights,
    bind_production_character,
    clean_weighting_temporary_data,
    load_weight_report,
    validate_production_weights,
)

__all__ = (
    "EDITABLE_LANDMARKS",
    "LANDMARK_NAMES",
    "HAND_POSES",
    "RESERVED_HAND_SHAPE_KEYS",
    "HAND_BONES",
    "SIMPLE_HANDS_PROFILE",
    "analyze_canonical_rig",
    "analyze_target",
    "audit_production_weights",
    "apply_saved_corrections",
    "apply_hand_pose",
    "canonical_fingerprint",
    "bind_production_character",
    "clean_rig_preview",
    "clean_owned_production_actions",
    "clean_weighting_temporary_data",
    "confidence_summary",
    "create_landmark_preview",
    "create_production_actions",
    "derive_simplified_contract",
    "encode_analysis",
    "estimate_landmarks",
    "export_rigged_glb",
    "fit_skeleton_preview",
    "finalize_production_rig",
    "hand_metrics",
    "identify_finger_descendants",
    "iter_action_fcurves",
    "landmark_objects",
    "load_weight_report",
    "reset_corrections",
    "pose_transforms_finite",
    "production_armature",
    "refresh_rigging_manifest",
    "save_corrections",
    "simplified_fingerprint",
    "run_animation_forge_acceptance",
    "run_pose_torture_tests",
    "test_canonical_actions",
    "topology_snapshot",
    "validate_fitted_rig",
    "validate_simplified_contract",
    "validate_clean_reimport",
    "validate_production_weights",
    "write_contract_report",
)
