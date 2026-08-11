# Architecture

## Proof Claim

The demo proves one narrow, strong claim:

> A real external model can make different decisions for identical live input,
> while Retrace preserves any selected historical invocation so its exact model
> response and downstream decision can be replayed and debugged later without
> the model.

The live variation and replay determinism are measured separately. The demo
does not use a clock, counter, shuffled prompt, hardcoded response, application
RNG, or replay-only fixture to create the differing decisions.

## Runtime Shape

```text
Host VS Code / operator
        |
        | identical POST /decisions
        v
provider-neutral agent API (not recorded)
        |
        | one sanitized subprocess per invocation
        v
retracepython worker (recorded, Python 3.12)
        |
        | identical HTTP model request
        v
model gateway (not recorded) -> real local Qwen through Ollama
        |
        | structured review score + visible reason
        v
worker validates and returns the decision
```

Every worker invocation creates a separate `.retrace` file and manifest. The
parent is deliberately outside recording because it owns the long-lived async
server lifecycle and platform context. Only a small environment allowlist is
passed into the recorded worker, so parent credentials cannot accidentally
enter the recording.

## Why A Discretionary Score

The model returns a structured `review_score` from 0 to 100 and one concise
reason. A small deterministic policy maps it to one of three actions:

- `approve_refund`
- `request_more_information`
- `escalate_specialist`

Scores below 65 approve, scores from 65 through 69 request more information,
and scores of 70 or more escalate. This is a material decision, not free-text
wording variation. The model request uses positive temperature and omits
`seed`; every request hash is checked for equality.

Enum-constrained actions and native tool selection were both rejected during
design because the tested small model usually collapsed to one action. A
structured discretionary score remained valid across the probe set while
varying enough to drive materially different, policy-controlled actions. The
application still strictly validates the score, fields and rationale.

## Record And Replay Boundary

The worker reaches the gateway through Python's HTTP/socket path. Retrace
records the external socket behavior during the live run. During replay, the
same Python code runs, but the historical external result is supplied from the
recording. The gateway is stopped and each proof replay is launched in a fresh
Docker container with `--network none`.

The proof requires all ten replays to match the selected live output exactly,
including:

- chosen decision
- review score
- visible reason
- model name and provider timestamp
- gateway response ID
- model request and response hashes

The model-gateway call counter must remain unchanged across replay.

## Debugger Path

The generated recording is extracted and served through `retracesoftware-dap`.
The verifier uses the same DAP protocol as VS Code:

```text
initialize -> launch -> setBreakpoints -> configurationDone -> continue
-> stackTrace -> scopes -> variables -> stepBack -> continue
```

At `RETRACE_MODEL_DECISION_BREAKPOINT`, DAP must expose the original
`raw_model_response`, review score, resulting decision, rationale, provider
metadata and hashes. Reverse navigation is claimed only within the active
Python function.

## Portability

The parent exposes a small provider-neutral HTTP contract and launches one
recorded worker per decision. The model is reached through a separate HTTP
gateway. Either boundary can be replaced with another agent host or model
provider without changing the worker's Retrace recording, offline replay, or
DAP inspection flow.
