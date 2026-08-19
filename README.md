# Retrace Model-Dependent Failure Demo

This demo shows how Retrace complements agent telemetry by turning one
historical AI invocation into a deterministic, debuggable Python execution.

A real sampled language model reviews the same borderline refund request on
every live invocation. Its score selects one of three ordinary Python routes:

```text
score below 65  -> approve_refund              -> succeeds
score 65-69     -> request_more_information    -> rare runtime failure
score 70+       -> escalate_specialist         -> succeeds
```

The input has no serial number. That is harmless on the common approval and
escalation routes. When the model selects `request_more_information`, Python
tries to normalize the missing value and raises:

```text
AttributeError: 'NoneType' object has no attribute 'strip'
```

The model is not instructed to fail and no response is hardcoded. Sampling
causes real model responses to vary; deterministic application code maps the
returned score to the route. Retrace records every worker invocation,
preserves the failed one, replays it after the model is stopped, and lets VS
Code inspect the original response, score, route, missing value, and failing
statement.

## The Core Message

Foundry's OpenTelemetry trace can identify the failed invocation and retain
model/tool telemetry. Retrace answers the next debugging question:

> What exactly did the Python application do with that historical response?

The demo uses Microsoft's Hosted Agent container protocol 2.0 through the
production Invocations adapter. Foundry injects `call_id`, `user_id`, and
`session_id`; the SDK exposes them through `get_request_context()`. Foundry
also forwards W3C `traceparent`, `tracestate`, and `baggage`. The application
therefore joins its `.retrace` artifact to the active OTel trace and span with:

```text
recording_id + trace_id + span_id + foundry_call_id + session_id
```

The trace/span IDs are the diagnostic join. The Foundry call ID records the
platform identity context. The local harness supplies the same platform
headers that the real Foundry gateway injects; application callers do not
invent a custom invocation header.

Then Retrace:

1. re-executes the original Python path,
2. supplies the recorded model-boundary result instead of calling the model,
3. reproduces the same route, failure, and exit code,
4. exposes historical stack, scopes, and locals through DAP, and
5. supports reverse navigation toward the routing decision.

The exact positioning is:

> Foundry tells you which agent invocation failed. Retrace lets you re-enter
> that exact historical Python execution and debug why.

## Two Workflows

The repository intentionally separates engineering proof from presentation.

### Presentation workflow

```bash
make presentation
```

This uses a reviewed **genuine failed recording** captured from the real Qwen
workflow. It does not call Ollama. It:

1. copies the reviewed failed trace into `generated/`,
2. extracts it,
3. replays it three times with Docker networking disabled,
4. requires the same score, route, exception, exit code, and traceback,
5. verifies DAP stack, scopes, locals, Step Back, and forward return, and
6. verifies the recording's provenance manifest, and
7. creates the workspace used by the VS Code walkthrough.

This is the reliable stage path. The recording is not fabricated; it is a
reviewed artifact from the complete live proof below.

### Complete live proof

```bash
make run
```

This starts the real model and captures fresh invocations. It is the deeper
engineering validation path and deliberately depends on genuine sampling.

## Requirements

For presentation mode:

- Git
- Docker Desktop or Docker Engine with Docker Compose
- VS Code
- the VS Code Dev Containers extension

