"""Collection checkpoints, structured agent outcomes and publication."""

import hashlib
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import TypeAdapter

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(
    0,
    str(
        Path(__file__).parents[1] / "files/local/libexec/gas-prices-breakdown"
    ),
)

from test_gas_prices_breakdown import (
    CODES,
    _backups_under,
    _page,
    _sample_sources,
    _snapshot_block,
    _tax_period,
)
from test_gas_prices_job import TARGET, completed_research

import gas_prices_breakdown as gpb
import gas_prices_collectors as collectors


def collected() -> gpb.CollectedSnapshot:
    lcfs, _cca, _wa, orm = _sample_sources()
    start, end = gpb.pat_quarter(TARGET)
    return gpb.CollectedSnapshot(
        target=TARGET,
        collected_at=datetime(2026, 9, 17, tzinfo=UTC),
        retail=dict.fromkeys(CODES, 3.5),
        period=_tax_period(),
        in_gut=gpb.InGutRate(date(2026, 9, 1), 0.239, "https://www.in.gov/"),
        spot={
            code: gpb.SpotQuote("2026-07", 3.222, series)
            for code, series in gpb.EIA_SPOT_SERIES.items()
        },
        lcfs=lcfs,
        orm=orm,
        pat=gpb.PatQuote(start, end, start, 3.041, gpb.OH_PAT_URL),
        research=completed_research(),
    )


def receipt(
    url: str, _target: date, _cache: Path
) -> collectors.PrimaryDocument:
    return collectors.PrimaryDocument(
        url, "Test primary evidence for mocked gas-tax inputs."
    )


@pytest.mark.parametrize("harness_exit", [0, 7])
@pytest.mark.parametrize(
    "outcome", ["success", "failure", "malformed", "missing"]
)
@pytest.mark.parametrize("dry_run", [False, True])
def test_blob_owns_outcome_and_utility_owns_publication(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    harness_exit: int,
    outcome: str,
    dry_run: bool,
) -> None:
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    state = tmp_path / "state"
    inputs = tmp_path / "shared-inputs.json"
    inputs.write_text(collected().model_dump_json(indent=2) + "\n")

    def amend(_command: list[str], workspace: Path) -> int:
        path = workspace / "amended.json"
        if outcome == "missing":
            path.unlink()
        elif outcome == "malformed":
            path.write_text('{"status": "success"}')
        else:
            result = gpb.AmendedSnapshot.model_validate_json(path.read_bytes())
            result.status = gpb.AmendmentStatus(outcome)
            result.explanation = (
                "Known sourced inputs need no further amendments."
                if outcome == "success"
                else "Conflicting applicable tax notices prevent this update."
            )
            path.write_text(result.model_dump_json(indent=2) + "\n")
        return harness_exit

    argv = [
        "add-snapshot",
        str(html),
        "--agent",
        "claude",
        "--model",
        "sonnet",
        "--target",
        str(TARGET),
        "--inputs",
        str(inputs),
        "--state-dir",
        str(state),
    ]
    if dry_run:
        argv.append("--dry-run")
    with (
        _backups_under(tmp_path),
        patch.object(
            gpb, "run_agent", autospec=True, side_effect=amend
        ) as agent,
        patch.object(
            gpb, "collect_primary", autospec=True, side_effect=receipt
        ),
        patch.object(gpb, "fetch_aaa_retail", autospec=True) as fetch,
    ):
        assert gpb.main(argv) == (0 if outcome == "success" else 1)
    command = agent.call_args.args[0]
    assert command[0] == "claude"
    assert command[command.index("--model") + 1] == "sonnet"
    fetch.assert_not_called()
    run = next((state / "runs").iterdir())
    assert (run / "collected.json").exists()
    if outcome == "success":
        assert (run / "final.json").exists()
        assert (state / "last-final.json").exists()
        gpb.verify_append(
            original, (run / "prepared.html").read_text(), TARGET
        )
        if dry_run:
            assert html.read_text() == original
        else:
            assert html.read_text() == (run / "prepared.html").read_text()
    else:
        assert html.read_text() == original
        assert (run / "failure.json").exists()
        assert not (run / "prepared.html").exists()
        assert not (state / "last-final.json").exists()
        if outcome == "failure":
            assert "Conflicting applicable tax notices" in caplog.text
            assert (run / "agent-result.json").exists()


