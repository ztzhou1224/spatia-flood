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
            "raised_n": int((r & np.isfinite(e)).sum()), "raised_MAE": np.nanmean(e[r]), "not_raised_MAE": np.nanmean(e[~r])}


def detect(pred, y):
    m = np.isfinite(pred)  # count only houses the method gives a value for
    pred, y = pred[m], y[m]
    tp, fp, fn = ((pred > 3) & (y > 3)).sum(), ((pred > 3) & (y <= 3)).sum(), ((pred <= 3) & (y > 3)).sum()
    return {"flagged": int(tp + fp), "precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1)}


def boot_ci(err, y, blocks, reps=1000, seed=0):
    """95% block-bootstrap interval (resample 1 km blocks) of MAE and raised-house MAE."""
    rng = np.random.default_rng(seed)
    d = pd.DataFrame({"e": np.abs(err), "r": y > 3, "b": blocks}).dropna(subset=["e"])
    g = {b: x for b, x in d.groupby("b")}
    keys = list(g)
    mae, rmae = [], []
    for _ in range(reps):
        s = pd.concat([g[k] for k in rng.choice(keys, len(keys))])
        mae.append(s.e.mean())
        rmae.append(s.e[s.r].mean() if s.r.any() else np.nan)
    q = lambda v: f"{np.nanpercentile(v, 2.5):.2f}-{np.nanpercentile(v, 97.5):.2f}"
    return {"MAE_95ci": q(mae), "raised_MAE_95ci": q(rmae)}


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
    f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    # scorer-side consistency screen of the ANSWER KEY (never used to choose training rows): a front door within 6 ft
    # of the roof top (roof p95) cannot be a living floor, and a door > 1 ft below the adjacent grade is a mismatch
    f["key_ok"] = ~((f.roof_p95 - f.dh < 6) | (f.dh < -1))
    print(f"{area}: {len(f)} houses; HCAD record {f.stories.notna().mean():.1%}; stories {f.stories.value_counts().to_dict()}; "
          f"raised (door > 3 ft) {int((f.dh > 3).sum())}; blocks {f.block.nunique()}; answer key fails the screen: "
          f"{int((~f.key_ok).sum())} ({int((~f.key_ok & (f.dh > 3)).sum())} raised, {int((f.dh < -1).sum())} below grade)")

    print("\n## Records alone: share raised (door > 3 ft) by HCAD foundation / lower level / stories\n")
    lvl = f.has_lower.map({1.0: "lower level", 0.0: "no lower"}).fillna("-")
    t = f.assign(raised=f.dh > 3).groupby([f.foundation.fillna("no record"), lvl, f.stories.fillna(0).astype(int)]).raised
    print(t.agg(["size", "sum", "mean"]).rename(columns={"size": "houses", "sum": "raised", "mean": "share"}).round(2).to_markdown())
    rec_flag = ((f.basement > 0) | (f.lower_any > 0) | f.foundation.str.contains("Basement", na=False)
                | ((f.foundation == "Crawl Space") & (f.stories == 2)))
    for nm, m in (("all", f.index == f.index), ("screened", f.key_ok)):
        tp = (rec_flag & (f.dh > 3) & m).sum()
        print(f"records flag (basement, lower level, or 2-story crawl space), {nm}: flagged {int((rec_flag & m).sum())}, "
              f"precision {tp / max((rec_flag & m).sum(), 1):.2f}, recall {tp / max(((f.dh > 3) & m).sum(), 1):.2f}")

    # typical eave of an ordinary slab house per story count, from the records + point cloud only (no answer key)
    ref = f[(f.foundation == "Slab") & (f.has_lower == 0)]
    for e in ("eave_p10", "eave_p50", "eave_main"):
        typ = ref.groupby("stories")[e].median()
        print(f"typical {e} of slab houses without a lower level (ft above ground): {typ.round(2).to_dict()}")
        f[f"est_{e}"] = f[e] - f.stories.map(typ) + SLAB_FT

    dem = ["year_built", "fp_area_m2", "g_p10", "g_med", "g_hag", "g_inside", "g_far", "nsi_ft", "nsi_found_ht",
           "nsi_stories"]
    rec = ["stories", "upper_base", "lower_any", "lower_base", "lower_garage", "basement", "fnd_crawl", "im_sq_ft", "base_ar"]
    sets = {"GBM dem": dem, "GBM dem + lpc": dem + el.LPC, "GBM dem + lpc + records": dem + el.LPC + rec,
            "GBM dem + lpc + records + eave estimates": dem + el.LPC + rec + ["est_eave_p50", "est_eave_main"]}
    preds = {f"eave - stories ({e})": f[f"est_{e}"].values for e in ("eave_p10", "eave_p50", "eave_main")}
    for name, cols in sets.items():
        p = np.full(len(f), np.nan)
        for tr, te in GroupKFold(5).split(f, groups=f.block):  # trained on ALL rows, screened or not
            p[te] = lgb.LGBMRegressor(**el.P).fit(f.loc[tr, cols], f.dh.iloc[tr]).predict(f.loc[te, cols])
        preds[name] = p
    # triage list for imagery (fixed before any image is read; label-free per house): out-of-fold prediction of the
    # full model > 2 ft, or an appraisal basement / lower level / two-story crawl space
    last = list(sets)[-1]
    tri = pd.DataFrame({"oid": f.oid, "pred": preds[last], "rec_flag": rec_flag.values,
                        "est_eave_p50": f.est_eave_p50, "est_eave_main": f.est_eave_main, "stories": f.stories})
    tri["flagged"] = (tri.pred > 2) | tri.rec_flag
    tri.to_parquet(D / "harris_mini" / area / "triage.parquet", index=False)
    print(f"\ntriage for imagery (pred > 2 ft or records flag): {int(tri.flagged.sum())} of {len(tri)} houses; "
          f"raised among them {int(((f.dh > 3) & tri.flagged).sum())} of {int((f.dh > 3).sum())}")
    for nm, m in (("all houses", np.ones(len(f), bool)), ("answer key passes the screen", f.key_ok.values)):
        rows = {k: {**score(p[m] - f.dh.values[m], f.dh.values[m]), **detect(p[m], f.dh.values[m]),
                    **boot_ci(p[m] - f.dh.values[m], f.dh.values[m], f.block.values[m])} for k, p in preds.items()}
        print(f"\n## Door height above ground (ft), raised detection (> 3 ft); GBM 5-fold by 1 km block; {nm}\n")
        print(pd.DataFrame(rows).T.round(3).to_markdown())
    r = f[(f.dh > 3) & f.key_ok]
    for e in ("eave_p50", "eave_main"):
        err = r[f"est_{e}"] - r.dh
        print(f"\nraised houses passing the screen, estimate from {e}, by HCAD stories: n {r.groupby('stories').size().to_dict()}, "
              f"median abs error {err.abs().groupby(r.stories).median().round(2).to_dict()}, "
              f"median signed error {err.groupby(r.stories).median().round(2).to_dict()}")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1])
