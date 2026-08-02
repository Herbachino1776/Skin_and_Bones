"""Pure regression tests for rigged-GLB seam weight repair."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "addon"
    / "skin_and_bones_forge"
    / "rigging"
    / "glb_skin.py"
)
SPEC = importlib.util.spec_from_file_location("sbf_glb_skin", MODULE_PATH)
GLB_SKIN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GLB_SKIN
SPEC.loader.exec_module(GLB_SKIN)


def _aligned(payload, fill=b"\x00"):
    return payload + fill * ((-len(payload)) % 4)


def _write_fixture(path):
    positions = struct.pack(
        "<12f",
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
    )
    joints = struct.pack(
        "<16B",
        0,
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    weights = struct.pack(
        "<16f",
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.5,
        0.5,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
    )
    binary = positions + joints + weights
    document = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [2]}],
        "nodes": [
            {"name": "body"},
            {"name": "leg"},
            {"name": "character", "mesh": 0, "skin": 0},
        ],
        "skins": [{"joints": [0, 1]}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "JOINTS_0": 1,
                            "WEIGHTS_0": 2,
                        }
                    }
                ]
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {
                "buffer": 0,
                "byteOffset": len(positions),
                "byteLength": len(joints),
            },
            {
                "buffer": 0,
                "byteOffset": len(positions) + len(joints),
                "byteLength": len(weights),
            },
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5121, "count": 4, "type": "VEC4"},
            {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC4"},
        ],
    }
    json_chunk = _aligned(
        json.dumps(document, separators=(",", ":")).encode("utf-8"), b" "
    )
    binary_chunk = _aligned(binary)
    total = 12 + 8 + len(json_chunk) + 8 + len(binary_chunk)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(json_chunk), b"JSON")
        + json_chunk
        + struct.pack("<I4s", len(binary_chunk), b"BIN\x00")
        + binary_chunk
    )


class GlbSkinTests(unittest.TestCase):
    def test_repair_rewrites_every_split_copy_from_authoritative_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.glb"
            _write_fixture(path)
            before = GLB_SKIN.audit_glb_skin_weights(path)
            self.assertEqual(before["mismatched_coincident_weight_groups"], 2)

            report = GLB_SKIN.repair_glb_skin_weights(
                path,
                {
                    (0.0, 0.0, 0.0): {"body": 0.75, "leg": 0.25},
                    (1.0, 0.0, 0.0): {"leg": 1.0},
                },
            )

            self.assertEqual(report["rewritten_vertices"], 4)
            self.assertEqual(
                report["before"]["mismatched_coincident_weight_groups"], 2
            )
            self.assertTrue(report["after"]["coincident_seam_weights_match"])
            document, data, start, length = GLB_SKIN._load_glb(path)
            primitive = document["meshes"][0]["primitives"][0]["attributes"]
            joints = GLB_SKIN._read_accessor(
                document, data, start, length, primitive["JOINTS_0"]
            )
            weights = GLB_SKIN._read_accessor(
                document, data, start, length, primitive["WEIGHTS_0"]
            )
            self.assertEqual(joints[0], joints[1])
            self.assertEqual(weights[0], weights[1])
            self.assertEqual(joints[2], joints[3])
            self.assertEqual(weights[2], weights[3])
            self.assertEqual(joints[0][:2], (0, 1))
            self.assertAlmostEqual(weights[0][0], 0.75)
            self.assertAlmostEqual(weights[0][1], 0.25)

    def test_unmatched_export_position_fails_without_overwriting_glb(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.glb"
            _write_fixture(path)
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "cannot be mapped"):
                GLB_SKIN.repair_glb_skin_weights(
                    path, {(0.0, 0.0, 0.0): {"body": 1.0}}
                )
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
