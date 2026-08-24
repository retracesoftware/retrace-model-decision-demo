# Retrace Model-Dependent Failure Demo

This repository demonstrates deterministic recording, replay, and debugging of
a Python application whose control flow depends on a sampled model response. A
later model call may not reproduce the same route, so Retrace preserves the
specific execution that produced the failure.

## Quick Presentation Path

Use this section when presenting. The longer sections below explain the
implementation and provide additional tests.

The repository already contains a genuine failed recording captured during a
real sampled Qwen invocation. In this workflow, **prepare the incident** means
selecting the bundled recording for the current Docker architecture, verifying
it, extracting it, and generating its debugger workspace. It does not create a
new failure or call Qwen. Ollama is not required for this presentation path.

For a first-time checkout:

```bash
git clone https://github.com/retracesoftware/retrace-model-decision-demo.git
cd retrace-model-decision-demo
code --install-extension ms-vscode-remote.remote-containers
```

The Retrace VS Code extension is installed automatically inside the Dev
Container.

### 1. Prepare the recording and show the failure

From the repository root:

```bash
docker info
make investigate
```

`make investigate` runs these two targets in order:

```text
make replay-example   # verify, copy, extract, replay, and prepare VS Code
make show-failure     # replay once more and print the complete traceback
```

The expected application failure appears in the terminal:

```text
File "/app/worker/decision_agent.py", line 116, in run_decision_agent
  normalized = serial_number.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

The traceback is also saved at:

```bash
cat generated/replay/presentation-traceback.log
```

At this point you have completed the first two parts of the story:

```text
historical failed invocation
  -> deterministic terminal replay
  -> real Python traceback identifies decision_agent.py:116
