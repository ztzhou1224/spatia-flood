"""Check a lidar run over area P against the research features of the same houses (the code method E was scored on).

Research: data/harris_mini/P/houses.parquet (DEM ground e2018_*, footprints in EPSG:6442) and lpc_features.parquet
(point-cloud features), built by research/harris_mini/fl_build.py and lpc_features.py P. Run: the job.py output
(features.parquet) and its buildings.parquet. Houses are paired by footprint centroid within 0.5 m (both use Overture
footprints; releases may differ, unpaired houses are reported). The answer key (ffe) is not read.
Usage: python pipeline/lidar/check_trial.py RUN_DIR [features.parquet]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely import wkt as swkt

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / "data" / "harris_mini" / "P"
PAIRS = [("e2018_lag", "g_lag"), ("e2018_p10", "g_p10"), ("e2018_med", "g_med"), ("e2018_hag", "g_hag"),
         ("e2018_inside", "g_inside"), ("e2018_far", "g_far")]
LPC = ["n_in", "pts_m2", "bldg_share", "roof_p05", "roof_p50", "roof_p95", "eave_p10", "eave_p50", "eave_main", "ridge",
       "ground_in_share", "ring_low_share", "ring_low_p90"]


def main(run: Path, feats: str = "out_features.parquet") -> None:
    h = pd.read_parquet(P / "houses.parquet", columns=["oid", "fp_wkt"] + [a for a, _ in PAIRS])
    h = h.merge(pd.read_parquet(P / "lpc_features.parquet"), on="oid", how="left")
    hc = shapely.centroid(np.array([swkt.loads(w) for w in h.fp_wkt]))
    b = pd.read_parquet(run / "buildings.parquet")
    f = pd.read_parquet(run / feats)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
    g = shapely.transform(shapely.from_wkb(b.wkb.values), lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
    bc = shapely.centroid(g)
    d, j = cKDTree(np.c_[shapely.get_x(bc), shapely.get_y(bc)]).query(np.c_[shapely.get_x(hc), shapely.get_y(hc)])
    ok = d <= 0.5
    print(f"research houses {len(h)}; paired with a run building (centroid <= 0.5 m) {ok.sum()}")
    r, s = h[ok].reset_index(drop=True), f.iloc[j[ok]].reset_index(drop=True)
    print(f"run status of paired houses: ground {s.ground_status.value_counts().to_dict()}, "
          f"lpc {s.lpc_status.value_counts().to_dict()}")
    rows = []
    for a, c in PAIRS + [(k, k) for k in LPC]:
        x, y = r[a].astype(float), s[c].astype(float)
        both = x.notna() & y.notna()
        diff = (x - y)[both].abs()
        rows.append({"feature": c, "research_n": int(x.notna().sum()), "run_n": int(y.notna().sum()), "both": int(both.sum()),
                     "identical(<1e-6)": float((diff < 1e-6).mean()) if both.any() else np.nan,
                     "median_abs_diff": float(diff.median()) if both.any() else np.nan,
                     "p99_abs_diff": float(diff.quantile(0.99)) if both.any() else np.nan})
    print(pd.DataFrame(rows).round(4).to_string(index=False))
    print("run status, all buildings:", f.ground_status.value_counts().to_dict(), f.lpc_status.value_counts().to_dict())


if __name__ == "__main__":
    main(Path(sys.argv[1]), *sys.argv[2:])
