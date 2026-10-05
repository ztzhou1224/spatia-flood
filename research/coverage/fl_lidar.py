"""Florida benchmark, part 2: does 1 m lidar ground fix the ground error?

Certificates (answer key, scorer only) inside 8 USGS 1 m DEM tiles (the tiles holding the most
certificates: Lee, Collier, Broward, Pinellas, Pasco). For each: the Overture footprint holding the NSI
building point (else the certificate point; else nearest within 10 m), lidar ground in a 0.5-2.5 m ring
outside it (lowest, 10th percentile, median; ft NAVD88 from metres).
Floor height above ground: a GBM trained on certificates in OTHER counties (target = floor - certificate
LAG; national features only: NSI foundation type and height, stories, year built, SFHA / V zone, BFE - NSI
ground, living area). FFE = ground + predicted height, with ground from
  NSI 10 m DEM | lidar ring lowest | lidar ring 10th pct | lidar ring median | certificate LAG (best case).
Usage: python fl_lidar.py
"""
import glob
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from shapely import wkt
from shapely.geometry import Point, mapping
from shapely.strtree import STRtree
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import KDTree

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data" / "fl"
EC = ROOT / "data" / "fl" / "ec_joined.parquet"  # written by ec_backtest/join2.py, run in data/fl
FT = {"S": 0, "C": 1, "B": 2, "P": 3, "I": 4, "W": 5}
USFT = 1200 / 3937


