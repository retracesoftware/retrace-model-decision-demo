from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen


def request_json(
    url: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())
