from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections import deque
from pathlib import Path
from types import TracebackType
from typing import Self, cast
from unittest.mock import call, patch

import pytest
from websockets.exceptions import WebSocketException

REPO_ROOT = Path(__file__).parents[1]
LIBEXEC_DIR = (
    REPO_ROOT / "files" / "local" / "libexec" / "codex-archive-inactive"
)
COMMAND = LIBEXEC_DIR / "codex_archive_inactive.py"
sys.path.insert(0, str(LIBEXEC_DIR))

import codex_archive_inactive as archive  # noqa: E402

type JsonObject = dict[str, object]


def _thread(
    thread_id: str,
    *,
    status: str = "notLoaded",
    updated_at: int = 1_000,
    name: str | None = None,
    parent_thread_id: str | None = None,
    path: str | None = None,
) -> JsonObject:
    return {
        "id": thread_id,
        "name": name,
        "preview": f"preview {thread_id}",
        "updatedAt": updated_at,
        "status": {"type": status},
        "path": path if path is not None else f"/sessions/{thread_id}.jsonl",
        "parentThreadId": parent_thread_id,
    }


class FakeRpcClient:
    def __init__(
        self,
        responses: dict[str, list[JsonObject]],
    ) -> None:
        self.responses = {
            method: deque(method_responses)
            for method, method_responses in responses.items()
        }
        self.requests: list[tuple[str, JsonObject]] = []
        self.notifications: list[tuple[str, JsonObject]] = []

    async def notify(self, method: str, params: JsonObject) -> None:
        self.notifications.append((method, params))

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        self.requests.append((method, params))
        try:
            return self.responses[method].popleft()
        except (KeyError, IndexError) as exc:
            raise AssertionError(f"unexpected request: {method}") from exc


class FakeConnection:
    def __init__(self, incoming: list[str | bytes]) -> None:
        self.incoming = deque(incoming)
        self.sent: list[JsonObject] = []

    async def send(self, message: str) -> None:
        parsed: object = json.loads(message)
        self.sent.append(cast(JsonObject, parsed))

    async def recv(self) -> str | bytes:
        return self.incoming.popleft()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


class NeverRespondConnection(FakeConnection):
    async def recv(self) -> str | bytes:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class DisconnectingConnection(FakeConnection):
    async def recv(self) -> str | bytes:
        raise WebSocketException("daemon replaced")


def test_command_is_python_314_uv_script() -> None:
    assert COMMAND.read_text().splitlines()[:5] == [
        "#!/usr/bin/env -S uv run --script",
        "# /// script",
        '# requires-python = ">=3.14"',
        '# dependencies = ["websockets>=16,<17"]',
        "# ///",
    ]


