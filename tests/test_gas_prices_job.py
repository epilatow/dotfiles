"""Research validation and the agent-driven snapshot publication boundary."""

import fcntl
import hashlib
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from curl_cffi import requests as source_requests
from curl_cffi.requests.exceptions import CertificateVerifyError
from pydantic import BaseModel, TypeAdapter, ValidationError

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
sys.path.insert(
    0,
    str(
        Path(__file__).parents[1] / "files/local/libexec/gas-prices-breakdown"
    ),
)

from test_gas_prices_breakdown import (
    CODES,
    _add_snapshot_sources,
    _backups_under,
    _page,
    _snapshot_block,
    _tax_period,
)

import gas_prices_agent as job
import gas_prices_breakdown as gpb
from gas_prices_research import (
    Adjustment,
    AllocationInput,
    Auction,
    EvidenceTopic,
    ResearchData,
    ReviewOutcome,
    SourceEvidence,
    UnquantifiedFee,
    required_topics,
)

TARGET = date(2026, 9, 17)


class ProcessIdentity(BaseModel):
    pid: int
    pgid: int


def completed_research() -> ResearchData:
    data = gpb.research_template(TARGET)
    baseline = _tax_period()
    data.eia_tax_period = baseline.period
    data.eia_baseline_sha256 = gpb.tax_baseline_sha256(baseline)
    data.wa_ppt_rate = 0.0
    data.wa_ppt_source_url = "https://revenue.iowa.gov/"
    data.ny_sales_tax_usd_per_gal = 0.08
    data.ny_sales_tax_source_url = "https://revenue.iowa.gov/"
    active = {
        entry.state
        for entry in data.adjustments
        if entry.start <= TARGET <= entry.end
    }
    active.add("IN")
    for review in data.state_reviews:
        review.outcome = (
            ReviewOutcome.OVERRIDE
            if review.state in active
            else ReviewOutcome.NO_OVERRIDE
        )
        review.sources = ["https://revenue.iowa.gov/"]
        review.note = "Test fixture, not real research."
        review.evidence = [
            SourceEvidence(
                source_url=review.sources[0],
                excerpt="Test primary evidence for mocked gas-tax inputs.",
                topics=sorted(required_topics(review.state)),
            )
        ]
    return data


def write_research(path: Path, data: ResearchData) -> Path:
    path.write_text(data.model_dump_json(indent=2))
    return path


def test_seed_cannot_be_used_as_completed_research(tmp_path: Path) -> None:
    seed = write_research(
        tmp_path / "seed.json", gpb.research_template(TARGET)
    )
    with pytest.raises(gpb.SnapshotError, match="unresolved"):
        gpb.load_research(seed, TARGET)


def test_completed_research_does_not_authorize_an_unresearched_backfill(
    tmp_path: Path,
) -> None:
    path = write_research(tmp_path / "research.json", completed_research())
    with pytest.raises(gpb.SnapshotError, match="does not cover"):
        gpb.load_research(path, TARGET - timedelta(days=1))


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "unresolved",
        "contradiction",
        "nonprimary",
        "wrongyear",
        "expired",
        "future",
        "overlap",
    ],
)
def test_incomplete_or_inconsistent_research_is_refused(
    tmp_path: Path, defect: str
) -> None:
    data = completed_research()
    if defect == "missing":
        data.state_reviews.pop()
    elif defect == "duplicate":
        data.state_reviews[-1] = data.state_reviews[0]
    elif defect == "unresolved":
        data.state_reviews[0].outcome = ReviewOutcome.UNRESOLVED
    elif defect == "contradiction":
        next(
            r for r in data.state_reviews if r.state == "IN"
        ).outcome = ReviewOutcome.NO_OVERRIDE
    elif defect == "nonprimary":
        data.state_reviews[0].sources = ["https://example.com/a-news-story"]
    elif defect == "wrongyear":
        data.in_oil_inspection_source_url = (
            data.in_oil_inspection_source_url.replace("2026", "2025")
        )
    elif defect == "expired":
        data.checked_through = TARGET - timedelta(days=1)
    elif defect == "future":
        data.checked_through = datetime.now(
            UTC
        ).astimezone().date() + timedelta(days=1)
    else:
        data.adjustments.append(data.adjustments[0])
    path = write_research(tmp_path / "research.json", data)
    with pytest.raises(gpb.SnapshotError):
        gpb.load_research(path, TARGET)