```

### 2. Open that same execution in VS Code

```bash
code .
```

In VS Code:

1. Open the Command Palette.
2. Select **Dev Containers: Reopen in Container**.
3. Wait for the status bar to show **Retrace Model Decision Demo**.
4. Open `/app/worker/decision_agent.py`.
5. Set one breakpoint on line `116`, at `serial_number.strip()`.
6. Click the Retrace icon in the left activity bar.
7. Click Play beside the Python process under `selected-failure.retrace`.
8. Wait for replay to stop automatically at line `116`; do not press Continue
   before the first stop.

Inspect Locals and show:

```text
serial_number = None
review_score = 65
decision_name = "request_more_information"
```

Terminal replay and VS Code are using the same
`generated/recordings/selected-failure.retrace` artifact.

### 3. Follow the cause backward

Restart replay with only line `83` enabled. Step Into
`route_review_score(review_score)` and show:

```text
65 < 65 -> false
65 < 70 -> true
route -> request_more_information
```

Restart with only line `82` enabled. Step Into
`parse_model_assessment(raw_model_response)` and show that `review_score=65`
came from the preserved model response.

Optionally restart with only `worker/http_json.py:21` enabled. Step Over
`urlopen()`. The response returns while the gateway is stopped, proving that
Retrace supplies the recorded historical HTTP result. The automated replay and
DAP proofs perform the same check inside `--network none` containers.

The presentation story is therefore:

```text
1. Reproduce and show the historical failure.
2. Use its traceback to choose the first debugger location.
3. Inspect the exact historical value that caused it.
4. Follow the route backward to the preserved model response.
5. Prove the model was not called again during replay.
```

For the spoken explanation and additional debugger operations, use
[`docs/GUIDED_WALKTHROUGH.md`](docs/GUIDED_WALKTHROUGH.md).

For the complete team-facing explanation of what changed, what to say, what to
show, and how to recover during a live call, use
[`docs/TEAM_DEMO_RUNBOOK.md`](docs/TEAM_DEMO_RUNBOOK.md).

## Reading Order

The quick path above is sufficient for presenting. For a complete technical
understanding, read these sections in order:

1. **Failure Scenario** defines the input, model output, route, and exception.
2. **How The Demo Application Works** follows one request through every
   application function, from the HTTP endpoint to the model call, route, and
   exception.
3. **System Architecture** shows every process, the exact recording boundary,
   and why the model gateway remains outside the recording.
4. **Recommended Eight-Minute Presentation** gives the complete terminal and
   VS Code sequence, including what every step proves.
5. **Capture And Replay Fresh Model Decisions** explains the live experiment.
6. **Replay The Bundled Historical Example** explains the deterministic
   presentation workflow.
7. **Debug Either Recording In VS Code** provides additional debugger tests.
8. **How The Make Targets And Python Scripts Fit Together** maps every command
   to the source code that implements it.

## Failure Scenario

The demo supplies Qwen with a text description of Sofia asking for a GBP 125
refund for a damaged medical-device accessory. The text describes a
deliberately borderline case:

- it is one day outside the self-service window,
- a photo supports the damage,
- the serial number is obscured and represented in the request as `None`,
- the customer has a good four-year history, and
- the accessory accompanies regulated equipment but is not safety-critical.

These statements are **textual prompt content**, not independently loaded case
records. The demo does not upload a photo, send image bytes or a photo URL, run
a vision model, query an account-history database, or evaluate a policy engine.
The word `photo` is part of the sentence Qwen receives. It means "the prompt
asserts that photo evidence exists," not "the application verified a photo."

The complete application request has only three structured fields:

```python
{
    "case_id": "CASE-MODEL-NONDETERMINISM-001",
    "serial_number": None,
    "user_prompt": "Sofia requests a GBP 125 refund ...",
}
```

The scenario details are represented and consumed as follows:

| Scenario detail | Actual representation | Code that consumes it |
| --- | --- | --- |
| Day 31 of a 30-day window | Words inside `user_prompt` | Qwen only |
| Photo supports the damage | Words inside `user_prompt`; no photo is transmitted | Qwen only |
| Serial number is obscured | Words inside `user_prompt` and structured `serial_number=None` | Qwen sees the words; Python later reads the structured value |
| Four-year account history | Words inside `user_prompt` | Qwen only |
| Regulated but non-safety-critical accessory | Words inside `user_prompt` | Qwen only |

Qwen does not receive or emit a full business decision. It receives the system
instruction plus `user_prompt` and returns exactly two fields:

```json
{"review_score": 65, "reason": "..."}
```

Ordinary Python then validates those fields, maps the score to a route, and
executes that route. Python does not independently recompute the score from the
five scenario statements. The only case fact directly consumed after model
inference is `serial_number`, and only the middle route reads it.

A real sampled `qwen3:1.7b` model assigns a discretionary review score. The
application converts that score into one of three ordinary Python routes:

```text
score below 65  -> approve_refund              -> succeeds
score 65-69     -> request_more_information    -> needs a serial number
score 70+       -> escalate_specialist         -> succeeds
```

The missing serial number is present as `None` on every invocation, but only
the middle route reads it. In the preserved incident, Qwen returned score
`65`. Python selected `request_more_information`, loaded
`serial_number=None`, and called
`.strip()` on it:

```text
AttributeError: 'NoneType' object has no attribute 'strip'
```

This is a realistic AI-integration failure pattern. The model response is
valid. The application bug is a route-specific assumption about an optional
field. A later call with the same request can receive a different sampled
score, choose a successful route, and make the incident appear to have
vanished.

## How The Demo Application Works

This section describes the application independently of Retrace. Read it
before running the commands or setting breakpoints.

### What the application is

The demo is a small model-assisted support-routing service. It accepts a
customer case, asks a language model for a discretionary review score, validates
the response, and maps the score to one of three application actions.

It does not transfer money, update an account, or submit a real refund. The
three actions are represented by returned strings so that the example remains
small enough to inspect completely during a presentation. The production-like
part under investigation is the integration pattern:

```text
unstructured case text
  -> sampled model result
  -> strict response validation
  -> deterministic Python routing
  -> route-specific application code
