# Retrace Model-Dependent Runtime Failure Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model and Microsoft's Hosted Agent Invocations adapter.

- Identical live application and model input: yes
- Identical exact model request hash: `c6c45a73aa7ae42f60188cdbe69158d83f041d4e65460cbadab379b96a4bbd76`
- Distinct live model decisions: `approve_refund`, `request_more_information`
- Genuine model-selected failure observed: `request_more_information`
- Preserved exception: `AttributeError: 'NoneType' object has no attribute 'strip'`
- Every live invocation recorded separately: yes
- Selected failed recording: `/private/tmp/retrace-model-decision-demo-0.2.26-validation/generated/recordings/selected-failure.retrace`
- Offline failed replays: 10 of 10 exact matches
- Model calls during replay: 0
- Docker replay network: disabled
- Exported OTel failed-invocation span correlated to recording: yes
- DAP failure stack, scopes, locals and reverse navigation: passed

## Foundry Trace And Retrace Recording

Microsoft's adapter assigns an invocation ID and session ID and establishes
the OpenTelemetry request context and exporter. The handler emits an
invocation span and adds the corresponding `retrace.recording.id`. Foundry
telemetry identifies which invocation failed; Retrace turns that invocation
into a deterministic, debuggable artifact.

## Live Model Invocations

The same request and exact model payload were used on every row. The real
sampled model selected the score and route. Only scores from 65 through 69
enter the rare `request_more_information` path, where the latent missing serial
number bug becomes observable.

| Run | Score | Model-selected route | Runtime outcome | Response hash | Recording ID |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | failed: AttributeError | `022d9305d9e77515` | `decision-804aadf0-8353-48b6-84d9-727b79b760c2` |
| 2 | 60 | `approve_refund` | completed | `a9caa2cb37e2eff4` | `decision-64c5e6be-8281-4052-8754-48e8994e4ce9` |

## Failed Invocation Replayed Offline

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the same historical model score,
route, failing line and exception.

| Replay | Score | Route | Exception | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 2 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 3 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 4 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 5 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 6 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 7 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 8 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 9 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |
| 10 | 65 | `request_more_information` | `AttributeError` | `ef37fee4ad661983` | yes |

## Debugger Evidence

Retrace DAP stopped on the historical `.strip()` failure in
`worker/decision_agent.py`. The failure frame exposed the preserved
`raw_model_response`, score, reason, selected route and `serial_number=None`.
Step Back moved from the exception toward the application routing decision,
then forward execution returned to the same failure without a new inference.

Foundry tells you which agent invocation failed. Retrace lets you re-enter
that exact historical Python execution and debug why.
