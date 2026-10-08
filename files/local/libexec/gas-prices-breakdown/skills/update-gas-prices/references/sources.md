# Gasoline research sources

Use this guide for pending inputs and applicable changes during the amendment
pass. The utility supplies downloaded data and source receipts; do not repeat
its collection or independently transcribe every jurisdiction. The links below
are starting points for affected inputs. Select the applicable edition and
effective period, following the latest-supported-rate policy.

## Evidence and scope

Use `research-source URL [URL ...] --cache-dir CACHE` to retrieve documents and
obtain paths to readable text. Read that text and record exact, contiguous
excerpts in the state's `evidence`, with the appropriate schema topics. The
utility uses independently collected source receipts or retrieves new cited
documents during validation. Whitespace is normalized; do not paraphrase,
insert ellipses or quote search summaries instead of the retained text.

New priced tax amendments need primary evidence. Agency rate tables,
filing/collection notices, applicable statutes and executive orders can
establish them. Check qualifications and read the relevant provision, including
amendment and uncodified notes. Use bill history to distinguish proposals from
enacted changes. Unchanged EIA inputs and retained rules do not require new
51-state primary-source quotations for each run.

Keep regular gasoline separate from diesel, aviation fuel and blend waivers.
The page excludes local, county and geographically limited taxes. Reconcile
statewide taxes and fees with EIA's notes and the utility's computed
supplements. Apply the [fee-allocation audit](fee-allocation.md): include fees
when sourced information supports their per-gallon value; omit and disclose
only those needing unavailable allocation inputs. A fee's name or annual
billing schedule alone does not determine eligibility. A missing source for an
included rate remains unresolved and blocks generation.

A blocked page cannot establish a rate or change. Use another primary endpoint
for required evidence. A forecast or study projection does not establish an
effective change. Do not infer a previous successful review from the HTML
history. Retained rules and source receipts are supplied context; their
applicable effective periods matter more than publication age. Check subsequent
applicable changes rather than demanding new confirmation of collection.

## Required component checks

- **Indiana (`indiana-inspection`):** the current code is a JavaScript site.
  Retrieve the chapter PDF at
  `https://iga.in.gov/ic/YEAR/Title_16/Article_44/Chapter_2.pdf` and read
  16-44-2-18. The Title_16.json endpoint is only an index and cannot establish
  the fee amount. Cite the target-year chapter directly. Check excise and
  gasoline use-tax collection separately in DOR notices and executive orders.
- **New York (`new-york-state-sales`):** compare Publication 908's excise,
  testing and petroleum-business-tax components with EIA, then separately
  verify statewide motor-fuel sales tax in Publication 718-F. EIA's additional
  sales-tax qualification matters: do not confuse the excise with the separate
  sales tax or assume EIA's "Other" column includes it. Supply the collected
  statewide sales tax in `ny_sales_tax_usd_per_gal` and its primary citation in
  `ny_sales_tax_source_url`; the utility adds it. Exclude MCTD and local rates.
- **Vermont (`vermont-quarterly-assessments`):** both MFTIA and MFTA change by
  quarter. Read the target quarter's pair, include fixed per-gallon components,
  and compare the full amount with EIA. The workbook can carry earlier-quarter
  assessments even on a July sheet.
- **DC (`dc-annual-indexing`):** October 1 starts a new fiscal/tax year. A
  published rate must be distinguished from a derived annual adjustment. Read
  D.C. Code 47-2301 and 47-2302 with OTR's latest stated rate. Use a statutory
  calculation only when its formula, input period and rounding are established
  by primary sources, and label it as derived. Matching older determinations
  cannot supply a missing rule. BLS's public All Items file is
  `https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems`; retain the
  specified Washington-area series and annual-average rows. Apply the skill's
  latest-supported-rate policy when no supported later amount is available.
  OTR's Motor Fuel Notices links can contain a newer published fiscal-year
  amount than its summary table. If a register notice serves its document via a
  "View text" ASP.NET form postback, retrieve that document as part of the
  agent's review. The index title alone cannot establish its numeric amount.
  Preserve the downloaded document and use a text converter for a legacy Word
  notice; do not label a CPI reconstruction as a published amount without
  reading the actual published notice. For the result's numeric citation, use
  the direct notice attachment linked from the register issue's notice listing
  (`DownloadFile` query), or a directly downloadable official issue PDF. Check
  its text with `research-source`. That command retrieves the cited URL without
  executing page forms; the NoticeDetail index is sufficient only for its own
  metadata.
