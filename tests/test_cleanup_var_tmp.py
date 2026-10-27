from __future__ import annotations

import errno
import fcntl
import getpass
import os
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import cleanup_var_tmp as cleanup  # noqa: E402


def node_file(root: Path, name: str = "0123abcd") -> Path:
    path = (
        root
        / "node-compile-cache"
        / f"v24.22.1-arm64-964aae3f-{os.getuid()}"
        / name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic compilation cache")
    return path


def pytest_run(root: Path, number: int) -> Path:
    path = root / f"pytest-of-{getpass.getuser()}" / f"pytest-{number}"
    path.mkdir(parents=True)
    (path / "diagnostic.txt").write_text("synthetic test output")
    return path


def test_unused_fresh_caches_are_removed_without_an_age_delay(
    tmp_path: Path,
) -> None:
    node = node_file(tmp_path)
    run = pytest_run(tmp_path, 1)
    unrelated = tmp_path / "other-tool"
    unrelated.mkdir()
    with patch.object(
        cleanup, "active_paths", autospec=True, return_value=set()
    ):
        cleanup.prune(tmp_path, apply=True)
    assert not node.exists() and not run.exists()
    assert unrelated.is_dir()


def test_live_pytest_pid_and_open_paths_are_preserved(tmp_path: Path) -> None:
    node = node_file(tmp_path)
    live = pytest_run(tmp_path, 1)
    (live / ".lock").write_text(str(os.getpid()))
    inspected = pytest_run(tmp_path, 2)
    with patch.object(
        cleanup,
        "active_paths",
        autospec=True,
        return_value={node, inspected / "diagnostic.txt"},
    ):
        cleanup.prune(tmp_path, apply=True)
    assert node.exists() and live.exists() and inspected.exists()


def test_dead_pytest_lock_can_be_claimed_and_removed(tmp_path: Path) -> None:
    run = pytest_run(tmp_path, 1)
    (run / ".lock").write_text("12345")
    with (
        patch.object(
            cleanup, "active_paths", autospec=True, return_value=set()
        ),
        patch.object(
            os, "kill", autospec=True, side_effect=ProcessLookupError
        ),
    ):
        cleanup.prune(tmp_path, apply=True)
    assert not run.exists()


@pytest.mark.parametrize(
    "contents", ["", "unknown", "-5", "0", "9999999999", "1" * 5000]
)
def test_uncertain_pytest_lock_is_kept(tmp_path: Path, contents: str) -> None:
    run = pytest_run(tmp_path, 1)
    (run / ".lock").write_text(contents)
    with patch.object(
        cleanup, "active_paths", autospec=True, return_value=set()
    ):
        cleanup.prune(tmp_path, apply=True)
    assert run.exists()


def test_dry_run_does_not_claim_or_delete_caches(tmp_path: Path) -> None:
    node = node_file(tmp_path)
    run = pytest_run(tmp_path, 1)
    with patch.object(
        cleanup, "active_paths", autospec=True, return_value=set()
    ):
        cleanup.prune(tmp_path, apply=False)
    assert node.exists() and run.exists()
    assert not (run / ".lock").exists()


def test_symlinks_and_unknown_entries_are_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve")
    node = node_file(root)
    node.unlink()
    node.symlink_to(sentinel)
    (node.parent / "unknown").write_text("keep")
    bucket_alias = node.parent.with_name(
        f"v25.0.0-arm64-abcdef01-{os.getuid()}"
    )
    bucket_alias.symlink_to(outside, target_is_directory=True)
    run = pytest_run(root, 1)
    (run / ".lock").symlink_to(sentinel)
    (run.parent / "pytest-2").symlink_to(outside, target_is_directory=True)
    with patch.object(
        cleanup, "active_paths", autospec=True, return_value=set()
    ):
        cleanup.prune(root, apply=True)
    assert node.is_symlink() and bucket_alias.is_symlink()
    assert (node.parent / "unknown").exists()
    assert run.exists() and sentinel.read_text() == "preserve"


def test_changed_candidate_is_kept(tmp_path: Path) -> None:
    node = node_file(tmp_path)

    def inspect(_root: Path) -> set[Path]:
        node.write_bytes(b"rewritten by another process")
        return set()

    with patch.object(
        cleanup, "active_paths", autospec=True, side_effect=inspect
    ):
        cleanup.prune(tmp_path, apply=True)
    assert node.read_bytes() == b"rewritten by another process"


def test_entries_owned_by_another_user_are_preserved(tmp_path: Path) -> None:
    node = node_file(tmp_path)
    run = pytest_run(tmp_path, 1)
    original = cleanup.Entry.read

    def read(path: Path) -> cleanup.Entry:
        entry = original(path)
        return (
            replace(entry, owner=entry.owner + 1)
            if path in (node, run)
            else entry
        )

    with (
        patch.object(cleanup.Entry, "read", autospec=True, side_effect=read),
        patch.object(
            cleanup, "active_paths", autospec=True, return_value=set()
        ),
    ):
        cleanup.prune(tmp_path, apply=True)
    assert node.exists() and run.exists()


def test_symlinked_tmpdir_is_rejected(tmp_path: Path) -> None:
    node = node_file(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    assert cleanup.main(["--tmpdir", str(alias), "--apply"]) == 1
    assert node.exists()


def test_replaced_parent_cannot_redirect_deletion(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    node = node_file(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / node.name
    sentinel.write_text("preserve")

    def inspect(_root: Path) -> set[Path]:
        node.parent.rename(root / "saved-cache")
        node.parent.symlink_to(outside, target_is_directory=True)
        return set()

    with patch.object(
        cleanup, "active_paths", autospec=True, side_effect=inspect
    ):
        cleanup.prune(root, apply=True)
    assert sentinel.read_text() == "preserve"


def test_pytest_becoming_active_before_claim_is_preserved(
    tmp_path: Path,
) -> None:
    run = pytest_run(tmp_path, 1)
    original = cleanup.pytest_lock
    calls = 0

    def inspect(path: Path) -> tuple[bool, cleanup.Entry | None]:
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text(str(os.getpid()))
        return original(path)

    with (
        patch.object(
            cleanup, "active_paths", autospec=True, return_value=set()
        ),
        patch.object(
            cleanup, "pytest_lock", autospec=True, side_effect=inspect
        ),
    ):
        cleanup.prune(tmp_path, apply=True)
    assert run.exists()


def test_failed_cleanup_releases_its_pytest_claim(tmp_path: Path) -> None:
    run = pytest_run(tmp_path, 1)
    with (
        patch.object(
            cleanup, "active_paths", autospec=True, return_value=set()
        ),
        patch.object(
            shutil, "rmtree", autospec=True, side_effect=OSError("busy")
        ),
        pytest.raises(OSError, match="busy"),
    ):
        cleanup.prune(tmp_path, apply=True)
    assert run.exists() and not (run / ".lock").exists()


@pytest.mark.parametrize("returncode", [0, 1])
def test_activity_snapshot_parses_mapped_files_and_spaces(
    tmp_path: Path, returncode: int
) -> None:
    path = tmp_path / "with spaces"
    result = subprocess.CompletedProcess(
        [], returncode, f"p42\0\nftxt\0n{path}\0\n".encode(), b""
    )
    with patch.object(subprocess, "run", autospec=True, return_value=result):
        assert cleanup.active_paths(tmp_path) == {path.resolve()}


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [(2, b"", b""), (1, b"", b"warning"), (0, b"garbage", b"")],
)
def test_unreliable_activity_check_prevents_cleanup(
    tmp_path: Path, returncode: int, stdout: bytes, stderr: bytes
) -> None:
    node = node_file(tmp_path)
    result = subprocess.CompletedProcess([], returncode, stdout, stderr)
    with patch.object(subprocess, "run", autospec=True, return_value=result):
        assert cleanup.main(["--tmpdir", str(tmp_path), "--apply"]) == 1
    assert node.exists()


def test_real_open_cache_is_preserved_until_closed(tmp_path: Path) -> None:
    if shutil.which("lsof") is None:
        pytest.skip("lsof required")
    node = node_file(tmp_path)
    with node.open("rb"):
        cleanup.prune(tmp_path, apply=True)
        assert node.exists()
    cleanup.prune(tmp_path, apply=True)
    assert not node.exists()


def test_walk_has_a_real_hard_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = tmp_path / "slow_walk.py"
    worker.write_text("import time\ntime.sleep(10)\n")
    monkeypatch.setattr(cleanup, "__file__", str(worker))
    with pytest.raises(RuntimeError, match="traversal exceeded"):
        cleanup.verify_walk(tmp_path, timeout=0.05)


def test_late_successful_walk_still_fails(tmp_path: Path) -> None:
    with (
        patch.object(
            subprocess,
            "run",
            autospec=True,
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run,
        patch.object(time, "monotonic", autospec=True, side_effect=[0, 61]),
        pytest.raises(RuntimeError, match="exceeded 60 seconds"),
    ):
        cleanup.verify_walk(tmp_path)
    assert run.call_args.kwargs["timeout"] == 60
    assert run.call_args.args[0] == [
        sys.executable,
        str(Path(cleanup.__file__).resolve()),
        "--walk-only",
        "--tmpdir",
        str(tmp_path),
    ]


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EPERM])
def test_walk_counts_inaccessible_descendants_and_visits_accessible_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], error_number: int
) -> None:
    denied = tmp_path / "denied"
    denied.mkdir()
    accessible = tmp_path / "accessible" / "nested"
    accessible.mkdir(parents=True)
    original = os.open
    visited: set[Path] = set()

    def open_directory(path: Path, flags: int) -> int:
        visited.add(path)
        if path == denied:
            raise PermissionError(error_number, "denied", path)
        return original(path, flags)

    with patch.object(os, "open", autospec=True, side_effect=open_directory):
        assert cleanup.main(["--walk-only", "--tmpdir", str(tmp_path)]) == 0
    assert visited == {tmp_path, denied, accessible.parent, accessible}
    assert "skipped 1 inaccessible path." in capsys.readouterr().out
    assert not (tmp_path / ".cleanup-var-tmp.lock").exists()


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EPERM])
def test_walk_fails_on_an_inaccessible_root(
    tmp_path: Path, error_number: int
) -> None:
    with patch.object(
        os,
        "open",
        autospec=True,
        side_effect=PermissionError(error_number, "denied", tmp_path),
    ):
        assert cleanup.main(["--walk-only", "--tmpdir", str(tmp_path)]) == 1


