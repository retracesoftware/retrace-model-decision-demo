from __future__ import annotations

from pathlib import Path
import platform
import shutil

from scripts.platforms import normalize_architecture, reviewed_artifact_directory
from scripts.proof_manifest import verify_recording_proof


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "recordings" / "examples"


def prepare(architecture: str | None = None) -> Path:
    selected_architecture = normalize_architecture(architecture or platform.machine())
    source = reviewed_artifact_directory(ROOT, selected_architecture)
    DESTINATION.mkdir(parents=True, exist_ok=True)

    for outcome in ("success", "failure"):
        source_recording = source / f"selected-{outcome}.retrace"
        source_expected = source / f"selected-{outcome}.expected.json"
        source_proof = source / f"selected-{outcome}.proof.json"
        verify_recording_proof(
            source_recording,
            source_proof,
            expected_platform=f"linux/{selected_architecture}",
        )

        destination_recording = DESTINATION / f"{outcome}.retrace"
        shutil.copy2(source_recording, destination_recording)
        shutil.copy2(source_expected, DESTINATION / f"{outcome}.expected.json")
        shutil.copy2(source_proof, DESTINATION / f"{outcome}.proof.json")
        destination_recording.chmod(destination_recording.stat().st_mode | 0o111)

    print(f"example_recordings={DESTINATION}")
    print("success_recording=recordings/examples/success.retrace")
    print("failure_recording=recordings/examples/failure.retrace")
    return DESTINATION


if __name__ == "__main__":
    prepare()
