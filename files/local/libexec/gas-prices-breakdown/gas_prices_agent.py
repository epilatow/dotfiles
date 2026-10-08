"""CLI selection and supervision for the snapshot utility's amendment pass."""

import json
import logging
import os
import signal
import subprocess
import time
from enum import StrEnum
from pathlib import Path
from types import FrameType

log = logging.getLogger(__name__)


class AgentError(RuntimeError):
    pass


class AgentCli(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"
    PI = "pi"
    MUSE = "muse"


def agent_command(
    agent: AgentCli,
    custom: str | None,
    prompt: str,
    workspace: Path,
    *,
    model: str | None = None,
) -> list[str]:
    """Select native argv; no shell interprets the prompt or configuration."""
    if model is not None and not model.strip():
        raise AgentError("model must not be empty")
    if custom is not None:
        try:
            value: object = json.loads(custom)
        except json.JSONDecodeError as exc:
            raise AgentError("agent command is not valid JSON") from exc
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(arg, str) or not arg for arg in value)
        ):
            raise AgentError("agent command must be a nonempty string array")
        command = [str(arg) for arg in value]
        if not any("{prompt}" in arg for arg in command):
            raise AgentError("agent command must contain {prompt}")
        has_model = any("{model}" in arg for arg in command)
        if model is not None and not has_model:
            raise AgentError(
                "custom agent command must contain {model} when --model is set"
            )
        if model is None and has_model:
            raise AgentError("custom {model} requires --model")
    else:
        commands = {
            AgentCli.CLAUDE: [
                "claude",
                "-p",
                "--permission-mode",
                "dontAsk",
                "--permission-prompts",
                "none",
                "--allowedTools",
                "Read,Write,Edit,Bash,WebSearch,WebFetch",
                "--no-session-persistence",
                "--output-format",
                "stream-json",
                "--verbose",
                "--",
                "{prompt}",
            ],
            AgentCli.CODEX: [
                "codex",
                "--search",
                "-a",
                "never",
                "exec",
                "-c",
                "sandbox_workspace_write.network_access=true",
                "--sandbox",
                "workspace-write",
                "--add-dir",
                str(workspace.parent.parent),
                "--skip-git-repo-check",
                "--ephemeral",
                "--json",
                "--",
                "{prompt}",
            ],
            AgentCli.OPENCODE: [
                "opencode",
                "run",
                "--auto",
                "--format",
                "json",
                "--",
                "{prompt}",
            ],
            AgentCli.PI: [
                "pi",
                "-p",
                "--no-session",
                "--mode",
                "json",
                "--",
                "{prompt}",
            ],
            AgentCli.MUSE: [
                "muse",
                "exec",
                "--approval-mode",
                "never",
                "--workspace",
                str(workspace),
                "--json",
                "--",
                "{prompt}",
            ],
        }
        command = commands[agent]
    expanded = [
        arg.replace("{workspace}", str(workspace))
        .replace("{model}", model or "")
        .replace("{prompt}", prompt)
        for arg in command
    ]
    if custom is None and model is not None:
        position = expanded.index("--")
        expanded[position:position] = ["--model", model]
    return expanded


def run_agent(command: list[str], workspace: Path) -> int:
    """Retain harness diagnostics; the amended-data blob owns the outcome."""
    with (
        (workspace / "agent.log").open("w") as output,
        subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process,
    ):

        def cancel(signum: int, _frame: FrameType | None) -> None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signum)
                except ProcessLookupError:
                    pass
            raise AgentError(f"agent interrupted by signal {signum}")

        previous = {
            sig: signal.signal(sig, cancel)
            for sig in (signal.SIGINT, signal.SIGTERM)
        }
        started = time.monotonic()
        try:
            identity = {"pid": process.pid, "pgid": process.pid}
            (workspace / "agent-process.json").write_text(json.dumps(identity))
            log.info(
                "agent pid=%d pgid=%d; artifacts: %s",
                process.pid,
                process.pid,
                workspace,
            )
            while True:
                try:
                    code = process.wait(timeout=60)
                    break
                except subprocess.TimeoutExpired:
                    log.info(
                        "agent still running after %.0fs",
                        time.monotonic() - started,
                    )
            (workspace / "agent-exit.json").write_text(
                json.dumps({"exit_code": code}) + "\n"
            )
            return code
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
