# Retrace Model-Dependent Execution Comparison

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model and Microsoft's Hosted Agent Invocations adapter.

- Identical live application and model input: yes
- Identical worker-request hash: `76769685d134d0b79b5679d6420b8f4dc73ae4ab39be0b3f7f5fef311f8f1992`
- Identical exact model request hash: `8f3d00729a8e1f4f9441847f79bbda3d3d422d6d354eb29ca4e43ad407dc656b`
- Distinct live model decisions: `escalate_specialist`, `request_more_information`
- Genuine model-selected failure observed: `request_more_information`
- Preserved exception: `AttributeError: 'NoneType' object has no attribute 'strip'`
- Preserved successful route: `escalate_specialist`
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
| 1 | 70 | `escalate_specialist` | completed | `0cd37b5728ecf397` | `decision-b2799298-978f-4d41-853d-3f3d641c2537` |
| 2 | 65 | `request_more_information` | failed: AttributeError | `6de7e269111b0a38` | `decision-9478d396-44c1-4b88-b455-3cc8ebd19e43` |

## Failed Invocation Replayed Offline

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the same historical model score,
route, failing line and exception.

| Replay | Score | Route | Exception | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 2 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 3 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 4 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 5 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 6 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 7 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 8 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 9 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |
| 10 | 65 | `request_more_information` | `AttributeError` | `926a9534a0667a97` | yes |

## Successful Invocation Replayed Offline

The successful trace has the same application input and model-request hash as
the failed trace. Its historical model response selected a different route,
which completed without reading the missing serial number.

| Replay | Score | Route | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- |
| 1 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 2 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 3 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 4 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 5 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 6 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 7 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 8 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 9 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |
| 10 | 70 | `escalate_specialist` | `a50c40d47ba88013` | yes |

## Debugger Evidence

Retrace DAP stopped on the historical `.strip()` failure in
`worker/decision_agent.py`. The failure frame exposed the preserved
`raw_model_response`, score, reason, selected route and `serial_number=None`.
Step Back moved from the exception toward the application routing decision,
then forward execution returned to the same failure without a new inference.

Foundry tells you which agent invocation failed. Retrace lets you re-enter
that exact historical Python execution and debug why.
