# Team Demo Runbook

This runbook prepares a presenter to explain the model-dependent failure demo,
describe what changed from the previous version, and run the complete terminal
and VS Code investigation without assuming prior knowledge of the codebase.

## The Main Message

The application sends the same borderline support case to a sampled Qwen
model. Qwen returns a score and reason. Ordinary Python validates the response
and maps the score to one of three routes.

The preserved invocation returned score `65`, which selected the
`request_more_information` route. That route assumed an optional serial number
was text and called `.strip()` on `None`, raising `AttributeError`.

A normal rerun can produce another model score, take a successful route, and
hide the incident. Retrace preserves the exact model response and Python
execution that failed. The demo replays that execution without the model,
starts from its real traceback, and follows the historical state backward from
the exception to the model response.

## What Changed From The Previous Version

### Previous presentation flow

The previous version already had a genuine Qwen recording, deterministic
offline replay, automated DAP checks, and a generated VS Code workspace. Its
presentation path was approximately:

```text
make replay-example
  -> see replay=pass and dap=pass summaries
  -> open VS Code
  -> set a preselected breakpoint at line 116
  -> inspect the recording
```

That proved the underlying functionality, but the investigation started at a
location selected by someone who already knew the code. A new audience had no
application evidence explaining why line `116` was the right place to begin.

### Current presentation flow

The revised version is:

```text
make investigate
  -> prepare and verify the reviewed recording
  -> replay the historical worker with networking disabled
  -> print its complete application output and Python traceback
  -> traceback identifies decision_agent.py:116
  -> open the same recording in VS Code
  -> inspect line 116 and follow state backward toward the model response
```

The change turns a collection of debugger operations into an incident
investigation with a clear cause-and-effect sequence.

### New implementation

The following pieces were added:

| Change | Technical behavior | Reason |
| --- | --- | --- |
| `make investigate` | Runs `make replay-example`, followed by `make show-failure`. | Provides one correct command from clean checkout to traceback. |
| `make show-failure` | Runs `scripts/show_failure.py`. | Makes the historical application failure visible in ordinary terminal form. |
| `scripts/show_failure.py` | Finds the extracted root process, invokes the installed `replay` command in a `--network none` container, prints stdout and traceback, and saves the output. | Proves this is an executed replay, not copied explanatory text. |
| Historical failure validation | Requires exit code `1`, the reviewed score and route, exact exception type/message, `decision_agent.py:116`, and the `.strip()` traceback statement. | Prevents the presentation from silently accepting a different execution or stale output. |
| `generated/replay/presentation-traceback.log` | Stores the output produced by the latest `make show-failure`. | Lets the presenter redisplay the traceback without scrolling. |
| `tests/test_show_failure.py` | Tests both bundled architectures and rejects changed decisions or missing traceback locations. | Protects the traceback-first workflow against regression. |
| Expanded architecture documentation | Separates application code, external services, Retrace integration, and verification scripts. | Lets a new reader understand what is being recorded and what the harness merely checks. |
| Quick Presentation Path | Places the complete short workflow at the top of `README.md`. | The presenter no longer has to search the full technical reference during a call. |

### What did not change

The revision did not manufacture a new failure or change the routing thresholds
to make the presentation easier. It did not change Retrace's recording model or
replace the real Qwen response with a fixture.

The underlying incident remains:

```text
historical model response contains review_score=65
  -> deterministic Python selects request_more_information
  -> structured request contains serial_number=None
  -> serial_number.strip()
  -> AttributeError
```

The main functional change is how that incident is surfaced, validated, and
used to begin the debugger investigation.

## Understand The Application Before Presenting

### What the application does

This is a small model-assisted support-routing application. It does not execute
a payment or modify a customer account. Its three branches return action
descriptions so the complete model-to-Python path remains visible.

The fixed case is defined in `scripts/demo_state.py`:

```python
{
    "case_id": "CASE-MODEL-NONDETERMINISM-001",
    "serial_number": None,
    "user_prompt": "Sofia requests a GBP 125 refund ...",
}
```

The day, photo evidence, account history, and equipment context are prose sent
to Qwen. No image is uploaded and no customer database is queried.
`serial_number=None` is structured runtime data and is later read by Python.

### Runtime code path

