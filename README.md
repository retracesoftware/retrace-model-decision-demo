# Retrace Model-Dependent Failure Demo

This repository demonstrates deterministic recording, replay, and debugging of
a Python application whose control flow depends on a sampled model response. A
later model call may not reproduce the same route, so Retrace preserves the
specific execution that produced the failure.

## Reading Order

For a complete technical understanding, read these sections in order:

1. **Failure Scenario** defines the input, model output, route, and exception.
2. **System Architecture** shows every process and the exact point where
   `retracepython` enters the execution.
3. **Capture And Replay Fresh Model Decisions** explains the live experiment.
4. **Replay The Bundled Historical Example** explains the deterministic
   presentation workflow.
5. **Debug Either Recording In VS Code** explains the investigation and why
   each breakpoint is used.
6. **How The Make Targets And Python Scripts Fit Together** maps every command
   to the source code that implements it.

## Failure Scenario

Alice asks for a GBP 125 refund for a damaged medical-device accessory. The
case is deliberately borderline:

- it is one day outside the self-service window,
- a photo supports the damage,
- the serial number is obscured and represented in the request as `None`,
- the customer has a good four-year history, and
- the accessory accompanies regulated equipment but is not safety-critical.

A real sampled `qwen3:1.7b` model assigns a discretionary review score. The
application converts that score into one of three ordinary Python routes:

```text
score below 65  -> approve_refund              -> succeeds
score 65-69     -> request_more_information    -> needs a serial number
score 70+       -> escalate_specialist         -> succeeds
```

The missing serial number exists on every invocation, but only the middle
route reads it. In the preserved incident, Qwen returned score `65`. Python
selected `request_more_information`, loaded `serial_number=None`, and called
`.strip()` on it:

```text
AttributeError: 'NoneType' object has no attribute 'strip'
```

This is a realistic AI-integration failure pattern. The model response is
valid. The application bug is a route-specific assumption about an optional
field. A later call with the same request can receive a different sampled
score, choose a successful route, and make the incident appear to have
vanished.

## Application Code Path

The application path is short enough to understand on screen:

```text
same customer request
  -> real sampled Qwen response over HTTP
  -> parse_model_assessment() extracts score and reason
  -> route_review_score() selects an application action
  -> request_more_information reads serial_number
  -> serial_number.strip() raises AttributeError
```

The relevant source files are:

| File | Responsibility |
| --- | --- |
| `scripts/demo_state.py` | Defines the identical customer case, including `serial_number=None`. |
| `external_world/model_gateway.py` | Makes the real sampled Qwen call during fresh capture. |
| `worker/http_json.py` | Contains the external HTTP boundary that Retrace records. |
| `worker/model_client.py` | Sends the model messages and output schema to the gateway. |
| `worker/decision_agent.py` | Parses the model output, routes the score, and contains the latent bug. |
| `worker/__main__.py` | Prints the application failure and lets Python emit the real traceback. |
| `agent/invocation_runner.py` | Launches one `retracepython` worker and one recording per invocation. |

The model is not instructed to fail, and the failing response is not
hardcoded. Fresh mode uses temperature `1.7`, top-p `1.0`, and no seed. Every
invocation sends the same model-request hash, but sampled responses may produce
different scores and therefore different Python routes.

## System Architecture

The demo separates orchestration, the long-lived agent host, the recorded
application process, and external services. This separation is important:
Retrace records the short-lived Python worker that consumes one model response.
It does not record Docker Compose, the test harness, Ollama, or the long-lived
agent server.

```text
Host terminal
  |
  | make run
  v
scripts/run_demo.py                         orchestration and assertions
  |
  | POST /invocations
  v
agent/main.py                               long-lived Invocations HTTP host
  |
  | run_recorded_invocation(...)
  v
agent/invocation_runner.py                  creates one recording per request
  |
  | retracepython --recording <id>.retrace
  |   -m worker --request-json <payload>
  v
worker/__main__.py                          recorded application process
  |
  v
worker/decision_agent.py                    application and routing logic
  |
  v
worker/model_client.py
  |
  v
worker/http_json.py                         recorded HTTP boundary
  |
  | POST /v1/decision
  v
external_world/model_gateway.py             unrecorded external service
  |
  v
Ollama / qwen3:1.7b                         sampled model inference
```

There are three Compose services during fresh capture:

| Service | Process | Purpose | Recorded by Retrace? |
| --- | --- | --- | --- |
| `agent` | `python -m agent.main` | Accepts Invocations requests, creates the OTel span, and launches one worker per request. | No |
| `model-gateway` | `python -m external_world.model_gateway` | Calls Ollama and returns a normalized model response. | No |
| `telemetry-collector` | `python -m external_world.otel_collector` | Receives and stores OTLP spans for correlation checks. | No |

The fourth process, the worker, is a subprocess of `agent`. It is the only
process recorded by Retrace.

### Where Retrace is integrated

The integration is in `agent/invocation_runner.py`. For each incoming agent
request it executes the equivalent of:

```bash
retracepython \
  --recording /app/generated/session-home/retrace/recordings/<recording-id>.retrace \
  -m worker \
  --request-json '<canonical request JSON>'
```

This is the normal Retrace recording interface. No demo-specific recording API
is used. `retracepython` starts the worker under Retrace, the worker executes
ordinary Python, and the resulting `.retrace` file is persisted when the
worker exits.

The worker receives a deliberately restricted environment containing only the
Python path, locale, recording ID, isolated home directory, and model-gateway
URL. Parent-process telemetry configuration and the canary parent secret are
not copied into the recorded process.

### What Retrace records in this demo

The application builds a normal `urllib.request.Request` and executes
`urlopen()` in `worker/http_json.py`. During recording:

1. The worker makes the real HTTP request.
2. The model gateway makes the real Qwen inference.
3. The HTTP response crosses Retrace's external-call boundary.
4. Retrace writes the response and the ordering information needed to replay
   that boundary into the recording.
5. Python parses the response, selects a route, and either returns or fails.

Retrace records boundary behavior rather than taking a memory snapshot of the
entire process. During replay the Python code executes again, but the external
HTTP operation receives the recorded result. The model gateway and Ollama are
not required.

### Recording and replay data flow

Fresh capture:

```text
real Qwen response
  -> recorded HTTP result
  -> Python parser and route execute
  -> structured decision/failure events
  -> .retrace recording
  -> per-invocation manifest
```

Offline replay:

```text
selected-failure.retrace
  -> extract recording process tree
  -> selected-failure.d/<root-pid>.bin
  -> run recorded root process with --network none
  -> Retrace supplies historical HTTP response
  -> same parser, score, route, locals, traceback, and exit code
```

DAP debugging:

```text
VS Code Retrace extension
  -> retrace-dap Go adapter
  -> starts the extracted replay process
  -> scans the historical execution for requested breakpoints
  -> drives the replay cursor
  -> asks the Python control runtime for stack, scopes, and variables
```

The generated `.code-workspace` identifies the extracted process tree for the
extension. The extension and DAP adapter do not debug a new model invocation;
they control replay of the selected recording.

## Failure-Driven Investigation

The recommended demo does not begin with an unexplained breakpoint. It begins
with the application evidence an engineer would actually receive: a traceback.

After preparing the bundled historical incident, run:

```bash
make show-failure
```

Retrace replays the selected worker with Docker networking disabled and prints
the original decision event, failure event, and Python traceback. The important
tail is:

```text
File "/app/worker/__main__.py", line 15, in main
  result = run_decision_agent(request)
File "/app/worker/decision_agent.py", line 116, in run_decision_agent
  normalized = serial_number.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

The traceback identifies `worker/decision_agent.py` line `116` as the first
source location to inspect. From there, the debugger answers progressively
deeper questions:

| Investigation question | Evidence to show | Why this point matters |
| --- | --- | --- |
| Where did the incident fail? | `decision_agent.py:116` | This is the exact operation named by the traceback. |
| What value caused it? | `serial_number=None` in Locals | This proves the concrete historical runtime state, not a source-level guess. |
| Why did Python execute this branch? | Step Back to the route, or restart at line `83` | `review_score=65` selected `request_more_information`. |
| Where did score 65 come from? | Step Into line `82` | `parse_model_assessment` reads it from the historical model response. |
| Is replay asking the model again? | Restart at `http_json.py:21` with no gateway | Step Over returns the recorded HTTP response immediately while replay has no network. |

The causal chain recovered from the historical execution is:

```text
recorded Qwen response
  -> review_score = 65
  -> decision_name = request_more_information
  -> serial_number = None
  -> None.strip()
  -> AttributeError
