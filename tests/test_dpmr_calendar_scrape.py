"""Tests for files/local/libexec/dpmr-calendar-scrape/dpmr-calendar-scrape."""

from __future__ import annotations

import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest
from curl_cffi import CurlECode, requests
from curl_cffi.requests.exceptions import CODE2ERROR

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


def _curl_error(code: CurlECode) -> requests.exceptions.RequestException:
    """Build the exception curl_cffi raises for a curl failure code.

    A request that died before a status line arrived still comes back
    with the parsed response attached, carrying `status_code == 0`
    rather than nothing at all; a bare `Timeout("...")` answers None
    instead, a shape the library never produces. The class comes from
    the library's own `CODE2ERROR` table, so the cases below stay
    honest about which failures it routes to an `HTTPError` subclass.
    """
    exc_type = CODE2ERROR.get(code, requests.exceptions.RequestException)
    response = requests.Response()
    response.status_code = 0
    return exc_type(f"Failed to perform, curl: ({int(code)})", code, response)


# Curl failures that never reached a status line: the connection died,
# the name did not resolve, the transfer was cut short, the HTTP/2
# session broke. The session impersonates Chrome and so negotiates
# HTTP/2, which puts the protocol-level codes in reach of a real run.
TRANSPORT_CURL_CODES = [
    CurlECode.OPERATION_TIMEDOUT,
    CurlECode.COULDNT_RESOLVE_HOST,
    CurlECode.COULDNT_CONNECT,
    CurlECode.RECV_ERROR,
    CurlECode.SEND_ERROR,
    CurlECode.GOT_NOTHING,
    CurlECode.PARTIAL_FILE,
    CurlECode.HTTP2,
    CurlECode.HTTP2_STREAM,
]


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code", TRANSPORT_CURL_CODES, ids=lambda code: code.name
)
def test_failures_without_a_status_are_retried(
    code: CurlECode, no_backoff_sleep: list[float]
) -> None:
    """No status line arrived, so there is no verdict to obey.

    Runs against the class curl_cffi itself maps each code to, which is
    the fact worth pinning: the library routes several of these
    transport failures to `HTTPError` subclasses, so the exception type
    alone does not establish that the site answered. Only a nonzero
    status does.
    """
    session = _session(_curl_error(code), "<html>ok</html>")
    assert dcs._get_text(session, URL) == "<html>ok</html>"
    assert session.get.call_count == 2
    assert no_backoff_sleep == [dcs.HTTP_BACKOFF_SEC]


@pytest.mark.parametrize("status", [500, 502, 503, 429, 408])
def test_retryable_statuses_are_retried(
    status: int, no_backoff_sleep: list[float]
) -> None:
    """A status the site could answer differently gets another go."""
    session = _session(_http_error(status), "<html>ok</html>")
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
    session = _session(
        *[
            _curl_error(CurlECode.OPERATION_TIMEDOUT)
            for _ in range(dcs.HTTP_ATTEMPTS)
        ]
    )
    with pytest.raises(dcs.FetchError) as caught:
        dcs._get_text(session, URL)
    assert session.get.call_count == dcs.HTTP_ATTEMPTS
    assert len(no_backoff_sleep) == dcs.HTTP_ATTEMPTS - 1
    message = str(caught.value)
    assert URL in message
    assert f"giving up after {dcs.HTTP_ATTEMPTS} attempts" in message


def test_backoff_sequence_spans_the_budgeted_window(
    no_backoff_sleep: list[float],
) -> None:
    """The delays the budget is reasoned about, pinned to their values.

    `HTTP_ATTEMPTS` is documented in terms of how long the attempts
    span, so a change to the count or the growth factor that silently
    shortens the window has to fail here rather than leave the comment
    describing a budget the code no longer has.
    """
    session = _session(
        *[_curl_error(CurlECode.RECV_ERROR) for _ in range(dcs.HTTP_ATTEMPTS)]
    )
    with pytest.raises(dcs.FetchError):
        dcs._get_text(session, URL)
    assert no_backoff_sleep == [5.0, 15.0, 45.0, 135.0]


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
    session = _session(
        _curl_error(CurlECode.OPERATION_TIMEDOUT), "<html>ok</html>"
    )
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


# ---------------------------------------------------------------------------
# Parsing the agenda markup
# ---------------------------------------------------------------------------

# The plugin renders the separator in a time range as an en dash, which
# `TIME_RE` accepts alongside a hyphen. Built with chr() so this file
# stays ASCII while the fixture carries the character the site sends.
EN_DASH = chr(0x2013)


