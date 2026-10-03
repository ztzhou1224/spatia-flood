# CLAUDE.md

Guidance for Claude Code sessions working in this repository.

## What this repo is

spatia-flood estimates a building's **first-floor height** (FFH: lowest finished floor above the
ground next to it) and **first-floor elevation** (FFE: that floor in NAVD88 feet), so it can be
compared with the FEMA base flood elevation (BFE). It is a sibling of
[`spatia-data`](https://github.com/ztzhou1224/spatia-data) (publishes curated layers to R2) and
[`spatia-report`](https://github.com/ztzhou1224/spatia-report) (the cited report engine). Read
`docs/00-summary.md` first, then the active plan in `docs/`.

Current work: the Harris County pilot, `docs/01-plan-harris-pilot.md`. Implement it phase by phase;
each phase has acceptance criteria. Do not widen scope beyond the plan without asking the owner.

## Rules that are not optional

- **Every number in a handoff, doc or commit comes from a command you actually ran**, with the
  command or script named. If something you measure contradicts the plan, report it instead of
  encoding the plan's claim. (Inherited from spatia-data, where fabricated measurements once
  shipped.)
- **Ground truth is never a feature.** The Harris County measured FFE (Cyclomedia) is the answer key.
  No method may read it, its derived fields, or anything joined from it, except the scorer.
- **Separate what was measured from what was estimated.** Every estimate carries its method, its
  inputs' dates, and an error band; never a bare number.
- **Coordinates:** store everything as OGC:CRS84 (lon, lat). Read each raster's CRS from the file;
  never assume. Measure distances and areas in a projected metric CRS (UTM 15N for Harris County),
  never in degrees. In this DuckDB build the `*_Spheroid` functions read x as LATITUDE: do not use
  them on lon/lat geometry. Use `'EPSG:4326'` (always_xy) as the source tag when transforming
  published lon/lat to a projected CRS.
- **Vertical datum:** all elevations in feet NAVD88. Record the geoid model per value
  (GEOID12B vs GEOID18); never mix silently. US survey feet vs international feet must be explicit.
- **Imagery terms:** **Never use Google Street View** (owner decision 2026-10-03; its terms forbid
  testing ML models on it). Mapillary images are CC BY-SA 4.0 (attribute, logo + link on extracted
  data). Bee Maps (Hivemapper) imagery is paid and licensed only for use within our implementation,
  no redistribution; use it only after the owner accepts its terms, and tag its rows
  `provider=beemaps` so they can be dropped.
- **No secrets in git.** Keys live in `.env` (gitignored): `MAPILLARY_ACCESS_TOKEN`,
  `BEEMAPS_API_KEY`, and the R2 read credentials if reading spatia-data layers.
- **No data in git.** Raw downloads, rasters, images and parquet go under `data/` (gitignored).
  Commit code, configs, small result tables and docs.
- **No personal data in committed outputs.** Some public sources carry owner names; drop owner,
  taxpayer and contact columns at ingest.

## Stack (proposed for the pilot)

Python 3.12 managed with `uv`, DuckDB (+ `spatial`, `httpfs`, `h3` — h3 is a COMMUNITY extension:
`INSTALL h3 FROM community`), rasterio/GDAL for rasters, PyTorch for vision models. Keep it typed
and ruff-clean.
