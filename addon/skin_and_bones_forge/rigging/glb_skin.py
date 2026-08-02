"""Deterministic skin-weight repair and audit for Blender-exported GLBs."""

from __future__ import annotations

import json
import math
from pathlib import Path
import struct


_COMPONENT_FORMATS = {
    5120: "b",
    5121: "B",
    5122: "h",
    5123: "H",
    5125: "I",
    5126: "f",
}
_COMPONENT_LIMITS = {
    5120: 127,
    5121: 255,
    5122: 32767,
    5123: 65535,
    5125: 4294967295,
}
_TYPE_WIDTHS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def position_key(values):
    """Return an exact float32 key, treating signed zero identically."""

    cleaned = tuple(0.0 if float(value) == 0.0 else float(value) for value in values)
    if len(cleaned) != 3:
        raise ValueError("GLB skin position keys require three coordinates.")
    return struct.pack("<3f", *cleaned)


def _load_glb(path):
    data = bytearray(Path(path).read_bytes())
    if len(data) < 20:
        raise ValueError("Rigged GLB is truncated.")
    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(data):
        raise ValueError("Expected a complete binary glTF 2.0 file.")
    offset = 12
    document = None
    binary_start = None
    binary_length = None
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        payload_start = offset + 8
        payload_end = payload_start + chunk_length
        if payload_end > len(data):
            raise ValueError("GLB chunk extends beyond the declared file length.")
        if chunk_type == b"JSON":
            document = json.loads(
                bytes(data[payload_start:payload_end]).decode("utf-8")
            )
        elif chunk_type == b"BIN\x00":
            binary_start = payload_start
            binary_length = chunk_length
        offset = payload_end
    if document is None or binary_start is None:
        raise ValueError("Rigged GLB must contain JSON and BIN chunks.")
    return document, data, binary_start, binary_length


def _accessor_layout(document, accessor_index, binary_start, binary_length):
    accessor = document["accessors"][int(accessor_index)]
    if "sparse" in accessor:
        raise ValueError("Sparse GLB skin accessors are not supported.")
    view = document["bufferViews"][int(accessor["bufferView"])]
    if int(view.get("buffer", 0)) != 0:
        raise ValueError("Rigged GLB skin accessors must use the binary buffer.")
    component_type = int(accessor["componentType"])
    component_format = _COMPONENT_FORMATS.get(component_type)
    width = _TYPE_WIDTHS.get(accessor["type"])
    if component_format is None or width is None:
        raise ValueError("Unsupported GLB skin accessor encoding.")
    value_struct = struct.Struct("<" + component_format * width)
    stride = int(view.get("byteStride", value_struct.size))
    if stride < value_struct.size:
        raise ValueError("GLB accessor stride is smaller than its encoded value.")
    relative_start = int(view.get("byteOffset", 0)) + int(
        accessor.get("byteOffset", 0)
    )
    count = int(accessor["count"])
    relative_end = relative_start + max(count - 1, 0) * stride + value_struct.size
    if relative_start < 0 or relative_end > binary_length:
        raise ValueError("GLB accessor extends beyond the binary chunk.")
    return {
        "accessor": accessor,
        "component_type": component_type,
        "count": count,
        "normalized": bool(accessor.get("normalized", False)),
        "start": binary_start + relative_start,
        "stride": stride,
        "struct": value_struct,
        "width": width,
    }


def _read_accessor(document, data, binary_start, binary_length, index):
    layout = _accessor_layout(document, index, binary_start, binary_length)
    values = []
    limit = _COMPONENT_LIMITS.get(layout["component_type"])
    for item in range(layout["count"]):
        offset = layout["start"] + item * layout["stride"]
        value = layout["struct"].unpack_from(data, offset)
        if layout["normalized"] and limit is not None:
            value = tuple(float(component) / limit for component in value)
        values.append(value)
    return values


