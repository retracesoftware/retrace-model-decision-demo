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
    replay_success_times,
    verify_dap,
    verify_docker,
)


def artifact_names(outcome: str) -> tuple[str, str, str]:
    if outcome not in {"failure", "success"}:
        raise ValueError(f"unsupported reviewed outcome: {outcome}")
    return (
        f"selected-{outcome}.retrace",
        f"selected-{outcome}.expected.json",
        f"selected-{outcome}.proof.json",
    )


def copy_reviewed_invocation(
    outcome: str,
    *,
    architecture: str,
) -> tuple[Path, Path, Path]:
    recording_name, expected_name, proof_name = artifact_names(outcome)
    example = reviewed_artifact_directory(ROOT, architecture)
    source_recording = example / recording_name
    source_expected = example / expected_name
    source_proof = example / proof_name
    if not all(
        path.is_file() for path in (source_recording, source_expected, source_proof)
    ):
        raise RuntimeError(
            f"the reviewed Linux {architecture} {outcome} artifact or its proof "
            "manifest is missing; run the full proof and promote a genuine "
            f"{outcome} recording before using the bundled replay pair"
        )
    verify_recording_proof(
        source_recording,
        source_proof,
        expected_platform=f"linux/{architecture}",
    )
    destination = GENERATED / "recordings"
    destination.mkdir(parents=True, exist_ok=True)
    recording = destination / recording_name
    expected = destination / expected_name
    proof = destination / proof_name
    shutil.copy2(source_recording, recording)
    shutil.copy2(source_expected, expected)
    shutil.copy2(source_proof, proof)
    recording.chmod(recording.stat().st_mode | 0o111)
    verify_recording_proof(
        recording,
        proof,
        expected_platform=f"linux/{architecture}",
    )
    return recording, expected, proof


def verify_pair(
    failure_expected: dict,
    success_expected: dict,
    failure_proof: dict,
    success_proof: dict,
) -> None:
    if failure_expected["runtime_input"] != success_expected["runtime_input"]:
        raise AssertionError("reviewed pair does not share the same runtime input")
    if (
        failure_proof["model"]["request_sha256"]
        != success_proof["model"]["request_sha256"]
    ):
        raise AssertionError("reviewed pair does not share the same model request")
    if (
        failure_proof["model"]["response_sha256"]
        == success_proof["model"]["response_sha256"]
    ):
        raise AssertionError("reviewed pair unexpectedly shares one model response")
    if (
        failure_expected["decision"]["decision"]
        == success_expected["decision"]["decision"]
    ):
        raise AssertionError("reviewed pair did not diverge at model routing")
    if failure_expected.get("failure") is None:
        raise AssertionError("reviewed failure has no exception")
    if success_expected.get("failure") is not None:
        raise AssertionError("reviewed success unexpectedly has an exception")
    if success_expected["worker_exit_code"] != 0:
        raise AssertionError("reviewed success did not exit cleanly")
    if (
        failure_proof["application"]["request_sha256"]
        != success_proof["application"]["request_sha256"]
    ):
        raise AssertionError("reviewed pair does not share the same worker request")
    for section in ("source", "runtime"):
        if failure_proof[section] != success_proof[section]:
            raise AssertionError(
                f"reviewed pair was not captured from one {section}: "
                f"{failure_proof[section]} != {success_proof[section]}"
            )
    if failure_proof["model"]["digest"] != success_proof["model"]["digest"]:
        raise AssertionError("reviewed pair used different model builds")


def main() -> None:
    verify_docker()
    reset_generated()
    architecture = docker_architecture()
    failure_recording, failure_expected_path, failure_proof_path = (
        copy_reviewed_invocation("failure", architecture=architecture)
    )
    success_recording, success_expected_path, success_proof_path = (
        copy_reviewed_invocation("success", architecture=architecture)
    )
    report = (
        reviewed_artifact_directory(ROOT, architecture)
        / "DEMO_RESULTS.paired.example.md"
    )
    if report.is_file():
        shutil.copy2(report, GENERATED / "DEMO_RESULTS.md")

    failure_expected = json.loads(failure_expected_path.read_text())
    success_expected = json.loads(success_expected_path.read_text())
    failure_proof = verify_recording_proof(
        failure_recording,
        failure_proof_path,
        expected_platform=f"linux/{architecture}",
    )
    success_proof = verify_recording_proof(
        success_recording,
        success_proof_path,
        expected_platform=f"linux/{architecture}",
    )
    verify_pair(failure_expected, success_expected, failure_proof, success_proof)

    print("replay_example=reviewed-genuine-success-and-failure")
    print(f"docker_architecture={architecture}")
    print(f"model_request_sha256={failure_proof['model']['request_sha256']}")
    print(
        "historical_success="
        f"score:{success_expected['decision']['review_score']} "
        f"route:{success_expected['decision']['decision']} "
        f"recording:{success_recording}"
    )
    print(
        "historical_failure="
        f"score:{failure_expected['decision']['review_score']} "
        f"route:{failure_expected['decision']['decision']} "
        f"exception:{failure_expected['failure']['exception_type']} "
        f"recording:{failure_recording}"
    )

    replay_success_times(success_recording, success_expected, count=3)
    replay_failure_times(failure_recording, failure_expected, count=3)
    print(verify_dap(success_recording, success_expected_path))
    print(verify_dap(failure_recording, failure_expected_path))
    print(generate_workspace(success_recording))
    print(generate_workspace(failure_recording))
    print(
        "success_proof=pass "
        f"sha256={success_proof['artifact']['sha256']} "
        f"source_git_sha={success_proof['source']['git_sha']} "
        f"trace_id={success_proof['telemetry']['trace_id']} "
        f"span_id={success_proof['telemetry']['span_id']}"
    )
    print(
        "failure_proof=pass "
        f"sha256={failure_proof['artifact']['sha256']} "
        f"source_git_sha={failure_proof['source']['git_sha']} "
        f"trace_id={failure_proof['telemetry']['trace_id']} "
        f"span_id={failure_proof['telemetry']['span_id']}"
    )
    print("replay_pair=ready")
    print("next=make show-success")
    print("then=make show-failure")
    print("debug=Open either generated recording workspace in the Dev Container")


if __name__ == "__main__":
    main()
