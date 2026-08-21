# Retrace Model-Dependent Runtime Failure Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model and Microsoft's Hosted Agent Invocations adapter.

- Identical live application and model input: yes
- Identical exact model request hash: `c6c45a73aa7ae42f60188cdbe69158d83f041d4e65460cbadab379b96a4bbd76`
- Distinct live model decisions: `escalate_specialist`, `request_more_information`
- Genuine model-selected failure observed: `request_more_information`
- Preserved exception: `AttributeError: 'NoneType' object has no attribute 'strip'`
- Every live invocation recorded separately: yes
- Selected failed recording: `/home/runner/work/retrace-model-decision-demo/retrace-model-decision-demo/generated/recordings/selected-failure.retrace`
- Offline failed replays: 10 of 10 exact matches
- Model calls during replay: 0
- Docker replay network: disabled
- OTel trace/span, Foundry call/session, and recording manifest correlated: yes
- Verifiable recording provenance manifest: `/home/runner/work/retrace-model-decision-demo/retrace-model-decision-demo/generated/recordings/selected-failure.proof.json`
- DAP failure stack, scopes, locals and reverse navigation: passed

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
| 1 | 65 | `request_more_information` | failed: AttributeError | `f6fdbb7582a74144` | `decision-dca36e61-53ea-41b1-9092-55fedcb6d24b` |
| 2 | 75 | `escalate_specialist` | completed | `bf889fff6f9b14ca` | `decision-fa1d57d9-53b7-4bc4-a694-210f980467bc` |

## Failed Invocation Replayed Offline

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the same historical model score,
route, failing line and exception.

| Replay | Score | Route | Exception | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 2 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 3 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 4 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 5 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 6 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 7 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 8 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 9 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |
| 10 | 65 | `request_more_information` | `AttributeError` | `35a60ec1168a2369` | yes |

## Debugger Evidence

Retrace DAP stopped on the historical `.strip()` failure in
`worker/decision_agent.py`. The failure frame exposed the preserved
`raw_model_response`, score, reason, selected route and `serial_number=None`.
Step Back moved from the exception toward the application routing decision,
then forward execution returned to the same failure without a new inference.

Foundry tells you which agent invocation failed. Retrace lets you re-enter
that exact historical Python execution and debug why.
