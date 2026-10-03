# Product direction: B2B flood floor data

Status: **direction set by the owner (2026-10-03); nothing built.** spatia-flood is a new product, sold
to businesses and governments, not to consumers. This doc says what is sold, to whom, through which
channel, and what that changes for the Harris County pilot. Market facts below were checked on
2026-10-03 (sources at the end); anything not checked is marked *unverified*.

## 1. The decision

- **B2B only.** Owner: "this time I want to focus on 2B, it's much better outreach path than plain
  customer." A stand-alone consumer estimate was already the weakest sale (`00-summary.md` §6).
- **Three channels, one product:**
  1. **Data licence (self-hosted)**: the building table for a county or state as GeoParquet/CSV,
     refreshed on a schedule; the customer hosts it.
  2. **API**: one address or building in, one record out; metered.
  3. **Flood portal**: a map and list UI over the same table, with exports.
- **No data-sharing deals for now** (owner, 2026-10-03) still holds. Selling our data is not a deal
  to obtain theirs.

## 2. One table, three views

Build the **per-building table** first; the API and the portal only read it.

- It is what every buyer evaluates before paying: they score it against their own claims, surveys or
  certificates. API latency and portal design come later.
- A data licence needs the whole table anyway (every building in a county, not only the houses
  someone looked up).
- spatia-data already does the hard parts of a data product: versioned GeoParquet on R2, a published
  schema contract, sidecars, refresh discipline. spatia-report already has the web stack, auth
  (spatia-auth) and maplibre + PMTiles maps the portal needs.

## 3. Who buys which channel

| Buyer | Job | Channel | Notes |
|---|---|---|---|
| Private-flood insurers and MGAs | price and select risks; check NFIP-transfer quotes | data licence, then API at quote time | the largest buyer named in `00-summary.md` §6; they will backtest on their own book before buying |
| Reinsurers, cat modellers, lenders, mortgage-risk teams | portfolio exposure, stress tests | data licence | want whole-county coverage, a stable schema and versioned refreshes |
| Local governments (floodplain managers) | substantial-damage triage after a storm, CRS activities, outreach lists, mitigation grant targeting | portal (+ export) | Harris County and NYC already measure floors, so they are not the first market (earlier finding) |
| Surveyors, elevation contractors, insurance agencies | find houses worth a survey or a lift; quote faster | API or portal seat | smaller deals; also a lead channel |
| Proptech and real-estate platforms | a floor-vs-flood line in listings or due diligence | API | volume pricing |

## 4. Competitors already sell all three channels

FloodVision says its building-level Entry Floor Elevations come "as a licensable data layer, API, or
custom GIS-ready output". True Flood Risk sells an enterprise API and a nationwide floor-elevation
database. **The channel is not our edge.** None of the vendors checked publish per-property prices
(search 2026-10-03), so pricing is a question for discovery calls.

What can be the edge:

1. **Published, reproducible accuracy.** The Harris County benchmark (`01-plan-harris-pilot.md`)
   and the Florida certificate backtest (`00-summary.md` §5), with coverage, abstentions and failure
   cases shown. Competitors' reports carry no error bands (`00-summary.md` §6).
2. **Per-building calibrated intervals and provenance**: measured vs estimated, method, input
   dates, and a triage class (clearly above / clearly below / survey needed) with its false-"above"
   rate.
3. **Flood context done right**: building touches the SFHA, BFE, datum and geoid stated, FIRM date
   vs year built. The True Flood Risk report we checked missed the SFHA touch entirely.
4. **A self-hosted option without per-call fees**, sized for small buyers (a county, one MGA's
   state book).

## 5. Licences decide what we may sell

Selling data is redistribution, so every input needs a licence check. What we found (2026-10-03):

| Input | What we may do | Status |
|---|---|---|
| FEMA NFHL, OpenFEMA, USGS 3DEP lidar | US federal works, public domain | clear |
| FDEM Elevation Certificate layer (Florida) | Florida public records; check the service's use constraints | *unverified* |
| Florida DOR parcels | public record; check DOR terms | *unverified* |
| Harris County HCFCD door elevations | **answer key only, never shipped**; confirm before publishing scores against it | *unverified* (no explicit licence found during planning) |
| Mapillary images | Terms §12 allow commercial use for developing datasets and "provision of services for or on behalf of one or more of your clients", with face and licence-plate safeguards; no apps that "merely redistribute Content". Images are CC BY-SA 4.0; whether image-derived floor heights in a sold dataset carry share-alike is **unresolved** | needs a lawyer before a data licence ships image-derived values |
| Bee Maps images | commercial use, or a database built by downloading content, requires an Order Form; the terms reserve derivative works to Hivemapper | derived-data rights must be written into the Order Form before any value reaches a customer |
| Image methods (any imagery) | three active patents to 2041 (`02-floor-height-methods.md` § Patents) | freedom-to-operate opinion before shipping |

