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


@dataclass(frozen=True)
class InvocationResult:
    recording_id: str
    output: dict[str, Any]
    manifest_path: Path
    recording_path: Path


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


async def run_recorded_invocation(
    *,
    request_payload: dict[str, Any],
    foundry_context: dict[str, str | None],
    cancellation_signal: asyncio.Event,
) -> InvocationResult:
    recording_id = f"decision-{uuid.uuid4()}"
    request_json = json.dumps(request_payload, sort_keys=True, separators=(",", ":"))
    recording_path = GENERATED / "recordings" / f"{recording_id}.retrace"
    manifest_path = GENERATED / "manifests" / f"{recording_id}.json"
    stdout_path = GENERATED / "logs" / f"{recording_id}.stdout.log"
    stderr_path = GENERATED / "logs" / f"{recording_id}.stderr.log"
    invocation_home = GENERATED / "homes" / recording_id

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

    output_lines = [line for line in stdout.splitlines() if line.strip()]
    output = json.loads(output_lines[-1]) if output_lines else None
    manifest = {
        "schema_version": 1,
        "recording_id": recording_id,
        "recording_path": str(recording_path),
        "recording_sha256": (
            sha256_file(recording_path) if recording_available else None
        ),
        "request_sha256": sha256_text(request_json),
        "source_sha256": _source_hash(),
        "foundry_call_id": foundry_context.get("call_id"),
        "foundry_user_id": foundry_context.get("user_id"),
        "foundry_session_id": foundry_context.get("session_id"),
        "worker_exit_code": worker_exit_code,
        "recording_available": recording_available,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "python_version": sys.version.split()[0],
        "retracesoftware_version": version("retracesoftware"),
        "retracesoftware_dap_version": version("retracesoftware-dap"),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "output": output,
    }
    write_manifest(manifest_path, manifest)

    if worker_exit_code:
        raise RuntimeError(
            f"recorded model invocation failed: {recording_id}; stderr={stderr_path}"
        )
    if not recording_available:
        raise RuntimeError(f"worker succeeded without recording: {recording_path}")
    if not isinstance(output, dict):
        raise RuntimeError(f"worker returned no JSON output: {stdout_path}")

    return InvocationResult(
        recording_id=recording_id,
        output=output,
        manifest_path=manifest_path,
        recording_path=recording_path,
    )