```

The demo is divided into four code areas:

| Area | Files | Role |
| --- | --- | --- |
| Incoming agent service | `agent/main.py`, `agent/invocation_runner.py` | Accepts an invocation and launches one isolated application worker. |
| Recorded application | `worker/` | Calls the model boundary, validates the result, chooses the route, and either returns or fails. This is the code being debugged. |
| External dependencies | `external_world/` and Ollama | Performs sampled Qwen inference and collects telemetry. These services are outside the worker process. |
| Demo controller | `scripts/`, `Makefile` | Starts services, sends repeated requests, selects evidence, and verifies claims. This is test and presentation orchestration, not business logic. |

### Complete request lifecycle

One fresh invocation moves through the following code. The numbered steps map
directly to files and functions that can be opened in the repository.

#### 1. The fixed case is defined

[`scripts/demo_state.py`](scripts/demo_state.py) defines the case used for each
fresh invocation:

```python
CASE = {
    "case_id": "CASE-MODEL-NONDETERMINISM-001",
    "serial_number": None,
    "user_prompt": "Sofia requests a GBP 125 refund ...",
}
```

`case_id` identifies the example. `user_prompt` contains the facts presented
to Qwen. `serial_number` is structured application data and is deliberately
`None` because the serial is obscured.

No code derives `serial_number` from the text. No photo is uploaded. The
structured value and the explanatory prose are both fixed inputs supplied by
the demo.

#### 2. A client calls the agent endpoint

[`scripts/agent_client.py`](scripts/agent_client.py) sends this HTTP request to
the local agent service:

```json
{
  "input": "Sofia requests a GBP 125 refund ...",
  "metadata": {
    "demo_case_id": "CASE-MODEL-NONDETERMINISM-001",
    "purpose": "retrace-nondeterministic-model-decision"
  }
}
```

The client also sends call, user, and W3C trace-context headers. Those values
exist to demonstrate correlation between the platform invocation, telemetry,
and recording. They do not affect the refund route.

#### 3. The agent host constructs the worker request

[`agent/main.py`](agent/main.py) exposes the `/invocations` handler. It checks
that `input` is non-empty, reads the request context, starts an OpenTelemetry
span, and combines the incoming text with the fixed structured case:

```python
request_payload = {
    **CASE,
    "user_prompt": user_input,
}
```

The resulting worker request is therefore:

```json
{
  "case_id": "CASE-MODEL-NONDETERMINISM-001",
  "serial_number": null,
  "user_prompt": "Sofia requests a GBP 125 refund ..."
}
```

The outer HTTP client does not independently submit a serial-number field;
the local agent combines the fixed demo case with the received text before
launching the worker.

#### 4. One isolated worker is launched for this invocation

[`agent/invocation_runner.py`](agent/invocation_runner.py) creates a unique
recording ID and paths for the recording, manifest, stdout, stderr, and worker
home. It then launches the application as a subprocess:

```bash
retracepython \
  --recording <recording-id>.retrace \
  -m worker \
  --request-json '<the three-field worker request>'
```

This process boundary is where recording begins. The long-lived HTTP host and
the controller stay outside; the short-lived worker handling one decision is
inside.

#### 5. The worker enters the business function

[`worker/__main__.py`](worker/__main__.py) decodes `--request-json` and calls:

```python
result = run_decision_agent(request)
```

[`worker/decision_agent.py`](worker/decision_agent.py) contains the complete
application decision path. There is no hidden framework logic between this
function and the route that fails.

#### 6. Python builds the model request

`model_messages()` creates two messages:

1. A system instruction asks a senior support agent for a discretionary score
   from 0 to 100. Lower scores mean approve; higher scores mean specialist
   review. It explicitly says reasonable experts may score the case
   differently.
2. A user message contains the fixed case prose.

The application also supplies `DECISION_SCHEMA`, requiring exactly:

```json
{
  "review_score": 65,
  "reason": "a concise customer-facing explanation"
}
```

The actual value need not be `65`; it must be an integer from 0 through 100.
The schema disallows extra fields.

#### 7. The worker calls the model gateway

The call chain is:

```text
worker/decision_agent.py:request_model_decision()
  -> worker/model_client.py:request_model_decision()
  -> worker/http_json.py:request_json()
  -> urllib.request.urlopen()
  -> POST http://model-gateway:8091/v1/decision
