from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
from typing import Any


GENERATED_ROOT = Path(os.environ.get("DEMO_GENERATED_ROOT", "/app/generated"))
COUNTER_PATH = GENERATED_ROOT / "counters" / "model-gateway.json"


def record_request(request: dict[str, Any]) -> None:
    COUNTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"count": 0, "requests": []}
    if COUNTER_PATH.is_file():
        data = json.loads(COUNTER_PATH.read_text())
    data["count"] = int(data["count"]) + 1
    data["requests"].append(request)
    temporary = COUNTER_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(COUNTER_PATH)


class JSONHandler(BaseHTTPRequestHandler):
    server_version = "RetraceModelGateway/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.server.server_name}: {format % args}", flush=True)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
