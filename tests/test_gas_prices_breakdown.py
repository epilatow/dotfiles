"""Tests for files/local/libexec/gas-prices-breakdown/gas-prices-breakdown."""

from __future__ import annotations

import contextlib
import gzip
import http.client
import re
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
import xlrd  # type: ignore[import-untyped]

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
        gpb._load_workbook(not_a_workbook, "OR CFP")
    assert "OR CFP" in str(caught.value)


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


AAA_TODAY = date(2026, 9, 17)


def _aaa_page(rows: str) -> str:
    return (
        f"<html>as of {AAA_TODAY.month}/{AAA_TODAY.day}/"
        f"{AAA_TODAY.year % 100:02d} "
        f'<table id="sortable"><tr><th>State</th></tr>{rows}</table>'
    )


def _aaa_row(state: str, price: str) -> str:
    return f'<tr><td><a href="#">{state}</a></td><td>${price}</td></tr>'


def test_aaa_missing_table_is_reported() -> None:
    """The page rendering without its table is a source failure."""
    with (
        patch.object(
            gpb,
            "_http_text",
            autospec=True,
            return_value="<html>as of 9/17/26 maintenance",
        ),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail(AAA_TODAY)
    assert "sortable table not found" in str(caught.value)


def test_aaa_short_table_is_reported() -> None:
    """A partial table would silently drop states from the snapshot."""
    page = _aaa_page(_aaa_row("California", "5.62"))
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail(AAA_TODAY)
    assert "expected 51" in str(caught.value)


def test_aaa_unknown_state_name_is_reported() -> None:
    """An unmapped row means the name column changed, not a new state."""
    page = _aaa_page(_aaa_row("Atlantis", "5.62"))
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail(AAA_TODAY)
    assert "unrecognized state" in str(caught.value)


def test_aaa_parses_every_mapped_state() -> None:
    """The happy path, at the full width the caller requires."""
    rows = "".join(_aaa_row(name, "3.50") for name in sorted(gpb.STATE_CODE))
    with patch.object(
        gpb, "_http_text", autospec=True, return_value=_aaa_page(rows)
    ):
        retail = gpb.fetch_aaa_retail(AAA_TODAY)
    assert len(retail) == 51
    assert retail["CA"] == 3.50


class _FakeSheet:
    """The two-column shape xlrd exposes for the monitor's export."""

    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = rows
        self.nrows = len(rows)
        self.ncols = max((len(r) for r in rows), default=0)

    def cell_value(self, row: int, col: int) -> object:
        cells = self._rows[row]
        return cells[col] if col < len(cells) else ""


class _FakeBook:
    def __init__(self, rows: list[list[object]]) -> None:
        self._sheet = _FakeSheet(rows)

    def sheet_by_index(self, index: int) -> _FakeSheet:
        assert index == 0
        return self._sheet


@contextlib.contextmanager
def _lcfs_export(rows: list[list[object]]) -> Iterator[None]:
    """Stand in for xlrd reading the downloaded export."""
    with patch.object(
        xlrd, "open_workbook", autospec=True, return_value=_FakeBook(rows)
    ):
        yield


@contextlib.contextmanager
def _lcfs_quotes(quotes: list[tuple[date, float]]) -> Iterator[None]:
    """Stand in for the monitor download and its parsed series."""
    with (
        patch.object(gpb, "_http_bytes", autospec=True, return_value=b"xls"),
        patch.object(
            gpb, "_read_lcfs_daily", autospec=True, return_value=quotes
        ),
    ):
        yield


def test_lcfs_uses_the_newest_quote_on_or_before_the_target(
    tmp_path: Path,
) -> None:
    """The assessment is daily, so the target's own quote is the one."""
    with _lcfs_quotes(
        [
            (date(2026, 9, 14), 84.50),
            (date(2026, 9, 15), 84.65),
            (date(2026, 9, 16), 84.75),
        ]
    ):
        quote = gpb.fetch_lcfs_for_target_date(date(2026, 9, 16), tmp_path)
    assert quote.as_of == date(2026, 9, 16)
    assert quote.usd_per_mt == 84.75


def test_lcfs_does_not_use_a_quote_from_after_the_target(
    tmp_path: Path,
) -> None:
    """Re-running an old snapshot must not reach for a later price."""
    with _lcfs_quotes(
        [(date(2026, 9, 14), 84.50), (date(2026, 9, 16), 84.75)]
    ):
        quote = gpb.fetch_lcfs_for_target_date(date(2026, 9, 15), tmp_path)
    assert quote.as_of == date(2026, 9, 14)


def test_lcfs_tolerates_a_weekend_gap(tmp_path: Path) -> None:
    """Quotes stop on non-trading days; that is not the source going quiet."""
    with _lcfs_quotes([(date(2026, 9, 11), 84.35)]):
        quote = gpb.fetch_lcfs_for_target_date(date(2026, 9, 14), tmp_path)
    assert quote.as_of == date(2026, 9, 11)


def test_lcfs_source_gone_quiet_fails_the_run(tmp_path: Path) -> None:
    """A source that stopped updating cannot describe the target date."""
    target = date(2026, 9, 17)
    stale = target - timedelta(days=gpb.LCFS_STALE_DAYS + 1)
    with (
        _lcfs_quotes([(stale, 71.96)]),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_lcfs_for_target_date(target, tmp_path)
    message = str(caught.value)
    assert "CA LCFS" in message
    assert "days old" in message


def test_lcfs_at_the_freshness_limit_still_answers(tmp_path: Path) -> None:
    """The bound is inclusive, so a run on the limit is not a failure."""
    target = date(2026, 9, 17)
    edge = target - timedelta(days=gpb.LCFS_STALE_DAYS)
    with _lcfs_quotes([(edge, 71.96)]):
        assert gpb.fetch_lcfs_for_target_date(target, tmp_path).as_of == edge


def test_lcfs_target_before_the_series_starts_is_reported(
    tmp_path: Path,
) -> None:
    """The export is a rolling window; older targets are off its front."""
    with (
        _lcfs_quotes([(date(2026, 9, 16), 84.75)]),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_lcfs_for_target_date(date(2026, 1, 5), tmp_path)
    assert "CA LCFS" in str(caught.value)


def test_lcfs_export_rows_are_read_in_date_order(tmp_path: Path) -> None:
    """The caller takes the last usable row, so order is load-bearing."""
    with _lcfs_export(
        [
            ["Date", "California LCFS Carbon Credit (USD/ton)"],
            ["2026-09-16", 84.75],
            ["2026-09-14", 84.50],
            ["2026-09-15", 84.65],
        ]
    ):
        assert gpb._read_lcfs_daily(tmp_path / "lcfs.xls") == [
            (date(2026, 9, 14), 84.50),
            (date(2026, 9, 15), 84.65),
            (date(2026, 9, 16), 84.75),
        ]


@pytest.mark.parametrize(
    "rows",
    [
        [["Date", "Price"]],
        [["Date", "Price"], ["not a date", 84.75]],
        [["Date", "Price"], ["2026-09-16", "n/a"]],
        [["2026-09-16"]],
        [],
    ],
    ids=["header_only", "bad_date", "bad_price", "missing_column", "empty"],
)
def test_lcfs_export_without_usable_rows_is_reported(
    tmp_path: Path, rows: list[list[object]]
) -> None:
    """A reshaped export must not read as an empty price series."""
    with (
        _lcfs_export(rows),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb._read_lcfs_daily(tmp_path / "lcfs.xls")
    assert "no dated rows" in str(caught.value)


def test_lcfs_export_that_is_not_a_workbook_is_reported(
    tmp_path: Path,
) -> None:
    """A source answering 200 with an error page is still bad input."""
    book = tmp_path / "lcfs.xls"
    book.write_text("<html>503 Service Unavailable</html>")
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb._read_lcfs_daily(book)
    assert "CA LCFS" in str(caught.value)


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


@pytest.mark.parametrize(
    "blob",
    [
        b"",
        b"<html>503 Service Unavailable</html>",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600,
    ],
    ids=["empty", "error_page", "corrupt_ole2"],
)
def test_lcfs_damaged_export_is_reported_not_raised(
    tmp_path: Path, blob: bytes
) -> None:
    """xlrd signals damage through several unrelated exception types.

    Only the innermost is an `XLRDError`; a corrupt container and a
    truncated transfer surface as other classes entirely, and any of
    them escaping would be a traceback where the tool promises one
    reported line.
    """
    book = tmp_path / "lcfs.xls"
    book.write_bytes(blob)
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb._read_lcfs_daily(book)
    assert "CA LCFS" in str(caught.value)


def test_lcfs_missing_export_is_reported_not_raised(tmp_path: Path) -> None:
    """A download that never landed is bad input, not a crash."""
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb._read_lcfs_daily(tmp_path / "never-written.xls")
    assert "CA LCFS" in str(caught.value)


def test_emitted_ca_nontax_fragment_is_well_formed() -> None:
    """The note is prose inside a quoted JS literal, so it has to escape.

    An unescaped quote or brace here would corrupt the snapshot array
    for every reader of the page, and the damage would not show up in
    any value this script checks.
    """
    fragment = gpb.build_ca_nontax(
        date(2026, 9, 17),
        gpb.LcfsQuote(date(2026, 9, 16), 84.75, "https://example.invalid"),
        gpb.AuctionSettlement(date(2026, 8, 19), 32.48, "Aug 2026 #48"),
    )
    assert fragment.count("{") == fragment.count("}")
    assert fragment.count("[") == fragment.count("]")
    # Every double quote must open or close a field, never sit loose
    # inside the prose.
    assert fragment.count('"') % 2 == 0
    for field in ("src:", "note:", "asOf:"):
        assert field in fragment
    note = re.search(r'note:"((?:[^"\\]|\\.)*)"', fragment)
    assert note is not None, "note field is not a parseable string literal"
    assert "Argus" in note.group(1)
    assert "not exact" in note.group(1)
    assert gpb.LCFS_LAST_CARB_WEEK.isoformat() in note.group(1)


# ---------------------------------------------------------------------------
# Freshness of the remaining live sources
# ---------------------------------------------------------------------------


def test_aaa_page_gone_stale_fails_the_run() -> None:
    """Frozen averages look identical to fresh ones without the date."""
    stale = AAA_TODAY - timedelta(days=gpb.AAA_STALE_DAYS + 1)
    page = (
        f"<html>as of {stale.month}/{stale.day}/{stale.year % 100:02d} "
        f'<table id="sortable"><tr><th>State</th></tr></table>'
    )
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail(AAA_TODAY)
    message = str(caught.value)
    assert "AAA" in message
    assert str(stale) in message


def test_aaa_page_without_an_as_of_date_is_reported() -> None:
    """The freshness check cannot be skipped just because the stamp moved."""
    rows = "".join(_aaa_row(name, "3.50") for name in sorted(gpb.STATE_CODE))
    page = f'<html><table id="sortable"><tr><th>S</th></tr>{rows}</table>'
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail(AAA_TODAY)
    assert "no 'as of' date" in str(caught.value)


def test_aaa_page_dated_within_the_limit_still_answers() -> None:
    """A weekend-old page is normal, not a failure."""
    recent = AAA_TODAY - timedelta(days=gpb.AAA_STALE_DAYS)
    rows = "".join(_aaa_row(name, "3.50") for name in sorted(gpb.STATE_CODE))
    page = (
        f"<html>as of {recent.month}/{recent.day}/{recent.year % 100:02d} "
        f'<table id="sortable"><tr><th>S</th></tr>{rows}</table>'
    )
    with patch.object(gpb, "_http_text", autospec=True, return_value=page):
        assert len(gpb.fetch_aaa_retail(AAA_TODAY)) == 51


def test_or_cfp_source_gone_quiet_fails_the_run(tmp_path: Path) -> None:
    """DEQ publishing nothing new must not read as an unchanged market."""
    with (
        _or_cfp_sources({(2025, 1): 120.0}),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_or_cfp_for_target_date(date(2026, 9, 17), tmp_path)
    message = str(caught.value)
    assert "OR CFP" in message
    assert "days before" in message


def test_or_cfp_normal_publication_lag_is_not_stale(tmp_path: Path) -> None:
    """The bound has to clear the widest gap the +2 month rule produces."""
    # Aug becomes available Oct 1, so a Sep 30 run still has to accept
    # July -- the longest a correctly-published month is ever behind.
    with _or_cfp_sources({(2026, 7): 161.01}):
        month = gpb.fetch_or_cfp_for_target_date(date(2026, 9, 30), tmp_path)
    assert month.year_month == "2026-07"


def test_aaa_page_from_after_the_target_fails_the_run() -> None:
    """Backfilling must not take today's prices for a past date.

    The page serves only current averages, so a run for an old target
    would otherwise stamp a months-old snapshot with this morning's
    numbers while its notes claim they are the target's.
    """
    ahead = AAA_TODAY + timedelta(days=gpb.AAA_STALE_DAYS + 1)
    rows = "".join(_aaa_row(name, "3.50") for name in sorted(gpb.STATE_CODE))
    page = (
        f"<html>as of {ahead.month}/{ahead.day}/{ahead.year % 100:02d} "
        f'<table id="sortable"><tr><th>S</th></tr>{rows}</table>'
    )
    with (
        patch.object(gpb, "_http_text", autospec=True, return_value=page),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_aaa_retail(AAA_TODAY)
    message = str(caught.value)
    assert "AAA" in message
    assert "after" in message


def test_aaa_page_slightly_ahead_of_the_target_is_fine() -> None:
    """A catch-up run days later is normal and must still publish."""
    ahead = AAA_TODAY + timedelta(days=gpb.AAA_STALE_DAYS)
    rows = "".join(_aaa_row(name, "3.50") for name in sorted(gpb.STATE_CODE))
    page = (
        f"<html>as of {ahead.month}/{ahead.day}/{ahead.year % 100:02d} "
        f'<table id="sortable"><tr><th>S</th></tr>{rows}</table>'
    )
    with patch.object(gpb, "_http_text", autospec=True, return_value=page):
        assert len(gpb.fetch_aaa_retail(AAA_TODAY)) == 51


@pytest.mark.parametrize(
    "stamp", ["as of 13/45/26", "as of 2/30/26"], ids=["month", "day"]
)
def test_aaa_unparseable_date_is_reported(stamp: str) -> None:
    """A date-shaped string that is not a date must not reach the check."""
    with pytest.raises(gpb.SnapshotError) as caught:
        gpb._aaa_as_of(f"<html>{stamp} <table id='sortable'></table>")
    assert "unreadable" in str(caught.value)


def test_or_cfp_at_the_freshness_limit_still_answers(tmp_path: Path) -> None:
    """The bound is inclusive, so a run on the limit is not a failure.

    Age is measured from the first of the published month, so the target
    is derived from the month rather than the other way round.
    """
    month = date(2026, 5, 1)
    target = month + timedelta(days=gpb.OR_CFP_STALE_DAYS)
    with _or_cfp_sources({(month.year, month.month): 150.0}):
        got = gpb.fetch_or_cfp_for_target_date(target, tmp_path)
    assert got.year_month == "2026-05"


def test_or_cfp_one_day_past_the_limit_fails(tmp_path: Path) -> None:
    """Pins the constant itself, not merely some value far outside it."""
    month = date(2026, 5, 1)
    target = month + timedelta(days=gpb.OR_CFP_STALE_DAYS + 1)
    with (
        _or_cfp_sources({(month.year, month.month): 150.0}),
        pytest.raises(gpb.SnapshotError) as caught,
    ):
        gpb.fetch_or_cfp_for_target_date(target, tmp_path)
    assert "OR CFP" in str(caught.value)
