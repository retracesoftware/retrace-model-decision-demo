from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

from agent.manifest import sha256_file, sha256_sources, sha256_text, write_manifest


ROOT = Path(os.environ.get("DEMO_ROOT", "/app"))
GENERATED = Path(os.environ.get("DEMO_GENERATED_ROOT", ROOT / "generated"))


def session_artifact_root() -> Path:
    configured = os.environ.get("RETRACE_SESSION_ARTIFACT_ROOT")
    return Path(configured) if configured else Path.home() / "retrace"


@dataclass(frozen=True)
class InvocationResult:
    recording_id: str
    worker_exit_code: int
    decision: dict[str, Any]
    output: dict[str, Any] | None
    failure: dict[str, Any] | None
    manifest_path: Path
    recording_path: Path

    @property
    def succeeded(self) -> bool:
        return self.worker_exit_code == 0


def _worker_environment(*, invocation_home: Path, recording_id: str) -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(invocation_home),
        "PYTHONPATH": str(ROOT),
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "RETRACE_RECORDING_ID": recording_id,
        "MODEL_GATEWAY_URL": os.environ.get(
            "MODEL_GATEWAY_URL", "http://model-gateway:8091"
        ),
    }


def _source_hash() -> str:
    return sha256_sources(sorted((ROOT / "worker").glob("*.py")))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _worker_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("event"), str):
            events.append(payload)
    return events


def _event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    matches = [item for item in events if item.get("event") == name]
    if len(matches) > 1:
        raise RuntimeError(f"worker emitted duplicate {name!r} events")
    return matches[0] if matches else None


async def run_recorded_invocation(
    *,
    request_payload: dict[str, Any],
    request_context: dict[str, str | None],
    cancellation_signal: asyncio.Event,
) -> InvocationResult:
    recording_id = f"decision-{uuid.uuid4()}"
    request_json = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    artifact_root = session_artifact_root()
    recording_path = artifact_root / "recordings" / f"{recording_id}.retrace"
    manifest_path = artifact_root / "manifests" / f"{recording_id}.json"
    stdout_path = artifact_root / "logs" / f"{recording_id}.stdout.log"
    stderr_path = artifact_root / "logs" / f"{recording_id}.stderr.log"
    invocation_home = artifact_root / "worker-homes" / recording_id

    for path in (
        recording_path.parent,
        manifest_path.parent,
        stdout_path.parent,
        invocation_home,
    ):
        path.mkdir(parents=True, exist_ok=True)

    started_at = _utc_now()
    process = await asyncio.create_subprocess_exec(
        "retracepython",
        "--recording",
        str(recording_path),
        "-m",
        "worker",
        "--request-json",
        request_json,
        cwd=ROOT,
        env=_worker_environment(
            invocation_home=invocation_home,
            recording_id=recording_id,
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    communication = asyncio.create_task(process.communicate())
    cancellation = asyncio.create_task(cancellation_signal.wait())
    done, _ = await asyncio.wait(
        {communication, cancellation},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if cancellation in done and cancellation.result() and not communication.done():
        process.terminate()
    stdout_bytes, stderr_bytes = await communication
    cancellation.cancel()
    with suppress(asyncio.CancelledError):
        await cancellation

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)
    worker_exit_code = int(process.returncode or 0)
    recording_available = recording_path.is_file() and recording_path.stat().st_size > 0

    events = _worker_events(stdout)
    decision = _event(events, "model_decision_selected")
    completed = _event(events, "invocation_completed")
    failure = _event(events, "application_failure")
    output = completed.get("output") if completed else None
    manifest = {
        "schema_version": 2,
        "recording_id": recording_id,
        "recording_path": str(recording_path),
        "recording_sha256": (
            sha256_file(recording_path) if recording_available else None
        ),
        "request_sha256": sha256_text(request_json),
        "source_sha256": _source_hash(),
        "source_git_sha": os.environ.get("DEMO_SOURCE_GIT_SHA", "unknown"),
        "foundry_call_id": request_context.get("foundry_call_id"),
        "user_id": request_context.get("user_id"),
        "session_id": request_context.get("session_id"),
        "trace_id": request_context.get("trace_id"),
        "span_id": request_context.get("span_id"),
        "protocol_invocation_id": request_context.get("protocol_invocation_id"),
        "worker_exit_code": worker_exit_code,
        "recording_available": recording_available,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "python_version": sys.version.split()[0],
        "retracesoftware_version": version("retracesoftware"),
        "retracesoftware_dap_version": version("retracesoftware-dap"),
        "model_digest": os.environ.get("OLLAMA_MODEL_DIGEST"),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "decision": decision,
        "output": output,
        "failure": failure,
    }
    write_manifest(manifest_path, manifest)

    if not recording_available:
        raise RuntimeError(f"worker exited without recording: {recording_path}")
    if not isinstance(decision, dict):
        raise RuntimeError(f"worker emitted no model decision event: {stdout_path}")
    if worker_exit_code == 0:
        if not isinstance(output, dict) or failure is not None:
            raise RuntimeError(
                f"successful worker emitted invalid events: {stdout_path}"
            )
    elif not isinstance(failure, dict) or output is not None:
        raise RuntimeError(f"failed worker emitted invalid events: {stdout_path}")

    return InvocationResult(
        recording_id=recording_id,
        worker_exit_code=worker_exit_code,
        decision=decision,
        output=output,
        failure=failure,
        manifest_path=manifest_path,
        recording_path=recording_path,
    )