def test_help_describes_scheduled_cleanup_options() -> None:
    result = subprocess.run(
        [str(COMMAND), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--apply" in result.stdout
    assert "-v" in result.stdout
    assert "--verbose" in result.stdout
    assert "--dry-run" not in result.stdout
    assert "--minimum-age SECONDS" in result.stdout
    assert "--socket" not in result.stdout
    assert "--sessions-dir" not in result.stdout


def test_apply_must_be_explicit() -> None:
    parser = archive.build_parser()

    assert parser.parse_args([]).apply is False
    assert parser.parse_args(["--apply"]).apply is True


def test_json_rpc_ignores_notifications_and_uses_matching_response() -> None:
    connection = FakeConnection(
        [
            json.dumps({"method": "thread/status/changed", "params": {}}),
            json.dumps({"id": 99, "result": {"ignored": True}}),
            json.dumps({"id": 1, "result": {"data": []}}),
        ]
    )
    client = archive.JsonRpcClient(connection)

    result = asyncio.run(client.request("thread/list", {"limit": 1}))

    assert result == {"data": []}
    assert connection.sent == [
        {
            "id": 1,
            "method": "thread/list",
            "params": {"limit": 1},
        }
    ]


def test_json_rpc_reports_server_errors() -> None:
    connection = FakeConnection(
        [
            json.dumps(
                {
                    "id": 1,
                    "error": {"code": -1, "message": "archive refused"},
                }
            )
        ]
    )
    client = archive.JsonRpcClient(connection)

    with pytest.raises(archive.ArchiveError, match="archive refused"):
        asyncio.run(client.request("thread/archive", {"threadId": "a"}))


def test_json_rpc_reports_server_overload_as_transient() -> None:
    connection = FakeConnection(
        [
            json.dumps(
                {
                    "id": 1,
                    "error": {
                        "code": -32001,
                        "message": "Server overloaded; retry later.",
                    },
                }
            )
        ]
    )
    client = archive.JsonRpcClient(connection)

    with pytest.raises(
        archive.TransientRpcError,
        match="Server overloaded",
    ):
        asyncio.run(client.request("thread/list", {}))


def test_json_rpc_reports_timeout_as_transient() -> None:
    client = archive.JsonRpcClient(
        NeverRespondConnection([]),
        request_timeout=0,
    )

    with pytest.raises(archive.TransientRpcError, match="timed out"):
        asyncio.run(client.request("thread/list", {}))


def test_json_rpc_rejects_binary_messages() -> None:
    client = archive.JsonRpcClient(FakeConnection([b"binary"]))

    with pytest.raises(archive.ArchiveError, match="binary message"):
        asyncio.run(client.request("thread/list", {}))


def test_initialize_performs_request_then_notification() -> None:
    client = FakeRpcClient({"initialize": [{}]})

    asyncio.run(archive.initialize(client))

    assert client.requests[0][0] == "initialize"
    assert client.notifications == [("initialized", {})]


def test_list_threads_paginates_interactive_sources() -> None:
    client = FakeRpcClient(
        {
            "thread/list": [
                {
                    "data": [_thread("one")],
                    "nextCursor": "page-two",
                },
                {
                    "data": [_thread("two")],
                    "nextCursor": None,
                },
            ]
        }
    )

    threads = asyncio.run(archive.list_threads(client))

    assert [thread.thread_id for thread in threads] == ["one", "two"]
    assert client.requests == [
        (
            "thread/list",
            {
                "archived": False,
                "limit": archive.PAGE_SIZE,
                "sourceKinds": list(archive.INTERACTIVE_SOURCE_KINDS),
            },
        ),
        (
            "thread/list",
            {
                "archived": False,
                "limit": archive.PAGE_SIZE,
                "sourceKinds": list(archive.INTERACTIVE_SOURCE_KINDS),
                "cursor": "page-two",
            },
        ),
    ]


def test_list_threads_rejects_repeated_cursor() -> None:
    client = FakeRpcClient(
        {
            "thread/list": [
                {"data": [], "nextCursor": "repeat"},
                {"data": [], "nextCursor": "repeat"},
            ]
        }
    )

    with pytest.raises(archive.ArchiveError, match="repeated"):
        asyncio.run(archive.list_threads(client))


def test_untitled_thread_uses_a_compact_preview() -> None:
    value = _thread("thread-id")
    value["preview"] = "This is a very long first message. " * 5

    thread = archive._thread_from_json(value)

    assert thread.label.startswith("Untitled: This is a very long")
    assert thread.label.endswith("...")
    assert len(thread.label) <= archive.MAX_LABEL_LENGTH


def test_cleanup_archives_only_old_unloaded_sessions() -> None:
    listed = [
        _thread("old", updated_at=1_000, name="Old session"),
        _thread("recent", updated_at=9_500),
        _thread("idle", status="idle", updated_at=1_000),
        _thread("active", status="active", updated_at=1_000),
        _thread(
            "system-error",
            status="systemError",
            updated_at=1_000,
        ),
    ]
    client = FakeRpcClient(
        {
            "thread/list": [
                {
                    "data": listed,
                    "nextCursor": None,
                },
                {
                    "data": listed,
                    "nextCursor": None,
                },
            ],
            "thread/read": [
                {
                    "thread": _thread(
                        "old",
                        updated_at=1_000,
                        name="Old session",
                    )
                }
            ],
            "thread/archive": [{}],
        }
    )

    result = asyncio.run(
        archive.cleanup_sessions(
            client,
            open_paths=set(),
            sessions_dir=Path("/sessions"),
            dry_run=False,
            minimum_age=1_000,
            now=10_000,
        )
    )

    assert result.archived == 1
    assert [thread.thread_id for thread in result.selected] == ["old"]
    assert [method for method, _ in client.requests] == [
        "thread/list",
        "thread/list",
        "thread/read",
        "thread/archive",
    ]


def test_cleanup_rechecks_status_before_archiving() -> None:
    client = FakeRpcClient(
        {
            "thread/list": [
                {
                    "data": [_thread("changed", updated_at=1_000)],
                    "nextCursor": None,
                },
                {
                    "data": [_thread("changed", updated_at=1_000)],
                    "nextCursor": None,
                },
            ],
            "thread/read": [
                {"thread": _thread("changed", status="idle", updated_at=1_000)}
            ],
        }
    )

    result = asyncio.run(
        archive.cleanup_sessions(
            client,
            open_paths=set(),
            sessions_dir=Path("/sessions"),
            dry_run=False,
            minimum_age=1_000,
            now=10_000,
        )
    )

    assert result.archived == 0
    assert result.changed_before_archive == 1
    assert not result.selected
    assert "thread/archive" not in [method for method, _ in client.requests]


def test_cleanup_dry_run_does_not_archive() -> None:
    client = FakeRpcClient(
        {
            "thread/list": [
                {
                    "data": [_thread("old", updated_at=1_000)],
                    "nextCursor": None,
                },
                {
                    "data": [_thread("old", updated_at=1_000)],
                    "nextCursor": None,
                },
            ],
            "thread/read": [{"thread": _thread("old", updated_at=1_000)}],
        }
    )

    result = asyncio.run(
        archive.cleanup_sessions(
            client,
            open_paths=set(),
            sessions_dir=Path("/sessions"),
            dry_run=True,
            minimum_age=0,
            now=10_000,
        )
    )

    assert result.archived == 0
    assert [thread.thread_id for thread in result.selected] == ["old"]
    assert "thread/archive" not in [method for method, _ in client.requests]


def test_cleanup_skips_family_with_open_root() -> None:
    root = _thread("root", updated_at=1_000)
    client = FakeRpcClient(
        {
            "thread/list": [
                {"data": [root], "nextCursor": None},
                {"data": [root], "nextCursor": None},
            ]
        }
    )

    result = asyncio.run(
        archive.cleanup_sessions(
            client,
            open_paths={Path("/sessions/root.jsonl")},
            sessions_dir=Path("/sessions"),
            dry_run=False,
            minimum_age=1_000,
            now=10_000,
        )
    )

    assert result.archived == 0
    assert result.open_families == 1
    assert result.blocked_families == 1
    assert [thread.thread_id for thread in result.kept] == ["root"]
    assert "thread/read" not in [method for method, _ in client.requests]


def test_cleanup_skips_family_with_open_descendant() -> None:
    root = _thread("root", updated_at=1_000)
    child = _thread(
        "child",
        updated_at=1_000,
        parent_thread_id="root",
    )
    client = FakeRpcClient(
        {
            "thread/list": [
                {"data": [root], "nextCursor": None},
                {"data": [root, child], "nextCursor": None},
            ]
        }
    )

    result = asyncio.run(
        archive.cleanup_sessions(
            client,
            open_paths={Path("/sessions/child.jsonl")},
            sessions_dir=Path("/sessions"),
            dry_run=False,
            minimum_age=1_000,
            now=10_000,
        )
    )

    assert result.archived == 0
    assert result.open_families == 1
    assert result.blocked_families == 1
    assert [thread.thread_id for thread in result.kept] == ["root"]
    assert "thread/read" not in [method for method, _ in client.requests]


def test_cleanup_skips_family_with_recent_descendant() -> None:
    root = _thread("root", updated_at=1_000)
    child = _thread(
        "child",
        updated_at=9_500,
        parent_thread_id="root",
    )
    client = FakeRpcClient(
        {
            "thread/list": [
                {"data": [root], "nextCursor": None},
                {"data": [root, child], "nextCursor": None},
            ]
        }
    )

    result = asyncio.run(
        archive.cleanup_sessions(
            client,
            open_paths=set(),
            sessions_dir=Path("/sessions"),
            dry_run=False,
            minimum_age=1_000,
            now=10_000,
        )
    )

    assert result.archived == 0
    assert result.blocked_families == 1
    assert "thread/read" not in [method for method, _ in client.requests]


def test_open_rollout_paths_parses_lsof_names(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.jsonl"
    second = tmp_path / "nested" / "second.jsonl"
    second.parent.mkdir()
    first.touch()
    second.touch()
    with patch(
        "subprocess.run",
        autospec=True,
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=f"p123\nf4\nn{first}\nf5\nn{second}\n",
            stderr="",
        ),
    ) as run:
        assert archive.open_rollout_paths(tmp_path) == {first, second}
    assert run.call_count == 1
    command = run.call_args.args[0]
    assert "+D" not in command
    assert command[-2:] == [str(first), str(second)]


def test_open_rollout_paths_accepts_lsof_no_matches(
    tmp_path: Path,
) -> None:
    (tmp_path / "closed.jsonl").touch()
    with patch(
        "subprocess.run",
        autospec=True,
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="",
        ),
    ):
        assert archive.open_rollout_paths(tmp_path) == set()


def test_open_rollout_paths_canonicalizes_symlinks(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(sessions_dir, target_is_directory=True)
    rollout = sessions_dir / "thread.jsonl"
    rollout.touch()
    with patch(
        "subprocess.run",
        autospec=True,
        return_value=subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=f"p123\nf4\nn{rollout}\n",
            stderr="",
        ),
    ):
        assert archive.open_rollout_paths(alias) == {rollout}


def test_open_rollout_paths_fails_on_unreadable_tree(
    tmp_path: Path,
) -> None:
    with (
        patch(
            "os.scandir",
            autospec=True,
            side_effect=PermissionError("permission denied"),
        ),
        pytest.raises(archive.ArchiveError, match="could not traverse"),
    ):
        archive.open_rollout_paths(tmp_path)


def test_open_rollout_paths_fails_closed(
    tmp_path: Path,
) -> None:
    (tmp_path / "thread.jsonl").touch()
    with (
        patch(
            "subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=2,
                stdout="",
                stderr="permission denied",
            ),
        ),
        pytest.raises(archive.ArchiveError, match="permission denied"),
    ):
        archive.open_rollout_paths(tmp_path)


