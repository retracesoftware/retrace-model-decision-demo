from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from typing import Any

from agent.invocation_runner import run_recorded_invocation
from scripts.demo_state import CASE


async def execute_decision(
    request_payload: dict[str, Any],
    request_context: dict[str, str | None],
):
    return await run_recorded_invocation(
        request_payload=request_payload,
        request_context=request_context,
        cancellation_signal=asyncio.Event(),
    )


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "RetraceDecisionAgent/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"agent: {format % args}", flush=True)

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

    def do_GET(self) -> None:
        if self.path == "/readiness":
            self.send_json(200, {"status": "healthy"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/decisions":
            self.send_json(404, {"error": "not_found"})
            return
        try:
            request = self.read_json()
            user_input = request.get("input")
            if not isinstance(user_input, str) or not user_input.strip():
                raise ValueError("input must be nonempty text")
            request_payload = {**CASE, "user_prompt": user_input}
            result = asyncio.run(
                execute_decision(
                    request_payload,
                    {
                        "request_id": self.headers.get("x-request-id"),
                        "session_id": self.headers.get("x-session-id"),
                        "user_id": self.headers.get("x-user-id"),
                    },
                )
            )
            self.send_json(
                200,
                {
                    "recording_id": result.recording_id,
                    "output": result.output,
                },
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except Exception as error:
            self.send_json(500, {"error": str(error)})


def main() -> None:
    port = int(os.environ.get("PORT", "8088"))
    server = HTTPServer(("0.0.0.0", port), AgentHandler)
    print(f"agent listening on {port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