```text
scripts/agent_client.py
  POST /invocations with the case text
        |
        v
agent/main.py
  merges the text with case_id and serial_number=None
        |
        v
agent/invocation_runner.py
  creates recording ID and launches retracepython -m worker
        |
        v
worker/__main__.py
  decodes the request and calls run_decision_agent()
        |
        v
worker/decision_agent.py
  builds model messages and strict response schema
        |
        v
worker/model_client.py -> worker/http_json.py
  POST /v1/decision through urllib.request.urlopen()
        |
        v
external_world/model_gateway.py -> Ollama -> qwen3:1.7b
  real sampled score and reason during fresh capture
        |
        v
parse_model_assessment()
  validates and extracts review_score and reason
        |
        v
route_review_score()
  maps score to deterministic Python route
        |
        v
request_more_information branch
  None.strip() raises AttributeError
```

### Model responsibility versus Python responsibility

Qwen returns only:

```json
{"review_score": 65, "reason": "..."}
```

Qwen does not return `request_more_information`, does not return an exception,
and is not instructed to fail.

Python owns the route:

```python
if review_score < 65:
    return "approve_refund"
if review_score < 70:
    return "request_more_information"
return "escalate_specialist"
```

Python also owns the bug:

```python
elif decision_name == "request_more_information":
    serial_number = request["serial_number"]
    normalized = serial_number.strip()
```

The model introduces varying data. Deterministic application code decides what
that data means. Only the middle route reaches the unsafe assumption.

### What Retrace records

The recorded process begins here in `agent/invocation_runner.py`:

```bash
retracepython --recording <id>.retrace -m worker --request-json '<request>'
```

The worker is recorded. The long-lived agent host, model gateway, Ollama, and
demo controller are separate processes.

The gateway's Python internals are not in the worker recording, but its exact
HTTP response is captured where it crosses into the worker at
`worker/http_json.py:21`. Replay re-executes the worker's Python code and
supplies that historical HTTP result instead of contacting the model.

The recording contains the visible model response, score, reason, metadata,
downstream Python state, route, exception, and execution ordering. It does not
contain private model chain-of-thought or Ollama's token-generation internals.

## Before The Meeting

Run these steps before screen sharing so image building and extension setup do
not consume presentation time.

```bash
cd /Users/danielpatrascanu/retrace-model-decision-demo
git switch codex/traceback-first-presentation-story
git pull --ff-only
open -a Docker
docker info
make replay-example
code .
```

In VS Code:

1. Open the Command Palette.
2. Select **Dev Containers: Reopen in Container**.
3. Wait for **Retrace Model Decision Demo** in the status bar.
4. Confirm the Retrace icon appears in the activity bar.
5. Confirm `/app/worker/decision_agent.py` opens.
6. Stop any active debug session and remove old source breakpoints.

`make replay-example` is preparation, not the live presentation. It verifies
the reviewed recording, runs three offline replays, runs automated DAP checks,
and generates the workspace. During the call, `make show-failure` executes one
new replay and prints its real traceback.

If presenting directly from a clean checkout and waiting for the build is
acceptable, skip the pre-run and use `make investigate` during the call.

## Live Presentation Script

The following script is designed for approximately ten minutes.

### Part 1: Explain what changed

Show the repository README or speak directly.

Say:

> The previous version already proved deterministic replay and DAP, but it
> began with a breakpoint that we had chosen in advance. That made sense to us
> because we knew the source, but it skipped the first step of a real incident
> investigation.
>
> We changed the workflow so it now starts with the evidence an engineer would
> normally receive: the failed program's Python traceback. The traceback tells
> us which file and operation failed. We then open that exact historical
> execution in VS Code and work backward from the symptom to the model response
> that selected the route.

Point out that the application logic and genuine recording were not replaced.
The new code exposes and verifies the historical traceback.

### Part 2: Explain the application in one minute

Open `worker/decision_agent.py` and show the routing function and branches.

Say:

> The same borderline support case is sent to a sampled Qwen model. The model
> returns only a score and a reason. Python validates that response and maps
> the score to approve, request more information, or escalate.
>
> The request always has `serial_number=None`, but only the middle route reads
> it. Therefore the bug exists deterministically in Python, while the sampled
> model determines whether a particular invocation reaches it.

Show:

```text
score below 65 -> approve_refund
score 65-69    -> request_more_information
score 70+      -> escalate_specialist
```