def test_open_rollout_paths_retries_a_timeout(
    tmp_path: Path,
) -> None:
    rollout = tmp_path / "thread.jsonl"
    rollout.touch()
    with patch(
        "subprocess.run",
        autospec=True,
        side_effect=(
            subprocess.TimeoutExpired(cmd=["lsof"], timeout=15),
            subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=f"p123\nf4\nn{rollout}\n",
                stderr="",
            ),
        ),
    ) as run:
        assert archive.open_rollout_paths(tmp_path) == {rollout}

    assert [call.kwargs["timeout"] for call in run.call_args_list] == [
        15,
        120,
    ]


def test_open_rollout_paths_fails_after_retry_timeout(
    tmp_path: Path,
) -> None:
    (tmp_path / "thread.jsonl").touch()
    with (
        patch(
            "subprocess.run",
            autospec=True,
            side_effect=(
                subprocess.TimeoutExpired(cmd=["lsof"], timeout=15),
                subprocess.TimeoutExpired(cmd=["lsof"], timeout=120),
            ),
        ) as run,
        pytest.raises(archive.ArchiveError, match="timed out after 120"),
    ):
        archive.open_rollout_paths(tmp_path)

    assert run.call_count == 2


def test_ensure_app_server_starts_missing_default_socket(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "control.sock"
    with (
        patch.object(
            archive,
            "default_socket_path",
            autospec=True,
            return_value=socket_path,
        ),
        patch("shutil.which", autospec=True, return_value="/usr/bin/codex"),
        patch(
            "subprocess.run",
            autospec=True,
            return_value=subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"status":"started"}',
                stderr="",
            ),
        ) as run,
    ):
        archive.ensure_app_server(socket_path)

    assert run.call_args.args[0] == [
        "/usr/bin/codex",
        "app-server",
        "daemon",
        "start",
    ]


