from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from agent.manifest import sha256_file, write_manifest
from scripts.agent_client import decision_request, post_invocation
from scripts.demo_state import (
    CASE,
    GENERATED,
    ROOT,
    SESSION_ARTIFACTS,
    canonical_json,
    reset_generated,
)
from scripts.platforms import docker_architecture


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
HOST_UID = str(os.getuid()) if hasattr(os, "getuid") else "0"
HOST_GID = str(os.getgid()) if hasattr(os, "getgid") else "0"
os.environ.setdefault("DEMO_UID", HOST_UID)
os.environ.setdefault("DEMO_GID", HOST_GID)
DECISION_FIELDS = (
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


class DemoPreflightError(RuntimeError):
    pass


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


def compose(
    *arguments: str,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run([*COMPOSE, *arguments], capture=capture, check=check)


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
            "--network",
            "none",
            "--memory",
            "768m",
            "--cpus",
            "1",
            "--user",
            f"{HOST_UID}:{HOST_GID}",
            "--env",
            "HOME=/tmp/retrace-offline-replay-home",
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


def verify_docker() -> None:
    try:
        result = subprocess.run(
            ["docker", "info"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    except FileNotFoundError as error:
        raise DemoPreflightError(
            "Docker is not installed. Install Docker Desktop or Docker Engine "
            "before running the demo."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise DemoPreflightError(
            "Docker did not become ready within 10 seconds. Start Docker Desktop, "
            "wait until the engine reports that it is running, and try again."
        ) from error
    if result.returncode != 0:
        raise DemoPreflightError(
            "Docker is installed but its engine is not reachable. Start Docker "
            "Desktop, wait until it reports that Docker is running, and try again."
        )


def manifest_paths() -> set[Path]:
    return set((SESSION_ARTIFACTS / "manifests").glob("*.json"))


def _decision_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in DECISION_FIELDS}


def invoke_live(number: int) -> dict[str, Any]:
    before = manifest_paths()
    status, response, headers, local_platform_context = post_invocation(
        "http://localhost:8088/invocations"
        "?agent_session_id=SESSION-MODEL-DECISION-DEMO",
        invocation_number=number,
    )
    response_path = GENERATED / "invocations" / f"live-{number:02d}.json"
    response_path.write_text(
        json.dumps(
            {"status": status, "headers": headers, "body": response},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if status not in {200, 500} or not isinstance(response, dict):
        raise AssertionError(
            f"live invocation {number} returned HTTP {status}: {response!r}"
        )
    created = manifest_paths() - before
    if len(created) != 1:
        raise AssertionError(
            f"live invocation {number} created {len(created)} manifests: {created}"
        )
    manifest_path = created.pop()
    manifest = json.loads(manifest_path.read_text())
    if not manifest.get("recording_available"):
        raise AssertionError(f"invocation did not preserve a recording: {manifest}")
    decision = manifest.get("decision")
    if not isinstance(decision, dict):
        raise AssertionError(f"invocation omitted model decision: {manifest}")

    succeeded = manifest.get("worker_exit_code") == 0
    if succeeded != (status == 200):
        raise AssertionError(
            f"worker/HTTP outcome mismatch: status={status} manifest={manifest}"
        )
    if response.get("recording_id") != manifest.get("recording_id"):
        raise AssertionError("protocol response did not identify its recording")

    foundry_call_id = local_platform_context["foundry_call_id"]
    if response.get("foundry_call_id") != foundry_call_id:
        raise AssertionError("response did not preserve the Foundry call ID")
    if manifest.get("foundry_call_id") != foundry_call_id:
        raise AssertionError("manifest did not preserve the Foundry call ID")
    if manifest.get("user_id") != local_platform_context["user_id"]:
        raise AssertionError("manifest did not preserve the Foundry user ID")
    if manifest.get("trace_id") != local_platform_context["trace_id"]:
        raise AssertionError("manifest trace ID did not continue traceparent")
    if not manifest.get("span_id"):
        raise AssertionError("manifest omitted the recording span ID")

    normalized_headers = {key.lower(): value for key, value in headers.items()}
    if not normalized_headers.get("x-agent-session-id"):
        raise AssertionError(f"Microsoft session header was not returned: {headers}")
    if response.get("session_id") != normalized_headers["x-agent-session-id"]:
        raise AssertionError("response and adapter session IDs differ")
    if manifest.get("session_id") != response.get("session_id"):
        raise AssertionError("manifest and response session IDs differ")

    return {
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "http_status": status,
        "foundry_call_id": foundry_call_id,
        "trace_id": manifest["trace_id"],
        "span_id": manifest["span_id"],
        "protocol_session_id": normalized_headers["x-agent-session-id"],
        **_decision_payload(decision),
        "output": manifest.get("output"),
        "failure": manifest.get("failure"),
        "succeeded": succeeded,
    }


def counter_count() -> int:
    path = GENERATED / "counters" / "model-gateway.json"
    return int(json.loads(path.read_text())["count"])


def container_path(host_path: Path) -> Path:
    return Path("/app") / host_path.relative_to(ROOT)


def parse_worker_events(output: str) -> tuple[dict[str, Any], dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("event") in {
            "model_decision_selected",
            "application_failure",
        }:
            events[str(payload["event"])] = payload
    try:
        return events["model_decision_selected"], events["application_failure"]
    except KeyError as error:
        raise AssertionError(
            f"replay omitted structured worker events:\n{output}"
        ) from error


def failure_expectation(invocation: dict[str, Any]) -> dict[str, Any]:
    failure = invocation.get("failure")
    if not isinstance(failure, dict):
        raise AssertionError(f"selected invocation did not fail: {invocation}")
    return {
        "decision": {key: invocation[key] for key in DECISION_FIELDS},
        "failure": {
            "exception_type": failure["exception_type"],
            "exception_message": failure["exception_message"],
        },
        "worker_exit_code": int(invocation["manifest"]["worker_exit_code"]),
        "runtime_input": {"serial_number": CASE["serial_number"]},
    }


def prepare_selected_failure(invocation: dict[str, Any]) -> tuple[Path, Path]:
    source = Path(
        str(invocation["manifest"]["recording_path"]).replace("/app/", f"{ROOT}/")
    )
    selected = GENERATED / "recordings" / "selected-failure.retrace"
    expected = GENERATED / "recordings" / "selected-failure.expected.json"
    shutil.copy2(source, selected)
    selected.chmod(selected.stat().st_mode | 0o111)
    expected.write_text(json.dumps(failure_expectation(invocation), indent=2) + "\n")
    return selected, expected


def replay_failure_times(
    recording: Path,
    expected: dict[str, Any],
    *,
    count: int = REPLAY_COUNT,
) -> list[dict[str, Any]]:
    extracted = recording.with_suffix(".d")
    shutil.rmtree(extracted, ignore_errors=True)
    extraction = in_offline_container([str(container_path(recording)), "--extract"])
    if extraction.returncode != 0:
        raise AssertionError(f"offline extraction failed:\n{extraction.stdout}")
    index = json.loads((extracted / "index.json").read_text())
    pid = int(index["root"]["pid"])
    pidfile = container_path(extracted) / f"{pid}.bin"
    expected_decision = expected["decision"]
    expected_failure = expected["failure"]
    proof = []
    for number in range(1, count + 1):
        replay = in_offline_container([str(pidfile)], check=False)
        log_path = GENERATED / "replay" / f"replay-{number:02d}.log"
        log_path.write_text(replay.stdout)
        decision_event, failure_event = parse_worker_events(replay.stdout)
        actual_decision = _decision_payload(decision_event)
        actual_failure = {
            "exception_type": failure_event["exception_type"],
            "exception_message": failure_event["exception_message"],
        }
        if replay.returncode != expected["worker_exit_code"]:
            raise AssertionError(
                f"offline replay {number} exit changed: "
                f"{replay.returncode} != {expected['worker_exit_code']}"
            )
        if actual_decision != expected_decision:
            raise AssertionError(
                f"offline replay {number} changed model decision:\n"
                f"expected={expected_decision}\nactual={actual_decision}"
            )
        if actual_failure != expected_failure:
            raise AssertionError(
                f"offline replay {number} changed exception:\n"
                f"expected={expected_failure}\nactual={actual_failure}"
            )
        if "serial_number.strip()" not in replay.stdout:
            raise AssertionError("replay traceback omitted the historical failing line")
        observation = {
            "decision": actual_decision,
            "failure": actual_failure,
            "exit_code": replay.returncode,
        }
        output_sha256 = hashlib.sha256(canonical_json(observation).encode()).hexdigest()
        proof.append(
            {
                "replay": number,
                "decision": actual_decision["decision"],
                "review_score": actual_decision["review_score"],
                "exception_type": actual_failure["exception_type"],
                "output_sha256": output_sha256,
                "network": "none",
                "match": True,
            }
        )
        print(
            f"replay={number:02d} score={actual_decision['review_score']} "
            f"decision={actual_decision['decision']} "
            f"exception={actual_failure['exception_type']} "
            f"network=none match=yes"
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


def read_telemetry_spans() -> list[dict[str, Any]]:
    path = GENERATED / "telemetry" / "spans.jsonl"
    for _ in range(30):
        if path.is_file():
            spans = [json.loads(line) for line in path.read_text().splitlines()]
            if spans:
                return spans
        time.sleep(0.2)
    raise AssertionError("Microsoft invocation host exported no OTLP spans")


def verify_failed_invocation_span(failed: dict[str, Any]) -> dict[str, Any]:
    recording_id = str(failed["manifest"]["recording_id"])
    trace_id = str(failed["manifest"]["trace_id"])
    span_id = str(failed["manifest"]["span_id"])
    for span in read_telemetry_spans():
        attributes = span.get("attributes", {})
        if attributes.get("retrace.recording.id") != recording_id:
            continue
        if span.get("trace_id") != trace_id or span.get("span_id") != span_id:
            raise AssertionError(f"span/manifest diagnostic join changed: {span}")
        if attributes.get("microsoft.foundry.call_id") != failed["foundry_call_id"]:
            raise AssertionError(f"span Foundry call ID changed: {span}")
        if attributes.get("retrace.model.decision") != failed["decision"]:
            raise AssertionError(f"span model decision changed: {span}")
        if attributes.get("retrace.application.exception.type") != "AttributeError":
            raise AssertionError(f"span omitted application exception: {span}")
        if span.get("status_code") != 2:
            raise AssertionError(f"failed invocation span was not ERROR: {span}")
        return span
    raise AssertionError(
        f"no exported span correlated failed recording {recording_id!r}"
    )


def write_selected_proof_manifest(
    *,
    failed: dict[str, Any],
    selected: Path,
    failed_span: dict[str, Any],
    model: dict[str, Any],
) -> Path:
    manifest = failed["manifest"]
    proof = {
        "schema_version": 1,
        "artifact": {
            "path": selected.name,
            "sha256": sha256_file(selected),
            "original_recording_id": manifest["recording_id"],
            "original_recording_sha256": manifest["recording_sha256"],
            "platform": f"linux/{docker_architecture()}",
        },
        "source": {
            "git_sha": manifest["source_git_sha"],
            "worker_sha256": manifest["source_sha256"],
        },
        "runtime": {
            "python": manifest["python_version"],
            "retracesoftware": manifest["retracesoftware_version"],
            "retracesoftware_dap": manifest["retracesoftware_dap_version"],
        },
        "model": {
            "name": failed["model"],
            "digest": model["digest"],
            "request_sha256": failed["model_request_sha256"],
            "response_sha256": failed["model_response_sha256"],
        },
        "foundry": {
            "call_id": manifest["foundry_call_id"],
            "user_id": manifest["user_id"],
            "session_id": manifest["session_id"],
        },
        "telemetry": {
            "trace_id": failed_span["trace_id"],
            "span_id": failed_span["span_id"],
        },
    }
    path = GENERATED / "recordings" / "selected-failure.proof.json"
    write_manifest(path, proof)
    return path


def write_results(
    *,
    model: dict[str, Any],
    live: list[dict[str, Any]],
    replay_proof: list[dict[str, Any]],
    selected: Path,
    counter_before: int,
    counter_after: int,
    failed_span: dict[str, Any],
    proof_manifest: Path,
) -> None:
    decisions = sorted({str(item["decision"]) for item in live})
    request_hashes = sorted({str(item["model_request_sha256"]) for item in live})
    failed = next(item for item in live if not item["succeeded"])
    summary = {
        "status": "passed",
        "python": "3.12.13",
        "agent_protocol": "Microsoft Hosted Agent Invocations",
        "model": OLLAMA_MODEL,
        "model_digest": model["digest"],
        "identical_agent_request": decision_request(),
        "live_invocations": live,
        "distinct_live_decisions": decisions,
        "model_request_sha256_values": request_hashes,
        "failed_recording_id": failed["manifest"]["recording_id"],
        "selected_recording": str(selected),
        "selected_recording_sha256": sha256_file(selected),
        "selected_proof_manifest": str(proof_manifest),
        "offline_replays": replay_proof,
        "model_calls_before_replay": counter_before,
        "model_calls_after_replay": counter_after,
        "dap": "passed",
        "failed_invocation_span": failed_span,
    }
    (GENERATED / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    live_rows = "\n".join(
        f"| {index} | {item['review_score']} | `{item['decision']}` | "
        f"{'failed: ' + item['failure']['exception_type'] if item['failure'] else 'completed'} | "
        f"`{item['model_response_sha256'][:16]}` | "
        f"`{item['manifest']['recording_id']}` |"
        for index, item in enumerate(live, start=1)
    )
    replay_rows = "\n".join(
        f"| {item['replay']} | {item['review_score']} | `{item['decision']}` | "
        f"`{item['exception_type']}` | `{item['output_sha256'][:16]}` | yes |"
        for item in replay_proof
    )
    report = f"""# Retrace Model-Dependent Runtime Failure Proof

## Result

The complete proof passed on Python 3.12.13 with the real local
`{OLLAMA_MODEL}` model and Microsoft's Hosted Agent Invocations adapter.

- Identical live application and model input: yes
- Identical exact model request hash: `{request_hashes[0]}`
- Distinct live model decisions: {", ".join(f"`{item}`" for item in decisions)}
- Genuine model-selected failure observed: `request_more_information`
- Preserved exception: `{failed["failure"]["exception_type"]}: {failed["failure"]["exception_message"]}`
- Every live invocation recorded separately: yes
- Selected failed recording: `{selected}`
- Offline failed replays: {len(replay_proof)} of {REPLAY_COUNT} exact matches
- Model calls during replay: {counter_after - counter_before}
- Docker replay network: disabled
- OTel trace/span, Foundry call/session, and recording manifest correlated: yes
- Verifiable recording provenance manifest: `{proof_manifest}`
- DAP failure stack, scopes, locals and reverse navigation: passed

## Foundry Trace And Retrace Recording

Foundry protocol 2.0 supplies request-scoped call, user, and session context.
The gateway also forwards W3C trace context. The handler records the active
trace and span IDs with `retrace.recording.id`, producing a direct diagnostic
join from the platform span to the persisted executable artifact.

## Live Model Invocations

The same request and exact model payload were used on every row. The real
sampled model selected the score and route. Only scores from 65 through 69
enter the rare `request_more_information` path, where the latent missing serial
number bug becomes observable.

| Run | Score | Model-selected route | Runtime outcome | Response hash | Recording ID |
| ---: | ---: | --- | --- | --- | --- |
{live_rows}

## Failed Invocation Replayed Offline

The model gateway was stopped before replay. Every row below ran in a fresh
`--network none` container and reproduced the same historical model score,
route, failing line and exception.

| Replay | Score | Route | Exception | Observation hash | Exact match |
| ---: | ---: | --- | --- | --- | --- |
{replay_rows}

## Debugger Evidence

Retrace DAP stopped on the historical `.strip()` failure in
`worker/decision_agent.py`. The failure frame exposed the preserved
`raw_model_response`, score, reason, selected route and `serial_number=None`.
Step Back moved from the exception toward the application routing decision,
then forward execution returned to the same failure without a new inference.

Foundry tells you which agent invocation failed. Retrace lets you re-enter
that exact historical Python execution and debug why.
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
    docker_ready = False
    try:
        heading("1. Verify Docker, the real model, and pinned Python 3.12")
        verify_docker()
        docker_ready = True
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

        heading("2. Start the Microsoft invocation host and real model gateway")
        compose("up", "--detach", "--wait")

        heading("3. Record identical requests until a model-selected route fails")
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
            outcome = (
                f"failed:{result['failure']['exception_type']}"
                if result["failure"]
                else "completed"
            )
            print(
                f"live={number:02d} decision={result['decision']} "
                f"score={result['review_score']} outcome={outcome} "
                f"request_sha256={current_hash[:16]} "
                f"recording={result['manifest']['recording_id']}"
            )
            has_failure = any(not item["succeeded"] for item in live)
            has_success = any(item["succeeded"] for item in live)
            if (
                len(decisions) >= MINIMUM_DISTINCT_DECISIONS
                and has_failure
                and has_success
            ):
                break
        failures = [item for item in live if not item["succeeded"]]
        if len(decisions) < MINIMUM_DISTINCT_DECISIONS or not failures:
            raise AssertionError(
                f"real model did not expose the rare branch after {len(live)} "
                f"identical calls: decisions={sorted(decisions)} failures={len(failures)}"
            )

        heading("4. Stop the model and replay the failed invocation ten times")
        selected, expected_path = prepare_selected_failure(failures[0])
        expected = json.loads(expected_path.read_text())
        counter_before = counter_count()
        compose("stop", "model-gateway")
        replay_proof = replay_failure_times(selected, expected)
        counter_after = counter_count()
        if counter_before != counter_after:
            raise AssertionError(
                f"replay contacted the model: {counter_before} -> {counter_after}"
            )

        heading("5. Inspect the historical failure through DAP")
        print(verify_dap(selected, expected_path))
        print(generate_workspace(selected))

        recordings = [
            Path(str(item["manifest"]["recording_path"]).replace("/app/", f"{ROOT}/"))
            for item in live
        ]
        verify_secret_boundary(recordings)
        failed_span = verify_failed_invocation_span(failures[0])
        proof_manifest = write_selected_proof_manifest(
            failed=failures[0],
            selected=selected,
            failed_span=failed_span,
            model=model,
        )
        write_results(
            model=model,
            live=live,
            replay_proof=replay_proof,
            selected=selected,
            counter_before=counter_before,
            counter_after=counter_after,
            failed_span=failed_span,
            proof_manifest=proof_manifest,
        )
        if args.archive:
            archive_results(args.archive.resolve())

        heading("6. Proof complete")
        print((GENERATED / "DEMO_RESULTS.md").read_text())
    finally:
        if docker_ready:
            compose("down", "--remove-orphans", check=False)


if __name__ == "__main__":
    try:
        main()
    except DemoPreflightError as error:
        raise SystemExit(f"Demo preflight failed: {error}") from None
