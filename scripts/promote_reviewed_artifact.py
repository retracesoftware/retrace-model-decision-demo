from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from agent.manifest import sha256_file
from scripts.demo_state import ROOT
from scripts.proof_manifest import verify_recording_proof
from scripts.platforms import docker_architecture, reviewed_artifact_directory


def source_file(source: Path, name: str) -> Path:
    direct = source / name
    nested = source / "recordings" / name
    for candidate in (direct, nested):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"reviewed artifact input is missing {name}: {source}")


def promote(source: Path, architecture: str | None = None) -> None:
    artifacts = {
        outcome: {
            "recording": source_file(source, f"selected-{outcome}.retrace"),
            "expected": source_file(source, f"selected-{outcome}.expected.json"),
            "proof": source_file(source, f"selected-{outcome}.proof.json"),
        }
        for outcome in ("failure", "success")
    }
    report_path = source / "DEMO_RESULTS.md"
    if not report_path.is_file():
        raise FileNotFoundError(f"reviewed proof report is missing: {report_path}")

    selected_architecture = architecture or docker_architecture()
    expected = {
        outcome: json.loads(paths["expected"].read_text())
        for outcome, paths in artifacts.items()
    }
    proofs = {
        outcome: verify_recording_proof(
            paths["recording"],
            paths["proof"],
            expected_platform=f"linux/{selected_architecture}",
        )
        for outcome, paths in artifacts.items()
    }
    if expected["failure"].get("failure", {}).get("exception_type") != "AttributeError":
        raise AssertionError(
            f"reviewed artifact is not the expected failure: {expected['failure']}"
        )
    if expected["success"].get("failure") is not None:
        raise AssertionError(
            f"reviewed success contains a failure: {expected['success']}"
        )
    if expected["success"].get("worker_exit_code") != 0:
        raise AssertionError(
            f"reviewed success did not exit cleanly: {expected['success']}"
        )
    if expected["failure"]["runtime_input"] != expected["success"]["runtime_input"]:
        raise AssertionError("reviewed success and failure runtime inputs differ")
    if (
        proofs["failure"]["model"]["request_sha256"]
        != proofs["success"]["model"]["request_sha256"]
    ):
        raise AssertionError("reviewed success and failure model requests differ")
    if (
        proofs["failure"]["model"]["response_sha256"]
        == proofs["success"]["model"]["response_sha256"]
    ):
        raise AssertionError("reviewed success and failure model responses match")
    if (
        proofs["failure"]["application"]["request_sha256"]
        != proofs["success"]["application"]["request_sha256"]
    ):
        raise AssertionError("reviewed success and failure worker requests differ")
    for section in ("source", "runtime"):
        if proofs["failure"][section] != proofs["success"][section]:
            raise AssertionError(
                f"reviewed success and failure {section} differ: "
                f"{proofs['failure'][section]} != {proofs['success'][section]}"
            )
    if proofs["failure"]["model"]["digest"] != proofs["success"]["model"]["digest"]:
        raise AssertionError("reviewed success and failure model builds differ")

    destination = reviewed_artifact_directory(
        ROOT,
        selected_architecture,
    )
    destination.mkdir(parents=True, exist_ok=True)
    for outcome, paths in artifacts.items():
        for path in paths.values():
            shutil.copy2(path, destination / path.name)
        proof = proofs[outcome]
        recording = paths["recording"]
        print(f"promoted_{outcome}_recording={destination / recording.name}")
        print(f"{outcome}_recording_sha256={sha256_file(recording)}")
        print(f"{outcome}_source_git_sha={proof['source']['git_sha']}")
        print(f"{outcome}_trace_id={proof['telemetry']['trace_id']}")
        print(f"{outcome}_span_id={proof['telemetry']['span_id']}")
    shutil.copy2(report_path, destination / "DEMO_RESULTS.paired.example.md")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--architecture", choices=("amd64", "arm64"))
    args = parser.parse_args()
    promote(args.source.resolve(), args.architecture)


if __name__ == "__main__":
    main()
