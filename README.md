# Retrace Nondeterministic Model-Decision Demo

This repository demonstrates why deterministic record and replay matters for
AI applications.

A real local language model receives the exact same borderline refund case on
every invocation. Sampling is enabled, so separate live calls can produce
different review scores and drive different application decisions. Retrace
records every invocation independently, preserves one exact historical model
response, and later replays and debugs that decision without contacting the
model again.

The complete proof includes:

1. A real `qwen3:1.7b` model served by Ollama.
2. Microsoft's official Responses-compatible agent host.
3. One short-lived `retracepython` worker and one recording per invocation.
4. Different material decisions from identical live model requests.
5. Ten exact replays of one selected decision with Docker networking disabled.
6. DAP inspection of the historical model response and downstream Python
   decision logic.
7. A VS Code Dev Container configured with the Retrace debugger extension.

This demo records the model's externally visible structured response and its
concise stated reason. It does not claim to expose hidden chain-of-thought or
the model's internal neural execution.

## Why This Matters

Without Retrace, rerunning a nondeterministic AI workflow can replace the
evidence you need to understand the original decision:

```text
same application input -> new model call -> different response -> old evidence lost
```

With Retrace:

```text
historical invocation -> recording -> exact offline replay -> inspect original state
```

The demo separates two claims and proves both:

- **Live variation:** identical requests can produce different scores and
  application actions.
- **Replay determinism:** one selected historical invocation can be reproduced
  exactly after the model is stopped and networking is removed.

## The Decision Scenario

The agent reviews this same case every time:

```text
Alice requests a GBP 125 refund for a damaged medical-device accessory.
It is day 31 of a 30-day self-service window. A photo supports packaging
damage, but the serial number is partly obscured. Alice has four years of
good account history and no previous refunds. The accessory is not
safety-critical but accompanies regulated equipment.
```

The model returns strict JSON containing a discretionary score and a visible
customer-facing reason:

```json
{
  "review_score": 68,
  "reason": "The evidence supports the claim, but the serial number needs verification."
}
```

Ordinary Python code converts the score into a material action:

```text
score below 65  -> approve_refund
score 65-69     -> request_more_information
score 70+       -> escalate_specialist
```

There is no clock, counter, shuffled prompt, application-side random choice,
or hardcoded rotating response. The exact model-request SHA-256 hash must be
identical on every live invocation. Variation comes from the real sampled
model call.

## Requirements

- Git
- Docker Desktop or Docker Engine with Docker Compose
- Ollama
- approximately 3 GB of free disk space
- internet access for the initial image, package, and model downloads
- VS Code plus the Dev Containers extension for visual replay debugging

The demo runs in a pinned Linux/amd64 Python 3.12.13 container. It installs:

```text
retracesoftware==0.2.25
retracesoftware-dap==0.2.25
azure-ai-agentserver-core==2.0.0
azure-ai-agentserver-responses==2.0.0b1
```

You do not need Python or Retrace installed on the host. Docker supplies the
matching Python and Retrace environment.

### Install Ollama

