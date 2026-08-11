from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from agent.manifest import sha256_file
from scripts.demo_state import GENERATED, ROOT, canonical_json, reset_generated
from scripts.responses_client import post_response, response_request


COMPOSE = ["docker", "compose", "--file", str(ROOT / "compose.yaml")]
IMAGE = "retrace-model-decision-demo:py312"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:1.7b")
OLLAMA_HOST_URL = os.environ.get("OLLAMA_HOST_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL_DIGEST = os.environ.get(
    "OLLAMA_MODEL_DIGEST",
    "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7",
)
MINIMUM_DISTINCT_DECISIONS = 2
MAXIMUM_LIVE_INVOCATIONS = 20
REPLAY_COUNT = 10


def heading(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def run(
    command: list[str],
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def compose(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return run([*COMPOSE, *arguments], capture=capture)


def in_offline_container(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--memory",
            "768m",
            "--cpus",
            "1",
            "--volume",
            f"{ROOT}:/app",
            "--workdir",
            "/app",
            IMAGE,
            *command,
        ],
        check=check,
        capture=True,
    )


def verify_real_model() -> dict[str, Any]:
    try:
        with urlopen(f"{OLLAMA_HOST_URL.rstrip('/')}/api/tags", timeout=5) as response:
            tags = json.load(response)
    except (OSError, URLError, TimeoutError) as error:
        raise RuntimeError(
            "Ollama is not reachable. Start Ollama and run "
            f"`ollama pull {OLLAMA_MODEL}` before this demo."
        ) from error
    models = {str(item.get("name")): item for item in tags.get("models", [])}
    if OLLAMA_MODEL not in models:
        raise RuntimeError(
            f"required real model {OLLAMA_MODEL!r} is not installed; run "
            f"`ollama pull {OLLAMA_MODEL}`"
        )
    model = models[OLLAMA_MODEL]
    actual_digest = str(model.get("digest", ""))
    if actual_digest != OLLAMA_MODEL_DIGEST:
        raise RuntimeError(
            f"model {OLLAMA_MODEL!r} has unverified digest {actual_digest!r}; "
            f"expected {OLLAMA_MODEL_DIGEST!r}"
        )
    return model


def manifest_paths() -> set[Path]:
    return set((GENERATED / "manifests").glob("*.json"))


def invoke_live(number: int) -> dict[str, Any]:
    before = manifest_paths()
    status, response = post_response("http://localhost:8088/responses")
    response_path = GENERATED / "responses" / f"live-{number:02d}.json"
    response_path.write_text(
        json.dumps({"status": status, "body": response}, indent=2, sort_keys=True)
        + "\n"
    )
    if status != 200:
        raise AssertionError(
            f"live invocation {number} failed with HTTP {status}: {response!r}"
        )
    created = manifest_paths() - before
    if len(created) != 1:
        raise AssertionError(
            f"live invocation {number} created {len(created)} manifests: {created}"
        )
    manifest_path = created.pop()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("worker_exit_code") != 0 or not manifest.get("recording_available"):
        raise AssertionError(f"invalid recorded invocation: {manifest}")
    output = manifest.get("output")
    if not isinstance(output, dict):
        raise AssertionError(f"recorded invocation omitted output: {manifest}")
    return {"manifest_path": str(manifest_path), "manifest": manifest, **output}


def counter_count() -> int:
    path = GENERATED / "counters" / "model-gateway.json"
    return int(json.loads(path.read_text())["count"])


def container_path(host_path: Path) -> Path:
    return Path("/app") / host_path.relative_to(ROOT)


def parse_worker_output(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "decision" in payload:
            return payload
    raise AssertionError(f"replay produced no model decision JSON:\n{output}")


def prepare_selected_recording(first: dict[str, Any]) -> tuple[Path, Path]:
    source = Path(str(first["manifest"]["recording_path"]).replace("/app/", f"{ROOT}/"))
    selected = GENERATED / "recordings" / "selected-decision.retrace"
    expected = GENERATED / "recordings" / "selected-decision.expected.json"
    shutil.copy2(source, selected)
    selected.chmod(selected.stat().st_mode | 0o111)
    expected.write_text(
        json.dumps(
            {
                key: first[key]
                for key in (
                    "case_id",
                    "review_score",
                    "decision",
                    "reason",
                    "model",
                    "created_at",
                    "gateway_response_id",
                    "model_request_sha256",
                    "model_response_sha256",
                )
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return selected, expected


def replay_ten_times(
    recording: Path,
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    extracted = recording.with_suffix(".d")
    shutil.rmtree(extracted, ignore_errors=True)
    extraction = in_offline_container([str(container_path(recording)), "--extract"])
    if extraction.returncode != 0:
        raise AssertionError(f"offline extraction failed:\n{extraction.stdout}")
    index = json.loads((extracted / "index.json").read_text())
    pid = int(index["root"]["pid"])
    pidfile = container_path(extracted) / f"{pid}.bin"
    expected_json = canonical_json(expected)
    expected_sha256 = hashlib.sha256(expected_json.encode()).hexdigest()
    proof = []
    for number in range(1, REPLAY_COUNT + 1):
        replay = in_offline_container([str(pidfile)], check=False)
        log_path = GENERATED / "replay" / f"replay-{number:02d}.log"
        log_path.write_text(replay.stdout)
        if replay.returncode != 0:
            raise AssertionError(
                f"offline replay {number} exited {replay.returncode}:\n{replay.stdout}"
            )
        output = parse_worker_output(replay.stdout)
        output_json = canonical_json(output)
        output_sha256 = hashlib.sha256(output_json.encode()).hexdigest()
        if output_json != expected_json:
            raise AssertionError(
                f"replay {number} changed the model decision:\n"
                f"expected={expected_json}\nactual={output_json}"
            )
        if output_sha256 != expected_sha256:
            raise AssertionError("canonical output hash changed despite equal JSON")
        proof.append(
            {
                "replay": number,
                "decision": output["decision"],
                "gateway_response_id": output["gateway_response_id"],
                "output_sha256": output_sha256,
                "network": "none",
                "match": True,
            }
        )
        print(
            f"replay={number:02d} decision={output['decision']} "
            f"output_sha256={output_sha256[:16]} network=none match=yes"
        )
    return proof


def verify_dap(recording: Path, expected_path: Path) -> str:
    result = in_offline_container(
        [
            "python",
            "/app/scripts/verify_dap.py",
            "--recording",
            str(container_path(recording)),
            "--expected",
            str(container_path(expected_path)),
        ],
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"DAP verification failed:\n{result.stdout}")
    return result.stdout


def generate_workspace(recording: Path) -> str:
    result = in_offline_container(
        [
            "retrace-dap",
            "--recording",
            str(container_path(recording)),
            "--workspace",
        ]
    )
    return result.stdout


def verify_secret_boundary(recordings: list[Path]) -> None:
    canary = b"RETRACE_PARENT_SECRET_MUST_NOT_ENTER_RECORDING"
    for recording in recordings:
        if canary in recording.read_bytes():
            raise AssertionError(f"parent secret leaked into {recording}")


def write_results(
    *,
    model: dict[str, Any],
    live: list[dict[str, Any]],
    replay_proof: list[dict[str, Any]],
    selected: Path,
    counter_before: int,
    counter_after: int,
) -> None:
    decisions = sorted({str(item["decision"]) for item in live})
    request_hashes = sorted({str(item["model_request_sha256"]) for item in live})
    summary = {
        "status": "passed",
        "python": "3.12.13",
        "model": OLLAMA_MODEL,
        "model_digest": model["digest"],
        "identical_responses_request": response_request(),
        "live_invocations": live,
        "distinct_live_decisions": decisions,
        "model_request_sha256_values": request_hashes,
        "selected_recording": str(selected),
        "selected_recording_sha256": sha256_file(selected),
        "offline_replays": replay_proof,
        "model_calls_before_replay": counter_before,
        "model_calls_after_replay": counter_after,
        "dap": "passed",
    }
    (GENERATED / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    live_rows = "\n".join(
        f"| {index} | {item['review_score']} | `{item['decision']}` | {item['reason']} | "
        f"`{item['model_response_sha256'][:16]}` | `{item['manifest']['recording_id']}` |"
        for index, item in enumerate(live, start=1)
    )
    replay_rows = "\n".join(
        f"| {item['replay']} | `{item['decision']}` | "
        f"`{item['gateway_response_id']}` | `{item['output_sha256'][:16]}` | yes |"
        for item in replay_proof
    )
    report = f"""# Retrace Nondeterministic Model Decision Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`{OLLAMA_MODEL}` model.

- Identical live application input: yes
- Identical exact model request hash: `{request_hashes[0]}`
- Distinct live model decisions: {", ".join(f"`{item}`" for item in decisions)}
- Every live invocation recorded separately: yes
- Selected historical recording: `{selected}`
- Fresh offline replays: {len(replay_proof)} of {REPLAY_COUNT} exact matches
- Model calls during replay: {counter_after - counter_before}
- Docker replay network: disabled
- DAP stack, scopes, locals and reverse navigation: passed

## Live Model Decisions

The same Microsoft Responses-compatible request and the same model request were
sent on every row. Different rows are separate real Qwen inferences, not
hardcoded responses or application-side random selection.

| Run | Review score | Application decision | Visible model rationale | Response hash | Recording ID |
| ---: | ---: | --- | --- | --- | --- |
{live_rows}

## Selected Historical Decision Replayed Ten Times

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the complete selected output,
including the original decision, rationale, provider timestamp and gateway
response ID.

| Replay | Decision | Historical response ID | Output hash | Exact match |
| ---: | --- | --- | --- | --- |
{replay_rows}

## Debugger Evidence

Retrace DAP replayed the selected recording, stopped in
`worker/decision_agent.py`, and inspected the historical `raw_model_response`,
`review_score`, `decision_name`, `decision_reason`, `model_name`,
`gateway_response_id`, request hash and response hash. Step Back moved within
the decision function and
forward replay returned to the same decision point.

## Honest Scope

The demo captures the model's externally visible assessment and its concise
rationale. It does not claim to expose private hidden chain-of-thought.
The proof is that a nondeterministic external model decision does not disappear
after production moves on: Retrace preserves that exact invocation for offline,
repeatable replay and debugging.
"""
    (GENERATED / "DEMO_RESULTS.md").write_text(report)


def archive_results(destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(GENERATED, destination)
    print(f"archived_results={destination}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    try:
        heading("1. Verify the real model and pinned Python 3.12 environment")
        model = verify_real_model()
        print(
            json.dumps(
                {
                    "provider": "ollama",
                    "model": OLLAMA_MODEL,
                    "digest": model["digest"],
                    "size": model.get("size"),
                },
                indent=2,
            )
        )
        compose("down", "--remove-orphans")
        reset_generated()
        if not args.skip_build:
            compose("build")

        heading(
            "2. Start the Microsoft Responses-compatible agent and real model gateway"
        )
        compose("up", "--detach", "--wait")

        heading(
            "3. Record identical live requests until the real model makes two decisions"
        )
        live: list[dict[str, Any]] = []
        decisions: set[str] = set()
        model_request_hash: str | None = None
        for number in range(1, MAXIMUM_LIVE_INVOCATIONS + 1):
            result = invoke_live(number)
            current_hash = str(result["model_request_sha256"])
            if model_request_hash is None:
                model_request_hash = current_hash
            elif current_hash != model_request_hash:
                raise AssertionError(
                    "model request changed between live invocations: "
                    f"{model_request_hash} != {current_hash}"
                )
            live.append(result)
            decisions.add(str(result["decision"]))
            print(
                f"live={number:02d} decision={result['decision']} "
                f"score={result['review_score']} "
                f"request_sha256={current_hash[:16]} "
                f"recording={result['manifest']['recording_id']}"
            )
            if len(decisions) >= MINIMUM_DISTINCT_DECISIONS:
                break
        if len(decisions) < MINIMUM_DISTINCT_DECISIONS:
            raise AssertionError(
                f"real model did not vary after {len(live)} identical live calls: "
                f"{sorted(decisions)}"
            )

        heading(
            "4. Select the first recording, stop the model, and replay it ten times"
        )
        selected, expected_path = prepare_selected_recording(live[0])
        expected = json.loads(expected_path.read_text())
        counter_before = counter_count()
        compose("stop", "model-gateway")
        replay_proof = replay_ten_times(selected, expected)
        counter_after = counter_count()
        if counter_before != counter_after:
            raise AssertionError(
                f"replay contacted the model: {counter_before} -> {counter_after}"
            )

        heading("5. Verify DAP can inspect the historical decision")
        dap_output = verify_dap(selected, expected_path)
        print(dap_output)
        print(generate_workspace(selected))

        recordings = [
            Path(str(item["manifest"]["recording_path"]).replace("/app/", f"{ROOT}/"))
            for item in live
        ]
        verify_secret_boundary(recordings)
        write_results(
            model=model,
            live=live,
            replay_proof=replay_proof,
            selected=selected,
            counter_before=counter_before,
            counter_after=counter_after,
        )
        if args.archive:
            archive_results(args.archive.resolve())

        heading("6. Proof complete")
        print((GENERATED / "DEMO_RESULTS.md").read_text())
    finally:
        compose("down", "--remove-orphans")


if __name__ == "__main__":
    main()
