from __future__ import annotations

import os
from typing import Any

from worker.http_json import request_json


def request_model_decision(
    *,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any],
) -> dict[str, Any]:
    base_url = os.environ["MODEL_GATEWAY_URL"].rstrip("/")
    return request_json(
        f"{base_url}/v1/decision",
        method="POST",
        payload={"messages": messages, "format": response_format},
    )