Install Ollama from [ollama.com](https://ollama.com/), then confirm it is
available:

```bash
ollama --version
```

Start the Ollama service in a terminal:

```bash
ollama serve
```

Leave that terminal running while using the live demo.

### Prepare VS Code

Install the Dev Containers extension:

```bash
code --install-extension ms-vscode-remote.remote-containers
```

If `code` is unavailable in a macOS terminal, open VS Code and run
**Shell Command: Install 'code' command in PATH** from the Command Palette.

## Get The Demo

```bash
git clone https://github.com/retracesoftware/retrace-model-decision-demo.git
cd retrace-model-decision-demo
```

Confirm you are on the unmodified `main` branch:

```bash
git status
```

Expected result:

```text
On branch main
nothing to commit, working tree clean
```

## Part 1: Run The Complete Live Proof

Make sure Docker and `ollama serve` are running, then execute:

```bash
make run
```

That is the complete quick start. The first run downloads the pinned Qwen
model and builds the Python 3.12 image, so it takes longer than later runs.

### What `make run` does

`make run` performs the following checks in order:

1. Verifies that the Docker engine is reachable before downloading anything.
2. Pulls `qwen3:1.7b` through Ollama.
3. Verifies the model digest expected by this reviewed demo.
4. Builds the pinned Python 3.12.13 Linux/amd64 image.
5. Starts Microsoft's `ResponsesAgentServerHost` on port `8088`.
6. Starts the HTTP model gateway connected to the real Ollama model.
7. Sends the exact same Responses request repeatedly.
8. Runs every invocation in a separate short-lived `retracepython` worker.
9. Creates one `.retrace` recording and manifest per live invocation.
10. Continues until the model has produced at least two distinct application
   decisions, with a maximum of 20 live calls.
11. Verifies every live model request has the same SHA-256 hash.
12. Selects the first historical invocation.
13. Stops the model gateway.
14. Replays the selected recording ten times in ten fresh containers with
    `--network none`.
15. Requires every complete replayed output to match the selected live output.
16. Verifies the model-call counter did not increase during replay.
17. Uses DAP to inspect stack, scopes, locals, the historical response, score,
    reason, selected action, identifiers, and hashes.
18. Exercises reverse and forward navigation around the decision function.
19. Generates a VS Code workspace and a readable proof report.
20. Stops and removes the temporary Compose services.

The demo intentionally fails instead of manufacturing variety if the real
model does not produce two valid decisions within 20 identical live calls.

### What successful output looks like

The live section should show the same request hash with different scores or
decisions, for example:

```text
live=01 decision=escalate_specialist score=85 request_sha256=c6c45a73aa7ae42f
live=02 decision=escalate_specialist score=70 request_sha256=c6c45a73aa7ae42f
live=03 decision=approve_refund score=40 request_sha256=c6c45a73aa7ae42f
```

The replay section should show ten exact matches:

```text
replay=01 decision=escalate_specialist ... network=none match=yes
...
replay=10 decision=escalate_specialist ... network=none match=yes
```

The DAP result should end with:

```text
dap=pass model_response=historical decision=historical reason=historical stack=pass scopes=pass locals=pass step_back=in-frame forward_return=pass
```

The live values are expected to vary from these examples. The important
properties are:

- all live request hashes are identical
- at least two application decisions are observed
- all ten replays match the selected historical decision
- replay runs with `network=none`
- the model-call counter does not increase during replay
- DAP reports `pass`

## Read The Generated Evidence

Open the main report:

```bash
code generated/DEMO_RESULTS.md
```

or on macOS:

```bash
open generated/DEMO_RESULTS.md
```

The generated artifacts include:

```text
generated/DEMO_RESULTS.md
generated/run-summary.json
generated/recordings/selected-decision.retrace
generated/recordings/selected-decision.expected.json
generated/recordings/selected-decision.code-workspace
generated/manifests/*.json
generated/responses/live-*.json
generated/replay/replay-01.log ... replay-10.log
generated/transcripts/dap.json
generated/counters/model-gateway.json
```

Important files:

```text
generated/DEMO_RESULTS.md
    Human-readable comparison of varying live decisions and exact replays.

generated/run-summary.json
    Structured proof containing requests, hashes, recordings, decisions,
    replay results, and model-call counts.

generated/recordings/selected-decision.retrace
    The selected historical model invocation preserved by Retrace.

generated/recordings/selected-decision.expected.json
    The exact visible response and application result expected during replay.

generated/transcripts/dap.json
    Raw debugger transcript proving stack, scopes, locals, and navigation.
```

Confirm the recording and report are nonempty:

```bash
ls -lh generated/recordings/selected-decision.retrace
ls -lh generated/DEMO_RESULTS.md
ls -lh generated/transcripts/dap.json
```

Confirm replay made no new model call:

```bash
python3 - <<'PY'
import json
from pathlib import Path

summary = json.loads(Path("generated/run-summary.json").read_text())
print("before:", summary["model_calls_before_replay"])
print("after: ", summary["model_calls_after_replay"])
PY
```

The two numbers must be equal.

## Part 2: Debug The Exact Historical Decision In VS Code

Complete Part 1 first if you want to inspect your fresh model decision. Do not
run `make clean` between Part 1 and Part 2 because cleanup removes generated
artifacts.

The repository also contains a reviewed historical recording, so the VS Code
walkthrough works even before a new live run.

### 1. Open the repository in VS Code

From the repository root:

```bash
code .
```

### 2. Reopen the project in the Dev Container

In VS Code:

1. Open the Command Palette with `Cmd+Shift+P` on macOS or `Ctrl+Shift+P` on
   Linux.
2. Run **Dev Containers: Reopen in Container**.
3. Wait for the container build and remote extension installation to finish.
4. Confirm the lower-left corner identifies the Retrace Model Decision Demo
   Dev Container.

VS Code remains on the host. The source, Python 3.12 environment, recording,
Retrace extension, replay executable, and DAP adapter run inside the Linux
container at `/app`.

The Dev Container automatically:

- installs the Retrace Debug Extension in the remote extension host
- copies the reviewed recording if no fresh recording exists
- extracts the selected recording
- generates its `.code-workspace`
- runs the automated DAP preflight
- prints the source file and breakpoint marker

### 3. Verify the debugger automatically

Open a terminal inside the Dev Container and run:

```bash
python /app/scripts/verify_dap.py \
  --recording /app/generated/recordings/selected-decision.retrace \
  --expected /app/generated/recordings/selected-decision.expected.json
```

Expected output:

```text
dap=pass model_response=historical decision=historical reason=historical stack=pass scopes=pass locals=pass step_back=in-frame forward_return=pass
```

This is the same DAP protocol used by the VS Code extension.

### 4. Set the source breakpoint

Open:

```text
/app/worker/decision_agent.py
```

Find this marker:

```python
decision_evidence = {  # RETRACE_MODEL_DECISION_BREAKPOINT
```

Set a breakpoint on that line.

### 5. Start historical replay debugging

In VS Code:

1. Click the Retrace icon in the left activity bar.
2. Find the Python process under `selected-decision.retrace`.
3. Click Play beside that Python process.
4. Wait for breakpoint scanning to complete.
5. Retrace initially enters its debugger entry state. Press `F5` or
   **Continue** once.
6. Replay stops at `RETRACE_MODEL_DECISION_BREAKPOINT`.

An early message such as:

```text
stackTrace: no active cursor: replay is not stopped at an inspectable position
```

is expected before Continue moves replay to the historical breakpoint. It is
not evidence that breakpoint scanning failed.

### 6. Inspect the preserved decision

Open **Run and Debug**, expand **Variables** and **Locals**, and inspect:

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
```

These values must match:

```text
generated/recordings/selected-decision.expected.json
generated/DEMO_RESULTS.md
```

Use **Step Back**, **Continue**, **Step Over**, **Step Into**, **Step Out**,
**Call Stack**, **Scopes**, and **Locals** to inspect how ordinary Python:

1. received the historical model response
2. parsed its strict JSON
3. validated the score and reason
4. mapped the score to the application action
5. returned the preserved decision evidence

The debugger is not making a fresh model call. It is replaying the selected
historical invocation.

## Use The Bundled Historical Recording

The repository includes a reviewed recording captured by the complete live
workflow:

```text
example-artifacts/selected-decision.retrace
example-artifacts/selected-decision.expected.json
example-artifacts/DEMO_RESULTS.example.md
```

That reviewed run sent the same real model request three times and received
scores `85`, `70`, and `40`, producing both `escalate_specialist` and
`approve_refund`. The selected score-85 invocation then passed ten exact
network-disabled replays and DAP verification.

To inspect it without making a new model call:

1. Clone the repository.
2. Run `code .`.
3. Select **Dev Containers: Reopen in Container**.
4. Follow Part 2 beginning with the automatic DAP verification.

The Dev Container copies the reviewed recording under `generated/` when no
fresh recording exists.

## Run Source Tests

With Docker running:

```bash
make build
make test
```

The tests cover:

- strict model-output validation
- score-to-action policy boundaries
- stable prompt and Responses request construction
- enabled nondeterministic sampling with no supplied seed
- exact request hashing
- one worker and recording per invocation
- Microsoft Responses-host behavior
- parent/worker environment and secret isolation
- DAP access to the bundled historical recording in CI

## Useful Commands

```bash
make run       # pull the real model and execute the complete proof
make model     # pull only the reviewed Ollama model
make build     # build the Python 3.12 demo image
make demo      # run the proof without pulling the model first
make test      # run lint, formatting, and unit tests in Docker
make status    # show this demo's Compose services
make logs      # show service logs
make clean     # remove this demo's containers, volumes, and generated output
```

## Troubleshooting

### Ollama is not reachable

If the demo reports that Ollama is unavailable, start it:

```bash
ollama serve
```

Then verify its API:

```bash
curl http://127.0.0.1:11434/api/tags
```

### Docker is not reachable

Start Docker Desktop or Docker Engine and wait until it reports that the
engine is running. Confirm it from the terminal:

```bash
docker info
```

Then run `make run` again. If the model was already downloaded successfully,
you may resume without pulling it again:

```bash
make demo
```

### The model is missing

Run:

```bash
make model
```

Then confirm it is installed:

```bash
ollama list
```

### The model digest is different

The demo pins a reviewed Qwen model digest so a silently changed model cannot
be presented as the same validated demo. If Ollama reports a different digest,
do not bypass the check for a presentation. Review and revalidate that model
version first.

### The model did not produce two decisions

Variation is genuine, not scripted. The proof allows up to 20 identical live
calls. If all 20 valid outputs map to one action, the command fails honestly.
Run it again rather than editing the prompt, thresholds, or recorded output
during a presentation.

### Docker consumes too many resources

The Compose services have explicit CPU and memory limits, and each offline
replay container is limited to one CPU and 768 MB. Clean this demo's stopped
state with:

```bash
make clean
```

Inspect Docker usage with:

```bash
docker system df
```

Do not run multiple copies of the demo concurrently on a presentation laptop.

### VS Code does not stop at the breakpoint

Check that:

- VS Code says it is connected to the Dev Container
- the breakpoint is in `/app/worker/decision_agent.py`
- you selected the process under `selected-decision.retrace`
- breakpoint scanning has completed
- you pressed Continue once after the initial entry state
- the automated `verify_dap.py` command passes

If necessary, stop the debug session, run **Developer: Reload Window**, start
the recorded process again, wait for scanning, and press `F5`.

## Architecture And Claim Boundaries

The runtime shape is:

```text
host operator / VS Code
        |
        | identical POST /responses
        v
Microsoft ResponsesAgentServerHost (not recorded)
        |
        | sanitized subprocess environment
        v
retracepython worker (recorded)
        |
        | identical HTTP request
        v
model gateway -> real local Qwen through Ollama
        |
        | structured score and visible reason
        v
ordinary Python validation and action routing
```

The parent host remains outside the recording because it owns the long-lived
server lifecycle and platform context. A sanitized worker records one finite
invocation. The recording therefore preserves the application/model boundary
without capturing parent credentials.

This repository proves a real Microsoft Responses-contract-compatible local
agent architecture. It does not claim that this exact image has been deployed
to Microsoft Foundry, that Ollama is an Azure-hosted model, or that Retrace can
inspect private model internals.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full process,
record/replay, debugger, security, and Microsoft compatibility design.

## Cleanup

Remove generated recordings, reports, containers, networks, and volumes owned
by this demo:

```bash
make clean
```

The reviewed recording under `example-artifacts/` and the host Ollama model
remain available.

## License

Apache-2.0. See [LICENSE](LICENSE).
