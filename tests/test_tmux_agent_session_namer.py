from __future__ import annotations

import ast
import json
import os
import shutil
import sqlite3
import subprocess
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

REPO_ROOT = Path(__file__).parents[1]
HELPER = (
    REPO_ROOT
    / "files"
    / "local"
    / "libexec"
    / "tmux-agent-session-namer"
    / "tmux-agent-session-namer"
)
CLAUDE_WRAPPER = (
    REPO_ROOT
    / "files"
    / "claude"
    / "skills"
    / "tmux-namer"
    / "hooks"
    / "tmux-name.sh"
)
MUSE_PLUGIN_MANIFEST = (
    REPO_ROOT
    / "files"
    / "muse"
    / "tmux-namer"
    / ".muse-plugin"
    / "plugin.json"
)
PI_EXTENSION = (
    REPO_ROOT / "files" / "pi" / "agent" / "extensions" / "tmux-namer.ts"
)
OPENCODE_PLUGIN = (
    REPO_ROOT / "files" / "config" / "opencode" / "plugins" / "tmux-namer.ts"
)
STATUS_COMMANDS = [
    "set-option status-left [#{session_name}] ",
    "set-option status-left-length 34",
    (
        "set-option status-right "
        "#{?window_bigger,[#{window_offset_x}#,#{window_offset_y}] ,}"
        "%H:%M %d-%b-%y"
    ),
    "set-option window-status-format ",
    "set-option window-status-current-format ",
    "set-option window-status-separator ",
]
PANE_START_COMMAND = "display-message -p -t %0 #{pane_start_command}"
OWNER_READ_ONLY_COMMANDS = [
    PANE_START_COMMAND,
    "show-options -qv @agent_namer",
]
REFUSED_SLOT_COMMANDS = [
    PANE_START_COMMAND,
    "wait-for -L tmux-agent-session-namer-slots",
    "show-options -qv @agent_namer",
    "wait-for -U tmux-agent-session-namer-slots",
]
# What `agent_stub` is running once its exec has replaced the shell.
AGENT_STUB_COMMAND = "sleep"
PANE_COMMAND_TIMEOUT_SEC = 10.0
CODEX_HOOKS = REPO_ROOT / "files" / "codex" / "hooks.json"
CRONY_CONFIG = REPO_ROOT / "files" / "config" / "crony" / "config.toml"
ENVRC_ALIASES = REPO_ROOT / "files" / "envrc.aliases"


@pytest.fixture
def fake_tmux(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    tmux = bin_dir / "tmux"
    tmux.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_TMUX_LOG"
case "$1" in
    display-message)
        case "$*" in
            *session_name*)
                printf '%s' "${FAKE_TMUX_SESSION_NAME-}"
                ;;
            *)
                printf '%s' "${FAKE_TMUX_START-claude}"
                ;;
        esac
        ;;
    show-options)
        case "$*" in
            *@agent_namer*)
                printf '%s' "${FAKE_TMUX_OWNER-}"
                ;;
            *)
                printf '%s' "${FAKE_TMUX_CURRENT_NUM-}"
                ;;
        esac
        ;;
    list-sessions)
        printf '%s' "${FAKE_TMUX_USED_NUMS-}"
        ;;
    list-panes)
        printf '%s' "${FAKE_TMUX_PANES-}"
        ;;
esac
exit 0
""",
    )
    tmux.chmod(0o755)
    codex = bin_dir / "codex"
    codex.write_text(
        """#!/bin/sh
initialized=
while IFS= read -r line; do
    printf '%s\n' "$line" >> "$FAKE_CODEX_LOG"
    case "$line" in
        *'"id": 1,'*)
            printf '%s\n' '{"id":1,"result":{}}'
            ;;
        *'"method": "initialized"'*)
            initialized=yes
            ;;
        *'"method": "config/read"'*)
            [ "$initialized" = yes ] || exit 2
            printf '%s\n' '{"method":"status/changed","params":{}}'
            printf '%s' '{"id":2,"result":{"config":{"tui":{'
            case "$line" in
                *'"cwd":'*)
                    printf '"terminal_title":%s' \
                        "${FAKE_CODEX_PROJECT_TERMINAL_TITLE-${FAKE_CODEX_TERMINAL_TITLE-null}}"
                    ;;
                *)
                    printf '"terminal_title":%s' \
                        "${FAKE_CODEX_TERMINAL_TITLE-null}"
                    ;;
            esac
            printf '%s\n' '}}}}'
            ;;
        *'"method": "thread/read"'*)
            [ "$initialized" = yes ] || exit 2
            printf '%s' '{"id":2,"result":{"thread":{'
            printf '"name":%s,' "${FAKE_CODEX_THREAD_NAME-null}"
            printf '"preview":%s' "${FAKE_CODEX_THREAD_PREVIEW-null}"
            printf '%s\n' '}}}'
            ;;
    esac
