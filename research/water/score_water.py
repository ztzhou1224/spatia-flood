"""Score a flood2d run against who flooded in Harvey (Cypress Creek, area B).

Per answer-key house: simulated max water-surface elevation = median over wet cells (simulated
depth > 0.05 m at the peak) within RING m of the footprint (outside it); dry houses get water below
the floor. Compared with the measured front-door floor (scoring only), the NATIONAL floor estimate
(NSI foundation height + 2018 lidar median ring grade, research/coverage), and the PRIMo hindcast on
the same houses. Labels: HCFCD flooded structures, Harvey (coverage_features.fl_harvey).
Usage: python score_water.py RUN_NAME [RING_M]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from shapely import wkt
from shapely.geometry import mapping
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data"
USFT = 1200 / 3937


def main(run, ring_m=15.0):
    out = D / "water" / run
    wse = rasterio.open(out / "wse_max_m.tif"); dem = rasterio.open(out / "dem_m.tif")
    W = wse.read(1); Z = dem.read(1)
    depth = np.where(W > -9000, W - Z, 0.0)
    h = pd.read_parquet(D / "harris_mini" / "B" / "houses.parquet", columns=["oid", "fp_wkt", "ffe", "e2018_lag", "e2018_med", "prec", "loc"])
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()]
    cov = pd.read_parquet(D / "harris_mini" / "B" / "coverage_features.parquet", columns=["oid", "fl_harvey", "fl_any", "nsi_found_ht"])
    h = h.merge(cov, on="oid")
    vals = []
    for w in h.fp_wkt:
        fp = wkt.loads(w)  # EPSG:6344 metres; DEM is EPSG:26915 (both NAD83 UTM 15N, sub-metre apart)
        r = fp.buffer(ring_m).difference(fp)
        b = r.bounds
        win = rasterio.windows.from_bounds(*b, wse.transform).round_offsets().round_lengths()
        try:
            sub_w = W[win.row_off: win.row_off + win.height, win.col_off: win.col_off + win.width]
            sub_d = depth[win.row_off: win.row_off + win.height, win.col_off: win.col_off + win.width]
            m = ~geometry_mask([mapping(r)], sub_w.shape, wse.window_transform(win), all_touched=True)
        except Exception:  # noqa: BLE001
            vals.append((np.nan, np.nan)); continue
        wet = m & (sub_d > 0.05)
        vals.append((np.median(sub_w[wet]) / USFT if wet.any() else np.nan, sub_d[m].max() / USFT if m.any() else np.nan))
    h["wse_ft"], h["depth_max_ft"] = [v[0] for v in vals], [v[1] for v in vals]
    h["floor_nat"] = h.e2018_med + h.nsi_found_ht
    for col, floor in (("over_measured", h.ffe), ("over_national", h.floor_nat)):
        h[col] = np.where(np.isfinite(h.wse_ft), h.wse_ft - floor, -(floor - h.e2018_lag) - 1)
    pr = pd.read_parquet(D / "harris_mini" / "B" / "harvey_houses.parquet", columns=["oid", "water_over_floor"])
    h = h.merge(pr, on="oid", how="left")
    y = h.fl_harvey.astype(int)
    rows = {"simulated depth next to the house": roc_auc_score(y, h.depth_max_ft.fillna(0)),
            "simulated water - measured floor": roc_auc_score(y, h.over_measured),
            "simulated water - NATIONAL floor": roc_auc_score(y, h.over_national.fillna(-10)),
            "PRIMo hindcast water - measured floor (reference)": roc_auc_score(y, h.water_over_floor.fillna(-10))}
    info = json.load(open(out / "run.json"))
    print(f"## {run}: dx {info['dx']} m, n {info['n']}, loss {info['loss_in_h']} in/h, IA {info['ia_in']} in; "
          f"wall {info['wall_s'] / 60:.1f} min; peak WSE at USGS 08068900 {info['peak_wse_chk_ft']:.2f} ft (observed 113.82)")
    print(f"houses {len(h)}, Harvey-flooded {int(y.sum())}; simulated wet within {ring_m:.0f} m: {np.isfinite(h.wse_ft).mean():.0%}")
    print(pd.Series(rows, name="ROC AUC").round(3).to_markdown())
    for col, lab in (("over_measured", "measured floor"), ("over_national", "national floor")):
        t = h.groupby(pd.cut(h[col], [-100, -1, 0, 0.5, 1, 2, 100]), observed=True).fl_harvey.agg(["size", "mean"])
        print(f"\nFlood rate by simulated water minus {lab} (ft):"); print(t.rename(columns={"size": "houses", "mean": "flooded"}).round(3).to_markdown())
        pred = h[col] > 0
        tp, fp_, fn = int((pred & h.fl_harvey).sum()), int((pred & ~h.fl_harvey).sum()), int((~pred & h.fl_harvey).sum())
        print(f"'water above floor' call: precision {tp / max(tp + fp_, 1):.2f}, recall {tp / max(tp + fn, 1):.2f}")
    h.drop(columns=["fp_wkt"]).to_parquet(out / "houses_scored.parquet")


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 15.0)