def test_ensure_app_server_rejects_missing_custom_socket(
    tmp_path: Path,
) -> None:
    with (
        patch.object(
            archive,
            "default_socket_path",
            autospec=True,
            return_value=tmp_path / "default.sock",
        ),
        pytest.raises(archive.ArchiveError, match="socket does not exist"),
    ):
        archive.ensure_app_server(tmp_path / "custom.sock")


@pytest.mark.parametrize(
    "unavailable",
    [
        FakeConnection(
            [
                json.dumps({"id": 1, "result": {}}),
                json.dumps(
                    {
                        "id": 2,
                        "error": {
                            "code": -32001,
                            "message": "Server overloaded; retry later.",
                        },
                    }
                ),
            ]
        ),
        DisconnectingConnection([]),
    ],
    ids=("overloaded", "daemon-disconnected"),
)
def test_run_cleanup_reconnects_to_load_snapshot(
    tmp_path: Path,
    unavailable: FakeConnection,
) -> None:
    ready = FakeConnection(
        [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {"data": [], "nextCursor": None}}),
            json.dumps({"id": 3, "result": {"data": [], "nextCursor": None}}),
        ]
    )
    with (
        patch.object(
            archive,
            "unix_connect",
            autospec=True,
            side_effect=(unavailable, ready),
        ) as connect,
        patch.object(
            archive,
            "ensure_app_server",
            autospec=True,
        ) as ensure,
        patch.object(
            archive,
            "open_rollout_paths",
            autospec=True,
            return_value=set(),
        ) as open_paths,
        patch(
            "asyncio.sleep",
            autospec=True,
        ) as sleep,
    ):
        result = asyncio.run(
            archive.run_cleanup(
                socket_path=tmp_path / "control.sock",
                sessions_dir=tmp_path,
                dry_run=False,
                minimum_age=1_000,
                now=10_000,
                snapshot_retry_delays=(7,),
            )
        )

    assert result.archived == 0
    assert connect.call_count == 2
    assert ensure.call_count == 2
    open_paths.assert_called_once_with(tmp_path)
    sleep.assert_awaited_once_with(7)


