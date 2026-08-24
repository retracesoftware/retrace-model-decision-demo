from __future__ import annotations

import json
from typing import Any

from scripts.demo_state import GENERATED
from scripts.run_demo import (
    DECISION_FIELDS,
    container_path,
    in_offline_container,
    parse_success_events,
    verify_docker,
)
from scripts.show_failure import root_pidfile


RECORDING = GENERATED / "recordings" / "selected-success.retrace"
EXPECTED = GENERATED / "recordings" / "selected-success.expected.json"
OUTPUT_LOG = GENERATED / "replay" / "presentation-success.log"


def validate_historical_success(
    output: str,
    returncode: int,
    expected: dict[str, Any],
) -> None:
    decision_event, completed_event = parse_success_events(output)
    actual_decision = {key: decision_event[key] for key in DECISION_FIELDS}
    actual_output = completed_event.get("output")
    if returncode != 0 or returncode != expected["worker_exit_code"]:
        raise AssertionError(
            "historical successful replay exit changed: "
            f"{returncode} != {expected['worker_exit_code']}"
        )
    if actual_decision != expected["decision"]:
        raise AssertionError(
            "historical successful replay decision changed:\n"
            f"expected={expected['decision']}\nactual={actual_decision}"
        )
    if actual_output != expected["output"]:
        raise AssertionError(
            "historical successful replay output changed:\n"
            f"expected={expected['output']}\nactual={actual_output}"
        )
    if "Traceback (most recent call last)" in output:
        raise AssertionError("historical successful replay emitted a traceback")


def main() -> None:
    verify_docker()
    if not RECORDING.is_file() or not EXPECTED.is_file():
        raise RuntimeError(
            "no active selected success exists; run `make replay-pair` first"
        )
    expected = json.loads(EXPECTED.read_text())
    pidfile = root_pidfile(RECORDING)

    print("\n" + "=" * 78)
    print("Historical passing execution: deterministic offline replay")
    print("=" * 78)
    print("network=none model_gateway=unavailable expected_application_exit=0")
    print(f"recording={RECORDING}")
    print(f"root_process={pidfile}")
    replay = in_offline_container(
        ["replay", str(container_path(pidfile))],
        check=False,
    )
    OUTPUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_LOG.write_text(replay.stdout)
    print("\n--- historical successful application output ---")
    print(replay.stdout.rstrip())
    print("--- end historical successful application output ---\n")

    validate_historical_success(replay.stdout, replay.returncode, expected)
    decision = expected["decision"]
    print(
        "historical_success=verified "
        f"score={decision['review_score']} "
        f"route={decision['decision']} "
        "serial_number=None network=none"
    )
    print(f"success_log={OUTPUT_LOG}")
    print("compare=Run `make show-failure` for the divergent execution")


if __name__ == "__main__":
    main()
