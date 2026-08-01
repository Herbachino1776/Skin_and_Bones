"""Static repository contract checks that do not require Blender."""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "addon" / "skin_and_bones_forge"
EXPECTED_VERSION = (1, 2, 1)
EXPECTED_BLENDER = (5, 1, 2)
REQUIRED_FILES = (
    PACKAGE / "__init__.py",
    PACKAGE / "constants.py",
    PACKAGE / "properties.py",
    PACKAGE / "intake" / "analysis.py",
    PACKAGE / "intake" / "weld.py",
    PACKAGE / "intake" / "core.py",
    PACKAGE / "operators" / "intake.py",
    PACKAGE / "baking" / "core.py",
    PACKAGE / "baking" / "texture_repair.py",
    PACKAGE / "baking" / "repair_service.py",
    PACKAGE / "export" / "core.py",
    PACKAGE / "operators" / "workflow.py",
    PACKAGE / "operators" / "texture_repair.py",
    PACKAGE / "panels" / "main_panel.py",
    PACKAGE / "projection" / "core.py",
    PACKAGE / "projection" / "material.py",
    PACKAGE / "projection" / "source_doctor.py",
    PACKAGE / "projection" / "body_alignment.py",
    PACKAGE / "projection" / "source_processing.py",
    PACKAGE / "rigging" / "contract.py",
    PACKAGE / "rigging" / "analysis.py",
    PACKAGE / "rigging" / "landmarks.py",
    PACKAGE / "rigging" / "fitting.py",
    PACKAGE / "rigging" / "validation.py",
    PACKAGE / "rigging" / "profile.py",
    PACKAGE / "rigging" / "hands.py",
    PACKAGE / "rigging" / "weights.py",
    PACKAGE / "rigging" / "poses.py",
    PACKAGE / "rigging" / "production.py",
    PACKAGE / "rigging" / "compatibility.py",
    PACKAGE / "rigging" / "deformation.py",
    PACKAGE / "rigging" / "acceptance_runner.py",
    PACKAGE / "rigging" / "reimport_runner.py",
    PACKAGE / "operators" / "rigging.py",
    PACKAGE / "operators" / "source_doctor.py",
    PACKAGE / "validation" / "core.py",
)


def _literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path}: missing literal assignment for {name}")


def _compile_sources():
    for path in sorted(PACKAGE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")


def _validate_operator_ids():
    identifiers = []
    for operator_path in sorted((PACKAGE / "operators").glob("*.py")):
        tree = ast.parse(
            operator_path.read_text(encoding="utf-8"),
            filename=str(operator_path),
        )
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if any(
                    isinstance(target, ast.Name) and target.id == "bl_idname"
                    for target in statement.targets
                ):
                    identifier = ast.literal_eval(statement.value)
                    assert identifier.startswith("sbf."), (
                        f"Unexpected operator namespace: {identifier}"
                    )
                    identifiers.append(identifier)
    assert identifiers, "No SBF operators were discovered."
    assert len(identifiers) == len(set(identifiers)), "Duplicate operator ID found."


def main():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.is_file()]
    assert not missing, f"Missing required add-on files: {missing}"

    _compile_sources()
    _validate_operator_ids()

    bl_info = _literal_assignment(PACKAGE / "__init__.py", "bl_info")
    constants_version = _literal_assignment(PACKAGE / "constants.py", "ADDON_VERSION")
    assert tuple(bl_info["version"]) == EXPECTED_VERSION
    assert tuple(constants_version) == EXPECTED_VERSION
    assert tuple(bl_info["blender"]) == EXPECTED_BLENDER

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = tuple(
        int(part) for part in project["project"]["version"].split(".")
    )
    assert project_version == EXPECTED_VERSION

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"Skin_and_Bones_Forge_v{'.'.join(map(str, EXPECTED_VERSION))}.zip" in readme
    assert "3D Viewport" in readme

    print(
        "Validated Skin & Bones Forge "
        f"{'.'.join(map(str, EXPECTED_VERSION))} for Blender "
        f"{'.'.join(map(str, EXPECTED_BLENDER))}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
