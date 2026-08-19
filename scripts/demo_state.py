from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "generated"
SESSION_HOME = GENERATED / "session-home"
SESSION_ARTIFACTS = SESSION_HOME / "retrace"
CASE = {
    "case_id": "CASE-MODEL-NONDETERMINISM-001",
    "serial_number": None,
    "user_prompt": (
        "Alice requests a GBP 125 refund for a damaged medical-device accessory. "
        "It is day 31 of a 30-day self-service window. A photo supports packaging "
        "damage but the serial number is partly obscured. She has four years of "
        "good account history and no earlier refunds. The accessory is not "
        "safety-critical but accompanies regulated equipment. Decide the next "
        "action now."
    ),
}


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def reset_generated() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)
    for child in GENERATED.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()

    for name in (
        "counters",
        "homes",
        "logs",
        "manifests",
        "recordings",
        "replay",
        "requests",
        "invocations",
        "transcripts",
        "telemetry",
    ):
        (GENERATED / name).mkdir(parents=True, exist_ok=True)
    for name in ("recordings", "manifests", "logs", "worker-homes"):
        (SESSION_ARTIFACTS / name).mkdir(parents=True, exist_ok=True)
    (GENERATED / "requests" / "identical-request.json").write_text(
        json.dumps(
            {
                "input": CASE["user_prompt"],
                "metadata": {
                    "demo_case_id": CASE["case_id"],
                    "purpose": "retrace-nondeterministic-model-decision",
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