```

`worker/http_json.py` is intentionally ordinary application code. It JSON
encodes a request, calls `urlopen()`, reads the response, and parses JSON.

The separate [`external_world/model_gateway.py`](external_world/model_gateway.py)
forwards the messages and schema to the local Ollama API using:

```text
model       = qwen3:1.7b
temperature = 1.7
top_p       = 1.0
top_k       = 100
seed        = not set
```

It returns Ollama's response plus a gateway response ID, request hash, provider
name, and sampling options. A simplified response visible to the worker is:

```json
{
  "model": "qwen3:1.7b",
  "created_at": "...",
  "gateway_response_id": "MODEL-...",
  "model_request_sha256": "...",
  "message": {
    "role": "assistant",
    "content": "{\"review_score\":65,\"reason\":\"...\"}"
  }
}
```

This is a real sampled Qwen response during fresh capture. The gateway does not
choose the Python route and does not inject an exception. It only returns model
output and provenance fields.

The demo records the response exposed to the application. It does not claim to
record hidden chain-of-thought or Ollama's internal token-generation process;
`think` is disabled and the application receives only the score and visible
reason.

#### 8. Python validates the model output

Back in `run_decision_agent()`, `parse_model_assessment()` verifies that:

- `message` is an object,
- `message.content` is text,
- the text is valid JSON,
- the JSON contains exactly `review_score` and `reason`,
- `review_score` is an integer from 0 through 100, and
- `reason` is non-empty.

It returns:

```python
review_score, decision_reason
```

For the bundled failed invocation, those historical values are `65` and the
visible reason preserved in the recording.

#### 9. Deterministic Python selects the route

`route_review_score()` is ordinary deterministic code:

```python
if review_score < 65:
    return "approve_refund"
if review_score < 70:
    return "request_more_information"
return "escalate_specialist"
```

For score `65`:

```text
65 < 65 -> false
65 < 70 -> true
decision_name = "request_more_information"
```

The model does not return the route name. Python derives it from the returned
score. This is why stepping into line `83` is useful: it exposes the exact
transition from model-derived data to application control flow.

#### 10. The application records decision evidence

Before executing the route, the worker constructs `decision_evidence` with:

```text
review_score
decision_name
decision_reason
model name and response time
gateway response ID
model request hash
model response hash
```

It prints a `model_decision_selected` JSON event. The invocation runner later
copies this event into the manifest. This event is application telemetry; it
does not replace the `.retrace` recording.

#### 11. One of three branches executes

The route code is deliberately small:

```python
if decision_name == "approve_refund":
    action_detail = "refund approved from the available evidence"
elif decision_name == "request_more_information":
    serial_number = request["serial_number"]
    normalized = serial_number.strip()
    action_detail = f"request a clearer image of {normalized}"
else:
    action_detail = "send the case to a regulated-equipment specialist"
```

The first and third branches do not read `serial_number`, so they succeed even
though it is `None`. The middle branch assumes it is text. In the selected
historical invocation:

```text
serial_number = None
None.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

The correct production fix would be to define the business behavior for a
missing serial number and handle it before calling `.strip()`. The demo leaves
the bug in place because the failed execution is the subject of the
investigation.

#### 12. The failure returns through the process boundary

`worker/__main__.py` catches the exception long enough to emit a structured
`application_failure` event, then re-raises it. Re-raising is why normal Python
prints the full traceback and the worker exits with code `1`.

`agent/invocation_runner.py` captures stdout and stderr, verifies that a
recording exists, writes the per-invocation manifest, and returns an
`InvocationResult`. `agent/main.py` converts that result into an HTTP `500`
response containing the recording ID, model decision, and failure metadata.

On either successful route, the worker instead emits `invocation_completed`,
exits with code `0`, and the agent returns HTTP `200` with the selected action.

### What varies and what does not

The scenario is useful because the nondeterministic and deterministic parts
are cleanly separated:

| Property | Fresh invocations | Replay of one recording |
| --- | --- | --- |
| Case ID, prompt, and `serial_number=None` | Same | Same |
| Python parser and routing thresholds | Same | Same |
| Qwen score and reason | May vary | Exact historical response is restored |
| Gateway response ID and creation time | May vary | Exact historical values are restored |
| Selected Python branch | Depends on sampled score | Same historical branch |
| Failure | Occurs only when score is 65-69 | Reproduces whenever the selected failed recording is replayed |

The latent Python bug is deterministic. Whether a fresh run reaches it is
model-dependent. That is the debugging problem Retrace solves here: preserving
the one model response and downstream execution that exposed the bug.