def _write_accessor_value(layout, data, item, values):
    if len(values) != layout["width"]:
        raise ValueError("GLB accessor write width does not match its schema.")
    component_type = layout["component_type"]
    if component_type == 5126:
        encoded = tuple(float(value) for value in values)
    else:
        limit = _COMPONENT_LIMITS[component_type]
        if layout["normalized"]:
            encoded = tuple(
                min(limit, max(0, int(round(float(value) * limit))))
                for value in values
            )
        else:
            encoded = tuple(int(value) for value in values)
    offset = layout["start"] + int(item) * layout["stride"]
    layout["struct"].pack_into(data, offset, *encoded)


def _weight_map(joints, weights, palette):
    result = {}
    for joint, weight in zip(joints, weights):
        value = float(weight)
        if value <= 1.0e-8:
            continue
        index = int(joint)
        if index < 0 or index >= len(palette):
            raise ValueError("GLB JOINTS_0 references outside its skin palette.")
        name = palette[index]
        result[name] = result.get(name, 0.0) + value
    return result


def _weight_delta(first, second):
    return sum(
        abs(float(first.get(name, 0.0)) - float(second.get(name, 0.0)))
        for name in set(first).union(second)
    )


def _skinned_primitives(document):
    seen = set()
    for node_index, node in enumerate(document.get("nodes", [])):
        if "mesh" not in node or "skin" not in node:
            continue
        mesh_index = int(node["mesh"])
        skin_index = int(node["skin"])
        key = (mesh_index, skin_index)
        if key in seen:
            continue
        seen.add(key)
        skin = document["skins"][skin_index]
        palette = [
            document["nodes"][int(joint)].get("name", "")
            for joint in skin["joints"]
        ]
        if not all(palette) or len(set(palette)) != len(palette):
            raise ValueError("GLB skin joint names must be present and unique.")
        for primitive_index, primitive in enumerate(
            document["meshes"][mesh_index].get("primitives", [])
        ):
            attributes = primitive.get("attributes", {})
            required = {"POSITION", "JOINTS_0", "WEIGHTS_0"}
            if not required.issubset(attributes):
                raise ValueError("Rigged GLB primitive is missing skin attributes.")
            yield {
                "node": node_index,
                "mesh": mesh_index,
                "skin": skin_index,
                "primitive": primitive_index,
                "attributes": attributes,
                "palette": palette,
            }


def _audit_loaded(document, data, binary_start, binary_length, tolerance):
    grouped = {}
    primitive_count = 0
    vertex_count = 0
    for record in _skinned_primitives(document):
        primitive_count += 1
        attributes = record["attributes"]
        positions = _read_accessor(
            document, data, binary_start, binary_length, attributes["POSITION"]
        )
        joints = _read_accessor(
            document, data, binary_start, binary_length, attributes["JOINTS_0"]
        )
        weights = _read_accessor(
            document, data, binary_start, binary_length, attributes["WEIGHTS_0"]
        )
        if not (len(positions) == len(joints) == len(weights)):
            raise ValueError("GLB skin attribute counts do not match.")
        vertex_count += len(positions)
        for index, (position, joint, weight) in enumerate(
            zip(positions, joints, weights)
        ):
            key = (record["mesh"], record["skin"], position_key(position))
            grouped.setdefault(key, []).append(
                {
                    "primitive": record["primitive"],
                    "vertex": index,
                    "weights": _weight_map(joint, weight, record["palette"]),
                }
            )
    if not primitive_count or not vertex_count:
        raise ValueError("Rigged GLB contains no skinned mesh vertices.")
    duplicate_groups = 0
    mismatched = []
    for values in grouped.values():
        if len(values) < 2:
            continue
        duplicate_groups += 1
        maximum = max(
            _weight_delta(first["weights"], second["weights"])
            for offset, first in enumerate(values)
            for second in values[offset + 1 :]
        )
        if maximum > float(tolerance):
            mismatched.append((maximum, values))
    mismatched.sort(key=lambda item: item[0], reverse=True)
    return {
        "skinned_primitives": primitive_count,
        "skinned_vertices": vertex_count,
        "coincident_vertex_groups": duplicate_groups,
        "mismatched_coincident_weight_groups": len(mismatched),
        "maximum_coincident_weight_delta": round(
            mismatched[0][0] if mismatched else 0.0, 8
        ),
        "coincident_seam_weights_match": not mismatched,
        "worst_mismatches": [
            {
                "weight_delta": round(delta, 8),
                "vertices": [
                    [int(item["primitive"]), int(item["vertex"])]
                    for item in values
                ],
            }
            for delta, values in mismatched[:10]
        ],
    }