Then show lines `114-116` and explain that the middle route assumes the serial
number is text.

### Part 3: Replay and display the historical failure

If `make replay-example` was run before the meeting, use:

```bash
make show-failure
```

From a clean checkout, use:

```bash
make investigate
```

Say while it runs:

> This is not printing a committed traceback file. The command locates the
> extracted root process from the reviewed `.retrace` recording and invokes
> Retrace's installed `replay` command in a container with networking disabled.
> It then validates that the replay produced the reviewed decision, failure,
> source line, and exit code.

When the traceback appears, point to:

```text
File "/app/worker/__main__.py", line 15, in main
  result = run_decision_agent(request)
File "/app/worker/decision_agent.py", line 116, in run_decision_agent
  normalized = serial_number.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

Say:

> We now have the normal starting evidence. The worker failed at
> `decision_agent.py:116` because something on that line was `None`. We have not
> guessed a breakpoint; the traceback has identified the first location to
> inspect.

If the output scrolls away:

```bash
cat generated/replay/presentation-traceback.log
```

Explain that this log was written from the replay that just ran.

### Part 4: Open the same recording in VS Code

If VS Code is not already open:

```bash
code .
```

Select **Dev Containers: Reopen in Container** if necessary.

Say:

> Terminal replay and VS Code both use
> `generated/recordings/selected-failure.retrace`. We are not switching to a
> cleaner reproduction or asking the model again. The Dev Container provides
> the matching Linux Python 3.12 runtime, replay binary, DAP adapter, source,
> and Retrace extension.

### Part 5: Inspect the concrete failure state

Open `/app/worker/decision_agent.py` and set the only source breakpoint at line
`116`:

```python
normalized = serial_number.strip()
```

Then:

1. Click the Retrace icon.
2. Find the Python process under `selected-failure.retrace`.
3. Click Play beside that process.
4. Wait for `breakpoint scan ... complete`.
5. Let replay stop automatically. Do not press Continue before the first stop.

Open **Run and Debug** and inspect Locals:

```text
serial_number = None
review_score = 65
decision_name = "request_more_information"
raw_model_response = {...}
```

Say:

> The traceback told us where the failure occurred. Historical Locals now tell
> us what caused it: the route loaded `serial_number=None` and called `.strip()`.
> The same frame also retains the score and route, so we can continue from the
> exception toward its cause.

### Part 6: Explain why the route executed

1. Stop the current debug session with the red square.
2. Remove or disable the line `116` breakpoint.
3. Set the only breakpoint on line `83`:

```python
decision_name = route_review_score(review_score)
```

4. Return to the Retrace sidebar and click Play again.
5. At line `83`, click **Step Into**.
6. Step Over the comparisons in `route_review_score()`.

Show:

```text
review_score = 65
65 < 65 -> false
65 < 70 -> true
result = "request_more_information"
```

Say:

> The model did not return this route name. Python derived it from the
> historical score. This is the exact control-flow transition that exposed the
> latent bug.

### Part 7: Show where score 65 came from

1. Stop the debug session.
2. Remove or disable line `83`.
3. Set the only breakpoint on line `82`:

```python
review_score, decision_reason = parse_model_assessment(raw_model_response)
```

4. Start replay from the Retrace sidebar.
5. Step Into `parse_model_assessment()`.
6. Step Over its parsing and validation statements.
7. Inspect `content`, `assessment`, `review_score`, and `decision_reason`.

Say:

> This score was not inserted by the demo controller. It was parsed from the
> model response preserved in this recording. We can inspect both the raw
> response and the application's interpreted values.

### Part 8: Prove replay does not call the model

From a host terminal, stop the live gateway if it exists:

```bash
docker compose --file compose.yaml stop model-gateway
docker compose --file compose.yaml ps model-gateway
```

The automated replay and DAP proofs have already run inside `--network none`
containers. The interactive Dev Container itself remains network-capable, so
this scene proves the same boundary by making the named gateway unavailable.

1. Stop the debug session.
2. Remove or disable line `82`.
3. Open `/app/worker/http_json.py`.
4. Set the only breakpoint on line `21`:

```python
with urlopen(request, timeout=timeout) as response:
```

5. Ensure **Raised Exceptions** is unchecked for this scene.
6. Start replay from the Retrace sidebar.
7. At line `21`, click Step Over.
8. Confirm execution moves to line `22` and `response` exists.

Say:

> The model gateway is stopped. Python still receives the original response
> immediately because Retrace captured the HTTP behavior observed by the
> worker. The parser and route then execute normally against that historical
> value. Separately, the automated proof has already demonstrated this same
> replay in a container with networking completely disabled.

This is the strongest short proof that replay is reproducing the original
external result rather than generating another model answer.

### Part 9: Optional reverse-execution scene

Restart with only line `116` enabled. Step Back once to line `115`, then move
backward toward the route and decision-evidence construction. Watch variables
disappear when moving before their assignments and reappear when moving
forward.

Say:

> We can move through the historical execution rather than merely inspecting a
> static dump. Locals reflect the selected point in time.

Python bytecode and multiline expressions do not always map to numerically
descending source lines. Explain temporal state rather than promising that
every Step Back decrements the displayed line number.

### Part 10: Close

Show this chain:

```text
recorded Qwen response
  -> review_score = 65
  -> request_more_information
  -> serial_number = None
  -> None.strip()
  -> AttributeError
