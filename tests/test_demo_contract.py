from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from agent.invocation_runner import _worker_environment
from external_world.model_gateway import SAMPLING_OPTIONS, sha256_json
from scripts.agent_client import decision_request
from scripts.demo_state import CASE
from scripts.run_demo import DemoPreflightError, verify_docker
from scripts.verify_dap import dap_value_matches


ROOT = Path(__file__).resolve().parents[1]
RETRACE_EXTENSION_ID = "RetraceSoftware.retrace-debug-extension"
SELECTED_RECORDING = "/app/generated/recordings/selected-decision.retrace"


def test_sampling_is_nondeterministic_by_configuration() -> None:
    assert SAMPLING_OPTIONS["temperature"] > 0
    assert SAMPLING_OPTIONS["top_p"] > 0
    assert "seed" not in SAMPLING_OPTIONS


def test_model_request_hash_is_stable_and_sensitive() -> None:
    payload = {"messages": ["same"], "tools": ["same"]}
    assert sha256_json(payload) == sha256_json(dict(reversed(list(payload.items()))))
    assert sha256_json(payload) != sha256_json({"messages": ["changed"]})


def test_agent_request_is_identical_across_live_invocations() -> None:
    first = decision_request()
    second = decision_request()
    assert first == second
    assert first["input"] == CASE["user_prompt"]


def test_devcontainer_uses_current_retrace_extension_and_selected_recording() -> None:
    devcontainer = json.loads(
        (ROOT / ".devcontainer" / "devcontainer.json").read_text()
    )
    vscode = devcontainer["customizations"]["vscode"]
    assert RETRACE_EXTENSION_ID in vscode["extensions"]
    assert vscode["settings"]["remote.extensionKind"][RETRACE_EXTENSION_ID] == [
        "workspace"
    ]

    workspace_settings = json.loads((ROOT / ".vscode" / "settings.json").read_text())
    assert workspace_settings["retrace.recording"] == SELECTED_RECORDING
    assert workspace_settings["terminal.integrated.cwd"] == "/app"


def test_recorded_worker_environment_excludes_parent_secrets(tmp_path) -> None:
    os.environ["DEMO_PARENT_SECRET"] = "must-not-cross-boundary"
    environment = _worker_environment(
        invocation_home=tmp_path,
        recording_id="decision-test",
    )
    assert "DEMO_PARENT_SECRET" not in environment
    assert environment["RETRACE_RECORDING_ID"] == "decision-test"


def test_docker_preflight_explains_an_unreachable_engine(monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            returncode=1,
            stdout="Cannot connect to the Docker daemon",
        ),
    )

    with pytest.raises(DemoPreflightError, match="Start Docker Desktop"):
        verify_docker()


def test_dap_value_accepts_exact_and_repr_truncated_historical_strings() -> None:
    expected = "The historical model rationale is longer than the DAP repr budget."

    assert dap_value_matches(expected, repr(expected))
    assert dap_value_matches(expected, repr("The historical model rationale..."))
    assert dap_value_matches(expected, "'The historical model rationale...")


def test_dap_value_rejects_a_different_historical_prefix() -> None:
    assert not dap_value_matches("approve_refund", repr("escalate_specialist..."))
