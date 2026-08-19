# Guided Demo Walkthrough

This walkthrough demonstrates both halves of the Retrace workflow: capturing
a fresh model-dependent execution and debugging a preserved execution after
the model is unavailable.

## 1. Capture Fresh Invocations

Start Ollama and run:

```bash
make run
```

The same application request and model prompt are used for every invocation.
Qwen sampling produces different scores, which select different Python routes.
Retrace creates one recording for every invocation. The harness continues until
it observes both a successful route and a naturally selected failing route.

Point out the live rows in `generated/DEMO_RESULTS.md` and their identical
model-request hashes. These are fresh model calls and fresh recordings.

## 2. Reproduce After The Model Stops

The fresh-capture workflow stops the model gateway before replay. Show the ten
lines containing:

```text
network=none match=yes
```

Each replay restores the exact historical model response and reproduces the
same score, application route, exception, traceback, and exit code. The model
call counter remains unchanged.

## 3. Use The Bundled Recording Independently

The repository also includes an architecture-matched recording captured from
an earlier genuine Qwen invocation:

```bash
make replay-example
```

This command does not create a recording and does not contact Qwen. It verifies
the artifact's SHA-256 proof, performs three network-disabled replays, validates
DAP behavior, and prepares the VS Code workspace. This is useful when the goal
is to inspect replay without waiting for fresh model sampling.

## 4. Enter The Historical Execution

Open the repository in VS Code and select `Dev Containers: Reopen in
Container`. Open `/app/worker/decision_agent.py` and set a breakpoint on:

```python
normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
```

Click the Retrace icon, locate the Python process for
`selected-failure.retrace`, and click Play. Replay stops directly at the
historical source breakpoint.

Inspect these locals:

```text
review_score = 65
decision_name = request_more_information
serial_number = None
raw_model_response = ...
```

The debugger is showing the recorded model response and the Python state that
consumed it. It is not making another inference.

## 5. Navigate Through History

Use Step Back to move from the exception toward the model-score routing logic.
Inspect the original score and route, then continue forward to the same
failure. Call Stack, Scopes, and Locals remain available throughout the
historical execution.

## 6. Explain The Result

The platform trace identifies the invocation. Its trace and span IDs join to
the Retrace recording and proof manifest. Retrace then provides the missing
execution-level evidence: the exact model response, Python route, runtime
value, and statement that produced the incident.

The important distinction is:

```text
make run
  fresh model calls -> fresh recordings -> model stopped -> offline replay

make replay-example
  bundled genuine recording -> proof verification -> offline replay and DAP
```
