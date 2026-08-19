from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from agent.manifest import sha256_file
from scripts.demo_state import ROOT


DESTINATION = ROOT / "example-artifacts"


def source_file(source: Path, name: str) -> Path:
    direct = source / name
    nested = source / "recordings" / name
    for candidate in (direct, nested):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"reviewed artifact input is missing {name}: {source}")


def promote(source: Path) -> None:
    recording = source_file(source, "selected-failure.retrace")
    expected_path = source_file(source, "selected-failure.expected.json")
    proof_path = source_file(source, "selected-failure.proof.json")
    report_path = source / "DEMO_RESULTS.md"
    if not report_path.is_file():
        raise FileNotFoundError(f"reviewed proof report is missing: {report_path}")

    expected = json.loads(expected_path.read_text())
    proof = json.loads(proof_path.read_text())
    if proof.get("artifact", {}).get("sha256") != sha256_file(recording):
        raise AssertionError("proof manifest does not match the selected recording")
    if expected.get("failure", {}).get("exception_type") != "AttributeError":
        raise AssertionError(
            f"reviewed artifact is not the expected failure: {expected}"
        )
    if proof.get("telemetry", {}).get("trace_id") is None:
        raise AssertionError("proof manifest omitted the OTel trace ID")
    if proof.get("telemetry", {}).get("span_id") is None:
        raise AssertionError("proof manifest omitted the OTel span ID")

    DESTINATION.mkdir(parents=True, exist_ok=True)
    shutil.copy2(recording, DESTINATION / recording.name)
    shutil.copy2(expected_path, DESTINATION / expected_path.name)
    shutil.copy2(proof_path, DESTINATION / proof_path.name)
    shutil.copy2(report_path, DESTINATION / "DEMO_RESULTS.failure.example.md")
    print(f"promoted_recording={DESTINATION / recording.name}")
    print(f"recording_sha256={sha256_file(recording)}")
    print(f"source_git_sha={proof['source']['git_sha']}")
    print(f"trace_id={proof['telemetry']['trace_id']}")
    print(f"span_id={proof['telemetry']['span_id']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    promote(args.source.resolve())


if __name__ == "__main__":
    main()
