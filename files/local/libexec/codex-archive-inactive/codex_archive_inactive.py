#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["websockets>=16,<17"]
# ///
"""Find and optionally archive inactive Codex sessions."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, cast

from websockets.asyncio.client import unix_connect
from websockets.exceptions import WebSocketException

type JsonObject = dict[str, object]

DEFAULT_MINIMUM_AGE_SECONDS = 3600
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 15
SNAPSHOT_RETRY_DELAYS_SECONDS = (15, 30, 60)
LSOF_TIMEOUTS_SECONDS = (15, 120)
MAX_LABEL_LENGTH = 68
INTERACTIVE_SOURCE_KINDS = ("cli", "vscode")
ALL_SOURCE_KINDS = (
    *INTERACTIVE_SOURCE_KINDS,
    "exec",
    "appServer",
    "subAgent",
    "subAgentReview",
    "subAgentCompact",
    "subAgentThreadSpawn",
    "subAgentOther",
    "unknown",
)


class ArchiveError(RuntimeError):
    """A Codex session archive operation failed."""


class TransientRpcError(ArchiveError):
    """An app-server request can be retried on a fresh connection."""


class ThreadStatus(StrEnum):
    NOT_LOADED = "notLoaded"
    IDLE = "idle"
    ACTIVE = "active"
    SYSTEM_ERROR = "systemError"


@dataclass(frozen=True)
class Thread:
    thread_id: str
    label: str
    updated_at: int
    status: ThreadStatus
    rollout_path: Path | None
    parent_thread_id: str | None


@dataclass(frozen=True)
class CleanupResult:
    selected: tuple[Thread, ...]
    kept: tuple[Thread, ...]
    archived: int
    open_families: int
    changed_before_archive: int
    blocked_families: int


@dataclass(frozen=True)
class ThreadSnapshot:
    listed: tuple[Thread, ...]
    all_threads: tuple[Thread, ...]


class JsonConnection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...


class RpcClient(Protocol):
    async def notify(self, method: str, params: JsonObject) -> None: ...

    async def request(self, method: str, params: JsonObject) -> JsonObject: ...


class JsonRpcClient:
    def __init__(
        self,
        connection: JsonConnection,
        *,
        request_timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._connection = connection
        self._request_timeout = request_timeout
        self._next_id = 1

    async def notify(self, method: str, params: JsonObject) -> None:
        await self._connection.send(
            json.dumps({"method": method, "params": params})
        )

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        request_id = self._next_id
        self._next_id += 1
        await self._connection.send(
            json.dumps(
                {
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
        )

        try:
            async with asyncio.timeout(self._request_timeout):
                while True:
                    raw_message = await self._connection.recv()
                    if not isinstance(raw_message, str):
                        raise ArchiveError(
                            "app server returned a binary message"
                        )
                    try:
                        parsed: object = json.loads(raw_message)
                    except json.JSONDecodeError as exc:
                        raise ArchiveError(
                            f"app server returned invalid JSON: {exc}"
                        ) from exc
                    response = _as_object(parsed, "app-server response")
                    if response.get("id") != request_id:
                        continue
                    error = response.get("error")
                    if error is not None:
                        error_type = (
                            TransientRpcError
                            if _is_transient_rpc_error(error)
                            else ArchiveError
                        )
                        raise error_type(
                            f"{method} failed: {_format_rpc_error(error)}"
                        )
                    return _as_object(
                        response.get("result"),
                        f"{method} result",
                    )
        except TimeoutError as exc:
            raise TransientRpcError(
                f"{method} timed out after {self._request_timeout} seconds"
            ) from exc


def _as_object(value: object, context: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ArchiveError(f"{context} is not an object")
    if not all(isinstance(key, str) for key in value):
        raise ArchiveError(f"{context} has a non-string key")
    return cast(JsonObject, value)


def _format_rpc_error(value: object) -> str:
    try:
        error = _as_object(value, "JSON-RPC error")
    except ArchiveError:
        return repr(value)
    message = error.get("message")
    return message if isinstance(message, str) else repr(error)


def _is_transient_rpc_error(value: object) -> bool:
    try:
        error = _as_object(value, "JSON-RPC error")
    except ArchiveError:
        return False
    return error.get("code") == -32001


def _required_str(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArchiveError(f"{context} is not a non-empty string")
    return value


def _required_int(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiveError(f"{context} is not an integer")
    return value


def _optional_str(value: object, context: str) -> str | None:
    if value is None:
        return None
    return _required_str(value, context)


def _normalized_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ArchiveError(
            f"could not canonicalize path {path}: {exc}"
        ) from exc


def _compact_label(value: str) -> str:
    label = " ".join(value.split())
    if len(label) <= MAX_LABEL_LENGTH:
        return label
    return f"{label[: MAX_LABEL_LENGTH - 3].rstrip()}..."


def _thread_from_json(value: object) -> Thread:
    thread = _as_object(value, "thread")
    thread_id = _required_str(thread.get("id"), "thread.id")
    status_object = _as_object(thread.get("status"), "thread.status")
    status_value = _required_str(
        status_object.get("type"),
        "thread.status.type",
    )
    try:
        status = ThreadStatus(status_value)
    except ValueError as exc:
        raise ArchiveError(
            f"thread.status.type has unknown value {status_value!r}"
        ) from exc

    name = thread.get("name")
    preview = thread.get("preview")
    if isinstance(name, str) and name.strip():
        label = _compact_label(name)
    elif isinstance(preview, str) and preview.strip():
        label = _compact_label(f"Untitled: {preview}")
    else:
        label = thread_id
    path_value = _optional_str(thread.get("path"), "thread.path")

    return Thread(
        thread_id=thread_id,
        label=label,
        updated_at=_required_int(thread.get("updatedAt"), "thread.updatedAt"),
        status=status,
        rollout_path=(
            _normalized_path(Path(path_value))
            if path_value is not None
            else None
        ),
        parent_thread_id=_optional_str(
            thread.get("parentThreadId"),
            "thread.parentThreadId",
        ),
    )


async def initialize(client: RpcClient) -> None:
    await client.request(
        "initialize",
        {
            "clientInfo": {
                "name": "codex-archive-inactive",
                "title": "Codex inactive-session archiver",
                "version": "1",
            }
        },
    )
    await client.notify("initialized", {})


async def list_threads(
    client: RpcClient,
    *,
    source_kinds: Sequence[str] = INTERACTIVE_SOURCE_KINDS,
) -> list[Thread]:
    threads: list[Thread] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()

    while True:
        params: JsonObject = {
            "archived": False,
            "limit": PAGE_SIZE,
            "sourceKinds": list(source_kinds),
        }
        if cursor is not None:
            params["cursor"] = cursor
        result = await client.request("thread/list", params)
        data = result.get("data")
        if not isinstance(data, list):
            raise ArchiveError("thread/list result.data is not a list")
        threads.extend(_thread_from_json(item) for item in data)

        next_cursor = result.get("nextCursor")
        if next_cursor is None:
            return threads
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ArchiveError(
                "thread/list result.nextCursor is not a string or null"
            )
        if next_cursor in seen_cursors:
            raise ArchiveError("thread/list repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


async def read_thread(client: RpcClient, thread_id: str) -> Thread:
    result = await client.request(
        "thread/read",
        {
            "threadId": thread_id,
            "includeTurns": False,
        },
    )
    return _thread_from_json(result.get("thread"))


async def archive_thread(client: RpcClient, thread_id: str) -> None:
    await client.request("thread/archive", {"threadId": thread_id})


async def load_thread_snapshot(client: RpcClient) -> ThreadSnapshot:
    return ThreadSnapshot(
        listed=tuple(await list_threads(client)),
        all_threads=tuple(
            await list_threads(client, source_kinds=ALL_SOURCE_KINDS)
        ),
    )


def _eligible(thread: Thread, *, now: int, minimum_age: int) -> bool:
    return (
        thread.status is ThreadStatus.NOT_LOADED
        and now - thread.updated_at >= minimum_age
    )


def _session_files(root: Path) -> tuple[Path, ...]:
    pending = [root]
    files: list[Path] = []
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        files.append(_normalized_path(Path(entry.path)))
        except OSError as exc:
            raise ArchiveError(
                f"could not traverse session directory {directory}: {exc}"
            ) from exc
    return tuple(files)


def _run_lsof(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    last_timeout: subprocess.TimeoutExpired | None = None
    for timeout in LSOF_TIMEOUTS_SECONDS:
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            last_timeout = exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise ArchiveError(
                f"could not inspect open session files: {exc}"
            ) from exc
    if last_timeout is None:
        raise ArchiveError("lsof has no configured timeout attempts")
    raise ArchiveError(
        f"could not inspect open session files: {last_timeout}"
    ) from last_timeout


def open_rollout_paths(sessions_dir: Path) -> set[Path]:
    sessions_dir = _normalized_path(sessions_dir)
    if not sessions_dir.is_dir():
        raise ArchiveError(f"session directory does not exist: {sessions_dir}")
    session_files = _session_files(sessions_dir)
    if not session_files:
        return set()

    lsof = Path("/usr/sbin/lsof")
    if not lsof.is_file():
        discovered = shutil.which("lsof")
        if discovered is None:
            raise ArchiveError("lsof is not installed")
        lsof = Path(discovered)

    completed = _run_lsof(
        [
            str(lsof),
            "-w",
            "-Fn",
            "-f",
            "--",
            *(str(path) for path in session_files),
        ]
    )

    if completed.stderr.strip():
        raise ArchiveError(
            "lsof could not inspect open session files: "
            f"{completed.stderr.strip()}"
        )
    if completed.returncode not in (0, 1):
        raise ArchiveError(
            "lsof could not inspect open session files: "
            f"exit status {completed.returncode}"
        )

    paths: set[Path] = set()
    for line in completed.stdout.splitlines():
        if not line.startswith("n"):
            continue
        if len(line) == 1:
            raise ArchiveError("lsof returned an empty file name")
        paths.add(_normalized_path(Path(line[1:])))
    if completed.returncode == 1 and completed.stdout.strip() and not paths:
        raise ArchiveError(
            "lsof returned partial output without open session file names"
        )
    return paths


def _thread_families(
    roots: Sequence[Thread],
    all_threads: Sequence[Thread],
) -> dict[str, tuple[Thread, ...]]:
    by_id = {thread.thread_id: thread for thread in all_threads}
    by_id.update((thread.thread_id, thread) for thread in roots)
    children: dict[str, list[str]] = defaultdict(list)
    for thread in all_threads:
        if thread.parent_thread_id is not None:
            children[thread.parent_thread_id].append(thread.thread_id)

    families: dict[str, tuple[Thread, ...]] = {}
    for root in roots:
        family: list[Thread] = []
        pending = [root.thread_id]
        seen: set[str] = set()
        while pending:
            thread_id = pending.pop()
            if thread_id in seen:
                raise ArchiveError(
                    f"thread family contains a cycle at {thread_id}"
                )
            seen.add(thread_id)
            family_member = by_id.get(thread_id)
            if family_member is None:
                raise ArchiveError(
                    f"thread family references missing thread {thread_id}"
                )
            family.append(family_member)
            pending.extend(children.get(thread_id, ()))
        families[root.thread_id] = tuple(family)
    return families


def _safe_family(
    family: Collection[Thread],
    *,
    open_paths: Collection[Path],
    sessions_dir: Path,
    now: int,
    minimum_age: int,
) -> bool:
    normalized_sessions_dir = _normalized_path(sessions_dir)
    for thread in family:
        if not _eligible(thread, now=now, minimum_age=minimum_age):
            return False
        path = thread.rollout_path
        if path is None or not path.is_relative_to(normalized_sessions_dir):
            return False
        if path in open_paths:
            return False
    return True


async def _cleanup_snapshot(
    client: RpcClient,
    *,
    snapshot: ThreadSnapshot,
    open_paths: Collection[Path],
    sessions_dir: Path,
    dry_run: bool,
    minimum_age: int,
    now: int,
) -> CleanupResult:
    families = _thread_families(snapshot.listed, snapshot.all_threads)
    open_root_ids = {
        root_id
        for root_id, family in families.items()
        if any(member.rollout_path in open_paths for member in family)
    }
    kept = [
        root for root in snapshot.listed if root.thread_id in open_root_ids
    ]
    kept_ids = {root.thread_id for root in kept}
    candidates = [
        thread
        for thread in snapshot.listed
        if _eligible(thread, now=now, minimum_age=minimum_age)
    ]
    selected: list[Thread] = []
    archived = 0
    changed_before_archive = 0
    blocked_families = 0

    for candidate in candidates:
        if not _safe_family(
            families[candidate.thread_id],
            open_paths=open_paths,
            sessions_dir=sessions_dir,
            now=now,
            minimum_age=minimum_age,
        ):
            blocked_families += 1
            if candidate.thread_id not in kept_ids:
                kept.append(candidate)
                kept_ids.add(candidate.thread_id)
            continue
        current = await read_thread(client, candidate.thread_id)
        if not _safe_family(
            (current,),
            open_paths=open_paths,
            sessions_dir=sessions_dir,
            now=now,
            minimum_age=minimum_age,
        ):
            changed_before_archive += 1
            if current.thread_id not in kept_ids:
                kept.append(current)
                kept_ids.add(current.thread_id)
            continue
        selected.append(current)
        if not dry_run:
            await archive_thread(client, current.thread_id)
            archived += 1

    return CleanupResult(
        selected=tuple(selected),
        kept=tuple(kept),
        archived=archived,
        open_families=len(open_root_ids),
        changed_before_archive=changed_before_archive,
        blocked_families=blocked_families,
    )


async def cleanup_sessions(
    client: RpcClient,
    *,
    open_paths: Collection[Path],
    sessions_dir: Path,
    dry_run: bool,
    minimum_age: int,
    now: int,
) -> CleanupResult:
    return await _cleanup_snapshot(
        client,
        snapshot=await load_thread_snapshot(client),
        open_paths=open_paths,
        sessions_dir=sessions_dir,
        dry_run=dry_run,
        minimum_age=minimum_age,
        now=now,
    )


def default_codex_home() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    return (
        Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    )


def default_socket_path() -> Path:
    return (
        default_codex_home() / "app-server-control" / "app-server-control.sock"
    )


def default_sessions_dir() -> Path:
    return default_codex_home() / "sessions"


def _nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find inactive Codex CLI and IDE sessions; archive them only "
            "when --apply is specified."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Archive eligible sessions instead of previewing the changes",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show protected sessions and zero-result summaries",
    )
    parser.add_argument(
        "--minimum-age",
        type=_nonnegative_int,
        default=DEFAULT_MINIMUM_AGE_SECONDS,
        metavar="SECONDS",
        help="Require the session's last update to be this old",
    )
    return parser


def ensure_app_server(socket_path: Path) -> None:
    socket_path = _normalized_path(socket_path)
    if socket_path.is_socket():
        return
    if socket_path != _normalized_path(default_socket_path()):
        raise ArchiveError(f"app-server socket does not exist: {socket_path}")

    codex = shutil.which("codex")
    if codex is None:
        raise ArchiveError(
            "app-server socket is absent and codex is not on PATH"
        )
    try:
        completed = subprocess.run(
            [codex, "app-server", "daemon", "start"],
            check=False,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveError(
            f"could not start app-server daemon: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if not detail:
            detail = f"exit status {completed.returncode}"
        raise ArchiveError(f"could not start app-server daemon: {detail}")


async def run_cleanup(
    *,
    socket_path: Path,
    sessions_dir: Path,
    dry_run: bool,
    minimum_age: int,
    now: int,
    snapshot_retry_delays: Sequence[int] = SNAPSHOT_RETRY_DELAYS_SECONDS,
) -> CleanupResult:
    normalized_sessions_dir = _normalized_path(sessions_dir)
    retry_delays = iter(snapshot_retry_delays)
    attempts = 0
    while True:
        attempts += 1
        snapshot_loaded = False
        try:
            ensure_app_server(socket_path)
            async with unix_connect(
                path=str(socket_path.expanduser()),
                uri="ws://localhost/",
                compression=None,
                user_agent_header=None,
                open_timeout=REQUEST_TIMEOUT_SECONDS,
                close_timeout=1,
            ) as connection:
                client = JsonRpcClient(connection)
                await initialize(client)
                snapshot = await load_thread_snapshot(client)
                snapshot_loaded = True
                open_paths = open_rollout_paths(normalized_sessions_dir)
                return await _cleanup_snapshot(
                    client,
                    snapshot=snapshot,
                    open_paths=open_paths,
                    sessions_dir=normalized_sessions_dir,
                    dry_run=dry_run,
                    minimum_age=minimum_age,
                    now=now,
                )
        except (
            OSError,
            TimeoutError,
            TransientRpcError,
            WebSocketException,
        ) as exc:
            if snapshot_loaded:
                raise
            try:
                delay = next(retry_delays)
            except StopIteration:
                raise ArchiveError(
                    "could not load thread snapshot after "
                    f"{attempts} attempts: {exc}"
                ) from exc
            await asyncio.sleep(delay)


def _print_result(
    result: CleanupResult,
    *,
    dry_run: bool,
    verbose: bool,
) -> None:
    changed = bool(result.selected) if dry_run else result.archived > 0
    if not changed and not verbose:
        return
    for thread in result.kept:
        print(f"keeping: {thread.label}")
    for thread in result.selected:
        print(f"archiving: {thread.label}")
    if dry_run:
        print(
            f"would archive {len(result.selected)} session(s); "
            f"observed {result.open_families} open family(s); "
            f"skipped {result.blocked_families} active/uncertain family(s) "
            f"and {result.changed_before_archive} changed session(s)"
        )
        return
    print(
        f"archived {result.archived} session(s); "
        f"observed {result.open_families} open family(s); "
        f"skipped {result.blocked_families} active/uncertain family(s) "
        f"and {result.changed_before_archive} changed session(s)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = not args.apply
    try:
        result = asyncio.run(
            run_cleanup(
                socket_path=default_socket_path(),
                sessions_dir=default_sessions_dir(),
                dry_run=dry_run,
                minimum_age=args.minimum_age,
                now=int(time.time()),
            )
        )
    except KeyboardInterrupt:
        return 130
    except (ArchiveError, OSError, TimeoutError, WebSocketException) as exc:
        print(f"codex-archive-inactive: {exc}", file=sys.stderr)
        return 1
    _print_result(result, dry_run=dry_run, verbose=args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
