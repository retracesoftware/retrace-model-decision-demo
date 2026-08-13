from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)


OUTPUT = Path(os.environ.get("OTEL_OUTPUT", "/app/generated/telemetry/spans.jsonl"))


def _value(value: Any) -> Any:
    kind = value.WhichOneof("value")
    if kind == "array_value":
        return [_value(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return {item.key: _value(item.value) for item in value.kvlist_value.values}
    return getattr(value, kind) if kind else None


def decode_spans(payload: bytes) -> list[dict[str, Any]]:
    request = ExportTraceServiceRequest()
    request.ParseFromString(payload)
    decoded = []
    for resource_spans in request.resource_spans:
        resource = {
            item.key: _value(item.value) for item in resource_spans.resource.attributes
        }
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                decoded.append(
                    {
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                        "name": span.name,
                        "status_code": int(span.status.code),
                        "status_message": span.status.message,
                        "attributes": {
                            item.key: _value(item.value) for item in span.attributes
                        },
                        "resource": resource,
                    }
                )
    return decoded


class CollectorHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        print(f"otel-collector: {format % args}", flush=True)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        if self.path == "/v1/traces":
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            with OUTPUT.open("a") as stream:
                for span in decode_spans(payload):
                    stream.write(json.dumps(span, sort_keys=True) + "\n")
            response = ExportTraceServiceResponse().SerializeToString()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main() -> None:
    port = int(os.environ.get("PORT", "4318"))
    HTTPServer(("0.0.0.0", port), CollectorHandler).serve_forever()


if __name__ == "__main__":
    main()
