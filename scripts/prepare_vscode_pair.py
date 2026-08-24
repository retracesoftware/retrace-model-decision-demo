from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess

from scripts.demo_state import ROOT
from scripts.prepare_vscode import prepare


def vscode_open_commands(
    code_cli: str,
    success_workspace: Path,
    failure_workspace: Path,
) -> list[list[str]]:
    return [
        [code_cli, "--new-window", str(success_workspace)],
        [code_cli, "--reuse-window", str(failure_workspace)],
    ]


def prepare_pair() -> tuple[Path, Path]:
    success = prepare("success")
    failure = prepare("failure")
    if success is None or failure is None:
        raise SystemExit("both selected recordings are required")
    return (
        success.with_suffix(".code-workspace"),
        failure.with_suffix(".code-workspace"),
    )


def remote_code_cli() -> str:
    if ROOT != Path("/app"):
        raise SystemExit(
            "Open the repository in its Dev Container, then run "
            "`make vscode-pair` in the VS Code terminal."
        )
    code_cli = shutil.which("code")
    if code_cli is None:
        raise SystemExit(
            "The VS Code remote CLI is unavailable. Run this command from "
            "the integrated terminal of the open Dev Container."
        )
    return code_cli


def open_pair(
    code_cli: str,
    success_workspace: Path,
    failure_workspace: Path,
) -> None:
    for command in vscode_open_commands(
        code_cli,
        success_workspace,
        failure_workspace,
    ):
        subprocess.run(command, check=True)

    print("vscode_pair=opened passing=new-window failing=current-window")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--open",
        action="store_true",
        help="open two VS Code windows after preparing both recordings",
    )
    args = parser.parse_args()
    code_cli = remote_code_cli() if args.open else None
    success_workspace, failure_workspace = prepare_pair()
    print(f"passing_workspace={success_workspace}")
    print(f"failing_workspace={failure_workspace}")
    if args.open:
        assert code_cli is not None
        open_pair(code_cli, success_workspace, failure_workspace)


if __name__ == "__main__":
    main()
