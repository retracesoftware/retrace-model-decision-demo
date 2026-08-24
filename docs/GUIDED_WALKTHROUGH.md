# Guided Incident Walkthrough

This is the presenter script for the Retrace model-decision demo. It is written
so that someone who did not build the repository can explain the application,
reproduce the historical incident, and investigate it in VS Code.

The presentation follows one question at a time:

```text
What failed?
What value caused it?
Why did this route execute?
Where did the route input come from?
How do we know replay did not ask the model again?
```

## Incident Summary

Say:

> This application handles a borderline refund request for a damaged
> medical-device accessory. A sampled language model assigns a review score,
> and ordinary Python maps that score to approve, request more information, or
> escalate.
>
> The request has no usable serial number. Most model-selected routes never
> need it and succeed. On one historical invocation, the model returned score
> 65, Python selected the request-more-information route, and that branch
> called `.strip()` on `None`.
>
> Calling the model again can produce another score and avoid the branch, so a
> normal rerun can erase the evidence. Retrace preserved the exact invocation
> that failed. We will replay it without the model, start from its traceback,
> and follow the historical values backward to the model response.

## Understand The Application Before Running It

The fixed customer input lives in `scripts/demo_state.py`:

```python
CASE = {
    "case_id": "CASE-MODEL-NONDETERMINISM-001",
    "serial_number": None,
    "user_prompt": "Sofia requests a GBP 125 refund ...",
}
```

Be precise when presenting what this request represents:

- No photo is uploaded or analyzed. The phrase saying that a photo supports
  the damage is text inside `user_prompt`.
- The day-31 timing, four-year account history, and regulated-equipment context
  are also text supplied to Qwen; the application does not query separate
  systems for them.
- `serial_number=None` is different: it is a structured request field as well
  as a fact described in the prompt. The downstream Python route reads this
  structured value.

The demo therefore proves recording and replay of a real sampled language-model
HTTP response and the Python control flow driven by that response. It does not
claim to demonstrate image analysis, policy retrieval, or account-data
retrieval.

The same customer request and the same model prompt are used on every fresh
invocation. The model gateway uses real Qwen sampling with temperature `1.7`,
top-p `1.0`, and no seed. That means the request hash stays identical while
the returned score can vary.

The model reads the prompt text and returns only a score and a reason. It does
not decide whether Python crashes. `worker/decision_agent.py` owns the
deterministic application logic:

```text
score below 65 -> approve_refund
score 65-69    -> request_more_information
score 70+      -> escalate_specialist
```

Only `request_more_information` uses the absent serial number:

```python
elif decision_name == "request_more_information":
    serial_number = request["serial_number"]
    normalized = serial_number.strip()
```

This separation is important. The model response is valid, and the application
contains a latent route-specific bug. Non-determinism determines whether that
bug is reached on a particular invocation.

### Separate the application from the demo controller

Before presenting, distinguish the code being investigated from the code that
runs the experiment:

| Code | Purpose |
| --- | --- |
| `agent/` | The incoming invocation service and per-invocation worker launcher. |
| `worker/` | The application being recorded and debugged. It calls the model boundary, validates the response, chooses a route, and fails. |
| `external_world/` | The model gateway and telemetry collector outside the recorded worker. |
| `scripts/` and `Makefile` | The controller and assertions used to prepare, repeat, and prove the demo. They are not the business application. |

The refund is a routing example, not a payment integration. Successful routes
return action descriptions; they do not transfer money or modify an account.
The point is to make a real model-dependent Python control-flow problem small
enough to inspect completely.

### Follow one invocation through the source

Use this sequence to explain the code before introducing Retrace:

1. `scripts/demo_state.py` defines `case_id`, `serial_number=None`, and the
   case prose in `user_prompt`.
2. `scripts/agent_client.py` sends the prose to the local `/invocations`
   endpoint with call, user, and trace-context headers.
3. `agent/main.py` merges that input with the fixed structured case and asks
   `agent/invocation_runner.py` to run one worker.