def test_run_cleanup_does_not_retry_candidate_processing(
    tmp_path: Path,
) -> None:
    ready = FakeConnection(
        [
            json.dumps({"id": 1, "result": {}}),
            json.dumps({"id": 2, "result": {"data": [], "nextCursor": None}}),
            json.dumps({"id": 3, "result": {"data": [], "nextCursor": None}}),
        ]
    )
    with (
        patch.object(
            archive,
            "unix_connect",
            autospec=True,
            return_value=ready,
        ) as connect,
        patch.object(
            archive,
            "ensure_app_server",
            autospec=True,
        ),
        patch.object(
            archive,
            "open_rollout_paths",
            autospec=True,
            return_value=set(),
        ),
        patch.object(
            archive,
            "_cleanup_snapshot",
            autospec=True,
            side_effect=archive.TransientRpcError("connection replaced"),
        ),
        patch(
            "asyncio.sleep",
            autospec=True,
        ) as sleep,
        pytest.raises(archive.TransientRpcError, match="connection replaced"),
    ):
        asyncio.run(
            archive.run_cleanup(
                socket_path=tmp_path / "control.sock",
                sessions_dir=tmp_path,
                dry_run=False,
                minimum_age=1_000,
                now=10_000,
                snapshot_retry_delays=(0,),
            )
        )

    assert connect.call_count == 1
    sleep.assert_not_awaited()