def test_schema_rejects_unknown_fields_and_nonfinite_prices() -> None:
    encoded = completed_research().model_dump_json()
    with pytest.raises(ValidationError):
        ResearchData.model_validate_json(
            encoded.replace('"price":27.94', '"price":NaN')
        )
    with pytest.raises(ValidationError):
        ResearchData.model_validate_json(
            encoded[:-1] + ',"ignore_errors":true}'
        )


@pytest.mark.parametrize("defect", ["missing", "topic", "eia", "wa", "ny"])
def test_completed_reviews_require_primary_component_evidence(
    defect: str,
) -> None:
    data = completed_research()
    review = next(r for r in data.state_reviews if r.state == "NY")
    if defect == "missing":
        review.evidence.clear()
    elif defect == "topic":
        review.evidence[0].topics = [EvidenceTopic.COLLECTION]
    elif defect == "eia":
        url = "https://www.eia.gov/petroleum/"
        review.sources = [url]
        review.evidence[0].source_url = url
    elif defect == "wa":
        data.wa_ppt_rate = None
    else:
        data.ny_sales_tax_usd_per_gal = None
    with pytest.raises(ValueError):
        data.validate_for(TARGET, set(CODES))


@pytest.mark.parametrize("excerpt", [" " * 40, "tax" + " " * 40])
def test_padding_cannot_turn_an_empty_quote_into_evidence(
    excerpt: str,
) -> None:
    with pytest.raises(ValidationError):
        SourceEvidence(
            source_url="https://revenue.iowa.gov/",
            excerpt=excerpt,
            topics=[EvidenceTopic.COLLECTION],
        )


@pytest.mark.parametrize("curl_fails", [False, True])
def test_system_client_verifies_sources_when_bundled_tls_cannot(
    tmp_path: Path,
    curl_fails: bool,
) -> None:
    url = "https://www.legislature.ohio.gov/download?key=example"
    error = CertificateVerifyError("missing issuer")
    body = b"Verified primary collection statement for this test case."
    result = subprocess.CompletedProcess(
        ["curl"], 60 if curl_fails else 0, stdout=body, stderr=b""
    )
    with (
        patch.object(
            source_requests, "get", autospec=True, side_effect=error
        ) as get,
        patch.object(
            subprocess, "run", autospec=True, return_value=result
        ) as curl,
    ):
        if curl_fails:
            with pytest.raises(gpb.SnapshotError, match="curl exited 60"):
                gpb.fetch_source_document(url, tmp_path)
        else:
            document = gpb.fetch_source_document(url, tmp_path)
            assert document.text_path.read_bytes() == body
    get.assert_called_once_with(url, impersonate="chrome", timeout=30)
    argv = curl.call_args.args[0]
    assert argv[-1] == url and "--insecure" not in argv and "-k" not in argv
    assert argv[argv.index("--user-agent") + 1] == gpb.USER_AGENT


@pytest.mark.parametrize("mismatch", [False, True])
def test_validation_compares_the_baseline_before_evidence_or_prices(
    tmp_path: Path,
    mismatch: bool,
) -> None:
    data = completed_research()
    if mismatch:
        data.eia_baseline_sha256 = "0" * 64
    path = write_research(tmp_path / "research.json", data)
    with (
        _add_snapshot_sources(),
        patch.object(
            gpb, "fetch_source_document", wraps=gpb.fetch_source_document
        ) as evidence,
        patch.object(gpb, "fetch_aaa_retail") as prices,
    ):
        assert gpb.main(
            [
                "validate-research",
                str(path),
                "--target",
                TARGET.isoformat(),
                "--cache-dir",
                str(tmp_path),
            ]
        ) == int(mismatch)
    prices.assert_not_called()
    assert bool(evidence.call_count) == (not mismatch)


