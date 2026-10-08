# Outreach program: public data in, floodplain managers' eyes on the map

Status: **proposal, 2026-10-08; nothing sent yet.** Facts (dates, CRS classes, points, portals, statute text) are in
`docs/08a-outreach-facts-2026-10-08.md`, each marked verified or not; this doc cites it as *(facts §X)*. The
preconditions in §2 come from the review of the first edition, `docs/07-review-pinellas-r0.md`. Owner decisions
still in force: B2B only, **no data-sharing deals** ("selling our data is not a deal to obtain theirs",
`docs/03-product-b2b.md` §1), no NFIP record matching, no personal data, no Google Street View.

## 1. What the program is for

Two goals, one loop:

1. **Data in.** Public records that make the layer better: elevation certificates we do not yet hold, substantial-damage
   determinations and permits (what changed since the 2018 lidar), LOMAs, newer lidar, appraiser building records.
   Every batch lands in `data/inbox/<source>/`, gets a sources-registry entry with its licence, and goes through the
   release gate (plan `docs/04` §4-5, phase 3). A batch that does not move held-out accuracy is still worth having as
   labels for the next county.
2. **Eyes on the map.** The people who sign off on floodplain decisions in Pinellas (county and city floodplain
   administrators, FDEM's state office, the regional CRS group, surveyors who write the certificates, one private
   flood insurer) look at the viewer, compare it with what they hold, and tell us where it is wrong. Their flags are
   data too (goal 1), and their verdict is the first external test of whether the product's edge
   ("published, reproducible accuracy", `docs/03` §4) is real.

Not goals: selling in this phase (the first sale follows the discovery calls in `docs/03` §7), a FEMA / NFIP
endorsement, or becoming a community's official EC repository.

## 2. Preconditions: what must be true before any outsider sees the map

A floodplain manager will check the things the review found first (facts §C: datum and geoid, which BFE and FIRM
date, LOMAs, substantial damage, freeboard, measured vs estimated). From `docs/07-review-pinellas-r0.md`, before the
first reviewer login:

| # | Precondition | Why | Source |
|---|---|---|---|
| P1 | The accuracy card shows the **fresh held-out score against the Pinellas county certificate layer** (MAE 2.22 ft, band coverage 0.884, BFE side 0.861 on 1,282 buildings) next to the FDEM gate (1.04 / 0.918 / 0.898), and says why they differ (elevated houses: MAE 3.1 ft, bias -1.4 ft; the slab stock scores 1.07 ft) | the county holds those certificates; they will run the comparison themselves | 07 DA1 |
| P2 | Every row states **which floor** `ffe_ft` is (first living floor vs NFIP lowest floor) and record rows carry the lowest floor too; `bfe_call` on a next-higher-floor certificate is not shown as a bare `above` | 434 of 462 such `above` calls are `below` on the lowest floor; 44 % of the enclosures are not documented vent-compliant | 07 M1 |
| P3 | Lidar ground that is water or a seawall base carries a null reason or a `ground_suspect` flag, and `raised_flag` is not driven by a sloped ring (228 of 510 certificate lots with a sloped ring are falsely flagged) | waterfront rows are the ones a floodplain manager looks at first | 07 G1 / DA2 |
| P4 | A certificate that conflicts with the lidar gives `too_close` / null, not `above`; `raised_flag` on record rows comes from the certificate's own floor height | 244 `above` vs 2 `below` from conflict rows; 708 record rows flagged raised against their own certificate | 07 M3, V1 |
| P5 | Viewer: a **known-limitations page** (the NYC BES precedent, facts §D), the datum / geoid statement on every building card, "screening, not a determination" on every page, and a per-building **flag** button | what reviewers need to do the job | §4 |
| P6 | Handoff and viewer counts regenerated from the pinned run13 table | the §8 counts are run9 | 07 DA3 |

Until P1-P4 ship in a release that passes the gate, show the map only in a guided demo (owner present), never a login.

## 3. Track A: data requests (public records)

### 3.1 Principles

- **Public records route first.** Florida Chapter 119: any person may inspect and copy; no reason or identification
  required; copies at most 15¢ a page plus a reasonable special service charge for extensive work; agencies must
  acknowledge and respond promptly and in good faith (facts §B, s. 119.07). Microdecisions v. Skinner: public records
  may be used commercially and an agency cannot copyright them (`docs/phase0-sources-survey.md` B-1d). Ask the
  **agency** for the record, not the vendor portal that hosts it (Forerunner's terms say "internal, non commercial";
  the same certificates obtained from FDEM or the city under ch. 119 are not under those terms).
