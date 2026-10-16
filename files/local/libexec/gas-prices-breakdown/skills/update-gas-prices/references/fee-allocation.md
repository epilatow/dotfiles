# Fee allocation

Include a fee when sourced data supports a per-gallon value. A stated
per-gallon rate, a legally defined continuous volume rate, explicit proration,
or matched public allocation data can establish that value. A charge's name,
annual billing schedule or use of barrels does not make it unpriceable.

Omit and disclose a charge only when its gasoline allocation needs information
not available in the sourced inputs. Do not assume a truck size, product mix,
facility turnover or taxpayer's annual volume. Do not treat an inaccessible
source for a calculable rate as an allocation exclusion. Indiana's gasoline use
tax is the one exception: the utility discloses it as excluded when its notice
yields no usable rate, as the skill describes.

## Allocation audit

The July 2026 [EIA fuel-tax workbook][eia] notes for all 50 states and DC were
reviewed on 2026-10-11, alongside retained state primary sources. Ambiguous
load/volume mechanisms and facility charges were checked against the primary
sources below. This is an allocation audit of the modeled fuel charges; it does
not claim an exhaustive inventory of every business permit or prove that an
unchanged rate page rules out later enacted changes. Continue checking
effective changes under the skill's latest-supported-rate policy.

Coverage of the 51 jurisdictions:

- Published gallon-based charges or assessments: AK, AL, AR, AZ, CO, DC, FL,
  GA, HI, ID, IL, IN, KY, MI, MN, MS, MT, NC, ND, NE, NH, NV, NY, OK, PA, RI,
  SC, SD, TN, UT, VA, VT, WI, WY. Retain the applicable per-gallon components;
  exemptions and effective periods still matter.
- Defined barrel-volume conversions: CA, KS, MD, ME, NJ, WA. Use the source's
  gallon definition, not a universal barrel size. Keep unrelated unallocated
  charges separate.
- Load-related charges with a sourced per-gallon basis: LA, MA, MO, NM. Retain
  them; the mechanisms below provide the conversion.
- Delivery-allocation exclusions: OR, TX. Their charges need actual delivery
  information that the modeled inputs do not provide.
- Other modeled taxes rather than an additional flat-fee conversion: CT, DE,
  OH, WV. The EIA notes also identify IA's repealed environmental charge.

### Retained load and volume charges

