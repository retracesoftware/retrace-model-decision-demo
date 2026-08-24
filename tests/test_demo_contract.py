from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from agent.invocation_runner import (
    InvocationResult,
    _event,
    _worker_environment,
    _worker_events,
    session_artifact_root,
)
from agent.manifest import write_manifest
from external_world.model_gateway import SAMPLING_OPTIONS, sha256_json
from scripts.agent_client import decision_request
from scripts.demo_state import CASE
from scripts.proof_manifest import verify_recording_proof
from scripts.prepare_vscode import customize_workspace
from scripts.prepare_vscode_pair import vscode_open_commands
from scripts import platforms
from scripts.platforms import normalize_architecture, reviewed_artifact_directory
from scripts.run_demo import (
    DemoPreflightError,
    parse_success_events,
    structured_worker_events,
    verify_docker,
)
from scripts.verify_dap import (
    SOURCE,
    configure_to_marker,
    dap_value_matches,
    marker_line,
)


ROOT = Path(__file__).resolve().parents[1]
RETRACE_EXTENSION_ID = "RetraceSoftware.retrace-debug-extension"
SELECTED_RECORDING = "/app/generated/recordings/selected-failure.retrace"


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
    assert CASE["serial_number"] is None


def test_worker_events_preserve_decision_before_natural_failure() -> None:
    stdout = "\n".join(
        [
            '{"event":"model_decision_selected","decision":"request_more_information"}',
            '{"event":"application_failure","exception_type":"AttributeError"}',
        ]
    )
    events = _worker_events(stdout)

    assert _event(events, "model_decision_selected")["decision"] == (
        "request_more_information"
    )
    assert _event(events, "application_failure")["exception_type"] == ("AttributeError")


def test_worker_events_preserve_decision_and_output_for_success() -> None:
    stdout = "\n".join(
        [
            '{"event":"model_decision_selected","decision":"approve_refund"}',
            '{"event":"invocation_completed","output":{"action_detail":"approved"}}',
        ]
    )

    decision, completed = parse_success_events(stdout)

    assert decision["decision"] == "approve_refund"
    assert completed["output"] == {"action_detail": "approved"}


def test_replay_event_parser_rejects_duplicate_event_names() -> None:
    stdout = "\n".join(
        [
            '{"event":"model_decision_selected","decision":"approve_refund"}',
            '{"event":"model_decision_selected","decision":"escalate_specialist"}',
        ]
    )

    with pytest.raises(AssertionError, match="duplicate"):
        structured_worker_events(stdout)


def test_failed_recorded_invocation_remains_a_first_class_result(tmp_path) -> None:
    result = InvocationResult(
        recording_id="decision-test",
        worker_exit_code=1,
        decision={"decision": "request_more_information"},
        output=None,
        failure={
            "exception_type": "AttributeError",
            "exception_message": "'NoneType' object has no attribute 'strip'",
        },
        manifest_path=tmp_path / "manifest.json",
        recording_path=tmp_path / "recording.retrace",
    )

    assert not result.succeeded
    assert result.failure["exception_type"] == "AttributeError"


def test_protocol_response_distinguishes_invocation_and_recording_ids(
    tmp_path,
) -> None:
    pytest.importorskip("azure.ai.agentserver.invocations")
    from agent.main import _response_payload

    result = InvocationResult(
        recording_id="decision-test",
        worker_exit_code=1,
        decision={"decision": "request_more_information"},
        output=None,
        failure={
            "exception_type": "AttributeError",
            "exception_message": "'NoneType' object has no attribute 'strip'",
        },
        manifest_path=tmp_path / "manifest.json",
        recording_path=tmp_path / "recording.retrace",
    )
    payload = _response_payload(
        result,
        foundry_call_id="CALL-TEST",
        session_id="SESSION-TEST",
    )

    assert payload["recording_id"] == "decision-test"
    assert payload["foundry_call_id"] == "CALL-TEST"
    assert payload["session_id"] == "SESSION-TEST"


