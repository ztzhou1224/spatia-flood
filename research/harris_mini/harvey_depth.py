"""Floor vs simulated Harvey water level, per answer-key house.

Water: PRIMo hindcast of Harvey (Schubert et al., UC Irvine; Zenodo 7011402, CC0), HU10.tif, max
depth (m) 2017-08-26..30, ~3 m grid, EPSG:4269, NAVD88. Read by HTTP range for the area only.
Ground: our 2018 3DEP 1 m DEM, reprojected onto the hindcast grid (average), GEOID12B.
Per house, over hindcast cells within 10 m of the footprint (outside it):
  depth_max_ft = max simulated depth; wse_ft = median over wet cells of (depth + ground), NAVD88 ft.
Then: water above the measured front-door floor (wse - ffe) and above our ESTIMATED floor
(lidar LAG + median door height of the 5 nearest 10%-pool houses; the house itself never used).
Flood labels from HCFCD layer 22, Harvey, matched to footprints within 25 m (as harvey.py).
Usage: python harvey_depth.py AREA [AREA ...]
"""
import glob, json, sys
from pathlib import Path
import numpy as np, pandas as pd, rasterio
from rasterio.features import geometry_mask
from rasterio.warp import reproject, Resampling, transform_geom
from rasterio.windows import from_bounds
from shapely import wkt as swkt
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree
from sklearn.metrics import roc_auc_score
from sklearn.neighbors import KDTree

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
HC = "/vsicurl/https://zenodo.org/records/7011402/files/HU10.tif"
USFT = 1200 / 3937

def flooded_hcads(area):
    import harvey  # reuse the footprint matching
    fl = pd.read_parquet(D / area / "l22.parquet")
    si = pd.read_parquet(D / area / "l24.parquet"); si = si[si.WWCStrucType == "SFR"].copy()
    fp = pd.read_parquet(D / area / "l26.parquet")
    fpg = {o: harvey.esri_poly(json.dumps({"rings": json.loads(r)})) for o, r in zip(fp.outline_id, fp.rings) if r}
    geoms = [fpg.get(o) or Point(x, y) for o, x, y in zip(si.outline_id, si.gx, si.gy)]
    tree = STRtree(geoms); out = set()
    for x, y, e in zip(fl.gx, fl.gy, fl.Event):
        if e != "Harvey": continue
        j = tree.query_nearest(Point(x, y), max_distance=25)
        if len(j): out.add(si.HCAD_NUM.values[j[0]])
    return out

def main(area):
    h = pd.read_parquet(D / area / "houses.parquet")
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].copy()
    fps = [swkt.loads(w) for w in h.fp_wkt]
    rings = [f.buffer(10).difference(f) for f in fps]
    rings_ll = [shape(transform_geom("EPSG:6344", "EPSG:4269", mapping(r))) for r in rings]
    x0 = min(r.bounds[0] for r in rings_ll) - 0.002; y0 = min(r.bounds[1] for r in rings_ll) - 0.002
    x1 = max(r.bounds[2] for r in rings_ll) + 0.002; y1 = max(r.bounds[3] for r in rings_ll) + 0.002
    with rasterio.open(HC) as src:
        win = from_bounds(x0, y0, x1, y1, src.transform).round_offsets().round_lengths()
        dep = src.read(1, window=win).astype("float64"); tr = src.window_transform(win)
        dep[(dep < 0) | (dep > 1e3)] = 0.0
    ground = np.full(dep.shape, np.nan)
    for f in glob.glob(str(D / area / "*2018*.tif")):
        with rasterio.open(f) as s:
            tmp = np.full(dep.shape, np.nan)
            reproject(rasterio.band(s, 1), tmp, dst_transform=tr, dst_crs="EPSG:4269",
                      dst_nodata=np.nan, resampling=Resampling.average)
            ground = np.where(np.isfinite(tmp), tmp, ground)
    dep_ft, ground_ft = dep / USFT, ground / USFT
    dmax, wse = [], []
    for r in rings_ll:
        m = ~geometry_mask([mapping(r)], dep.shape, tr, all_touched=True)
        d, g = dep_ft[m], ground_ft[m]
        dmax.append(d.max() if d.size else np.nan)
        wet = (d > 0.05) & np.isfinite(g)
        wse.append(np.median(d[wet] + g[wet]) if wet.any() else np.nan)
    h["hc_depth_max"], h["hc_wse"] = dmax, wse
    h["flooded"] = h.hcad.isin(flooded_hcads(area))
    h["ffh"] = h.ffe - h.e2018_lag
    rng = np.random.default_rng(0); pool = rng.random(len(h)) < 0.10
    pts = h[["x", "y"]].values; tree = KDTree(pts[pool]); _, idx = tree.query(pts, k=6)
    pf, pidx = h.ffh.values[pool], np.where(pool)[0]
    h["ffe_est"] = h.e2018_lag + np.array([np.median([pf[j] for j in row if pidx[j] != i][:5]) for i, row in enumerate(idx)])
    # dry houses: water margin = -(floor - ground) - 0 (no simulated water) -> use depth-based fill
    h["water_over_floor"] = np.where(np.isfinite(h.hc_wse), h.hc_wse - h.ffe, -(h.ffh) - 1)
    h["water_over_est_floor"] = np.where(np.isfinite(h.hc_wse), h.hc_wse - h.ffe_est, -(h.ffe_est - h.e2018_lag) - 1)
    y = h.flooded.astype(int)
    print(f"\n## Area {area}: {len(h)} answer-key houses, Harvey-flooded {y.sum()} ({y.mean():.1%}); "
          f"simulated wet within 10 m: {np.isfinite(h.hc_wse).mean():.1%}")
    res = {}
    for k in ("hc_depth_max", "water_over_floor", "water_over_est_floor"):
        res[k] = roc_auc_score(y, h[k])
    print("\nAUC (0.5 = no skill)"); print(pd.Series(res).round(3).to_markdown())
    for k, lab in (("water_over_floor", "measured floor"), ("water_over_est_floor", "ESTIMATED floor")):
        g = pd.cut(h[k], [-100, -1, 0, 0.5, 1, 2, 4, 100])
        t = h.groupby(g, observed=True).flooded.agg(["size", "mean"]).rename(columns={"size": "houses", "mean": "flood_rate"})
        print(f"\nFlood rate by simulated Harvey water minus {lab} (ft; dry houses in the lowest bin)"); print(t.round(3).to_markdown())
        pred = h[k] > 0
        tp, fp_, fn = (pred & h.flooded).sum(), (pred & ~h.flooded).sum(), (~pred & h.flooded).sum()
        print(f"'water above {lab}' as a flood call: precision {tp / max(tp + fp_, 1):.2f}, recall {tp / max(tp + fn, 1):.2f} "
              f"(called {pred.sum()}, flooded {h.flooded.sum()})")
    out = D / area / "harvey_houses.parquet"; h.drop(columns=["fp_wkt"]).to_parquet(out)

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    pd.set_option("display.width", 200)
    for a in sys.argv[1:]: main(a)
