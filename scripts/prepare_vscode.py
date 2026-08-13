from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from scripts.demo_state import GENERATED, ROOT
from scripts.verify_dap import marker_line, verify


ACTIVE = GENERATED / "recordings" / "selected-failure.retrace"
EXPECTED = GENERATED / "recordings" / "selected-failure.expected.json"
FALLBACK = ROOT / "example-artifacts" / "selected-failure.retrace"
FALLBACK_EXPECTED = ROOT / "example-artifacts" / "selected-failure.expected.json"


def prepare() -> Path | None:
    if not ACTIVE.is_file() and FALLBACK.is_file():
        ACTIVE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(FALLBACK, ACTIVE)
        shutil.copy2(FALLBACK_EXPECTED, EXPECTED)
    if not ACTIVE.is_file():
        print(
            "No selected failure recording yet. Run `make demo` on the host, "
            "then reopen the folder in the Dev Container."
        )
        return None
    if not EXPECTED.is_file():
        raise AssertionError(f"selected recording expectation is missing: {EXPECTED}")

    ACTIVE.chmod(ACTIVE.stat().st_mode | 0o111)
    shutil.rmtree(ACTIVE.with_suffix(".d"), ignore_errors=True)
    ACTIVE.with_suffix(".code-workspace").unlink(missing_ok=True)
    subprocess.run([str(ACTIVE), "--extract"], cwd=ROOT, check=True)
    subprocess.run(
        ["retrace-dap", "--recording", str(ACTIVE), "--workspace"],
        cwd=ROOT,
        check=True,
    )
    verify(
        ACTIVE,
        json.loads(EXPECTED.read_text()),
        GENERATED / "transcripts" / "vscode-preflight-dap.json",
    )
    print(f"active_recording={ACTIVE}")
    print(f"workspace={ACTIVE.with_suffix('.code-workspace')}")
    print(f"breakpoint={ROOT / 'worker/decision_agent.py'}:{marker_line()}")
    return ACTIVE


if __name__ == "__main__":
    prepare()
