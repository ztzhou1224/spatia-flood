"""Does what the lidar POINT CLOUD saw of each house find raised houses and measure the front-door height?

Answer key: HCFCD front-door FFE (scorer only), precision tiers A+B; target = door height above the DEM lowest
adjacent grade (e2018_lag). Features never include the answer key or anything derived from it:
  dem        year built, footprint area, DEM ring stats (as evaluate.py) + NSI foundation type / height / stories
  dem + lpc  plus lpc_features.py (roof / eave heights, ground seen under the roof, low structures in a 3 m ring)
LightGBM (as evaluate.py), 5 folds grouped by 1 km block inside the area; no neighbour certificates.
Also: how well single point-cloud measures separate raised houses (door > 3 ft above ground), as ROC AUC.
Usage: python eval_lpc.py AREA
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
FT = {"S": 0, "C": 1, "B": 2, "P": 3, "I": 4, "W": 5}
P = dict(objective="l1", n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=30,
         subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
LPC = ["bldg_share", "roof_p05", "roof_p50", "roof_p95", "eave_p10", "eave_p50", "ground_in_share", "ring_low_share",
       "ring_low_p90", "pts_m2"]


def metrics(err, y):
    e, r = np.abs(err), y > 3
    return {"n": len(e), "MAE": e.mean(), "within_1": (e <= 1).mean(), "raised_n": int(r.sum()),
            "raised_MAE": e[r].mean(), "not_raised_MAE": e[~r].mean()}


def main(area):
    f = pd.read_parquet(D / area / "coverage_features.parquet")
    f = f[f.prec <= 6].copy()
    f["y"] = f.ffe - f.e2018_lag  # scorer only
    for c in ("p10", "med", "hag", "inside", "far"):
        f[f"g_{c}"] = f[f"e2018_{c}"] - f.e2018_lag
    f["nsi_ft"] = f.nsi_found_type.map(FT)
    for c in ("nsi_found_ht", "nsi_stories", "year_built"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f = f.merge(pd.read_parquet(D / area / "lpc_features.parquet"), on="oid", how="left").reset_index(drop=True)
    dem = ["year_built", "fp_area_m2", "g_p10", "g_med", "g_hag", "g_inside", "g_far", "nsi_ft", "nsi_found_ht",
           "nsi_stories"]
    f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    print(f"{area}: {len(f)} houses (tiers A+B); point cloud seen the roof of {f.roof_p50.notna().mean():.1%}; "
          f"raised (door > 3 ft) {int((f.y > 3).sum())}; blocks {f.block.nunique()}")
    preds = {}
    for name, cols in (("dem", dem), ("dem + lpc", dem + LPC)):
        p = np.full(len(f), np.nan)
        for tr, te in GroupKFold(5).split(f, groups=f.block):
            p[te] = lgb.LGBMRegressor(**P).fit(f.loc[tr, cols], f.y.iloc[tr]).predict(f.loc[te, cols])
        preds[name] = p
    res = pd.DataFrame({k: metrics(p - f.y.values, f.y.values) for k, p in preds.items()}).T
    print("\n## Door height above ground, 5-fold by 1 km block (ft)\n")
    print(res.round(3).to_markdown())
    print("\n## Raised-house detection (door > 3 ft) from the predicted height > 3 ft\n")
    rows = {}
    for k, p in preds.items():
        tp, fp, fn = ((p > 3) & (f.y > 3)).sum(), ((p > 3) & (f.y <= 3)).sum(), ((p <= 3) & (f.y > 3)).sum()
        rows[k] = {"flagged": int(tp + fp), "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1)}
    print(pd.DataFrame(rows).T.round(3).to_markdown())
    print("\n## Single measures: ROC AUC for raised (door > 3 ft), houses with the measure\n")
    auc = {}
    for c in LPC + ["nsi_found_ht", "g_inside"]:
        m = f[c].notna()
        if m.sum() > 50 and (f.y[m] > 3).nunique() == 2:
            auc[c] = {"n": int(m.sum()), "AUC": roc_auc_score(f.y[m] > 3, f[c][m])}
    print(pd.DataFrame(auc).T.round(3).to_markdown())
    print("\nmedian measures, raised vs not raised:\n")
    print(f.groupby(f.y > 3)[LPC].median().T.round(2).rename(columns={False: "not raised", True: "raised"}).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1])
