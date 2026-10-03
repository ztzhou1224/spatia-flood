"""Score M3 v2 against the HCFCD answer key, next to lidar + neighbours, with raised houses reported apart.

Per-view checks (no answer key): status ok; door passed the 80-inch door-scale gate (0.75-1.33);
wall distance 8-45 m; when a house-mask ground line exists, implied camera height above the road
1.5-13 ft; door height above ground -1..20 ft (raised houses allowed). House filter: NSI occupancy
RES1 (single-family; drops condos/apartments mislabelled SFR).
Per-view estimate: ground from the house mask; the garage-door bottom when no house ground (variant
columns score each ground reference alone, and the door-scale distance). Per house: median of views.
FFE = 2018 lidar ground at the wall + estimate. Baseline and blend as eval_m3.py.
Usage: python eval_m3v2.py B C
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold

sys.path.insert(0, str(Path(__file__).parent))
import evaluate as ev  # noqa: E402

D = ev.D


def metrics(e):
    e = pd.Series(e).dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(), within_1=(e.abs() <= 1).mean(),
                p90=e.abs().quantile(0.9) if len(e) else np.nan, bias=e.mean())


def main(area):
    h = ev.load(area)
    m = pd.read_parquet(D / area / "m3_measure2.parquet")
    views = pd.read_parquet(D / area / "m3_views2.parquet")
    cov = pd.read_parquet(D / area / "coverage_features.parquet", columns=["oid", "nsi_occ"])
    st = m.status.str.split(":").str[0].value_counts().to_dict()
    k = m[m.status == "ok"].copy()
    k["cam_h_ft"] = (k.g_wall_ft - k.dz_ground_ft) - k.g_cam_ft
    ok = k.gated & k.R_m.between(8, 45) & (k.cam_h_ft.between(1.5, 13) | k.cam_h_ft.isna())
    k = k[ok].copy()
    k["ffh_view"] = k.ffh_house_ft.where(k.ffh_house_ft.notna(), k.ffh_garage_ft)
    k = k[k.ffh_view.between(-1, 20)]
    k = k.merge(cov, on="oid", how="left")
    k = k[k.nsi_occ.fillna("RES1").str.startswith("RES1")]
    per = k.groupby("oid").agg(ffh=("ffh_view", "median"), ffh_house=("ffh_house_ft", "median"),
                               ffh_garage=("ffh_garage_ft", "median"), ffh_ds=("ffh_doorscale_ft", "median"),
                               g_wall=("g_wall_ft", "median"), n_views=("image_id", "size"))
    for c in ("ffh", "ffh_house", "ffh_garage", "ffh_ds"):
        per[c.replace("ffh", "m3")] = per.g_wall + per[c]
    # baseline: 10% pool of houses not in the v2 image sample
    rng = np.random.default_rng(0)
    cand = h[~h.oid.isin(set(views.oid))]
    pool = cand[rng.random(len(cand)) < 0.10]
    nb = ev.nb_feats(pool, h)
    X = lambda d: pd.concat([d[ev.BASE + ev.GROUND], nb.loc[d.index, ["nb_ffh_med", "nb_ffh_idw", "nb_ffh_std", "nb_n", "nb_dist"]]], axis=1)
    gbm = lgb.LGBMRegressor(**ev.P).fit(X(pool), pool.ffh)
    t = h[h.oid.isin(per.index)].copy()
    t["base_ffe"] = t.e2018_lag + gbm.predict(X(t))
    t = t.join(per, on="oid")
    t = t[t.tier != "C"]
    t["blend"] = np.nan
    if len(t) >= 20:
        A = np.c_[t.m3 - t.e2018_lag, t.base_ffe - t.e2018_lag]; y = (t.ffe - t.e2018_lag).values
        for tr, te in KFold(5, shuffle=True, random_state=0).split(A):
            t.iloc[te, t.columns.get_loc("blend")] = t.e2018_lag.values[te] + LinearRegression().fit(A[tr], y[tr]).predict(A[te])
    sampled = len(pd.read_csv(D / area / "image_sample.csv"))
    print(f"\n## Area {area}")
    print(f"sampled {sampled}; houses with a v2 view {views.oid.nunique()}; views {len(m)} by status {st}; "
          f"views kept {len(k)}; **houses measured (A+B) {len(t)} = {len(t) / sampled:.1%} of sampled**")
    rows = {"lidar + neighbours (GBM)": metrics(t.base_ffe - t.ffe), "M3 v2 (house ground, garage fallback)": metrics(t.m3 - t.ffe),
            "  house-mask ground only": metrics(t.m3_house - t.ffe), "  garage-door ground only": metrics(t.m3_garage - t.ffe),
            "  door-scale distance": metrics(t.m3_ds - t.ffe), "blend (CV)": metrics(t.blend - t.ffe)}
    print(pd.DataFrame(rows).T.round(3).to_markdown())
    raised = (t.ffe - t.e2018_lag) > 3
    hh = h[h.tier != "C"]
    n_raised_sampled = int(((hh.ffe - hh.e2018_lag) > 3)[hh.oid.isin(pd.read_csv(D / area / "image_sample.csv").oid)].sum())
    print(f"\nRaised houses (true door > 3 ft above LAG): {n_raised_sampled} in the sample, {int(raised.sum())} measured")
    if raised.sum():
        print(pd.DataFrame({"lidar + neighbours": metrics((t.base_ffe - t.ffe)[raised]), "M3 v2": metrics((t.m3 - t.ffe)[raised]),
                            "blend": metrics((t.blend - t.ffe)[raised])}).T.round(3).to_markdown())
        pred = (t.m3 - t.e2018_lag) > 3
        tp, fp, fn = int((pred & raised).sum()), int((pred & ~raised).sum()), int((~pred & raised).sum())
        print(f"M3 'raised' call (> 3 ft): TP {tp}, FP {fp}, FN {fn}")
    t[["oid", "ffe", "e2018_lag", "base_ffe", "m3", "m3_house", "m3_garage", "m3_ds", "blend", "n_views"]].to_parquet(D / area / "m3v2_scored.parquet")


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    for a in sys.argv[1:]:
        main(a)
