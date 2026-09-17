"""Tests for files/local/libexec/gas-prices-breakdown/gas-prices-breakdown."""

from __future__ import annotations

import contextlib
import gzip
import http.client
import subprocess
import sys
import time
import urllib.error
import zipfile
from datetime import date, timedelta
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


# ---------------------------------------------------------------------------
# Source content that stopped matching
# ---------------------------------------------------------------------------
#
# Each source is scraped out of a page or workbook whose shape the
# publisher can change without notice. A run that cannot find what it
# needs has to say so and leave the snapshot alone, because the
# alternative is writing a plausible-looking number nobody can trace.


def _aaa_page(rows: str) -> str:
    return f'<html><table id="sortable"><tr><th>State</th></tr>{rows}</table>'


def _aaa_row(state: str, price: str) -> str:
    return f'<tr><td><a href="#">{state}</a></td><td>${price}</td></tr>'


def test_aaa_missing_table_is_reported() -> None:
    """The page rendering without its table is a source failure."""
    with (
        patch.object(
            gpb, "_http_text", autospec=True, return_value="<html>maintenance"
        ),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail()
    assert "sortable table not found" in str(caught.value)


def test_aaa_short_table_is_reported() -> None:
    """A partial table would silently drop states from the snapshot."""
    page = _aaa_page(_aaa_row("California", "5.62"))
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail()
    assert "expected 51" in str(caught.value)


def test_aaa_unknown_state_name_is_reported() -> None:
    """An unmapped row means the name column changed, not a new state."""
    page = _aaa_page(_aaa_row("Atlantis", "5.62"))
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail()
    assert "unrecognized state" in str(caught.value)


def test_aaa_parses_every_mapped_state() -> None:
    """The happy path, at the full width the caller requires."""
    rows = "".join(_aaa_row(name, "3.50") for name in sorted(gpb.STATE_CODE))
    with patch.object(
        gpb, "_http_text", autospec=True, return_value=_aaa_page(rows)
    ):
        retail = gpb.fetch_aaa_retail()
    assert len(retail) == 51
    assert retail["CA"] == 3.50


def test_lcfs_landing_without_an_xlsx_link_is_reported(
    tmp_path: Path,
) -> None:
    """CARB serving anything but the report index stops the run cleanly.

    The link is discovered by pattern on every run rather than pinned,
    so a page that renders without one -- an interstitial, an outage
    notice -- has to surface as a source failure.
    """
    with (
        patch.object(
            gpb,
            "_http_text",
            autospec=True,
            return_value="<html><body>No reports here</body></html>",
        ),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_lcfs_for_target_date(date(2026, 8, 7), tmp_path)
    assert "xlsx link not found" in str(caught.value)


def test_lcfs_relative_link_resolves_against_the_carb_host(
    tmp_path: Path,
) -> None:
    """CARB publishes the href site-relative, so it needs a scheme and host."""
    href = "/sites/default/files/2026-07/Weekly%20LCFS%20Credit.xlsx"
    landing = f'<html><a href="{href}">report</a></html>'
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=landing),
        patch.object(
            gpb, "_http_bytes", autospec=True, return_value=b"xlsx"
        ) as fetched,
        patch.object(
            gpb,
            "_read_lcfs_weekly",
            autospec=True,
            return_value=[(date(2026, 7, 13), 72.61)],
        ),
    ):
        week = gpb.fetch_lcfs_for_target_date(date(2026, 8, 7), tmp_path)
    assert fetched.call_args.args[0] == "https://ww2.arb.ca.gov" + href
    assert week.source_xlsx_url.startswith("https://ww2.arb.ca.gov/")
    assert week.vwap_per_mt == 72.61


def test_lcfs_picks_the_newest_published_week(tmp_path: Path) -> None:
    """A week counts only once its report has had time to be published.

    The rows run oldest first, as the workbook's own sheet order does;
    the selection stops at the first week past the cutoff rather than
    scanning the rest, so feeding it any other order would exercise
    something the reader never produces.
    """
    weeks = [
        (date(2026, 7, 6), 70.0),
        (date(2026, 7, 13), 72.61),
        (date(2026, 7, 20), 75.0),
    ]
    landing = '<html><a href="https://x.invalid/Weekly.xlsx">r</a></html>'
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=landing),
        patch.object(gpb, "_http_bytes", autospec=True, return_value=b"xlsx"),
        patch.object(
            gpb, "_read_lcfs_weekly", autospec=True, return_value=weeks
        ),
    ):
        # Target is 8 days past the 13th and 1 day past the 20th, so the
        # 20th is not yet reportable and the 13th is the newest usable.
        week = gpb.fetch_lcfs_for_target_date(date(2026, 7, 21), tmp_path)
    assert week.monday == date(2026, 7, 13)


def test_lcfs_workbook_with_no_reportable_week_is_reported(
    tmp_path: Path,
) -> None:
    """Every week in the workbook still being unpublishable is a failure.

    The same publication lag that picks the newest usable week can
    disqualify all of them, and a run that cannot name a week has to
    say so rather than reach for one whose report is not out yet.
    """
    landing = '<html><a href="https://x.invalid/Weekly.xlsx">r</a></html>'
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=landing),
        patch.object(gpb, "_http_bytes", autospec=True, return_value=b"xlsx"),
        patch.object(
            gpb,
            "_read_lcfs_weekly",
            autospec=True,
            return_value=[(date(2026, 7, 20), 75.0)],
        ),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_lcfs_for_target_date(date(2026, 7, 21), tmp_path)
    assert "no week with monday" in str(caught.value)