def test_walk_fails_on_unexpected_descendant_errors(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    original = os.open

    def open_directory(path: Path, flags: int) -> int:
        if path == broken:
            raise OSError(errno.EIO, "I/O error", path)
        return original(path, flags)

    with (
        patch.object(os, "open", autospec=True, side_effect=open_directory),
        pytest.raises(OSError, match="I/O error"),
    ):
        cleanup.walk(tmp_path)


@pytest.mark.parametrize("replacement", ["missing", "file", "symlink"])
def test_walk_tolerates_descendants_replaced_after_discovery(
    tmp_path: Path, replacement: str
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    original = os.open

    def open_directory(path: Path, flags: int) -> int:
        if path == child:
            child.rmdir()
            if replacement == "file":
                child.write_text("replacement")
            elif replacement == "symlink":
                child.symlink_to(tmp_path, target_is_directory=True)
        return original(path, flags)

    with patch.object(os, "open", autospec=True, side_effect=open_directory):
        assert cleanup.walk(tmp_path) == 0


def test_real_walk_does_not_follow_directory_symlinks(tmp_path: Path) -> None:
    (tmp_path / "cycle").symlink_to(tmp_path, target_is_directory=True)
    cleanup.verify_walk(tmp_path)


def test_real_walk_still_fails_when_the_starting_directory_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="TMPDIR traversal failed"):
        cleanup.verify_walk(tmp_path / "missing")


def test_walk_failure_fails_job_after_cleanup(tmp_path: Path) -> None:
    node = node_file(tmp_path)
    with (
        patch.object(
            cleanup, "active_paths", autospec=True, return_value=set()
        ),
        patch.object(
            cleanup,
            "verify_walk",
            autospec=True,
            side_effect=RuntimeError("traversal exceeded 60 seconds"),
        ),
    ):
        assert cleanup.main(["--tmpdir", str(tmp_path), "--apply"]) == 1
    assert not node.exists()


def test_busy_job_lock_defers_cleanup(tmp_path: Path) -> None:
    node = node_file(tmp_path)
    with (tmp_path / ".cleanup-var-tmp.lock").open("w+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cleanup.main(["--tmpdir", str(tmp_path), "--apply"]) == 0
    assert node.exists()


def test_missing_tmpdir_does_not_fall_back_to_system_tmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    assert cleanup.main([]) == 1


def test_real_command_removes_unused_and_keeps_live_run(
    tmp_path: Path,
) -> None:
    if shutil.which("lsof") is None:
        pytest.skip("lsof required")
    node = node_file(tmp_path)
    live = pytest_run(tmp_path, 1)
    (live / ".lock").write_text(str(os.getpid()))
    result = subprocess.run(
        [
            sys.executable,
            str(cleanup.__file__),
            "--tmpdir",
            str(tmp_path),
            "--apply",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not node.exists() and live.exists()
    assert "TMPDIR traversal:" in result.stdout


class _Job(TypedDict):
    script: str
    args: list[str]
    platforms: list[str]


class _Group(TypedDict):
    jobs: list[str]


_Config = TypedDict(
    "_Config", {"job": dict[str, _Job], "job-group": dict[str, _Group]}
)


def test_cleanup_is_registered_in_the_daily_group() -> None:
    config = cast(
        _Config,
        tomllib.loads(
            (REPO_ROOT / "files/config/crony/config.toml").read_text()
        ),
    )
    job = config["job"]["cleanup-var-tmp"]
    assert job["script"] == "~/.local/libexec/cleanup-var-tmp/cleanup-var-tmp"
    assert job["args"] == ["--apply"] and job["platforms"] == ["darwin"]
    assert "cleanup-var-tmp" in config["job-group"]["daily-misc"]["jobs"]
    assert "daily-misc" in config["job-group"]["daily"]["jobs"]
