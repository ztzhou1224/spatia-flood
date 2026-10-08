# spatia-flood

House-level flood elevation evidence: what is the lowest floor of a building, relative to the ground
and to the base flood elevation (BFE), and how confident can we be without a surveyed Elevation
Certificate?

This repo starts with research and one pilot:

- [`docs/00-summary.md`](docs/00-summary.md) — what was learned so far (from the spatia-report /
  spatia-data investigation that led here), with the measured numbers.
- [`docs/01-plan-harris-pilot.md`](docs/01-plan-harris-pilot.md) — the Harris County, TX pilot
  plan: 1 m lidar ground for the pilot area, Mapillary street imagery (Bee Maps as a
  paid fallback; no Google Street View), and a head-to-head benchmark of floor-height methods against Harris County's
  measured first-floor elevations.
- [`docs/02-floor-height-methods.md`](docs/02-floor-height-methods.md) — the literature and model
  survey the benchmark shortlist comes from.
- [`docs/03-product-b2b.md`](docs/03-product-b2b.md) — the product direction: B2B only, sold as a
  data licence, an API or a flood portal; buyers, licence limits on what we may resell, the record
  schema, Florida first.
- [`research/`](research/) — the scripts behind the Florida Elevation Certificate backtest and the
  public-source survey (reproducible; they download public data, no data is committed).

Status: **first edition built** (2026-10-08). The flood layer v1 plan (`docs/04-plan-flood-layer-v1.md`) is in phase 1:
Pinellas County `pinellas-r0` is assembled, gated and published as a spatia-data pilot layer, with an internal viewer
(`docs/05-handoff-2026-10-07.md`). Its multi-angle review is `docs/07-review-pinellas-r0.md`; the outreach program is
`docs/08-outreach-program.md` (facts in `docs/08a-outreach-facts-2026-10-08.md`). The Harris plan above is the research
basis and the planned accuracy proof.
