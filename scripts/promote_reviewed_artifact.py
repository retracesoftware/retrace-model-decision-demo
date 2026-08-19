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
    recording = source_file(source, "selected-failure.retrace")
    expected_path = source_file(source, "selected-failure.expected.json")
    proof_path = source_file(source, "selected-failure.proof.json")
    report_path = source / "DEMO_RESULTS.md"
    if not report_path.is_file():
        raise FileNotFoundError(f"reviewed proof report is missing: {report_path}")

    expected = json.loads(expected_path.read_text())
    selected_architecture = architecture or docker_architecture()
    proof = verify_recording_proof(
        recording,
        proof_path,
        expected_platform=f"linux/{selected_architecture}",
    )
    if expected.get("failure", {}).get("exception_type") != "AttributeError":
        raise AssertionError(
            f"reviewed artifact is not the expected failure: {expected}"
        )
    destination = reviewed_artifact_directory(
        ROOT,
        selected_architecture,
    )
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(recording, destination / recording.name)
    shutil.copy2(expected_path, destination / expected_path.name)
    shutil.copy2(proof_path, destination / proof_path.name)
    shutil.copy2(report_path, destination / "DEMO_RESULTS.failure.example.md")
    print(f"promoted_recording={destination / recording.name}")
    print(f"recording_sha256={sha256_file(recording)}")
    print(f"source_git_sha={proof['source']['git_sha']}")
    print(f"trace_id={proof['telemetry']['trace_id']}")
    print(f"span_id={proof['telemetry']['span_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--architecture", choices=("amd64", "arm64"))
    args = parser.parse_args()
    promote(args.source.resolve(), args.architecture)


if __name__ == "__main__":
    main()