### Source-reading order

To understand the complete program directly in code, read these files in this
order:

1. [`scripts/demo_state.py`](scripts/demo_state.py): fixed case data.
2. [`scripts/agent_client.py`](scripts/agent_client.py): incoming HTTP request.
3. [`agent/main.py`](agent/main.py): request handler and response.
4. [`agent/invocation_runner.py`](agent/invocation_runner.py): worker launch and
   recording integration.
5. [`worker/__main__.py`](worker/__main__.py): worker entry and failure
   propagation.
6. [`worker/decision_agent.py`](worker/decision_agent.py): prompt, validation,
   routing, evidence, and route-specific bug.
7. [`worker/model_client.py`](worker/model_client.py): gateway request.
8. [`worker/http_json.py`](worker/http_json.py): recorded HTTP boundary.
9. [`external_world/model_gateway.py`](external_world/model_gateway.py): real
   sampled Ollama call during fresh capture.

The model is not instructed to fail, and the failing response is not
hardcoded. Every fresh invocation sends the same model request, but sampling
may produce different scores. The bundled recording is one genuine invocation
in which the returned score naturally selected the buggy middle route.

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
| `agent` | `python -m agent.main` | Accepts Invocations requests, creates the OTel span, and launches one worker per request. | No; it launches the separately recorded worker. |
| `model-gateway` | `python -m external_world.model_gateway` | Calls Ollama and returns a normalized model response. | No; the worker records the exact returned HTTP behavior. |
| `telemetry-collector` | `python -m external_world.otel_collector` | Receives and stores OTLP spans for correlation checks. | No; it stores correlation telemetry outside the application trace. |

The fourth process, the worker, is a subprocess of `agent`. It is the only
process recorded by Retrace.

### Why the model gateway is outside the recording

`Recorded by Retrace? No` does **not** mean that the model result is absent
from the recording. It means that the gateway's own Python instructions are
not part of this worker recording. The value returned by the gateway is
captured where it crosses into the recorded worker at
`worker/http_json.py:21`.

Retrace starts recording at this command:

```bash
retracepython --recording <recording>.retrace -m worker --request-json <request>
```

That command defines the recording scope: the worker and any process children
it launches. Docker Compose starts `model-gateway` independently, so it is an
external service from the worker's point of view.

The process boundary is deliberate:

| Component | What the selected recording preserves |
| --- | --- |
| Recorded worker | Python parsing, validation, routing, local variables, output, exception, and exit code |
| Worker-to-gateway HTTP call | The request/response behavior observed by the worker, including the exact historical model response |
| Model gateway internals | Not executed during worker replay |
| Ollama inference internals | Not executed during worker replay |

This is why the worker can replay with `--network none`. Python reaches the
same `urlopen()` call, but Retrace supplies the recorded response instead of
requiring the gateway or Qwen. The replay then re-executes the parser and route
that produced the application failure.

Recording the gateway instead would answer a different question: what happened
inside the gateway while it normalized and forwarded a provider request. It
would produce a separate gateway-process recording and would not, by itself,
contain the worker's downstream routing and `serial_number.strip()` failure.
The gateway could be recorded separately when investigating gateway code, but
the correct target for this incident is the worker that consumed the model
response and failed.

This selective boundary is a core Retrace capability. Reproducing the worker
does not require reproducing the entire distributed system; it requires the
worker's Python execution plus the exact external behavior that the worker
observed.

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

## Requirements

For the bundled replay and VS Code investigation:

- Git
- Docker Desktop or Docker Engine with Docker Compose
- VS Code
- the VS Code Dev Containers extension

