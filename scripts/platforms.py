from __future__ import annotations

from pathlib import Path
import platform
import subprocess


ARCHITECTURE_ALIASES = {
    "aarch64": "arm64",
    "amd64": "amd64",
    "arm64": "arm64",
    "x86_64": "amd64",
}


def normalize_architecture(value: str) -> str:
    architecture = ARCHITECTURE_ALIASES.get(value.strip().lower())
    if architecture is None:
        raise RuntimeError(f"unsupported Docker architecture: {value!r}")
    return architecture


def docker_architecture() -> str:
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.Architecture}}"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return normalize_architecture(platform.machine())
    return normalize_architecture(result.stdout)


def reviewed_artifact_directory(root: Path, architecture: str | None = None) -> Path:
    selected = architecture or docker_architecture()
    return root / "example-artifacts" / f"linux-{normalize_architecture(selected)}"
