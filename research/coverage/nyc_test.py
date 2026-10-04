"""Test the core floor method on New York City's measured first floors (Staten Island east shore).

Answer key (scorer only): NYC DCP Building Elevation and Subgrade (BES, NYC Open Data bsin-59hv):
z_floor = first-floor elevation, z_grade = lowest adjacent grade, ft NAVD88, measured from street-level
imagery + mobile lidar; subgrade = Y/N. Street addresses are dropped at download.
Inputs (national): USGS 3DEP 1 m DEM NY_CMPG_2013 (EPSG:26918, metres), NSI (USACE), NYC building
footprints (BUILDING dataset 5zhs-2jue, joined by BIN; construction_year).
Estimates (FFE, ft NAVD88):
  national      lidar median ring grade + NSI foundation height (no local measurements)
  nsi only      NSI ground + NSI foundation height
  harris model  GBM trained on Harris County (areas B+C) national features, applied here
  local const   lidar LAG + median door height of a 10% local pool (needs local measurements)
  neighbours    GBM with a 10% local pool (evaluate.py design)
Usage: python nyc_test.py
"""
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as stransform
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402
import evaluate_cov as ec  # noqa: E402

ROOT = HERE.parents[1]
D = ROOT / "data"
USFT = 1200 / 3937
FT = {"S": 0, "C": 1, "B": 2, "P": 3, "I": 4, "W": 5}


def metrics(e):
    e = pd.Series(e).dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(), within_1=(e.abs() <= 1).mean(),
                p90=e.abs().quantile(0.9), bias=e.mean())


