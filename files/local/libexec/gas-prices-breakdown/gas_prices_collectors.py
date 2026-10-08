"""Parse maintained numeric inputs from their published primary sources."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from gas_prices_research import (
    Adjustment,
    Auction,
    EvidenceTopic,
    ResearchData,
    SourceEvidence,
)

NY_URL = "https://www.tax.ny.gov/forms/publications/st/pub718f.htm"
VT_URL = "https://dmv.vermont.gov/CVO/fuel-tax/mftia-mfta-quarterly-fees"
WA_URL = "https://dor.wa.gov/taxes-rates/other-taxes/petroleum-products-tax"
CARB_URL = (
    "https://ww2.arb.ca.gov/our-work/programs/cap-and-trade-program/"
    "auction-information"
)
CARB_SUMMARY_URL = (
    "https://ww2.arb.ca.gov/sites/default/files/2020-08/results_summary.pdf"
)
WA_AUCTIONS_URL = (
    "https://ecology.wa.gov/air-climate/climate-commitment-act/"
    "cap-and-invest/auctions-and-market"
)
MONTH = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)


class CollectionError(ValueError):
    pass


@dataclass(frozen=True)
class PrimaryDocument:
    url: str
    text: str
    links: tuple[tuple[str, str], ...] = ()


FetchDocument = Callable[[str], PrimaryDocument]


def normalized(text: str) -> str:
    return " ".join(text.split())


def calendar_day(value: str) -> date:
    return (
        datetime.strptime(value.strip(), "%B %d, %Y")
        .replace(tzinfo=UTC)
        .date()
    )


def match_required(pattern: str, text: str, name: str) -> re.Match[str]:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        raise CollectionError(f"{name}: published input no longer parses")
    return match


def new_york(document: PrimaryDocument, target: date) -> float:
    text = normalized(document.text)
    effective = match_required(
        rf"Effective ((?:{MONTH}) \d{{1,2}}, \d{{4}})", text, "NY date"
    )
    if calendar_day(effective[1]) > target:
        raise CollectionError("NY publication takes effect after target")
    rate = match_required(
        r"Motor fuel and diesel motor fuel\s+Jurisdiction\s+"
        r"Cents-per-gallon rate\s+New York State\s+"
        r"(\d+(?:\.\d+)?)\s+New York State/MCTD",
        text,
        "NY statewide gasoline sales tax",
    )
    return float(rate[1]) / 100


def vermont(
    document: PrimaryDocument, target: date
) -> tuple[float, date, date]:
    text = normalized(document.text)
    entries = re.findall(
        rf"\$(\d+\.\d+) \(({MONTH}) - ({MONTH}) (\d{{4}})\)", text
    )
    matching: list[float] = []
    start = end = target
    for amount, first, last, year in entries:
        start_day = calendar_day(f"{first} 1, {year}")
        last_month = calendar_day(f"{last} 1, {year}").month
        next_year = int(year) + (last_month == 12)
        next_month = last_month % 12 + 1
        end_day = date(next_year, next_month, 1) - timedelta(days=1)
        if start_day <= target <= end_day:
            matching.append(float(amount))
            start, end = start_day, end_day
    if len(matching) != 2:
        raise CollectionError("VT needs exactly two target-quarter amounts")
    # The fixed excise and licensing amounts are the reviewed components
    # outside these two published quarterly assessments.
    return 0.121 + 0.010 + sum(matching), start, end


def indiana_inspection(document: PrimaryDocument) -> float:
    text = normalized(document.text)
    match = match_required(
        r"fees for the inspection of gasoline or kerosene shall be at the "
        r"rate of [^$]+\(\$(\d+\.\d+)\) per barrel "
        r"\([^()]+\((\d+)\) gallons\)",
        text,
        "Indiana inspection fee",
    )
    return float(match[1]) / int(match[2])


def washington_ppt(document: PrimaryDocument, target: date) -> float:
    text = normalized(document.text)
    match = match_required(
        r"Oct\. 1, 2023, forward\s+\.?0\.3%\s+\(0\.0030\)",
        text,
        "WA stated PPT rate",
    )
    if target < date(2023, 10, 1):
        raise CollectionError("WA collector needs an earlier rate edition")
    return float(match[0].rsplit("(", 1)[1].rstrip(")"))


def auction_document(
    document: PrimaryDocument, fetch: FetchDocument
) -> PrimaryDocument:
    """Follow a publication summary's link to its actual auction report."""
    publication = re.search(r"(?<!\d)\d{7}(?!\d)", document.url)
    if publication:
        reports = {
            url
            for url, _label in document.links
            if url.lower().endswith(f"/{publication[0]}.pdf")
        }
        if len(reports) == 1:
            return fetch(reports.pop())
    return document