- **Oregon (`oregon-complete-rate`):** start with ODOT's collected gasoline
  rate. ORS 319.020's base amount is qualified by the uncodified note following
  it, including subsequent conditional increases. A base amount alone cannot
  justify reducing EIA's complete rate. Check later legislation and referendum
  effects on the target date.
- **Washington (`washington-petroleum-products`):** PPT is separate from the
  motor-fuel excise, hazardous-substance/oil-spill taxes and carbon auctions.
  RCW 82.23A.020 makes collection conditional on quarterly unrestricted PLIA
  account balances and prior-quarter collection status. Start with DOR's dated
  rate and check for subsequent effective suspension or reinstatement
  decisions. The trigger does not itself establish a suspension. Set
  `wa_ppt_rate` to the effective decimal fraction, zero for verified
  noncollection, or null while unresolved. Cite the rate evidence in
  `wa_ppt_source_url`. The utility computes PPT against its disclosed West
  Coast spot benchmark; do not also add a flat PPT correction. Keep the last
  supported rate if no later applicable change is found; do not require a fresh
  quarterly notice. Study projections and forecast assumptions cannot establish
  a change.

The baseline's known exclusions need unavailable delivery, product-mix or
throughput allocations. Their supported state inputs remain publishable.
Maine's annual Petroleum Marketing Fund fee is in this group: do not add its
nominal $0.00004/gal conversion. Its calculable oil-import fee remains
included. Louisiana, Massachusetts, Missouri and New Mexico have load-related
fees with published per-gallon equivalents or statutory conversion rules;
retain those components. Separate facility charges are excluded only where a
per-gallon allocation is unavailable. See the audit for the primary sources and
details.

## Primary starting points by jurisdiction