4. `agent/invocation_runner.py` assigns a recording ID and launches
   `retracepython -m worker --request-json ...`.
5. `worker/__main__.py` decodes the request and calls
   `run_decision_agent()`.
6. `worker/decision_agent.py` creates a system message, the case message, and
   a strict JSON schema requiring `review_score` and `reason`.
7. `worker/model_client.py` and `worker/http_json.py` POST that request to the
   model gateway. `urlopen()` is the external boundary observed by the worker.
8. `external_world/model_gateway.py` asks the real sampled Qwen model and
   returns its response plus identifiers and hashes.
9. `parse_model_assessment()` validates the response, and
   `route_review_score()` maps the integer score to a Python action.
10. The score-65 invocation selects `request_more_information`; that branch
    reads `serial_number=None` and calls `.strip()`, raising `AttributeError`.
11. `worker/__main__.py` emits failure metadata and re-raises, producing the
    traceback and exit code `1`.
12. The invocation runner saves the recording, stdout, stderr, and manifest;
    the agent endpoint returns HTTP `500` with the recording ID.

The relevant data changes are:

```text
fixed case prose
  -> Qwen message content: {"review_score": 65, "reason": "..."}
  -> parse_model_assessment(): (65, "...")
  -> route_review_score(65): "request_more_information"
  -> request["serial_number"]: None
  -> None.strip(): AttributeError
```

Say:

> Qwen does not return an exception or a route name. It returns a valid score
> and reason. Ordinary deterministic Python converts that score into a route.
> The application contains an unsafe assumption in only one route, so later
> sampled calls can choose a successful route and hide the original incident.
> The recording lets us investigate the invocation that actually mattered.

The recording contains the exact HTTP result seen by the worker and the Python
execution that consumed it. It does not contain a hidden model chain-of-thought
or Ollama's token-generation internals. The visible model reason, score, model
metadata, downstream locals, route, and exception are all inspectable.

## Prepare The Historical Incident

From the repository root, run:

```bash
docker info
make investigate
```

`make investigate` does two things.

First, `make replay-example`:

- builds the pinned Python 3.12 image,
- selects the bundled recording for Docker's native architecture,
- verifies the recording SHA and provenance manifest,
- extracts the recorded root process,
- replays it three times with networking disabled,
- checks stack, scopes, locals, exception behavior, Step Back, and Step Into,
- creates the VS Code recording workspace.

Second, `make show-failure`:

- invokes `replay` against that extracted historical root process,
- starts a new container with `--network none`,
- prints the full application output and Python traceback,
- requires the same score, route, exception, source line, and exit code,
- stores the output in `generated/replay/presentation-traceback.log`.

The replayed worker is expected to exit with code `1`. The surrounding command
only succeeds when that expected application failure matches the reviewed
historical incident exactly.

## Scene One: Start With The Traceback

On screen, find the tail of the output:

```text
File "/app/worker/__main__.py", line 15, in main
  result = run_decision_agent(request)
File "/app/worker/decision_agent.py", line 116, in run_decision_agent
  normalized = serial_number.strip()
AttributeError: 'NoneType' object has no attribute 'strip'
```

Say:

> The preserved execution reproduces the incident and identifies
> `decision_agent.py` line 116 as the failing source location. We derive the
> first breakpoint from that runtime evidence and begin the investigation
> there.

Also point out:

```text
network=none
```

Say:

> The model gateway is not running and this replay has no network interface.
> The failure is being reproduced from the Retrace recording, not from a new
> inference.

## Scene Two: Open The Recording In VS Code

Run:

```bash
code .
```

In VS Code:

1. Press `Cmd+Shift+P` on macOS or `Ctrl+Shift+P` elsewhere.
2. Select **Dev Containers: Reopen in Container**.
3. Wait until the lower-left status bar says
   **Dev Container: Retrace Model Decision Demo**.
4. Let `postCreateCommand` finish.
5. Open `/app/worker/decision_agent.py`.

The Dev Container keeps all replay paths consistent. The source, Python
3.12.13 runtime, Retrace packages, replay binary, recording, and VS Code
extension all live at the same `/app` paths used when the recording was made.