@contextlib.contextmanager
def _or_cfp_sources(
    monthly: dict[tuple[int, int], float],
) -> Iterator[None]:
    """Stand in for the DEQ download and the workbook read."""
    with (
        patch.object(gpb, "_http_bytes", autospec=True, return_value=b"xlsx"),
        patch.object(
            gpb, "_read_or_cfp_monthly", autospec=True, return_value=monthly
        ),
    ):
        yield


def test_or_cfp_picks_the_newest_published_month(tmp_path: Path) -> None:
    """DEQ publishes month M by the end of M+1, so M+2 is when it counts."""
    with _or_cfp_sources(
        {(2026, 5): 150.0, (2026, 6): 155.0, (2026, 7): 161.01}
    ):
        # July becomes available 2026-09-01, so a run the day before
        # still has to settle for June.
        month = gpb.fetch_or_cfp_for_target_date(date(2026, 8, 31), tmp_path)
    assert month.year_month == "2026-06"
    assert month.vwap_per_credit == 155.0


@pytest.mark.parametrize(
    ("year_month", "available_on"),
    [
        ((2026, 1), date(2026, 3, 1)),
        ((2026, 10), date(2026, 12, 1)),
        ((2026, 11), date(2027, 1, 1)),
        ((2026, 12), date(2027, 2, 1)),
    ],
    ids=["jan", "oct", "nov", "dec"],
)
def test_or_cfp_availability_crosses_the_year_boundary(
    tmp_path: Path, year_month: tuple[int, int], available_on: date
) -> None:
    """November and December land in the next year, and must not wrap wrong.

    The month-plus-two arithmetic is the one place a year rollover can
    silently shift a value by twelve months, so each boundary month is
    pinned at the day it becomes usable and the day before.
    """
    year, month = year_month
    with _or_cfp_sources({year_month: 99.0}):
        on_the_day = gpb.fetch_or_cfp_for_target_date(available_on, tmp_path)
    assert on_the_day.year_month == f"{year}-{month:02d}"

    day_before = available_on - timedelta(days=1)
    with (
        _or_cfp_sources({year_month: 99.0}),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_or_cfp_for_target_date(day_before, tmp_path)
    assert "no monthly value available" in str(caught.value)


def test_or_cfp_workbook_with_nothing_published_yet_is_reported(
    tmp_path: Path,
) -> None:
    """A workbook whose months are all too recent cannot answer the date."""
    with (
        _or_cfp_sources({(2026, 7): 161.01}),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_or_cfp_for_target_date(date(2026, 8, 1), tmp_path)
    assert "no monthly value available" in str(caught.value)


# ---------------------------------------------------------------------------
# Hand-maintained auction tables
# ---------------------------------------------------------------------------
#
# These are the only inputs a human has to top up, which makes a missed
# update the likeliest way a wrong number reaches the page: the lookup
# keeps answering with the last entry, and nothing about that looks like
# a failure.

AUCTIONS = [
    (date(2026, 2, 18), 27.94, "Feb 2026 #46"),
    (date(2026, 5, 20), 28.81, "May 2026 #47"),
    (date(2026, 8, 19), 32.48, "Aug 2026 #48"),
]


def test_auction_is_not_used_before_its_results_publish() -> None:
    """A settlement is unknowable until it is certified a week later."""
    lag = gpb.CCA_PUBLICATION_LAG_DAYS
    auction = date(2026, 8, 19)
    day_before = gpb.latest_auction(
        AUCTIONS, auction + timedelta(days=lag - 1), program="T"
    )
    assert day_before.label == "May 2026 #47"
    on_publication = gpb.latest_auction(
        AUCTIONS, auction + timedelta(days=lag), program="T"
    )
    assert on_publication.label == "Aug 2026 #48"


def test_stale_auction_table_fails_the_run() -> None:
    """An un-topped-up table must not keep answering with its last entry."""
    target = date(2026, 8, 19) + timedelta(days=gpb.CCA_STALE_DAYS + 1)
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb.latest_auction(AUCTIONS, target, program="WA CCA")
    message = str(caught.value)
    assert "WA CCA" in message
    assert "days old" in message


def test_auction_table_inside_the_limit_still_answers() -> None:
    """The bound has to tolerate a normal quarterly gap."""
    target = date(2026, 8, 19) + timedelta(days=gpb.CCA_STALE_DAYS)
    assert gpb.latest_auction(AUCTIONS, target, program="T").price == 32.48


def test_target_before_any_published_auction_is_reported() -> None:
    """Nothing to fall back on is a source failure, not a silent zero."""
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb.latest_auction(AUCTIONS, date(2026, 1, 1), program="CARB CCA")
    assert "CARB CCA" in str(caught.value)


@pytest.mark.parametrize("name", sorted(gpb.CCA_AUCTION_TABLES))
def test_shipped_tables_are_ordered_and_unique(name: str) -> None:
    """The lookup walks the table in order and keeps the last match."""
    table = gpb.CCA_AUCTION_TABLES[name]
    dates = [row[0] for row in table]
    assert dates == sorted(dates), f"{name} is out of order"
    assert len(set(dates)) == len(dates), f"{name} has a duplicate date"
    assert all(row[1] > 0 for row in table), f"{name} has a bad price"
