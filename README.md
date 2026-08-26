# Retrace Model-Decision Demo

This repository is a hands-on introduction to deterministic record, replay,
and time-travel debugging with Retrace.

The application sends the same borderline refund case to a real sampled Qwen
model. Qwen returns a review score, and ordinary Python maps that score to one
of three routes. Different model responses can therefore make the same input
succeed or expose a route-specific application bug.

The exercise uses the normal Retrace commands a developer would use in their
own project:

```text
python application command
        |
        v
RETRACE_RECORDING=... python <the same application command>
        |
        v
./recording.retrace --extract
        |
        v
./recording.d/<pid>.bin
        |
        v
./recording.retrace --workspace
        |
        v
VS Code + Retrace Debug Extension
```

Docker provides a clean Python 3.12 environment with Retrace already installed.
The image also installs Retrace's inactive environment hook. Ordinary `python`
commands remain unchanged until `RETRACE_RECORDING` or `RETRACE=1` is set. You
therefore record the same application command you would normally run, then use
the executable recording and extracted PidFile directly.

## What You Can Do

Two paths are available:

1. **Start immediately with reviewed recordings.** Replay and debug one real
   successful execution and one real failed execution. No model service or
   internet connection is needed after the container image has been built.
2. **Capture your own model decisions.** Run Qwen repeatedly, record each
   invocation by setting `RETRACE_RECORDING`, replay any result, and open that
   exact recording in VS Code.

By the end, you will have verified that:

- the same application input can receive different sampled model responses;
- each `.retrace` file preserves the response seen by that invocation;
- replay re-executes the Python application without requesting another model
  inference;
- a failed model-dependent execution remains reproducible;
- VS Code can inspect historical stack frames, scopes, locals, exceptions,
  forward steps, and reverse steps.

## The Application

The request in [`examples/refund-request.json`](examples/refund-request.json)
describes a GBP 125 refund for a damaged medical-device accessory. It also
contains a structured field:

```json
"serial_number": null
```

The application asks `qwen3:1.7b` for a JSON assessment containing a
`review_score` and a short reason. Sampling is enabled with temperature `1.7`,
top-p `1.0`, and no seed. The prompt and request stay the same, but valid model
responses can differ between invocations.

Python validates the model response and maps the score to a route:

```text
score below 65  -> approve_refund
score 65-69     -> request_more_information
score 70+       -> escalate_specialist
```

The latent bug exists only in the middle route:

```python
elif decision_name == "request_more_information":
    serial_number = request["serial_number"]
    normalized = serial_number.strip()
```

The input always has `serial_number=None`, but the approve and escalation
routes never read it. A model score from 65 through 69 selects the middle route
and raises:

```text
AttributeError: 'NoneType' object has no attribute 'strip'
```

This is the debugging problem Retrace preserves. Calling Qwen again may return
a score outside that range and make an ordinary rerun succeed.

The model is not instructed to fail, and the failing response is not
hardcoded. Qwen returns a valid assessment; deterministic Python contains the
unsafe assumption.

## Architecture

```text
Host
  Ollama running qwen3:1.7b                 required only for fresh capture
       |
       | model inference
       v
Docker
  model-gateway sidecar                     external to the recording
       |
       | HTTP /v1/decision
       v
  VS Code Dev Container
    Python 3.12.13
    retracesoftware 0.2.29
    retracesoftware-dap 0.2.29
    Retrace VS Code extension
       |
       v
    RETRACE_RECORDING=... python -m worker  one recorded Python process
       |
       v
    parse response -> route score -> output or AttributeError
```

Retrace wraps the finite `python -m worker` application process. The model
gateway and Ollama are external services, just as a hosted model API would be
external to a production application.

During recording, the worker makes a real HTTP request and receives a real
model response. Retrace captures the nondeterministic result at that boundary.
During replay, the same worker code runs again, but Retrace supplies the
historical HTTP result from the trace. The gateway and Qwen are not contacted.

