# research/

Scripts from the 2026-10-02 investigation, kept for reproducibility. They were run as one-off
scripts from a scratch directory, so they read and write files in the current working directory.
No data is committed; every input is downloaded from a public source (or from the spatia-data R2
bucket, which needs read credentials).

## `ec_backtest/` — neighbour-certificate floor estimate, Florida

Run in this order from an empty working directory:

1. `fetch_ec.py` — pulls every record of the FDEM elevation-certificate FeatureServer (the numeric
   fields included) into `ec_all.json` (~210,888 rows).
2. `backtest.py` — cleans to 59,590 certificates (NAVD88, residential, finished construction,
   zones AE/AH/A, plausible values, one per property) and scores the neighbour medians
   (B0 floor = BFE, B1 neighbours' floor−BFE, B2 own LAG + neighbours' floor−LAG).
3. `backtest2.py` — leakage check (exclude neighbours within 15 m), simulated ground noise, the
   Bonita Springs subset, and the 27536 Riverbank Dr worked example.
4. `join2.py` — point-in-polygon join of the certificates to `fl_parcels.parquet` (download it from
   R2 `layers/state/FL/fl_parcels.parquet`, 2.7 GB) for year built, plus the year-built
   distribution of single-family parcels in the same neighbourhoods. Memory-bounded (bbox bucket
   join, then exact `ST_Intersects`).
5. `ml.py` — by-age results, reweighting to the housing stock, gradient boosting with spatial
   5-fold CV and quantile intervals.
6. `ml2.py` (+ `ml_head.py`, generated from the top of `ml.py`) — LightGBM / random forest /
   residual kriging / ensemble comparison, and the street-view simulations. Needs `lightgbm`.

The DuckDB used needs the `spatial` and `h3` extensions. Python packages: numpy, scikit-learn,
pyarrow, duckdb, lightgbm.

## `ec_sources/`

- `forerunner_portals.txt` — Forerunner community portal hostnames found in certificate-
  transparency logs, with the HTTP status seen on 2026-10-02. Portals show certificates as
  documents; none offers a bulk feed.

The full verified source survey (endpoints, record counts, fields) is summarised in
`docs/00-summary.md` §7.
