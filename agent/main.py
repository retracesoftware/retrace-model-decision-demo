from __future__ import annotations

import asyncio

from azure.ai.agentserver.core import get_request_context
from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)

from agent.invocation_runner import run_recorded_invocation
from scripts.demo_state import CASE


app = ResponsesAgentServerHost()
INVOCATION_LOCK = asyncio.Lock()


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    user_input = await context.get_input_text() or ""
    request_context = get_request_context()
    request_payload = {**CASE, "user_prompt": user_input}
    async with INVOCATION_LOCK:
        result = await run_recorded_invocation(
            request_payload=request_payload,
            foundry_context={
                "call_id": request_context.call_id,
                "user_id": request_context.user_id,
                "session_id": request_context.session_id,
            },
            cancellation_signal=cancellation_signal,
        )
    return TextResponse(context, request, text=json_text(result.output))


def json_text(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


if __name__ == "__main__":
    app.run()
