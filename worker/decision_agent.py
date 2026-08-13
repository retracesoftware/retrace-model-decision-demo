from __future__ import annotations

import hashlib
import json
from typing import Any

from worker.model_client import request_model_decision


DECISION_SCHEMA = {
    "type": "object",
    "required": ["review_score", "reason"],
    "additionalProperties": False,
    "properties": {
        "review_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": {"type": "string"},
    },
}


def model_messages(request: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a senior support agent. Assign a discretionary review "
                "score from 0 to 100 to this genuinely borderline case, where "
                "lower means approve now and higher means specialist review. "
                "There is no policy-mandated score and reasonable experts can "
                "score it differently. Use your judgment. Return only JSON with "
                "review_score and one concise customer-facing reason."
            ),
        },
        {"role": "user", "content": request["user_prompt"]},
    ]


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_model_assessment(response: dict[str, Any]) -> tuple[int, str]:
    message = response.get("message")
    if not isinstance(message, dict):
        raise ValueError(f"model response omitted message: {response!r}")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError(f"model response content must be text: {content!r}")
    try:
        assessment = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"model response was not valid JSON: {content!r}") from error
    if not isinstance(assessment, dict):
        raise ValueError(f"model assessment must be an object: {assessment!r}")
    if set(assessment) != {"review_score", "reason"}:
        raise ValueError(f"model assessment has unexpected fields: {assessment!r}")
    review_score = assessment["review_score"]
    if isinstance(review_score, bool) or not isinstance(review_score, int):
        raise ValueError(f"review_score must be an integer: {review_score!r}")
    if not 0 <= review_score <= 100:
        raise ValueError(f"review_score is out of range: {review_score!r}")
    decision_reason = str(assessment["reason"]).strip()
    if not decision_reason:
        raise ValueError("model assessment omitted its visible reason")
    return review_score, decision_reason


def route_review_score(review_score: int) -> str:
    if review_score < 65:
        return "approve_refund"
    if review_score < 70:
        return "request_more_information"
    return "escalate_specialist"


def run_decision_agent(request: dict[str, Any]) -> dict[str, Any]:
    messages = model_messages(request)
    raw_model_response = request_model_decision(
        messages=messages,
        response_format=DECISION_SCHEMA,
    )
    review_score, decision_reason = parse_model_assessment(raw_model_response)
    decision_name = route_review_score(review_score)
    model_name = str(raw_model_response["model"])
    model_created_at = str(raw_model_response["created_at"])
    gateway_response_id = str(raw_model_response["gateway_response_id"])
    model_request_sha256 = str(raw_model_response["model_request_sha256"])
    model_response_sha256 = hashlib.sha256(
        canonical_json(raw_model_response["message"]).encode()
    ).hexdigest()
    decision_evidence = {
        "review_score": review_score,
        "decision": decision_name,
        "reason": decision_reason,
        "model": model_name,
        "created_at": model_created_at,
        "gateway_response_id": gateway_response_id,
        "model_request_sha256": model_request_sha256,
        "model_response_sha256": model_response_sha256,
    }
    print(
        canonical_json(
            {
                "event": "model_decision_selected",
                "case_id": request["case_id"],
                **decision_evidence,
            }
        ),
        flush=True,
    )

    if decision_name == "approve_refund":  # RETRACE_MODEL_ROUTE_BREAKPOINT
        action_detail = "refund approved from the available evidence"
    elif decision_name == "request_more_information":
        serial_number = request["serial_number"]
        normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
        action_detail = f"request a clearer image of {normalized}"
    else:
        action_detail = "send the case to a regulated-equipment specialist"

    return {
        "case_id": request["case_id"],
        **decision_evidence,
        "action_detail": action_detail,
    }
