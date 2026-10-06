"""Out-of-area test of the lidar point cloud + appraisal records method: train in one area, score in the other.

Areas B (Cypress Creek) and C (Clear Lake), tiers A+B; target = front-door height above the DEM lowest adjacent grade
(answer key, scorer only). Feature sets as eval_stories.py; LightGBM trained on ALL houses of the other area.
Also the eave-minus-stories estimates, calibrated per area without the answer key, and the per-story choice
suggested by area C (eave p50 for one-story, eave_main for two-story houses), tested here for the first time on B.
The answer-key screen of eval_stories.py is applied to the scored rows (reported both ways).
Usage: python eval_transfer.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from eval_stories import D, SLAB_FT, detect, score  # noqa: E402

DEM = ["year_built", "fp_area_m2", "g_p10", "g_med", "g_hag", "g_inside", "g_far", "nsi_ft", "nsi_found_ht", "nsi_stories"]
REC = ["stories", "upper_base", "lower_any", "lower_base", "lower_garage", "basement", "fnd_crawl", "im_sq_ft", "base_ar"]


def load(area, feats="lpc_features"):
    """feats: lpc_features file stem (lpc_features.py output; e.g. lpc_features_2024_single)."""
    f = pd.read_parquet(D / "harris_mini" / area / "coverage_features.parquet")
    f = f[f.prec <= 6].copy()
    f["dh"] = f.ffe - f.e2018_lag  # scorer only
    for c in ("p10", "med", "hag", "inside", "far"):
        f[f"g_{c}"] = f[f"e2018_{c}"] - f.e2018_lag
    f["nsi_ft"] = f.nsi_found_type.map(el.FT)
    for c in ("nsi_found_ht", "nsi_stories", "year_built"):
        f[c] = pd.to_numeric(f[c], errors="coerce")
    f = f.merge(pd.read_parquet(D / "harris_mini" / area / f"{feats}.parquet"), on="oid", how="left")
    f = f.merge(pd.read_parquet(D / "hcad" / "bld_2018.parquet").rename(columns={"acct": "hcad"}), on="hcad", how="left")
    f["has_lower"] = (f.lower_any > 0).astype(float).where(f.stories.notna())
    f["fnd_crawl"] = (f.foundation == "Crawl Space").astype(float).where(f.foundation.notna())
    f["key_ok"] = ~((f.roof_p95 - f.dh < 6) | (f.dh < -1))
    ref = f[(f.foundation == "Slab") & (f.has_lower == 0)]  # label-free calibration, per area
    for e in ("eave_p50", "eave_main"):
        f[f"est_{e}"] = f[e] - f.stories.map(ref.groupby("stories")[e].median()) + SLAB_FT
    f["est_split"] = np.where(f.stories == 1, f.est_eave_p50, f.est_eave_main)
    f["area"] = area
    return f.reset_index(drop=True)


def main():
    a = {k: load(k) for k in ("B", "C")}
    for k, f in a.items():
        print(f"{k}: {len(f)} houses; raised (door > 3 ft) {int((f.dh > 3).sum())}; HCAD record {f.stories.notna().mean():.1%}; "
              f"roof measured {f.roof_p50.notna().mean():.1%}; answer key fails the screen {int((~f.key_ok).sum())}")
    sets = {"dem": DEM, "dem + lpc": DEM + el.LPC, "dem + lpc + records": DEM + el.LPC + REC,
            "dem + lpc + records + eave estimates": DEM + el.LPC + REC + ["est_eave_p50", "est_eave_main"]}
    for tr, te in (("C", "B"), ("B", "C")):
        x, y = a[tr], a[te]
        preds = {f"eave - stories ({e})": y[f"est_{e}"].values for e in ("eave_p50", "eave_main", "split")}
        for nm, cols in sets.items():
            preds[f"GBM {nm}"] = lgb.LGBMRegressor(**el.P).fit(x[cols], x.dh).predict(y[cols])
        for lab, m in (("all", np.ones(len(y), bool)), ("screened", y.key_ok.values)):
            rows = {k: {**score(p[m] - y.dh.values[m], y.dh.values[m]), **detect(p[m], y.dh.values[m])} for k, p in preds.items()}
            print(f"\n## Trained on {tr}, scored on {te} ({lab}); door height above ground (ft), raised = door > 3 ft\n")
            print(pd.DataFrame(rows).T.round(3).to_markdown())
    for k, f in a.items():
        r = f[(f.dh > 3) & f.key_ok]
        for e in ("eave_p50", "eave_main", "split"):
            err = r[f"est_{e}"] - r.dh
            print(f"{k} raised houses (screened), {e}: n {r.groupby('stories').size().to_dict()}, median abs error "
                  f"{err.abs().groupby(r.stories).median().round(2).to_dict()}, median signed "
                  f"{err.groupby(r.stories).median().round(2).to_dict()}")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
