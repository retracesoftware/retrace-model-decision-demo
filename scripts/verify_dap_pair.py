from __future__ import annotations

import subprocess
import sys

from scripts.demo_state import GENERATED, ROOT


def verification_command(outcome: str) -> list[str]:
    recordings = GENERATED / "recordings"
    return [
        sys.executable,
        str(ROOT / "scripts" / "verify_dap.py"),
        "--recording",
        str(recordings / f"selected-{outcome}.retrace"),
        "--expected",
        str(recordings / f"selected-{outcome}.expected.json"),
        "--transcript",
        str(GENERATED / "transcripts" / f"concurrent-{outcome}-dap.json"),
    ]


def main() -> None:
    processes = {
        outcome: subprocess.Popen(
            verification_command(outcome),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for outcome in ("success", "failure")
    }

    failures = []
    for outcome, process in processes.items():
        output, _ = process.communicate()
        print(f"--- {outcome} DAP session ---")
        print(output.rstrip())
        if process.returncode != 0:
            failures.append(f"{outcome} exited with {process.returncode}")

    if failures:
        raise SystemExit("; ".join(failures))
    print("concurrent_dap_pair=pass sessions=2")


if __name__ == "__main__":
    main()
