from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from agent.manifest import sha256_file
from scripts.agent_client import decision_request
from scripts.demo_state import GENERATED, ROOT
from scripts.verify_dap import replay_binary


def wait_for_url(url: str, *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.1)
    raise TimeoutError(f"service did not become ready: {url}")


def wait_for_path(path: Path, *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start_process(
    command: list[str],
    *,
    environment: dict[str, str],
    stdout_path: Path,
) -> tuple[subprocess.Popen[str], Any]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stream = stdout_path.open("w")
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    return process, stream


def request_process(
    *,
    agent_port: int,
    call_id: str,
    user_id: str,
    session_id: str,
    trace_id: str,
    stdout_path: Path,
) -> tuple[subprocess.Popen[str], Any]:
    payload_path = stdout_path.with_suffix(".request.json")
    payload_path.write_text(json.dumps(decision_request()) + "\n")
    parent_span_id = hashlib.sha256(f"parent-{call_id}".encode()).hexdigest()[:16]
    stream = stdout_path.open("w")
    process = subprocess.Popen(
        [
            "curl",
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--max-time",
            "30",
            "--request",
            "POST",
            f"http://127.0.0.1:{agent_port}/invocations?agent_session_id={session_id}",
            "--header",
            "Content-Type: application/json",
            "--header",
            f"x-agent-foundry-call-id: {call_id}",
            "--header",
            f"x-agent-user-id: {user_id}",
            "--header",
            f"traceparent: 00-{trace_id}-{parent_span_id}-01",
            "--data-binary",
            f"@{payload_path}",
        ],
        cwd=ROOT,
        text=True,
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    return process, stream


def manifest_for(session_home: Path) -> tuple[Path, dict[str, Any]]:
    manifest_dir = session_home / "retrace" / "manifests"
    temporary = list(manifest_dir.glob("*.tmp"))
    if temporary:
        raise AssertionError(
            f"incomplete manifest files survived shutdown: {temporary}"
        )
    paths = list(manifest_dir.glob("*.json"))
    if len(paths) != 1:
        raise AssertionError(f"expected one persisted manifest, found {paths}")
    return paths[0], json.loads(paths[0].read_text())


def replay_recording(recording: Path, *, expected_decision: str) -> dict[str, Any]:
    extracted = recording.with_suffix(".d")
    shutil.rmtree(extracted, ignore_errors=True)
    extraction = subprocess.run(
        [replay_binary(recording), "--recording", str(recording), "--extract"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if extraction.returncode != 0:
        raise AssertionError(
            f"persisted recording did not extract:\n{extraction.stdout}"
        )
    index = json.loads((extracted / "index.json").read_text())
    pidfile = extracted / f"{int(index['root']['pid'])}.bin"
    replay = subprocess.run(
        [str(pidfile)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if replay.returncode != 0:
        raise AssertionError(f"persisted recording did not replay:\n{replay.stdout}")
    events = []
    for line in replay.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event"):
            events.append(event)
    decisions = [
        item for item in events if item.get("event") == "model_decision_selected"
    ]
    completed = [item for item in events if item.get("event") == "invocation_completed"]
    if len(decisions) != 1 or decisions[0].get("decision") != expected_decision:
        raise AssertionError(f"replay changed the model decision: {events}")
    if len(completed) != 1:
        raise AssertionError(f"replay did not complete the invocation: {events}")
    return {
        "decision": decisions[0]["decision"],
        "review_score": decisions[0]["review_score"],
        "stdout_sha256": hashlib.sha256(replay.stdout.encode()).hexdigest(),
    }


def verify_run(number: int) -> dict[str, Any]:
    run_root = GENERATED / "lifecycle" / f"run-{number:02d}"
    shutil.rmtree(run_root, ignore_errors=True)
    run_root.mkdir(parents=True)
    session_home = run_root / "session-home"
    session_home.mkdir()
    marker = run_root / "worker-at-model-boundary.marker"
    telemetry_path = run_root / "spans.jsonl"
    agent_port = 18088 + number
    gateway_port = 18188 + number
    telemetry_port = 18288 + number
    call_id = f"CALL-LIFECYCLE-{number:02d}"
    user_id = "USER-LIFECYCLE-PROOF"
    session_id = f"SESSION-LIFECYCLE-{number:02d}"
    trace_id = hashlib.sha256(f"lifecycle-trace-{number}".encode()).hexdigest()[:32]

    base_environment = os.environ.copy()
    base_environment.update(
        {
            "DEMO_ROOT": str(ROOT),
            "DEMO_GENERATED_ROOT": str(run_root),
            "PYTHONPATH": str(ROOT),
        }
    )
    gateway_environment = {
        **base_environment,
        "PORT": str(gateway_port),
        "LIFECYCLE_REQUEST_MARKER": str(marker),
        "LIFECYCLE_RESPONSE_DELAY": "2",
    }
    telemetry_environment = {
        **base_environment,
        "PORT": str(telemetry_port),
        "OTEL_OUTPUT": str(telemetry_path),
    }
    agent_environment = {
        **base_environment,
        "PORT": str(agent_port),
        "HOME": str(session_home),
        "MODEL_GATEWAY_URL": f"http://127.0.0.1:{gateway_port}",
        "FOUNDRY_AGENT_NAME": "retrace-lifecycle-proof",
        "FOUNDRY_AGENT_VERSION": "1.0",
        "OTEL_SDK_DISABLED": "false",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{telemetry_port}",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "DEMO_SOURCE_GIT_SHA": os.environ.get("DEMO_SOURCE_GIT_SHA", "unknown"),
        "OLLAMA_MODEL_DIGEST": "lifecycle-contract-fixture",
    }

    processes: list[subprocess.Popen[Any]] = []
    streams: list[Any] = []
    try:
        gateway, gateway_stream = start_process(
            [sys.executable, "-m", "scripts.lifecycle_model_gateway"],
            environment=gateway_environment,
            stdout_path=run_root / "gateway.log",
        )
        telemetry, telemetry_stream = start_process(
            [sys.executable, "-m", "external_world.otel_collector"],
            environment=telemetry_environment,
            stdout_path=run_root / "telemetry.log",
        )
        agent, agent_stream = start_process(
            [sys.executable, "-m", "agent.main"],
            environment=agent_environment,
            stdout_path=run_root / "agent.log",
        )
        processes.extend([gateway, telemetry, agent])
        streams.extend([gateway_stream, telemetry_stream, agent_stream])
        wait_for_url(f"http://127.0.0.1:{gateway_port}/health")
        wait_for_url(f"http://127.0.0.1:{telemetry_port}/health")
        wait_for_url(f"http://127.0.0.1:{agent_port}/readiness")

        client, client_stream = request_process(
            agent_port=agent_port,
            call_id=call_id,
            user_id=user_id,
            session_id=session_id,
            trace_id=trace_id,
            stdout_path=run_root / "client-response.json",
        )
        processes.append(client)
        streams.append(client_stream)
        wait_for_path(marker)
        agent.send_signal(signal.SIGTERM)

        if client.wait(timeout=30) != 0:
            client_stream.flush()
            raise AssertionError(
                "in-flight invocation failed while the host drained SIGTERM:\n"
                + (run_root / "client-response.json").read_text()
            )
        if agent.wait(timeout=30) != 0:
            agent_stream.flush()
            raise AssertionError(
                "Hosted Agent process did not exit cleanly after SIGTERM:\n"
                + (run_root / "agent.log").read_text()
            )
        client_stream.flush()
        response = json.loads((run_root / "client-response.json").read_text())
        if response.get("status") != "completed":
            raise AssertionError(f"drained invocation was not completed: {response}")

        manifest_path, manifest = manifest_for(session_home)
        recording = Path(manifest["recording_path"])
        if not recording.is_file() or recording.stat().st_size <= 10_000:
            raise AssertionError(f"recording was not fully persisted: {recording}")
        if manifest.get("recording_sha256") != sha256_file(recording):
            raise AssertionError("persisted recording hash does not match its manifest")
        expected_context = {
            "foundry_call_id": call_id,
            "user_id": user_id,
            "session_id": session_id,
            "trace_id": trace_id,
        }
        for key, expected in expected_context.items():
            if manifest.get(key) != expected:
                raise AssertionError(
                    f"persisted manifest changed {key}: {manifest.get(key)!r}"
                )
        if not manifest.get("span_id"):
            raise AssertionError("persisted manifest omitted the active span ID")

        stop_process(gateway)
        replay = replay_recording(recording, expected_decision="approve_refund")
        result = {
            "run": number,
            "signal": "SIGTERM",
            "request_drained": True,
            "session_home": str(session_home),
            "manifest": str(manifest_path),
            "recording": str(recording),
            "recording_sha256": manifest["recording_sha256"],
            "foundry_call_id": call_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "span_id": manifest["span_id"],
            "model_service_during_replay": "stopped",
            "replay": replay,
        }
        (run_root / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
        print(
            f"lifecycle={number:02d} signal=SIGTERM drain=pass "
            f"manifest=pass replay=pass model_service=stopped"
        )
        return result
    finally:
        for process in reversed(processes):
            stop_process(process)
        for stream in streams:
            stream.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be positive")
    results = [verify_run(number) for number in range(1, args.runs + 1)]
    output = GENERATED / "lifecycle" / "summary.json"
    output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"lifecycle_summary={output} runs={len(results)} status=pass")


if __name__ == "__main__":
    main()
