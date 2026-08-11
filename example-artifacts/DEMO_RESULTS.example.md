# Retrace Nondeterministic Model Decision Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model.

- Identical live application input: yes
- Identical exact model request hash: `c6c45a73aa7ae42f60188cdbe69158d83f041d4e65460cbadab379b96a4bbd76`
- Distinct live model decisions: `escalate_specialist`, `request_more_information`
- Every live invocation recorded separately: yes
- Selected historical recording: `example-artifacts/selected-decision.retrace`
- Fresh offline replays: 10 of 10 exact matches
- Model calls during replay: 0
- Docker replay network: disabled
- DAP stack, scopes, locals and reverse navigation: passed

## Live Model Decisions

The same agent request and the same model request were sent on every row.
Different rows are separate real Qwen inferences, not hardcoded responses or
application-side random selection.

| Run | Review score | Application decision | Visible model rationale | Response hash | Recording ID |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | The request is appropriately initiated within the self-service window, the damage is documented with a photo, and the customer has a clean account history. The accessory is not safety-critical, and the damage does not meet the threshold for a full refund. A discretionary review score of 65 is appropriate, as the case is borderline and requires expert evaluation for final determination. | `1078a65d89dd79df` | `decision-bb080474-1347-4e0b-99c8-3173ce3052c6` |
| 2 | 65 | `request_more_information` | The request presents a borderline scenario. The photo provides sufficient evidence of damaged packaging, and the user has a clean history. However, the obscured serial number could complicate verification. Since there is no evidence of a safety-critical issue, the refund can be processed based on current evidence. A discretionary review score of 65 is appropriate. | `d7ecf65d796407c2` | `decision-3b963bcb-2dc8-4acb-9cbe-fdcfaedfc00c` |
| 3 | 65 | `request_more_information` | The refund request is valid under self-service policies, the damage is evident in the photo, and the accessory is non-safety-critical. The case is borderline but suitable for immediate approval with a discretionary review score of 65. | `c002366ce1ccd86a` | `decision-b8e7a8bf-0806-474e-aaf4-47f78fb327f8` |
| 4 | 78 | `escalate_specialist` | The customer’s request reflects a legitimate claim for a refund due to damaged goods. The photo provides substantial evidence of packaging damage, and the account history demonstrates trustworthiness. While the serial number’s partial obstruction may slightly hinder verification, the damage is manifest and the product is not safety-critical. The issue is straightforward and within the standard refund process. The customer’s account history reinforces the likelihood of a justified claim. | `2bac412a74e5b268` | `decision-58427c39-e534-4282-819a-58ac6f4a7216` |

## Selected Historical Decision Replayed Ten Times

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the complete selected output,
including the original decision, rationale, provider timestamp and gateway
response ID.

| Replay | Decision | Historical response ID | Output hash | Exact match |
| ---: | --- | --- | --- | --- |
| 1 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 2 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 3 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 4 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 5 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 6 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 7 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 8 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 9 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |
| 10 | `request_more_information` | `MODEL-932DCB4032D4` | `64311a1d9caf4389` | yes |

## Debugger Evidence

Retrace DAP replayed the selected recording, stopped in
`worker/decision_agent.py`, and inspected the historical `raw_model_response`,
`review_score`, `decision_name`, `decision_reason`, `model_name`,
`gateway_response_id`, request hash and response hash. Step Back moved within
the decision function and
forward replay returned to the same decision point.

Retrace preserves the selected model invocation for exact offline replay and
repeatable debugging after production has moved on.