@pytest.mark.parametrize("rate", [0.0, 0.08])
def test_new_york_sales_tax_is_added_without_a_flat_adjustment(
    tmp_path: Path,
    rate: float,
) -> None:
    data = completed_research()
    data.ny_sales_tax_usd_per_gal = rate
    path = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(gpb.BASELINE_DATE, CODES)))
    with _backups_under(tmp_path), _add_snapshot_sources():
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(path),
                    "--cache-dir",
                    str(tmp_path),
                ]
            )
            == 0
        )
    block = gpb.find_block_for_date(
        gpb.parse_snapshots(html.read_text()).blocks, TARGET.isoformat()
    )
    assert block is not None
    ny = dict(gpb.split_state_blocks(block))["NY"]
    expected = _tax_period().per_state["NY"] + rate
    assert f"fixed:{{ total:{expected:.4f}" in ny
    assert "State motor-fuel sales tax" in ny
    assert gpb.NY_SALES_TAX is None


def test_evidence_is_refetched_and_shared_documents_are_read_once(
    tmp_path: Path,
) -> None:
    data = completed_research()
    text = data.state_reviews[0].evidence[0].excerpt.replace(" ", "\n")
    document = gpb.SourceDocument(
        data.state_reviews[0].sources[0], text, tmp_path / "source.txt"
    )
    with patch.object(
        gpb, "fetch_source_document", autospec=True, return_value=document
    ) as fetch:
        gpb.verify_research_evidence(data, tmp_path)
        fetch.assert_called_once_with(document.source_url, tmp_path)


@pytest.mark.parametrize("unreachable", [False, True])
def test_unverifiable_evidence_cannot_fetch_prices_or_change_the_page(
    tmp_path: Path,
    unreachable: bool,
) -> None:
    data = completed_research()
    path = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with (
        _backups_under(tmp_path),
        _add_snapshot_sources(),
        patch.object(
            gpb,
            "fetch_source_document",
            side_effect=gpb.SnapshotError("unreachable")
            if unreachable
            else None,
            return_value=gpb.SourceDocument(
                "https://revenue.iowa.gov/", "Different primary text", tmp_path
            ),
        ),
        patch.object(gpb, "fetch_aaa_retail") as prices,
    ):
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(path),
                    "--cache-dir",
                    str(tmp_path),
                ]
            )
            == 1
        )
    prices.assert_not_called()
    assert html.read_text() == original
    assert gpb.WA_PPT_RATE is None and gpb.RESEARCH_DATA is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            b"<html><script>wrong</script>"
            + b"<p>Gas <b>tax</b> collected.</p></html>",
            "Gas\ntax\ncollected.",
        ),
        (
            b'{"code":"<p>Inspection fee</p>","rate":0.01}',
            "code\nInspection fee\nrate\n0.01",
        ),
    ],
)
def test_primary_text_extraction_handles_markup_and_code_json(
    raw: bytes,
    expected: str,
) -> None:
    assert gpb._source_text(raw, "https://iga.in.gov/") == expected


@pytest.mark.parametrize("rate", [0.0, 0.003])
def test_researched_wa_tax_reaches_the_snapshot_and_only_fetches_if_active(
    tmp_path: Path,
    rate: float,
) -> None:
    data = completed_research()
    data.wa_ppt_rate = rate
    path = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(gpb.BASELINE_DATE, CODES)))
    with (
        _backups_under(tmp_path),
        _add_snapshot_sources(),
        patch.object(
            gpb,
            "load_spot_series",
            return_value={"2026-07": 3.2},
        ) as fetch,
    ):
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(path),
                    "--cache-dir",
                    str(tmp_path),
                ]
            )
            == 0
        )
    series = [call.args[0] for call in fetch.call_args_list]
    assert (gpb.EIA_SPOT_SERIES["WA"] in series) == (rate > 0)
    block = gpb.find_block_for_date(
        gpb.parse_snapshots(html.read_text()).blocks, TARGET.isoformat()
    )
    assert block is not None
    wa = dict(gpb.split_state_blocks(block))["WA"]
    assert "Petroleum products tax" in wa
    if rate > 0:
        assert "Los Angeles RBOB" in wa and "0.0096" in wa
    assert gpb.WA_PPT_RATE is None and gpb.RESEARCH_DATA is None


