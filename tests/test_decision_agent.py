from __future__ import annotations

import json

import pytest

from scripts.demo_state import CASE
from worker.decision_agent import (
    model_messages,
    parse_model_assessment,
    route_review_score,
)


def model_response(score: object, reason: object = "Visible reason") -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": json.dumps({"review_score": score, "reason": reason}),
        }
    }


@pytest.mark.parametrize(
    "score, expected",
    [
        (0, "approve_refund"),
        (64, "approve_refund"),
        (65, "request_more_information"),
        (69, "request_more_information"),
        (70, "escalate_specialist"),
        (100, "escalate_specialist"),
    ],
)
def test_review_score_routes_to_application_decision(
    score: int,
    expected: str,
) -> None:
    assert route_review_score(score) == expected


def test_parse_model_assessment_returns_score_and_visible_reason() -> None:
    assert parse_model_assessment(model_response(72)) == (72, "Visible reason")


@pytest.mark.parametrize(
    "response, match",
    [
        ({"message": {"content": "not-json"}}, "valid JSON"),
        (model_response(True), "integer"),
        (model_response(101), "out of range"),
        (model_response(65, ""), "omitted"),
        (
            {
                "message": {
                    "content": json.dumps(
                        {"review_score": 65, "reason": "ok", "extra": "bad"}
                    )
                }
            },
            "unexpected fields",
        ),
    ],
)
def test_parse_model_assessment_rejects_invalid_model_output(
    response: dict,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        parse_model_assessment(response)


def test_model_input_is_stable_and_describes_a_discretionary_score() -> None:
    request = {**CASE, "user_prompt": CASE["user_prompt"]}
    first = model_messages(request)
    second = model_messages(request)
    assert first == second
    assert first[1]["content"] == CASE["user_prompt"]
    assert "no policy-mandated score" in first[0]["content"]