def _event_div(
    *,
    instance_id: str | None = "27431",
    event_id: str | None = "630674",
    end: str | None = "2026-09-17T19:15:00-07:00",
    title: str = "Hill Workout",
    location: str | None = None,
    time_text: str | None = f"Sep 17 @ 6:00 pm {EN_DASH} 7:15 pm",
    description: str | None = "Weekly hills.",
    href: str | None = (
        "https://example.invalid/event/hill/?instance_id=27431"
    ),
) -> str:
    """Render one agenda entry in the shape the plugin emits.

    The class list carries both ids and the end timestamp rides on
    `data-end`; the location, when present, is a span nested inside the
    title rather than a field of its own.
    """
    classes = ["ai1ec-event"]
    if event_id is not None:
        classes.append(f"ai1ec-event-id-{event_id}")
    if instance_id is not None:
        classes.append(f"ai1ec-event-instance-id-{instance_id}")
    end_attr = f' data-end="{end}"' if end is not None else ""
    loc_span = (
        f'<span class="ai1ec-event-location">@ {location}</span>'
        if location is not None
        else ""
    )
    time_div = (
        f'<div class="ai1ec-event-time">{time_text}</div>'
        if time_text is not None
        else ""
    )
    desc_div = (
        f'<div class="ai1ec-event-description"><p>{description}</p></div>'
        if description is not None
        else ""
    )
    link = (
        f'<a class="ai1ec-load-event" href="{href}">details</a>'
        if href is not None
        else ""
    )
    return (
        f'<div class="{" ".join(classes)}"{end_attr}>'
        f'<span class="ai1ec-event-title">{title}{loc_span}</span>'
        f"{time_div}{desc_div}{link}"
        f"</div>"
    )


def test_event_fields_are_extracted() -> None:
    """Every field the .ics carries comes off the agenda entry."""
    (ev,) = dcs.extract_events(_event_div(location="Sierra Bakehouse"))
    assert ev.instance_id == "27431"
    assert ev.event_id == "630674"
    assert ev.title == "Hill Workout"
    assert ev.location == "Sierra Bakehouse"
    assert ev.description == "Weekly hills."
    assert ev.url == "https://example.invalid/event/hill/?instance_id=27431"
    assert (ev.start.hour, ev.start.minute) == (18, 0)
    assert (ev.end.hour, ev.end.minute) == (19, 15)


def test_location_span_is_lifted_out_of_the_title() -> None:
    """The venue is its own .ics field, not part of the summary."""
    (ev,) = dcs.extract_events(
        _event_div(title="Tuesday Track", location="Truckee High Track")
    )
    assert ev.title == "Tuesday Track"
    assert ev.location == "Truckee High Track"


def test_at_sign_in_a_plain_title_is_left_alone() -> None:
    """Some entries name the venue in the title with no location span.

    Stripping on the character rather than the markup would truncate
    these, so the whole string has to survive as the summary.
    """
    title = "Tuesday Social Run @ Trout Creek Pocket"
    (ev,) = dcs.extract_events(_event_div(title=title, location=None))
    assert ev.title == title
    assert ev.location is None


def test_hyphen_separated_times_parse_too() -> None:
    """The separator is not guaranteed to be the en dash."""
    (ev,) = dcs.extract_events(
        _event_div(time_text="Sep 17 @ 6:00 pm - 7:15 pm")
    )
    assert (ev.start.hour, ev.start.minute) == (18, 0)


@pytest.mark.parametrize(
    "time_text",
    [None, "Sep 17", "all day", "6 pm onwards"],
    ids=["absent", "date_only", "all_day", "unparseable"],
)
def test_entry_with_no_readable_range_starts_at_midnight(
    time_text: str | None,
) -> None:
    """With no range to read, the start falls back to the end date's 00:00.

    The end timestamp is the only instant such an entry supplies, so
    the event is dated from it either way and keeps a start that
    precedes its end.
    """
    (ev,) = dcs.extract_events(_event_div(time_text=time_text))
    assert (ev.start.hour, ev.start.minute, ev.start.second) == (0, 0, 0)
    assert ev.start.date() == ev.end.date()
    assert ev.start <= ev.end


def test_overnight_event_starts_the_day_before_it_ends() -> None:
    """A range that wraps midnight is anchored off the end timestamp.

    Both clock times render against the end date, so a start later than
    the end means the event began the previous day.
    """
    (ev,) = dcs.extract_events(
        _event_div(
            end="2026-09-18T02:00:00-07:00",
            time_text=f"Sep 17 @ 10:00 pm {EN_DASH} 2:00 am",
        )
    )
    assert ev.start.hour == 22
    assert ev.start.date() < ev.end.date()
    assert ev.start < ev.end


def test_noon_and_midnight_clocks_convert() -> None:
    """12am is hour 0 and 12pm is hour 12, not 12 and 24."""
    assert dcs.parse_clock(12, 30, "am") == (0, 30)
    assert dcs.parse_clock(12, 30, "pm") == (12, 30)
    assert dcs.parse_clock(1, 5, "pm") == (13, 5)


def test_times_are_reanchored_to_the_named_zone() -> None:
    """The feed declares a TZID, so instants carry that zone, not an offset."""
    (ev,) = dcs.extract_events(_event_div())
    assert ev.start.tzinfo is dcs.EVENT_TZ
    assert ev.end.tzinfo is dcs.EVENT_TZ