Each bundled recording contains one root Python process and no child process.
The model provider is not a hidden child of the recorded application.

For the complete component design, see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Requirements

For bundled replay and VS Code debugging:

- Docker Desktop or Docker Engine with Compose;
- Visual Studio Code;
- the VS Code **Dev Containers** extension.

For fresh model calls and fresh recordings, also install
[Ollama](https://ollama.com/download) on the host. The Dev Container connects
to it through `host.docker.internal`.

The repository supports Docker on Linux AMD64 and Linux ARM64. On Apple
Silicon, Docker uses the native ARM64 reviewed recordings. It does not emulate
AMD64.

## 1. Clone And Open The Dev Container

Run these commands in a normal host terminal:

```bash
git clone https://github.com/retracesoftware/retrace-model-decision-demo.git
cd retrace-model-decision-demo
code .
```

In VS Code:

1. Open the Command Palette with `Cmd+Shift+P` on macOS or `Ctrl+Shift+P` on
   Linux/Windows.
2. Select **Dev Containers: Reopen in Container**.
3. Wait until the lower-left status bar says
   **Dev Container: Retrace Model Decision Demo**.
4. Open **Terminal > New Terminal**.

The first build installs the pinned Python dependencies and the Retrace VS
Code extension. The post-create step verifies and copies the correct reviewed
recordings for the container architecture into:

```text
recordings/examples/failure.retrace
recordings/examples/success.retrace
```

From this point onward, run every command in this README in the **Dev Container
terminal** unless a step explicitly says **host terminal**.

Verify the environment:

```bash
pwd
python --version
python -m pip show retracesoftware
python -m pip show retracesoftware-dap
command -v retracepython
command -v replay
python -c "from retracesoftware.retrace_venv import current_hook_pth_target; print(current_hook_pth_target().is_file())"
```

Expected highlights:

```text
/app
Python 3.12.13
Version: 0.2.29
/usr/local/bin/retracepython
/usr/local/bin/replay
True
```

If the example recordings are absent, prepare them again:

```bash
python -m scripts.prepare_examples
```

This helper only selects and verifies the architecture-matched files shipped
in the repository. It does not record, replay, or debug the application.

## 2. Replay The Bundled Failed Execution

First inspect the process tree:

```bash
./recordings/examples/failure.retrace --index
```

The JSON shows one root `exec` process with `children: []`, its original
arguments, Python version, working directory, and recording metadata.

Extract the recording:

```bash
./recordings/examples/failure.retrace --extract
```

This creates `recordings/examples/failure.d/`. Select its only recorded Python
process and replay it:

```bash
FAILURE_PID_FILE="$(find recordings/examples/failure.d -maxdepth 1 -name '*.bin' -print -quit)"
"$FAILURE_PID_FILE"
```

The historical application output includes a model score of `65`, the
`request_more_information` route, and the original traceback ending at
`worker/decision_agent.py` line 116.

The replay command returns exit code `1` because the recorded application
failed. That is the expected result, not a replay failure.

Run the same replay again:

```bash
"$FAILURE_PID_FILE"
```

It reproduces the same model response hash, route, local state, exception, and
traceback. No Ollama service is required for either replay.

## 3. Replay The Bundled Successful Execution

```bash
./recordings/examples/success.retrace --index
./recordings/examples/success.retrace --extract
SUCCESS_PID_FILE="$(find recordings/examples/success.d -maxdepth 1 -name '*.bin' -print -quit)"
"$SUCCESS_PID_FILE"
```

This execution uses the same customer request and same model-request hash. Its
historical Qwen response has score `70`, so Python selects
`escalate_specialist` and exits successfully.

The pair demonstrates the important distinction:

```text
same application input
same prompt and output schema
same Python source
same Qwen model
different sampled model response
different Python route
one success and one failure
```

## 4. Debug The Failed Recording In VS Code

Generate a workspace using the installed replay tool:

```bash
./recordings/examples/failure.retrace --workspace
code recordings/examples/failure.code-workspace
```

The second command is run inside the Dev Container terminal, so the new VS
Code window remains connected to the container and can access `/app`, the
Linux replay binary, and the recording.

In the generated workspace:

1. Open `worker/decision_agent.py`.
2. Set a breakpoint at line 116:

   ```python
   normalized = serial_number.strip()
   ```

3. Click the **Retrace** icon in the Activity Bar.
4. Expand the recording and find its Python process.
5. Click **Play** beside that process.
6. Wait until the Debug Console says the breakpoint scan is complete.

Retrace normally moves to the first matching breakpoint automatically. If the
debug toolbar is active but VS Code has not yet paused on line 116, press
**Continue** once. Do not press Continue a second time unless another later
breakpoint exists; otherwise the historical execution will finish.

Open **Run and Debug > Variables > Locals** and inspect:

```text
serial_number = None
review_score = 65
decision_name = "request_more_information"
model_name = "qwen3:1.7b"
raw_model_response = {...}
```

These are values from the preserved invocation. The debugger has not made a
new model call.

### Follow The Cause Backward

At line 116:

1. Press **Step Back** once to line 115. This shows the assignment
   `serial_number = request["serial_number"]`.
2. Inspect `request` and confirm its structured input contains
   `"serial_number": None`.
3. Continue stepping backward toward line 112 to see the selected route.
4. Restart the debug session with a breakpoint at line 83, then use
   **Step Into** to enter `route_review_score()`.
5. Confirm score `65` is not below `65`, is below `70`, and therefore returns
   `request_more_information`.
6. Restart with a breakpoint at line 82 and Step Into
   `parse_model_assessment()` to inspect the exact historical model JSON from
   which score `65` was parsed.

To stop directly on the historical exception:

1. Remove or disable source breakpoints.
2. In **Run and Debug > Breakpoints**, enable **Raised Exceptions**.
3. Stop and start the Retrace debug session again.
4. The debugger stops at line 116 with the historical `AttributeError`.

To test the recorded HTTP boundary:

1. Disable **Raised Exceptions**.
2. Set a breakpoint at `worker/http_json.py` line 21.
3. Restart the Retrace debug session.
4. Step Over the `urlopen(...)` statement.

The step completes and `response` becomes available even if Ollama is stopped,
because replay supplies the historical HTTP response.

## 5. Prepare Qwen For Fresh Capture

Skip this section if you only want to inspect the bundled recordings.

Run on the **host**, outside VS Code's Dev Container terminal:

```bash
ollama pull qwen3:1.7b
ollama list
```

Make sure Ollama is running. On macOS or Windows, opening the Ollama
application is sufficient. On Linux, expose it to the Docker bridge from a
separate host terminal:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Return to the **Dev Container terminal** and check the demo gateway:

```bash
curl --fail --silent http://model-gateway:8091/health | python -m json.tool
```

Expected:

```json
{
    "model": "qwen3:1.7b",
    "provider": "ollama",
    "status": "healthy"
}
```

The gateway is a lightweight Python sidecar. The Qwen model remains on the
host, so the repository does not download or retain a multi-gigabyte Ollama
Docker image.

## 6. Run The Application Normally

In the Dev Container terminal:

```bash
python -m worker --request-json "$(cat examples/refund-request.json)"
```

This is the ordinary application command. It calls Qwen through the gateway
but does not use Retrace.

The command can either:

- exit successfully with `approve_refund` or `escalate_specialist`; or
- select `request_more_information` and raise the expected `AttributeError`.

Both are genuine model-selected outcomes.

## 7. Record A Fresh Execution With Retrace

The Docker image enabled Retrace's environment hook while it was built. Set
`RETRACE_RECORDING` to activate recording and choose the output path, then run
the same ordinary Python command:

```bash
mkdir -p recordings/live
RETRACE_RECORDING=recordings/live/run-01.retrace python -m worker --request-json "$(cat examples/refund-request.json)"
```

This is the active-environment recording pattern:

```text
RETRACE_RECORDING=<trace path> python <normal application command and arguments>
```

`RETRACE_RECORDING` both activates the preinstalled hook and names the trace.
Without that variable, `python -m worker ...` remains the unrecorded command
shown in the previous section.

The application may succeed or fail. In both cases,
`recordings/live/run-01.retrace` should exist:

```bash
ls -lh recordings/live/run-01.retrace
./recordings/live/run-01.retrace --index
```

Record more independent invocations to observe model variation:

```bash
RETRACE_RECORDING=recordings/live/run-02.retrace python -m worker --request-json "$(cat examples/refund-request.json)"
RETRACE_RECORDING=recordings/live/run-03.retrace python -m worker --request-json "$(cat examples/refund-request.json)"
```

Every command sends the same application input. Qwen may return different
scores and reasons. Each trace keeps the outcome of its own invocation.

## 8. Replay Your Fresh Recording

Use the same public replay commands as for the bundled examples:

```bash
./recordings/live/run-01.retrace --index
./recordings/live/run-01.retrace --extract
RUN_PID_FILE="$(find recordings/live/run-01.d -maxdepth 1 -name '*.bin' -print -quit)"
"$RUN_PID_FILE"
```

Replay must reproduce the result of `run-01`, even if `run-02` and `run-03`
received different model decisions.

To prove that replay does not need Qwen, stop Ollama on the host and run:

```bash
"$RUN_PID_FILE"
```

The historical result still reappears. Start Ollama again before making any
new fresh recording.

## 9. Debug Your Fresh Recording

Generate and open a workspace for the exact trace you recorded:

```bash
./recordings/live/run-01.retrace --workspace
code recordings/live/run-01.code-workspace
```

Use the Retrace sidebar exactly as described for the bundled failure. Useful
breakpoints are:

| File and line | What it reveals |
| --- | --- |
| `worker/http_json.py:21` | The external model HTTP boundary whose result was recorded. |
| `worker/decision_agent.py:82` | The historical model response being parsed into a score and reason. |
| `worker/decision_agent.py:83` | The deterministic route selected from that score. |
| `worker/decision_agent.py:115` | The structured `serial_number` value entering the failing branch. |
| `worker/decision_agent.py:116` | The route-specific operation that raises `AttributeError`. |

If your fresh trace succeeded, lines 115 and 116 were never executed, so
breakpoints there correctly have no hit. Use lines 82, 83, or 112 to inspect
the successful route, or open the bundled failure for the exception path.

## Retrace Command Reference

Record a script with the preinstalled environment hook:

```bash
RETRACE_RECORDING=recordings/example.retrace python script.py --your-args
```

Record a module:

```bash
RETRACE_RECORDING=recordings/example.retrace python -m package.module --your-args
```

Inspect the process tree:

```bash
./recordings/example.retrace --index
```

Extract recorded processes:

```bash
./recordings/example.retrace --extract
```

Replay one extracted process:

```bash
./recordings/example.d/<pid>.bin
```

Generate a VS Code workspace:

```bash
./recordings/example.retrace --workspace
```

For a one-shot recording outside an enabled environment, the installed
launcher remains available:

```bash
retracepython --recording recordings/example.retrace -m package.module --your-args
```

Show help:

```bash
retracepython --help
replay --help
retrace --help
```

The environment hook and `retracepython` both enter the same Retrace recording
path. Executable `.retrace` and `.bin` files dispatch to the installed `replay`
tool; `retrace-dap` exposes the same recording and DAP tooling for compatibility.

## Suggested Experiments

### Compare Two Fresh Decisions

Record two invocations, replay both, and compare:

- `review_score`;
- `reason`;
- `gateway_response_id`;
- `model_response_sha256`;
- selected route;
- exit code.

The `model_request_sha256` should remain the same for the unchanged input,
while model response hashes may differ.

### Change The Input

Copy `examples/refund-request.json`, change its prompt or serial number, and
record the new command. If you replace `null` with a string, the middle route
can complete because `.strip()` receives a string.

### Debug A Successful Trace

Open `recordings/examples/success.retrace`, stop at line 83, and inspect why
score `70` selects `escalate_specialist`. Compare its locals with the bundled
failed trace.

### Verify Repeatability

Replay one extracted PID file several times. Its output and failure state must
remain the same each time, regardless of later model calls.

## Repository Map

| Path | Responsibility |
| --- | --- |
| `examples/refund-request.json` | Human-readable input used by all direct commands in this guide. |
| `worker/__main__.py` | CLI entry point for the recorded application. |
| `worker/decision_agent.py` | Prompt construction, response parsing, score routing, and route-specific bug. |
| `worker/model_client.py` | Sends the strict model request to the gateway. |
| `worker/http_json.py` | HTTP boundary whose external result Retrace records. |
| `external_world/model_gateway.py` | Calls host Ollama and normalizes the Qwen response. It is external to the worker trace. |
| `example-artifacts/` | Reviewed genuine success/failure traces for Linux AMD64 and ARM64. |
| `recordings/examples/` | Architecture-matched copies prepared for immediate use. |
| `recordings/live/` | Your own fresh traces; ignored by Git. |
| `.devcontainer/` | Reproducible Python 3.12 workspace and lightweight model-gateway sidecar. |
| `.vscode/` | Remote extension and terminal defaults plus optional direct-command tasks. |
| `scripts/` | Maintainer validation, artifact review, and CI helpers. |
| `tests/` | Unit, contract, recording-proof, replay, and DAP tests. |

The `Makefile` and the larger scripts are retained for maintainers and CI to
regenerate reviewed artifacts and run repeated assertions. They are not part
of the self-service workflow and do not replace the direct product commands in
this README.

## Troubleshooting

### Docker Is Not Running

Start Docker Desktop or Docker Engine, verify `docker info`, then choose
**Dev Containers: Rebuild and Reopen in Container**.

### Example Recordings Are Missing

Inside the Dev Container:

```bash
python -m scripts.prepare_examples
```

### The Gateway Health Check Returns 503

On the host:

```bash
ollama list
ollama pull qwen3:1.7b
```

Ensure Ollama is running, then retry the health request from the container.

### A Fresh Recording Command Exits With Code 1

If the output ends in `NoneType ... strip`, Qwen selected the known failing
route. The `.retrace` file is still valid. Extract, replay, and debug it.

If the error instead says the model provider is unavailable, fix Ollama or the
gateway before recording again.

### A Breakpoint Is Not Hit

Check that:

- the generated `.code-workspace` belongs to the recording you intend to use;
- the breakpoint is in code that the selected historical route executed;
- the Retrace debug session was started from the Retrace sidebar;
- breakpoint scanning completed before navigation;
- the source remains under `/app`, matching the recorded path.

### Continue Ends The Debug Session

Continue searches for the next later matching breakpoint. If the current
breakpoint has only one historical hit, reaching the end is expected. Restart
the debug session to return to an earlier location.

### Clean Up

Close the Dev Container window, then run in a host terminal:

```bash
docker compose --file compose.yaml --file .devcontainer/compose.yaml down --remove-orphans
```

This removes the demo containers and network. It does not delete unrelated
Docker resources or the host Ollama model.

To remove only your generated recordings:

```bash
rm -rf recordings/live recordings/examples/*.d recordings/examples/*.code-workspace
```

## Scope Of The Demo

The demo records the model response visible to the Python application and the
application code that consumes it. It does not expose hidden model
chain-of-thought or record Ollama's internal token-generation process.

The refund action is a routing example. It does not transfer money or modify a
real account. Its purpose is to make a realistic model-dependent control-flow
problem compact enough to inspect from boundary to failure.

## License

See [`LICENSE`](LICENSE).
