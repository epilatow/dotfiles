"""Tests for files/local/libexec/gas-prices-breakdown/gas-prices-breakdown."""

from __future__ import annotations

import gzip
import http.client
import subprocess
import sys
import time
import urllib.error
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import gas_prices_breakdown as gpb  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

HELPER = (
    REPO_ROOT
    / "files"
    / "local"
    / "libexec"
    / "gas-prices-breakdown"
    / "gas-prices-breakdown"
)

URL = "https://example.invalid/report.xlsx"


@pytest.fixture(autouse=True)
def no_backoff_sleep() -> Iterator[list[float]]:
    """Record the retry delays instead of waiting them out."""
    slept: list[float] = []
    # The script resolves `time.sleep` at call time, so patching the
    # module here is what its retry loop will find.
    with patch.object(time, "sleep", autospec=True, side_effect=slept.append):
        yield slept


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        URL,
        code,
        "boom",
        {},  # type: ignore[arg-type]
        None,
    )


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.URLError(OSError(8, "nodename nor servname provided")),
        ConnectionResetError(54, "Connection reset by peer"),
        TimeoutError("timed out"),
        http.client.RemoteDisconnected("closed without response"),
        gzip.BadGzipFile("not a gzipped file"),
        _http_error(500),
        _http_error(503),
        _http_error(429),
        _http_error(408),
    ],
    ids=lambda e: f"{type(e).__name__}{getattr(e, 'code', '')}",
)
def test_transient_failures_are_retried(
    exc: Exception, no_backoff_sleep: list[float]
) -> None:
    """A failure that says nothing about the request gets another go."""
    with patch.object(
        gpb, "_http_bytes_once", autospec=True, side_effect=[exc, b"ok"]
    ) as once:
        assert gpb._http_bytes(URL) == b"ok"
    assert once.call_count == 2
    assert no_backoff_sleep == [gpb.HTTP_BACKOFF_SEC]


@pytest.mark.parametrize("code", [400, 403, 404, 410, 451])
def test_client_errors_are_not_retried(
    code: int, no_backoff_sleep: list[float]
) -> None:
    """A 4xx describes the request; repeating it unchanged is pointless."""
    with (
        patch.object(
            gpb,
            "_http_bytes_once",
            autospec=True,
            side_effect=_http_error(code),
        ) as once,
        pytest.raises(gpb.FetchError) as caught,
    ):
        gpb._http_bytes(URL)
    assert once.call_count == 1
    assert no_backoff_sleep == []
    assert "giving up after" not in str(caught.value)


def test_retries_are_exhausted_then_reported(
    no_backoff_sleep: list[float],
) -> None:
    """A source down for the whole run fails as FetchError, not URLError."""
    exc = urllib.error.URLError(ConnectionResetError(54, "reset by peer"))
    with (
        patch.object(
            gpb, "_http_bytes_once", autospec=True, side_effect=exc
        ) as once,
        pytest.raises(gpb.FetchError) as caught,
    ):
        gpb._http_bytes(URL)
    assert once.call_count == gpb.HTTP_ATTEMPTS
    assert len(no_backoff_sleep) == gpb.HTTP_ATTEMPTS - 1
    message = str(caught.value)
    assert URL in message
    assert "reset by peer" in message
    assert f"giving up after {gpb.HTTP_ATTEMPTS} attempts" in message


def test_backoff_grows_between_attempts(no_backoff_sleep: list[float]) -> None:
    """Successive waits widen, so a slow recovery still gets caught."""
    with (
        patch.object(
            gpb,
            "_http_bytes_once",
            autospec=True,
            side_effect=urllib.error.URLError("down"),
        ),
        pytest.raises(gpb.FetchError),
    ):
        gpb._http_bytes(URL)
    assert no_backoff_sleep == sorted(no_backoff_sleep)
    assert len(set(no_backoff_sleep)) == len(no_backoff_sleep)


def test_first_attempt_success_does_not_wait(
    no_backoff_sleep: list[float],
) -> None:
    """The retry path costs a working run nothing."""
    with patch.object(
        gpb, "_http_bytes_once", autospec=True, return_value=b"body"
    ) as once:
        assert gpb._http_bytes(URL) == b"body"
    assert once.call_count == 1
    assert no_backoff_sleep == []


