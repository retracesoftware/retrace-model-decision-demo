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
  |  Foundry call/user/session context, W3C OTel context
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

The recording, manifest, and logs are published beneath `$HOME/retrace`.
Foundry's current session backend persists `$HOME` across compute
scale-to-zero and exposes session files through its existing API.

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

## Current Foundry Context And Telemetry Correlation

The Foundry protocol 2.0 gateway injects `x-agent-foundry-call-id` and
`x-agent-user-id`, resolves the session, and forwards `traceparent`,
`tracestate`, and `baggage`. The SDK exposes the platform context through
`get_request_context()`. Inside the propagated OTel context, the handler
creates the application invocation span and annotates it with:

```text
retrace.recording.id
retrace.recording.available
retrace.worker.exit_code
retrace.model.decision
retrace.application.exception.type
microsoft.foundry.call_id
microsoft.session.id
```

The local OTLP collector decodes exported protobuf spans to
`generated/telemetry/spans.jsonl`. The proof requires an ERROR span whose
trace ID, span ID, Foundry call ID, session ID, and recording ID match the
persisted manifest. The trace/span pair is the diagnostic join; the call ID is
the platform identity context.

## Session And Shutdown Contract

The demo models the current Hosted Agent session lifecycle:

```text
request enters current protocol 2.0 adapter
  -> one Retrace worker starts
  -> trace is written under $HOME/retrace
  -> worker exits
  -> trace hash is calculated
  -> manifest file and parent directory are fsynced
  -> manifest is atomically published
```

The lifecycle verifier sends `SIGTERM` while the worker is blocked at a
delayed external model boundary. The Microsoft host must drain that in-flight
request before shutdown. The test then stops the model service and executes
the persisted recording. A pass proves that the demo does not publish a
truncated recording at the scale-to-zero boundary.

CI repeats this process five times on Linux/amd64. It uses the released
Retrace packages unchanged.

## Proof Manifest

The selected reviewed artifact has an adjacent provenance manifest containing:

```text
selected recording SHA
original recording ID and SHA
source git SHA and worker-source SHA
Python, Retrace, and DAP versions
Qwen model name and digest
model request and response hashes
Foundry call/user/session context
OTel trace and span IDs
```

Presentation preparation verifies the recording hash before replay or DAP is
started.

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

`make replay-example` uses an architecture-matched, reviewed genuine failed
artifact captured by that proof. It does not require the model. It validates
the artifact through offline replay and DAP before the visual walkthrough.

The bundled replay is an independent convenience path. The fresh-capture path
remains the primary proof that Retrace records a newly observed model-dependent
execution.
