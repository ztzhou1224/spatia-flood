# Review of pinellas-r0 (2026-10-08)

Consolidated verdict and action list: `docs/07-review-pinellas-r0.md`. This directory holds the evidence.

| File | What |
|---|---|
| `sources.md`, `methodology.md`, `implementation.md`, `gis.md`, `data_audit.md` | the five round-1 reviews, each from a clean context with one angle |
| `verification.md` | round-2 re-derivation of every blocking / major finding of the first four reports, contradictions settled, severities re-graded |
| `verification_gis.md` | the same for the GIS review, plus one finding none of the round-1 reviews made (`raised_flag` vs record floor height) |
| `work/<angle>/` | the scripts and text outputs behind every number (run against the local run13 table and train artefacts under `data/flood_v1/`, which are not in git); large intermediates (parquet, geoid grids, fetched pages) were not committed |

Rules the reviews ran under: every number from a command actually run; no owner / contact names (two outputs were
redacted before commit); ground truth used only to score; nothing under the repo modified; no R2, no paid API.