```

This is the capability under test. Static analysis can warn that `.strip()` may
receive `None`. Logs may show that the request failed. A normal rerun may choose
a different model route. Retrace lets the engineer re-enter the exact failed
execution, inspect the original model-derived state, and move backward through
the Python decisions that connected the model response to the exception.

## Recommended Eight-Minute Presentation

Prepare and reproduce the incident:

```bash
make investigate
```

This runs the verified bundled workflow and then performs one additional
network-disabled replay that prints the complete traceback. Use the traceback
to introduce the investigation:

> We have an agent invocation that failed only on one model-selected route.
> Rerunning the request may change the model decision, so instead of replacing
> the evidence, we are reopening the execution that actually failed. The
> traceback points us to `decision_agent.py:116`; that is where we begin.

Then open VS Code:

```bash
code .
```

Select **Dev Containers: Reopen in Container**, set the first breakpoint on
line `116`, and follow this narrative:

1. **Symptom:** At line `116`, show `serial_number=None` and the
   `AttributeError` operation.
2. **Route:** Show `decision_name="request_more_information"` and
   `review_score=65` in the same historical Locals scope.
3. **Causality:** Step backward, or restart at line `83`, and enter
   `route_review_score` to show how 65 selected the middle route.
4. **Model evidence:** Restart at line `82` and enter
   `parse_model_assessment` to show that 65 came from the preserved model JSON.
5. **External-boundary proof:** Restart at `worker/http_json.py:21`, Step Over
   `urlopen`, and show that the historical response returns even though the
   gateway is absent and replay has no network.
6. **Time travel:** Return to line `116`, Step Back toward the assignment and
   route, then Step Over forward to the same failure.

Close with:

> The value is not merely that the model can vary. The value is that one
> production outcome can depend on one historical model response. Retrace
> preserves that response together with the Python execution that consumed it,
> then makes the execution reproducible and debuggable after the live model is
> gone.

The full spoken script and precise VS Code actions are in
[`docs/GUIDED_WALKTHROUGH.md`](docs/GUIDED_WALKTHROUGH.md).

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

## What Is Bundled

The repository contains one reviewed genuine failed recording for each native
Linux architecture supported by the demo:

```text
example-artifacts/
  linux-amd64/
    selected-failure.retrace
    selected-failure.expected.json
    selected-failure.proof.json
    DEMO_RESULTS.failure.example.md
  linux-arm64/
    selected-failure.retrace
    selected-failure.expected.json
    selected-failure.proof.json
    DEMO_RESULTS.failure.example.md
```

Each file has a distinct purpose:

- `selected-failure.retrace` is the executable Retrace artifact captured from
  a real Qwen-backed worker invocation.
- `selected-failure.expected.json` contains the exact decision, exception,
  exit code, and runtime input that every replay must reproduce.
- `selected-failure.proof.json` binds the recording SHA-256 to its source
  revision, worker hash, Python and Retrace versions, native platform, model
  name and digest, request and response hashes, Foundry identifiers, and OTel
  trace/span identifiers.
- `DEMO_RESULTS.failure.example.md` is the human-readable report from that
  reviewed run.

Two `.retrace` files are necessary because the recording contains a native
Linux replay executable. An AMD64 recording is replayed with the AMD64 image,
and an ARM64 recording is replayed with the ARM64 image. Python and Retrace
versions are also pinned so replay uses the environment represented by the
recording.

### How the bundled recordings were created

The bundled recordings were not written by hand and the model response was
not inserted into a fixture. Each artifact started as output from the complete
fresh workflow:

1. `make run` called the real sampled Qwen model with the identical request.
2. The model naturally returned score `65` and Python selected
   `request_more_information`.
3. The recorded worker reached `serial_number=None` and raised the historical
   `AttributeError` at `.strip()`.
4. The harness selected that failed invocation and proved ten offline replays,
   historical DAP state, model-call isolation, telemetry linkage, and artifact
   integrity.
5. The recording, expectation, proof manifest, and report were reviewed.
6. A maintainer promoted them into the appropriate architecture directory
   with `scripts/promote_reviewed_artifact.py`.

Promotion rechecks the recording SHA, required provenance fields, native
platform, and expected exception before copying anything under
`example-artifacts/`. The public bundled workflow repeats those checks every
time it runs.

## Requirements

For the bundled replay:

- Git
- Docker Desktop or Docker Engine with Docker Compose
- VS Code
- the VS Code Dev Containers extension

For fresh capture, also install [Ollama](https://ollama.com/).

The image is pinned to:

```text
Debian Bookworm, native Linux/AMD64 or Linux/ARM64
Python 3.12.13
retracesoftware==0.2.28
retracesoftware-dap==0.2.28
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