For fresh model capture, also install [Ollama](https://ollama.com/).

The container image is pinned to:

```text
Debian Bookworm, native Linux/AMD64 or Linux/ARM64
Python 3.12.13
retracesoftware==0.2.28
retracesoftware-dap==0.2.28
azure-ai-agentserver-invocations==1.0.0
qwen3:1.7b, pinned digest for live mode
```

Python, Retrace, the DAP adapter, and the agent adapter run inside Docker. They
do not need to be installed on the host.

## Get The Demo

```bash
git clone https://github.com/retracesoftware/retrace-model-decision-demo.git
cd retrace-model-decision-demo
```

Install the Dev Containers extension if needed:

```bash
code --install-extension ms-vscode-remote.remote-containers
```

## Failure-Driven Investigation

The recommended demo does not begin with an unexplained breakpoint. It begins
with the application evidence an engineer would actually receive: a traceback.

On a clean checkout, run:

```bash
make investigate
```

This command first runs `make replay-example` to prepare and verify the bundled
recording. It then runs `make show-failure` to replay the selected worker with
Docker networking disabled and print the original decision event, failure
event, and Python traceback.

The two commands can also be run explicitly:

```bash
make replay-example
make show-failure
```

Do not run `make show-failure` first on a clean checkout; it expects
`make replay-example` to have created the active extracted recording under
`generated/recordings/`. After preparation, `make show-failure` can be repeated
whenever the traceback needs to be shown again.

The important traceback tail is:

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
| Is replay asking the model again? | Restart at `http_json.py:21` with no gateway | Step Over returns the recorded HTTP response immediately; the automated proof also verifies this under `--network none`. |

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

This is the complete bundled-recording presentation path. It does not call
Qwen or create a replacement recording. It verifies and opens one genuine
failed recording previously captured by the fresh workflow.

### 0. Explain the program before running it

Show [`worker/decision_agent.py`](worker/decision_agent.py) and summarize the
application in this order:

```text
The same borderline support case is sent to Qwen.
Qwen returns only a sampled score and visible reason.
Python validates the response and maps the score to an action.
Only the 65-69 action reads the optional serial number.
The preserved invocation scored 65 and called .strip() on None.
```

Then show the three route branches at lines `112-119`. Explain that no real
refund is executed: these branches return action descriptions. The model does
not throw the exception and is not prompted to fail. It returns a valid score;
the application exposes its own latent assumption only on the selected middle
route.

This gives the audience the program, variable, route, and failure model before
any tooling appears. The remaining steps show how the historical execution is
reproduced and investigated.

### 1. Confirm Docker is available

From the repository root:

```bash
docker info
```

This confirms the execution environment needed for the pinned Linux Python
runtime, replay binary, and Dev Container. Start Docker Desktop first if this
command fails.

### 2. Prepare and replay the historical incident

```bash
make investigate
```

This target is a readable wrapper around two operations:

```text
make investigate
  -> make replay-example
  -> make show-failure
```

`make replay-example` performs the preparation and automated proof:

1. builds the pinned Python 3.12 image for Docker's native architecture,
2. selects the matching reviewed AMD64 or ARM64 recording,
3. verifies its SHA-256 and provenance manifest,
4. copies it to `generated/recordings/selected-failure.retrace`,
5. extracts its recorded process tree into `selected-failure.d/`,
6. replays the root process three times with `--network none`,
7. requires the same score, route, exception, traceback location, and exit code,
8. runs the automated DAP stack, scopes, locals, stepping, and exception tests,
9. generates `selected-failure.code-workspace` for VS Code.

`make show-failure` then uses the installed `replay` command against the
extracted root process in one additional `--network none` container. It prints
the original application output and complete Python traceback. The replayed
application exits with code `1`; the outer script exits successfully only when
that failure matches the reviewed expectation.

The engineering chain is therefore:

```text
reviewed selected-failure.retrace
  -> proof and architecture verification
  -> extracted selected-failure.d/<root-pid>.bin
  -> terminal replay prints the historical traceback
  -> the same selected-failure.retrace is opened by retrace-dap in VS Code
```

No step silently swaps to another execution. Terminal replay and VS Code use
the same selected recording.

### 3. Show the traceback

`make investigate` prints the traceback directly in the terminal between:

```text
--- historical application output and traceback ---
...
--- end historical application output ---
```

The important tail is:

```text
File "/app/worker/__main__.py", line 15, in main
  result = run_decision_agent(request)
File "/app/worker/decision_agent.py", line 116, in run_decision_agent
  normalized = serial_number.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

If the terminal has scrolled past it, display the saved output without
rerunning preparation:

```bash
cat generated/replay/presentation-traceback.log
```

To execute and verify the traceback replay again, run:

```bash
make show-failure
```

Explain the starting point:

> We have an agent invocation that failed only on one model-selected route.
> Rerunning the request may change the model decision, so instead of replacing
> the evidence, we are reopening the execution that actually failed. The
> traceback points us to `decision_agent.py:116`; that is where we begin.

### 4. Open the same recording in VS Code

```bash
code .
```

Open the Command Palette and select **Dev Containers: Reopen in Container**.
Wait until the status bar identifies **Retrace Model Decision Demo**.

VS Code remains a host application, but its workspace extension, Python
runtime, source, recording, replay binary, and DAP adapter now run inside the
container at `/app`. The Dev Container's `postCreateCommand` verifies the
active `selected-failure.retrace`, extracts it, regenerates its workspace, and
runs the DAP preflight. It does not call the model or create a new recording.

### 5. Stop at the operation identified by the traceback

Open:

```text
/app/worker/decision_agent.py
```

Set the only source breakpoint on line `116`:

```python
normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
```

Then:

1. click the Retrace icon in the left activity bar,
2. find the Python process under `selected-failure.retrace`,
3. click Play beside that process,
4. wait for `breakpoint scan ... complete`, and
5. let replay stop automatically on line `116`.

Do not press Continue before the first stop. With one breakpoint hit, Continue
means continue beyond that hit and can terminate the replay.

Open **Run and Debug**, then inspect Locals:

```text
serial_number = None
review_score = 65
decision_name = "request_more_information"
model_name = "qwen3:1.7b"
raw_model_response = {...}
```

This stop answers two questions. The traceback showed **where** the incident
failed. Historical Locals now show **what concrete value** caused it and retain
the model-derived route information in the same frame.

### 6. Prove why the failing route executed

Stop the current debug session. Remove or disable line `116`, then leave only a
breakpoint on line `83`:

```python
decision_name = route_review_score(review_score)
```

Start replay again from the Retrace sidebar. When it stops, select **Step
Into** to enter `route_review_score`. Step Over its two comparisons:

```text
review_score = 65
65 < 65 -> false
65 < 70 -> true
route -> request_more_information
```

This proves that the failing branch was selected by the historical model score
rather than by a hardcoded failure switch.

### 7. Prove where score 65 came from

Stop the session, remove or disable line `83`, and leave only line `82`:

```python
review_score, decision_reason = parse_model_assessment(raw_model_response)
```

Start replay and Step Into `parse_model_assessment`. Step Over the validation
and JSON parsing code. Inspect `content`, `assessment`, `review_score`, and
`decision_reason`. This shows that score `65` was parsed from the preserved raw
model response before Python selected a route.

### 8. Prove that replay does not call the model

Stop the session and remove or disable the previous breakpoint. Open
`/app/worker/http_json.py` and set the only breakpoint on line `21`:

```python
with urlopen(request, timeout=timeout) as response:
```

Start replay and Step Over. Execution moves to line `22`, and `response` is
available even though the model gateway is not running. Retrace supplied the
historical HTTP result recorded at this boundary. The automated replay and DAP
proofs verify the same behavior in `--network none` containers. Step Over again
to parse the preserved response and return toward `model_client.py` and
`decision_agent.py`.

This is also why `model-gateway` is not part of the worker recording: its exact
returned behavior has already been captured at the point where the worker
observed it.

### 9. Demonstrate reverse execution

Restart with only line `116` enabled. After the automatic stop:

1. Step Back to the line `115` serial-number assignment.
2. Continue backward toward the branch and decision-evidence construction.
3. Watch locals disappear when the cursor moves before their assignments.
4. Step Over forward and watch the same historical values reappear.

Python bytecode for calls and multiline expressions does not always map to
numerically descending source lines. Judge reverse movement by the earlier
execution state and temporal locals, not by line-number arithmetic alone.

### 10. Close the investigation

The demonstrated chain is:

```text
recorded Qwen response
  -> review_score = 65
  -> request_more_information
  -> serial_number = None
  -> None.strip()
  -> AttributeError
```

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
| `external_world/model_gateway.py` | Compose `model-gateway` service | Forwards the worker's messages and response schema to the pinned Ollama model with nondeterministic sampling, augments the returned response with gateway metadata, records the request, and increments the live-call counter. |
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
