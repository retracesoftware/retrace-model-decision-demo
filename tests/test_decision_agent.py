from __future__ import annotations

import json

import pytest

from scripts.demo_state import CASE
from worker.decision_agent import (
    model_messages,
    parse_model_assessment,
    route_review_score,
    run_decision_agent,
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


def complete_model_response(score: int) -> dict:
    return {
        **model_response(score),
        "model": "qwen3:1.7b",
        "created_at": "2026-08-13T10:00:00Z",
        "gateway_response_id": "MODEL-TEST",
        "model_request_sha256": "a" * 64,
    }


@pytest.mark.parametrize("score", [0, 64, 70, 100])
def test_common_model_routes_complete_with_missing_serial_number(
    monkeypatch,
    score: int,
) -> None:
    monkeypatch.setattr(
        "worker.decision_agent.request_model_decision",
        lambda **kwargs: complete_model_response(score),
    )

    result = run_decision_agent(CASE)

    assert result["decision"] == route_review_score(score)
    assert result["action_detail"]


@pytest.mark.parametrize("score", [65, 67, 69])
def test_model_selected_information_route_exposes_runtime_only_bug(
    monkeypatch,
    score: int,
    capsys,
) -> None:
    monkeypatch.setattr(
        "worker.decision_agent.request_model_decision",
        lambda **kwargs: complete_model_response(score),
    )

    with pytest.raises(AttributeError, match="has no attribute 'strip'"):
        run_decision_agent(CASE)

    decision = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert decision["event"] == "model_decision_selected"
    assert decision["review_score"] == score
    assert decision["decision"] == "request_more_information"
    assert "serial_number" not in decision
