# spatia-flood

House-level flood elevation evidence: what is the lowest floor of a building, relative to the ground
and to the base flood elevation (BFE), and how confident can we be without a surveyed Elevation
Certificate?

This repo starts with research and one pilot:

- [`docs/00-summary.md`](docs/00-summary.md) — what was learned so far (from the spatia-report /
  spatia-data investigation that led here), with the measured numbers.
- [`docs/01-plan-harris-pilot.md`](docs/01-plan-harris-pilot.md) — the Harris County, TX pilot
  plan: 1 m lidar ground for the pilot area, Mapillary street imagery (Google Street View as a
  pilot-only fallback), and a head-to-head benchmark of floor-height methods against Harris County's
  measured first-floor elevations.
- [`docs/02-floor-height-methods.md`](docs/02-floor-height-methods.md) — the literature and model
  survey the benchmark shortlist comes from.
- [`research/`](research/) — the scripts behind the Florida Elevation Certificate backtest and the
  public-source survey (reproducible; they download public data, no data is committed).

Status: **planning**. Nothing is built yet; the pilot is implemented by a separate session from
`docs/01-plan-harris-pilot.md`.
