from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.show_failure import validate_historical_failure


ROOT = Path(__file__).resolve().parents[1]


def reviewed_expectation(architecture: str = "linux-arm64") -> dict:
    return json.loads(
        (
            ROOT / "example-artifacts" / architecture / "selected-failure.expected.json"
        ).read_text()
    )


def historical_output(expected: dict) -> str:
    decision = {"event": "model_decision_selected", **expected["decision"]}
    failure = {"event": "application_failure", **expected["failure"]}
    return "\n".join(
        (
            json.dumps(decision),
            json.dumps(failure),
            "Traceback (most recent call last):",
            '  File "/app/worker/decision_agent.py", line 116, in run_decision_agent',
            "    normalized = serial_number.strip()",
            "                 ^^^^^^^^^^^^^^^^^^^",
            "AttributeError: 'NoneType' object has no attribute 'strip'",
        )
    )


@pytest.mark.parametrize("architecture", ["linux-amd64", "linux-arm64"])
def test_historical_failure_accepts_the_complete_traceback(
    architecture: str,
) -> None:
    expected = reviewed_expectation(architecture)

    validate_historical_failure(
        historical_output(expected),
        expected["worker_exit_code"],
        expected,
    )


def test_historical_failure_rejects_a_changed_model_decision() -> None:
    expected = reviewed_expectation()
    changed = copy.deepcopy(expected)
    changed["decision"]["review_score"] = 66

    with pytest.raises(AssertionError, match="decision changed"):
        validate_historical_failure(
            historical_output(changed),
            expected["worker_exit_code"],
            expected,
        )


def test_historical_failure_requires_the_source_location() -> None:
    expected = reviewed_expectation()
    output = historical_output(expected).replace(
        '  File "/app/worker/decision_agent.py", line 116, in run_decision_agent\n',
        "",
    )

    with pytest.raises(AssertionError, match="traceback source location"):
        validate_historical_failure(
            output,
            expected["worker_exit_code"],
            expected,
        )
