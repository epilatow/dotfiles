from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING
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
    show-options)
        printf '%s' "${FAKE_TMUX_CURRENT_NUM-}"
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
    else:
        env.pop("TMUX", None)
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


def create_tmux_session(
    real_tmux_server: tuple[str, str],
    name: str,
) -> dict[str, str]:
    real_tmux, server = real_tmux_server
    subprocess.run(
        [real_tmux, "-L", server, "new-session", "-d", "-s", name],
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
    return {
        "TMUX": f"{socket_path},{pid},{session_id.removeprefix('$')}",
        "TMUX_PANE": pane_id,
    }


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
    path.write_text(
        f"""#!/bin/sh
printf '%s' '{label}' >> "$ARGV_LOG"
for arg in "$@"; do
    printf '\\t%s' "$arg" >> "$ARGV_LOG"
done
printf '\\n' >> "$ARGV_LOG"
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


def test_crony_runs_one_shared_remote_control_app_server() -> None:
    config = tomllib.loads(CRONY_CONFIG.read_text())

    assert config["job"]["codex-remote-control"] == {
        "command": ("codex app-server --remote-control --listen unix://"),
        "gate": "command -v codex",
        "env": {"PATH": "$PATH:$HOME/.local/bin"},
        "daemon": True,
        "uuid": "4c392a33-485b-4a2a-abd6-4d029d151769",
    }
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
    assert not fake_tmux[1].exists()


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
    assert not fake_tmux[1].exists()


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
    assert not fake_tmux[1].exists()


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
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @codex_num",
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
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @codex_num",
        "list-sessions -F #{@codex_num}",
        "set-option @codex_num 01",
        "wait-for -U tmux-agent-session-namer-slots",
        "rename-session codex01-Suggest-cat-names-plea",
    ]


def test_codex_stop_treats_title_as_literal_tmux_format(
    fake_tmux: tuple[Path, Path],
    real_tmux_server: tuple[str, str],
) -> None:
    tmux_environment = create_tmux_session(real_tmux_server, "literal")
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
    tmux_environment = create_tmux_session(real_tmux_server, "literal")
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
        create_tmux_session(real_tmux_server, f"concurrent-{number}")
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
    assert not fake_tmux[1].exists()
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
        "wait-for -L tmux-agent-session-namer-slots",
        "show-options -qv @codex_num",
        "list-sessions -F #{@codex_num}",
        "wait-for -U tmux-agent-session-namer-slots",
    ]


def test_claude_reuses_slot_and_strips_leading_status(
    tmp_path: Path,
    fake_tmux: tuple[Path, Path],
) -> None:
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
    result = run_helper(
        fake_tmux,
        extra_env={"FAKE_TMUX_CURRENT_NUM": "07", "HOME": str(home)},
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


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("other",),
        ("codex;bad",),
        ("codex-hook", "--require-codex-thread-title"),
        ("claude", "--strip-leading-status"),
    ],
)
def test_rejects_unknown_or_extra_subcommand(
    fake_tmux: tuple[Path, Path],
    args: tuple[str, ...],
) -> None:
    result = run_helper(fake_tmux, *args)

    assert result.returncode == 2
    assert not fake_tmux[1].exists()