def test_run_cleanup_stops_after_snapshot_retries(
    tmp_path: Path,
) -> None:
    unavailable = tuple(DisconnectingConnection([]) for _ in range(3))
    with (
        patch.object(
            archive,
            "unix_connect",
            autospec=True,
            side_effect=unavailable,
        ) as connect,
        patch.object(
            archive,
            "ensure_app_server",
            autospec=True,
        ) as ensure,
        patch.object(
            archive,
            "open_rollout_paths",
            autospec=True,
        ) as open_paths,
        patch(
            "asyncio.sleep",
            autospec=True,
        ) as sleep,
        pytest.raises(archive.ArchiveError, match="after 3 attempts"),
    ):
        asyncio.run(
            archive.run_cleanup(
                socket_path=tmp_path / "control.sock",
                sessions_dir=tmp_path,
                dry_run=False,
                minimum_age=1_000,
                now=10_000,
                snapshot_retry_delays=(1, 2),
            )
        )

    assert connect.call_count == 3
    assert ensure.call_count == 3
    assert sleep.await_args_list == [call(1), call(2)]
    open_paths.assert_not_called()


def test_print_result_is_quiet_for_noop(
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive._print_result(
        archive.CleanupResult(
            selected=(),
            kept=(),
            archived=0,
            open_families=0,
            changed_before_archive=0,
            blocked_families=0,
        ),
        dry_run=False,
        verbose=False,
    )

    assert capsys.readouterr().out == ""

    archive._print_result(
        archive.CleanupResult(
            selected=(),
            kept=(),
            archived=0,
            open_families=0,
            changed_before_archive=0,
            blocked_families=0,
        ),
        dry_run=False,
        verbose=True,
    )

    assert capsys.readouterr().out == (
        "archived 0 session(s); observed 0 open family(s); skipped 0 "
        "active/uncertain family(s) and 0 changed session(s)\n"
    )


def test_print_result_lists_dry_run_candidates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive._print_result(
        archive.CleanupResult(
            selected=(
                archive.Thread(
                    thread_id="thread-1",
                    label="Useful session",
                    updated_at=1_000,
                    status=archive.ThreadStatus.NOT_LOADED,
                    rollout_path=Path("/sessions/thread-1.jsonl"),
                    parent_thread_id=None,
                ),
            ),
            kept=(
                archive.Thread(
                    thread_id="thread-2",
                    label="Active session",
                    updated_at=2_000,
                    status=archive.ThreadStatus.NOT_LOADED,
                    rollout_path=Path("/sessions/thread-2.jsonl"),
                    parent_thread_id=None,
                ),
            ),
            archived=0,
            open_families=1,
            changed_before_archive=1,
            blocked_families=2,
        ),
        dry_run=True,
        verbose=False,
    )

    assert capsys.readouterr().out == (
        "keeping: Active session\n"
        "archiving: Useful session\n"
        "would archive 1 session(s); observed 1 open family(s); skipped 2 "
        "active/uncertain family(s) and 1 changed session(s)\n"
    )


def test_print_result_kept_noop_requires_verbose(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = archive.CleanupResult(
        selected=(),
        kept=(
            archive.Thread(
                thread_id="thread-2",
                label="Active session",
                updated_at=2_000,
                status=archive.ThreadStatus.NOT_LOADED,
                rollout_path=Path("/sessions/thread-2.jsonl"),
                parent_thread_id=None,
            ),
        ),
        archived=0,
        open_families=1,
        changed_before_archive=0,
        blocked_families=0,
    )

    archive._print_result(
        result,
        dry_run=False,
        verbose=False,
    )

    assert capsys.readouterr().out == ""

    archive._print_result(
        result,
        dry_run=False,
        verbose=True,
    )

    assert capsys.readouterr().out == (
        "keeping: Active session\n"
        "archived 0 session(s); observed 1 open family(s); skipped 0 "
        "active/uncertain family(s) and 0 changed session(s)\n"
    )


def test_minimum_age_must_be_nonnegative() -> None:
    parser = archive.build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--minimum-age", "-1"])

    assert exc_info.value.code == 2
