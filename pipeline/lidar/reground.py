"""Re-run only the DEM ground stage of a lidar run, locally, with the r1 mask (r1 plan docs/09 C1), into a new run.

Reads data/flood_v1/lidar/<run>/{buildings,features,tiles}.parquet|json and the run's 1 m DEM tiles (downloaded to
data/flood_v1/lidar/dem/ if missing, size-checked against tiles.json). Ground = job.ground with features.ground_stats
(water constant and < -1.5 ft cells masked). The point cloud is NOT re-run: its heights (LPC_HEIGHTS) were offsets from
the r0 ring minimum and are re-based arithmetically to the new base, the masked ring MEDIAN (owner decision Q3):
h_new = h_old + (lag_r0 - med_new). The two shares defined by height thresholds (ground_in_share, ring_low_share) keep
their r0 thresholds (relative to the r0 minimum); meta.json says so.
Checks before writing: the unmasked ring minimum must reproduce r0's g_lag on every building (same code path, nothing
masked), else the run stops.
Report (C1 acceptance): on certificate lots (train/certificates_<FIPS>.parquet, certificate LAG), certificate LAG minus
r0 ring minimum / new masked minimum / new masked median: median, MAE, share of certificate LAGs below the minimum.
Outputs: data/flood_v1/lidar/<out>/ (features.parquet, buildings.parquet, tiles.json, meta.json) and
pipeline/lidar/out/reground_<out>.json.
Usage: python pipeline/lidar/reground.py 12103 pinellas_2018 pinellas_2018_r1g [--workers N]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import shapely
from pyproj import CRS, Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import job
from features import WATER_FLOOR_FT

ROOT = Path(__file__).resolve().parents[2]
LIDAR = ROOT / "data" / "flood_v1" / "lidar"
LPC_HEIGHTS = ["roof_p05", "roof_p50", "roof_p95", "eave_p10", "eave_p50", "eave_main", "ridge", "ring_low_p90"]


def tiles(run: str) -> list[Path]:
    tl = json.loads((LIDAR / run / "tiles.json").read_text())
    d = LIDAR / "dem"
    d.mkdir(exist_ok=True)
    out = []
    for t in tl["dem"]:
        p = d / t["url"].rsplit("/", 1)[1]
        if not (p.exists() and p.stat().st_size == t["bytes"]):
            urllib.request.urlretrieve(t["url"], p)
        assert p.stat().st_size == t["bytes"], f"{p.name}: size differs from tiles.json"
        out.append(p)
    return out


def lag_check(fips: str, f: pd.DataFrame) -> dict:
    c = pd.read_parquet(ROOT / "data" / "flood_v1" / "train" / f"certificates_{fips}.parquet")
    d = c[["building_id", "cert_lag_ft"]].dropna().merge(f, on="building_id")
    res: dict = {"certificate_lots": len(d)}
    for name, col in (("r0 ring minimum", "lag_r0"), ("masked minimum", "g_lag"), ("masked median", "g_med")):
        e = (d.cert_lag_ft - d[col]).dropna()
        res[name] = {
            "n": len(e),
            "median_cert_minus_ground_ft": round(float(e.median()), 3),
            "MAE_ft": round(float(e.abs().mean()), 3),
            "share_cert_below_ground": round(float((e < 0).mean()), 3),
        }
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    job.setup_logging()
    src, dst = LIDAR / a.run, LIDAR / a.out
    b = pd.read_parquet(src / "buildings.parquet")
    old = pd.read_parquet(src / "features.parquet")
    assert (old.building_id.values == b.building_id.values).all(), "features and buildings out of order"
    paths = tiles(a.run)
    crs = set()
    for p in paths:
        with rasterio.open(p) as r:
            crs.add(CRS.from_user_input(r.crs).to_string())
    assert len(crs) == 1, crs
    dem = crs.pop()
    geoms = shapely.make_valid(shapely.from_wkb(b.wkb.values))
    to_dem = Transformer.from_crs("EPSG:4326", dem, always_xy=True)
    fp_dem = list(shapely.transform(geoms, lambda xy: np.c_[to_dem.transform(xy[:, 0], xy[:, 1])]))
    g = job.ground(fp_dem, paths, a.workers)

    # the unmasked minimum is r0's definition: it must reproduce r0 exactly
    diff = np.abs(g.lag_unmasked.values - old.g_lag.values)
    both = ~np.isnan(diff)
    mism = int((diff[both] > 1e-9).sum())
    assert mism == 0 and both.sum() == old.g_lag.notna().sum(), f"r0 g_lag not reproduced: {mism} differ"

    f = old.copy()
    f["lag_r0"] = old.g_lag
    for c in ("lag", "p10", "med", "hag", "inside", "far", "ring_n", "ring_n_masked", "lag_unmasked"):
        f[f"g_{c}"] = g[c].values
    f["ground_status"] = g.ground_status.values
    shift = f.lag_r0 - f.g_med  # r0 heights were above the r0 minimum; re-base to the masked median
    for c in LPC_HEIGHTS:
        f[c] = f[c] + shift
    dst.mkdir(parents=True, exist_ok=True)
    f.to_parquet(dst / "features.parquet", index=False)
    for n in ("buildings.parquet", "tiles.json"):
        shutil.copy2(src / n, dst / n)
    meta = json.loads((src / "meta.json").read_text())
    meta |= {
        "reground_from": a.run,
        "ground_mask": f"ring / inside / far cells < {WATER_FLOOR_FT} ft NAVD88 and the tile water constant",
        "water_constants_m": job.STATUS.get("water_constants_m"),
        "height_base": "g_med (masked ring median); LPC heights re-based h + (lag_r0 - g_med)",
        "shares_threshold_base": "ground_in_share, ring_low_share keep r0's thresholds above the r0 ring minimum",
        "ground_status": f.ground_status.value_counts().to_dict(),
    }
    (dst / "meta.json").write_text(json.dumps(meta, indent=1))
    rep = {
        "run": a.out,
        "buildings": len(f),
        "r0_g_lag_reproduced": int(both.sum()),
        "water_constants_m": meta["water_constants_m"],
        "ground_status": meta["ground_status"],
        "ring_cells_masked_any": int((f.g_ring_n_masked > 0).sum()),
        "ring_fully_masked_or_under_5": int((f.g_lag.isna() & old.g_lag.notna()).sum()),
        "lag_check": lag_check(a.fips, f),
    }
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    (out / f"reground_{a.out}.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
