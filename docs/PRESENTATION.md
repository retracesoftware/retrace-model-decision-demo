# Four-Minute Presentation Script

## 0:00 - The Problem

Show the live-invocation table in `generated/DEMO_RESULTS.md`.

Say:

> These are separate calls with the same application input and the same exact
> model-request hash. The sampled model chose different scores. The common
> routes completed, but score 65 selected a rare application path and crashed.

## 0:40 - Platform Trace To Recording

Show the recording ID and telemetry section.

Say:

> The Hosted Agent trace tells us which invocation failed. The handler links
> that span to this Retrace recording. Retrace gives us the executable artifact
> behind the trace.

## 1:10 - Reproduce Without The Model

Run:

```bash
make presentation
```

Point to the three `network=none match=yes` lines.

Say:

> The model is not called here. Retrace re-executes the original Python and
> supplies the recorded model-boundary result. We get the same score, route,
> failing statement, exception, and exit code every time.

## 2:00 - Enter The Historical Execution

Open the Dev Container and set a breakpoint on:

```python
normalized = serial_number.strip()  # RETRACE_MODEL_FAILURE_BREAKPOINT
```

Start the process from the Retrace sidebar. Replay stops directly on the
historical failure breakpoint after scanning completes.

Say:

> We are now inside the failed historical invocation, not a new inference.

Show these locals:

```text
review_score = 65
decision_name = request_more_information
serial_number = None
raw_model_response = ...
```

Say:

> The model selected the more-information route. That route expected a serial
> number, but this request had None. The exact application failure is visible
> in ordinary Python state.

## 3:10 - Time Travel

Use Step Back toward routing, then continue forward to the failure.

Say:

> We can move backward from the exception toward the routing decision, inspect
> the original values, and move forward to the same failure again.

## 3:40 - Close

Say:

> Foundry tells you which agent invocation failed. Retrace lets you re-enter
> that exact historical Python execution and debug why. Even when the next
> model call behaves differently, the execution that mattered remains
> reproducible and inspectable.