- **Louisiana:** [R.S. 30:2195.3][la-load] explicitly adjusts larger and
  smaller withdrawals using the cent-per-gallon equivalent.
  [LDEQ's registration instructions][la-form] state a $0.008-per-gallon
  motor-fuel trust fee. This is not an assumed 9,000-gallon truckload.
- **Massachusetts:** [DOR motor-fuel guidance][ma-fuel] explicitly prorates the
  delivery fee above or below 10,000 gallons. [The UST rate notice][ma-rate]
  publishes 3.4393 cents per gallon for 2026. Retain this fee while treating
  the distinct annual tank charge separately.
- **Missouri:** [DOR's motor-fuel FAQ][mo] publishes both the
  $0.0009-per-gallon inspection fee and $0.004-per-gallon transport-load
  equivalent. EIA already includes them; do not add a second correction or
  substitute a guessed truck.
- **New Mexico:** [chaptered HB 218][nm-history], Section 95 of the
  [final act][nm-act], charges $150 per defined 8,000-gallon load and
  calculates loads from aggregate taxable gallons. It is a volume conversion,
  not a count of physical deliveries: $150 / 8,000 = $0.01875 per gallon before
  the prescribed return rounding to a hundredth of a load. The 2025 act removed
  the contingent fund-balance tiers. The older TRD page still shows those
  tiers; do not use it to invent uncertainty about the current statutory rate.
- **Kansas:** [KDOR's inspection-rate memorandum][ks-rate] and [MF-7][ks-form]
  prescribe $0.015 per **50-gallon** barrel, or $0.0003 per gallon. EIA's prose
  says "0.015 cents" but its numeric total uses the dollar amount. Do not
  introduce a factor-of-100 correction based on that prose error.
- **Maine oil imports:** [DEP's effective fee notice][me-oil] establishes the
  gasoline fee at $0.61 per barrel; [38 M.R.S. 542][me-barrel] defines 42
  gallons. EIA includes that conversion. The separate Marketing Fund charge
  below must not cause this calculable fee to be removed.
- **Minnesota:** [Revenue's inspection guidance][mn] states both $1 per 1,000
  gallons and $0.001 per gallon. Its cleanup fee is also explicitly per gallon;
  check the applicable collection period without demanding payer volume data.
- **Pennsylvania:** [Revenue's rate guidance][pa-rate] expressly includes the
  1.1-cent-per-gallon gasoline UST charge. A fee on tank capacity applies to
  other substances under [Section 705(d)][pa-act]; tank capacity is not
  gasoline throughput. Do not add that other-product capacity fee to gasoline
  totals.

### Unquantified charges

The following charges remain real costs, but no supported gasoline-specific
per-gallon allocation was established for this build. They are disclosed
exclusions, not zero charges or acknowledged data gaps awaiting backfill.
State-cost totals omit them; the supply-chain residual includes them.

- **Maine Marketing Fund:** [10 M.R.S. 1681][me-marketing] assesses rounded
  10,000-gallon units over annual volume. Dividing $0.40 by 10,000 supplies a
  nominal lower bound, not the effective charge. Do not add $0.00004 per
  gallon.
- **Oregon petroleum load fee:** [DOR's instructions][or] charge by delivery.
  Actual load volumes are needed for the modeled per-gallon allocation.
- **Texas petroleum delivery fee:** [Comptroller guidance][tx] varies by
  delivery quantity and, in relevant tiers, the gasoline share of split loads.
  A representative truck size cannot supply those facts.
- **Facility and registration charges:** [Delaware gasoline licensing][de],
  [Indiana gasoline-use-tax registration][in],
  [Louisiana UST registration][la],
  [Massachusetts annual UST charges][ma-annual],
  [Mississippi tank charges][ms],
  [Pennsylvania tank registration][pa-registration] and
  [Wisconsin business registration][wi] need matched gasoline-throughput or
  business-allocation information. Their calculable per-gallon fuel fees remain
  included. The same data criterion applies elsewhere; it is not a blanket
  exclusion of annual, licensing, inspection or environmental fees.

For a newly identified charge, record the primary allocation evidence and the
missing input in the review's `unquantified_fees`. If matched public data or an
applicable proration rule supports the per-gallon amount, include the fee
instead. The utility renders recorded exclusions in state notes without adding
a numeric zero or correction. Preserve existing snapshots during ordinary
updates; an exclusion is not authorization to rewrite their numeric data.

[de]: https://delcode.delaware.gov/title30/c051/sc01/index.html
[eia]: https://www.eia.gov/petroleum/marketing/monthly/xls/fueltaxes.xlsx
[in]: https://www.in.gov/dor/i-am-a/business-corp/gasoline-use-tax/
[ks-form]: https://www.ksrevenue.gov/pdf/mf7.pdf
[ks-rate]: https://www.ksrevenue.gov/pdf/PPIrates.pdf
[la]: https://www.deq.louisiana.gov/underground-storage-tank-ust-registrations
[la-form]: https://deq.louisiana.gov/assets/docs/Forms/UST_REG_FORM.pdf
[la-load]: https://www.legis.la.gov/legis/Law.aspx?d=87241
[ma-annual]: https://www.mass.gov/info-details/ust-frequently-asked-questions
[ma-fuel]: https://www.mass.gov/info-details/dor-motor-fuel-excise
[ma-rate]: https://www.mass.gov/info-details/underground-storage-tank-program-ust
[me-barrel]: https://www.legis.maine.gov/statutes/38/title38sec542.html
[me-marketing]: https://legislature.maine.gov/statutes/10/title10sec1681.html
[me-oil]: https://www.maine.gov/dep/waste/oilconveyance/documents/Oil%20Import%20Fee%20interested%20party%20notice%2011-1-2025.pdf
[mn]: https://www.revenue.state.mn.us/mndor-pp/6331?type=html
[mo]: https://dor.mo.gov/faq/taxation/business/motor-fuel.html
[ms]: https://www.mdeq.ms.gov/water/groundwater-assessment-and-remediation/underground-storage-tanks/
[nm-act]: https://www.nmlegis.gov/Sessions/25%20Regular/final/HB0218.pdf
[nm-history]: https://www.nmlegis.gov/Legislation/Legislation?Chamber=H&LegType=B&LegNo=218&year=25
[or]: https://www.oregon.gov/dor/programs/businesses/Pages/petroleum.aspx
[pa-act]: https://www.legis.state.pa.us/WU01/LI/LI/US/HTM/1989/0/0032..HTM
[pa-rate]: https://www.pa.gov/agencies/revenue/resources/tax-rates/motor-fuel-tax-rates.html
[pa-registration]: https://www.pa.gov/services/dep/register-a-storage-tank-with-the-department-of-environmental-protection
[tx]: https://comptroller.texas.gov/taxes/fuels/delivery-fee.php
[wi]: https://www.revenue.wi.gov/dor%20publications/pb307.pdf
