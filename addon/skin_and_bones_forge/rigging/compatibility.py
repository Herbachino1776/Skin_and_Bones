"""Launch isolated clean-scene Animation Forge acceptance."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import bpy


def run_animation_forge_acceptance(
    glb_path,
    forge_repository,
    report_path=None,
):
    glb = Path(bpy.path.abspath(str(glb_path))).resolve()
    repo = Path(bpy.path.abspath(str(forge_repository))).resolve()
    if not glb.is_file():
        raise RuntimeError(f"Rigged GLB does not exist: {glb}")
    if not (repo / "__init__.py").is_file():
        raise RuntimeError(f"Animation Forge repository is unavailable: {repo}")
    report = (
        Path(bpy.path.abspath(str(report_path))).resolve()
        if report_path
        else glb.with_suffix(glb.suffix + ".animation_forge.json")
    )
    runner = Path(__file__).with_name("acceptance_runner.py").resolve()
    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--python",
        str(runner),
        "--",
        "--glb",
        str(glb),
        "--forge-repo",
        str(repo),
        "--report",
        str(report),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    if not report.is_file():
        raise RuntimeError(
            "Animation Forge acceptance did not produce a report. "
            + completed.stderr[-1000:]
        )
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["process_return_code"] = completed.returncode
    payload["process_stdout_tail"] = completed.stdout[-2000:]
    payload["process_stderr_tail"] = completed.stderr[-2000:]
    if completed.returncode and payload["status"] != "ANIMATION_FORGE_WARNING":
        payload["status"] = "ANIMATION_FORGE_REJECTED"
    return payload, report

