from __future__ import annotations

import asyncio
import os

from agent.invocation_runner import _worker_environment
from external_world.model_gateway import SAMPLING_OPTIONS, sha256_json
from scripts.demo_state import CASE
from scripts.responses_client import response_request
from scripts.verify_dap import dap_value_matches


def test_sampling_is_nondeterministic_by_configuration() -> None:
    assert SAMPLING_OPTIONS["temperature"] > 0
    assert SAMPLING_OPTIONS["top_p"] > 0
    assert "seed" not in SAMPLING_OPTIONS


def test_model_request_hash_is_stable_and_sensitive() -> None:
    payload = {"messages": ["same"], "tools": ["same"]}
    assert sha256_json(payload) == sha256_json(dict(reversed(list(payload.items()))))
    assert sha256_json(payload) != sha256_json({"messages": ["changed"]})


def test_responses_request_is_identical_across_live_invocations() -> None:
    first = response_request()
    second = response_request()
    assert first == second
    assert first["input"] == CASE["user_prompt"]


def test_recorded_worker_environment_excludes_parent_secrets(tmp_path) -> None:
    os.environ["DEMO_PARENT_SECRET"] = "must-not-cross-boundary"
    environment = _worker_environment(
        invocation_home=tmp_path,
        recording_id="decision-test",
    )
    assert "DEMO_PARENT_SECRET" not in environment
    assert "FOUNDRY_PROJECT_ENDPOINT" not in environment
    assert environment["RETRACE_RECORDING_ID"] == "decision-test"


def test_invocation_lock_is_not_part_of_worker_environment() -> None:
    event = asyncio.Event()
    assert not event.is_set()


def test_dap_value_accepts_exact_and_repr_truncated_historical_strings() -> None:
    expected = "The historical model rationale is longer than the DAP repr budget."

    assert dap_value_matches(expected, repr(expected))
    assert dap_value_matches(expected, repr("The historical model rationale..."))
    assert dap_value_matches(expected, "'The historical model rationale...")


def test_dap_value_rejects_a_different_historical_prefix() -> None:
    assert not dap_value_matches("approve_refund", repr("escalate_specialist..."))