## How To Restart A Debugging Scene

Use this reset sequence before each independent breakpoint demonstration:

1. Click the red Stop square if a debug session is active.
2. Open **Run and Debug**.
3. In **Breakpoints**, remove or disable old source breakpoints.
4. Leave only the breakpoint requested by the next scene.
5. Click the Retrace icon in the left activity bar.
6. Find the Python process under `selected-failure.retrace`.
7. Click Play beside the process.
8. Wait for `breakpoint scan ... complete`.
9. Retrace stops automatically on the first matching historical location.

Do not press Continue before the initial stop. Continue means “go to the next
matching breakpoint,” so pressing it when there is only one hit can terminate
the session.

## Scene Three: What Value Caused The Failure?

Set the only source breakpoint on line `116`:

```python
normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
```

Start replay from the Retrace sidebar. When it stops, open **Run and Debug**
and inspect Locals.

Show these values:

```text
serial_number = None
review_score = 65
decision_name = "request_more_information"
model_name = "qwen3:1.7b"
raw_model_response = {...}
```

Say:

> The traceback told us where the failure happened. Historical Locals now tell
> us what made it fail: `serial_number` was actually `None`. In the same frame
> we can see the model-derived score and route that led here. These are values
> from the failed invocation, not values from a replacement run.

Why line 116 is the first breakpoint:

- it is named by the traceback,
- the failing value is present,
- the model response, parsed score, and route are still in scope,
- the debugger can now move backward from symptom toward cause.

## Scene Four: Follow The State Backward

While stopped at line `116`:

1. Press **Step Back** once. Expect line `115`, where `serial_number` is read.
2. Press **Step Back** again. Expect the route branch around line `114` or
   line `112`.
3. Continue backward toward the decision event and routing code.
4. Watch Locals as values disappear before their assignment statements.
5. Use **Step Over** forward and watch them reappear.

Say:

> In a live debugger, the bad execution is already gone. Here we can move
> backward through the execution that failed. The local value disappears when
> we cross to a time before its assignment, then reappears when we move forward
> again. This is historical state, not a second run with fresh model output.

Do not insist on a numerically descending source line at every Step Back. Python
bytecode for function calls, dictionary construction, and multiline
expressions does not map monotonically to source line numbers. The proof is
that the execution cursor moves to an earlier bytecode state and the visible
locals change consistently with that earlier state.

## Scene Five: Why Did This Branch Execute?

Restart with only line `83` enabled:

```python
decision_name = route_review_score(review_score)
```

Start replay, then press **Step Into**. You should enter
`route_review_score` around line `69`.

Step Over through the conditions:

```python
if review_score < 65:   # 65 < 65 is false
    return "approve_refund"
if review_score < 70:   # 65 < 70 is true
    return "request_more_information"
```

How to prove this visibly:

- Locals shows `review_score = 65`.
- Execution moves past the first return without entering it.
- Execution reaches the second condition and then line `72`.
- The Call Stack shows `route_review_score` above `run_decision_agent`.

Say:

> We now know why the failing branch ran. This is deterministic application
> logic consuming a model-derived value. Score 65 does not satisfy the approval
> threshold, but it does satisfy the request-more-information threshold.

Why line 83 matters:

- line 116 explains the immediate exception,
- line 83 explains the control-flow decision that made line 116 reachable,
- it connects AI output to ordinary, inspectable Python behavior.

## Scene Six: Where Did Score 65 Come From?

Restart with only line `82` enabled:

```python
review_score, decision_reason = parse_model_assessment(raw_model_response)
```

Start replay and press **Step Into**. Expect
`parse_model_assessment` around line `43`.

Use Step Over through the parser. Show:

- `response` contains the historical provider response,
- `content` contains the model's JSON text,
- `assessment` becomes the parsed object,
- `review_score` becomes `65`,
- `decision_reason` becomes the model's preserved explanation.

Then press **Step Out** and return to `run_decision_agent` around line `83`.

Say:

> The route was not guessed by the application and was not manufactured by the
> demo harness. We can inspect the exact response that this invocation received
> and watch ordinary Python parse the score that later selected the failing
> route.

Why line 82 matters:

- it is the data-conversion boundary between provider output and application
  state,
- it proves the routing score came from the historical response,
- it lets an engineer inspect schema handling and validation as they happened.

## Scene Seven: Prove The Model Was Not Called Again

Restart with only `worker/http_json.py` line `21` enabled:

```python
with urlopen(request, timeout=timeout) as response:
```

The bundled workflow has not started a model gateway. The terminal replay was
also launched with `--network none`.

From a host terminal, stop the gateway if an earlier Compose or Dev Container
session started it:

```bash
docker compose --file compose.yaml stop model-gateway
```

Start replay. At line `21`:

1. Inspect `url`, `method`, and `payload` in Locals.
2. Press **Step Over**.
3. Expect an immediate move to line `22`.
4. Inspect `response`.
5. Press **Step Over** again to return through `model_client.py` and
   `decision_agent.py`.

Say:

> This is the external non-deterministic boundary. During recording, `urlopen`
> contacted the real model gateway and Retrace captured the result. During
> interactive replay there is no gateway, yet the same call returns the
> historical response. Python after the boundary then executes normally. The
> automated proof separately verifies this path with networking disabled.

Why line 21 matters:

- it distinguishes replaying execution from merely displaying a saved final
  answer,
- it demonstrates that Retrace restores the external result at the boundary,
- the downstream parser and router still run as application code.

## Optional Scene: Exception Unwind

Restart at line `116`. Press **Step Into**.

Because `serial_number` is `None`, there is no user Python function to enter;
attribute lookup raises immediately. Retrace should move to the inspectable
exception handler in `worker/__main__.py` around line `16`.

Show that Call Stack, Scopes, and Locals remain available and that there is no
`control_runtime.py` crash.

Say:

> The debugger follows the real exception unwind into the application's
> handler. It does not expose CPython's artificial source-less frame as if it
> were application code.

This is useful engineering evidence, but it is optional in the main customer
investigation.

## Optional Scene: Raised Exception

1. Stop the current session.
2. Remove all source breakpoints.
3. In **Run and Debug → Breakpoints**, enable **Raised Exceptions**.
4. Start the recording from the Retrace sidebar.
5. Expect a stop at the historical `AttributeError` on line `116`.

This shows that Retrace can locate the exception without requiring a source
breakpoint to be configured in advance.

## The Closing Message

Say:

> We started with the same evidence an engineer normally gets: a failed
> invocation and a traceback. From that failure location, Retrace let us
> inspect the actual `None` value, move backward to the route selection,
> recover score 65 from the historical model response, and prove that the
> external HTTP result
> was replayed while the model was unavailable.
>
> A normal rerun can ask the model again and change the evidence. Retrace
> preserves the execution that actually mattered. It turns a non-reproducible
> AI-dependent incident into a deterministic Python debugging session.

## If Someone Asks Whether The Recording Is Genuine

Say:

> The bundled artifact was captured by the full `make run` workflow from a real
> sampled Qwen invocation. Its recording hash, model digest, model request and
> response hashes, Python and Retrace versions, source revision, trace ID, span
> ID, and platform context are bound in the adjacent proof manifest. The
> bundled path verifies that manifest before replay.

Show:

```text
generated/recordings/selected-failure.proof.json
```

If time and local model availability permit, `make run` creates a new set of
live decisions and recordings. It sends identical requests until it observes
at least two distinct decisions plus a naturally selected failure, then stops
the model gateway and replays the newly captured failure ten times offline.

## Final Automated Check

Inside the Dev Container, run:

```bash
python /app/scripts/verify_dap.py \
  --recording /app/generated/recordings/selected-failure.retrace \
  --expected /app/generated/recordings/selected-failure.expected.json
```

The final line must begin with:

```text
dap=pass
```

## Cleanup

From a host terminal:

```bash
make clean
```

This stops only this demo's Compose services and clears generated demo output.
It does not globally prune Docker.