That gives two tiers:

- **Core tier**: certificate neighbours + lidar ground + FEMA context. Public-domain or public-record
  inputs and no image patents. It can ship in all three channels, and the Florida backtest already
  shows it at **0.86 ft MAE without ground and ~0.56 ft with lidar-grade ground (simulated)**. Florida is
  where this tier is strongest: ~206 k certificates with numbers.
- **Image tier**: Mapillary / Bee Maps floor readings. It improves accuracy (0.37 ft simulated), but
  ships only after the licence and patent checks. Until then, at most API/portal values computed for
  a client, never a bulk file.

Every row carries an `input_licences` field so a customer's file can be built from the tiers they are
licensed for, and Bee Maps rows can be dropped (`provider=beemaps`, CLAUDE.md).

## 6. The record (draft schema, for the pilot to emit)

One row per building. Names are a draft; the pilot fixes them.

| Group | Fields |
|---|---|
| Identity | `building_id`, footprint source + date, parcel id, normalized address, lon/lat (CRS84) |
| Ground | LAG / HAG estimate (ft NAVD88), source (lidar project, QL, date), geoid model |
| Floor | FFH and FFE estimate, 80% and 95% intervals (calibrated), method, evidence class (`measured_ec` / `measured_inventory` / `estimated`), input dates |
| Flood context | zone(s), building touches SFHA, BFE and its datum, FIRM effective date, year built |
| Decision | floor − BFE, P(floor above BFE), triage class |
| Building | foundation class and its source, enclosure/lower-level flag |
| Provenance | `model_version`, `release`, `input_licences`, `provider` |

Rules carried from CLAUDE.md: estimate and measurement never share a column without the evidence
class; no bare numbers; no personal data (owner names dropped at ingest).

## 7. First market: Florida (recommendation)

- The core tier works statewide with no images and no patent exposure.
- Florida carries the most NFIP and private-flood exposure, and recent storms (Ian, Helene, Milton)
  put substantial-damage work in front of many local governments *(the market share is not
  measured here)*.
- Harris County stays the **accuracy proof**, not the first market.

Two first motions, both cheap:

1. **Blind backtest offer for 2–3 Florida MGAs/insurers**: they send addresses (and, if they want,
   the certificates they hold); we return the table; they score it. The data licence follows.
2. **Portal pilot for 1–2 coastal Florida floodplain managers**: substantial-damage and CRS triage on
   their jurisdiction, from the core tier.

Questions for every discovery call: what do you use today and what does it cost; which fields would
you act on; per property, per county or per seat; how fresh must it be; self-hosted or API; what
accuracy, measured how, would make you switch.

## 8. Changes to the pilot

Added to `01-plan-harris-pilot.md` § 11 (no spatial change, so no new GIS review):

1. P5 writes its per-house outputs in the §6 record shape, as a sample deliverable.
2. Every input row records its licence and provider (`input_licences`).
3. The results doc is written as something a buyer can read (methods, coverage, errors, failures),
   and it becomes the sales benchmark. It moves to `docs/04-pilot-results.md`.
4. Results are reported separately for the core tier (M0/M1, no images) and the image tier.

## 9. Not now

- Building the API or portal before the pilot results and three discovery calls.
- Consumer sales; data-sharing deals; national coverage.
- Any image-derived value in a bulk file before the Mapillary/Bee Maps and patent checks.

## Sources (checked 2026-10-03)

- Mapillary Terms of Use: https://www.mapillary.com/terms
- Mapillary CC BY-SA help article (page blocked to our fetcher; summary seen in search):
  https://help.mapillary.com/hc/en-us/articles/115001770409-CC-BY-SA-license-for-open-data
- Bee Maps Terms of Service: https://beemaps.com/tos and https://beemaps.com/tos/map-products
- FloodVision Entry Floor Elevations: https://fv-efe.netlify.app/
- True Flood Risk nationwide FFE database (PR Newswire):
  https://www.prnewswire.com/news-releases/true-flood-risk-unveils-nationwide-first-floor-elevation-ffe-and-property-feature-database-for-flood-risk-300833467.html
