from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import select
import subprocess
import time
from typing import Any, Callable


ROOT = Path("/app")
SOURCE = ROOT / "worker" / "decision_agent.py"
MARKER = "RETRACE_MODEL_FAILURE_BREAKPOINT"


def dap_value_matches(expected: str, rendered: str) -> bool:
    if expected in rendered:
        return True
    try:
        value = ast.literal_eval(rendered)
    except (SyntaxError, ValueError):
        value = rendered
    text = str(value)
    if text[:1] in {"'", '"'} and not text.endswith(text[0]):
        text = text[1:]
    return text.endswith("...") and expected.startswith(text[:-3])


def replay_binary(recording: Path) -> str:
    with recording.open("rb") as stream:
        shebang = stream.readline().decode("ascii").strip()
    if not shebang.startswith("#!"):
        raise AssertionError(f"recording has no replay shebang: {recording}")
    return shebang[2:].split()[0]


def trace_index(recording: Path) -> dict[str, Any]:
    result = subprocess.run(
        [replay_binary(recording), "--recording", str(recording), "--index"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def marker_line() -> int:
    matches = [
        number
        for number, text in enumerate(SOURCE.read_text().splitlines(), start=1)
        if MARKER in text
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {MARKER} marker, found {matches}")
    return matches[0]


class DAPClient:
    def __init__(self, recording: Path, pid: int) -> None:
        self.sequence = 1
        self.messages: list[dict[str, Any]] = []
        self.process = subprocess.Popen(
            [
                replay_binary(recording),
                "--recording",
                str(recording),
                "--dap",
                "--pid",
                str(pid),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def send(self, command: str, arguments: dict[str, Any] | None = None) -> None:
        assert self.process.stdin is not None
        message = {
            "seq": self.sequence,
            "type": "request",
            "command": command,
            "arguments": arguments or {},
        }
        self.sequence += 1
        payload = json.dumps(message, separators=(",", ":")).encode()
        self.process.stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode())
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def read(self, timeout: float) -> dict[str, Any]:
        assert self.process.stdout is not None
        deadline = time.monotonic() + timeout
        headers: dict[str, str] = {}
        while True:
            remaining = deadline - time.monotonic()
            if (
                remaining <= 0
                or not select.select([self.process.stdout], [], [], remaining)[0]
            ):
                raise TimeoutError("timed out waiting for DAP message")
            line = self.process.stdout.readline()
            if not line:
                stderr = (
                    self.process.stderr.read().decode(errors="replace")
                    if self.process.stderr
                    else ""
                )
                raise RuntimeError(f"DAP exited before a response:\n{stderr}")
            if line == b"\r\n":
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()
        message = json.loads(self.process.stdout.read(int(headers["content-length"])))
        self.messages.append(message)
        return message

    def wait_for(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        timeout: float = 90,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.read(deadline - time.monotonic())
            if predicate(message):
                return message
        raise TimeoutError(f"DAP condition not met; messages={self.messages!r}")

    def response(self, command: str, timeout: float = 90) -> dict[str, Any]:
        message = self.wait_for(
            lambda item: item.get("type") == "response"
            and item.get("command") == command,
            timeout,
        )
        if not message.get("success"):
            raise AssertionError(f"DAP {command} failed: {message}")
        return message

    def failed_response(
        self,
        command: str,
        *,
        message_contains: str,
        timeout: float = 90,
    ) -> dict[str, Any]:
        message = self.wait_for(
            lambda item: item.get("type") == "response"
            and item.get("command") == command,
            timeout,
        )
        if message.get("success"):
            raise AssertionError(f"DAP {command} unexpectedly succeeded: {message}")
        if message_contains not in str(message.get("message", "")):
            raise AssertionError(
                f"DAP {command} error omitted {message_contains!r}: {message}"
            )
        return message

    def stopped(self, reason: str, timeout: float = 90) -> dict[str, Any]:
        message = self.wait_for(
            lambda item: item.get("type") == "event"
            and item.get("event") in {"stopped", "terminated"},
            timeout,
        )
        if message.get("event") != "stopped":
            raise AssertionError(f"expected stopped({reason}), got {message}")
        if message.get("body", {}).get("reason") != reason:
            raise AssertionError(f"expected stopped({reason}), got {message}")
        return message


def continue_to_marker(
    client: DAPClient,
    *,
    line: int,
    maximum_stops: int = 8,
) -> list[dict[str, Any]]:
    observed = []
    for _ in range(maximum_stops):
        client.send("continue", {"threadId": 1})
        client.stopped("breakpoint")
        client.send("stackTrace", {"threadId": 1})
        frames = client.response("stackTrace").get("body", {}).get("stackFrames", [])
        observed.append(
            [
                (frame.get("source", {}).get("path"), int(frame.get("line", 0)))
                for frame in frames[:3]
            ]
        )
        if any(
            frame.get("source", {}).get("path") == str(SOURCE)
            and int(frame.get("line", 0)) == line
            for frame in frames
        ):
            return frames
    raise AssertionError(f"did not reach {SOURCE}:{line}; observed={observed}")


def configure_to_marker(
    client: DAPClient,
    *,
    line: int,
) -> list[dict[str, Any]]:
    client.send("configurationDone")
    client.response("configurationDone")
    client.stopped("breakpoint")
    client.send("stackTrace", {"threadId": 1})
    frames = client.response("stackTrace").get("body", {}).get("stackFrames", [])
    if not any(
        frame.get("source", {}).get("path") == str(SOURCE)
        and int(frame.get("line", 0)) == line
        for frame in frames
    ):
        raise AssertionError(
            f"configuration did not stop at {SOURCE}:{line}; frames={frames}"
        )
    return frames


def start_session(client: DAPClient, recording: Path) -> dict[str, Any]:
    client.send(
        "initialize",
        {"clientID": "retrace-model-decision-verifier", "adapterID": "retrace"},
    )
    capabilities = client.response("initialize").get("body", {})
    client.send(
        "launch",
        {"type": "retrace", "request": "launch", "recording": str(recording)},
    )
    client.response("launch")
    return capabilities


def verify_raised_exception(
    recording: Path,
    *,
    line: int,
    transcript: Path,
) -> None:
    pid = int(trace_index(recording)["root"]["pid"])
    client = DAPClient(recording, pid)
    try:
        start_session(client, recording)
        client.send("setExceptionBreakpoints", {"filters": ["raised"]})
        client.response("setExceptionBreakpoints")
        client.send("configurationDone")
        client.response("configurationDone")
        client.stopped("exception")
        client.send("stackTrace", {"threadId": 1})
        frames = client.response("stackTrace").get("body", {}).get("stackFrames", [])
        top = frames[0]
        if (
            top.get("source", {}).get("path") != str(SOURCE)
            or int(top.get("line", 0)) != line
        ):
            raise AssertionError(f"raised exception stopped at wrong frame: {top}")
        client.send("exceptionInfo", {"threadId": 1})
        info = client.response("exceptionInfo").get("body", {})
        if info.get("exceptionId") != "AttributeError":
            raise AssertionError(f"wrong raised exception info: {info}")
        if info.get("breakMode") != "always":
            raise AssertionError(f"raised exception was mislabeled: {info}")
    finally:
        transcript.write_text(json.dumps(client.messages, indent=2) + "\n")
        client.close()


def verify_no_breakpoint_termination(recording: Path, *, transcript: Path) -> None:
    pid = int(trace_index(recording)["root"]["pid"])
    client = DAPClient(recording, pid)
    try:
        start_session(client, recording)
        client.send("configurationDone")
        client.response("configurationDone")
        event = client.wait_for(
            lambda item: item.get("type") == "event"
            and item.get("event") in {"stopped", "terminated"}
        )
        if event.get("event") != "terminated":
            raise AssertionError(
                f"session without breakpoints emitted an unexpected stop: {event}"
            )
    finally:
        transcript.write_text(json.dumps(client.messages, indent=2) + "\n")
        client.close()


def verify(recording: Path, expected: dict[str, Any], transcript: Path) -> None:
    line = marker_line()
    pid = int(trace_index(recording)["root"]["pid"])
    client = DAPClient(recording, pid)
    try:
        capabilities = start_session(client, recording)
        if not capabilities.get("supportsStepBack"):
            raise AssertionError("DAP did not advertise reverse execution")
        if capabilities.get("supportsSteppingGranularity"):
            raise AssertionError("DAP advertised unsupported stepping granularity")
        exception_filters = {
            item.get("filter")
            for item in capabilities.get("exceptionBreakpointFilters", [])
        }
        if exception_filters != {"raised"}:
            raise AssertionError(
                f"DAP advertised inaccurate exception filters: {exception_filters}"
            )

        client.send("setExceptionBreakpoints", {"filters": ["uncaught"]})
        client.failed_response(
            "setExceptionBreakpoints",
            message_contains="not supported",
        )
        client.send(
            "setBreakpoints",
            {
                "source": {"name": SOURCE.name, "path": str(SOURCE)},
                "lines": [line],
                "breakpoints": [{"line": line}],
            },
        )
        breakpoints = (
            client.response("setBreakpoints").get("body", {}).get("breakpoints", [])
        )
        if not breakpoints or not breakpoints[0].get("verified"):
            raise AssertionError(
                f"model-decision breakpoint not verified: {breakpoints}"
            )

        frames = configure_to_marker(client, line=line)
        frame = next(
            item
            for item in frames
            if item.get("source", {}).get("path") == str(SOURCE)
            and int(item.get("line", 0)) == line
        )
        client.send(
            "next",
            {"threadId": 1, "granularity": "instruction"},
        )
        client.failed_response("next", message_contains="granularity")
        client.send("stackTrace", {"threadId": 1})
        preserved_frames = (
            client.response("stackTrace").get("body", {}).get("stackFrames", [])
        )
        preserved_top = preserved_frames[0]
        if (
            preserved_top.get("source", {}).get("path") != str(SOURCE)
            or int(preserved_top.get("line", 0)) != line
        ):
            raise AssertionError(
                f"unsupported granularity changed the stopped cursor: {preserved_top}"
            )
        client.send("scopes", {"frameId": int(frame["id"])})
        scopes = client.response("scopes").get("body", {}).get("scopes", [])
        locals_scope = next(
            (scope for scope in scopes if scope.get("name") == "Locals"), None
        )
        if not locals_scope or not locals_scope.get("variablesReference"):
            raise AssertionError(f"historical Locals unavailable: {scopes}")
        client.send(
            "variables",
            {"variablesReference": int(locals_scope["variablesReference"])},
        )
        variables = client.response("variables").get("body", {}).get("variables", [])
        values = {str(item.get("name")): str(item.get("value")) for item in variables}
        decision = expected["decision"]
        expected_values = {
            "review_score": str(decision["review_score"]),
            "decision_name": str(decision["decision"]),
            "decision_reason": str(decision["reason"]),
            "model_name": str(decision["model"]),
            "gateway_response_id": str(decision["gateway_response_id"]),
            "model_request_sha256": str(decision["model_request_sha256"]),
            "model_response_sha256": str(decision["model_response_sha256"]),
            "serial_number": "None",
        }
        for name, value in expected_values.items():
            if not dap_value_matches(value, values.get(name, "")):
                raise AssertionError(
                    f"historical local {name} omitted {value!r}: {values.get(name)!r}"
                )
        raw_response = values.get("raw_model_response", "")
        for value in (
            str(decision["gateway_response_id"]),
            "message",
        ):
            if value not in raw_response:
                raise AssertionError(
                    f"raw historical model response omitted {value!r}: {raw_response}"
                )

        client.send("stepBack", {"threadId": 1})
        client.stopped("step")
        client.send("stackTrace", {"threadId": 1})
        reverse_frames = (
            client.response("stackTrace").get("body", {}).get("stackFrames", [])
        )
        reverse_top = reverse_frames[0]
        if reverse_top.get("source", {}).get("path") != str(SOURCE):
            raise AssertionError(f"Step Back left decision function: {reverse_top}")
        if int(reverse_top.get("line", 0)) == line:
            raise AssertionError("Step Back did not move the historical cursor")

        returned_frames = continue_to_marker(client, line=line)
        returned = next(
            item
            for item in returned_frames
            if item.get("source", {}).get("path") == str(SOURCE)
            and int(item.get("line", 0)) == line
        )
        if int(returned.get("line", 0)) != line:
            raise AssertionError(
                f"forward replay did not return to failure: {returned}"
            )
    finally:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps(client.messages, indent=2) + "\n")
        client.close()

    verify_raised_exception(
        recording,
        line=line,
        transcript=transcript.with_name(f"{transcript.stem}-raised{transcript.suffix}"),
    )
    verify_no_breakpoint_termination(
        recording,
        transcript=transcript.with_name(
            f"{transcript.stem}-no-breakpoint{transcript.suffix}"
        ),
    )

    print(
        "dap=pass failure=historical model_response=historical "
        "decision=historical serial_number=None stack=pass scopes=pass "
        "locals=pass entry_stop=real granularity_contract=pass "
        "exception_filter_contract=pass raised_exception=pass "
        "no_breakpoint_termination=pass step_back=toward-routing "
        "forward_return=failure"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument(
        "--transcript",
        type=Path,
        default=Path("/app/generated/transcripts/dap.json"),
    )
    args = parser.parse_args()
    verify(args.recording, json.loads(args.expected.read_text()), args.transcript)


if __name__ == "__main__":
    main()
