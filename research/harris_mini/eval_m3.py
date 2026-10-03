"""Score M3 (street-image door measurement) against the HCFCD answer key, next to lidar + neighbours.

Per view (m3_measure.parquet) keep a measurement only if it passes geometry checks that use no
answer key: status ok, wall distance 8-45 m, door score >= 0.3, implied camera height above the
road under the camera 1.5-13 ft (camera = wall ground - dz_ground; catches mis-posed frames),
door height above wall ground -1..15 ft. Per house: median over its kept views.
M3 FFE = lidar ground at the wall (2018 DEM) + image door height.
Baseline on the same houses: GBM + lidar ground (evaluate.py features), trained on a 10% pool of
OTHER houses (the image sample is excluded from the pool), as the "certificate neighbours".
Blend: M3 and baseline combined with weights fit by 5-fold CV over the image houses.
Usage: python eval_m3.py AREA [AREA ...]
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


def keep_views(m: pd.DataFrame) -> pd.DataFrame:
    m = m[m.status == "ok"].copy()
    m["cam_h_ft"] = (m.g_wall_ft - m.dz_ground_ft) - m.g_cam_ft
    ok = (m.R_m.between(8, 45) & (m.door_score >= 0.3) & m.ffh_img_ft.between(-1, 15)
          & m.cam_h_ft.between(1.5, 13))
    return m[ok]


def metrics(err: pd.Series) -> dict:
    e = err.dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(), within_1=(e.abs() <= 1).mean(),
                p90=e.abs().quantile(0.9), bias=e.mean())


def main(area: str) -> None:
    h = ev.load(area)
    m = pd.read_parquet(D / area / "m3_measure.parquet")
    views = pd.read_parquet(D / area / "m3_views.parquet")
    sample = pd.read_csv(D / area / "image_sample.csv") if (D / area / "image_sample.csv").exists() else None
    n_sampled = len(sample) if sample is not None else np.nan
    st = m.status.str.split(":").str[0].value_counts().to_dict()
    k = keep_views(m)
    per = k.groupby("oid").agg(ffh_img=("ffh_img_ft", "median"), g_wall=("g_wall_ft", "median"),
                               n_views=("image_id", "size"), year=("captured", lambda s: pd.to_datetime(s).dt.year.median()))
    per["m3_ffe"] = per.g_wall + per.ffh_img
    # baseline: pool = 10% of houses NOT in the image sample
    rng = np.random.default_rng(0)
    img_oids = set(views.oid)
    cand = h[~h.oid.isin(img_oids)]
    pool = cand[rng.random(len(cand)) < 0.10]
    nb = ev.nb_feats(pool, h)
    X = lambda d: pd.concat([d[ev.BASE + ev.GROUND], nb.loc[d.index, ["nb_ffh_med", "nb_ffh_idw", "nb_ffh_std", "nb_n", "nb_dist"]]], axis=1)
    gbm = lgb.LGBMRegressor(**ev.P).fit(X(pool), pool.ffh)
    t = h[h.oid.isin(per.index)].copy()
    t["base_ffe"] = t.e2018_lag + gbm.predict(X(t))
    t = t.join(per, on="oid")
    t = t[t.tier != "C"]
    # blend by 5-fold CV over the image houses (weights only; the answer key of a test house unused)
    t["blend_ffe"] = np.nan
    if len(t) >= 20:
        A = np.c_[t.m3_ffe - t.e2018_lag, t.base_ffe - t.e2018_lag]
        y = (t.ffe - t.e2018_lag).values
        for tr, te in KFold(5, shuffle=True, random_state=0).split(A):
            lr = LinearRegression().fit(A[tr], y[tr])
            t.iloc[te, t.columns.get_loc("blend_ffe")] = t.e2018_lag.values[te] + lr.predict(A[te])
    print(f"\n## Area {area}")
    print(f"sampled houses {n_sampled}; houses with a posed Mapillary view {views.oid.nunique()}; "
          f"views {len(m)} by status {st}; views kept after geometry checks {len(k)}; "
          f"houses with an M3 measurement (precision A+B) {len(t)}")
    rows = {"lidar + neighbours (GBM)": metrics(t.base_ffe - t.ffe),
            "M3 street image + lidar wall ground": metrics(t.m3_ffe - t.ffe),
            "blend (CV weights)": metrics(t.blend_ffe - t.ffe)}
    print(pd.DataFrame(rows).T.round(3).to_markdown())
    raised = t.ffe - t.e2018_lag > 3
    if raised.sum() >= 3:
        print(f"\nHouses with the true door > 3 ft above the lowest adjacent grade (n={raised.sum()}):")
        print(pd.DataFrame({"lidar + neighbours": metrics((t.base_ffe - t.ffe)[raised]),
                            "M3": metrics((t.m3_ffe - t.ffe)[raised]),
                            "blend": metrics((t.blend_ffe - t.ffe)[raised])}).T.round(3).to_markdown())
    t["img_era"] = pd.cut(t.year, [2000, 2017.5, 2020.5, 2030], labels=["<=2017", "2018-2020", ">=2021"])
    print("\nM3 MAE by image capture year (answer key captured 2018-2020):")
    print(t.groupby("img_era", observed=True).apply(lambda g: pd.Series({"n": len(g), "M3": (g.m3_ffe - g.ffe).abs().mean(),
          "base": (g.base_ffe - g.ffe).abs().mean()})).round(3).to_markdown())
    t[["oid", "ffe", "e2018_lag", "base_ffe", "m3_ffe", "blend_ffe", "ffh_img", "n_views", "year"]].to_parquet(D / area / "m3_scored.parquet")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    for a in sys.argv[1:]:
        main(a)
