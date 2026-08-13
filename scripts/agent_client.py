from __future__ import annotations

import json
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
) -> tuple[int, dict[str, Any] | str, dict[str, str]]:
    payload = json.dumps(decision_request(), separators=(",", ":")).encode()
    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-agent-invocation-id": f"INVOCATION-MODEL-DEMO-{invocation_number:02d}",
            "x-agent-user-id": "USER-MODEL-DECISION-DEMO",
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
        return status, json.loads(body), response_headers
    except json.JSONDecodeError:
        return status, body, response_headers
