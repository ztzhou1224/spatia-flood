# Phase 0: Florida measured (2026-10-07)

Plan: `docs/04-plan-flood-layer-v1.md`. Sources and terms in detail: `docs/phase0-sources-survey.md` (every count
there from a REST query, API response or sampled file of 2026-10-07). Commands: `pipeline/phase0/measure_fl.py`
(output `pipeline/phase0/out/fl_counties.csv`), `pipeline/phase0/risk_area.py 12103` (output
`pipeline/phase0/out/risk_12103.json`).

## Statewide (measure_fl.py)

| Measure | Florida |
|---|---|
| Structures, USACE NSI 2022 | 8,373,586 (7,585,073 residential) |
| FDEM certificates: residential, NAVD88, latest per property, inside a county | 109,853 (94,054 diagram 1A / 1B; 14,986 diagrams 5-9) |
| FDEM layer total | 210,888 records, each with a PDF link; 206,255 with a bottom-floor value; 37,164 in NGVD29 (survey) |
| Lidar tiles listed over county bounding boxes | 246,341 tiles, ~42 TB, 362 projects (over-counts: boxes overlap counties, older flights included) |

NSI's own `firmzone` puts 1,130,020 structures in the SFHA statewide, but only 5,018 in Pinellas, where the risk
area below holds 290,540 buildings: **NSI's zone field is not usable**; zones come from the NFHL polygons
(spatia-data `fema_flood_zones`, which also carries every static BFE converted to NAVD88 with a sigma and status).

## Pinellas, the phase-1 county (risk_area.py)

| Measure | Pinellas (12103) |
|---|---|
| Area: county polygon (water included) / SFHA / 0.2% zone / risk area (SFHA + 0.2% + 500 m) | 2,234 / 424 / 77 / 900 km2 |
| Overture buildings in the county / in the risk area | 372,736 / **290,540 (78%)** |
| NSI structures in the risk area | 344,488 (316,071 residential) |
| FDEM certificates in the risk area | 8,147 |
| Pinellas county EC layer (structured fields + PDFs) | 19,382 records (survey; overlap with FDEM not measured) |
| Lidar touching the risk area | FL_Peninsular_2018_D18: 483 tiles, 88.2 GB; legacy: 473 tiles, 40.6 GB; FL_2018PascoCounty_C22: 11 tiles, 3.0 GB |

In coastal counties the risk area is most of the county, not a thin band: statewide floor work will cover millions
of buildings and terabytes of lidar. Phase 2 measures it county by county on the rented box with the same script.

## What this changes in the plan

1. **Zones and BFE**: from `fema_flood_zones` (NFHL, BFE already in NAVD88 with sigma); NSI zones dropped.
2. **Labels**: FDEM (109,853 usable statewide) plus county layers that are larger than FDEM's share in several
   counties (Miami-Dade 112,016 documents, Charlotte 36,894, Collier 32,630, Pinellas 19,382; survey). NGVD29
   certificates (37,164) need a datum conversion before use; `issuedAt` has invalid dates to clean.
3. **PDF reader**: FDEM PDFs are mostly born-digital (14 of 20 sampled have a text layer); county PDFs are mostly
   scans (27 of 31 sampled), so OCR is needed for the county sources. Size: tens of thousands of documents.
4. **Personal data**: owner names are in FDEM (`buildingOwnerName`, 175,106 records), the Pinellas EC layer, and
   `fl_parcels` (`own_name`); all dropped at ingest.
5. **Terms, before anything is sold** (not blocking the internal v1):
   - FDEM certificate PDFs are hosted by Forerunner, whose terms allow use "solely for your internal, non
     commercial purposes". Florida public-records law (Microdecisions v. Skinner, Fla. 2d DCA 2004) may override
     this for public records. A legal read is needed, or a direct chapter 119 request to FDEM.
   - NSI 2022 is built partly from licensed commercial inputs. NSI-derived values stay internal, marked
     `withheld` in any sold build, until USACE terms are confirmed.
   - Overture footprints and IDs are ODbL: shipping them in a sold table makes it a Derivative Database, which
     must be offered under ODbL. Maps are Produced Works and need only a notice. A legal read is needed.
   - 3DEP is public domain; NFHL is "free of copyright"; Florida addresses in Overture are public domain;
     Geocodio results may be stored and sold where their underlying source allows it (source kept per row).

## Paid lookups: cost before any call (2026-10-07; nothing called yet)

Owner rule (2026-10-07): no Geocodio or RentCast call without an approved cost estimate.

**Addresses, Pinellas risk area** (`pipeline/phase0/address_gap.py 12103`, output `out/address_gap_12103.json`):

| Risk-area buildings | Overture address point in footprint | else situs address of the containing `fl_parcels` parcel | no free address | no parcel |
|---|---|---|---|---|
| 290,540 | 233,881 (80.5%) | 55,932 (19.3%) | **727 (0.25%)** | 3,105 |

**Geocodio** (pricing page read 2026-10-07: 2,500 lookups / day free, then $1 / 1,000; reverse = forward; each
extra data field counts as one more lookup): Pinellas needs 727 reverse lookups = **$0** (inside one day's free
tier). Florida is not measured yet; if other counties match Pinellas's 0.25% of ~8.4 M structures, ~21,000 lookups:
$0 spread over 9 days, or ~$19 in one day. Phase 2 measures each county with the same script before any call.

**RentCast** (pricing page and `developers.rentcast.io/reference/billing-and-pricing` read 2026-10-07): billed per
successful request (HTTP 200), "it doesn't matter how much data you retrieve via each API request"; the property
records search returns up to 500 records per request (`limit` 1-500, `offset` pagination; by city, ZIP or
lat/lon + radius). Plans: Developer $0 (50 requests, then $0.20 each), Foundation $74 / month (1,000, then $0.06),
Growth $199 (5,000, then $0.03), Scale $449 (25,000, then $0.015). No hard cap: overage is billed automatically.
Unit = a residential parcel (DOR use codes 000-009):

| Area | Residential parcels | Requests at 500 per request (floor; tiling overlap may double it) | Cost |
|---|---|---|---|
| Pinellas risk area (with a building) | 212,386 (`address_gap.py`) | 425-850 | Foundation month $74 (or Developer: $75-160 in overage) |
| Florida, all residential parcels with living area | 8,049,712 (`fl_parcels` count) | 16,100-32,200 | Scale month $449-557 |

Not yet verified (needs one test request, at most $0.20): that the search results carry `features`
(foundation type, floor count) and that `offset` pages through a whole ZIP. Owner names in RentCast records are
dropped at ingest.