def load():
    ec = pd.read_parquet(EC)
    t = Transformer.from_crs("EPSG:4326", "EPSG:3086", always_xy=True)
    ec["X"], ec["Y"] = t.transform(ec.lon.values, ec.lat.values)
    nsi = pd.read_parquet(D / "nsi_fl.parquet")
    nsi = nsi[nsi.occtype.str.startswith("RES")].reset_index(drop=True)
    nsi["X"], nsi["Y"] = t.transform(nsi.x.values, nsi.y.values)
    dist, idx = KDTree(nsi[["X", "Y"]].values).query(ec[["X", "Y"]].values, k=1)
    ec["nsi_dist"] = dist[:, 0]
    for c in ("found_type", "found_ht", "num_story", "med_yr_blt", "ground_elv", "x", "y"):
        ec["nsi_" + c] = nsi[c].values[idx[:, 0]]
    ec = ec[ec.nsi_dist <= 30].copy()
    ec["county_fips"] = ec.county_fips.astype("string").fillna(
        "g" + (ec.lat // 0.5).astype(int).astype(str) + "_" + (ec.lon // 0.5).astype(int).astype(str))
    ec["floor"] = ec.topOfBottomFloor.astype(float); ec["lag"] = ec.lowestAdjacentGrade.astype(float)
    ec["bfe"] = pd.to_numeric(ec.baseFloodElevation, errors="coerce")
    ec["year"] = pd.to_numeric(ec.act_yr_blt, errors="coerce").fillna(pd.to_numeric(ec.nsi_med_yr_blt, errors="coerce"))
    ec["sfha"] = ec.floodZone.astype(str).str.upper().str.match(r"^(A|V)")
    d = ec.buildingDiagramNumber.astype(str).str.upper().str.strip()
    ec["dgroup"] = d.map(lambda x: "1A slab" if x.startswith("1A") else "1B raised slab" if x.startswith("1B")
                         else "8 crawlspace" if x.startswith("8") else "5-7 elevated" if x[:1] in "567" else "other")
    return ec


def features(ec):
    return pd.DataFrame({"ft": ec.nsi_found_type.map(FT), "fh": ec.nsi_found_ht, "stories": pd.to_numeric(ec.nsi_num_story, errors="coerce"),
                         "year": ec.year, "bfe_minus_ground": ec.bfe - ec.nsi_ground_elv, "sfha": ec.sfha.astype(float),
                         "ve": ec.floodZone.astype(str).str.upper().str.startswith("V").astype(float),
                         "liv_area": pd.to_numeric(ec.tot_lvg_ar, errors="coerce")}, index=ec.index)


def lidar_ground(ec):
    tiles = pd.read_csv(D / "tile_urls.csv")
    to17 = Transformer.from_crs("EPSG:4326", "EPSG:26917", always_xy=True)
    ex, ey = to17.transform(ec.lon.values, ec.lat.values)
    nx, ny = to17.transform(ec.nsi_x.values, ec.nsi_y.values)
    ec = ec.assign(ex=ex, ey=ey, nx=nx, ny=ny, tx=(ex // 10000).astype(int), ty=np.ceil(ey / 10000).astype(int))
    rows = []
    for t in tiles.itertuples():
        sub = ec[(ec.tx == t.tx) & (ec.ty == t.ty)]
        if sub.empty:
            continue
        fps = [wkt.loads(w) for w in pd.read_parquet(D / f"footprints_{t.tx}_{t.ty}.parquet").wkt]
        fps = [g.buffer(0) for g in fps if g.geom_type in ("Polygon", "MultiPolygon")]
        tree = STRtree(fps)
        src = rasterio.open(glob.glob(str(D / "dem" / f"*x{t.tx}y{t.ty}*.tif"))[0])
        for i, r in sub.iterrows():
            fp = None
            for p in (Point(r.nx, r.ny), Point(r.ex, r.ey)):
                j = tree.query(p, predicate="within")
                j = tree.query(p, predicate="intersects") if not len(j) else j
                if len(j):
                    fp = fps[j[0]]; break
            if fp is None:
                j = tree.query_nearest(Point(r.ex, r.ey), max_distance=10)
                fp = fps[j[0]] if len(j) else None
            if fp is None or fp.area > 2000:
                continue
            ring = fp.buffer(2.5).difference(fp.buffer(0.5))
            x0, y0, x1, y1 = ring.bounds
            win = rasterio.windows.from_bounds(x0, y0, x1, y1, src.transform).round_offsets().round_lengths()
            a = src.read(1, window=win, boundless=True, fill_value=np.nan).astype("float64")
            a[(a < -1e5) | (a > 1e5)] = np.nan
            m = ~geometry_mask([mapping(ring)], a.shape, src.window_transform(win))
            v = a[m]; v = v[np.isfinite(v)] / USFT
            if v.size >= 5:
                rows.append(dict(idx=i, l_min=v.min(), l_p10=np.percentile(v, 10), l_med=np.median(v), fp_area=fp.area,
                                 project=Path(src.name).stem))
    return pd.DataFrame(rows).set_index("idx")


def metrics(est, ec):
    e = (est - ec.floor).dropna()
    ok = est.notna() & ec.bfe.notna()
    right = ((est[ok] >= ec.bfe[ok]) == (ec.floor[ok] >= ec.bfe[ok])).mean()
    return dict(n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(), within_1=(e.abs() <= 1).mean(),
                p90=e.abs().quantile(0.9), bias=e.mean(), above_below_right=right)


def main():
    ec = load()
    X = features(ec)
    y = ec.floor - ec.lag
    P = dict(objective="l1", n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8,
             subsample_freq=1, colsample_bytree=0.8, verbose=-1)
    ffh = pd.Series(np.nan, index=ec.index)
    for tr, te in GroupKFold(5).split(X, groups=ec.county_fips):
        ffh.iloc[te] = lgb.LGBMRegressor(**P).fit(X.iloc[tr], y.iloc[tr]).predict(X.iloc[te])
    g = lidar_ground(ec)
    t = ec.loc[g.index].join(g)
    f = ffh.loc[g.index]
    print(f"certificates in the 8 lidar tiles with a footprint and lidar ring: {len(t)}; projects {t.project.value_counts().to_dict()}")
    for c in ("l_min", "l_p10", "l_med"):
        print(f"ground check {c} - certificate LAG: median {np.median(t[c] - t.lag):+.2f} ft, MAE {np.mean(np.abs(t[c] - t.lag)):.2f}")
    print(f"ground check NSI 10 m - certificate LAG: median {np.median(t.nsi_ground_elv - t.lag):+.2f} ft, MAE {np.mean(np.abs(t.nsi_ground_elv - t.lag)):.2f}")
    est = {"NSI 10 m ground + model height": t.nsi_ground_elv + f, "lidar ring lowest + model height": t.l_min + f,
           "lidar ring 10th pct + model height": t.l_p10 + f, "lidar ring median + model height": t.l_med + f,
           "certificate LAG (perfect ground) + model height": t.lag + f}
    print("\n## Lowest floor error (ft) on these certificates; model height trained in other counties\n")
    print(pd.DataFrame({k: metrics(v, t) for k, v in est.items()}).T.round(3).to_markdown())
    for gname in ("1A slab", "1B raised slab", "5-7 elevated", "8 crawlspace"):
        mm = t.dgroup == gname
        print(f"\n### {gname}: n {int(mm.sum())}")
        print(pd.DataFrame({k: metrics(v[mm], t[mm]) for k, v in est.items()}).T[["n", "MAE", "within_1", "bias", "above_below_right"]].round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
