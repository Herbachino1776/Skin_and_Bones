"""Deterministic discovery of cardinal projection images in a character folder."""

from __future__ import annotations

import re
from pathlib import Path


IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".tga", ".exr", ".webp"}
)
CARDINAL_VIEW_KEYS = ("front", "back", "left", "right")


def find_cardinal_view_images(directory):
    """Return one image per cardinal filename key, or raise on an unsafe match."""

    folder = Path(directory).resolve()
    if not folder.is_dir():
        raise ValueError(f"Perspective folder does not exist: {folder}")

    matches = {name: [] for name in CARDINAL_VIEW_KEYS}
    for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.casefold() not in IMAGE_EXTENSIONS:
            continue
        tokens = set(filter(None, re.split(r"[^a-z0-9]+", path.stem.casefold())))
        view_keys = [name for name in CARDINAL_VIEW_KEYS if name in tokens]
        if len(view_keys) > 1:
            raise ValueError(
                f"Ambiguous perspective filename '{path.name}' contains multiple "
                f"view keys: {', '.join(view_keys)}"
            )
        if view_keys:
            matches[view_keys[0]].append(path)

    missing = [name for name, paths in matches.items() if not paths]
    duplicates = {
        name: paths for name, paths in matches.items() if len(paths) > 1
    }
    problems = []
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    if duplicates:
        detail = "; ".join(
            f"{name} ({', '.join(path.name for path in paths)})"
            for name, paths in duplicates.items()
        )
        problems.append(f"multiple matches: {detail}")
    if problems:
        raise ValueError(
            "Perspective folder must contain exactly one image named with each "
            f"view key (front, back, left, right); {'; '.join(problems)}"
        )

    return {name: paths[0] for name, paths in matches.items()}