def test_validate_research_checks_freshness_without_fetching(
    tmp_path: Path,
) -> None:
    data = completed_research()
    data.carb_auctions = [
        Auction(day=date(2025, 1, 1), price=10.0, label="old")
    ]
    path = write_research(tmp_path / "research.json", data)
    with patch.object(gpb, "fetch_aaa_retail", autospec=True) as fetch:
        assert (
            gpb.main(
                [
                    "validate-research",
                    str(path),
                    "--target",
                    TARGET.isoformat(),
                ]
            )
            == 1
        )
    fetch.assert_not_called()


@pytest.mark.parametrize("fetch_fails", [False, True])
def test_research_changes_output_without_leaking_into_seed_tables(
    tmp_path: Path, fetch_fails: bool
) -> None:
    data = completed_research()
    data.in_oil_inspection_fee = 0.02
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(gpb.BASELINE_DATE, CODES)))
    original = html.read_text()
    with (
        _backups_under(tmp_path),
        _add_snapshot_sources(
            retail_error=gpb.FetchError("feed down") if fetch_fails else None
        ),
    ):
        code = gpb.main(
            [
                "add-snapshot",
                str(html),
                "--target",
                TARGET.isoformat(),
                "--research",
                str(research),
            ]
        )
    assert gpb.IN_OIL_INSPECTION_FEE == 0.01
    assert code == (1 if fetch_fails else 0)
    if fetch_fails:
        assert html.read_text() == original
    else:
        built = gpb.find_block_for_date(
            gpb.parse_snapshots(html.read_text()).blocks, TARGET.isoformat()
        )
        assert built is not None
        assert (
            "fixed:{ total:0.0200" in dict(gpb.split_state_blocks(built))["IN"]
        )


@pytest.mark.parametrize("agent", list(job.AgentCli))
@pytest.mark.parametrize("model", [None, "provider/model#variant"])
def test_agent_presets_pass_one_literal_prompt(
    agent: job.AgentCli, model: str | None, tmp_path: Path
) -> None:
    prompt = "Read this skill; {model}; $(touch unwanted); `exit 1`"
    command = job.agent_command(agent, None, prompt, tmp_path, model=model)
    assert command[0] == agent.value
    assert command.count(prompt) == 1
    if model is None:
        assert "--model" not in command
    else:
        position = command.index("--model")
        assert command[position + 1] == model
        assert position < command.index("--")


def test_custom_agent_command_is_argv_and_keeps_prompt_literal(
    tmp_path: Path,
) -> None:
    prompt = "{workspace} is literal inside this prompt; $(whoami)"
    command = job.agent_command(
        job.AgentCli.CLAUDE,
        '["other-agent", "--cwd", "{workspace}", "--prompt", "{prompt}"]',
        prompt,
        tmp_path,
    )
    assert command == [
        "other-agent",
        "--cwd",
        str(tmp_path),
        "--prompt",
        prompt,
    ]


def test_custom_agent_command_expands_the_selected_model(
    tmp_path: Path,
) -> None:
    prompt = "The {model} and {workspace} strings in this prompt are literal."
    command = job.agent_command(
        job.AgentCli.CLAUDE,
        '["other-agent", "--model={model}", "{prompt}"]',
        prompt,
        tmp_path,
        model="provider/model#variant",
    )
    assert command == ["other-agent", "--model=provider/model#variant", prompt]


