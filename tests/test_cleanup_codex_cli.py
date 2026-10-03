from __future__ import annotations

import fcntl
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import cleanup_codex_cli as cleanup  # noqa: E402


def release(root: Path, version: str, target: str = "aarch64-test") -> Path:
    path = root / f"{version}-{target}"
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "codex").write_bytes(b"synthetic binary")
    return path


@pytest.fixture
def installation(tmp_path: Path) -> Path:
    standalone = tmp_path / "packages" / "standalone"
    root = standalone / "releases"
    latest = release(root, "0.160.0")
    (standalone / "current").symlink_to(latest)
    return standalone


def test_deletes_only_superseded_unused_versions(installation: Path) -> None:
    root = installation / "releases"
    unused = release(root, "0.9.0")
    active = release(root, "0.150.0")
    other_target = release(root, "0.120.0", "x86_64-test")
    unknown = root / "development-build"
    unknown.mkdir()
    incomplete = root / "0.170.0-aarch64-test"
    incomplete.mkdir()
    with patch.object(cleanup, "active_releases", autospec=True) as inspect:
        inspect.return_value = {active}
        assert cleanup.cleanup(installation, apply=True) == 0
    assert not unused.exists()
    for kept in [active, other_target, unknown, incomplete]:
        assert kept.is_dir()
    assert (installation / "current").resolve().is_dir()


def test_dry_run_and_current_version_are_preserved(installation: Path) -> None:
    root = installation / "releases"
    old = release(root, "0.150.0")
    (installation / "current").unlink()
    (installation / "current").symlink_to(old)
    stale = release(root, "0.140.0")
    with patch.object(cleanup, "active_releases", autospec=True) as inspect:
        inspect.return_value = set()
        cleanup.cleanup(installation, apply=False)
        assert stale.exists()
        cleanup.cleanup(installation, apply=True)
    assert not stale.exists()
    assert old.exists()
    assert (root / "0.160.0-aarch64-test").exists()


def test_release_becoming_active_is_preserved(installation: Path) -> None:
    stale = release(installation / "releases", "0.150.0")
    with patch.object(cleanup, "active_releases", autospec=True) as inspect:
        inspect.side_effect = [set(), {stale}]
        cleanup.cleanup(installation, apply=True)
    assert stale.exists()


def test_activity_failure_prevents_deletion(installation: Path) -> None:
    stale = release(installation / "releases", "0.150.0")
    with patch.object(cleanup, "active_releases", autospec=True) as inspect:
        inspect.side_effect = RuntimeError("Cannot inspect")
        assert (
            cleanup.main(
                ["--codex-home", str(installation.parents[1]), "--apply"]
            )
            == 1
        )
    assert stale.exists()


def test_busy_installation_lock_defers_cleanup(installation: Path) -> None:
    stale = release(installation / "releases", "0.150.0")
    with (installation / "install.lock").open("w+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cleanup.cleanup(installation, apply=True) == 0
    assert stale.exists()


def test_symlinked_release_is_rejected(installation: Path) -> None:
    root = installation / "releases"
    external = installation.parent / "external"
    external.mkdir()
    (root / "0.150.0-aarch64-test").symlink_to(external)
    with pytest.raises(RuntimeError, match="real directory"):
        cleanup.cleanup(installation, apply=True)
    assert external.is_dir()


def test_broken_current_prevents_deletion(installation: Path) -> None:
    stale = release(installation / "releases", "0.150.0")
    (installation / "current").unlink()
    (installation / "current").symlink_to(installation / "missing")
    assert (
        cleanup.main(["--codex-home", str(installation.parents[1]), "--apply"])
        == 1
    )
    assert stale.exists()


def test_changed_candidate_is_rejected(installation: Path) -> None:
    root = installation / "releases"
    stale = release(root, "0.150.0")

    def inspect(_root: Path) -> set[Path]:
        (stale / "new-file").write_text("installation changed")
        return set()

    with (
        patch.object(
            cleanup, "active_releases", autospec=True, side_effect=inspect
        ),
        pytest.raises(RuntimeError, match="Release changed"),
    ):
        cleanup.cleanup(installation, apply=True)
    assert stale.exists()


@pytest.mark.parametrize("returncode", [0, 1])
def test_lsof_parses_mapped_helpers_and_spaces(
    tmp_path: Path, returncode: int
) -> None:
    root = tmp_path / "with spaces" / "releases"
    active = root / "0.150.0-aarch64-test"
    result = subprocess.CompletedProcess(
        [], returncode, f"p42\0\nftxt\0n{active}/bin/helper\0\n".encode(), b""
    )
    with patch.object(subprocess, "run", autospec=True) as run:
        run.return_value = result
        assert cleanup.active_releases(root) == {active}


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [(2, b"", b""), (1, b"", b"warning"), (0, b"garbage", b"")],
)
def test_unreliable_lsof_output_is_rejected(
    tmp_path: Path, returncode: int, stdout: bytes, stderr: bytes
) -> None:
    with patch.object(subprocess, "run", autospec=True) as run:
        run.return_value = subprocess.CompletedProcess(
            [], returncode, stdout, stderr
        )
        with pytest.raises(RuntimeError):
            cleanup.active_releases(tmp_path)


def test_real_lsof_protects_open_resource(installation: Path) -> None:
    if shutil.which("lsof") is None:
        pytest.skip("lsof not installed")
    stale = release(installation / "releases", "0.150.0")
    resource = stale / "resource"
    resource.write_text("synthetic resource")
    with resource.open("rb"):
        assert stale in cleanup.active_releases(installation / "releases")
        cleanup.cleanup(installation, apply=True)
    assert stale.exists()
    cleanup.cleanup(installation, apply=True)
    assert not stale.exists()


def test_real_lsof_protects_running_binary(installation: Path) -> None:
    compiler = shutil.which("cc")
    if compiler is None or shutil.which("lsof") is None:
        pytest.skip("cc and lsof required for native executable test")
    stale = release(installation / "releases", "0.150.0")
    binary = stale / "bin" / "codex"
    subprocess.run(
        [compiler, "-x", "c", "-o", str(binary), "-"],
        input=(
            b"#include <unistd.h>\nint main(void) { sleep(300); return 0; }\n"
        ),
        check=True,
        capture_output=True,
    )
    process = subprocess.Popen([str(binary)], start_new_session=True)
    process_group = process.pid
    try:
        assert stale in cleanup.active_releases(installation / "releases")
        cleanup.cleanup(installation, apply=True)
        assert stale.exists()
    finally:
        if process.poll() is None:
            os.killpg(process_group, signal.SIGTERM)
        process.wait()
    cleanup.cleanup(installation, apply=True)
    assert not stale.exists()
