"""Validated research inputs for the snapshot utility and maintenance skill."""

from datetime import UTC, date, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class ReviewOutcome(StrEnum):
    NO_OVERRIDE = "no-override"
    OVERRIDE = "override"
    UNRESOLVED = "unresolved"


class EvidenceTopic(StrEnum):
    COLLECTION = "collection"
    IN_INSPECTION = "indiana-inspection"
    NY_SALES = "new-york-state-sales"
    VT_QUARTERLY = "vermont-quarterly-assessments"
    DC_INDEXING = "dc-annual-indexing"
    OR_FULL_RATE = "oregon-complete-rate"
    WA_PPT = "washington-petroleum-products"
    FEE_ALLOCATION = "unquantified-fee-allocation"


FEE_ALLOCATION_POLICY = (
    "Include fees with a published per-gallon rate, a continuous defined-"
    "volume conversion, explicit proration or matched public allocation "
    "data. Exclude and disclose "
    "only charges whose per-gallon allocation needs unavailable load "
    "sizes, product mix or throughput. A missing source for an otherwise "
    "calculable rate is a data gap, not an allocation exclusion."
)


def excluded_fee_source(state: str, url: str) -> bool:
    """Identify specific charges without an approved per-gallon allocation."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").removeprefix("www.")
    path = parsed.path.rstrip("/").lower()
    if state == "ME":
        return (
            host == "maine.gov" or host.endswith(".maine.gov")
        ) and path.endswith("/statutes/10/title10sec1681.html")
    sources = {
        "OR": (
            "oregon.gov",
            "/dor/programs/businesses/pages/petroleum.aspx",
        ),
        "TX": (
            "comptroller.texas.gov",
            "/taxes/fuels/delivery-fee.php",
        ),
    }
    return sources.get(state) == (host, path)


class AllocationInput(StrEnum):
    DELIVERY_VOLUME = "delivery-volume"
    PRODUCT_MIX = "product-mix"
    ANNUAL_THROUGHPUT = "annual-throughput"
    FACILITY_THROUGHPUT = "facility-throughput"


class UnquantifiedFee(ResearchModel):
    name: str = Field(min_length=3, max_length=160)
    source_url: str
    missing_input: AllocationInput
    reason: str = Field(min_length=20, max_length=1000)

    @model_validator(mode="after")
    def meaningful_description(self) -> Self:
        if (
            len(" ".join(self.name.split())) < 3
            or len(" ".join(self.reason.split())) < 20
        ):
            raise ValueError(
                "unquantified fee needs a name and allocation explanation"
            )
        return self


REQUIRED_EVIDENCE = {
    "IN": EvidenceTopic.IN_INSPECTION,
    "NY": EvidenceTopic.NY_SALES,
    "VT": EvidenceTopic.VT_QUARTERLY,
    "DC": EvidenceTopic.DC_INDEXING,
    "OR": EvidenceTopic.OR_FULL_RATE,
    "WA": EvidenceTopic.WA_PPT,
}


def required_topics(state: str) -> set[EvidenceTopic]:
    topics = {EvidenceTopic.COLLECTION}
    if state in REQUIRED_EVIDENCE:
        topics.add(REQUIRED_EVIDENCE[state])
    return topics


def official_url(value: str) -> bool:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and (
            host.endswith((".gov", ".us", ".floridarevenue.com"))
            or host == "floridarevenue.com"
            or (
                host == "content.govdelivery.com"
                and parsed.path.startswith("/accounts/")
            )
        )
    )


class SourceEvidence(ResearchModel):
    source_url: str
    excerpt: str = Field(min_length=40, max_length=2000)
    topics: list[EvidenceTopic] = Field(min_length=1)

    @model_validator(mode="after")
    def unpadded_excerpt(self) -> Self:
        if len(" ".join(self.excerpt.split())) < 40:
            raise ValueError("excerpt needs 40 characters after normalization")
        return self


class StateReview(ResearchModel):
    state: str
    outcome: ReviewOutcome = ReviewOutcome.UNRESOLVED
    sources: list[str] = Field(default_factory=list)
    note: str = ""
    evidence: list[SourceEvidence] = Field(default_factory=list)
    unquantified_fees: list[UnquantifiedFee] = Field(default_factory=list)


class Suspension(ResearchModel):
    start: date
    end: date
    authority: str = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_window(self) -> Self:
        if self.start > self.end:
            raise ValueError("suspension starts after it ends")
        return self


class Adjustment(Suspension):
    state: str
    usd_per_gal: float = Field(
        description="Verified fixed-dollar correction per gallon. "
        "Do not estimate volume-dependent fees using assumed load sizes.",
    )
    source_url: str

    @model_validator(mode="after")
    def nonzero_correction(self) -> Self:
        if self.usd_per_gal == 0:
            raise ValueError("an adjustment must change the collected rate")
        return self


class Auction(ResearchModel):
    day: date
    price: float = Field(gt=0)
    label: str = Field(min_length=1)


class DatedRate(ResearchModel):
    day: date
    rate: float = Field(ge=0, le=1)


class ResearchData(ResearchModel):
    checked_from: date
    checked_through: date
    eia_tax_period: date | None = None
    eia_baseline_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    blocking_issues: list[str] = Field(default_factory=list)
    state_reviews: list[StateReview]
    adjustments: list[Adjustment]
    in_excise_suspensions: list[Suspension]
    in_gut_suspensions: list[Suspension]
    in_oil_inspection_fee: float = Field(ge=0, le=1)
    in_oil_inspection_source_url: str
    ny_sales_tax_usd_per_gal: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Collected statewide motor-fuel sales tax excluded "
        "from EIA, in dollars per gallon. Exclude the MCTD increment. "
        "Zero is verified noncollection; null is unresolved.",
    )
    ny_sales_tax_source_url: str = ""
    wa_ppt_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Effective collected fraction of wholesale value, "
        "not percentage units. Zero is verified noncollection; "
        "null is unresolved.",
    )
    wa_ppt_source_url: str = ""
    carb_auctions: list[Auction] = Field(min_length=1)
    wa_auctions: list[Auction] = Field(min_length=1)
    de_hsca_rates: list[DatedRate] = Field(min_length=1)
    auction_sources: list[str] = Field(min_length=2)
    de_hsca_source_url: str

    def validate_for(
        self,
        day: date,
        codes: set[str],
        *,
        baseline_states: frozenset[str] = frozenset(),
    ) -> None:
        """Require complete, internally consistent coverage for this date.

        This checks shape and consistency. The utility separately retrieves
        and checks exact excerpts; legal interpretations remain research
        assertions rather than machine-proved conclusions.
        """
        if self.blocking_issues:
            raise ValueError(
                f"research has blocking issues: {self.blocking_issues}"
            )
        if not self.checked_from <= day <= self.checked_through:
            raise ValueError(f"research does not cover {day}")
        if self.checked_through > datetime.now(UTC).astimezone().date():
            raise ValueError("research cannot assert future coverage")
        if self.checked_from.year != self.checked_through.year:
            raise ValueError("one Indiana code citation covers only one year")
        if not any(
            part in self.in_oil_inspection_source_url
            for part in (f"/laws/{day.year}/", f"/ic/{day.year}/")
        ):
            raise ValueError("Indiana inspection citation has the wrong year")
        states = [review.state for review in self.state_reviews]
        if set(states) != codes or len(states) != len(codes):
            raise ValueError("research needs one review for each of 51 states")
        active = {
            entry.state
            for entry in self.adjustments
            if entry.start <= day <= entry.end
        }
        if any(
            window.start <= day <= window.end
            for window in (
                *self.in_excise_suspensions,
                *self.in_gut_suspensions,
            )
        ):
            active.add("IN")
        for review in self.state_reviews:
            if review.outcome == ReviewOutcome.UNRESOLVED:
                raise ValueError(f"{review.state}: research is unresolved")
            if not review.sources or not review.note.strip():
                raise ValueError(f"{review.state}: review lacks evidence")
            if any(not official_url(url) for url in review.sources):
                raise ValueError(f"{review.state}: use primary state sources")
            topics: set[EvidenceTopic] = set()
            for evidence in review.evidence:
                if (
                    not official_url(evidence.source_url)
                    or evidence.source_url not in review.sources
                ):
                    raise ValueError(
                        f"{review.state}: evidence must cite a review source"
                    )
                host = urlsplit(evidence.source_url).hostname or ""
                if EvidenceTopic.COLLECTION in evidence.topics and (
                    host == "eia.gov" or host.endswith(".eia.gov")
                ):
                    raise ValueError(
                        f"{review.state}: EIA cannot establish collection"
                    )
                topics.update(evidence.topics)
            required = required_topics(review.state)
            if review.state not in baseline_states and not required <= topics:
                raise ValueError(
                    f"{review.state}: missing primary evidence for "
                    f"{sorted(required - topics)}"
                )
            names = [fee.name.casefold() for fee in review.unquantified_fees]
            if len(names) != len(set(names)):
                raise ValueError(f"{review.state}: duplicate unquantified fee")
            for fee in review.unquantified_fees:
                if (
                    not official_url(fee.source_url)
                    or fee.source_url not in review.sources
                    or not any(
                        item.source_url == fee.source_url
                        and EvidenceTopic.FEE_ALLOCATION in item.topics
                        for item in review.evidence
                    )
                ):
                    raise ValueError(
                        f"{review.state}: unquantified fee lacks primary "
                        "allocation evidence"
                    )
            if (review.outcome == ReviewOutcome.OVERRIDE) != (
                review.state in active
            ):
                raise ValueError(
                    f"{review.state}: review and windows disagree"
                )
        if self.eia_tax_period is None or self.eia_baseline_sha256 is None:
            raise ValueError("the EIA tax baseline is unresolved")
        if self.ny_sales_tax_usd_per_gal is None:
            raise ValueError("NY statewide motor-fuel sales tax is unresolved")
        ny_review = next(r for r in self.state_reviews if r.state == "NY")
        if "NY" not in baseline_states and not any(
            e.source_url == self.ny_sales_tax_source_url
            and EvidenceTopic.NY_SALES in e.topics
            for e in ny_review.evidence
        ):
            raise ValueError("NY motor-fuel sales tax lacks evidence")
        if self.wa_ppt_rate is None:
            raise ValueError("WA petroleum products collection is unresolved")
        wa_review = next(r for r in self.state_reviews if r.state == "WA")
        if "WA" not in baseline_states and not any(
            e.source_url == self.wa_ppt_source_url
            and EvidenceTopic.WA_PPT in e.topics
            for e in wa_review.evidence
        ):
            raise ValueError("WA petroleum products rate lacks evidence")
        if (
            self.eia_tax_period > day
            or self.eia_tax_period.day != 1
            or self.eia_tax_period.month not in (1, 7)
        ):
            raise ValueError("invalid EIA tax baseline period")
        windows: dict[str, list[Suspension]] = {
            "IN excise": self.in_excise_suspensions,
            "IN use tax": self.in_gut_suspensions,
        }
        for entry in self.adjustments:
            if entry.state not in codes or entry.state == "IN":
                raise ValueError(f"unsupported flat adjustment: {entry.state}")
            if excluded_fee_source(entry.state, entry.source_url):
                raise ValueError(
                    f"{entry.state}: excluded fee cannot supply a flat "
                    "per-gallon adjustment"
                )
            if not official_url(entry.source_url):
                raise ValueError(
                    f"{entry.state}: use a primary override source"
                )
            windows.setdefault(entry.state, []).append(entry)
        for state, entries in windows.items():
            ordered = sorted(entries, key=lambda entry: entry.start)
            if any(
                left.end >= right.start for left, right in pairwise(ordered)
            ):
                raise ValueError(f"{state}: overlapping suspension windows")
        for name, days in (
            ("CARB auctions", [entry.day for entry in self.carb_auctions]),
            ("WA auctions", [entry.day for entry in self.wa_auctions]),
            ("DE rates", [entry.day for entry in self.de_hsca_rates]),
        ):
            if days != sorted(set(days)):
                raise ValueError(f"{name}: dates must be unique and ascending")
        if any(
            entry.day.month != 1 or entry.day.day != 1
            for entry in self.de_hsca_rates
        ):
            raise ValueError("Delaware rates must take effect on January 1")
        sources = [
            self.in_oil_inspection_source_url,
            self.de_hsca_source_url,
            self.wa_ppt_source_url,
            self.ny_sales_tax_source_url,
            *self.auction_sources,
        ]
        if any(not official_url(url) for url in sources):
            raise ValueError(
                "inspection, auction, NY, WA and DE sources must be primary"
            )