@pytest.mark.parametrize(
    "custom, model",
    [
        (None, ""),
        (None, " "),
        ('["other-agent", "{prompt}"]', "sonnet"),
        ('["other-agent", "{model}", "{prompt}"]', None),
    ],
)
def test_invalid_model_configuration_is_refused(
    custom: str | None, model: str | None, tmp_path: Path
) -> None:
    with pytest.raises(job.AgentError):
        job.agent_command(
            job.AgentCli.CLAUDE, custom, "prompt", tmp_path, model=model
        )


def test_skill_frontmatter_is_a_prompt_not_a_cli_option(
    tmp_path: Path,
) -> None:
    prompt = "---\nname: update-gas-prices\n---\nResearch the snapshot."
    command = job.agent_command(job.AgentCli.CLAUDE, None, prompt, tmp_path)
    parser_program = (
        "import argparse,sys\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('-p', action='store_true')\n"
        "for flag in ('--permission-mode', '--permission-prompts', "
        "'--allowedTools', '--output-format'):\n"
        "    parser.add_argument(flag)\n"
        "for flag in ('--no-session-persistence', '--verbose'):\n"
        "    parser.add_argument(flag, action='store_true')\n"
        "parser.add_argument('prompt')\n"
        "sys.stdout.write(parser.parse_args().prompt)"
    )
    result = subprocess.run(
        [sys.executable, "-c", parser_program, *command[1:]],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == prompt


@pytest.mark.parametrize("fully_waived", [False, True])
def test_signed_corrections_and_a_zero_rate_build_valid_snapshots(
    tmp_path: Path, fully_waived: bool
) -> None:
    data = completed_research()
    base = _tax_period().per_state["TX"]
    delta = -base if fully_waived else 0.02
    data.adjustments.append(
        Adjustment(
            state="TX",
            start=TARGET,
            end=TARGET,
            usd_per_gal=delta,
            authority="Test collection notice",
            source_url="https://comptroller.texas.gov/",
        )
    )
    next(
        r for r in data.state_reviews if r.state == "TX"
    ).outcome = ReviewOutcome.OVERRIDE
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    html.write_text(_page(_snapshot_block(gpb.BASELINE_DATE, CODES)))
    with _backups_under(tmp_path), _add_snapshot_sources():
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(research),
                ]
            )
            == 0
        )
    block = gpb.find_block_for_date(
        gpb.parse_snapshots(html.read_text()).blocks, TARGET.isoformat()
    )
    assert block is not None
    state = dict(gpb.split_state_blocks(block))["TX"]
    assert f"fixed:{{ total:{base + delta:.4f}" in state
    assert "Tax or fee adjustment" in state


@pytest.mark.parametrize("period_changed", [False, True])
def test_a_changed_research_baseline_cannot_publish(
    tmp_path: Path, period_changed: bool
) -> None:
    data = completed_research()
    if period_changed:
        data.eia_tax_period = date(2026, 1, 1)
    else:
        data.eia_baseline_sha256 = "0" * 64
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with _backups_under(tmp_path), _add_snapshot_sources():
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(research),
                ]
            )
            == 1
        )
    assert html.read_text() == original
    assert gpb.RESEARCH_EIA_TAX_PERIOD is None
    assert gpb.RESEARCH_EIA_BASELINE_SHA256 is None


def test_known_unrepresented_inputs_stop_before_any_feed_fetch(
    tmp_path: Path,
) -> None:
    data = completed_research()
    data.blocking_issues = ["An effective charge cannot be represented."]
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with patch.object(gpb, "fetch_aaa_retail", autospec=True) as fetch:
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(research),
                ]
            )
            == 1
        )
    fetch.assert_not_called()
    assert html.read_text() == original


