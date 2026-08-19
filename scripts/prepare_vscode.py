from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from scripts.demo_state import GENERATED, ROOT
from scripts.proof_manifest import verify_recording_proof
from scripts.platforms import docker_architecture, reviewed_artifact_directory
from scripts.verify_dap import marker_line, verify


ACTIVE = GENERATED / "recordings" / "selected-failure.retrace"
EXPECTED = GENERATED / "recordings" / "selected-failure.expected.json"
ACTIVE_PROOF = GENERATED / "recordings" / "selected-failure.proof.json"


def prepare() -> Path | None:
    architecture = docker_architecture()
    fallback_directory = reviewed_artifact_directory(ROOT, architecture)
    fallback = fallback_directory / "selected-failure.retrace"
    fallback_expected = fallback_directory / "selected-failure.expected.json"
    fallback_proof = fallback_directory / "selected-failure.proof.json"
    if not ACTIVE.is_file() and fallback.is_file():
        ACTIVE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fallback, ACTIVE)
        shutil.copy2(fallback_expected, EXPECTED)
        shutil.copy2(fallback_proof, ACTIVE_PROOF)
    if not ACTIVE.is_file():
        print(
            "No selected failure recording yet. Run `make demo` on the host, "
            "then reopen the folder in the Dev Container."
        )
        return None
    if not EXPECTED.is_file():
        raise AssertionError(f"selected recording expectation is missing: {EXPECTED}")
    if not ACTIVE_PROOF.is_file():
        raise AssertionError(f"selected recording proof is missing: {ACTIVE_PROOF}")
    verify_recording_proof(
        ACTIVE,
        ACTIVE_PROOF,
        expected_platform=f"linux/{architecture}",
    )

    ACTIVE.chmod(ACTIVE.stat().st_mode | 0o111)
    shutil.rmtree(ACTIVE.with_suffix(".d"), ignore_errors=True)
    ACTIVE.with_suffix(".code-workspace").unlink(missing_ok=True)
    subprocess.run([str(ACTIVE), "--extract"], cwd=ROOT, check=True)
    subprocess.run(
        ["retrace-dap", "--recording", str(ACTIVE), "--workspace"],
        cwd=ROOT,
        check=True,
    )
    verify(
        ACTIVE,
        json.loads(EXPECTED.read_text()),
        GENERATED / "transcripts" / "vscode-preflight-dap.json",
    )
    print(f"active_recording={ACTIVE}")
    print(f"workspace={ACTIVE.with_suffix('.code-workspace')}")
    print(f"breakpoint={ROOT / 'worker/decision_agent.py'}:{marker_line()}")
    return ACTIVE


if __name__ == "__main__":
    prepare()