def test_collection_failure_precedes_agent(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(gpb.BASELINE_DATE, CODES)))
    state = tmp_path / "state"
    with (
        _backups_under(tmp_path),
        patch.object(
            gpb,
            "collect_snapshot_inputs",
            autospec=True,
            side_effect=gpb.FetchError("LCFS download failed"),
        ),
        patch.object(gpb, "run_agent", autospec=True) as agent,
    ):
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    str(TARGET),
                    "--state-dir",
                    str(state),
                ]
            )
            == 1
        )
    agent.assert_not_called()
    run = next((state / "runs").iterdir())
    assert "LCFS download failed" in (run / "failure.json").read_text()


def test_completed_amendment_is_reused_after_publication_failure(
    tmp_path: Path,
) -> None:
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(gpb.BASELINE_DATE, CODES)))
    state = tmp_path / "state"

    def amend(_command: list[str], workspace: Path) -> int:
        path = workspace / "amended.json"
        result = gpb.AmendedSnapshot.model_validate_json(path.read_bytes())
        result.status = gpb.AmendmentStatus.SUCCESS
        result.explanation = (
            "Retained rules and published inputs require no changes."
        )
        path.write_text(result.model_dump_json(indent=2) + "\n")
        return 0

    argv = [
        "add-snapshot",
        str(html),
        "--target",
        str(TARGET),
        "--state-dir",
        str(state),
    ]
    with (
        _backups_under(tmp_path),
        patch.object(
            gpb,
            "collect_snapshot_inputs",
            autospec=True,
            return_value=collected(),
        ) as collect,
        patch.object(
            gpb, "run_agent", autospec=True, side_effect=amend
        ) as agent,
        patch.object(
            gpb, "collect_primary", autospec=True, side_effect=receipt
        ),
    ):
        with patch.object(
            gpb,
            "publish_snapshot",
            autospec=True,
            side_effect=OSError("publication unavailable"),
        ):
            assert gpb.main(argv) == 1
        assert gpb.main(argv) == 0
    assert collect.call_count == 1
    assert agent.call_count == 1


def test_checkpoint_survives_a_later_collection_failure(
    tmp_path: Path,
) -> None:
    adapter = TypeAdapter(dict[str, float])
    first = {"CA": 4.123}
    with patch.object(
        gpb, "fetch_aaa_retail", autospec=True, return_value=first
    ) as fetch:
        assert (
            gpb.checkpoint_value(
                tmp_path,
                "retail",
                adapter,
                lambda: gpb.fetch_aaa_retail(TARGET),
            )
            == first
        )
        with pytest.raises(gpb.FetchError):
            gpb.checkpoint_value(
                tmp_path, "later", adapter, lambda: fail_collection()
            )
        assert (
            gpb.checkpoint_value(
                tmp_path,
                "retail",
                adapter,
                lambda: gpb.fetch_aaa_retail(TARGET),
            )
            == first
        )
    fetch.assert_called_once()


def fail_collection() -> dict[str, float]:
    raise gpb.FetchError("later feed failed")


def test_amended_inputs_are_bound_and_unexplained_price_edits_fail(
    tmp_path: Path,
) -> None:
    inputs = collected()
    digest = hashlib.sha256(
        (inputs.model_dump_json(indent=2) + "\n").encode()
    ).hexdigest()
    final = inputs.model_copy(deep=True)
    final.retail["CA"] = 4.5
    result = gpb.AmendedSnapshot(
        status=gpb.AmendmentStatus.SUCCESS,
        explanation="Corrected California's price from the primary source.",
        input_sha256=digest,
        data=final,
    )
    with pytest.raises(gpb.SnapshotError, match="amendment lacks"):
        gpb.validate_amended_data(result, inputs, digest, tmp_path)
    result.input_sha256 = "0" * 64
    with pytest.raises(gpb.SnapshotError, match="different collected inputs"):
        gpb.validate_amended_data(result, inputs, digest, tmp_path)