@pytest.mark.parametrize(
    ("state", "source"),
    [
        (
            "ME",
            "https://legislature.maine.gov/statutes/10/title10sec1681.html",
        ),
        (
            "ME",
            "https://www.legis.maine.gov/statutes/10/title10sec1681.html?v=1",
        ),
        (
            "OR",
            "https://www.oregon.gov/dor/programs/businesses/Pages/petroleum.aspx",
        ),
        ("TX", "https://comptroller.texas.gov/taxes/fuels/delivery-fee.php"),
    ],
)
def test_unallocatable_fee_cannot_publish_as_a_nominal_flat_correction(
    tmp_path: Path, state: str, source: str
) -> None:
    data = completed_research()
    data.adjustments.append(
        Adjustment(
            state=state,
            start=TARGET,
            end=TARGET,
            usd_per_gal=0.00004,
            authority="Nominal fee conversion",
            source_url=source,
        )
    )
    next(
        r for r in data.state_reviews if r.state == state
    ).outcome = ReviewOutcome.OVERRIDE
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with patch.object(gpb, "fetch_aaa_retail", autospec=True) as fetch:
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(research),
                ]
            )
            == 1
        )
    fetch.assert_not_called()
    assert html.read_text() == original


def test_published_prorated_fee_can_adjust_a_state_with_a_tank_charge(
    tmp_path: Path,
) -> None:
    data = completed_research()
    data.adjustments.append(
        Adjustment(
            state="MA",
            start=TARGET,
            end=TARGET,
            usd_per_gal=0.000393,
            authority="Published per-gallon delivery-fee rate difference",
            source_url="https://www.mass.gov/info-details/underground-storage-tank-program-ust",
        )
    )
    next(
        r for r in data.state_reviews if r.state == "MA"
    ).outcome = ReviewOutcome.OVERRIDE
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with _backups_under(tmp_path), _add_snapshot_sources():
        assert (
            gpb.main(
                [
                    "add-snapshot",
                    str(html),
                    "--target",
                    TARGET.isoformat(),
                    "--research",
                    str(research),
                ]
            )
            == 0
        )
    block = gpb.find_block_for_date(
        gpb.parse_snapshots(html.read_text()).blocks, TARGET.isoformat()
    )
    assert block is not None
    state = dict(gpb.split_state_blocks(block))["MA"]
    assert "fixed:{ total:0.3004" in state
    assert "Tax or fee adjustment" in state
    assert "Annual UST tank charges" in state
    gpb.verify_append(original, html.read_text(), TARGET)


@pytest.mark.parametrize("has_allocation_evidence", [False, True])
def test_additional_unquantified_fee_needs_evidence_and_preserves_value(
    tmp_path: Path, has_allocation_evidence: bool
) -> None:
    data = completed_research()
    review = next(r for r in data.state_reviews if r.state == "ID")
    review.unquantified_fees = [
        UnquantifiedFee(
            name="Test terminal delivery charge",
            source_url=review.sources[0],
            missing_input=AllocationInput.DELIVERY_VOLUME,
            reason="Actual delivery quantities are not in the sourced inputs.",
        )
    ]
    if has_allocation_evidence:
        review.evidence[0].topics.append(EvidenceTopic.FEE_ALLOCATION)
    research = write_research(tmp_path / "research.json", data)
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with _backups_under(tmp_path), _add_snapshot_sources():
        result = gpb.main(
            [
                "add-snapshot",
                str(html),
                "--target",
                TARGET.isoformat(),
                "--research",
                str(research),
            ]
        )
    if not has_allocation_evidence:
        assert result == 1
        assert html.read_text() == original
        return
    assert result == 0
    block = gpb.find_block_for_date(
        gpb.parse_snapshots(html.read_text()).blocks, TARGET.isoformat()
    )
    assert block is not None
    state = dict(gpb.split_state_blocks(block))["ID"]
    assert "fixed:{ total:0.3000" in state
    assert "Test terminal delivery charge" in state
    assert "Actual delivery quantities" in state
    assert "Tax or fee adjustment" not in state
    gpb.verify_append(original, html.read_text(), TARGET)


