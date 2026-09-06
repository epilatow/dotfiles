"""Tests for files/local/libexec/dpmr-calendar-scrape/dpmr-calendar-scrape."""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from curl_cffi import requests

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import dpmr_calendar_scrape as dcs  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

URL = "https://example.invalid/calendar/"


@pytest.fixture(autouse=True)
def no_backoff_sleep() -> Iterator[list[float]]:
    """Record the retry delays instead of waiting them out."""
    slept: list[float] = []
    # The script resolves `time.sleep` at call time, so patching the
    # module here is what its retry loop will find.
    with patch.object(time, "sleep", autospec=True, side_effect=slept.append):
        yield slept


def _session(*results: object) -> Mock:
    """A stand-in session whose `get` yields `results` in order.

    An exception in `results` is raised by `get`; anything else is
    returned as a response whose `raise_for_status` is a no-op.
    """
    responses = []
    for item in results:
        if isinstance(item, BaseException):
            responses.append(item)
        else:
            responses.append(Mock(text=item, raise_for_status=Mock()))
    return Mock(get=Mock(side_effect=responses))


def _http_error(status: int) -> requests.exceptions.HTTPError:
    exc = requests.exceptions.HTTPError(f"HTTP {status}")
    exc.response = Mock(status_code=status)
    return exc


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        requests.exceptions.Timeout("Operation timed out"),
        requests.exceptions.ConnectionError("connection reset by peer"),
        _http_error(500),
        _http_error(502),
        _http_error(503),
        _http_error(429),
        _http_error(408),
    ],
    ids=[
        "Timeout",
        "ConnectionError",
        "HTTPError500",
        "HTTPError502",
        "HTTPError503",
        "HTTPError429",
        "HTTPError408",
    ],
)
def test_transient_failures_are_retried(
    exc: Exception, no_backoff_sleep: list[float]
) -> None:
    """A failure that says nothing about the request gets another go."""
    session = _session(exc, "<html>ok</html>")
    assert dcs._get_text(session, URL) == "<html>ok</html>"
    assert session.get.call_count == 2
    assert no_backoff_sleep == [dcs.HTTP_BACKOFF_SEC]


@pytest.mark.parametrize("status", [400, 403, 404, 410])
def test_client_errors_are_not_retried(
    status: int, no_backoff_sleep: list[float]
) -> None:
    """A 4xx describes the request; repeating it unchanged is pointless."""
    session = _session(_http_error(status))
    with pytest.raises(dcs.FetchError) as caught:
        dcs._get_text(session, URL)
    assert session.get.call_count == 1
    assert no_backoff_sleep == []
    assert "giving up after" not in str(caught.value)


def test_retries_are_exhausted_then_reported(
    no_backoff_sleep: list[float],
) -> None:
    """A site down for the whole run fails as FetchError, not a curl error."""
    exc = requests.exceptions.Timeout("Operation timed out after 992057 ms")
    session = _session(*[exc] * dcs.HTTP_ATTEMPTS)
    with pytest.raises(dcs.FetchError) as caught:
        dcs._get_text(session, URL)
    assert session.get.call_count == dcs.HTTP_ATTEMPTS
    assert len(no_backoff_sleep) == dcs.HTTP_ATTEMPTS - 1
    message = str(caught.value)
    assert URL in message
    assert f"giving up after {dcs.HTTP_ATTEMPTS} attempts" in message


def test_backoff_grows_between_attempts(no_backoff_sleep: list[float]) -> None:
    """Successive waits widen, so a slow recovery still gets caught."""
    exc = requests.exceptions.ConnectionError("down")
    session = _session(*[exc] * dcs.HTTP_ATTEMPTS)
    with pytest.raises(dcs.FetchError):
        dcs._get_text(session, URL)
    assert no_backoff_sleep == sorted(no_backoff_sleep)
    assert len(set(no_backoff_sleep)) == len(no_backoff_sleep)


def test_first_attempt_success_does_not_wait(
    no_backoff_sleep: list[float],
) -> None:
    """The retry path costs a working run nothing."""
    session = _session("<html>ok</html>")
    assert dcs._get_text(session, URL) == "<html>ok</html>"
    assert session.get.call_count == 1
    assert no_backoff_sleep == []


