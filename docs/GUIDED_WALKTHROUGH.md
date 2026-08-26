# VS Code Replay Debugger Lab

This lab expands the README's debugger section. Complete the Dev Container
setup and prepare the reviewed recordings before starting:

```bash
python -m scripts.prepare_examples
./recordings/examples/failure.retrace --workspace
code recordings/examples/failure.code-workspace
```

Run those commands in the Dev Container terminal. The new workspace selects
the failed recording and stays attached to the container.

## Controls

The debug toolbar provides:

- **Continue**: move to the next later breakpoint hit;
- **Step Over**: advance to the next statement without entering a call;
- **Step Into**: advance into an executed Python call where history exists;
- **Step Out**: return to the caller;
- **Step Back**: move to the previous historical statement;
- **Restart**: create a fresh cursor at the beginning of the recording;
- **Stop**: end the replay session.

Adding or removing a source breakpoint sends a DAP breakpoint update. Wait for
the Debug Console to report that its scan is complete before navigating.

If a new breakpoint lies earlier than the current cursor, use **Restart**. If
it lies later, **Continue** can reach it. Continue ends the session when no
later matching hit exists.

## Lab 1: Start At The Exception Site

1. Open `worker/decision_agent.py`.
2. Set the only source breakpoint at line 116.
3. Open the Retrace sidebar.
4. Click Play beside the Python process.
5. Wait for the completed breakpoint scan and the automatic stop.

Inspect Locals:

```text
serial_number = None
review_score = 65
decision_name = "request_more_information"
raw_model_response = {...}
```

The same frame contains the immediate bad value, the model-derived score, and
the route selected from that score.

Press **Step Back** once. The cursor moves to line 115:

```python
serial_number = request["serial_number"]
```

Expand `request`. This proves that `None` came from the structured application
input rather than from `.strip()` or from the debugger.

## Lab 2: Inspect Routing

1. Stop the session.
2. Remove the line-116 breakpoint.
3. Set one breakpoint at line 83.
4. Start the recording again.
5. Press **Step Into** on `route_review_score(review_score)`.

At line 69, Locals shows `review_score = 65`.

Step Over the conditions:

```text
65 < 65  -> false
65 < 70  -> true
return "request_more_information"
```

Press **Step Out** to return to `run_decision_agent`. After the call returns,
Locals contains:

```text
decision_name = "request_more_information"
```

The model did not return this route name. Deterministic Python derived it from
the historical score.

## Lab 3: Inspect Model-Response Parsing

1. Restart with the only breakpoint at line 82.
2. Press **Step Into** on `parse_model_assessment(raw_model_response)`.
3. Step through lines 43 through 65.

Inspect:

- `response`: the complete historical normalized gateway response;
- `content`: the model's JSON text;
- `assessment`: the decoded JSON object;
- `review_score`: integer `65`;
- `decision_reason`: the original reason returned by Qwen.

Press **Step Out** to return to the caller around line 82.

This links the score used by routing to the exact model result preserved in
the recording.

## Lab 4: Inspect The Recorded HTTP Boundary

Host Ollama is not required for this lab.

1. Restart with the only breakpoint at `worker/http_json.py` line 21.
2. Confirm the session stops at `urlopen(request, timeout=timeout)`.
3. Press **Step Over**.
4. Inspect `response`.
5. Press **Step Over** again to decode and return the JSON.

The operation completes without a live inference because Retrace supplies the
HTTP result observed during recording.

You can stop Ollama on the host before this lab for an explicit offline check.
Do not start a fresh recording until Ollama is running again.

## Lab 5: Stop On The Historical Exception

1. Stop the current session.
2. Remove or disable all source breakpoints.
3. Open **Run and Debug**.
4. Under **Breakpoints**, enable **Raised Exceptions**.
5. Start the failed recording from the Retrace sidebar.

The debugger stops at line 116 and displays:

```text
AttributeError: 'NoneType' object has no attribute 'strip'
```

The call stack shows `run_decision_agent()` called from `worker.__main__.main()`.
Locals still expose the score, route, request, and missing serial number.

Disable **Raised Exceptions** before the next source-breakpoint lab.

## Lab 6: Compare The Successful Recording

Generate and open its workspace:

```bash
./recordings/examples/success.retrace --workspace
code recordings/examples/success.code-workspace
```

Set a breakpoint at line 83 and enter `route_review_score()`.

The reviewed successful trace contains score `70`:

```text
70 < 65  -> false
70 < 70  -> false
return "escalate_specialist"
```

After returning to `run_decision_agent`, continue to line 112. The execution
skips the middle branch, never evaluates line 115 or 116, and returns the
specialist action.

The structured input still contains `serial_number=None`. The difference is
the historical Qwen response and the deterministic route it selected.

## Lab 7: Debug A Fresh Recording

For any trace you create yourself:

```bash
./recordings/live/run-01.retrace --workspace
code recordings/live/run-01.code-workspace
```

Begin at line 82 or 83 because every valid model decision reaches those lines.
Then follow the route that actually exists in that recording.

- A score below 65 reaches the approve branch.
- A score from 65 through 69 reaches the failing middle branch.
- A score of 70 or higher reaches the escalation branch.

Do not expect a breakpoint on line 116 to hit in a successful trace; that line
was never executed.

## What The Lab Establishes

Taken together, the stops show one connected historical explanation:

```text
recorded HTTP response
  -> parsed score 65
  -> request_more_information route
  -> structured serial_number None
  -> None.strip()
  -> AttributeError
```

All values come from one preserved application invocation. Moving through the
recording does not request another model response and cannot replace the
original evidence with a later sampled result.