## Capture And Replay Fresh Model Decisions

Start Ollama:

```bash
ollama serve
```

In another terminal, run:

```bash
make run
```

The first run pulls the pinned `qwen3:1.7b` model and builds the native Docker
image. The harness then:

1. starts the Invocations host, model gateway, and OTLP collector,
2. sends the identical request to the sampled model,
3. starts one sanitized `retracepython` worker per invocation,
4. creates one fresh recording for every model decision,
5. requires identical model-request hashes across calls,
6. waits for different decisions plus a naturally selected failure,
7. selects that newly captured failed recording,
8. stops the model gateway,
9. replays the recording ten times with `--network none`,
10. verifies the model-call counter did not change during replay,
11. verifies historical stack, scopes, locals, and reverse navigation, and
12. writes the report, run summary, telemetry join, and proof manifest.

Live sampling is real. A single invocation is not guaranteed to fail. The
harness allows at most 20 identical calls and fails rather than manufacturing
a score or response.

Successful output includes:

```text
live=01 decision=... score=... recording=...
replay=01 ... network=none match=yes
...
replay=10 ... network=none match=yes
dap=pass ...
```

The fresh selected recording is written to:

```text
generated/recordings/selected-failure.retrace
```

## Replay The Bundled Historical Example

To prepare and verify replay and DAP without calling the model:

```bash
make replay-example
```

Expected evidence includes:

```text
replay_example=reviewed-genuine-failed-invocation
docker_architecture=arm64  # or amd64
historical_model=score:65 route:request_more_information
historical_failure=AttributeError: 'NoneType' object has no attribute 'strip'
replay=01 ... network=none match=yes
replay=02 ... network=none match=yes
replay=03 ... network=none match=yes
dap=pass ...
proof=pass ...
replay_example=ready
```

The command verifies that the bundled recording matches its provenance
manifest before executing it. The recording contains a genuine historical
model response; replay supplies that recorded response rather than contacting
Qwen.

To run the selected process once more and display its complete application
traceback:

```bash
make show-failure
```

`show-failure` invokes the installed `replay` CLI against the extracted root
process inside a fresh `--network none` container. It prints the real replay
output, verifies the model decision and exception against
`selected-failure.expected.json`, and writes the same output to:

```text
generated/replay/presentation-traceback.log
```

To perform both operations with one command:

```bash
make investigate
```

### What `make replay-example` does

The Make target expands to:

```text
make replay-example
  -> make preflight
  -> make build
  -> python3 -m scripts.run_replay_example
```

The workflow then performs these steps in order:

1. Verifies that Docker and Docker Compose are available.
2. Builds or refreshes the pinned Python 3.12 demo image for Docker's native
   architecture.
3. Clears old files beneath `generated/` so stale results cannot satisfy the
   run.
4. Reads Docker's architecture and selects `linux-amd64` or `linux-arm64`.
5. Verifies the bundled recording's SHA-256, platform, source revision,
   runtime versions, model hashes, Foundry IDs, and telemetry IDs.
6. Copies the reviewed recording, expectation, proof, and report into
   `generated/` as the active example.
7. Extracts the recording and reads `index.json` to find the recorded root
   Python process.
8. Starts three independent replay containers with `--network none`.
9. Requires every replay to reproduce the exact model decision, score,
   exception type, exception message, traceback location, and worker exit
   code stored in `selected-failure.expected.json`.
10. Runs the DAP verifier against the same recording.
11. Verifies a real initial source-breakpoint stop, stack, scopes, historical
    locals, raised-exception stopping, Step Back, forward return, clean
    no-breakpoint termination, truthful capability handling, and Step Into
    across the exception unwind without exposing an artificial source-less
    frame.
12. Generates `selected-failure.code-workspace` for visual debugging.

The historical worker is expected to exit with code `1` because it reproduces
the recorded application failure. The surrounding verification command exits
successfully only when that failure exactly matches the reviewed expectation
on every replay and all DAP checks pass.

This workflow deliberately does not:

- call Ollama or Qwen,
- generate a new model response,
- create a new recording,
- contact a network service during replay, or
- accept a different decision as equivalent.

### Files produced by the bundled workflow

