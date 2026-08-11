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


def post_decision(url: str) -> tuple[int, dict[str, Any] | str]:
    payload = json.dumps(decision_request(), separators=(",", ":")).encode()
    request = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-request-id": "REQUEST-MODEL-DECISION-DEMO",
            "x-session-id": "SESSION-MODEL-DECISION-DEMO",
            "x-user-id": "USER-MODEL-DECISION-DEMO",
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