@pytest.mark.parametrize(
    "div",
    [
        _event_div(instance_id=None),
        _event_div(event_id=None),
        _event_div(end=None),
    ],
    ids=["no_instance_id", "no_event_id", "no_end"],
)
def test_entries_missing_an_identifier_are_skipped(div: str) -> None:
    """A half-rendered entry is dropped rather than parsed into junk."""
    assert dcs.extract_events(div) == []


def test_unrelated_markup_yields_no_events() -> None:
    """The empty-scrape guard depends on a clean page parsing as zero."""
    assert dcs.extract_events("<html><body><p>hi</p></body></html>") == []


# ---------------------------------------------------------------------------
# Assembling the calendar
# ---------------------------------------------------------------------------


def _cal_event(
    instance_id: str,
    start: datetime,
    *,
    title: str = "Run",
    hours: int = 1,
) -> dcs.CalEvent:
    return dcs.CalEvent(
        instance_id=instance_id,
        event_id="630674",
        title=title,
        start=start,
        end=start + timedelta(hours=hours),
        location=None,
        description=None,
        url=None,
    )


def _at(year: int, month: int, day: int, hour: int = 18) -> datetime:
    return datetime(year, month, day, hour, tzinfo=dcs.EVENT_TZ)


def _summaries(ics: bytes) -> list[str]:
    """The SUMMARY values in file order.

    RFC 5545 separates lines with CRLF, so the captures are rstripped
    rather than matched to end of line.
    """
    found = re.findall(rb"^SUMMARY:(.*)$", ics, re.MULTILINE)
    return [value.decode().rstrip("\r") for value in found]


def test_events_are_emitted_in_start_order() -> None:
    """Subscribers read the feed in order, so the file is sorted."""
    ics = dcs.build_ics(
        [
            _cal_event("c", _at(2026, 9, 20), title="third"),
            _cal_event("a", _at(2026, 9, 18), title="first"),
            _cal_event("b", _at(2026, 9, 19), title="second"),
        ]
    )
    assert _summaries(ics) == ["first", "second", "third"]


def test_identical_input_produces_identical_bytes() -> None:
    """Rebuilding an unchanged calendar must not churn the published file."""
    events = [_cal_event("a", _at(2026, 9, 18))]
    assert dcs.build_ics(events) == dcs.build_ics(events)


def test_past_events_are_carried_across_a_rebuild() -> None:
    """The agenda only looks forward, so history lives in the old file."""
    cutoff = _at(2026, 9, 17, hour=0)
    old = dcs.build_ics(
        [_cal_event("gone", _at(2026, 9, 10), title="last week")]
    )
    past = dcs._past_vevents(old, cutoff)
    rebuilt = dcs.build_ics(
        [_cal_event("new", _at(2026, 9, 24), title="next week")], past=past
    )
    assert _summaries(rebuilt) == ["last week", "next week"]


def test_events_at_or_after_the_cutoff_are_not_preserved() -> None:
    """Anything the scrape still covers comes from the site, not the file.

    The cutoff is midnight of the day being scraped, and the scrape
    starts at that same day, so an event landing exactly on it is one
    the site will supply again. Preserving it too would let a stale
    copy outlive the entry it duplicates.
    """
    cutoff = _at(2026, 9, 17, hour=0)
    old = dcs.build_ics(
        [
            _cal_event("before", _at(2026, 9, 16)),
            _cal_event("oncutoff", _at(2026, 9, 17, hour=0)),
            _cal_event("after", _at(2026, 9, 18)),
        ]
    )
    preserved = {str(ve["uid"]) for ve in dcs._past_vevents(old, cutoff)}
    assert any("before" in uid for uid in preserved)
    assert not any("oncutoff" in uid for uid in preserved)
    assert not any("after" in uid for uid in preserved)


def test_a_rescraped_event_wins_over_its_preserved_copy() -> None:
    """The site is authoritative for any instance still in its window."""
    start = _at(2026, 9, 16)
    old = dcs.build_ics([_cal_event("dup", start, title="old name")])
    past = dcs._past_vevents(old, _at(2026, 9, 17, hour=0))
    rebuilt = dcs.build_ics(
        [_cal_event("dup", start, title="new name")], past=past
    )
    assert _summaries(rebuilt) == ["new name"]


def test_missing_previous_file_preserves_nothing() -> None:
    """A first run has no history, and must not fail reaching for it."""
    assert dcs._past_vevents(None, _at(2026, 9, 17, hour=0)) == []


def test_feed_declares_the_named_timezone() -> None:
    """Clients need the VTIMEZONE that the events' TZID refers to."""
    ics = dcs.build_ics([_cal_event("a", _at(2026, 9, 18))])
    assert b"BEGIN:VTIMEZONE" in ics
    assert b"TZID:America/Los_Angeles" in ics
    assert b"DTSTART;TZID=America/Los_Angeles:" in ics