For the complete live proof, also install [Ollama](https://ollama.com/).

The image is pinned to:

```text
Debian Bookworm, Linux/amd64
Python 3.12.13
retracesoftware==0.2.26
retracesoftware-dap==0.2.26
azure-ai-agentserver-invocations==1.0.0
qwen3:1.7b, pinned digest for live mode
```

Python, Retrace, and the Microsoft adapter run inside Docker. They do not need
to be installed on the host.

## Get The Demo

```bash
git clone https://github.com/retracesoftware/retrace-model-decision-demo.git
cd retrace-model-decision-demo
```

Install the Dev Containers extension if needed:

```bash
code --install-extension ms-vscode-remote.remote-containers
```

## Reliable Presentation Walkthrough

Prepare this workflow before the meeting. Do not build the image or reopen the
Dev Container while screen sharing. Leave these three views ready:

1. `generated/DEMO_RESULTS.md` at the failed invocation and recording ID.
2. A terminal showing the verified recording SHA plus the
   `network=none match=yes` replay lines.
3. VS Code already connected to the Dev Container, with the historical source
   and Retrace sidebar open.

The live action is entering the prepared historical execution, inspecting its
locals, and using Step Back.

### 1. Prepare and verify the historical failure

Make sure Docker is running, then execute:

```bash
make presentation
```

Expected evidence includes:

```text
presentation=reviewed-genuine-failed-invocation
historical_model=score:65 route:request_more_information
historical_failure=AttributeError: 'NoneType' object has no attribute 'strip'
replay=01 ... network=none match=yes
replay=02 ... network=none match=yes
replay=03 ... network=none match=yes
dap=pass ... serial_number=None ...
proof=pass ... trace_id=... span_id=...
presentation=ready
```

This expected `AttributeError` is the incident being demonstrated. A green
presentation preparation reproduces it and verifies its debugger state.

### 2. Show the evidence summary

```bash
code generated/DEMO_RESULTS.md
```

The report shows the original real-model invocations: identical request hash,
different scores, successful neighboring routes, the failed route, the
recording ID, ten network-disabled replay matches, and DAP verification. The
adjacent proof manifest binds the selected recording SHA to the source commit,
model digest, model request/response hashes, Foundry context, and OTel span.

### 3. Open VS Code

```bash
code .
```

Open the Command Palette and select:

```text
Dev Containers: Reopen in Container
```

VS Code remains on the host. The workspace, source, Python 3.12 runtime,
recording, Retrace extension, replay binary, and DAP adapter run inside the
container at `/app`.

The Dev Container automatically:

- installs `RetraceSoftware.retrace-debug-extension` remotely,
- selects `/app/generated/recordings/selected-failure.retrace`,
- copies the reviewed artifact when no fresh artifact exists,
- extracts and indexes the recording,
- generates its `.code-workspace`, and
- runs the automated DAP preflight.

### 4. Set the failure breakpoint

Open:

```text
/app/worker/decision_agent.py
```

Find:

```python
normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
```

Set a breakpoint on that statement.

This point was chosen because all evidence is present together:

- the original raw model response,
- the parsed review score and reason,
- the model-selected route,
- provider metadata and hashes,
- the runtime `serial_number=None`, and
- the exact operation that fails.

### 5. Start replay debugging

1. Click the Retrace icon in the left activity bar.
2. Find the Python process under `selected-failure.retrace`.
3. Click Play next to that process.
4. Wait for breakpoint scanning to finish.
5. Replay stops directly on `RETRACE_MODEL_FAILURE_BREAKPOINT`.

The automated DAP preflight verifies that the breakpoint is discoverable and
that the historical stack, scopes, locals, Step Back, and forward return all
work before VS Code is opened.

### 6. Inspect historical runtime state

Open Run and Debug, then inspect Variables and Locals:

```text
raw_model_response
review_score
decision_reason
decision_name
model_name
model_created_at
gateway_response_id
model_request_sha256
model_response_sha256
serial_number
```

The important chain is:

```text
real model returned score 65
-> Python selected request_more_information
-> serial_number was None
-> .strip() raised AttributeError
```

The debugger does not request a new inference. It is inspecting the recorded
model result and re-executed historical Python path.

### 7. Time travel

Use Step Back to move from the failing operation toward score routing. Then
use Continue or Step Over to move forward to the same failure again. Also show
Call Stack, Scopes, and Locals.

The closing line is:

> The platform trace identifies the failed invocation. Retrace preserves the
> execution behind it, reproduces it without the model, and lets us debug the
> historical Python state as code.

## Complete Live Proof

Start Ollama:

```bash
ollama serve
```

In another terminal, run:

```bash
make run
```

The first run downloads the pinned Qwen model and builds the image. The proof:

1. verifies Docker and the pinned model digest,
2. starts Microsoft's Invocations host at port `8088`,
3. starts a real Ollama model gateway,
4. starts a local OTLP collector,
5. sends identical `POST /invocations` requests,
6. launches one sanitized `retracepython` worker per request,
7. requires identical model-request hashes,
8. continues until it has both a successful route and the rare failed route,
9. preserves every invocation under the session's `$HOME/retrace` directory,
10. exports and verifies the OTel trace/span/recording correlation,
11. stops the model gateway,
12. replays the failed invocation ten times under `--network none`,
13. requires the same score, route, exception, exit code, and traceback,
14. proves the model-call counter does not change during replay,
15. verifies DAP historical locals and reverse navigation, and
16. writes a human-readable report, machine-readable run summary, and
    provenance manifest.

The full proof runs each service at or below 1 CPU and 1 GiB. Offline replay
is separately constrained to 1 CPU and 768 MiB. CI exercises the actual
recording, replay, DAP, and shutdown paths under those limits; these are
correctness/resource-fit checks, not latency benchmarks.

Live sampling is real, so the number of calls varies. The harness allows at
most 20 identical calls and fails instead of manufacturing a response.

## Generated Evidence

After `make run`:

```text
generated/DEMO_RESULTS.md
generated/run-summary.json
generated/recordings/selected-failure.retrace
generated/recordings/selected-failure.expected.json
generated/recordings/selected-failure.proof.json
generated/recordings/selected-failure.code-workspace
generated/session-home/retrace/recordings/*.retrace
generated/session-home/retrace/manifests/*.json
generated/session-home/retrace/logs/*.log
generated/invocations/live-*.json
generated/replay/replay-*.log
generated/telemetry/spans.jsonl
generated/transcripts/dap.json
generated/counters/model-gateway.json
```

`run-summary.json` contains the complete proof, including the failed exported
span. `spans.jsonl` is decoded OTLP data emitted by Microsoft's host. The
failed span and persisted invocation manifest share the same trace ID, span ID,
Foundry call ID, session ID, and `retrace.recording.id`.

## Foundry Session Persistence

Hosted Agent sessions persist `$HOME` and `/files` when compute scales to
zero. The demo models that directly by setting:

```text
HOME=/app/generated/session-home
```

Each invocation publishes its artifacts atomically beneath:

```text
$HOME/retrace/recordings/
$HOME/retrace/manifests/
$HOME/retrace/logs/
```

In Foundry, the recording can therefore survive scale-to-zero in the existing
session filesystem and be retrieved through the Session Files API. No new
recording-storage primitive is required.

The manifest is written only after the Retrace worker has exited and the
recording hash has been calculated. Both the manifest file and parent
directory are fsynced before publication.

### Verify graceful shutdown

```bash
make lifecycle
```

This starts the real Microsoft adapter and a delayed model boundary, sends one
invocation, waits until the Retrace worker is in flight, and sends `SIGTERM` to
the Hosted Agent process. The test requires the request to drain, the
recording and manifest to be complete under `$HOME`, the server to exit
cleanly, and the trace to replay after the model service has been stopped.

CI repeats this lifecycle proof five times on Linux/amd64.

## Direct Contract Checks

With the services running, readiness is:

```bash
curl -i http://localhost:8088/readiness
```

The invocation protocol is:

```bash
curl -i -X POST \
  'http://localhost:8088/invocations?agent_session_id=demo-session' \
  -H 'Content-Type: application/json' \
  -H 'x-agent-foundry-call-id: demo-call' \
  -H 'x-agent-user-id: demo-user' \
  -H 'traceparent: 00-0123456789abcdef0123456789abcdef-0123456789abcdef-01' \
  --data @generated/requests/identical-request.json
```

When deployed, Foundry injects the call/user headers and forwards trace
context. They are shown explicitly here only to reproduce that gateway context
against the local container. The adapter returns `x-agent-session-id`, while
the response and recording manifest preserve the resolved session ID.

## Tests

```bash
make build
make test
```

The tests cover:

- strict model-output parsing,
- all routing boundaries,
- successful common routes with the missing field,
- failure only on the model-selected rare route,
- stable request and model hashes,
- structured failure preservation,
- sanitized worker environment,
- Microsoft adapter wiring,
- current `get_request_context()` call/user/session propagation,
- OTLP span decoding,
- atomic `$HOME/retrace` artifact publication,
- in-flight `SIGTERM` drain and post-shutdown replay,
- provenance-manifest integrity,
- reviewed failed-recording offline replay, and
- DAP stack, scopes, locals, Step Back, and forward return.

## Useful Commands

```bash
make presentation  # verify the reviewed failed artifact; no Ollama call
make run           # execute the complete real-model proof
make model         # pull only the pinned Ollama model
make build         # build the pinned Python 3.12 image
make demo          # run the live proof without pulling the model first
make test          # run formatting, lint, and tests in Docker
make lifecycle     # interrupt an in-flight request and verify durable replay
make vscode        # prepare the selected failed trace for VS Code
make logs          # show service logs
make clean         # remove this demo's generated state and Compose resources
```

## Architecture And Presentation Script

- [Architecture](docs/ARCHITECTURE.md)
- [Four-minute presentation script](docs/PRESENTATION.md)

## Troubleshooting

### Docker is unavailable

Start Docker Desktop or Docker Engine and wait until `docker info` succeeds.

### Ollama is unavailable in live mode

Run `ollama serve`, then verify:

```bash
curl http://127.0.0.1:11434/api/tags
```

Presentation mode does not require Ollama.

### The live model does not select the rare route

This is genuine sampling. The proof makes up to 20 identical calls and fails
without manufacturing a score. Use `make presentation` for a guaranteed
walkthrough of the reviewed genuine failed invocation.

### VS Code does not stop

Confirm:

- VS Code is connected to the Dev Container,
- the selected trace is `selected-failure.retrace`,
- the breakpoint is on `RETRACE_MODEL_FAILURE_BREAKPOINT`,
- scanning has finished, and
- replay has stopped directly on the historical breakpoint.

Run the same DAP verifier used by CI:

```bash
python /app/scripts/verify_dap.py \
  --recording /app/generated/recordings/selected-failure.retrace \
  --expected /app/generated/recordings/selected-failure.expected.json
```

## Cleanup

```bash
make clean
```

Resource limits are defined for every Compose service and every offline replay
container. Do not run multiple live proofs concurrently on one laptop.

## License

Apache-2.0. See [LICENSE](LICENSE).
