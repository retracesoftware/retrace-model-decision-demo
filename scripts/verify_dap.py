from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import select
import subprocess
import time
from typing import Any, Callable


ROOT = Path(os.environ.get("DEMO_ROOT", "/app"))
SOURCE = ROOT / "worker" / "decision_agent.py"
CALLER_SOURCE = ROOT / "worker" / "__main__.py"
LOCAL_SOURCE = Path(__file__).resolve().parents[1] / "worker" / "decision_agent.py"
LOCAL_CALLER_SOURCE = Path(__file__).resolve().parents[1] / "worker" / "__main__.py"
MARKER = "RETRACE_MODEL_FAILURE_BREAKPOINT"
ROUTE_MARKER = "RETRACE_MODEL_ROUTE_BREAKPOINT"
CALLER_MARKER = "except Exception as error:"


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
    source = SOURCE if SOURCE.is_file() else LOCAL_SOURCE
    matches = [
        number
        for number, text in enumerate(source.read_text().splitlines(), start=1)
        if MARKER in text
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {MARKER} marker, found {matches}")
    return matches[0]


def route_line() -> int:
    source = SOURCE if SOURCE.is_file() else LOCAL_SOURCE
    matches = [
        number
        for number, text in enumerate(source.read_text().splitlines(), start=1)
        if ROUTE_MARKER in text
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {ROUTE_MARKER} marker, found {matches}")
    return matches[0]


def line_containing(text: str) -> int:
    source = SOURCE if SOURCE.is_file() else LOCAL_SOURCE
    matches = [
        number
        for number, line in enumerate(source.read_text().splitlines(), start=1)
        if text in line
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one source line containing {text!r}: {matches}")
    return matches[0]


def caller_line() -> int:
    source = CALLER_SOURCE if CALLER_SOURCE.is_file() else LOCAL_CALLER_SOURCE
    matches = [
        number
        for number, text in enumerate(source.read_text().splitlines(), start=1)
        if CALLER_MARKER in text
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {CALLER_MARKER!r} marker, found {matches}")
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

    def navigate_and_stop(
        self,
        command: str,
        reason: str,
        *,
        timeout: float = 90,
    ) -> dict[str, Any]:
        self.send(command, {"threadId": 1})
        deadline = time.monotonic() + timeout
        response = None
        stopped = None
        while time.monotonic() < deadline and (response is None or stopped is None):
            message = self.read(deadline - time.monotonic())
            if message.get("type") == "response" and message.get("command") == command:
                if not message.get("success"):
                    raise AssertionError(f"DAP {command} failed: {message}")
                response = message
            elif message.get("type") == "event" and message.get("event") in {
                "stopped",
                "terminated",
            }:
                if message.get("event") != "stopped":
                    raise AssertionError(
                        f"expected {command} to stop with {reason!r}, got {message}"
                    )
                if message.get("body", {}).get("reason") != reason:
                    raise AssertionError(
                        f"expected stopped({reason}) after {command}, got {message}"
                    )
                stopped = message
        if response is None or stopped is None:
            raise TimeoutError(
                f"incomplete DAP {command} transaction; messages={self.messages!r}"
            )
        return stopped


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


def verify_step_into_exception_unwind(
    recording: Path,
    *,
    line: int,
    transcript: Path,
) -> None:
    pid = int(trace_index(recording)["root"]["pid"])
    client = DAPClient(recording, pid)
    try:
        start_session(client, recording)
        client.send(
            "setBreakpoints",
            {
                "source": {"name": SOURCE.name, "path": str(SOURCE)},
                "lines": [line],
                "breakpoints": [{"line": line}],
            },
        )
        client.response("setBreakpoints")
        configure_to_marker(client, line=line)

        client.navigate_and_stop("stepIn", "step")
        client.send("stackTrace", {"threadId": 1})
        frames = client.response("stackTrace").get("body", {}).get("stackFrames", [])
        if not frames:
            raise AssertionError("Step Into exception unwind returned no stack frames")
        top = frames[0]
        expected_line = caller_line()
        if (
            top.get("source", {}).get("path") != str(CALLER_SOURCE)
            or int(top.get("line", 0)) != expected_line
        ):
            raise AssertionError(
                "Step Into stopped on an artificial unwind position instead of "
                f"{CALLER_SOURCE}:{expected_line}: {top}"
            )

        client.send("scopes", {"frameId": int(top["id"])})
        scopes = client.response("scopes").get("body", {}).get("scopes", [])
        locals_scope = next(
            (scope for scope in scopes if scope.get("name") == "Locals"), None
        )
        if not locals_scope or not locals_scope.get("variablesReference"):
            raise AssertionError(
                f"Step Into caller frame is not inspectable through scopes: {scopes}"
            )
        client.send(
            "variables",
            {"variablesReference": int(locals_scope["variablesReference"])},
        )
        client.response("variables")
    finally:
        transcript.write_text(json.dumps(client.messages, indent=2) + "\n")
        client.close()


def verify_success(recording: Path, expected: dict[str, Any], transcript: Path) -> None:
    line = route_line()
    pid = int(trace_index(recording)["root"]["pid"])
    client = DAPClient(recording, pid)
    try:
        capabilities = start_session(client, recording)
        if not capabilities.get("supportsStepBack"):
            raise AssertionError("DAP did not advertise reverse execution")
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
                f"success-route breakpoint not verified: {breakpoints}"
            )

        frames = configure_to_marker(client, line=line)
        frame = next(
            item
            for item in frames
            if item.get("source", {}).get("path") == str(SOURCE)
            and int(item.get("line", 0)) == line
        )
        client.send("scopes", {"frameId": int(frame["id"])})
        scopes = client.response("scopes").get("body", {}).get("scopes", [])
        locals_scope = next(
            (scope for scope in scopes if scope.get("name") == "Locals"), None
        )
        if not locals_scope or not locals_scope.get("variablesReference"):
            raise AssertionError(f"successful historical Locals unavailable: {scopes}")
        client.send(
            "variables",
            {"variablesReference": int(locals_scope["variablesReference"])},
        )
        variables = client.response("variables").get("body", {}).get("variables", [])
        by_name = {str(item.get("name")): item for item in variables}
        decision = expected["decision"]
        for name, value in {
            "review_score": str(decision["review_score"]),
            "decision_name": str(decision["decision"]),
            "decision_reason": str(decision["reason"]),
            "gateway_response_id": str(decision["gateway_response_id"]),
            "model_request_sha256": str(decision["model_request_sha256"]),
            "model_response_sha256": str(decision["model_response_sha256"]),
        }.items():
            rendered = str(by_name.get(name, {}).get("value", ""))
            if not dap_value_matches(value, rendered):
                raise AssertionError(
                    f"successful historical local {name} omitted {value!r}: "
                    f"{rendered!r}"
                )

        request_variable = by_name.get("request")
        if not request_variable:
            raise AssertionError("successful historical Locals omitted request")
        request_reference = int(request_variable.get("variablesReference", 0))
        if request_reference:
            client.send("variables", {"variablesReference": request_reference})
            request_members = (
                client.response("variables").get("body", {}).get("variables", [])
            )
            request_values = {
                str(item.get("name")): str(item.get("value"))
                for item in request_members
            }
            if request_values.get("serial_number") != "None":
                raise AssertionError(
                    "successful historical request did not preserve "
                    f"serial_number=None: {request_values}"
                )
        else:
            rendered_request = str(request_variable.get("value", ""))
            if (
                "serial_number" not in rendered_request
                or "None" not in rendered_request
            ):
                raise AssertionError(
                    "successful historical request rendering omitted "
                    f"serial_number=None: {rendered_request}"
                )

        route = str(decision["decision"])
        if route == "approve_refund":
            expected_body_line = line_containing(
                'action_detail = "refund approved from the available evidence"'
            )
        elif route == "escalate_specialist":
            expected_body_line = line_containing(
                'action_detail = "send the case to a regulated-equipment specialist"'
            )
        else:
            raise AssertionError(
                f"selected successful route is not successful: {route}"
            )

        observed_lines = []
        for _ in range(4):
            client.navigate_and_stop("next", "step")
            client.send("stackTrace", {"threadId": 1})
            step_frames = (
                client.response("stackTrace").get("body", {}).get("stackFrames", [])
            )
            top = step_frames[0]
            observed_lines.append(int(top.get("line", 0)))
            if (
                top.get("source", {}).get("path") == str(SOURCE)
                and int(top.get("line", 0)) == expected_body_line
            ):
                break
        else:
            raise AssertionError(
                f"successful replay did not enter {route}: {observed_lines}"
            )

        client.navigate_and_stop("stepBack", "step")
        client.send("stackTrace", {"threadId": 1})
        reverse_frames = (
            client.response("stackTrace").get("body", {}).get("stackFrames", [])
        )
        reverse_top = reverse_frames[0]
        if reverse_top.get("source", {}).get("path") != str(SOURCE):
            raise AssertionError(
                f"success Step Back left decision function: {reverse_top}"
            )
    finally:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(json.dumps(client.messages, indent=2) + "\n")
        client.close()

    verify_no_breakpoint_termination(
        recording,
        transcript=transcript.with_name(
            f"{transcript.stem}-no-breakpoint{transcript.suffix}"
        ),
    )
    print(
        "dap=pass outcome=success model_response=historical "
        "decision=historical serial_number=None stack=pass scopes=pass "
        "locals=pass route=pass step_back=pass termination=pass"
    )


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
    verify_step_into_exception_unwind(
        recording,
        line=line,
        transcript=transcript.with_name(
            f"{transcript.stem}-step-into-unwind{transcript.suffix}"
        ),
    )

    print(
        "dap=pass failure=historical model_response=historical "
        "decision=historical serial_number=None stack=pass scopes=pass "
        "locals=pass entry_stop=real granularity_contract=pass "
        "exception_filter_contract=pass raised_exception=pass "
        "no_breakpoint_termination=pass step_back=toward-routing "
        "forward_return=failure step_into_exception_unwind=pass"
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
    expected = json.loads(args.expected.read_text())
    if expected.get("failure") is None:
        verify_success(args.recording, expected, args.transcript)
    else:
        verify(args.recording, expected, args.transcript)


if __name__ == "__main__":
    main()
