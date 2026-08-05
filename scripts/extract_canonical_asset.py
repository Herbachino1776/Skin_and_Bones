"""Extract the reusable Y+ armature template from the Townsman source file.

The source is opened only as a Blender library and is never saved.  The output
contains one armature object, its armature data, and no meshes or Actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix


def _args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--addon", type=Path, required=True)
    return parser.parse_args(argv)


args = _args()
source_path = args.source.resolve()
addon_path = args.addon.resolve()
if not source_path.is_file():
    raise RuntimeError(f"Townsman source does not exist: {source_path}")
if str(addon_path) not in sys.path:
    sys.path.insert(0, str(addon_path))

from skin_and_bones_forge.constants import (  # noqa: E402
    CANONICAL_ASSET_DIRECTORY,
    CANONICAL_ASSET_FILENAME,
    CANONICAL_ASSET_OBJECT,
    CANONICAL_MANIFEST_FILENAME,
    CANONICAL_RIG_VERSION,
)
from skin_and_bones_forge.rigging.canonical import (  # noqa: E402
    CANONICAL_TEMPLATE_ROLE,
    apply_canonical_metadata,
)
from skin_and_bones_forge.rigging.contract import (  # noqa: E402
    analyze_canonical_rig,
)
from skin_and_bones_forge.rigging.profile import (  # noqa: E402
    PRODUCTION_BONE_NAMES,
)


bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(source_path), link=False) as (data_from, data_to):
    data_to.objects = list(data_from.objects)
loaded = [obj for obj in data_to.objects if obj is not None]
armatures = [
    obj
    for obj in loaded
    if obj.type == "ARMATURE"
    and obj.get("sbf_production_rig", False)
    and tuple(bone.name for bone in obj.data.bones) == PRODUCTION_BONE_NAMES
]
if len(armatures) != 1:
    raise RuntimeError(
        "Expected one 21-bone Townsman production rig, found "
        f"{len(armatures)}."
    )
source = armatures[0]
template = source.copy()
template.data = source.data.copy()
template.name = CANONICAL_ASSET_OBJECT
template.data.name = f"{CANONICAL_ASSET_OBJECT}_Data"
template.parent = None
template.matrix_world = Matrix.Identity(4)
template.animation_data_clear()
template.data.pose_position = "REST"
template.show_in_front = True
template.display_type = "WIRE"
for key in list(template.keys()):
    del template[key]
for key in list(template.data.keys()):
    del template.data[key]
for pose_bone in template.pose.bones:
    pose_bone.matrix_basis.identity()
apply_canonical_metadata(template, role=CANONICAL_TEMPLATE_ROLE)
bpy.context.scene.collection.objects.link(template)

for obj in loaded:
    if obj is template:
        continue
    data = obj.data if obj.type == "ARMATURE" else None
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.armatures.remove(data)
for action in list(bpy.data.actions):
    bpy.data.actions.remove(action, do_unlink=True)

contract = analyze_canonical_rig(bpy.context, template)
if tuple(bone["name"] for bone in contract["bones"]) != PRODUCTION_BONE_NAMES:
    raise RuntimeError("Extracted template bone order changed unexpectedly.")
if contract["animation_inventory"]["actions"]:
    raise RuntimeError("Extracted template unexpectedly retained Actions.")
if contract["reference_meshes"]:
    raise RuntimeError("Extracted template unexpectedly retained mesh data.")

assets = addon_path / "skin_and_bones_forge" / CANONICAL_ASSET_DIRECTORY
assets.mkdir(parents=True, exist_ok=True)
asset_path = assets / CANONICAL_ASSET_FILENAME
manifest_path = assets / CANONICAL_MANIFEST_FILENAME
bpy.data.libraries.write(
    str(asset_path),
    {template, template.data},
    path_remap="NONE",
    fake_user=True,
    compress=True,
)
asset_digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
manifest = {
    "schema": "skin-and-bones-canonical-asset-v1",
    "rig_version": CANONICAL_RIG_VERSION,
    "object": CANONICAL_ASSET_OBJECT,
    "asset_filename": CANONICAL_ASSET_FILENAME,
    "asset_sha256": asset_digest,
    "source_filename": source_path.name,
    "source_sha256": source_digest,
    "fingerprint": contract["fingerprint"],
    "bone_names": [bone["name"] for bone in contract["bones"]],
    "bone_count": len(contract["bones"]),
    "deform_bone_count": sum(bool(bone["deform"]) for bone in contract["bones"]),
    "forward_axis": contract["forward_axis"],
    "up_axis": contract["up_axis"],
    "root_bone": contract["root_bone"],
    "unit_scale_meters": contract["unit_scale_meters"],
    "animation_count": len(contract["animation_inventory"]["actions"]),
    "reference_mesh_count": len(contract["reference_meshes"]),
    "contract": contract,
}
manifest_path.write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print("SBF_CANONICAL_ASSET_EXTRACTED")
print(json.dumps({
    "asset": str(asset_path),
    "asset_sha256": asset_digest,
    "manifest": str(manifest_path),
    "fingerprint": contract["fingerprint"],
    "source_sha256": source_digest,
}, indent=2, sort_keys=True))
