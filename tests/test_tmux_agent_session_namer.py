from __future__ import annotations

import ast
import json
import os
import shutil
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
MUSE_SKILL = (
    REPO_ROOT / "files" / "muse" / "skills" / "tmux-namer" / "SKILL.md"
)
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
        printf '%s' "${FAKE_TMUX_START-claude}"
        ;;
    show-options)
        case "$3" in
            @agent_namer)
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
esac
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
    log = tmp_path / "argv.log"
    env = os.environ.copy()
    env.update(
        {
            "ARGV_LOG": str(log),
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
        },
    )

    # tcodex is a function and runs as written. tclaude is an alias, and
    # a non-interactive bash expands one only under expand_aliases and
    # only on input parsed after the alias exists, hence the eval. A sh
    # without either lands on the "new", "new" assertion below rather
    # than passing quietly.
    result = subprocess.run(
        [
            "/bin/sh",
            "-c",
            (
                'shopt -s expand_aliases 2>/dev/null; . "$1"; '
                "eval tclaude; tcodex"
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
    assert [argv[1] for argv in launched] == ["new", "new"]
    launched_names = {os.path.basename(argv[2]) for argv in launched}
    assert launched_names <= accepted_start_commands()
    # `muse` is launched by the tmuse alias, which is environment state
    # outside this file; test_tmuse_launcher_shape_is_helper_accepted
    # pins the shapes it produces. Once that alias is committed here,
    # eval it above and restore the plain equality this replaced.
    assert accepted_start_commands() - launched_names == {"muse"}


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
                    "tmux naming disabled: claude already names this tmux "
                    "session."
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
        ("muse", True),
        ("muse --yolo", True),
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
    ],
)
def test_rejects_unknown_or_extra_subcommand(
    fake_tmux: tuple[Path, Path],
    args: tuple[str, ...],
) -> None:
    result = run_helper(fake_tmux, *args)

    assert result.returncode == 2
    assert not fake_tmux[1].exists()


def test_muse_renames_with_allocated_slot(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "muse",
        "tmuse",
        extra_env={
            "FAKE_TMUX_START": "muse --yolo",
            "FAKE_TMUX_USED_NUMS": "00\n",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        "show-options -qv @muse_num",
        "list-sessions -F #{@muse_num}",
        "set-option @muse_num 01",
        "set-option @agent_namer muse",
        "wait-for -U tmux-agent-session-namer-slots",
        "rename-session muse01-tmuse",
    ]


def test_muse_reuses_its_slot_on_rename(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "muse",
        "Second Name",
        extra_env={
            "FAKE_TMUX_START": "muse",
            "FAKE_TMUX_CURRENT_NUM": "04",
            "FAKE_TMUX_OWNER": "muse",
        },
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == [
        PANE_START_COMMAND,
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @agent_namer",
        "show-options -qv @muse_num",
        "wait-for -U tmux-agent-session-namer-slots",
        "rename-session muse04-Second-Name",
    ]


def test_muse_leaves_a_session_claude_names_alone(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "muse",
        "tmuse",
        extra_env={
            "FAKE_TMUX_START": "muse",
            "FAKE_TMUX_OWNER": "claude",
        },
    )

    assert result.returncode == 0
    assert fake_tmux[1].read_text().splitlines() == REFUSED_SLOT_COMMANDS


def test_muse_skips_a_shell_pane(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "muse",
        "tmuse",
        extra_env={"FAKE_TMUX_START": ""},
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert fake_tmux[1].read_text().splitlines() == [PANE_START_COMMAND]


def test_muse_ignores_a_blank_session_name(
    fake_tmux: tuple[Path, Path],
) -> None:
    result = run_helper(
        fake_tmux,
        "muse",
        "   ",
        extra_env={"FAKE_TMUX_START": "muse"},
    )

    assert result.returncode == 0
    assert not any(
        command.startswith("rename-session")
        for command in fake_tmux[1].read_text().splitlines()
    )


def test_tmuse_launcher_shape_is_helper_accepted(
    tmp_path: Path,
) -> None:
    # The tmuse aliases live as uncommitted environment state, so this
    # pins the contract on the shapes they produce rather than on the
    # alias definitions themselves: `tmux new` with the muse CLI.
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
        ["/bin/sh", "-c", "tmux new muse; tmux new muse --yolo"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )

    assert result.returncode == 0
    launched = [call.split("\t") for call in log.read_text().splitlines()]
    assert [argv[1] for argv in launched] == ["new", "new"]
    assert {
        os.path.basename(argv[2]) for argv in launched
    } <= accepted_start_commands()


def test_muse_skill_routes_session_naming_through_the_helper() -> None:
    text = MUSE_SKILL.read_text()

    assert text.startswith("---\nname: tmux-namer\n")
    assert "description: " in text.split("---\n")[1]
    assert (
        '"$HOME/.local/libexec/tmux-agent-session-namer/'
        'tmux-agent-session-namer" muse' in text
    )
    assert "renamed" in text
