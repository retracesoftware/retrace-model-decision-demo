from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.demo_state import GENERATED
from scripts.run_demo import (
    DECISION_FIELDS,
    container_path,
    in_offline_container,
    parse_worker_events,
    verify_docker,
)


RECORDING = GENERATED / "recordings" / "selected-failure.retrace"
EXPECTED = GENERATED / "recordings" / "selected-failure.expected.json"
TRACEBACK_LOG = GENERATED / "replay" / "presentation-traceback.log"


def root_pidfile(recording: Path) -> Path:
    extracted = recording.with_suffix(".d")
    index_path = extracted / "index.json"
    if not index_path.is_file():
        raise RuntimeError(
            "the selected recording has not been extracted; run "
            "`make replay-example` before `make show-failure`"
        )
    index = json.loads(index_path.read_text())
    pidfile = extracted / f"{int(index['root']['pid'])}.bin"
    if not pidfile.is_file():
        raise RuntimeError(
            f"the selected recording root process is missing: {pidfile}; "
            "run `make replay-example` again"
        )
    return pidfile


def validate_historical_failure(
    output: str,
    returncode: int,
    expected: dict[str, Any],
) -> None:
    decision_event, failure_event = parse_worker_events(output)
    actual_decision = {key: decision_event[key] for key in DECISION_FIELDS}
    actual_failure = {
        "exception_type": failure_event["exception_type"],
        "exception_message": failure_event["exception_message"],
    }
    if returncode != expected["worker_exit_code"]:
        raise AssertionError(
            "historical replay exit changed: "
            f"{returncode} != {expected['worker_exit_code']}"
        )
    if actual_decision != expected["decision"]:
        raise AssertionError(
            "historical replay decision changed:\n"
            f"expected={expected['decision']}\nactual={actual_decision}"
        )
    if actual_failure != expected["failure"]:
        raise AssertionError(
            "historical replay failure changed:\n"
            f"expected={expected['failure']}\nactual={actual_failure}"
        )
    required_traceback = (
        'File "/app/worker/decision_agent.py", line 116, in run_decision_agent',
        "normalized = serial_number.strip()",
        "AttributeError: 'NoneType' object has no attribute 'strip'",
    )
    missing = [line for line in required_traceback if line not in output]
    if missing:
        raise AssertionError(
            "historical replay omitted the required traceback source location: "
            + ", ".join(repr(line) for line in missing)
        )


def main() -> None:
    verify_docker()
    if not RECORDING.is_file() or not EXPECTED.is_file():
        raise RuntimeError(
            "no active selected failure exists; run `make replay-example` first"
        )
    expected = json.loads(EXPECTED.read_text())
    pidfile = root_pidfile(RECORDING)

    print("\n" + "=" * 78)
    print("Historical incident: deterministic offline replay")
    print("=" * 78)
    print("network=none model_gateway=unavailable expected_application_exit=1")
    print(f"recording={RECORDING}")
    print(f"root_process={pidfile}")
    replay = in_offline_container(
        ["replay", str(container_path(pidfile))],
        check=False,
    )
    TRACEBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    TRACEBACK_LOG.write_text(replay.stdout)
    print("\n--- historical application output and traceback ---")
    print(replay.stdout.rstrip())
    print("--- end historical application output ---\n")

    validate_historical_failure(replay.stdout, replay.returncode, expected)
    print(
        "historical_failure=verified "
        "exception=AttributeError "
        "source=/app/worker/decision_agent.py "
        "line=116 "
        "network=none"
    )
    print(f"traceback_log={TRACEBACK_LOG}")
    print("next=Open worker/decision_agent.py at line 116 in the Dev Container")


if __name__ == "__main__":
    main()
