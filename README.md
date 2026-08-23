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

## What You Can Run

The repository provides two independent workflows.

### Capture fresh model invocations

```bash
make run
```

This is the complete record-and-replay proof. It makes fresh calls to a real
Qwen model and creates new Retrace recordings on your machine. The same model
request is repeated until sampling produces at least two application decisions,
including one successful invocation and the rare failing route. The harness
then stops the model gateway and replays the newly recorded failure ten times
with Docker networking disabled.

This workflow proves that Retrace can capture a model-dependent execution as it
happens and reproduce it after the model is unavailable.

### Replay a bundled verified recording

```bash
make replay-example
```

This does **not** make a new model call or create a new recording. It uses a
small, reviewed `.retrace` artifact previously produced by `make run` from a
real Qwen invocation. It verifies the artifact's SHA-256 provenance manifest,
replays the failure three times with networking disabled, exercises the DAP
server, and creates the VS Code workspace.

The bundled recording provides a quick way to inspect a known historical
execution. It complements rather than replaces the fresh-capture workflow.
Reviewed recordings are supplied separately for Linux AMD64 and Linux ARM64,
and the demo automatically selects the one matching Docker's native
architecture.

## How The Repository Is Assembled

The demo has four cooperating parts:

```text
agent/
  Microsoft Invocations host, request context, telemetry, and worker launch

external_world/
  model gateway and local OTLP collector used during fresh capture

worker/
  ordinary single-invocation Python application recorded by Retrace

scripts/
  orchestration, verification, replay, DAP, and artifact-provenance checks
```

During fresh capture, the long-lived host is not recorded. It launches one
sanitized `retracepython` worker for each invocation. That worker makes the
model-boundary request, parses the returned score, chooses the application
route, and either succeeds or reaches the missing-serial-number failure.

```text
identical request
  -> Invocations host
  -> one Retrace worker
  -> model gateway
  -> real sampled Qwen response
  -> deterministic Python routing
  -> one .retrace recording
```

During replay, only the recorded worker is re-executed. The model gateway is
unavailable and Docker networking is disabled. Retrace supplies the historical
model-boundary result from the recording, so the ordinary Python code selects
the same route and reaches the same result.

```text
.retrace recording
  -> extracted root-process replay binary
  -> historical model response supplied by Retrace
  -> same Python route
  -> same exception and exit code
  -> DAP inspection of stack, scopes, and locals
```

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

To exercise replay and DAP without calling the model:

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

After `make run` or `make replay-example`, open the repository:

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

### Time travel

Use Step Back once or twice to move from the failing operation toward its
routing branch. Then use Continue or Step Over to move forward to the same
failure again. Also show Call Stack, Scopes, and Locals.

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
- DAP stack, scopes, locals, Step Back, forward return, and inspectable Step
  Into across exception unwind.

## Command Reference

### Primary workflows

| Command | What it does |
| --- | --- |
| `make run` | Runs `preflight`, pulls the pinned Qwen model, executes fresh real-model invocations, creates new recordings, selects a natural failure, performs ten network-disabled replays, validates DAP, and writes the complete proof set. |
| `make replay-example` | Builds the native image, selects and verifies the architecture-matched bundled recording, performs three network-disabled replays, validates DAP, and generates the VS Code workspace. It makes no model call and creates no recording. |
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

### The two main command chains

```text
make run
  -> preflight
  -> model
  -> demo
  -> fresh model calls
  -> fresh recordings
  -> ten offline replays
  -> DAP and evidence validation
```

```text
make replay-example
  -> preflight
  -> build
  -> verified bundled recording
  -> three offline replays
  -> DAP and provenance validation
  -> VS Code workspace
```

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
