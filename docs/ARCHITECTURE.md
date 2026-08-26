# Architecture

## Purpose

This demo isolates one common AI-application debugging problem:

> The same application input can receive a different model response on a later
> run, so rerunning the application can destroy the evidence needed to explain
> the original behavior.

Retrace records the finite Python invocation that consumes the model response.
It can then replay and debug that invocation without making another inference.

## Causality Chain

The reviewed failed execution has this complete value-to-control-flow chain:

```text
Qwen HTTP response
  message.content = {"review_score": 65, "reason": "..."}
                     |
                     v
parse_model_assessment()
  review_score = 65
                     |
                     v
route_review_score()
  decision_name = "request_more_information"
                     |
                     v
request["serial_number"]
  serial_number = None
                     |
                     v
serial_number.strip()
  AttributeError
```

The model response is valid. The application bug is the route-specific
assumption that an optional serial number is always a string.

## Runtime Components

```text
host process
  Ollama + qwen3:1.7b
      |
      | /api/chat
      v
Docker sidecar
  external_world.model_gateway
      |
      | /v1/decision
      v
Dev Container
  retracepython -m worker --request-json ...
      |
      +-- worker.__main__
      +-- worker.decision_agent
      +-- worker.model_client
      +-- worker.http_json
```

### Ollama

Ollama is the real model provider. It is required only to make fresh calls.
The model is configured with temperature `1.7`, top-p `1.0`, top-k `100`, and
no seed.

### Model Gateway

`external_world/model_gateway.py` is a lightweight service outside the
recorded process. It:

- accepts the application request and strict JSON schema;
- sends a real request to Ollama;
- returns Qwen's message, model metadata, response ID, sampling options, and
  request hash;
- provides a stable HTTP boundary representative of a hosted model API.

The gateway does not manufacture the score or choose a Python route.

### Worker

`python -m worker` is the application recorded by Retrace. It is one finite
Python process with no child process. It:

1. parses `--request-json`;
2. builds model messages and an output schema;
3. calls the model gateway over HTTP;
4. validates the returned JSON;
5. maps the score to an application route;
6. returns an action or raises the route-specific exception.

The worker emits a structured `model_decision_selected` event before returning
or failing. This makes terminal output easy to compare without changing the
application's control flow.

## Why The Gateway Is Outside The Recording

Retrace records an application's interactions with nondeterministic external
systems. A production Python service normally calls a model provider through
HTTP; it does not execute the provider's inference engine inside the same
Python process.

The same boundary is used here:

```text
record phase
  worker executes urlopen()
  gateway calls Qwen
  HTTP response crosses into worker
  Retrace records that external result

replay phase
  worker reaches the same urlopen() boundary
  Retrace returns the recorded result
  gateway and Qwen are not called
```

Recording Ollama's token-generation internals would answer a different
question and produce a much larger, provider-specific artifact. The useful
application evidence is the exact response the Python program received and
how the program transformed it.

## Application Input

The direct user workflow reads `examples/refund-request.json`:

```json
{
  "case_id": "CASE-MODEL-NONDETERMINISM-001",
  "serial_number": null,
  "user_prompt": "Sofia requests a GBP 125 refund ..."
}
```

The photo, account history, date, and equipment context are facts described in
the prompt. No image is uploaded, and no separate account service is queried.
The structured `serial_number` field is consumed by Python after routing.

## Model And Application Responsibilities

Qwen returns only:

```json
{
  "review_score": 65,
  "reason": "..."
}
```

Python owns the routing thresholds:

```text
score < 65  -> approve_refund
score < 70  -> request_more_information
otherwise   -> escalate_specialist
```

This keeps the failure realistic and inspectable. Model nondeterminism changes
an input to deterministic business logic; ordinary Python then succeeds or
fails based on that value.

## Direct Record And Replay Lifecycle

The self-service path contains no demo wrapper around Retrace:

```text
python -m worker ...
  ordinary application run

RETRACE_RECORDING=recordings/live/run-01.retrace python -m worker ...
  same command recorded through the preinstalled environment hook

./recordings/live/run-01.retrace --index
  inspect recorded process metadata

./recordings/live/run-01.retrace --extract
  extract executable per-process PidFiles

./recordings/live/run-01.d/<pid>.bin
  re-execute the application against recorded external results

./recordings/live/run-01.retrace --workspace
  generate a VS Code workspace selecting that recording
```

The `.retrace` recording is the source artifact. Extraction creates a `.d`
directory containing one root `.bin` PidFile for this application.

The image enables Retrace's environment hook during its build. The hook is
inactive for ordinary Python commands and enters the recording path only when
`RETRACE_RECORDING`, `RETRACE=1`, or `RETRACE_CONFIG` activates it.

## Reviewed Recordings

The repository ships one real successful and one real failed recording for
each supported Docker architecture:

```text
example-artifacts/linux-amd64/
example-artifacts/linux-arm64/
```

`scripts.prepare_examples` verifies the matching proof manifest and copies the
native pair to `recordings/examples/` when the Dev Container is created.

The reviewed pair shares:

- application request;
- model request hash;
- Python source hash;
- Python and Retrace versions;
- Qwen model name and digest.

It differs in model response hash, review score, route, and outcome. The pair
is an immediate exploration path, not a substitute for fresh capture.

## Dev Container

The Dev Container provides:

- Python 3.12.13;
- `retracesoftware==0.2.29`;
- `retracesoftware-dap==0.2.29`;
- the Retrace VS Code extension in the remote extension host;
- the source tree mounted at `/app`;
- a non-root `vscode` user whose UID is aligned by Dev Containers on Linux;
- a persistent workspace process capped at 2 GB and two CPUs;
- a model-gateway sidecar capped at 256 MB and half a CPU.

No recording is globally pinned in `.vscode/settings.json`. The generated
`.code-workspace` file selects the user's chosen fresh or reviewed trace.

The Ollama model is not baked into a Docker image. Fresh capture uses host
Ollama through `host.docker.internal`; bundled replay does not require it.

## DAP Flow

The generated workspace points the extension at a specific `.retrace` file.
The extension asks the recording index for its Python process and starts the
Go-owned DAP adapter for the selected PidFile.

For a source breakpoint, the adapter:

1. launches a replay cursor;
2. scans the historical execution for matching source locations;
3. moves to the first matching hit;
4. exposes stack, scopes, and locals through DAP;
5. handles forward and reverse navigation against the preserved execution.

Useful causal stops are:

```text
http_json.py:21       recorded external response boundary
decision_agent.py:82  response parsed into score and reason
decision_agent.py:83  score mapped to application route
decision_agent.py:115 optional input loaded by that route
decision_agent.py:116 failing operation
```

## Determinism Claims

The demo verifies these claims:

- a recording preserves the exact model result observed by one invocation;
- replay does not call the live model gateway;
- replay reproduces the original route, output or exception, and exit code;
- DAP exposes historical application state at recorded source locations;
- a later model response does not alter an earlier trace.

It does not claim to expose hidden chain-of-thought, reproduce model-provider
internals, analyze images, process real payments, or retrieve real account
data.

## Maintainer Automation

The `Makefile`, `agent/`, and most of `scripts/` support CI, repeated model
experiments, proof manifests, telemetry correlation, artifact promotion, and
recording-backed DAP regression checks. Those components establish that the
reviewed artifacts are genuine and stable.

They are deliberately outside the primary user path. A developer learning
Retrace should first follow the direct commands in the repository README.
