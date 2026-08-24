# Retrace Model-Dependent Execution Comparison

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model and Microsoft's Hosted Agent Invocations adapter.

- Identical live application and model input: yes
- Identical worker-request hash: `76769685d134d0b79b5679d6420b8f4dc73ae4ab39be0b3f7f5fef311f8f1992`
- Identical exact model request hash: `8f3d00729a8e1f4f9441847f79bbda3d3d422d6d354eb29ca4e43ad407dc656b`
- Distinct live model decisions: `approve_refund`, `request_more_information`
- Genuine model-selected failure observed: `request_more_information`
- Preserved exception: `AttributeError: 'NoneType' object has no attribute 'strip'`
- Preserved successful route: `approve_refund`
- Every live invocation recorded separately: yes
- Selected failed recording: `/home/runner/work/retrace-model-decision-demo/retrace-model-decision-demo/generated/recordings/selected-failure.retrace`
- Selected successful recording: `/home/runner/work/retrace-model-decision-demo/retrace-model-decision-demo/generated/recordings/selected-success.retrace`
- Offline failed replays: 10 of 10 exact matches
- Offline successful replays: 10 of 10 exact matches
- Model calls during replay: 0
- Docker replay network: disabled
- OTel trace/span, Foundry call/session, and recording manifest correlated: yes
- Failed recording provenance manifest: `/home/runner/work/retrace-model-decision-demo/retrace-model-decision-demo/generated/recordings/selected-failure.proof.json`
- Successful recording provenance manifest: `/home/runner/work/retrace-model-decision-demo/retrace-model-decision-demo/generated/recordings/selected-success.proof.json`
- DAP failure and success stack, scopes, locals and routing checks: passed

## Foundry Trace And Retrace Recording

Foundry protocol 2.0 supplies request-scoped call, user, and session context.
The gateway also forwards W3C trace context. The handler records the active
trace and span IDs with `retrace.recording.id`, producing a direct diagnostic
join from the platform span to the persisted executable artifact.

## Live Model Invocations

The same request and exact model payload were used on every row. The real
sampled model selected the score and route. Only scores from 65 through 69
enter the rare `request_more_information` path, where the latent missing serial
number bug becomes observable.

| Run | Score | Model-selected route | Runtime outcome | Response hash | Recording ID |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 60 | `approve_refund` | completed | `a3d4a75335325576` | `decision-ba79f824-41aa-4374-9d4e-0a4197fb7215` |
| 2 | 65 | `request_more_information` | failed: AttributeError | `58fb485cf20e5ae7` | `decision-50f5dc8f-2863-42da-92fa-f3daf6add69b` |

## Failed Invocation Replayed Offline

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the same historical model score,
route, failing line and exception.

| Replay | Score | Route | Exception | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 2 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 3 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 4 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 5 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 6 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 7 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 8 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 9 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |
| 10 | 65 | `request_more_information` | `AttributeError` | `5a36c66e7829c113` | yes |

## Successful Invocation Replayed Offline

The successful trace has the same application input and model-request hash as
the failed trace. Its historical model response selected a different route,
which completed without reading the missing serial number.

| Replay | Score | Route | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- |
| 1 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 2 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 3 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 4 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 5 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 6 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 7 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 8 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 9 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |
| 10 | 60 | `approve_refund` | `50962f66ff3d17cb` | yes |

## Debugger Evidence

Retrace DAP stopped on the historical `.strip()` failure in
`worker/decision_agent.py`. The failure frame exposed the preserved
`raw_model_response`, score, reason, selected route and `serial_number=None`.
Step Back moved from the exception toward the application routing decision,
then forward execution returned to the same failure without a new inference.

Foundry tells you which agent invocation failed. Retrace lets you re-enter
that exact historical Python execution and debug why.