def auction_report(
    document: PrimaryDocument, target: date, *, washington: bool
) -> Auction:
    text = normalized(document.text)
    auction_date = match_required(
        rf"(?:auction of allowances on|on) "
        rf"((?:{MONTH}) \d{{1,2}}, \d{{4}})\. The auction",
        text,
        "auction date",
    )
    day = calendar_day(auction_date[1])
    publication = match_required(
        rf"(?:Issued on|Summary Results Report) "
        rf"((?:{MONTH}) \d{{1,2}}, \d{{4}})",
        text,
        "certified auction publication date",
    )
    if calendar_day(publication[1]) > target:
        raise CollectionError("auction result was not yet published on target")
    if washington:
        price = match_required(
            r"(?:Auction Settlement Price|Settlement Price)\s*"
            r"(?:USD\s*|\(USD\)\s*)?\$\s*(\d+\.\d+)",
            text,
            "WA auction settlement",
        )
    else:
        match_required(
            r"Auction Statistics Auction Auction Auction Auction USD CAD "
            r"USD CAD",
            text,
            "CARB current/advance currency columns",
        )
        price = match_required(
            r"Settlement Price\s+\$\s*(\d+\.\d+)\s+\$\d+\.\d+"
            r"\s+\$\d+\.\d+\s+\$\d+\.\d+",
            text,
            "CARB current-vintage USD settlement",
        )
    return Auction(
        day=day,
        price=float(price[1]),
        label=f"{'WA' if washington else 'CARB'} auction {day.isoformat()}",
    )


def append_evidence(
    data: ResearchData,
    state: str,
    document: PrimaryDocument,
    topic: EvidenceTopic,
) -> None:
    review = next(r for r in data.state_reviews if r.state == state)
    if document.url not in review.sources:
        review.sources.append(document.url)
    # The receipt retains the entire source. This excerpt is provenance for
    # the collector's input, rather than an assertion of an exhaustive audit.
    text = normalized(document.text)
    patterns = {
        EvidenceTopic.NY_SALES: (
            r"New York State\s+\d+(?:\.\d+)?\s+New York State/MCTD"
        ),
        EvidenceTopic.IN_INSPECTION: r"fees for the inspection of gasoline",
        EvidenceTopic.WA_PPT: r"What rate do I pay",
        EvidenceTopic.VT_QUARTERLY: r"\$\d+\.\d+ \(January - March",
        EvidenceTopic.COLLECTION: r"from \d+\.\d+% to \d+\.\d+%",
    }
    match = re.search(patterns[topic], text, re.IGNORECASE)
    start = max(0, match.start() - 100) if match else 0
    review.evidence.append(
        SourceEvidence(
            source_url=document.url,
            excerpt=text[start : start + 1900],
            topics=[topic],
        )
    )


def collect_maintained(
    data: ResearchData,
    target: date,
    state_totals: dict[str, float],
    fetch: FetchDocument,
) -> list[str]:
    """Collect known formats; retain explicit requests for unfamiliar ones."""
    pending: list[str] = []

    def collect(name: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except CollectionError as exc:
            pending.append(f"{name}: {exc}")

    def ny() -> None:
        document = fetch(NY_URL)
        data.ny_sales_tax_usd_per_gal = new_york(document, target)
        data.ny_sales_tax_source_url = document.url
        append_evidence(data, "NY", document, EvidenceTopic.NY_SALES)

    def vt() -> None:
        document = fetch(VT_URL)
        total, start, end = vermont(document, target)
        data.adjustments = [a for a in data.adjustments if a.state != "VT"]
        difference = total - state_totals["VT"]
        if abs(difference) > 0.000001:
            data.adjustments.append(
                Adjustment(
                    state="VT",
                    start=start,
                    end=end,
                    authority="Published quarterly MFTIA/MFTA assessments",
                    usd_per_gal=round(difference, 8),
                    source_url=document.url,
                )
            )
        append_evidence(data, "VT", document, EvidenceTopic.VT_QUARTERLY)

    def inspection() -> None:
        url = f"https://iga.in.gov/ic/{target.year}/Title_16/Article_44/Chapter_2.pdf"
        document = fetch(url)
        data.in_oil_inspection_fee = indiana_inspection(document)
        data.in_oil_inspection_source_url = url
        append_evidence(data, "IN", document, EvidenceTopic.IN_INSPECTION)

    def ppt() -> None:
        document = fetch(WA_URL)
        stated = washington_ppt(document, target)
        # A reviewed noncollection decision remains a separate dated fact.
        # The agency rate table alone cannot supersede such a decision.
        if data.wa_ppt_rate is None or data.wa_ppt_rate != 0:
            data.wa_ppt_rate = stated
            data.wa_ppt_source_url = document.url
        append_evidence(data, "WA", document, EvidenceTopic.WA_PPT)

    def auctions(washington: bool) -> None:
        landing = fetch(WA_AUCTIONS_URL if washington else CARB_URL)
        candidates = [
            url
            for url, label in landing.links
            if (
                (
                    washington
                    and "Summary Report" in label
                    and "APCR" not in label
                    and "ECR" not in label
                    and "Emissions Containment" not in label
                )
                or (not washington and "Summary Results Report" in label)
            )
        ]
        if not candidates:
            raise CollectionError("program page contains no result reports")
        entries: list[Auction] = []
        for url in candidates:
            document = auction_document(fetch(url), fetch)
            entries.append(
                auction_report(document, target, washington=washington)
            )
        table = data.wa_auctions if washington else data.carb_auctions
        for entry in entries:
            table[:] = [old for old in table if old.day != entry.day] + [entry]
        table.sort(key=lambda entry: entry.day)

    for name, operation in (
        ("NY sales tax", ny),
        ("VT quarter", vt),
        ("IN inspection", inspection),
        ("WA PPT", ppt),
        ("CARB auction", lambda: auctions(False)),
        ("WA auction", lambda: auctions(True)),
    ):
        collect(name, operation)
    return pending
