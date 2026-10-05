"""Floor height from eave height minus the height of the stories below it (records give the story count).

For a house that is not raised, the eave sits one or two story-heights above its floor. So:
  door height above ground  ~  eave height above ground - typical eave of a slab house with the same stories + 1 ft
The typical eave is calibrated WITHOUT the answer key: the median eave (point cloud, lpc_features.py) of houses whose
HCAD record says foundation = Slab and no lower level, per story count; + 1 ft is the NSI default slab floor height.
Inputs: lpc_features.parquet, data/hcad/bld_2018.parquet (hcad_buildings.py: stories, lower-level areas,
foundation), coverage_features (DEM, NSI). Answer key (HCFCD front door, tiers A+B): scorer only.
Reports: the records alone vs raised; the physical estimate (eave p10 and p50 versions); LightGBM with DEM + point
cloud (+ records, + the estimate), 5 folds by 1 km block, as eval_lpc.py.
Usage: python eval_stories.py AREA
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402

D = HERE.parents[1] / "data"
SLAB_FT = 1.0  # NSI default foundation height for slab


def score(err, y):
    e, r = np.abs(err), y > 3
    return {"n": int(np.isfinite(e).sum()), "MAE": np.nanmean(e), "within_1": np.nanmean(e <= 1),
            "raised_MAE": np.nanmean(e[r]), "not_raised_MAE": np.nanmean(e[~r])}


def detect(pred, y):
    tp, fp, fn = ((pred > 3) & (y > 3)).sum(), ((pred > 3) & (y <= 3)).sum(), ((pred <= 3) & (y > 3)).sum()
    return {"flagged": int(tp + fp), "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1)}


def main(area):
    f = pd.read_parquet(D / "harris_mini" / area / "coverage_features.parquet")
    f = f[f.prec <= 6].copy()
    f["dh"] = f.ffe - f.e2018_lag  # door height above ground: scorer only
    for c in ("p10", "med", "hag", "inside", "far"):
        f[f"g_{c}"] = f[f"e2018_{c}"] - f.e2018_lag
    f["nsi_ft"] = f.nsi_found_type.map(el.FT)
    for c in ("nsi_found_ht", "nsi_stories", "year_built"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f = f.merge(pd.read_parquet(D / "harris_mini" / area / "lpc_features.parquet"), on="oid", how="left")
    b = pd.read_parquet(D / "hcad" / "bld_2018.parquet").rename(columns={"acct": "hcad"})
    f = f.merge(b, on="hcad", how="left").reset_index(drop=True)
    f["has_lower"] = (f.lower_any > 0).astype(float).where(f.stories.notna())
    f["fnd_crawl"] = (f.foundation == "Crawl Space").astype(float).where(f.foundation.notna())
    print(f"{area}: {len(f)} houses; HCAD record {f.stories.notna().mean():.1%}; stories {f.stories.value_counts().to_dict()}; "
          f"raised (door > 3 ft) {int((f.dh > 3).sum())}")

    print("\n## Records alone: share raised (door > 3 ft) by HCAD foundation / lower level / stories\n")
    t = f.assign(raised=f.dh > 3).groupby([f.foundation.fillna("no record"), f.has_lower.map({1.0: "lower level", 0.0: "no lower"}).fillna("-"),
                                          f.stories.fillna(0).astype(int)]).raised.agg(["size", "sum", "mean"])
    print(t.rename(columns={"size": "houses", "sum": "raised", "mean": "share"}).round(2).to_markdown())

    # typical eave of an ordinary slab house per story count, from the records + point cloud only (no answer key)
    ref = f[(f.foundation == "Slab") & (f.has_lower == 0)]
    rows, est = {}, {}
    for e in ("eave_p10", "eave_p50"):
        typ = ref.groupby("stories")[e].median()
        print(f"\ntypical {e} of slab houses without a lower level (ft above ground): {typ.round(2).to_dict()}")
        est[e] = f[e] - f.stories.map(typ) + SLAB_FT
        f[f"est_{e}"] = est[e]
        rows[f"eave - stories ({e})"] = {**score(est[e] - f.dh, f.dh), **detect(est[e].fillna(-9), f.dh)}

    dem = ["year_built", "fp_area_m2", "g_p10", "g_med", "g_hag", "g_inside", "g_far", "nsi_ft", "nsi_found_ht", "nsi_stories"]
    rec = ["stories", "upper_base", "lower_any", "lower_base", "lower_garage", "fnd_crawl", "im_sq_ft", "base_ar"]
    sets = {"GBM dem": dem, "GBM dem + lpc": dem + el.LPC, "GBM dem + lpc + records": dem + el.LPC + rec,
            "GBM dem + lpc + records + eave estimate": dem + el.LPC + rec + ["est_eave_p10", "est_eave_p50"]}
    f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    for name, cols in sets.items():
        p = np.full(len(f), np.nan)
        for tr, te in GroupKFold(5).split(f, groups=f.block):
            p[te] = lgb.LGBMRegressor(**el.P).fit(f.loc[tr, cols], f.dh.iloc[tr]).predict(f.loc[te, cols])
        rows[name] = {**score(p - f.dh.values, f.dh.values), **detect(p, f.dh.values)}
    print("\n## Door height above ground (ft) and raised detection (> 3 ft); GBM 5-fold by 1 km block\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())
    r = f[f.dh > 3]
    print("\nraised houses: estimate (eave p50) vs truth, by HCAD stories (median abs error, ft):",
          (r.est_eave_p50 - r.dh).abs().groupby(r.stories).median().round(2).to_dict(),
          "| median signed error:", (r.est_eave_p50 - r.dh).groupby(r.stories).median().round(2).to_dict())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1])
