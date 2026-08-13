# Architecture

## Claim

This demo proves:

> A real model response can select a Python path that fails only for one
> historical invocation. Platform telemetry identifies that invocation;
> Retrace preserves and re-enters its execution for deterministic offline
> replay and source-level debugging.

The demo does not claim that OpenTelemetry is unable to retain prompts,
responses, or tool data. The two systems answer different questions:

```text
Microsoft Hosted Agent telemetry
  Which invocation failed?
  What spans, model calls, and status were observed?

Retrace
  What did this Python execution do with those values?
  What were its stack, scopes, locals, and control flow?
  Can the same execution be replayed after the model changes or disappears?
```

## Runtime

```text
operator
  |
  | POST /invocations
  v
Microsoft InvocationAgentServerHost                 not recorded
  |  invocation ID, session ID, OTel span
  |  span attribute: retrace.recording.id
  |
  | launches one sanitized subprocess
  v
retracepython -m worker                             recorded
  |
  | identical HTTP model request
  v
model gateway -> real sampled qwen3:1.7b            external boundary
  |
  | strict JSON: review_score + reason
  v
ordinary Python parsing and routing
  |
  +-- score <65  approve_refund                    succeeds
  +-- score 65-69 request_more_information         None.strip() fails
  +-- score >=70 escalate_specialist               succeeds
```

The Microsoft host is deliberately outside Retrace. It owns long-lived server
lifecycle, concurrency, request identity, observability, and any platform
credentials. A short-lived provider-neutral worker contains only one finite
application invocation. That worker receives an environment allowlist, so
parent secrets do not enter the trace.

## Failure Design

`serial_number=None` is a stable application input. It does not itself force a
failure. The model's genuine sampled score determines whether Python executes
the route that needs that field.

This distinction matters:

```text
same input + score 60 -> approve route -> success
same input + score 65 -> more-information route -> AttributeError
same input + score 75 -> escalation route -> success
```

The failure is therefore model-dependent without asking the model to fail.
The bug is ordinary Python in an application branch, not an injected test
exception and not a hardcoded model response.

## Recording Contract

Every invocation creates:

- one `.retrace` recording,
- one manifest,
- stdout and stderr logs,
- a structured `model_decision_selected` event before branch execution, and
- either `invocation_completed` or `application_failure`.

The structured decision event identifies which failed recording to select and
provides stable verification metadata. It intentionally does not reveal the
bad serial-number value; that value is discovered from historical DAP locals.

The manifest persists failed application invocations as first-class outcomes.
Infrastructure failures still raise at the parent boundary, while a worker
`AttributeError` returns HTTP 500 with a recording ID and preserved failure
metadata.

## Replay Contract

The failed recording is extracted after the model gateway is stopped. Each
replay runs in a new container with:

```text
--network none
--memory 768m
--cpus 1
```

Every replay must match:

- model request hash,
- historical response hash and ID,
- score and reason,
- selected route,
- exception type and message,
- failing traceback line, and
- process exit code.

The model-gateway counter must not change. Replay is not a cached final answer:
the same Python code runs again and Retrace supplies recorded external behavior
at the model HTTP boundary.

## Telemetry Correlation

The Microsoft adapter establishes the invocation identifiers and propagated
OpenTelemetry request context. Inside that context, the handler creates the
application invocation span and annotates it with:

```text
retrace.recording.id
retrace.recording.available
retrace.worker.exit_code
retrace.model.decision
retrace.application.exception.type
```

The local OTLP collector decodes exported protobuf spans to
`generated/telemetry/spans.jsonl`. The proof requires an ERROR span whose
recording ID matches the failed manifest. This is executable evidence that the
platform invocation and Retrace artifact are correlated.

## Debugger Contract

DAP uses the failed recording and stops on:

```python
normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
```

The verifier requires historical values for:

- `raw_model_response`,
- `review_score`,
- `decision_reason`,
- `decision_name`,
- model name, response ID, and hashes,
- `serial_number=None`, and
- the application stack.

It then issues Step Back, verifies movement within the decision function, and
continues forward to the same failure breakpoint. VS Code uses the same DAP
protocol and the same replay binary.

## Proof Versus Presentation

`make run` is the complete stochastic proof. It makes fresh real-model calls
and must discover both a successful route and the rare failed route.

`make presentation` uses a reviewed genuine failed artifact captured by that
proof. It is deterministic and does not require the model. It still validates
the artifact through offline replay and DAP before the visual walkthrough.

This separation avoids making a stage demo depend on a narrow random score
band while preserving the authenticity of the recording.
