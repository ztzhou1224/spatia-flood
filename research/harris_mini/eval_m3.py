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
    """Two measurements per view, both anchored on 2018 lidar:
    diff - door above the wall-ground line seen in the image (camera height cancels), when the
           house mask reaches the ground below the door and the implied camera height is 1.5-13 ft;
    abs  - lidar road under the camera + a typical camera height + R tan(door angle); the typical
           height is the median implied camera height of OTHER houses' diff views of the same camera
           type (pano / perspective), so a house's own image never sets its own camera height."""
    m = m[(m.status == "ok") & m.R_m.between(8, 45) & (m.door_score >= 0.3)].copy()
    m["cam_h_ft"] = (m.g_wall_ft - m.dz_ground_ft) - m.g_cam_ft
    m["pano"] = m.camera_type.isin(["spherical", "equirectangular"])
    good = m.cam_h_ft.between(1.5, 13) & m.ffh_img_ft.between(-1, 15)
    m["ffe_diff"] = np.where(good, m.g_wall_ft + m.ffh_img_ft, np.nan)
    h_typ = []
    for r in m.itertuples():
        ref = m[good & (m.pano == r.pano) & (m.oid != r.oid)].cam_h_ft
        h_typ.append(ref.median() if len(ref) >= 5 else np.nan)
    m["cam_h_typ"] = h_typ
    m["ffe_abs"] = m.g_cam_ft + m.cam_h_typ + m.dz_door_ft
    m.loc[~(m.ffe_abs - m.g_wall_ft).between(-1, 15), "ffe_abs"] = np.nan
    m["ffe_view"] = m.ffe_diff.fillna(m.ffe_abs)
    m["method"] = np.where(m.ffe_diff.notna(), "diff", np.where(m.ffe_abs.notna(), "abs", None))
    return m[m.ffe_view.notna()]


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
    per = k.groupby("oid").agg(m3_ffe=("ffe_view", "median"), m3_diff=("ffe_diff", "median"), m3_abs=("ffe_abs", "median"),
                               ffh_img=("ffh_img_ft", "median"), n_views=("image_id", "size"),
                               year=("captured", lambda s: pd.to_datetime(s).dt.year.median()))
    print(f"{area}: views by method {k.method.value_counts().to_dict()}; typical camera height ft "
          f"pano {k[k.pano].cam_h_typ.median():.1f}, perspective {k[~k.pano].cam_h_typ.median():.1f}")
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
            "  M3 diff only (ground line seen)": metrics(t.m3_diff - t.ffe),
            "  M3 abs only (typical camera height)": metrics(t.m3_abs - t.ffe),
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
    t[["oid", "ffe", "e2018_lag", "base_ffe", "m3_ffe", "m3_diff", "m3_abs", "blend_ffe", "n_views", "year"]].to_parquet(D / area / "m3_scored.parquet")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    for a in sys.argv[1:]:
        main(a)