- **Ask for structured data, not scans**, and for the index first (parcel id, address, dates, the FEMA form's C2a-C2h
  values, datum, diagram). PDFs only where no index exists.
- **No personal data is requested where it can be avoided**; where a record carries owner names (certificate A1,
  substantial-damage letters), ask for the record with that field redacted or drop it at ingest
  (CLAUDE.md). Never ingest Madeira Beach's per-address SD letters (facts §B) as documents; ask the city for the list.
- **Give before asking.** Each request goes with (a) the layer's extract for their jurisdiction (viewer access after
  §2), (b) the discrepancy list between their certificates and ours, which is QC they can score under CRS Activity 310
  CCMP ("review, correct, maintain"), and (c) the coverage card showing where labels are missing.
- **One tracker**, `outreach/requests.csv` (org, record set, route, date sent, status, licence of what came back, inbox
  path); no names.

### 3.2 Target list, Pinellas (phase 1)

Ordered by what moves the layer most, per `docs/07` and the fact sheet.

| # | Record set | Holder | Why it matters | Route | Terms / notes |
|---|---|---|---|---|---|
| A1 | **Municipal elevation certificates**: the structured index behind `ElevationCertificatesCityNewest_Redacted` (1,513 records seen; Madeira Beach, Pinellas Park, Tarpon Springs) and each city's own file | Pinellas County eGIS; the 10 cities on Forerunner (pinellascountyfl, clearwaterfl, largofl, pinellasparkfl, seminolefl, madeirabeachfl, gulfportfl, oldsmarfl, stpetebeachfl, treasureislandfl) and the 4 without (St. Petersburg, Dunedin, Tarpon Springs, Safety Harbor) (facts §B) | **more elevated-house labels** is the owner's stated next step; the county layer's 19,382 records already expose the gap (07 DA1) and add 763 elevated labelled buildings; city certificates are the ones FDEM's 2023+ filing rule does not reach back to | ch. 119 to each city's floodplain administrator / building department: "the index and the FEMA form fields of all elevation certificates on file, as a CSV or your GIS export, owner name redacted" | no licence text on any county layer; FDEM/Forerunner clause avoided by asking the city |
| A2 | **Substantial-damage determinations** after Helene / Milton: parcel id, determination date, damage %, repair / elevate / demolish outcome | Pinellas County (unincorporated: 1,600+ letters by 2024-12-20, app exists, no bulk export), St. Petersburg (12,000+ damaged properties, codes database only), St. Pete Beach, Treasure Island, Madeira Beach (facts §B) | the 2018 lidar and many certificates are **stale** for these buildings (plan §3.1 `stale`); SD status is the first thing a local reviewer will check; a demolished or elevated house must not keep a 2018 floor | ch. 119 for the list (not the letters); county Floodplain Management (floodplain@pinellas.gov) | personal data in letters: ask for the list with owner fields removed |
| A3 | **Permits since 2019-01-01**: new construction, demolition, elevation (lift), fill | county and city building departments; some in county/city permit portals already | change detection with one lidar flight (owner answer 3: `not_evaluated`); a permit list gives `lift_or_rebuild` a record-class source | ch. 119: permit type, parcel, issue and final dates | public record |
| A4 | **LOMAs / LOMR-F** | FEMA NFHL MapServer layer 34 (LOMA points) and layer 1 (LOMRs); MSC weekly LOMC batches (facts §B) | a building removed from the SFHA by letter still reads `touches_sfha` from the polygons; reviewers will test exactly those | **no request needed**: pipeline step (download, point-in-footprint, `loma_case` column) | public domain |
| A5 | **Newer lidar**: the county's own flight (board approved up to $400k in 2023; "collection could begin as early as December 2024"; USGS FY24 DCA "QL1 Lidar Update for Pinellas County"); nothing published after the 2018 flight as of 2026-10-08 (facts §B) | Pinellas BTS / eGIS; USGS 3DEP | second flight = change detection, post-storm ground, GEOID18; the plan's `lift_or_rebuild` depends on it | ask eGIS (egis@pinellascounty.org) for delivery status; if delivered, ch. 119 for the point cloud or DEM before USGS publishes | public record; confirm vertical datum and geoid of the deliverable |
| A6 | **FDEM certificate export**, direct: structured fields of all records (not the Forerunner-hosted layer), including NGVD29 rows and the 2023+ s. 472.0366 filings | FDEM (floods@em.myflorida.com; no data-sharing route exists, facts §B) | settles the Forerunner-terms question for a sold build (`docs/phase0-florida.md` §5); gives the geoid field if the form's C2 "vertical datum" and comments are captured | ch. 119 request to FDEM for the dataset behind the public layer | public record; owner names redacted on request |
| A7 | **Property Appraiser building table** (year built, effective year built, stories, living area; owner table dropped) | PCPAO raw database download (facts §B; EPSG:2882 for shapes) | `year_built` and effective year for change detection; a second source for DOR values; **no foundation / floor-count column in the layer** (owner, 2026-10-07) stays | download; terms page 403, ask | drop owner file at ingest |
| A8 | **Repetitive-loss areas and the county Vulnerability Assessment BFE (+1 ft)** | county floodplain management | reviewers compare against the county's own planning elevation, not only the FIRM | ask with A2 | public |

