from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.run_replay_example import verify_pair


def paired_evidence() -> tuple[dict, dict, dict, dict]:
    failure_expected = {
        "runtime_input": {"serial_number": None},
        "decision": {"decision": "request_more_information"},
        "failure": {"exception_type": "AttributeError"},
        "worker_exit_code": 1,
    }
    success_expected = {
        "runtime_input": {"serial_number": None},
        "decision": {"decision": "approve_refund"},
        "failure": None,
        "worker_exit_code": 0,
    }
    shared = {
        "application": {"request_sha256": "application-request"},
        "source": {"git_sha": "revision", "worker_sha256": "worker"},
        "runtime": {
            "python": "3.12.13",
            "retracesoftware": "0.2.29",
            "retracesoftware_dap": "0.2.29",
        },
    }
    failure_proof = {
        **deepcopy(shared),
        "model": {
            "digest": "model-digest",
            "request_sha256": "model-request",
            "response_sha256": "failure-response",
        },
    }
    success_proof = {
        **deepcopy(shared),
        "model": {
            "digest": "model-digest",
            "request_sha256": "model-request",
            "response_sha256": "success-response",
        },
    }
    return failure_expected, success_expected, failure_proof, success_proof


def test_reviewed_pair_requires_one_identical_input_with_divergent_responses() -> None:
    verify_pair(*paired_evidence())


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda success_expected, success_proof: success_expected[
                "runtime_input"
            ].update(serial_number="different"),
            "runtime input",
        ),
        (
            lambda success_expected, success_proof: success_proof["application"].update(
                request_sha256="different"
            ),
            "worker request",
        ),
        (
            lambda success_expected, success_proof: success_proof["model"].update(
                request_sha256="different"
            ),
            "model request",
        ),
        (
            lambda success_expected, success_proof: success_proof["source"].update(
                git_sha="different"
            ),
            "source",
        ),
        (
            lambda success_expected, success_proof: success_proof["model"].update(
                response_sha256="failure-response"
            ),
            "one model response",
        ),
    ),
)
def test_reviewed_pair_rejects_noncomparable_artifacts(mutation, message: str) -> None:
    failure_expected, success_expected, failure_proof, success_proof = paired_evidence()
    mutation(success_expected, success_proof)

    with pytest.raises(AssertionError, match=message):
        verify_pair(
            failure_expected,
            success_expected,
            failure_proof,
            success_proof,
        )