def test_baseline_command_exposes_the_selected_rates_and_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _add_snapshot_sources():
        assert (
            gpb.main(
                [
                    "research-template",
                    "--tax-baseline",
                    "--target",
                    TARGET.isoformat(),
                    "--cache-dir",
                    str(tmp_path),
                ]
            )
            == 0
        )
    baseline = TypeAdapter(gpb.TaxBaseline).validate_json(
        capsys.readouterr().out
    )
    expected = _tax_period()
    assert baseline["period"] == expected.period.isoformat()
    assert baseline["state_totals"] == expected.per_state
    assert baseline["sha256"] == gpb.tax_baseline_sha256(expected)
    assert "NY" in baseline["required_evidence_topics"]
    assert "WA" in baseline["computed_supplements"]
    assert "ME" in baseline["unquantified_exclusions"]
    assert "explicit proration" in baseline["fee_allocation_policy"]


def test_changed_eia_qualifications_change_the_research_identity() -> None:
    period = _tax_period()
    original = gpb.tax_baseline_sha256(period)
    period.notes["NY"] = "An additional statewide sales tax is excluded."
    assert gpb.tax_baseline_sha256(period) != original


def test_previous_research_provides_hints_without_claiming_new_coverage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    previous = write_research(tmp_path / "previous.json", completed_research())
    target = TARGET + timedelta(days=7)
    assert (
        gpb.main(
            [
                "research-template",
                "--previous-research",
                str(previous),
                "--target",
                target.isoformat(),
            ]
        )
        == 0
    )
    seed = ResearchData.model_validate_json(capsys.readouterr().out)
    assert seed.checked_from == seed.checked_through == target
    assert seed.eia_tax_period is None and seed.eia_baseline_sha256 is None
    assert seed.wa_ppt_rate is None
    assert seed.ny_sales_tax_usd_per_gal is None
    assert all(not r.evidence for r in seed.state_reviews)
    assert all(
        r.outcome == ReviewOutcome.UNRESOLVED for r in seed.state_reviews
    )
    assert all(
        r.sources and "Previous review" in r.note for r in seed.state_reviews
    )
    with pytest.raises(ValueError, match="unresolved"):
        seed.validate_for(target, set(CODES))


def test_partial_research_can_supply_hints_but_not_completed_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = completed_research()
    data.state_reviews = data.state_reviews[:1]
    data.blocking_issues = ["The other states were not collected."]
    previous = write_research(tmp_path / "previous.json", data)
    assert (
        gpb.main(
            [
                "research-template",
                "--previous-research",
                str(previous),
                "--target",
                TARGET.isoformat(),
            ]
        )
        == 0
    )
    seed = ResearchData.model_validate_json(capsys.readouterr().out)
    assert len(seed.state_reviews) == 51
    assert seed.state_reviews[0].sources == data.state_reviews[0].sources
    assert all(not r.evidence for r in seed.state_reviews)
    assert all(
        r.outcome == ReviewOutcome.UNRESOLVED for r in seed.state_reviews
    )


def test_previous_research_drops_a_nominal_fee_but_keeps_tax_windows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = completed_research()
    original_adjustments = data.adjustments.copy()
    data.adjustments.append(
        Adjustment(
            state="ME",
            start=TARGET,
            end=TARGET,
            usd_per_gal=0.00004,
            authority="Nominal annual Marketing Fund fee",
            source_url="https://legislature.maine.gov/statutes/10/title10sec1681.html",
        )
    )
    previous = write_research(tmp_path / "previous.json", data)
    assert (
        gpb.main(
            [
                "research-template",
                "--previous-research",
                str(previous),
                "--target",
                TARGET.isoformat(),
            ]
        )
        == 0
    )
    seed = ResearchData.model_validate_json(capsys.readouterr().out)
    assert seed.adjustments == original_adjustments
    assert all(
        r.outcome == ReviewOutcome.UNRESOLVED for r in seed.state_reviews
    )