- AL:
  [Revenue motor-fuel rates](https://www.revenue.alabama.gov/business-license/motor-fuels-tax-rates/).
- AK: [Current statutes](https://www.akleg.gov/basis/statutes.asp), AS
  43.40.010.
- AZ:
  [ADOT fuel tax](https://azdot.gov/motor-vehicles/professional-services/fuel-tax-information).
- AR: [DFA](https://www.dfa.arkansas.gov/), target-year motor-fuel
  announcement.
- CA:
  [CDTFA fuel-tax publications](https://cdtfa.ca.gov/taxes-and-fees/fuel-tax-rates.htm).
- CO:
  [Fuel tax and fee components](https://tax.colorado.gov/fuel-tax-and-fee-rates).
- CT: [Current Chapter 221](https://www.cga.ct.gov/current/pub/chap_221.htm)
  and [DRS](https://portal.ct.gov/drs).
- DE:
  [Title 30, Chapter 51](https://delcode.delaware.gov/title30/c051/index.html);
  separately check the annual HSCA notice.
- DC:
  [OTR motor-vehicle fuel tax](https://otr.cfo.dc.gov/page/motor-vehicle-fuel-tax),
  [47-2301](https://code.dccouncil.gov/us/dc/council/code/sections/47-2301),
  [47-2302](https://code.dccouncil.gov/us/dc/council/code/sections/47-2302).
- FL:
  [DOR fuel-tax instructions](https://floridarevenue.com/taxes/taxesfees/Pages/fuel.aspx)
  and [current statutes](https://www.flsenate.gov/Laws/Statutes), Chapter 206.
- GA: [DOR motor-fuel tax](https://dor.georgia.gov/motor-fuel-tax), suspension
  FAQs, and [governor orders](https://gov.georgia.gov/).
- HI:
  [HRS 243-4](https://www.capitol.hawaii.gov/hrscurrent/Vol04_Ch0201-0257/HRS0243/HRS_0243-0004.htm)
  and [GET](https://tax.hawaii.gov/geninfo/get/).
- ID:
  [Distributor rates](https://tax.idaho.gov/taxes/product-excise-taxes/fuels-taxes-and-fees/distributor-fuels/tax-rate/)
  and
  [transfer fee](https://tax.idaho.gov/taxes/product-excise-taxes/fuels-taxes-and-fees/distributor-fuels/distributors-and-the-transfer-fee/).
- IL:
  [IDOR motor-fuel guidance](https://tax.illinois.gov/research/taxinformation/motorfuel.html),
  current-year bulletins and [enacted laws](https://ilga.gov/).
- IN:
  [Gasoline use-tax notices](https://www.in.gov/dor/i-am-a/business-corp/gasoline-use-tax/)
  and [executive orders](https://www.in.gov/gov/newsroom/executive-orders/);
  use the chapter PDF above for inspection.
- IA: [Iowa Revenue](https://revenue.iowa.gov/), current fuel-tax notices and
  effective July rates.
- KS: [Fuel-tax rates](https://www.ksrevenue.gov/mffueltaxrates.html) and
  [environmental fees](https://www.ksrevenue.gov/pdf/MFHistoricalEnvironmentalAssuranceFees.pdf).
  [Inspection rates](https://www.ksrevenue.gov/pdf/PPIrates.pdf) and
  [inspection report](https://www.ksrevenue.gov/pdf/mf7.pdf) establish $0.015
  per 50-gallon barrel, or $0.0003/gal. EIA's prose incorrectly calls the
  barrel amount "0.015 cents"; its numeric total uses the dollar amount.
- KY:
  [Current rate regulation](https://apps.legislature.ky.gov/law/kar/titles/103/043/341/)
  and [governor actions](https://governor.ky.gov/); distinguish statewide
  relief from limited geographic extensions.
- LA:
  [Motor-fuel taxes](https://revenue.louisiana.gov/businesses/excise/motor-fuel-taxes/).
- ME: [Fuel tax](https://www.maine.gov/revenue/taxes/fuel-tax).
- MD:
  [Comptroller FY2027 motor-fuel alert](https://www.marylandcomptroller.gov/content/dam/mdcomp/tax/legal-publications/alerts/tax-alert-maryland-motor-fuel-tax-rate-changes-fy27.pdf).
  Select the applicable fiscal year for other targets.
- MA: [Massachusetts fuel tax](https://www.mass.gov/motor-fuels-tax) and
  [bill history](https://malegislature.gov/); proposals and partial session-law
  indexes do not establish enactment.
- MI:
  [Treasury fuel-tax notices](https://www.michigan.gov/treasury/reference/taxpayer-notices).
- MN:
  [Cleanup fee collection](https://www.revenue.state.mn.us/petroleum-tax-tank-cleanup-fee)
  and
  [petroleum-tax updates](https://www.revenue.state.mn.us/whats-new-petroleum-tax).
- MS: [Revenue](https://www.dor.ms.gov/), petroleum taxes and current notices.
- MO:
  [Motor-fuel rates and fee equivalents](https://dor.mo.gov/faq/taxation/business/motor-fuel.html).
- MT: [MDT fuel tax](https://mdt.mt.gov/business/fueltax/).
- NE: [Revenue fuel-tax notices](https://revenue.nebraska.gov/), the target
  semiannual period.
- NV: [NRS Chapter 365](https://www.leg.state.nv.us/nrs/nrs-365.html).
- NH: [RSA 260-32](https://gc.nh.gov/rsa/html/XXI/260/260-32.htm).
- NJ: [Treasury](https://www.nj.gov/treasury/), annual petroleum-products
  gross-receipts and motor-fuel determinations; EIA already includes the
  per-gallon PPGRT.
- NM:
  [Gasoline tax](https://www.tax.newmexico.gov/businesses/2020/10/23/gasoline-tax/)
  and the loading-fee sources in the allocation audit. The chaptered 2025 act
  removed the old contingent rate tiers; do not create a fund-balance blocker
  from an agency page that still displays those obsolete tiers.
- NY:
  [Publication 908](https://tax.ny.gov/pubs_and_bulls/publications/pub-908.htm)
  and
  [Publication 718-F](https://www.tax.ny.gov/forms/publications/st/pub718f.htm).
- NC:
  [DOR rates/notices](https://www.ncdor.gov/taxes-forms/motor-fuels-tax/motor-fuels-tax-rates)
  and [official bill history](https://www.ncleg.gov/); verify the date enacted
  relief starts, not merely its signing date.
- ND:
  [Motor-fuel tax](https://www.tax.nd.gov/excise-special-and-other-taxes/motor-fuel-tax).
- OH: [Motor-fuel tax](https://tax.ohio.gov/business/motor-fuel-tax),
  [official legislature](https://www.legislature.ohio.gov/); reconcile
  residual-rate units against the act/LSC analysis when a bulletin conflicts.
  [Petroleum activity tax](https://tax.ohio.gov/business/petroleum-activity-tax)
  publishes the quarterly average wholesale prices used for that tax. The
  utility retrieves the prescribed base directly; do not use an EIA spot proxy
  or supply a duplicate flat correction.
- OK: [Tax Commission](https://oklahoma.gov/tax/businesses/other-taxes.html).
- OR:
  [ODOT collected rates](https://www.oregon.gov/odot/FTG/Pages/Current%20Fuel%20Tax%20Rates.aspx),
  [updates](https://www.oregon.gov/odot/ftg/pages/updates.aspx),
  [ORS 319 and notes](https://www.oregonlegislature.gov/bills_laws/ors/ors319.html).
- PA:
  [Motor-fuel rates](https://www.pa.gov/agencies/revenue/resources/tax-rates/motor-fuel-tax-rates.html)
  and [enacted legislation](https://www.palegis.us/); a co-sponsorship memo is
  a proposal.
- RI:
  [Motor-fuel tax](https://tax.ri.gov/tax-sections/sales-excise-taxes/motor-fuel-tax)
  and
  [31-36-7](https://webserver.rilegislature.gov/statutes/TITLE31/31-36/31-36-7.htm).
- SC: [Code Chapter 28](https://www.scstatehouse.gov/code/t12c028.php) and
  [bill history](https://www.scstatehouse.gov/).
- SD: [Motor-fuel taxes](https://dor.sd.gov/businesses/taxes/motor-fuel/).
- TN:
  [Fuel-tax rates](https://www.tn.gov/revenue/taxes/motor-fuel-taxes/due-dates-and-tax-rates.html).
- TX: [Gasoline tax](https://comptroller.texas.gov/taxes/fuels/gasoline.php)
  and
  [petroleum delivery fee](https://comptroller.texas.gov/taxes/fuels/delivery-fee.php).
- UT:
  [Collected fuel rates](https://tax.utah.gov/business/other-taxes/fuel/rates/)
  and [legislation](https://le.utah.gov/); if a bill page renders another
  session, inspect the target session's JSON record and enrolled act.
- VT:
  [Quarterly MFTIA/MFTA](https://dmv.vermont.gov/CVO/fuel-tax/mftia-mfta-quarterly-fees).
- VA:
  [DMV fuel rates](https://www.dmv.virginia.gov/businesses/tax-act/fuels/tax-rates)
  and
  [wholesale rates](https://www.dmv.virginia.gov/businesses/tax-act/wholesale/tax-rates).
- WA:
  [Excise and fuel-tax facts](https://dol.wa.gov/vehicles-and-boats/prorate-and-fuel-tax/fuel-tax/fuel-tax-facts),
  [PPT collection instructions](https://dor.wa.gov/taxes-rates/other-taxes/petroleum-products-tax),
  [RCW 82.23A.020](https://app.leg.wa.gov/RCW/default.aspx?cite=82.23A.020),
  [PLIA](https://plia.wa.gov/).
- WV: [Revenue](https://tax.wv.gov/), the target year's motor-fuel tax rate
  determination.
- WI:
  [Statutes 78.01](https://docs.legis.wisconsin.gov/statutes/statutes/78/i/01).
- WY: [Title 39](https://wyoleg.gov/statutes/compress/title39.pdf), relevant
  motor-fuel provisions.
