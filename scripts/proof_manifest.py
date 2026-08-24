from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.manifest import sha256_file


REQUIRED_VALUES = (
    ("artifact", "original_recording_id"),
    ("artifact", "original_recording_sha256"),
    ("artifact", "platform"),
    ("source", "git_sha"),
    ("source", "worker_sha256"),
    ("application", "request_sha256"),
    ("runtime", "python"),
    ("runtime", "retracesoftware"),
    ("runtime", "retracesoftware_dap"),
    ("model", "name"),
    ("model", "digest"),
    ("model", "request_sha256"),
    ("model", "response_sha256"),
    ("foundry", "call_id"),
    ("foundry", "user_id"),
    ("foundry", "session_id"),
    ("telemetry", "trace_id"),
    ("telemetry", "span_id"),
)


def verify_recording_proof(
    recording: Path,
    proof_path: Path,
    *,
    expected_platform: str | None = None,
) -> dict[str, Any]:
    proof = json.loads(proof_path.read_text())
    if proof.get("schema_version") != 1:
        raise AssertionError(f"unsupported recording proof schema: {proof}")
    actual_sha256 = sha256_file(recording)
    if proof.get("artifact", {}).get("sha256") != actual_sha256:
        raise AssertionError(
            f"proof manifest does not match {recording}: {actual_sha256}"
        )
    for section, key in REQUIRED_VALUES:
        value = proof.get(section, {}).get(key)
        if not isinstance(value, str) or not value:
            raise AssertionError(f"recording proof omitted {section}.{key}")
    if expected_platform is not None:
        actual_platform = proof["artifact"]["platform"]
        if actual_platform != expected_platform:
            raise AssertionError(
                f"recording platform {actual_platform!r} does not match "
                f"{expected_platform!r}"
            )
    return proof