### 3.3 Phase 2 targets (Florida), from the phase-0 survey

Counties with their own structured certificate layers, largest first (`docs/phase0-sources-survey.md` A2-A3):
Charlotte 36,894 (fields + links), Collier 32,630, Monroe 6,989 + Key West 1,489, Orange 10,781, Bay 3,417, Volusia
3,622, Lake 3,123, Sarasota 2,880 + FTP directory, Deerfield Beach 1,428; Miami-Dade's 112,016 documents (mostly
TIFF scans) wait for the PDF reader (plan phase 3). Same letter, same tracker; a batch per county drives that
county's build (phase 2).

### 3.4 The request letter (template, ch. 119)

> To the Records Custodian, [agency]. Under Chapter 119, Florida Statutes, I request copies of the following public
> records in electronic form: [record set, e.g. "the index of all FEMA Elevation Certificates on file with the City,
> with the FEMA form's section A and C fields (A2 address, A3 parcel id, A7 building diagram, C2a-C2h elevations,
> C2 vertical datum), the certificate date and the surveyor's licence number"], as maintained in [system], as a CSV
> or GIS export. Please redact the building owner's name (form field A1) if it is held in that system; we do not
> need it. If any part of this request requires extensive use of information technology resources, please tell me
> the estimated special service charge before fulfilling it. Please acknowledge receipt. [Name, company, email]

No reason is given and none is required (facts §B). A one-paragraph cover note says what we do with it
(a per-building flood-elevation layer; the agency gets its extract and the discrepancy list back).

## 4. Track B: the reviewer program ("look at our map")

### 4.1 Who, in order

