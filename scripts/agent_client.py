from __future__ import annotations

import json
import hashlib
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.demo_state import CASE


def decision_request() -> dict[str, Any]:
    return {
        "input": CASE["user_prompt"],
        "metadata": {
            "demo_case_id": CASE["case_id"],
            "purpose": "retrace-nondeterministic-model-decision",
        },
    }


def post_invocation(
    url: str,
    *,
    invocation_number: int,
) -> tuple[int, dict[str, Any] | str, dict[str, str], dict[str, str]]:
    payload = json.dumps(decision_request(), separators=(",", ":")).encode()
    call_id = f"CALL-MODEL-DEMO-{invocation_number:02d}"
    user_id = "USER-MODEL-DECISION-DEMO"
    trace_id = hashlib.sha256(f"trace-{invocation_number}".encode()).hexdigest()[:32]
    parent_span_id = hashlib.sha256(
        f"parent-span-{invocation_number}".encode()
    ).hexdigest()[:16]
    local_platform_context = {
        "foundry_call_id": call_id,
        "user_id": user_id,
        "trace_id": trace_id,
        "traceparent": f"00-{trace_id}-{parent_span_id}-01",
    }
    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-agent-foundry-call-id": call_id,
            "x-agent-user-id": user_id,
            "traceparent": local_platform_context["traceparent"],
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            status = response.status
            body = response.read().decode()
            response_headers = dict(response.headers.items())
    except HTTPError as error:
        status = error.code
        body = error.read().decode()
        response_headers = dict(error.headers.items())
    try:
        return status, json.loads(body), response_headers, local_platform_context
    except json.JSONDecodeError:
        return status, body, response_headers, local_platform_context
