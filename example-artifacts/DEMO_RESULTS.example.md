# Retrace Nondeterministic Model Decision Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model.

- Identical live application input: yes
- Identical exact model request hash: `c6c45a73aa7ae42f60188cdbe69158d83f041d4e65460cbadab379b96a4bbd76`
- Distinct live model decisions: `approve_refund`, `escalate_specialist`
- Every live invocation recorded separately: yes
- Selected historical recording: `/Users/danielpatrascanu/cookbook/examples/invoice-parser/retrace-demo/model-decision/generated/recordings/selected-decision.retrace`
- Fresh offline replays: 10 of 10 exact matches
- Model calls during replay: 0
- Docker replay network: disabled
- DAP stack, scopes, locals and reverse navigation: passed

## Live Model Decisions

The same Microsoft Responses-compatible request and the same model request were
sent on every row. Different rows are separate real Qwen inferences, not
hardcoded responses or application-side random selection.

| Run | Review score | Application decision | Visible model rationale | Response hash | Recording ID |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 85 | `escalate_specialist` | The refund request is eligible based on the photo evidence of packaging damage and the lack of safety-criticality. The requester has valid account history and no prior refunds. The exclusion of serial number obscuration does not affect refund eligibility. | `0d60257ea13f6edd` | `decision-3cb76e41-a5cb-4d75-9e53-257d8cdcdf07` |
| 2 | 70 | `escalate_specialist` | The refund request is eligible based on the evidence provided. The packaging damage is documented, the accessory is not safety-critical, and the customer has a clean history. However, the partial obscortion of the serial number may affect the authenticity of the claim. A discretionary review is recommended to ensure compliance with quality and safety standards. | `34de1d608f2d5080` | `decision-72396b73-d853-4c45-a07f-c5bf6fd11cff` |
| 3 | 40 | `approve_refund` | The request shows a pattern of carefully crafted claims and incomplete information, while the remaining details (e.g., serial number) could be manipulated. The lack of safety-critical status and the absence of earlier complaints suggest the claim may be staged or misworded. | `d4f5d8547f7e09a3` | `decision-2e7826e4-6efb-46ba-bc5a-07b0bf1b8fae` |

## Selected Historical Decision Replayed Ten Times

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the complete selected output,
including the original decision, rationale, provider timestamp and gateway
response ID.

| Replay | Decision | Historical response ID | Output hash | Exact match |
| ---: | --- | --- | --- | --- |
| 1 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 2 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 3 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 4 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 5 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 6 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 7 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 8 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 9 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |
| 10 | `escalate_specialist` | `MODEL-37E9AC743286` | `e4f597da6b659f99` | yes |

## Debugger Evidence

Retrace DAP replayed the selected recording, stopped in
`worker/decision_agent.py`, and inspected the historical `raw_model_response`,
`review_score`, `decision_name`, `decision_reason`, `model_name`,
`gateway_response_id`, request hash and response hash. Step Back moved within
the decision function and
forward replay returned to the same decision point.

## Honest Scope

The demo captures the model's externally visible assessment and its concise
rationale. It does not claim to expose private hidden chain-of-thought.
The proof is that a nondeterministic external model decision does not disappear
after production moves on: Retrace preserves that exact invocation for offline,
repeatable replay and debugging.
