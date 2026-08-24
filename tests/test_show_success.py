from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.show_success import validate_historical_success


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "architecture",
    tuple(
        path.name.removeprefix("linux-")
        for path in sorted((ROOT / "example-artifacts").glob("linux-*"))
        if path.is_dir()
    ),
)
def test_reviewed_success_output_validates(architecture: str) -> None:
    artifacts = ROOT / "example-artifacts" / f"linux-{architecture}"
    expected = json.loads((artifacts / "selected-success.expected.json").read_text())
    decision = expected["decision"]
    output = "\n".join(
        [
            json.dumps({"event": "model_decision_selected", **decision}),
            json.dumps({"event": "invocation_completed", "output": expected["output"]}),
        ]
    )

    validate_historical_success(output, 0, expected)


def test_success_validation_rejects_a_traceback() -> None:
    decision = {
        "case_id": "case",
        "review_score": 64,
        "decision": "approve_refund",
        "reason": "approved",
        "model": "model",
        "created_at": "now",
        "gateway_response_id": "response",
        "model_request_sha256": "request-hash",
        "model_response_sha256": "response-hash",
    }
    expected = {
        "decision": decision,
        "output": {"decision": "approve_refund"},
        "worker_exit_code": 0,
    }
    output = "\n".join(
        [
            json.dumps({"event": "model_decision_selected", **decision}),
            json.dumps(
                {
                    "event": "invocation_completed",
                    "output": {"decision": "approve_refund"},
                }
            ),
            "Traceback (most recent call last):",
        ]
    )

    with pytest.raises(AssertionError, match="traceback"):
        validate_historical_success(output, 0, expected)
