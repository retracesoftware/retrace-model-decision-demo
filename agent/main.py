from __future__ import annotations

import asyncio
import os
from typing import Any

from azure.ai.agentserver.core import flush_spans, get_request_context
from azure.ai.agentserver.invocations import InvocationAgentServerHost
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from agent.invocation_runner import InvocationResult, run_recorded_invocation
from scripts.demo_state import CASE


app = InvocationAgentServerHost()
tracer = trace.get_tracer("Azure.AI.AgentServer.Invocations")


def _otel_ids(span: trace.Span) -> tuple[str | None, str | None]:
    context = span.get_span_context()
    if not context.is_valid:
        return None, None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def _response_payload(
    result: InvocationResult,
    *,
    foundry_call_id: str | None,
    session_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recording_id": result.recording_id,
        "recording_available": True,
        "foundry_call_id": foundry_call_id,
        "session_id": session_id,
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
    foundry_context = get_request_context()
    with tracer.start_as_current_span(
        f"invoke_agent {agent_name}:{agent_version}"
    ) as span:
        trace_id, span_id = _otel_ids(span)
        span.set_attribute("gen_ai.system", "azure.ai.agentserver")
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        if foundry_context.call_id:
            span.set_attribute("microsoft.foundry.call_id", foundry_context.call_id)
        if foundry_context.session_id:
            span.set_attribute("microsoft.session.id", foundry_context.session_id)
        result = await run_recorded_invocation(
            request_payload={**CASE, "user_prompt": user_input},
            request_context={
                "foundry_call_id": foundry_context.call_id,
                "session_id": foundry_context.session_id,
                "user_id": foundry_context.user_id,
                "trace_id": trace_id,
                "span_id": span_id,
                "protocol_invocation_id": request.state.invocation_id,
            },
            cancellation_signal=asyncio.Event(),
        )
        _annotate_invocation_span(span, result)
    flush_spans()
    return JSONResponse(
        _response_payload(
            result,
            foundry_call_id=foundry_context.call_id,
            session_id=foundry_context.session_id,
        ),
        status_code=200 if result.succeeded else 500,
    )


@app.shutdown_handler
async def shutdown() -> None:
    flush_spans()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