def audit_glb_skin_weights(path, *, tolerance=1.0e-5):
    """Report weight disagreement among exact coincident GLB vertices."""

    document, data, binary_start, binary_length = _load_glb(path)
    return _audit_loaded(
        document, data, binary_start, binary_length, tolerance
    )


def _canonical_weights(source, palette):
    palette_indices = {name: index for index, name in enumerate(palette)}
    values = []
    for name, raw_weight in source.items():
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight < 0.0:
            raise ValueError("Authoritative skin weights must be finite and non-negative.")
        if weight <= 1.0e-8:
            continue
        if name not in palette_indices:
            raise ValueError(f"Authoritative skin group '{name}' is absent from the GLB skin.")
        values.append((name, weight, palette_indices[name]))
    values.sort(key=lambda item: (-item[1], item[2], item[0]))
    if not values:
        raise ValueError("Every exported vertex must have an authoritative skin weight.")
    if len(values) > 4:
        raise ValueError("Authoritative skin weights exceed four influences per vertex.")
    total = sum(item[1] for item in values)
    if total <= 1.0e-8:
        raise ValueError("Authoritative skin weights have a zero sum.")
    joints = [item[2] for item in values]
    weights = [item[1] / total for item in values]
    while len(joints) < 4:
        joints.append(0)
        weights.append(0.0)
    return tuple(joints), tuple(weights)


def repair_glb_skin_weights(
    path,
    authoritative_by_position,
    *,
    tolerance=1.0e-5,
):
    """Rewrite all exported split vertices from authoritative source weights."""

    output = Path(path).resolve()
    source = {}
    for position, weights in authoritative_by_position.items():
        key = position_key(position)
        normalized = {str(name): float(value) for name, value in weights.items()}
        previous = source.get(key)
        if previous is not None and _weight_delta(previous, normalized) > tolerance:
            raise ValueError(
                "Authoritative mesh has coincident vertices with ambiguous weights."
            )
        source[key] = normalized

    document, data, binary_start, binary_length = _load_glb(output)
    before = _audit_loaded(
        document, data, binary_start, binary_length, tolerance
    )
    rewritten = 0
    unmatched = []
    for record in _skinned_primitives(document):
        attributes = record["attributes"]
        positions = _read_accessor(
            document, data, binary_start, binary_length, attributes["POSITION"]
        )
        joint_layout = _accessor_layout(
            document, attributes["JOINTS_0"], binary_start, binary_length
        )
        weight_layout = _accessor_layout(
            document, attributes["WEIGHTS_0"], binary_start, binary_length
        )
        if joint_layout["count"] != len(positions) or weight_layout["count"] != len(
            positions
        ):
            raise ValueError("GLB skin attribute counts do not match.")
        for index, position in enumerate(positions):
            weights = source.get(position_key(position))
            if weights is None:
                if len(unmatched) < 10:
                    unmatched.append([round(float(value), 8) for value in position])
                continue
            joints, normalized = _canonical_weights(weights, record["palette"])
            _write_accessor_value(joint_layout, data, index, joints)
            _write_accessor_value(weight_layout, data, index, normalized)
            rewritten += 1
    if unmatched:
        raise ValueError(
            "Rigged GLB contains vertices that cannot be mapped to the authoritative "
            f"mesh positions: {unmatched}"
        )
    after = _audit_loaded(
        document, data, binary_start, binary_length, tolerance
    )
    if rewritten != after["skinned_vertices"]:
        raise ValueError("Not every exported skin vertex received authoritative weights.")
    if not after["coincident_seam_weights_match"]:
        raise ValueError("Rigged GLB still contains mismatched coincident seam weights.")
    temporary = output.with_name(output.name + ".sbf-skin.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": "GLB_SKIN_WEIGHTS_REPAIRED",
        "authoritative_vertices": len(source),
        "rewritten_vertices": rewritten,
        "before": before,
        "after": after,
    }