done
""",
    )
    codex.chmod(0o755)
    return bin_dir, log


def run_helper(
    fake_tmux: tuple[Path, Path],
    *args: str,
    in_tmux: bool = True,
    extra_env: Mapping[str, str] | None = None,
    hook_input: Mapping[str, object] | None = None,
    script: Path = HELPER,
) -> subprocess.CompletedProcess[str]:
    bin_dir, log = fake_tmux
    env = os.environ.copy()
    env.update(
        {
            "FAKE_CODEX_LOG": str(log.with_name("codex.log")),
            "FAKE_TMUX_LOG": str(log),
            "PATH": f"{bin_dir}:{env['PATH']}",
        },
    )
    if in_tmux:
        env["TMUX"] = "/tmp/tmux,fake,0"
        env["TMUX_PANE"] = "%0"
    else:
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
    if extra_env is not None:
        env.update(extra_env)

    return subprocess.run(
        [str(script), *args],
        check=False,
        capture_output=True,
        env=env,
        input=json.dumps(
            hook_input
            if hook_input is not None
            else {
                "hook_event_name": "SessionStart",
                "session_id": "test",
            }
        ),
        text=True,
    )


@pytest.fixture
def claude_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    installed_helper = (
        home
        / ".local"
        / "libexec"
        / "tmux-agent-session-namer"
        / "tmux-agent-session-namer"
    )
    installed_helper.parent.mkdir(parents=True)
    installed_helper.symlink_to(HELPER)
    return home


@pytest.fixture
def real_tmux_server(
    fake_tmux: tuple[Path, Path],
) -> Iterator[tuple[str, str]]:
    real_tmux = shutil.which("tmux")
    if real_tmux is None:
        pytest.skip("tmux is not installed")
    (fake_tmux[0] / "tmux").unlink()
    server = f"tmux-agent-session-namer-test-{uuid4().hex}"
    try:
        yield real_tmux, server
    finally:
        subprocess.run(
            [real_tmux, "-L", server, "kill-server"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def agent_stub(bin_dir: Path, name: str) -> Path:
    """Write an executable named for an agent launcher that just waits.

    It execs, the way tcodex's launcher becomes codex, so a session
    built from one holds a pane whose running command is no longer the
    command tmux recorded starting it with.

    Rewriting the file is deliberately skipped when the content already
    matches: `write_text` truncates, and truncating a script that a
    previously started session's shell has not finished reading kills
    that session.
    """
    stub = bin_dir / name
    body = f"#!/bin/sh\nexec {AGENT_STUB_COMMAND} 300\n"
    if not stub.exists() or stub.read_text() != body:
        stub.write_text(body)
        stub.chmod(0o755)
    return stub


def wait_for_pane_command(
    real_tmux_server: tuple[str, str], pane_id: str, expected: str
) -> None:
    """Block until `pane_id` reports `expected` as its running command.

    A pane tmux has just started is still running the stub's shell for a
    moment, until the `exec` replaces it. Every caller here cares about
    the state after that, so waiting for it is what makes the session
    settled rather than merely created.
    """
    real_tmux, server = real_tmux_server
    deadline = time.monotonic() + PANE_COMMAND_TIMEOUT_SEC
    while True:
        running = subprocess.run(
            [
                real_tmux,
                "-L",
                server,
                "display-message",
                "-p",
                "-t",
                pane_id,
                "#{pane_current_command}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if running == expected:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"pane {pane_id} still running {running!r} after "
                f"{PANE_COMMAND_TIMEOUT_SEC}s; expected {expected!r}"
            )
        time.sleep(0.01)


def wait_for_session_name(
    real_tmux_server: tuple[str, str], pane_id: str, expected: str
) -> None:
    """Block until `pane_id`'s session reports `expected` as its name."""
    real_tmux, server = real_tmux_server
    deadline = time.monotonic() + PANE_COMMAND_TIMEOUT_SEC
    while True:
        name = subprocess.run(
            [
                real_tmux,
                "-L",
                server,
                "display-message",
                "-p",
                "-t",
                pane_id,
                "#{session_name}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if name == expected:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"pane {pane_id} still in {name!r} after "
                f"{PANE_COMMAND_TIMEOUT_SEC}s; expected {expected!r}"
            )
        time.sleep(0.1)


def create_tmux_session(
    real_tmux_server: tuple[str, str],
    name: str,
    command: str | None = None,
) -> dict[str, str]:
    real_tmux, server = real_tmux_server
    subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "new-session",
            "-d",
            "-s",
            name,
            *([command] if command is not None else []),
        ],
        check=True,
    )
    details = subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "display-message",
            "-p",
            "-t",
            name,
            "#{socket_path},#{pid},#{session_id},#{pane_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    socket_path, pid, session_id, pane_id = details.split(",")
    if command is not None:
        wait_for_pane_command(real_tmux_server, pane_id, AGENT_STUB_COMMAND)
    return {
        "TMUX": f"{socket_path},{pid},{session_id.removeprefix('$')}",
        "TMUX_PANE": pane_id,
    }


def accepted_start_commands() -> frozenset[str]:
    """Read AGENT_START_COMMANDS out of the helper's source.

    The helper is an extension-less uv script rather than an importable
    module, and this needs the value the deployed script actually holds
    rather than a copy of it kept here.
    """
    for node in ast.walk(ast.parse(HELPER.read_text())):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "AGENT_START_COMMANDS"
            for target in node.targets
        ):
            continue
        call = node.value
        assert isinstance(call, ast.Call)
        return frozenset(
            cast("tuple[str, ...]", ast.literal_eval(call.args[0])),
        )
    raise AssertionError(f"AGENT_START_COMMANDS is unset in {HELPER}")


def read_session_option(
    real_tmux_server: tuple[str, str],
    option: str,
) -> str:
    real_tmux, server = real_tmux_server
    return subprocess.run(
        [real_tmux, "-L", server, "show-options", "-qv", option],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_codex_session_start_hook_uses_guarded_namer() -> None:
    config = json.loads(CODEX_HOOKS.read_text())

    assert config == {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                '"${HOME}/.local/libexec/'
                                "tmux-agent-session-namer/"
                                'tmux-agent-session-namer" codex-hook'
                            ),
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                '"${HOME}/.local/libexec/'
                                "tmux-agent-session-namer/"
                                'tmux-agent-session-namer" codex-hook'
                            ),
                        }
                    ],
                }
            ],
        }
    }


def _write_argv_logger(path: Path, label: str) -> None:
    # The tmux logger answers the pane-start-command probe as a pane tmux
    # was given an agent to run, so a logged run reaches the naming the
    # caller is there to observe rather than being refused before it.
    path.write_text(
        f"""#!/bin/sh
printf '%s' '{label}' >> "$ARGV_LOG"
for arg in "$@"; do
    printf '\\t%s' "$arg" >> "$ARGV_LOG"
done
printf '\\n' >> "$ARGV_LOG"
case "$1" in
    display-message)
        printf '%s' "${{FAKE_TMUX_START-claude}}"
        ;;
esac
""",
    )
    path.chmod(0o755)