def test_cancellation_reaps_a_child_that_ignores_sigterm(
    tmp_path: Path,
) -> None:
    ready = tmp_path / "ready"
    record = tmp_path / "agent-process.json"
    stderr = tmp_path / "supervisor.log"
    child_program = (
        "import os,signal,sys; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "Path(sys.argv[1]).write_text(str(os.getpid())); signal.pause()"
    )
    source_dir = (
        Path(__file__).parents[1] / "files/local/libexec/gas-prices-breakdown"
    )
    supervisor_program = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(source_dir)!r}); "
        "import gas_prices_agent as job; "
        "job.run_agent([sys.executable, '-c', sys.argv[1], sys.argv[2]], "
        "Path(sys.argv[3]))"
    )
    with (
        stderr.open("w") as output,
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                supervisor_program,
                child_program,
                str(ready),
                str(tmp_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=output,
            start_new_session=True,
        ) as supervisor,
    ):
        identity: ProcessIdentity | None = None
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if (
                    ready.exists()
                    and ready.stat().st_size
                    and record.exists()
                    and record.stat().st_size
                ):
                    break
                if supervisor.poll() is not None:
                    break
                time.sleep(0.02)
            assert ready.exists() and record.exists(), stderr.read_text()
            identity = ProcessIdentity.model_validate_json(record.read_bytes())
            assert identity.pid == int(ready.read_text())
            supervisor.send_signal(signal.SIGTERM)
            assert supervisor.wait(timeout=10) != 0
            with pytest.raises(ProcessLookupError):
                os.killpg(identity.pgid, 0)
        finally:
            if identity is None and ready.exists() and ready.stat().st_size:
                child_pid = int(ready.read_text())
                identity = ProcessIdentity(pid=child_pid, pgid=child_pid)
            if identity is not None:
                try:
                    os.killpg(identity.pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if supervisor.poll() is None:
                os.killpg(supervisor.pid, signal.SIGKILL)
                supervisor.wait()


@pytest.mark.parametrize(
    "custom",
    [
        '"claude -p prompt"',
        "[]",
        '["claude", 3]',
        '["claude", "-p"]',
        "not json",
    ],
)
def test_invalid_command_configuration_is_refused(
    custom: str, tmp_path: Path
) -> None:
    with pytest.raises(job.AgentError):
        job.agent_command(
            job.AgentCli.CLAUDE,
            custom,
            "prompt",
            tmp_path,
        )


def test_changed_live_input_is_preserved(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    html.write_text("changed by another writer")
    with pytest.raises(gpb.SnapshotError, match="changed while building"):
        gpb.publish_snapshot(html, "original", "prepared")
    assert html.read_text() == "changed by another writer"


def test_snapshot_update_refuses_an_overlapping_writer(tmp_path: Path) -> None:
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    state = tmp_path / ".local/state/gas-prices-breakdown"
    state.mkdir(parents=True)
    key = hashlib.sha256(str(html).encode()).hexdigest()
    with (
        _backups_under(tmp_path),
        (state / f"snapshot-{key}.lock").open("a") as lock,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch.object(gpb, "fetch_aaa_retail", autospec=True) as fetch:
            assert gpb.main(["add-snapshot", str(html)]) == 1
        fetch.assert_not_called()
    assert html.read_text() == original


def test_failed_atomic_replace_preserves_page_and_backup(
    tmp_path: Path,
) -> None:
    html = tmp_path / "page.html"
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    html.write_text(original)
    with (
        _backups_under(tmp_path),
        _add_snapshot_sources(),
        patch.object(
            os,
            "replace",
            autospec=True,
            side_effect=OSError("write failed"),
        ),
    ):
        assert (
            gpb.main(
                ["add-snapshot", str(html), "--target", TARGET.isoformat()]
            )
            == 1
        )
    assert html.read_text() == original
    backups = list(
        (tmp_path / ".local/state/gas-prices-breakdown").glob("backup-*.html")
    )
    assert len(backups) == 1
    assert backups[0].read_text() == original
    assert not list(tmp_path.glob(".gas-prices-*"))


def test_append_verifier_refuses_edits_to_history() -> None:
    original = _page(_snapshot_block(gpb.BASELINE_DATE, CODES))
    changed = _page(
        _snapshot_block(TARGET.isoformat(), CODES),
        _snapshot_block(gpb.BASELINE_DATE, CODES).replace("3.500", "4.000"),
    )
    with pytest.raises(gpb.SnapshotError, match="published history"):
        gpb.verify_append(original, changed, TARGET)