def test_fetch_window_retries_through_its_url() -> None:
    """Every window walked by a run goes through the retrying helper."""
    session = _session(requests.exceptions.Timeout("slow"), "<html>ok</html>")
    assert dcs.fetch_window(session, date(2026, 9, 4)) == "<html>ok</html>"
    assert session.get.call_count == 2
    requested = session.get.call_args.args[0]
    assert requested.endswith("/calendar/exact_date~9-4-2026/")


# ---------------------------------------------------------------------------
# Reporting a persistent failure
# ---------------------------------------------------------------------------


def test_fetch_error_is_a_scrape_error() -> None:
    """One `except` in `main` has to cover every failure kind."""
    assert issubclass(dcs.FetchError, dcs.ScrapeError)


def test_unwritable_output_is_reported_not_raised(tmp_path: Path) -> None:
    """The path comes from a job's argv, so a bad one is bad input."""
    unwritable = tmp_path / "no-such-dir" / "out.ics"
    with pytest.raises(dcs.ScrapeError) as caught:
        dcs._publish(unwritable, b"BEGIN:VCALENDAR\n", write=True)
    assert str(unwritable) in str(caught.value)


def test_unreadable_output_is_reported_not_raised(tmp_path: Path) -> None:
    """An existing but unreadable feed is reported, not raised raw."""
    existing = tmp_path / "out.ics"
    existing.write_bytes(b"BEGIN:VCALENDAR\n")
    existing.chmod(0o000)
    try:
        with pytest.raises(dcs.ScrapeError) as caught:
            dcs._read_existing(existing)
    finally:
        existing.chmod(0o644)
    assert str(existing) in str(caught.value)


def test_missing_output_reads_as_absent(tmp_path: Path) -> None:
    """A first run has no previous feed, which is not an error."""
    assert dcs._read_existing(tmp_path / "absent.ics") is None


def test_existing_output_is_read_back(tmp_path: Path) -> None:
    """The previous feed is what the past-event carry-over reads from."""
    existing = tmp_path / "out.ics"
    existing.write_bytes(b"BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    assert dcs._read_existing(existing) == b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"


def test_publish_writes_and_sets_mode(tmp_path: Path) -> None:
    """A changed feed is written and left world-readable."""
    out = tmp_path / "out.ics"
    dcs._publish(out, b"BEGIN:VCALENDAR\n", write=True)
    assert out.read_bytes() == b"BEGIN:VCALENDAR\n"
    assert out.stat().st_mode & 0o777 == 0o644


def test_publish_without_write_still_fixes_mode(tmp_path: Path) -> None:
    """An unchanged feed keeps its bytes but still gets its mode pinned."""
    out = tmp_path / "out.ics"
    out.write_bytes(b"BEGIN:VCALENDAR\n")
    out.chmod(0o600)
    dcs._publish(out, b"IGNORED", write=False)
    assert out.read_bytes() == b"BEGIN:VCALENDAR\n"
    assert out.stat().st_mode & 0o777 == 0o644


def test_main_reports_scrape_error_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A source failure exits nonzero with one error line."""
    with patch.object(
        dcs,
        "run",
        autospec=True,
        side_effect=dcs.FetchError("GET https://example.invalid: down"),
    ):
        exit_code = dcs.main([])
    assert exit_code == 1
    assert capsys.readouterr().err == (
        "error: GET https://example.invalid: down\n"
    )


def test_unexpected_errors_keep_their_traceback() -> None:
    """Only world conditions are swallowed; a bug still surfaces raw."""
    with (
        patch.object(
            dcs, "run", autospec=True, side_effect=ZeroDivisionError("bug")
        ),
        pytest.raises(ZeroDivisionError),
    ):
        dcs.main([])


def test_empty_scrape_refuses_to_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Markup that stops parsing must not blank an existing feed."""
    existing = tmp_path / "out.ics"
    existing.write_bytes(b"BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    before = existing.read_bytes()
    with patch.object(
        dcs, "fetch_window", autospec=True, return_value="<html></html>"
    ):
        exit_code = dcs.main([str(existing)])
    assert exit_code == 1
    assert existing.read_bytes() == before
    assert "no events parsed" in capsys.readouterr().err
