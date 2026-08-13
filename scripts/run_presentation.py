from __future__ import annotations

import json
from pathlib import Path
import shutil

from scripts.demo_state import GENERATED, ROOT, reset_generated
from scripts.run_demo import (
    generate_workspace,
    replay_failure_times,
    verify_dap,
    verify_docker,
)


EXAMPLE = ROOT / "example-artifacts"
RECORDING_NAME = "selected-failure.retrace"
EXPECTED_NAME = "selected-failure.expected.json"


def copy_reviewed_failure() -> tuple[Path, Path]:
    source_recording = EXAMPLE / RECORDING_NAME
    source_expected = EXAMPLE / EXPECTED_NAME
    if not source_recording.is_file() or not source_expected.is_file():
        raise RuntimeError(
            "the reviewed failure artifact is missing; run the full proof and "
            "review a genuine failed recording before using presentation mode"
        )
    destination = GENERATED / "recordings"
    destination.mkdir(parents=True, exist_ok=True)
    recording = destination / RECORDING_NAME
    expected = destination / EXPECTED_NAME
    shutil.copy2(source_recording, recording)
    shutil.copy2(source_expected, expected)
    report = EXAMPLE / "DEMO_RESULTS.failure.example.md"
    if report.is_file():
        shutil.copy2(report, GENERATED / "DEMO_RESULTS.md")
    recording.chmod(recording.stat().st_mode | 0o111)
    return recording, expected


def main() -> None:
    verify_docker()
    reset_generated()
    recording, expected_path = copy_reviewed_failure()
    expected = json.loads(expected_path.read_text())

    print("presentation=reviewed-genuine-failed-invocation")
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
    print("presentation=ready")
    print("next=code .")
    print("then=Dev Containers: Reopen in Container")


if __name__ == "__main__":
    main()