def test_session_artifacts_default_to_persistent_home(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("RETRACE_SESSION_ARTIFACT_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert session_artifact_root() == tmp_path / "retrace"


def test_manifest_publication_is_atomic(tmp_path) -> None:
    path = tmp_path / "manifests" / "recording.json"

    write_manifest(path, {"recording_id": "decision-test"})

    assert json.loads(path.read_text()) == {"recording_id": "decision-test"}
    assert not path.with_suffix(".tmp").exists()


def test_devcontainer_uses_current_retrace_extension_and_failed_recording() -> None:
    devcontainer = json.loads(
        (ROOT / ".devcontainer" / "devcontainer.json").read_text()
    )
    vscode = devcontainer["customizations"]["vscode"]
    assert RETRACE_EXTENSION_ID in vscode["extensions"]
    assert vscode["settings"]["python.analysis.languageServerMode"] == "light"
    assert vscode["settings"]["python.analysis.indexing"] is False
    assert vscode["settings"]["remote.extensionKind"][RETRACE_EXTENSION_ID] == [
        "workspace"
    ]
    assert devcontainer["postCreateCommand"] == (
        "python -m scripts.prepare_vscode_pair"
    )

    workspace_settings = json.loads((ROOT / ".vscode" / "settings.json").read_text())
    assert workspace_settings["retrace.recording"] == SELECTED_RECORDING
    assert workspace_settings["terminal.integrated.cwd"] == "/app"


@pytest.mark.parametrize(
    ("outcome", "label", "title_color"),
    (
        ("success", "PASSING EXECUTION", "#166534"),
        ("failure", "FAILING EXECUTION", "#991B1B"),
    ),
)
def test_generated_workspaces_are_visibly_outcome_specific(
    tmp_path: Path,
    outcome: str,
    label: str,
    title_color: str,
) -> None:
    workspace_path = tmp_path / f"selected-{outcome}.code-workspace"
    workspace_path.write_text(
        json.dumps(
            {
                "folders": [{"path": "/app"}],
                "settings": {
                    "retrace.recording": (
                        f"/app/generated/recordings/selected-{outcome}.retrace"
                    )
                },
                "launch": {
                    "configurations": [
                        {"type": "retrace", "name": "Retrace"},
                    ]
                },
            }
        )
    )

    customize_workspace(workspace_path, outcome)

    workspace = json.loads(workspace_path.read_text())
    assert workspace["folders"][0]["name"] == label
    assert workspace["settings"]["retrace.recording"] == (
        f"/app/generated/recordings/selected-{outcome}.retrace"
    )
    assert workspace["settings"]["window.title"].startswith(label)
    assert workspace["settings"]["python.analysis.languageServerMode"] == "light"
    assert workspace["settings"]["python.analysis.indexing"] is False
    assert (
        workspace["settings"]["workbench.colorCustomizations"][
            "titleBar.activeBackground"
        ]
        == title_color
    )
    assert workspace["launch"]["configurations"][0]["name"] == (f"Retrace: {label}")


def test_vscode_pair_opens_success_then_reuses_current_window_for_failure() -> None:
    success = Path("/app/success.code-workspace")
    failure = Path("/app/failure.code-workspace")

    assert vscode_open_commands("/remote/code", success, failure) == [
        ["/remote/code", "--new-window", str(success)],
        ["/remote/code", "--reuse-window", str(failure)],
    ]


def test_compose_writes_bind_mounted_artifacts_as_host_user() -> None:
    compose = (ROOT / "compose.yaml").read_text()

    assert 'user: "${DEMO_UID:-0}:${DEMO_GID:-0}"' in compose
    assert "HOME: /app/generated/session-home" in compose
    assert "platform: linux/amd64" not in compose

    devcontainer_compose = (ROOT / ".devcontainer" / "compose.yaml").read_text()
    assert "platform: linux/amd64" not in devcontainer_compose
    assert "mem_limit: 2g" in devcontainer_compose
    assert "cpus: 2" in devcontainer_compose


def test_supported_docker_architectures_use_native_reviewed_artifacts() -> None:
    assert normalize_architecture("x86_64") == "amd64"
    assert normalize_architecture("amd64") == "amd64"
    assert normalize_architecture("aarch64") == "arm64"
    assert normalize_architecture("arm64") == "arm64"
    assert reviewed_artifact_directory(ROOT, "arm64") == (
        ROOT / "example-artifacts" / "linux-arm64"
    )


def test_container_architecture_falls_back_when_docker_cli_is_absent(
    monkeypatch,
) -> None:
    def missing_docker(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(platforms.subprocess, "run", missing_docker)
    monkeypatch.setattr(platforms.platform, "machine", lambda: "aarch64")

    assert platforms.docker_architecture() == "arm64"


@pytest.mark.parametrize(
    "architecture",
    tuple(
        path.name.removeprefix("linux-")
        for path in sorted((ROOT / "example-artifacts").glob("linux-*"))
        if path.is_dir()
    ),
)
def test_reviewed_presentation_artifact_pair_is_complete(architecture: str) -> None:
    artifacts = reviewed_artifact_directory(ROOT, architecture)
    expected = {}
    proofs = {}
    for outcome in ("failure", "success"):
        recording = artifacts / f"selected-{outcome}.retrace"
        expected[outcome] = json.loads(
            (artifacts / f"selected-{outcome}.expected.json").read_text()
        )
        proofs[outcome] = verify_recording_proof(
            recording,
            artifacts / f"selected-{outcome}.proof.json",
            expected_platform=f"linux/{architecture}",
        )
        assert recording.stat().st_size > 10_000
        assert proofs[outcome]["runtime"] == {
            "python": "3.12.13",
            "retracesoftware": "0.2.29",
            "retracesoftware_dap": "0.2.29",
        }
        assert proofs[outcome]["model"]["name"] == "qwen3:1.7b"
        assert len(proofs[outcome]["telemetry"]["trace_id"]) == 32
        assert len(proofs[outcome]["telemetry"]["span_id"]) == 16

    failure = expected["failure"]
    success = expected["success"]
    assert failure["decision"]["decision"] == "request_more_information"
    assert 65 <= failure["decision"]["review_score"] < 70
    assert failure["failure"] == {
        "exception_type": "AttributeError",
        "exception_message": "'NoneType' object has no attribute 'strip'",
    }
    assert failure["runtime_input"]["serial_number"] is None

    assert success["failure"] is None
    assert success["worker_exit_code"] == 0
    assert success["decision"]["decision"] in {
        "approve_refund",
        "escalate_specialist",
    }
    assert success["output"]["decision"] == success["decision"]["decision"]
    assert success["runtime_input"] == failure["runtime_input"]

    assert (
        proofs["success"]["model"]["request_sha256"]
        == proofs["failure"]["model"]["request_sha256"]
    )
    assert (
        proofs["success"]["application"]["request_sha256"]
        == proofs["failure"]["application"]["request_sha256"]
    )
    assert (
        proofs["success"]["model"]["response_sha256"]
        != proofs["failure"]["model"]["response_sha256"]
    )
    assert (
        proofs["success"]["source"]["worker_sha256"]
        == proofs["failure"]["source"]["worker_sha256"]
    )
    assert proofs["success"]["source"] == proofs["failure"]["source"]
    assert proofs["success"]["runtime"] == proofs["failure"]["runtime"]
    assert (
        proofs["success"]["model"]["digest"] == (proofs["failure"]["model"]["digest"])
    )


def test_agent_uses_microsoft_invocation_contract() -> None:
    source = (ROOT / "agent" / "main.py").read_text()

    assert "InvocationAgentServerHost" in source
    assert "get_request_context" in source
    assert "@app.invoke_handler" in source
    assert "@app.shutdown_handler" in source
    assert "retrace.recording.id" in source
    assert "/decisions" not in source


def test_local_client_emulates_current_foundry_gateway_context() -> None:
    source = (ROOT / "scripts" / "agent_client.py").read_text()

    assert "x-agent-foundry-call-id" in source
    assert "x-agent-user-id" in source
    assert "traceparent" in source
    assert "x-agent-invocation-id" not in source


def test_python_package_pin_matches_the_built_retrace_release() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert '"retracesoftware==0.2.29"' in pyproject
    assert '"retracesoftware==0.2.25"' not in pyproject


def test_otel_collector_decodes_exported_invocation_span() -> None:
    trace_service = pytest.importorskip(
        "opentelemetry.proto.collector.trace.v1.trace_service_pb2"
    )
    from external_world.otel_collector import decode_spans

    ExportTraceServiceRequest = trace_service.ExportTraceServiceRequest
    request = ExportTraceServiceRequest()
    resource_spans = request.resource_spans.add()
    scope_spans = resource_spans.scope_spans.add()
    span = scope_spans.spans.add()
    span.trace_id = b"t" * 16
    span.span_id = b"s" * 8
    span.name = "invoke_agent retrace-model-decision-demo:1.0"
    attribute = span.attributes.add()
    attribute.key = "retrace.recording.id"
    attribute.value.string_value = "decision-test"

    decoded = decode_spans(request.SerializeToString())

    assert decoded[0]["attributes"]["retrace.recording.id"] == "decision-test"
    assert decoded[0]["trace_id"] == (b"t" * 16).hex()


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


def test_dap_configuration_stops_at_the_real_breakpoint() -> None:
    line = marker_line()

    class Client:
        def __init__(self) -> None:
            self.actions: list[tuple[str, str]] = []

        def send(self, command: str, arguments: dict | None = None) -> None:
            self.actions.append(("send", command))

        def response(self, command: str) -> dict:
            self.actions.append(("response", command))
            if command == "stackTrace":
                return {
                    "body": {
                        "stackFrames": [
                            {
                                "id": 1,
                                "line": line,
                                "source": {"path": str(SOURCE)},
                            }
                        ]
                    }
                }
            return {}

        def stopped(self, reason: str) -> dict:
            self.actions.append(("stopped", reason))
            return {"event": "stopped", "body": {"reason": reason}}

    client = Client()

    frames = configure_to_marker(client, line=line)

    assert frames[0]["line"] == line
    assert client.actions == [
        ("send", "configurationDone"),
        ("response", "configurationDone"),
        ("stopped", "breakpoint"),
        ("send", "stackTrace"),
        ("response", "stackTrace"),
    ]
