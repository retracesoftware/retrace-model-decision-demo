from __future__ import annotations

import json
from pathlib import Path
import shutil

from scripts.demo_state import GENERATED, ROOT, reset_generated
from scripts.proof_manifest import verify_recording_proof
from scripts.platforms import docker_architecture, reviewed_artifact_directory
from scripts.run_demo import (
    generate_workspace,
    replay_failure_times,
    verify_dap,
    verify_docker,
)


RECORDING_NAME = "selected-failure.retrace"
EXPECTED_NAME = "selected-failure.expected.json"
PROOF_NAME = "selected-failure.proof.json"


def copy_reviewed_failure() -> tuple[Path, Path, Path]:
    architecture = docker_architecture()
    example = reviewed_artifact_directory(ROOT, architecture)
    source_recording = example / RECORDING_NAME
    source_expected = example / EXPECTED_NAME
    source_proof = example / PROOF_NAME
    if not all(
        path.is_file() for path in (source_recording, source_expected, source_proof)
    ):
        raise RuntimeError(
            f"the reviewed Linux {architecture} failure artifact or its proof "
            "manifest is missing; "
            "run the full proof and promote a genuine failed recording before "
            "using the bundled replay example"
        )
    verify_recording_proof(
        source_recording,
        source_proof,
        expected_platform=f"linux/{architecture}",
    )
    destination = GENERATED / "recordings"
    destination.mkdir(parents=True, exist_ok=True)
    recording = destination / RECORDING_NAME
    expected = destination / EXPECTED_NAME
    proof = destination / PROOF_NAME
    shutil.copy2(source_recording, recording)
    shutil.copy2(source_expected, expected)
    shutil.copy2(source_proof, proof)
    report = example / "DEMO_RESULTS.failure.example.md"
    if report.is_file():
        shutil.copy2(report, GENERATED / "DEMO_RESULTS.md")
    recording.chmod(recording.stat().st_mode | 0o111)
    verify_recording_proof(
        recording,
        proof,
        expected_platform=f"linux/{architecture}",
    )
    return recording, expected, proof


def main() -> None:
    verify_docker()
    reset_generated()
    recording, expected_path, proof_path = copy_reviewed_failure()
    expected = json.loads(expected_path.read_text())
    architecture = docker_architecture()
    proof = verify_recording_proof(
        recording,
        proof_path,
        expected_platform=f"linux/{architecture}",
    )

    print("replay_example=reviewed-genuine-failed-invocation")
    print(f"docker_architecture={architecture}")
    print(f"recording={recording}")
    print(
        "historical_model="
        f"score:{expected['decision']['review_score']} "
        f"route:{expected['decision']['decision']}"
    )
    print(
        "historical_failure="
        f"{expected['failure']['exception_type']}: "
        f"{expected['failure']['exception_message']}"
    )
    replay_failure_times(recording, expected, count=3)
    print(verify_dap(recording, expected_path))
    print(generate_workspace(recording))
    print(
        "proof=pass "
        f"sha256={proof['artifact']['sha256']} "
        f"source_git_sha={proof['source']['git_sha']} "
        f"trace_id={proof['telemetry']['trace_id']} "
        f"span_id={proof['telemetry']['span_id']} "
        f"foundry_call_id={proof['foundry']['call_id']} "
        f"session_id={proof['foundry']['session_id']}"
    )
    print("replay_example=ready")
    print("next=code .")
    print("then=Dev Containers: Reopen in Container")


if __name__ == "__main__":
    main()
