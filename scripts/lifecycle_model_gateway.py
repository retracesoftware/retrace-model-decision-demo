from __future__ import annotations

import hashlib
from http.server import HTTPServer
import json
import os
from pathlib import Path
import time

from external_world.common import JSONHandler


MARKER = Path(os.environ["LIFECYCLE_REQUEST_MARKER"])
RESPONSE_DELAY = float(os.environ.get("LIFECYCLE_RESPONSE_DELAY", "2"))


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class LifecycleModelGatewayHandler(JSONHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {"status": "healthy"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/decision":
            self.send_json(404, {"error": "not_found"})
            return

        request = self.read_json()
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text("worker-reached-model-boundary\n")
        time.sleep(RESPONSE_DELAY)

        message = {
            "role": "assistant",
            "content": canonical_json(
                {
                    "review_score": 60,
                    "reason": "The available evidence supports approval.",
                }
            ),
        }
        self.send_json(
            200,
            {
                "model": "lifecycle-contract-fixture",
                "created_at": "2026-08-19T00:00:00Z",
                "message": message,
                "gateway_response_id": "MODEL-LIFECYCLE-CONTRACT",
                "model_request_sha256": hashlib.sha256(
                    canonical_json(request).encode()
                ).hexdigest(),
            },
        )


def main() -> None:
    port = int(os.environ.get("PORT", "18091"))
    server = HTTPServer(("127.0.0.1", port), LifecycleModelGatewayHandler)
    server.server_name = "lifecycle-model-gateway"
    server.serve_forever()


if __name__ == "__main__":
    main()