def test_remote_mode_configures_tmux_client_before_codex(
    tmp_path: Path,
    fake_tmux: tuple[Path, Path],
) -> None:
    bin_dir = fake_tmux[0]
    _write_argv_logger(bin_dir / "tmux", "tmux")
    _write_argv_logger(bin_dir / "codex", "codex")
    log = tmp_path / "argv.log"
    env = os.environ.copy()
    env.update(
        {
            "ARGV_LOG": str(log),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMUX": "/tmp/tmux,fake,0",
            "TMUX_PANE": "%0",
        },
    )

    result = subprocess.run(
        [str(HELPER), "codex-remote", "resume", "thread id"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    calls = log.read_text().splitlines()
    assert all(call.startswith("tmux\t") for call in calls[:-1])
    assert any(
        call.startswith("tmux\tset-hook\tpane-title-changed") for call in calls
    )
    assert any(call.startswith("tmux\trename-session") for call in calls)
    assert calls[-1] == (
        "codex\t--remote\tunix://\t-c\t"
        'tui.terminal_title=["thread-title"]\tresume\tthread id'
    )


def test_envrc_tcodex_functions_preserve_arguments(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_argv_logger(bin_dir / "tmux", "tmux")
    log = tmp_path / "argv.log"
    env = os.environ.copy()
    env.update(
        {
            "ARGV_LOG": str(log),
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
        },
    )

    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            '. "$1"; tcodex resume "thread id"; tcodexd --foo',
            "sh",
            str(ENVRC_ALIASES),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    helper = (
        f"{home}/.local/libexec/tmux-agent-session-namer/"
        "tmux-agent-session-namer"
    )
    assert result.returncode == 0
    assert log.read_text().splitlines() == [
        f"tmux\tnew\t{helper}\tcodex-remote\tresume\tthread id",
        (
            f"tmux\tnew\t{helper}\tcodex-remote\t"
            "--dangerously-bypass-approvals-and-sandbox\t--foo"
        ),
    ]


def test_the_launcher_aliases_run_commands_the_helper_accepts(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_argv_logger(bin_dir / "tmux", "tmux")
    helper_dir = home / ".local" / "libexec" / "tmux-agent-session-namer"
    helper_dir.mkdir(parents=True)
    _write_argv_logger(helper_dir / "tmux-agent-session-namer", "helper")
    log = tmp_path / "argv.log"
    env = os.environ.copy()
    env.update(
        {
            "ARGV_LOG": str(log),
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
        },
    )

    # tcodex, tmuse, and tmused are functions and run as written. The
    # rest are aliases, and a non-interactive bash expands one only
    # under expand_aliases and only on input parsed after the alias
    # exists, hence the eval. A sh without either lands on the count
    # assertions below rather than passing quietly. tmuse and tmused
    # start the helper as the pane command, like tcodex does; the rest
    # run their agent directly.
    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            (
                'shopt -s expand_aliases 2>/dev/null; . "$1"; '
                "eval 'tclaude; tmuse; tmused --foo; tpi; topencode'; "
                "tcodex"
            ),
            "sh",
            str(ENVRC_ALIASES),
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    launched = [call.split("\t") for call in log.read_text().splitlines()]
    tmux_calls = [argv[1:] for argv in launched if argv[0] == "tmux"]
    helper = (
        f"{home}/.local/libexec/tmux-agent-session-namer/"
        "tmux-agent-session-namer"
    )
    assert [argv[1:] for argv in tmux_calls] == [
        ["claude"],
        [helper, "muse-run"],
        [helper, "muse-run", "--yolo", "--foo"],
        ["pi"],
        ["opencode"],
        [helper, "codex-remote"],
    ]
    assert {
        os.path.basename(argv[1]) for argv in tmux_calls
    } <= accepted_start_commands()


def test_crony_runs_one_shared_remote_control_app_server() -> None:
    config = tomllib.loads(CRONY_CONFIG.read_text())

    assert config["job"]["codex-remote-control"] == {
        "command": ("codex app-server --remote-control --listen unix://"),
        "gate": "command -v codex",
        "env": {"PATH": "$PATH:$HOME/.local/bin"},
        "daemon": True,
        "uuid": "4c392a33-485b-4a2a-abd6-4d029d151769",
    }
    assert config["defaults"]["keep-awake"] is True
    assert "codex-archive" not in config["job"]
    assert "u-hourly" not in config["job-group"]
    assert config["target"]["host"]["squee"]["jobs"] == [
        "u-weekly",
        "u-daily",
        "codex-remote-control",
    ]


def test_helper_is_python_314_uv_script() -> None:
    lines = HELPER.read_text().splitlines()

    assert lines[:5] == [
        "#!/usr/bin/env -S uv run --script",
        "# /// script",
        '# requires-python = ">=3.14"',
        "# dependencies = []",
        "# ///",
    ]


def test_does_nothing_outside_tmux(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        in_tmux=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert not fake_tmux[1].exists()


@pytest.mark.parametrize(
    "terminal_title",
    [
        "null",
        '["activity", "project"]',
        '["thread", "project"]',
    ],
)
def test_codex_warns_and_skips_tmux_without_thread_only_title(
    fake_tmux: tuple[Path, Path],
    terminal_title: str,
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={"FAKE_CODEX_TERMINAL_TITLE": terminal_title},
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "continue": True,
        "systemMessage": (
            "tmux naming disabled: run /title and select only Thread, then "
            "start a new Codex session."
        ),
    }
    assert fake_tmux[1].read_text().splitlines() == OWNER_READ_ONLY_COMMANDS


def test_codex_guard_rejects_global_title_even_if_project_enables_thread(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["activity", "project"]',
            "FAKE_CODEX_PROJECT_TERMINAL_TITLE": '["thread"]',
        },
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "continue": True,
        "systemMessage": (
            "tmux naming disabled: run /title and select only Thread, then "
            "start a new Codex session."
        ),
    }
    assert fake_tmux[1].read_text().splitlines() == OWNER_READ_ONLY_COMMANDS


def test_codex_guard_rejects_project_disabling_thread_title(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_CODEX_PROJECT_TERMINAL_TITLE": ('["spinner", "project"]'),
        },
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "continue": True,
        "systemMessage": (
            'tmux naming disabled: set [tui] terminal_title = ["thread"] '
            "in the applicable .codex/config.toml, then start a new Codex "
            "session."
        ),
    }
    assert fake_tmux[1].read_text().splitlines() == OWNER_READ_ONLY_COMMANDS


@pytest.mark.parametrize(
    "terminal_title",
    [
        '["thread"]',
        '["thread-title"]',
    ],
)
def test_codex_allocates_slot_and_tracks_thread_title(
    fake_tmux: tuple[Path, Path],
    terminal_title: str,
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-client",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": terminal_title,
            "FAKE_TMUX_USED_NUMS": "00\n01\n",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    commands = fake_tmux[1].read_text().splitlines()
    assert "set-option @codex_num 02" in commands
    assert any(
        command.startswith("set-hook pane-title-changed ")
        and "codex#{@codex_num}-#{s| |-|:#{pane_title}}" in command
        for command in commands
    )
    assert any(
        command.startswith("rename-session #{?pane_title,")
        and "codex#{@codex_num}-#{s| |-|:#{pane_title}}" in command
        for command in commands
    )
    assert "set-option status-left-length 34" in commands
    assert "set-option status-left [#{session_name}] " in commands


def test_codex_client_trusts_the_launchers_title_override(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-client",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["activity", "project"]',
        },
    )

    assert result.returncode == 0
    assert result.stderr == ""
    commands = fake_tmux[1].read_text().splitlines()
    assert any(
        command.startswith("set-hook pane-title-changed ")
        for command in commands
    )
    assert not fake_tmux[1].with_name("codex.log").exists()


def test_codex_stop_renames_from_explicit_thread_name(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_CODEX_THREAD_NAME": json.dumps("Feline Ideas"),
            "FAKE_CODEX_THREAD_PREVIEW": json.dumps("Suggest cat names"),
            "FAKE_TMUX_CURRENT_NUM": "04",
        },
        hook_input={
            "hook_event_name": "Stop",
            "session_id": "target-thread-id",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "show-options -qv @agent_namer",
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        "show-options -qv @codex_num",
        "set-option @agent_namer codex",
        "wait-for -U tmux-agent-session-namer-slots",
        *STATUS_COMMANDS,
        "rename-session codex04-Feline-Ideas",
    ]
    codex_messages = [
        json.loads(line)
        for line in fake_tmux[1]
        .with_name("codex.log")
        .read_text()
        .splitlines()
    ]
    assert {
        "id": 2,
        "method": "thread/read",
        "params": {
            "threadId": "target-thread-id",
            "includeTurns": False,
        },
    } in codex_messages


def test_codex_stop_falls_back_to_preview_and_allocates_slot(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_CODEX_THREAD_PREVIEW": json.dumps(
                "Suggest cat names\nplease"
            ),
            "FAKE_TMUX_USED_NUMS": "00\n",
        },
        hook_input={
            "hook_event_name": "Stop",
            "session_id": "unnamed-thread-id",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "show-options -qv @agent_namer",
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        "show-options -qv @codex_num",
        "list-sessions -F #{@codex_num}",
        "set-option @codex_num 01",
        "set-option @agent_namer codex",
        "wait-for -U tmux-agent-session-namer-slots",
        *STATUS_COMMANDS,
        "rename-session codex01-Suggest-cat-names-plea",
    ]


def test_codex_stop_treats_title_as_literal_tmux_format(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
) -> None:
    tmux_environment = create_tmux_session(
        real_tmux_server,
        "literal",
        str(agent_stub(fake_tmux[0], "tmux-agent-session-namer")),
    )
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_CODEX_THREAD_NAME": json.dumps(
                "Literal #(true) #{session_id}"
            ),
            **tmux_environment,
        },
        hook_input={
            "hook_event_name": "Stop",
            "session_id": "literal-thread-id",
        },
    )

    assert result.returncode == 0
    real_tmux, server = real_tmux_server
    session_name = subprocess.run(
        [real_tmux, "-L", server, "display-message", "-p", "#S"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert session_name == "codex00-Literal-#(true)-#{sess"


def test_codex_pane_title_hook_treats_title_as_literal_tmux_format(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
) -> None:
    tmux_environment = create_tmux_session(
        real_tmux_server,
        "literal",
        str(agent_stub(fake_tmux[0], "tmux-agent-session-namer")),
    )
    result = run_helper(
        fake_tmux,
        "codex-client",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            **tmux_environment,
        },
    )

    assert result.returncode == 0
    real_tmux, server = real_tmux_server
    subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "select-pane",
            "-t",
            tmux_environment["TMUX_PANE"],
            "-T",
            "Review ##S ##{session_id}",
        ],
        check=True,
    )
    session_name = subprocess.run(
        [real_tmux, "-L", server, "display-message", "-p", "#S"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert session_name == "codex00-Review-#S-#{session_id"


def test_concurrent_codex_starts_allocate_distinct_slots(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
) -> None:
    session_count = 12
    tmux_environments = [
        create_tmux_session(
            real_tmux_server,
            f"concurrent-{number}",
            str(agent_stub(fake_tmux[0], "tmux-agent-session-namer")),
        )
        for number in range(session_count)
    ]

    def start_helper(tmux_environment: dict[str, str]) -> int:
        return run_helper(
            fake_tmux,
            "codex-client",
            extra_env={
                "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
                **tmux_environment,
            },
        ).returncode

    with ThreadPoolExecutor(max_workers=session_count) as executor:
        return_codes = list(executor.map(start_helper, tmux_environments))

    assert return_codes == [0] * session_count
    real_tmux, server = real_tmux_server
    slots = subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "list-sessions",
            "-F",
            "#{@codex_num}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert sorted(slots) == [f"{number:02d}" for number in range(12)]


def test_codex_stop_skips_tmux_without_thread_only_title(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["activity", "project"]',
            "FAKE_CODEX_THREAD_NAME": json.dumps("Feline Ideas"),
        },
        hook_input={
            "hook_event_name": "Stop",
            "session_id": "target-thread-id",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == OWNER_READ_ONLY_COMMANDS
    codex_messages = [
        json.loads(line)
        for line in fake_tmux[1]
        .with_name("codex.log")
        .read_text()
        .splitlines()
    ]
    assert not any(
        message.get("method") == "thread/read" for message in codex_messages
    )


def test_does_not_reuse_a_slot_when_all_are_allocated(
    fake_tmux: tuple[Path, Path],
) -> None:
    used = "\n".join(f"{slot:02d}" for slot in range(100))
    result = run_helper(
        fake_tmux,
        "codex-client",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_TMUX_USED_NUMS": used,
        },
    )

    assert result.returncode == 0
    commands = fake_tmux[1].read_text().splitlines()
    assert commands == [
        PANE_START_COMMAND,
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        "show-options -qv @codex_num",
        "list-sessions -F #{@codex_num}",
        "wait-for -U tmux-agent-session-namer-slots",
    ]


def test_claude_reuses_slot_and_strips_leading_status(
    fake_tmux: tuple[Path, Path],
    claude_home: Path,
) -> None:
    result = run_helper(
        fake_tmux,
        extra_env={
            "FAKE_TMUX_CURRENT_NUM": "07",
            "HOME": str(claude_home),
        },
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    commands = fake_tmux[1].read_text().splitlines()
    assert not any(
        command.startswith("set-option @claude_num") for command in commands
    )
    assert any(
        command.startswith("set-hook pane-title-changed ")
        and "claude#{@claude_num}-#{s| |-|:#{s|^. ||:pane_title}}" in command
        for command in commands
    )
    assert "set-option @agent_namer claude" in commands


def test_codex_start_leaves_a_session_claude_names_alone(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-client",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_TMUX_OWNER": "claude",
        },
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == REFUSED_SLOT_COMMANDS


@pytest.mark.parametrize(
    ("hook_input", "expected_stdout"),
    [
        (
            {"hook_event_name": "SessionStart", "session_id": "test"},
            {
                "continue": True,
                "systemMessage": (
                    "tmux naming disabled: claude already names this "
                    "tmux session."
                ),
            },
        ),
        (
            {"hook_event_name": "Stop", "session_id": "target-thread-id"},
            None,
        ),
    ],
)
def test_codex_hook_leaves_a_session_claude_names_alone(
    fake_tmux: tuple[Path, Path],
    hook_input: Mapping[str, object],
    expected_stdout: Mapping[str, object] | None,
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["activity", "project"]',
            "FAKE_CODEX_THREAD_NAME": json.dumps("Feline Ideas"),
            "FAKE_TMUX_OWNER": "claude",
        },
        hook_input=hook_input,
    )

    assert result.returncode == 0
    if expected_stdout is None:
        assert result.stdout == ""
    else:
        assert json.loads(result.stdout) == expected_stdout
    assert fake_tmux[1].read_text().splitlines() == OWNER_READ_ONLY_COMMANDS
    assert not fake_tmux[1].with_name("codex.log").exists()


def test_claude_leaves_a_session_codex_names_alone(
    fake_tmux: tuple[Path, Path],
    claude_home: Path,
) -> None:
    result = run_helper(
        fake_tmux,
        extra_env={
            "FAKE_TMUX_CURRENT_NUM": "07",
            "FAKE_TMUX_OWNER": "codex",
            "HOME": str(claude_home),
        },
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == REFUSED_SLOT_COMMANDS


def test_codex_stop_renames_a_session_it_already_owns(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            "FAKE_CODEX_THREAD_NAME": json.dumps("Feline Ideas"),
            "FAKE_TMUX_CURRENT_NUM": "04",
            "FAKE_TMUX_OWNER": "codex",
        },
        hook_input={
            "hook_event_name": "Stop",
            "session_id": "target-thread-id",
        },
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "show-options -qv @agent_namer",
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        "show-options -qv @codex_num",
        "wait-for -U tmux-agent-session-namer-slots",
        *STATUS_COMMANDS,
        "rename-session codex04-Feline-Ideas",
    ]


def test_claude_reconfigures_a_session_it_already_owns(
    fake_tmux: tuple[Path, Path],
    claude_home: Path,
) -> None:
    result = run_helper(
        fake_tmux,
        extra_env={
            "FAKE_TMUX_CURRENT_NUM": "07",
            "FAKE_TMUX_OWNER": "claude",
            "HOME": str(claude_home),
        },
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    commands = fake_tmux[1].read_text().splitlines()
    assert any(
        command.startswith("set-hook pane-title-changed ")
        for command in commands
    )
    assert not any(
        command.startswith("set-option @agent_namer") for command in commands
    )


def test_an_agent_started_inside_a_session_keeps_the_owners_naming(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
    claude_home: Path,
) -> None:
    tmux_environment = create_tmux_session(
        real_tmux_server,
        "owned",
        str(agent_stub(fake_tmux[0], "tmux-agent-session-namer")),
    )
    owner = run_helper(
        fake_tmux,
        "codex-client",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["thread"]',
            **tmux_environment,
        },
    )
    assert owner.returncode == 0

    nested = run_helper(
        fake_tmux,
        extra_env={"HOME": str(claude_home), **tmux_environment},
        script=CLAUDE_WRAPPER,
    )

    assert nested.returncode == 0
    assert read_session_option(real_tmux_server, "@agent_namer") == "codex"
    assert read_session_option(real_tmux_server, "@claude_num") == ""
    assert "codex#{@codex_num}-#{s| |-|:#{pane_title}}" in (
        read_session_option(real_tmux_server, "pane-title-changed")
    )
    real_tmux, server = real_tmux_server
    subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "select-pane",
            "-t",
            tmux_environment["TMUX_PANE"],
            "-T",
            "* Nested Title",
        ],
        check=True,
    )
    session_name = subprocess.run(
        [real_tmux, "-L", server, "display-message", "-p", "#S"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert session_name == "codex00-*-Nested-Title"


@pytest.mark.parametrize(
    ("start_command", "names_the_session"),
    [
        ("", False),
        ("zsh", False),
        ("vim", False),
        ("claude-code-wrapper", False),
        ('"claude --unbalanced', False),
        ("claude --dangerously-skip-permissions", True),
        ('"/opt/some path/claude" --dangerously-skip-permissions', True),
        ("muse", False),
        ("muse --yolo", False),
        (
            (
                "/home/u/.local/libexec/tmux-agent-session-namer"
                "/tmux-agent-session-namer codex-remote resume"
            ),
            True,
        ),
    ],
)
def test_only_a_pane_tmux_started_an_agent_in_is_named(
    fake_tmux: tuple[Path, Path],
    claude_home: Path,
    start_command: str,
    names_the_session: bool,
) -> None:
    result = run_helper(
        fake_tmux,
        extra_env={
            "FAKE_TMUX_CURRENT_NUM": "07",
            "FAKE_TMUX_START": start_command,
            "HOME": str(claude_home),
        },
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    commands = fake_tmux[1].read_text().splitlines()
    configured = any(
        command.startswith("set-hook pane-title-changed ")
        for command in commands
    )
    assert configured is names_the_session
    if not names_the_session:
        assert commands == [PANE_START_COMMAND]


def test_nothing_is_named_when_tmux_names_no_pane(
    fake_tmux: tuple[Path, Path],
    claude_home: Path,
) -> None:
    result = run_helper(
        fake_tmux,
        extra_env={
            "FAKE_TMUX_CURRENT_NUM": "07",
            "FAKE_TMUX_START": "claude",
            "HOME": str(claude_home),
            "TMUX_PANE": "",
        },
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    assert not fake_tmux[1].exists()


def test_codex_hook_reads_no_thread_for_a_pane_tmux_gave_a_shell(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "codex-hook",
        extra_env={
            "FAKE_CODEX_TERMINAL_TITLE": '["activity", "project"]',
            "FAKE_TMUX_START": "",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [PANE_START_COMMAND]
    assert not fake_tmux[1].with_name("codex.log").exists()


def test_a_session_is_named_from_the_command_tmux_started_it_with(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
    claude_home: Path,
) -> None:
    tmux_environment = create_tmux_session(
        real_tmux_server,
        "launched",
        str(agent_stub(fake_tmux[0], "claude")),
    )

    result = run_helper(
        fake_tmux,
        extra_env={"HOME": str(claude_home), **tmux_environment},
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    assert read_session_option(real_tmux_server, "@agent_namer") == "claude"
    real_tmux, server = real_tmux_server
    running = subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "display-message",
            "-p",
            "-t",
            tmux_environment["TMUX_PANE"],
            "#{pane_current_command}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert running == AGENT_STUB_COMMAND
    subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "select-pane",
            "-t",
            tmux_environment["TMUX_PANE"],
            "-T",
            "* Launched Title",
        ],
        check=True,
    )
    session_name = subprocess.run(
        [real_tmux, "-L", server, "display-message", "-p", "#S"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert session_name == "claude00-Launched-Title"


def test_a_shell_session_keeps_its_name_when_an_agent_starts_in_it(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
    claude_home: Path,
) -> None:
    tmux_environment = create_tmux_session(real_tmux_server, "handmade")

    result = run_helper(
        fake_tmux,
        extra_env={"HOME": str(claude_home), **tmux_environment},
        script=CLAUDE_WRAPPER,
    )

    assert result.returncode == 0
    real_tmux, server = real_tmux_server
    subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "select-pane",
            "-t",
            tmux_environment["TMUX_PANE"],
            "-T",
            "* Renamed Title",
        ],
        check=True,
    )
    session_name = subprocess.run(
        [real_tmux, "-L", server, "display-message", "-p", "#S"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert session_name == "handmade"
    assert read_session_option(real_tmux_server, "@agent_namer") == ""
    assert read_session_option(real_tmux_server, "@claude_num") == ""
    assert read_session_option(real_tmux_server, "pane-title-changed") == ""


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("other",),
        ("codex;bad",),
        ("codex-hook", "--require-codex-thread-title"),
        ("claude", "--strip-leading-status"),
        ("muse",),
        ("muse", "first", "second"),
        ("muse-hook", "extra"),
        ("muse-watch",),
        ("opencode",),
        ("opencode", "first", "second"),
        ("pi",),
        ("pi", "first", "second"),
    ],
)
def test_rejects_unknown_or_extra_subcommand(
    fake_tmux: tuple[Path, Path],
    args: tuple[str, ...],
) -> None:
    result = run_helper(fake_tmux, *args)

    assert result.returncode == 2
    assert not fake_tmux[1].exists()


@pytest.mark.parametrize(
    ("invocation", "start_command"),
    [
        ("opencode", "opencode"),
        ("pi", "pi --name Whatever"),
    ],
)
def test_named_run_renames_with_allocated_slot(
    fake_tmux: tuple[Path, Path],
    invocation: str,
    start_command: str,
) -> None:
    result = run_helper(
        fake_tmux,
        invocation,
        "Session Name",
        extra_env={
            "FAKE_TMUX_START": start_command,
            "FAKE_TMUX_USED_NUMS": "00\n",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        f"show-options -qv @{invocation}_num",
        f"list-sessions -F #{{@{invocation}_num}}",
        f"set-option @{invocation}_num 01",
        f"set-option @agent_namer {invocation}",
        "wait-for -U tmux-agent-session-namer-slots",
        *STATUS_COMMANDS,
        f"rename-session {invocation}01-Session-Name",
    ]


@pytest.mark.parametrize("invocation", ["opencode", "pi"])
def test_named_run_reuses_its_slot_on_rename(
    fake_tmux: tuple[Path, Path],
    invocation: str,
) -> None:
    result = run_helper(
        fake_tmux,
        invocation,
        "Second Name",
        extra_env={
            "FAKE_TMUX_START": invocation,
            "FAKE_TMUX_CURRENT_NUM": "04",
            "FAKE_TMUX_OWNER": invocation,
        },
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        f"show-options -qv @{invocation}_num",
        "wait-for -U tmux-agent-session-namer-slots",
        *STATUS_COMMANDS,
        f"rename-session {invocation}04-Second-Name",
    ]


@pytest.mark.parametrize("invocation", ["opencode", "pi"])
def test_named_run_leaves_a_session_claude_names_alone(
    fake_tmux: tuple[Path, Path],
    invocation: str,
) -> None:
    result = run_helper(
        fake_tmux,
        invocation,
        "Session Name",
        extra_env={
            "FAKE_TMUX_START": invocation,
            "FAKE_TMUX_OWNER": "claude",
        },
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == REFUSED_SLOT_COMMANDS


@pytest.mark.parametrize("invocation", ["opencode", "pi"])
def test_named_run_skips_a_shell_pane(
    fake_tmux: tuple[Path, Path],
    invocation: str,
) -> None:
    result = run_helper(
        fake_tmux,
        invocation,
        "Session Name",
        extra_env={"FAKE_TMUX_START": ""},
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [PANE_START_COMMAND]


@pytest.mark.parametrize("invocation", ["opencode", "pi"])
def test_named_run_renames_to_the_bare_slot_for_an_empty_name(
    fake_tmux: tuple[Path, Path],
    invocation: str,
) -> None:
    result = run_helper(
        fake_tmux,
        invocation,
        "   ",
        extra_env={"FAKE_TMUX_START": invocation},
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        f"show-options -qv @{invocation}_num",
        f"list-sessions -F #{{@{invocation}_num}}",
        f"set-option @{invocation}_num 00",
        f"set-option @agent_namer {invocation}",
        "wait-for -U tmux-agent-session-namer-slots",
        *STATUS_COMMANDS,
        f"rename-session {invocation}00",
    ]


def test_tmuse_launcher_shape_is_helper_accepted(
    tmp_path: Path,
) -> None:
    # The argument-carrying launcher shapes: tmux joins a CLI and its
    # flags into the one command string it records for the pane, and the
    # helper's gate has to accept what those produce. tmuse starts the
    # helper as the pane command.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_argv_logger(bin_dir / "tmux", "tmux")
    log = tmp_path / "argv.log"
    env = os.environ.copy()
    env.update(
        {
            "ARGV_LOG": str(log),
            "PATH": f"{bin_dir}:{env['PATH']}",
        },
    )

    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            "tmux new tmux-agent-session-namer muse-run --yolo",
        ],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    launched = [call.split("\t") for call in log.read_text().splitlines()]
    assert [argv[1] for argv in launched] == ["new"]
    assert {
        os.path.basename(argv[2]) for argv in launched
    } <= accepted_start_commands()


def test_pi_extension_routes_session_naming_through_the_helper() -> None:
    text = PI_EXTENSION.read_text()

    assert '"pi"' in text
    assert "tmux-agent-session-namer/tmux-agent-session-namer" in text
    assert "session_start" in text
    assert "session_info_changed" in text


def test_opencode_plugin_routes_session_naming_through_the_helper() -> None:
    text = OPENCODE_PLUGIN.read_text()

    assert '"opencode"' in text
    assert "tmux-agent-session-namer/tmux-agent-session-namer" in text
    assert "session.created" in text
    assert "session.updated" in text
    # Neither the placeholder timestamp title nor a subagent's session
    # may move the tmux session's name.
    assert "New session - " in text
    assert "parentID" in text


def write_muse_name_db(
    path: Path,
    claims: list[tuple[str, str, str]],
) -> Path:
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            "CREATE TABLE session_name_claims ("
            "normalized_name TEXT, session_id TEXT, kind TEXT)"
        )
        connection.executemany(
            "INSERT INTO session_name_claims VALUES (?, ?, ?)",
            claims,
        )
        connection.commit()
    finally:
        connection.close()
    return path


def write_muse_session_log(
    path: Path, session_id: str, pane: str, socket: str
) -> Path:
    """Forge a Muse session log naming the pane it runs on.

    Real logs open with a route_facts record carrying the tmux pane
    and socket, which is what the watcher resolves sessions through.
    """
    day = path / "2026" / "09" / "23" / session_id
    day.mkdir(parents=True)
    record = {
        "kind": "route_facts",
        "record": {"tmux_pane": pane, "tmux_socket_path": socket},
    }
    (day / "session.jsonl").write_text(json.dumps(record) + "\n")
    return path


def muse_pane_environment(
    tmp_path: Path,
    sessions: Path,
    claims: list[tuple[str, str, str]],
    session_name: str | None = None,
) -> dict[str, str]:
    db = write_muse_name_db(tmp_path / "session-names.db", claims)
    env = {
        "MUSE_SESSION_NAME_DB": str(db),
        "FAKE_TMUX_START": "tmux-agent-session-namer muse-run",
        "FAKE_TMUX_PANES": "%0",
        "MUSE_SESSIONS_DIR": str(sessions),
    }
    if session_name is not None:
        env["FAKE_TMUX_SESSION_NAME"] = session_name
    return env


def write_muse_stub(bin_dir: Path, body: str) -> None:
    """Stand in for the muse CLI the supervisor runs as its child."""
    muse = bin_dir / "muse"
    muse.write_text(f"#!/bin/sh\n{body}\n")
    muse.chmod(0o755)


def test_muse_plugin_registers_no_tool_interposition() -> None:
    # Naming is the supervisor's job now: the bundle must not
    # interpose on tool calls or prompt the model to rename.
    config = json.loads(MUSE_PLUGIN_MANIFEST.read_text())

    assert config["name"] == "tmux-namer"
    assert config["capabilities"]["hooks"] == []
    assert config["capabilities"]["skills"] == []


def _watch_socket_for_tests() -> str:
    return os.path.realpath("/tmp/tmux")


def test_muse_run_renames_an_unreported_session(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(
            tmp_path,
            sessions,
            [("tmuse", "session-1", "canonical")],
            session_name="muse00-tmuse",
        ),
    )

    assert result.returncode == 0
    assert (
        "rename-session -t %0 muse00-tmuse"
        in fake_tmux[1].read_text().splitlines()
    )


def test_muse_run_matches_real_route_facts_shape(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # Real session logs carry one compact route_facts record near the
    # head with bare quotes, e.g.
    # "payload":{"kind":"route_facts","record":{...,
    # "tmux_pane":"$67:@74.%74",
    # "tmux_socket_path":"/private/tmp/tmux-501/default",...}}.
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "09" / "23" / "session-9"
    day.mkdir(parents=True)
    record = {
        "schema_version": 1,
        "payload_type": "runtime.session.route_facts",
        "payload": {
            "kind": "route_facts",
            "record": {
                "tmux_pane": "$9:@1.%0",
                "tmux_socket_path": _watch_socket_for_tests(),
            },
        },
    }
    (day / "session.jsonl").write_text(
        json.dumps(record, separators=(",", ":"))
    )
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(
            tmp_path,
            sessions,
            [("tmuse", "session-9", "canonical")],
            session_name="muse00-tmuse",
        ),
    )

    assert result.returncode == 0
    assert (
        "rename-session -t %0 muse00-tmuse"
        in fake_tmux[1].read_text().splitlines()
    )


def test_muse_run_does_not_mix_records_across_lines(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # One line names this pane on another socket, another names another
    # pane on this socket: neither line maps this pane here, so per-line
    # matching stays silent where whole-chunk matching would rename.
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "09" / "23" / "mixed"
    day.mkdir(parents=True)
    lines = [
        {
            "payload": {
                "kind": "route_facts",
                "record": {
                    "tmux_pane": "$9:@1.%0",
                    "tmux_socket_path": "/tmp/other-tmux",
                },
            },
        },
        {
            "payload": {
                "kind": "route_facts",
                "record": {
                    "tmux_pane": "$9:@1.%9",
                    "tmux_socket_path": _watch_socket_for_tests(),
                },
            },
        },
    ]
    (day / "session.jsonl").write_text(
        "\n".join(json.dumps(line, separators=(",", ":")) for line in lines)
    )
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(
            tmp_path,
            sessions,
            [("thispane", "mixed", "canonical")],
        ),
    )

    assert result.returncode == 0
    assert "rename-session" not in fake_tmux[1].read_text()


def test_muse_run_matches_an_unresolved_socket_spelling(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # One side may spell /tmp where the other spells /private/tmp; the
    # socket matches in either spelling. On systems where /tmp is real
    # both spellings coincide and the test is vacuous but still passes.
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "09" / "23" / "session-9"
    day.mkdir(parents=True)
    record = {
        "payload": {
            "kind": "route_facts",
            "record": {
                "tmux_pane": "$9:@1.%0",
                "tmux_socket_path": "/tmp/tmux",
            },
        },
    }
    (day / "session.jsonl").write_text(
        json.dumps(record, separators=(",", ":"))
    )
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(
            tmp_path,
            sessions,
            [("tmuse", "session-9", "canonical")],
            session_name="muse00-tmuse",
        ),
    )

    assert result.returncode == 0
    assert (
        "rename-session -t %0 muse00-tmuse"
        in fake_tmux[1].read_text().splitlines()
    )


def test_muse_run_without_tmux_still_supervises(
    fake_tmux: tuple[Path, Path],
) -> None:
    write_muse_stub(fake_tmux[0], "exit 0")
    result = run_helper(fake_tmux, "muse-run", in_tmux=False)

    assert result.returncode == 0
    assert not fake_tmux[1].exists()


def test_muse_run_verifies_a_truncated_long_name(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # tmux only ever sees the first 30 chars, so the read-back must
    # compare against the truncated form: comparing the full name
    # would re-issue the rename on every pass forever.
    issued = "muse00-" + "a" * 23
    assert len(issued) == 30
    write_muse_stub(fake_tmux[0], "sleep 4")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    env = muse_pane_environment(
        tmp_path,
        sessions,
        [("a" * 60, "session-1", "canonical")],
        session_name=issued,
    )
    result = run_helper(fake_tmux, "muse-run", extra_env=env)

    assert result.returncode == 0
    renames = [
        line
        for line in fake_tmux[1].read_text().splitlines()
        if line.startswith("rename-session")
    ]
    assert renames == [f"rename-session -t %0 {issued}"]


def test_muse_run_waits_for_its_child(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    env = muse_pane_environment(
        tmp_path,
        sessions,
        [("tmuse", "session-1", "canonical")],
        session_name="muse00-tmuse",
    )
    start = time.monotonic()
    result = run_helper(fake_tmux, "muse-run", extra_env=env)
    elapsed = time.monotonic() - start

    assert result.returncode == 0
    assert elapsed >= 1.5
    assert (
        "rename-session -t %0 muse00-tmuse"
        in fake_tmux[1].read_text().splitlines()
    )


def test_muse_run_propagates_its_child_status(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "exit 3")
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(tmp_path, tmp_path / "empty", []),
    )

    assert result.returncode == 3
    assert "rename-session" not in fake_tmux[1].read_text()


def test_muse_run_is_silent_without_a_claim(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "nobody",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(tmp_path, sessions, []),
    )

    assert result.returncode == 0
    lines = fake_tmux[1].read_text().splitlines()
    assert "list-panes -a -F #{pane_id}" in lines
    assert "rename-session" not in fake_tmux[1].read_text()


def test_muse_run_prefers_the_newest_session_for_a_pane(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "sleep 2")
    root = tmp_path / "sessions"
    old = write_muse_session_log(
        root, "old-session", "$9:@1.%0", _watch_socket_for_tests()
    )
    new = write_muse_session_log(
        root, "new-session", "$9:@1.%0", _watch_socket_for_tests()
    )
    os.utime(old / "2026" / "09" / "23" / "old-session", (1_000_000_000,) * 2)
    os.utime(new / "2026" / "09" / "23" / "new-session", (2_000_000_000,) * 2)
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env=muse_pane_environment(
            tmp_path,
            root,
            [
                ("oldname", "old-session", "canonical"),
                ("newname", "new-session", "canonical"),
            ],
            session_name="muse00-newname",
        ),
    )

    assert result.returncode == 0
    assert (
        "rename-session -t %0 muse00-newname"
        in fake_tmux[1].read_text().splitlines()
    )


def test_muse_run_ignores_an_unknown_pane(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    env = {
        **muse_pane_environment(
            tmp_path,
            sessions,
            [("tmuse", "session-1", "canonical")],
        ),
        "FAKE_TMUX_PANES": "%1",
    }
    result = run_helper(fake_tmux, "muse-run", extra_env=env)

    assert result.returncode == 0
    lines = fake_tmux[1].read_text().splitlines()
    assert "list-panes -a -F #{pane_id}" in lines
    assert "rename-session" not in fake_tmux[1].read_text()


def test_muse_run_reports_a_missing_muse(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # Hide everything but the shebang's uv, so the helper itself starts
    # and its own OSError path answers instead of the real muse.
    uv_only = tmp_path / "uvbin"
    uv_only.mkdir()
    uv = shutil.which("uv") or "/usr/bin/uv"
    (uv_only / "uv").symlink_to(Path(uv).resolve())
    result = run_helper(
        fake_tmux,
        "muse-run",
        extra_env={
            **muse_pane_environment(tmp_path, tmp_path / "empty", []),
            "PATH": str(uv_only),
        },
    )

    assert result.returncode == 1
    assert "cannot start muse" in result.stderr


def test_muse_run_does_not_record_a_refused_rename(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    write_muse_stub(fake_tmux[0], "sleep 2")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    env = {
        **muse_pane_environment(
            tmp_path,
            sessions,
            [("tmuse", "session-1", "canonical")],
        ),
        "FAKE_TMUX_OWNER": "claude",
    }
    result = run_helper(fake_tmux, "muse-run", extra_env=env)

    assert result.returncode == 0
    lines = fake_tmux[1].read_text().splitlines()
    assert "list-panes -a -F #{pane_id}" in lines
    assert "rename-session" not in fake_tmux[1].read_text()


def test_muse_run_retries_an_unverified_rename(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # The rename goes out but tmux never applies it: the read-back
    # still shows the old name, so every pass re-issues the rename
    # instead of remembering and going quiet.
    write_muse_stub(fake_tmux[0], "sleep 4")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    env = muse_pane_environment(
        tmp_path,
        sessions,
        [("tmuse", "session-1", "canonical")],
        session_name="stale-name",
    )
    result = run_helper(fake_tmux, "muse-run", extra_env=env)

    assert result.returncode == 0
    renames = [
        line
        for line in fake_tmux[1].read_text().splitlines()
        if line.startswith("rename-session")
    ]
    assert len(renames) >= 2
    assert set(renames) == {"rename-session -t %0 muse00-tmuse"}


def test_muse_run_renames_once_per_name(
    fake_tmux: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    # Several passes run while the child sleeps, but the in-memory
    # record keeps the rename to exactly one issue.
    write_muse_stub(fake_tmux[0], "sleep 4")
    sessions = write_muse_session_log(
        tmp_path / "sessions",
        "session-1",
        "$9:@1.%0",
        _watch_socket_for_tests(),
    )
    env = muse_pane_environment(
        tmp_path,
        sessions,
        [("tmuse", "session-1", "canonical")],
        session_name="muse00-tmuse",
    )
    result = run_helper(fake_tmux, "muse-run", extra_env=env)

    assert result.returncode == 0
    renames = [
        line
        for line in fake_tmux[1].read_text().splitlines()
        if line.startswith("rename-session")
    ]
    assert renames == ["rename-session -t %0 muse00-tmuse"]


def test_muse_run_renames_on_a_live_server(
    real_tmux_server: tuple[str, str],
    tmp_path: Path,
) -> None:
    real_tmux, server = real_tmux_server
    bin_dir = tmp_path / "livebin"
    bin_dir.mkdir()
    agent_stub(bin_dir, "muse")
    db = write_muse_name_db(
        tmp_path / "live-names.db",
        [("liveclaim", "live-session", "canonical")],
    )
    sessions = tmp_path / "live-sessions"
    sessions.mkdir(parents=True)
    pane_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MUSE_SESSIONS_DIR": str(sessions),
        "MUSE_SESSION_NAME_DB": str(db),
    }
    subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "new-session",
            "-d",
            "-s",
            "live",
            *(
                flag
                for key, value in pane_env.items()
                for flag in ("-e", f"{key}={value}")
            ),
            str(HELPER),
            "muse-run",
        ],
        check=True,
    )
    details = subprocess.run(
        [
            real_tmux,
            "-L",
            server,
            "display-message",
            "-p",
            "-t",
            "live",
            "#{socket_path},#{pane_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    socket_path, pane_id = details.split(",")
    write_muse_session_log(
        sessions, "live-session", f"$9:@1.{pane_id}", socket_path
    )

    wait_for_session_name(real_tmux_server, pane_id, "muse00-liveclaim")