def main():
    bes = pd.read_parquet(D / "nyc" / "bes_si_east.parquet")
    bes = bes[bes.notes1.str.startswith("Property was Successfully Measured") & bes.z_floor.notna() & (bes.z_floor > 0)]
    fp = pd.read_parquet(D / "nyc" / "footprints_si_east.parquet")
    norm = lambda v: pd.to_numeric(v, errors="coerce").astype("Int64").astype(str)
    bes = bes.assign(bin=norm(bes.bin))
    fp = fp.assign(bin=norm(fp.bin)).drop_duplicates("bin")
    to = Transformer.from_crs("EPSG:4326", "EPSG:26918", always_xy=True).transform
    fp["geom"] = [stransform(to, shape(json.loads(g))) for g in fp.the_geom]
    h = bes.merge(fp[["bin", "geom", "construction_year", "height_roof"]], on="bin", how="inner")
    h["geom"] = [g.buffer(0) if not g.is_valid else g for g in h.geom]
    h = h[[g.area > 20 for g in h.geom]].reset_index(drop=True)
    # NSI: point inside the footprint
    nsi = pd.read_parquet(D / "harris_mini" / "NYC_SI" / "nsi.parquet")
    nx, ny_ = to(nsi.x.values, nsi.y.values)
    nt = STRtree([Point(a, b) for a, b in zip(nx, ny_)])
    pick = []
    for g in h.geom:
        j = nt.query(g, predicate="contains")
        pick.append(j[0] if len(j) else -1)
    for c, src in (("nsi_found_type", "found_type"), ("nsi_found_ht", "found_ht"), ("nsi_year", "med_yr_blt"),
                   ("nsi_stories", "num_story"), ("nsi_ground", "ground_elv"), ("nsi_occ", "occtype")):
        h[c] = [nsi[src].iat[k] if k >= 0 else None for k in pick]
    h = h[h.nsi_occ.fillna("").str.startswith("RES1")].reset_index(drop=True)  # single-family
    # lidar ring stats (0.5-2.5 m outside the footprint), ft NAVD88
    srcs = [rasterio.open(f) for f in sorted((D / "harris_mini" / "NYC_SI").glob("*.tif"))]
    stats = []
    for g in h.geom:
        ring, far = g.buffer(2.5).difference(g.buffer(0.5)), g.buffer(30).difference(g.buffer(10))
        out = {}
        for s in srcs:
            b = s.bounds
            x0, y0, x1, y1 = g.buffer(31).bounds
            if not (b.left < x0 and x1 < b.right and b.bottom < y0 and y1 < b.top):
                continue
            win = rasterio.windows.from_bounds(x0, y0, x1, y1, s.transform).round_offsets().round_lengths()
            a = s.read(1, window=win).astype("float64")
            a[(a < -1e5) | (a > 1e5)] = np.nan
            tr = s.window_transform(win)
            def vals(geom):
                m = ~geometry_mask([mapping(geom)], a.shape, tr)
                v = a[m]; return v[np.isfinite(v)] / USFT
            v, vi, vf = vals(ring), vals(g), vals(far)
            if v.size >= 5:
                out = dict(e2018_lag=v.min(), e2018_p10=np.percentile(v, 10), e2018_med=np.median(v), e2018_hag=v.max(),
                           e2018_inside=np.median(vi) if vi.size else np.nan, e2018_far=np.median(vf) if vf.size else np.nan)
            break
        stats.append(out)
    h = pd.concat([h, pd.DataFrame(stats)], axis=1)
    h = h[h.e2018_lag.notna()].reset_index(drop=True)
    h["ffe"] = h.z_floor
    h["ffh"] = h.ffe - h.e2018_lag
    c = h.geom.map(lambda g: g.centroid)
    h["x"], h["y"] = c.map(lambda p: p.x), c.map(lambda p: p.y)
    h["fp_area_m2"] = h.geom.map(lambda g: g.area)
    h["year_built"] = pd.to_numeric(h.construction_year, errors="coerce")
    for k in ("p10", "med", "hag", "inside", "far"):
        h[f"g_{k}"] = h[f"e2018_{k}"] - h.e2018_lag
    h["nsi_ft"] = h.nsi_found_type.map(FT)
    h["nsi_year"] = pd.to_numeric(h.nsi_year, errors="coerce"); h["nsi_stories"] = pd.to_numeric(h.nsi_stories, errors="coerce")
    h["nsi_found_ht"] = pd.to_numeric(h.nsi_found_ht, errors="coerce"); h["nsi_ground"] = pd.to_numeric(h.nsi_ground, errors="coerce")
    h["block"] = (h.x // 1000).astype(int).astype(str) + "_" + (h.y // 1000).astype(int).astype(str)
    print(f"Staten Island east shore: {len(h)} single-family buildings measured by BES, with a footprint, NSI and lidar")
    print(f"datum check: BES grade minus lidar lowest ring grade, median {np.median(h.z_grade - h.e2018_lag):.2f} ft "
          f"(q10/q90 {np.percentile(h.z_grade - h.e2018_lag, 10):.2f} / {np.percentile(h.z_grade - h.e2018_lag, 90):.2f})")
    print(f"first floor above lidar LAG: q10/50/90 {np.percentile(h.ffh, [10, 50, 90]).round(2)}; subgrade Y {h.subgrade.eq('Y').mean():.0%}; "
          f"NSI types {h.nsi_found_type.value_counts().to_dict()}")
    est = pd.DataFrame(index=h.index)
    est["national (NSI + lidar median grade)"] = h.e2018_med + h.nsi_found_ht
    est["NSI only"] = h.nsi_ground + h.nsi_found_ht
    harris = pd.concat([ec.load("B"), ec.load("C")])
    harris = harris[harris.tier != "C"]
    g = lgb.LGBMRegressor(**ev.P).fit(harris[ec.NAT], harris.ffh)
    est["model trained in Harris"] = h.e2018_lag + g.predict(h[ec.NAT])
    rng = np.random.default_rng(0)
    pool = h[rng.random(len(h)) < 0.10]
    est["local const (10% measured)"] = h.e2018_lag + pool.ffh.median()
    nb = ev.nb_feats(pool, h)
    X = lambda d: pd.concat([d[ev.BASE + ev.GROUND], nb.loc[d.index, ["nb_ffh_med", "nb_ffh_idw", "nb_ffh_std", "nb_n", "nb_dist"]]], axis=1)
    m = lgb.LGBMRegressor(**ev.P).fit(X(pool), pool.ffh)
    est["neighbours (10% measured)"] = h.e2018_lag + m.predict(X(h))
    test = ~h.index.isin(pool.index)
    print("\n## First-floor elevation error (ft), houses not in the 10% pool\n")
    print(pd.DataFrame({k: metrics((v - h.ffe)[test]) for k, v in est.items()}).T.round(3).to_markdown())
    for name, mask in (("no basement (subgrade N)", h.subgrade.eq("N")), ("basement/subgrade (Y)", h.subgrade.eq("Y")),
                       ("raised: floor > 6 ft above LAG", h.ffh > 6)):
        mm = test & mask
        print(f"\n### {name}: n {int(mm.sum())}")
        print(pd.DataFrame({k: metrics((v - h.ffe)[mm]) for k, v in est.items()}).T[["n", "MAE", "within_1", "bias"]].round(3).to_markdown())
    print("\nNSI foundation type vs measured floor height above LAG (median ft):")
    print(h.groupby("nsi_found_type").agg(n=("ffh", "size"), measured_ffh_median=("ffh", "median"), nsi_default=("nsi_found_ht", "median"),
                                          subgrade_share=("subgrade", lambda s: (s == "Y").mean())).round(2).to_markdown())
    h.drop(columns=["geom", "the_geom"], errors="ignore").to_parquet(D / "nyc" / "nyc_scored.parquet")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
