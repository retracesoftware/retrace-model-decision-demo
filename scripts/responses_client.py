from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.demo_state import CASE


def response_request() -> dict[str, Any]:
    return {
        "input": CASE["user_prompt"],
        "metadata": {
            "demo_case_id": CASE["case_id"],
            "purpose": "retrace-nondeterministic-model-decision",
        },
    }


def post_response(url: str) -> tuple[int, dict[str, Any] | str]:
    payload = json.dumps(response_request(), separators=(",", ":")).encode()
    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-agent-foundry-call-id": "CALL-MODEL-DECISION-DEMO",
            "x-agent-foundry-session-id": "SESSION-MODEL-DECISION-DEMO",
            "x-agent-foundry-user-id": "USER-MODEL-DECISION-DEMO",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            status = response.status
            body = response.read().decode()
    except HTTPError as error:
        status = error.code
        body = error.read().decode()
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body