```

Say:

> A new model call could produce another score and make this failure disappear.
> Retrace preserved the invocation that mattered. We reproduced it after the
> model was unavailable, started from its normal Python traceback, inspected
> the exact historical locals, and followed the application decision back to
> the model response without making another inference.

## What Every Command Means

| Command | Meaning |
| --- | --- |
| `make run` | Calls real Qwen repeatedly, records each worker, finds natural route variation and a failure, stops the gateway, replays the new failure ten times, validates DAP, and writes reports. |
| `make replay-example` | Prepares and verifies the committed genuine recording, performs three offline replays, validates DAP, and creates the VS Code workspace. It does not print the full traceback as its main presentation output. |
| `make show-failure` | Replays the already prepared root process once, prints and validates the complete traceback, and saves it to `presentation-traceback.log`. Run `make replay-example` first. |
| `make investigate` | Correct clean-checkout presentation command: `make replay-example` followed by `make show-failure`. |
| `code .` | Opens the repository so VS Code can reconnect it inside the configured Dev Container. |

## Questions The Team May Ask

### Is the failure hardcoded?

No. The Python bug is deliberately present, but fresh Qwen responses determine
whether the failing route is reached. The bundled artifact is a reviewed real
invocation in which Qwen naturally returned score `65`.

### Is the traceback a text fixture?

No. `make show-failure` invokes `replay` against the extracted root process and
captures that execution's stdout. The script then validates the resulting
traceback and writes a copy to the log.

### Why use a bundled recording?

A historical debugger should open the historical incident, not depend on
recreating it during the presentation. The bundled recording makes the
investigation predictable. `make run` remains available to demonstrate fresh
capture and model variability separately.

### Are terminal replay and VS Code debugging the same execution?

Yes. Both are prepared from
`generated/recordings/selected-failure.retrace` and its extracted root process.

### Why is the model gateway not recorded?

The incident is in the worker that consumes the model result. Retrace records
the exact HTTP response at the worker boundary. Recording the gateway would
capture gateway implementation details but would not contain the downstream
worker route and exception.

### Is the model's reasoning recorded?

The visible returned reason, score, and response metadata are recorded. Hidden
chain-of-thought and provider token-generation internals are not exposed to the
application and are not claimed by the demo.

### Could static analysis find `.strip()` on an optional value?

It could warn about the latent source-level risk. Retrace contributes the
historical execution evidence: this exact response produced score `65`, this
route ran, this concrete value was `None`, and the same incident remains
reproducible after the external model is unavailable.

## Recovery During The Presentation

If `make show-failure` reports that the selected recording is missing:

```bash
make investigate
```

If the traceback scrolls away:

```bash
cat generated/replay/presentation-traceback.log
```

If VS Code does not stop:

1. Confirm the status bar says **Dev Container: Retrace Model Decision Demo**.
2. Stop any old debug session.
3. Remove unrelated breakpoints.
4. Set only the intended breakpoint.
5. Start from the Retrace sidebar, not the ordinary Run button.
6. Wait for breakpoint scanning to complete.
7. Do not press Continue before the first automatic breakpoint stop.

If the visual debugger becomes cluttered, stop the session and restart one
scene with one breakpoint. Each restart replays the same historical recording.
