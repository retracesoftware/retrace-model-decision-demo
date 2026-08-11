from __future__ import annotations

import hashlib
from http.server import HTTPServer
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from external_world.common import JSONHandler, record_request


OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:1.7b")
SAMPLING_OPTIONS = {
    "temperature": 1.7,
    "top_p": 1.0,
    "top_k": 100,
    "num_predict": 160,
}


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sha256_json(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def ollama_json(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    request = Request(
        f"{OLLAMA_URL.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urlopen(request, timeout=120) as response:
        return json.load(response)


def model_is_ready() -> bool:
    tags = ollama_json("/api/tags")
    names = {str(item.get("name")) for item in tags.get("models", [])}
    return OLLAMA_MODEL in names


class ModelGatewayHandler(JSONHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            try:
                ready = model_is_ready()
            except (HTTPError, URLError, TimeoutError, ValueError):
                ready = False
            self.send_json(
                200 if ready else 503,
                {
                    "status": "healthy" if ready else "unavailable",
                    "provider": "ollama",
                    "model": OLLAMA_MODEL,
                },
            )
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/v1/decision":
            self.send_json(404, {"error": "not_found"})
            return

        request = self.read_json()
        ollama_request = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "think": False,
            "messages": request["messages"],
            "format": request["format"],
            "options": SAMPLING_OPTIONS,
        }
        request_sha256 = sha256_json(ollama_request)
        try:
            response = ollama_json("/api/chat", ollama_request)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            self.send_json(
                502,
                {
                    "error": "model_provider_failed",
                    "provider": "ollama",
                    "model": OLLAMA_MODEL,
                    "detail": str(error),
                },
            )
            return

        gateway_response_id = f"MODEL-{uuid.uuid4().hex[:12].upper()}"
        response.update(
            {
                "provider": "ollama",
                "gateway_response_id": gateway_response_id,
                "model_request_sha256": request_sha256,
                "sampling_options": SAMPLING_OPTIONS,
            }
        )
        record_request(
            {
                "gateway_response_id": gateway_response_id,
                "model_request_sha256": request_sha256,
                "model": response.get("model"),
                "created_at": response.get("created_at"),
                "sampling_options": SAMPLING_OPTIONS,
                "request": request,
                "message": response.get("message"),
            }
        )
        self.send_json(200, response)


def main() -> None:
    port = int(os.environ.get("PORT", "8091"))
    server = HTTPServer(("0.0.0.0", port), ModelGatewayHandler)
    server.server_name = "model-gateway"
    print(f"model-gateway listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