After `make replay-example`, the important active files are:

```text
generated/DEMO_RESULTS.md
generated/recordings/selected-failure.retrace
generated/recordings/selected-failure.expected.json
generated/recordings/selected-failure.proof.json
generated/recordings/selected-failure.code-workspace
generated/recordings/selected-failure.d/index.json
generated/recordings/selected-failure.d/<root-pid>.bin
generated/replay/replay-01.log
generated/replay/replay-02.log
generated/replay/replay-03.log
generated/replay/presentation-traceback.log  # after make show-failure
generated/transcripts/dap.json
generated/transcripts/dap-raised.json
generated/transcripts/dap-no-breakpoint.json
```

The `.retrace` file is the original selected artifact. The `.d/` directory is
its extracted process tree. The `.bin` file is the root process replay entry
used by terminal replay and DAP. The replay logs preserve each independent
offline run, while the transcript files contain the complete DAP request,
response, and event exchanges used by the automated checks.

### Reading the pass evidence

These lines establish different parts of the proof:

```text
proof=pass ...
```

The committed recording matches the provenance manifest and native platform.

```text
replay=01 ... network=none match=yes
```

The replay had no network and reproduced the exact reviewed decision, failure,
and exit code. The same requirement is applied independently to all three
replays.

```text
dap=pass ... entry_stop=real ... locals=pass ...
```

The debugger reached a real inspectable historical stop and satisfied the DAP
state, inspection, exception, and reverse-navigation checks.

```text
replay_example=ready
```

All verification completed and the recording is ready for VS Code.

## Debug Either Recording In VS Code

After `make run` or `make investigate`, open the repository:

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
- uses the fresh selected recording when one exists,
- otherwise copies the architecture-matched bundled recording,
- extracts and indexes the recording,
- generates its `.code-workspace`, and
- runs the automated DAP preflight.

### Start At The Traceback Location

If you used `make investigate`, the terminal has just shown:

```text
File "/app/worker/decision_agent.py", line 116, in run_decision_agent
  normalized = serial_number.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

That evidence identifies the source file and line to inspect. The first
breakpoint is therefore derived from the observed runtime failure.

### Set the failure breakpoint

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

The first stop answers **what failed and with which value**. It does not yet
answer **why this route executed**. That distinction provides the reason to
move backward through the recording.

### Start replay debugging

1. Click the Retrace icon in the left activity bar.
2. Find the Python process under `selected-failure.retrace`.
3. Click Play next to that process.
4. Wait for breakpoint scanning to finish.
5. Replay stops directly on `RETRACE_MODEL_FAILURE_BREAKPOINT`.

The automated DAP preflight verifies that the breakpoint is discoverable and
that the historical stack, scopes, locals, Step Back, forward return, and
exception-unwind Step Into all work before VS Code is opened.

### Inspect historical runtime state

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

### Follow causality backward

Use Step Back to move from line `116` to the `serial_number` assignment and
toward the branch at lines `112-115`. As you continue backward, historical
locals disappear before the statements that created them. Step Over forward
and they reappear.

For the clearest route explanation, restart replay with only a breakpoint on:

```python
decision_name = route_review_score(review_score)  # line 83
```

Step Into `route_review_score`. The historical value is `65`, so:

```text
65 < 65 -> false
65 < 70 -> true
result  -> request_more_information
```

That answers **why Python entered the failing branch**.

Next, restart with only line `82` enabled and Step Into
`parse_model_assessment`. This shows that the score and reason came from the
preserved `raw_model_response`, answering **where the routing input came
from**.

Finally, restart with only `worker/http_json.py:21` enabled. Step Over the
`urlopen` statement. The response returns immediately even though the model
gateway is not running. This is the visible proof that replay is supplying the
historical external result rather than making a new inference.

To demonstrate the exception-unwind fix, restart the replay at the failure
breakpoint and select Step Into. Because `serial_number` is `None`, no Python
child frame can be entered: attribute lookup raises immediately. Retrace skips
CPython's artificial source-less unwind bytecode and stops at the inspectable
exception handler in `/app/worker/__main__.py`. Call Stack, Scopes, and Locals
must remain available after that stop.

The debugger is re-executing the selected historical recording. It does not
make a new model inference.

The full proof runs each service at or below 1 CPU and 1 GiB. Offline replay
is constrained to 1 CPU and 768 MiB. Docker runs the image natively on AMD64
and ARM64; Apple Silicon does not emulate an AMD64 image.

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
- DAP stack, scopes, locals, Step Back, forward return, and inspectable Step
  Into across exception unwind.

## How The Make Targets And Python Scripts Fit Together

The `Makefile` is a command launcher. It contains no recording, replay, model,
or debugger implementation. Each target expands to one or more explicit Python,
Docker, Ollama, or Retrace commands. The Python scripts perform the assertions
that turn those commands into a repeatable demonstration.

### Historical incident workflow

`make investigate` expands to this call chain:

```text
make investigate
  |
  +-- make replay-example
  |     |
  |     +-- python3 -m scripts.preflight
  |     |     `-- docker info
  |     |
  |     +-- docker compose --file compose.yaml build --pull
  |     |
  |     `-- python3 -m scripts.run_replay_example
  |           |
  |           +-- reset generated/
  |           +-- detect Docker architecture
  |           +-- select example-artifacts/linux-<architecture>/
  |           +-- verify recording SHA and proof manifest
  |           +-- copy recording into generated/recordings/
  |           +-- extract the .retrace process tree
  |           +-- replay root process 3 times with --network none
  |           +-- run scripts/verify_dap.py
  |           `-- retrace-dap --recording ... --workspace
  |
  `-- make show-failure
        |
        +-- python3 -m scripts.preflight
        `-- python3 -m scripts.show_failure
              |
              +-- read root PID from selected-failure.d/index.json
              +-- replay selected-failure.d/<root-pid>.bin with --network none
              +-- print the complete Python traceback
              +-- compare decision, exception, location, and exit code
              `-- save generated/replay/presentation-traceback.log
