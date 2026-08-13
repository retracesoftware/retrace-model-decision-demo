# Retrace Model-Dependent Runtime Failure Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`qwen3:1.7b` model and Microsoft's Hosted Agent Invocations adapter.

- Identical live application and model input: yes
- Identical exact model request hash: `c6c45a73aa7ae42f60188cdbe69158d83f041d4e65460cbadab379b96a4bbd76`
- Distinct live model decisions: `approve_refund`, `escalate_specialist`, `request_more_information`
- Genuine model-selected failure observed: `request_more_information`
- Preserved exception: `AttributeError: 'NoneType' object has no attribute 'strip'`
- Every live invocation recorded separately: yes
- Selected failed recording: `/Users/danielpatrascanu/retrace-model-decision-demo/generated/recordings/selected-failure.retrace`
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
| 1 | 70 | `escalate_specialist` | completed | `1a8708fddafef81d` | `decision-256f5a6e-3471-44a8-a69a-20e2737d9dc9` |
| 2 | 60 | `approve_refund` | completed | `ee3b2eefe70a17b6` | `decision-352e7f89-a2ce-4a4b-9ef6-fae3df174ea8` |
| 3 | 65 | `request_more_information` | failed: AttributeError | `5e4158b7d345be7e` | `decision-252df1a8-e6e1-4180-93c0-f6b480581d2c` |

## Failed Invocation Replayed Offline

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the same historical model score,
route, failing line and exception.

| Replay | Score | Route | Exception | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- | --- |
| 1 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 2 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 3 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 4 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 5 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 6 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 7 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 8 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 9 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |
| 10 | 65 | `request_more_information` | `AttributeError` | `e9a3c670c9fac706` | yes |

## Debugger Evidence

Retrace DAP stopped on the historical `.strip()` failure in
`worker/decision_agent.py`. The failure frame exposed the preserved
`raw_model_response`, score, reason, selected route and `serial_number=None`.
Step Back moved from the exception toward the application routing decision,
then forward execution returned to the same failure without a new inference.

Foundry tells you which agent invocation failed. Retrace lets you re-enter
that exact historical Python execution and debug why.
