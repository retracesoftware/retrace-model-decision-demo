from __future__ import annotations

import asyncio
import os
from typing import Any

from azure.ai.agentserver.core import flush_spans
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agent.invocation_runner import InvocationResult, run_recorded_invocation
from scripts.demo_state import CASE


app = InvocationAgentServerHost()
tracer = trace.get_tracer("Azure.AI.AgentServer.Invocations")


def _response_payload(
    result: InvocationResult,
    *,
    platform_invocation_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invocation_id": platform_invocation_id,
        "recording_id": result.recording_id,
        "recording_available": True,
        "decision": result.decision,
    }
    if result.succeeded:
        payload.update({"status": "completed", "output": result.output})
    else:
        payload.update({"status": "failed", "error": result.failure})
    return payload


def _annotate_invocation_span(span: trace.Span, result: InvocationResult) -> None:
    if not span.is_recording():
        return
    span.set_attribute("retrace.recording.id", result.recording_id)
    span.set_attribute("retrace.recording.available", True)
    span.set_attribute("retrace.worker.exit_code", result.worker_exit_code)
    span.set_attribute("retrace.model.decision", str(result.decision["decision"]))
    if not result.succeeded and result.failure:
        message = str(result.failure["exception_message"])
        span.set_status(Status(StatusCode.ERROR, message))
        span.set_attribute(
            "retrace.application.exception.type",
            str(result.failure["exception_type"]),
        )


@app.invoke_handler
async def invoke(request: Request) -> Response:
    body = await request.json()
    user_input = body.get("input")
    if not isinstance(user_input, str) or not user_input.strip():
        return JSONResponse(
            {"error": "input must be nonempty text"},
            status_code=400,
        )

    agent_name = os.environ.get("FOUNDRY_AGENT_NAME", "retrace-model-decision-demo")
    agent_version = os.environ.get("FOUNDRY_AGENT_VERSION", "1.0")
    with tracer.start_as_current_span(
        f"invoke_agent {agent_name}:{agent_version}"
    ) as span:
        span.set_attribute("gen_ai.system", "azure.ai.agentserver")
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.response.id", request.state.invocation_id)
        span.set_attribute("microsoft.session.id", request.state.session_id)
        result = await run_recorded_invocation(
            request_payload={**CASE, "user_prompt": user_input},
            request_context={
                "request_id": request.state.invocation_id,
                "session_id": request.state.session_id,
                "user_id": request.state.user_id or None,
            },
            cancellation_signal=asyncio.Event(),
        )
        _annotate_invocation_span(span, result)
    flush_spans()
    return JSONResponse(
        _response_payload(
            result,
            platform_invocation_id=request.state.invocation_id,
        ),
        status_code=200 if result.succeeded else 500,
    )


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