```

This workflow does not create a recording. It proves and investigates an
existing recording that was created by the live workflow.

### Fresh capture workflow

`make run` expands to:

```text
make run
  |
  +-- python3 -m scripts.preflight
  +-- ollama pull qwen3:1.7b
  `-- python3 -m scripts.run_demo
        |
        +-- verify Docker and pinned Ollama model digest
        +-- stop stale demo Compose services
        +-- clear generated/
        +-- build the pinned Python 3.12 image
        +-- start agent, model-gateway, and telemetry-collector
        +-- POST identical requests to /invocations
        +-- create one retracepython worker and recording per request
        +-- stop after distinct decisions, one success, and one failure exist
        +-- select the first natural failure
        +-- stop model-gateway
        +-- replay the failure 10 times with --network none
        +-- prove the model-call counter did not increase
        +-- run the DAP verifier
        +-- generate the VS Code workspace
        +-- verify OTel/recording correlation and secret isolation
        +-- write the proof manifest and reports
        `-- stop this demo's Compose services
```

The recording is created inside `agent/invocation_runner.py`, not in
`scripts/run_demo.py`. `run_demo.py` drives the system from outside and checks
the evidence produced by the agent and worker.

### Runtime source files

| File | Called by | Technical responsibility |
| --- | --- | --- |
| `agent/main.py` | Compose `agent` service | Creates the Invocations HTTP server, reads platform request context, creates the OTel invocation span, calls `run_recorded_invocation`, and correlates the span with the recording ID and outcome. |
| `agent/invocation_runner.py` | `agent/main.py` | Creates the recording ID and artifact paths, sanitizes the worker environment, launches `retracepython`, captures stdout/stderr, parses worker events, and atomically writes the per-invocation manifest. |
| `agent/manifest.py` | Invocation and proof code | Provides SHA-256 and atomic manifest-writing helpers. |
| `worker/__main__.py` | `retracepython -m worker` | Parses the request, calls the application, prints structured success/failure events, and re-raises failures so Python emits the traceback and nonzero exit code. |
| `worker/decision_agent.py` | `worker/__main__.py` | Builds the prompt, parses strict model JSON, maps score ranges to routes, records decision evidence, and contains the optional-serial-number bug. |
| `worker/model_client.py` | `worker/decision_agent.py` | Converts the application model call into a request to the configured model gateway. |
| `worker/http_json.py` | `worker/model_client.py` | Implements the `urllib` HTTP call. Its `urlopen` operation is the external boundary demonstrated during replay. |
| `external_world/model_gateway.py` | Compose `model-gateway` service | Validates the exact request, calls the pinned Ollama model with nondeterministic sampling, normalizes the response, hashes request/response data, and increments the live-call counter. |
| `external_world/otel_collector.py` | Compose `telemetry-collector` service | Accepts OTLP/HTTP exports and writes decoded spans to `generated/telemetry/spans.jsonl`. |
| `external_world/common.py` | Both external HTTP services | Supplies their small JSON HTTP-server base class. |

### Orchestration and verification scripts

| File | Invoked by | Technical responsibility |
| --- | --- | --- |
| `scripts/run_demo.py` | `make run` through `make demo` | Orchestrates the complete fresh model workflow and verifies every claim: identical request hashes, route variation, natural failure, ten offline replays, no replay-time model calls, DAP behavior, telemetry correlation, provenance, and final reports. |
| `scripts/run_replay_example.py` | `make replay-example` | Selects the native reviewed artifact, verifies its proof, copies it into the active generated area, runs three offline replays, invokes the DAP verifier, and generates the VS Code workspace. |
| `scripts/show_failure.py` | `make show-failure` | Runs one explicit terminal replay through the installed `replay` command, prints the complete traceback, validates it against the expected result, and writes the presentation log. |
| `scripts/verify_dap.py` | Both replay workflows and Dev Container setup | Acts as a DAP client. It launches `retrace-dap`, sends protocol requests, and verifies source breakpoint stops, stack, scopes, locals, raised exceptions, clean termination, Step Back, forward execution, and Step Into across exception unwind. It is verification code, not part of the recorded application. |
| `scripts/prepare_vscode.py` | `make vscode` and Dev Container `postCreateCommand` | Selects a compatible active or bundled recording, verifies it, extracts it, generates the `.code-workspace`, and runs the DAP preflight before interactive use. |
| `scripts/demo_state.py` | Agent and orchestration code | Defines the fixed input case and generated-directory layout, canonicalizes JSON, and clears/recreates generated output directories. |
| `scripts/agent_client.py` | `scripts/run_demo.py` | Sends the local Invocations request with call, user, session, and W3C trace context and returns the HTTP response plus platform identifiers. |
| `scripts/preflight.py` | Make targets | Fails early when Docker is missing, stopped, or unreachable. |
| `scripts/platforms.py` | Replay and promotion scripts | Normalizes AMD64/ARM64 names, detects Docker's native architecture, and selects the matching reviewed recording directory. |
| `scripts/proof_manifest.py` | Replay and VS Code preparation | Verifies recording SHA-256, required provenance fields, and native platform before an artifact is used. |
| `scripts/reset_demo.py` | `make prepare` and `make clean` | Clears generated demo state without deleting source or unrelated Docker data. |
| `scripts/promote_reviewed_artifact.py` | Maintainer command | Revalidates a freshly generated failure and copies its recording, expectation, proof, and report into the architecture-specific committed artifact directory. |
| `scripts/verify_foundry_lifecycle.py` | `make lifecycle` | Tests process shutdown while a recorded worker is in flight, then verifies durable artifact publication and replay after the external service stops. |
| `scripts/lifecycle_model_gateway.py` | Lifecycle verifier only | Provides a delayed deterministic HTTP service used to put the lifecycle test at a known in-flight boundary. It is not used by `make run`. |

### Container and editor configuration

| File | Purpose |
| --- | --- |
| `Dockerfile` | Pins Debian Bookworm, Python 3.12.13, Retrace, retrace-dap, and all Python dependencies. Build-time checks fail if the pinned versions are not installed. |
| `compose.yaml` | Defines the three live services, bind mount, ports, health checks, resource limits, environment, and isolated demo network. |
| `.devcontainer/compose.yaml` | Adds a persistent `workspace` container using the same image and `/app` bind mount. It does not start a new model inference. |
| `.devcontainer/devcontainer.json` | Tells VS Code to connect to `workspace`, install the Retrace extension in the remote extension host, select container Python, and run `scripts.prepare_vscode` after creation. |
| `Makefile` | Gives stable operator commands for the Python and Docker workflows described above. |

### Why the implementation has multiple scripts

The split keeps the proof boundaries explicit:

- Runtime code under `agent/` and `worker/` is the system being demonstrated.
- `external_world/` is deliberately outside the recorded process.
- `scripts/run_demo.py` is the live experiment controller.
- `scripts/run_replay_example.py` is the deterministic artifact verifier.
- `scripts/show_failure.py` exposes the normal Python traceback used to begin
  interactive investigation.
- `scripts/verify_dap.py` checks debugger behavior independently of the VS Code
  user interface.

Combining these into one script would make it difficult to distinguish the
application, the external nondeterministic dependency, Retrace integration,
and the test harness that verifies the result.

## Command Reference

### Primary workflows

| Command | What it does |
| --- | --- |
| `make investigate` | Recommended incident walkthrough. Runs `replay-example`, then performs one additional network-disabled replay and prints the full historical traceback that leads into the VS Code investigation. |
| `make run` | Runs `preflight`, pulls the pinned Qwen model, executes fresh real-model invocations, creates new recordings, selects a natural failure, performs ten network-disabled replays, validates DAP, and writes the complete proof set. |
| `make replay-example` | Builds the native image, selects and verifies the architecture-matched bundled recording, performs three network-disabled replays, validates DAP, and generates the VS Code workspace. It makes no model call and creates no recording. |
| `make show-failure` | Replays the active selected root process through the installed `replay` CLI with networking disabled, prints and validates the complete historical traceback, and saves `presentation-traceback.log`. Run `replay-example` first. |
| `make presentation` | Compatibility alias for `make replay-example`. New instructions use the clearer `make replay-example` name. |

### Setup and service control

| Command | What it does |
| --- | --- |
| `make preflight` | Checks that Docker is reachable and suitable before other work starts. It does not build or run the demo. |
| `make model` | Pulls the pinned `qwen3:1.7b` model into local Ollama. It does not start the demo. |
| `make build` | Pulls the pinned Python base image and builds `retrace-model-decision-demo:py312` for Docker's native architecture. |
| `make prepare` | Builds the image and resets the mounted `generated/` workspace from a one-shot container. |
| `make start` | Starts the Invocations host, model gateway, and telemetry collector with Compose and waits for their health checks. Ollama must already be running for live model calls. |
| `make stop` | Stops this demo's Compose services and removes orphaned containers without deleting unrelated Docker state. |
| `make status` | Shows the current Compose service state. |
| `make logs` | Prints logs from this demo's Compose services. |
| `make shell` | Opens Bash inside the running `agent` service. Run `make start` first. |

### Verification and development

| Command | What it does |
| --- | --- |
| `make demo` | Runs the fresh orchestration script without first executing the `make model` dependency. Use it only when Ollama and the pinned model are already ready. |
| `make test` | Runs Ruff linting, Ruff formatting checks, and the Python test suite inside the pinned image. It does not call the model. |
| `make lifecycle` | Sends `SIGTERM` while a model request is in flight and proves graceful drain, durable recording publication, clean server exit, and replay after shutdown. |
| `make vscode` | Selects a compatible failed recording, verifies its proof, extracts and indexes it, creates the `.code-workspace`, and runs the DAP preflight. The Dev Container runs the same preparation automatically. |
| `make clean` | Stops this demo's Compose services, removes only this demo's Compose volumes, and clears generated demo output. It does not run a global Docker prune. |

## Architecture And Presentation Script

- [Architecture](docs/ARCHITECTURE.md)
- [Guided walkthrough](docs/GUIDED_WALKTHROUGH.md)

## Troubleshooting

### Docker is unavailable

Start Docker Desktop or Docker Engine and wait until `docker info` succeeds.

### Ollama is unavailable in live mode

Run `ollama serve`, then verify:

```bash
curl http://127.0.0.1:11434/api/tags
```

The bundled replay does not require Ollama.

### The live model does not select the rare route

This is genuine sampling. The proof makes up to 20 identical calls and fails
without manufacturing a score. Use `make replay-example` to inspect the
bundled genuine failed invocation without waiting for fresh sampling.

### Docker consumes excessive resources on Apple Silicon

Current versions of the demo use native Linux ARM64 containers. Confirm both
the Docker engine and demo image report ARM64:

```bash
docker info --format '{{.Architecture}}'
docker image inspect retrace-model-decision-demo:py312 \
  --format '{{.Architecture}}'
```

Both should print `arm64` or `aarch64`. If an older forced-AMD64 image remains,
remove only that demo image and rebuild it natively:

```bash
docker image rm retrace-model-decision-demo:py312
make build
```

Do not use `docker system prune --all`; the demo does not require deleting
unrelated Docker data.

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
container. The demo builds for Docker's native architecture, so Apple Silicon
does not run the Linux AMD64 image through emulation. Do not run multiple live
proofs concurrently on one laptop.

## License

Apache-2.0. See [LICENSE](LICENSE).