@pytest.mark.parametrize(
    "url", [gpb.AAA_URL, "https://tax.example.gov/temporary-notice"]
)
def test_amendment_receipt_survives_a_source_disappearing_on_retry(
    tmp_path: Path,
    url: str,
) -> None:
    inputs = collected()
    digest = hashlib.sha256(
        (inputs.model_dump_json(indent=2) + "\n").encode()
    ).hexdigest()
    final = inputs.model_copy(deep=True)
    final.retail["CA"] = 4.5
    excerpt = "California's published regular gasoline price is $4.50."
    result = gpb.AmendedSnapshot(
        status=gpb.AmendmentStatus.SUCCESS,
        explanation="Corrected California's price from the primary source.",
        input_sha256=digest,
        data=final,
        amendments=[
            gpb.DataAmendment(
                field="/retail/CA",
                reason="The primary source establishes the corrected price.",
                source_url=url,
                excerpt=excerpt,
            )
        ],
    )
    with patch.object(
        gpb,
        "fetch_source_bytes",
        autospec=True,
        side_effect=[excerpt.encode(), gpb.SnapshotError("source removed")],
    ) as fetch:
        for _ in range(2):
            assert (
                gpb.validate_amended_data(result, inputs, digest, tmp_path)
                == final
            )
    fetch.assert_called_once_with(url)


def test_already_published_snapshot_skips_collection_and_agent(
    tmp_path: Path,
) -> None:
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(str(TARGET), CODES)))
    with (
        _backups_under(tmp_path),
        patch.object(gpb, "collect_snapshot_inputs", autospec=True) as collect,
        patch.object(gpb, "run_agent", autospec=True) as agent,
    ):
        assert (
            gpb.main(["add-snapshot", str(html), "--target", str(TARGET)]) == 0
        )
    collect.assert_not_called()
    agent.assert_not_called()


def test_numeric_collectors_keep_units_and_products() -> None:
    ny = collectors.PrimaryDocument(
        collectors.NY_URL,
        "Effective September 1, 2026 Motor fuel and diesel motor fuel "
        "Jurisdiction Cents-per-gallon rate "
        "New York State 8 New York State/MCTD 8.75 "
        "B20 biodiesel New York State 6 New York State/MCTD 6.6",
    )
    assert collectors.new_york(ny, TARGET) == 0.08
    inspection = collectors.PrimaryDocument(
        "https://iga.in.gov/ic/2026/x.pdf",
        "fees for the inspection of gasoline or kerosene shall be at the "
        "rate of fifty cents ($0.50) per barrel (fifty (50) gallons)",
    )
    assert collectors.indiana_inspection(inspection) == 0.01
    vt = collectors.PrimaryDocument(
        collectors.VT_URL,
        "$0.0691 (October - December 2026) $0.1383 (October - December 2026)",
    )
    total, start, end = collectors.vermont(vt, date(2026, 10, 12))
    assert total == pytest.approx(0.3384)
    assert (start, end) == (date(2026, 10, 1), date(2026, 12, 31))


def test_auction_collector_selects_current_usd_and_publication_date() -> None:
    document = collectors.PrimaryDocument(
        "https://ww2.arb.ca.gov/report.pdf",
        "held an auction on August 19, 2026. The auction included allowances. "
        "Summary Results Report August 26, 2026 "
        "Auction Statistics Auction Auction Auction Auction USD CAD USD CAD "
        "Settlement Price $32.48 $45.11 $32.75 $45.49",
    )
    result = collectors.auction_report(document, TARGET, washington=False)
    assert result.price == 32.48
    with pytest.raises(collectors.CollectionError, match="not yet published"):
        collectors.auction_report(
            document, date(2026, 8, 20), washington=False
        )


def test_auction_publication_summary_follows_its_report() -> None:
    url = "https://apps.ecology.wa.gov/publications/SummaryPages/2614063.html"
    pdf = "https://apps.ecology.wa.gov/publications/documents/2614063.pdf"
    landing = collectors.PrimaryDocument(
        url, "Publication Summary", ((pdf, "View now"),)
    )
    report = collectors.PrimaryDocument(pdf, "Auction report")
    with patch.object(
        gpb, "collect_primary", autospec=True, return_value=report
    ) as fetch:
        result = collectors.auction_document(
            landing, lambda u: fetch(u, TARGET, Path("cache"))
        )
    assert result == report
    fetch.assert_called_once_with(pdf, TARGET, Path("cache"))


def test_retained_evidence_does_not_redownload_a_temporary_source(
    tmp_path: Path,
) -> None:
    data = completed_research()
    with patch.object(
        gpb,
        "collect_primary",
        autospec=True,
        side_effect=gpb.FetchError("temporary source gone"),
    ) as fetch:
        gpb.verify_collected_evidence(
            data, data.model_copy(deep=True), TARGET, tmp_path
        )
    fetch.assert_not_called()
