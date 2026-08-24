from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from scripts.demo_state import GENERATED, ROOT
from scripts.proof_manifest import verify_recording_proof
from scripts.platforms import docker_architecture, reviewed_artifact_directory
from scripts.verify_dap import marker_line, route_line, verify, verify_success


def artifact_paths(outcome: str) -> tuple[Path, Path, Path]:
    if outcome not in {"failure", "success"}:
        raise ValueError(f"unsupported VS Code recording outcome: {outcome}")
    directory = GENERATED / "recordings"
    return (
        directory / f"selected-{outcome}.retrace",
        directory / f"selected-{outcome}.expected.json",
        directory / f"selected-{outcome}.proof.json",
    )


def prepare(outcome: str = "failure") -> Path | None:
    active, expected_path, active_proof = artifact_paths(outcome)
    architecture = docker_architecture()
    fallback_directory = reviewed_artifact_directory(ROOT, architecture)
    fallback = fallback_directory / f"selected-{outcome}.retrace"
    fallback_expected = fallback_directory / f"selected-{outcome}.expected.json"
    fallback_proof = fallback_directory / f"selected-{outcome}.proof.json"
    active_matches_architecture = False
    if active.is_file() and expected_path.is_file() and active_proof.is_file():
        try:
            verify_recording_proof(
                active,
                active_proof,
                expected_platform=f"linux/{architecture}",
            )
        except AssertionError as error:
            print(f"Replacing incompatible selected recording: {error}")
        else:
            active_matches_architecture = True
    if not active_matches_architecture and fallback.is_file():
        active.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fallback, active)
        shutil.copy2(fallback_expected, expected_path)
        shutil.copy2(fallback_proof, active_proof)
    if not active.is_file():
        print(
            f"No selected {outcome} recording yet. Run `make run` on the host, "
            "then reopen the folder in the Dev Container."
        )
        return None
    if not expected_path.is_file():
        raise AssertionError(
            f"selected recording expectation is missing: {expected_path}"
        )
    if not active_proof.is_file():
        raise AssertionError(f"selected recording proof is missing: {active_proof}")
    verify_recording_proof(
        active,
        active_proof,
        expected_platform=f"linux/{architecture}",
    )

    active.chmod(active.stat().st_mode | 0o111)
    shutil.rmtree(active.with_suffix(".d"), ignore_errors=True)
    active.with_suffix(".code-workspace").unlink(missing_ok=True)
    subprocess.run([str(active), "--extract"], cwd=ROOT, check=True)
    subprocess.run(
        ["retrace-dap", "--recording", str(active), "--workspace"],
        cwd=ROOT,
        check=True,
    )
    expected = json.loads(expected_path.read_text())
    transcript = GENERATED / "transcripts" / f"vscode-{outcome}-preflight-dap.json"
    if outcome == "failure":
        verify(active, expected, transcript)
        breakpoint_line = marker_line()
    else:
        verify_success(active, expected, transcript)
        breakpoint_line = route_line()
    print(f"active_recording={active}")
    print(f"workspace={active.with_suffix('.code-workspace')}")
    print(f"breakpoint={ROOT / 'worker/decision_agent.py'}:{breakpoint_line}")
    return active


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recording",
        choices=("failure", "success"),
        default="failure",
    )
    args = parser.parse_args()
    prepare(args.recording)