| Wave | Reviewer (role) | Why them | Door |
|---|---|---|---|
| 1 | **Pinellas County Floodplain Management** (CRS Class 2, the highest in Florida; runs the county EC app, the SD program and the Tampa Bay regional CRS group) | the most capable reviewer in the state and the holder of the certificates we scored against; their 2022 CRS scorecard has headroom in 310 (38 of 116: no ECPO / ECPR points), 360 (85 of 110) and 440 (166 of 222: AMD digital flood-data systems) (facts §A, §C) | floodplain@pinellas.gov; ask for 30 minutes and a seat at the next **FRMPIWG** (the county's CRS public-information working group: unincorporated + 19 municipalities + insurers, lenders, realtors, TBRPC; meets up to 3×/yr; **next 2026-10-16**, so realistically the one after) |
| 1 | **City floodplain managers**: St. Petersburg (Class 5; 12,000+ damaged properties, 49% rule), Clearwater (Class 5; Alligator Creek preliminary maps), Dunedin (CFMs on staff), Madeira Beach, St. Pete Beach, Treasure Island (barrier islands: most elevated houses, most SD letters) | the decisions (SD, freeboard, permits) are made here; they hold the certificates we lack (A1) | floodplain@stpete.org; city floodplain pages (facts §A) |
| 2 | **FDEM Office of Floodplain Management** (NFIP state coordinator) | statewide credibility; the route to A6; trains with FFMA | floods@em.myflorida.com |
| 2 | **Tampa Bay Regional CRS Committee** and the **TBRPC Regional Resiliency Coalition** (companies may join as Resiliency Coalition Partners) | one room with every Tampa Bay floodplain office; TBRPC also sits on FRMPIWG | sign up as a partner (free, facts §A); ask Pinellas for the CRS committee date |
| 2 | **Surveyors** (FSMS Tampa Bay chapter) | they wrote the certificates; they know the datum / geoid practice in the county (which geoid a 2015 certificate used) and the diagram conventions; they are also a lead channel (`docs/03` §3) | chapter meeting; one or two firms that file many Pinellas certificates |
| 3 | **One private flood insurer** (Neptune Flood is headquartered in St. Petersburg; Florida is the #1 state for private residential flood premium, facts §A) | the buyer's review: a blind backtest on their book (`docs/03` §7 motion 1) | after wave 1-2 fixes; this is the first discovery call, not outreach |
| 3 | **SWFWMD** (watershed models for Pinellas; FEMA CTP role) and **FEMA Region 4** mitigation | the modelled-BFE side (07 M4 / G3) | WMP@WaterMatters.org; FEMA-R4-Info@fema.dhs.gov |

### 4.2 What a reviewer gets and is asked to do

**Gets**: a personal login to flood.runspatia.com (Cloudflare Access per e-mail once enabled; until then a per-reviewer
basic-auth password, rotated after the review), the accuracy card for their jurisdiction, the known-limitations page,
the data dictionary (`docs/06-layer-schema-v1.md` rendered), a 20-minute walkthrough, and a written answer to every
flag within two weeks. No bulk download in this phase (the viewer streams per cell; the data licence comes later).

**Is asked to do** (a one-page review guide, 60-90 minutes):

1. **Ten buildings you know.** Pick ten addresses whose certificate or survey you hold (include elevated houses and
   a post-storm rebuild). For each: our floor vs yours, our BFE vs yours, our zone vs yours. Flag every disagreement.
2. **The hard cases.** A LOMA property; a building on the Alligator Creek / Cross Bayou interpolated-BFE reach; a
   barrier-island house with an enclosure (diagram 6-9); a house elevated under Elevate Florida or after Helene; a
   waterfront lot (seawall, dock).
3. **Datum and dates.** Does the building card state the datum, geoid, FIRM date and lidar date the way you would?
4. **Use.** Which of these would you act on tomorrow: SD triage list, ECPO / ECPR targeting (which post-FIRM SFHA
   buildings have no certificate), outreach lists for Activity 360 site visits, a "survey needed" list for owners?
   What is missing for that use?
5. **Trust.** On a 1-5 scale: would you cite this map in a conversation with a property owner? What would change it?

**Flags** are captured in the viewer (building_id, issue type from a fixed list: wrong floor / wrong BFE / wrong zone /
wrong ground / building changed / wrong address / other; free text; optional attachment) and land in
`data/inbox/feedback/<reviewer-org>/`. A flag with a certificate attached is a label (goal 1).

### 4.3 Rules for the program

- Every page says **screening, not a determination**; the viewer never shows a bare number without its class,
  source and band (CLAUDE.md). Certificates shown carry their licence tag; nothing Bee Maps / NFIP-derived exists
  in this edition.
- Reviewers see addresses (needed for the job) but no owner, taxpayer or contact field; the viewer export already
  carries none (07 §4).
- Nothing a reviewer tells us is attributed to a named person in any doc or commit; organisations only, with consent.
- We do not represent the map as FEMA's, the county's or FDEM's; a disclaimer and our name are on every page.
- A reviewer's correction changes the layer only through the inbox → rebuild → gate → release-notes loop
  (plan phase 3), and the release notes say what changed and why.

## 5. Channels and calendar

| When | What | Cost | Note |
|---|---|---|---|
| now | TBRPC Resiliency Coalition partner sign-up | free | facts §A |
| by 2026-10-15 | e-mail Pinellas County Floodplain Management: 30-minute walkthrough + ask for a FRMPIWG agenda slot (next meeting 2026-10-16 is too soon; target the following one) + the Tampa Bay CRS committee date | — | wave 1 |
| by 2026-10-31 | ch. 119 letters A1 (county municipal layer + the 6 barrier-island / large cities), A2, A3 to the county and St. Petersburg; A5 status question to eGIS; A6 to FDEM | postage / fees | track A |
| **2026-11-02** | **ASFPM 2027 abstract deadline** (Pittsburgh, May 23-27 2027): "Published, reproducible accuracy of a per-building first-floor layer: Pinellas County" — the held-out and county-certificate scores, the band calibration, the failure cases | registration later | facts §A |
| Nov-Dec 2026 | wave 1 reviews (after §2 preconditions ship as a release); first flags; A1 batches arrive; r1 trained with county + city labels | — | §4 |
| Jan 2027 | FFMA 2027 commitment: **Innisbrook, Palm Harbor, April 13-16 2027 — inside Pinellas** (464 attendees in 2026, 248 from local government); Pond tier $1,500 (booth) or Lake $5,000 (3-minute plenary + attendee list); submit a presentation on the Pinellas review results and the reviewers' verdicts | $1,500-5,000 | facts §A; the best-placed event this product will ever get |
| Jan-Mar 2027 | wave 2 (FDEM, CRS committee, surveyors); phase-2 county letters (§3.3) | — | |
| Apr 2027 | FFMA: demo, reviewer testimonials (org-level), discovery calls with the 192 consultants' firms and the insurers present | | |
| May 2027 | ASFPM | | |

Elevate Florida (12,000+ applications; the state procures a certificate and survey for every awarded home; Pinellas is
not among its 37 partner counties; facts §B): send one note (info@elevatefl.org) offering the layer for prioritisation
and asking whether award-level certificates become public records; low effort, possibly a large future label source.

## 6. Materials to prepare (owner + one session)

1. **One-pager**: what the layer is, what it is not, the two accuracy numbers (FDEM gate and county-certificate
   held-out), coverage, the loop (your records → better map for you), who we are.
2. **Accuracy card per jurisdiction** (viewer, from `pipeline/assemble/coverage.py` + the county-certificate score):
   measured vs modeled counts, MAE and band coverage by group, decided-call share and its error rate, labels missing.
3. **Known-limitations page** (viewer): one lidar flight (2018-19, pre-Helene), first-living-floor definition, lidar
   ground vs certificate LAG, interpolated BFEs, the ODbL footprint licence, no LOMAs yet, no NGVD29 certificates.
4. **Data dictionary**: `docs/06` rendered, with the null reasons.
5. **Review guide** (§4.2) and the **feedback flag** in the viewer.
6. **Request letter** (§3.4) and the tracker.
7. **Demo script** (10 minutes): one slab house with a certificate, one elevated house with a modeled band, one
   `too_close`, one interpolated BFE, one waterfront null, the coverage map.

## 7. What success looks like in 90 days (measured, not felt)

| Metric | Target by 2027-01-15 | Where it is read |
|---|---|---|
| Requests sent / fulfilled | 8 / 4 (A1 county + 3 cities, A2, A3, A5, A6) | `outreach/requests.csv` |
| New certificate labels ingested, of which elevated (diagram 5-9) | +5,000 / +1,500 (county 19,382 layer plus city batches) | `pipeline/train/out/labels_*.json` |
| Held-out MAE on elevated houses (county-certificate set) | from 3.1 ft to under 2.0 ft; band coverage on unflagged elevated from 0.54 to >= 0.85 | release gate output |
| Reviewers onboarded / reviews returned | 6 / 4 (county + 3 cities + FDEM + 1 surveyor) | tracker |
| Flags received / answered within 14 days | all answered; > 50% resolved in a release | `data/inbox/feedback/` + release notes |
| Buildings changed by reviewer evidence | reported per release | release notes |
| A written statement from one jurisdiction that they used the layer for a CRS or SD task | 1 | tracker |
| ASFPM abstract submitted; FFMA 2027 booked | yes / yes | |

## 8. Risks

- **Post-storm bandwidth.** Every Pinellas floodplain office is working SD compliance deadlines (county: 2026-12-31).
  The pitch must be "here is your SD triage list and the certificates you are missing", not "please review our
  product". Keep the review to 90 minutes; do their ten buildings for them if they send the list.
- **Forerunner terms** on city portals: never scrape them; ch. 119 to the city instead (§3.1).
- **Being taken for an official map.** Disclaimers, our name, the "screening" wording; never a FEMA / county logo.
- **A reviewer finds the review's blocking findings before we fix them** (§2): do not invite before P1-P4 ship.
- **Personal data** in SD letters and certificate A1 fields: request redacted; drop at ingest; audit the inbox.
- **Share-alike** (Overture ODbL) and the FDEM / Forerunner question are unresolved for a *sold* build
  (`docs/phase0-florida.md` §5); outreach does not sell, but the one-pager must not promise a data licence before
  the legal read.