def test_http_text_decodes_the_retried_body() -> None:
    """The text helper sits on top of the retrying byte helper."""
    with patch.object(
        gpb,
        "_http_bytes_once",
        autospec=True,
        side_effect=[TimeoutError("slow"), b"<html>caf\xc3\xa9</html>"],
    ):
        # Built with chr() so this file stays ASCII; the bytes above
        # are the UTF-8 encoding of the same character.
        e_acute = chr(0xE9)
        assert gpb._http_text(URL) == f"<html>caf{e_acute}</html>"


# ---------------------------------------------------------------------------
# Reporting a persistent failure
# ---------------------------------------------------------------------------


def test_non_xlsx_body_is_reported_not_raised_raw(tmp_path: Path) -> None:
    """A source answering 200 with an error page names itself in the error."""
    not_a_workbook = tmp_path / "report.xlsx"
    not_a_workbook.write_text("<html>503 Service Unavailable</html>")
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb._load_workbook(not_a_workbook, "OR CFP")
    assert "OR CFP" in str(caught.value)
    assert not isinstance(caught.value, zipfile.BadZipFile)


def test_valid_zip_that_is_not_a_workbook_is_reported(tmp_path: Path) -> None:
    """A readable zip carrying the wrong contents is still bad input."""
    not_a_workbook = tmp_path / "report.xlsx"
    with zipfile.ZipFile(not_a_workbook, "w") as archive:
        archive.writestr("readme.txt", "not a spreadsheet")
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb._load_workbook(not_a_workbook, "CARB LCFS")
    assert "CARB LCFS" in str(caught.value)


def test_missing_spec_md_exits_one_not_two(tmp_path: Path) -> None:
    """Content that stopped parsing is a source failure, not a usage one."""
    html = tmp_path / "page.html"
    html.write_text("<html>no spec here</html>")
    assert gpb.main(["extract-markdown", str(html)]) == 1


def test_absent_snapshot_to_remove_exits_two(tmp_path: Path) -> None:
    """Naming a snapshot the file lacks is a usage error, not a source one."""
    html = tmp_path / "page.html"
    html.write_text("const SNAPSHOTS = [\n];\n")
    assert gpb.main(["remove-snapshot", str(html), "2026-01-01"]) == 2


def test_fetch_error_is_a_snapshot_error() -> None:
    """One `except` in `main` has to cover both failure kinds."""
    assert issubclass(gpb.FetchError, gpb.SnapshotError)


def test_main_reports_snapshot_error_without_a_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A source failure exits nonzero with one error line."""
    html = tmp_path / "page.html"
    html.write_text("const SNAPSHOTS = [\n];\n")
    with patch.object(
        gpb,
        "cmd_add_snapshot",
        autospec=True,
        side_effect=gpb.FetchError("GET https://example.invalid: down"),
    ):
        exit_code = gpb.main(["add-snapshot", str(html)])
    assert exit_code == 1
    assert [r.getMessage() for r in caplog.records] == [
        "GET https://example.invalid: down"
    ]


def test_unexpected_errors_keep_their_traceback(tmp_path: Path) -> None:
    """Only world conditions are swallowed; a bug still surfaces raw."""
    html = tmp_path / "page.html"
    html.write_text("const SNAPSHOTS = [\n];\n")
    with (
        patch.object(
            gpb,
            "cmd_add_snapshot",
            autospec=True,
            side_effect=ZeroDivisionError("bug"),
        ),
        pytest.raises(ZeroDivisionError),
    ):
        gpb.main(["add-snapshot", str(html)])


def test_unreadable_page_is_reported_not_raised(tmp_path: Path) -> None:
    """The path comes from a job's argv, so a bad one is bad input."""
    missing = tmp_path / "absent.html"
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb.read_html(missing)
    assert str(missing) in str(caught.value)


def test_process_exits_one_with_no_traceback(tmp_path: Path) -> None:
    """End-to-end: the crony job gets an exit code and a readable log.

    Driven through the real entry point so the `sys.exit(main())`
    wiring is covered, and through a failure that needs no network so
    the run costs no retry backoff.
    """
    missing = tmp_path / "absent.html"
    result = subprocess.run(
        [sys.executable, str(HELPER), "list-snapshots", str(missing)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "ERROR" in result.stderr
    assert str(missing) in result.stderr
