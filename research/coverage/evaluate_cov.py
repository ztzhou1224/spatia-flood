"""Coverage test: how far do NATIONAL inputs go without neighbours' certificates?

Part 1, floor (front-door FFE vs the HCFCD answer key, precision A+B):
  neighbours   GBM + lidar ground with a 10% certificate pool (reference; needs local certificates)
  const        lidar LAG + median door height of the OTHER area
  nsi+lidar    lidar LAG + NSI default foundation height
  nsi only     NSI ground + NSI foundation height (no lidar processing at all)
  era transfer lidar LAG + median door height by NSI year-built band in the OTHER area
  gbm transfer GBM trained in the OTHER area on national features (lidar ring stats, NSI year, stories,
               foundation type, footprint area); predicts door height above LAG
Part 2, risk ranking (ROC AUC of flooded in any recorded event / in Harvey), each with the floor
  estimate a national product would have (gbm transfer), and with the measured floor for reference.
Part 3, one combined logistic risk model trained in the OTHER area (a national model never sees local
  labels) vs trained locally with 1 km block CV.
Usage: python evaluate_cov.py   (both areas)
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
import evaluate as ev  # noqa: E402

D = ev.D
FT = {"S": 0, "C": 1, "B": 2, "P": 3, "I": 4, "W": 5}
NAT = ["g_p10", "g_med", "g_hag", "g_inside", "g_far", "nsi_year", "nsi_stories", "nsi_ft", "fp_area_m2"]


def load(area):
    f = pd.read_parquet(D / area / "coverage_features.parquet")
    f["ffh"] = f.ffe - f.e2018_lag
    for c in ("p10", "med", "hag", "inside", "far"):
        f[f"g_{c}"] = f[f"e2018_{c}"] - f.e2018_lag
    f["nsi_ft"] = f.nsi_found_type.map(FT)
    f["nsi_year"] = pd.to_numeric(f.nsi_year, errors="coerce")
    f["nsi_stories"] = pd.to_numeric(f.nsi_stories, errors="coerce")
    f["tier"] = np.where(f.prec <= 3, "A", np.where(f.prec <= 6, "B", "C"))
    f["block"] = area + (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    f["area"] = area
    return f


def metrics(e):
    e = e.dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(), within_1=(e.abs() <= 1).mean(),
                p90=e.abs().quantile(0.9), bias=e.mean())


def floors(t, o):
    """Floor estimates for target area t using only the other area o for anything learned."""
    out = pd.DataFrame(index=t.index)
    # reference: local neighbours (10% pool), as evaluate.py
    rng = np.random.default_rng(0)
    pool = t[rng.random(len(t)) < 0.10]
    nb = ev.nb_feats(pool, t)
    X = lambda d: pd.concat([d[ev.BASE + ev.GROUND], nb.loc[d.index, ["nb_ffh_med", "nb_ffh_idw", "nb_ffh_std", "nb_n", "nb_dist"]]], axis=1)
    m = lgb.LGBMRegressor(**ev.P).fit(X(pool), pool.ffh)
    out["neighbours"] = np.where(t.index.isin(pool.index), np.nan, t.e2018_lag + m.predict(X(t)))
    out["const"] = t.e2018_lag + o.ffh.median()
    out["nsi+lidar"] = t.e2018_lag + t.nsi_found_ht
    out["nsi + lidar median grade"] = t.e2018_med + t.nsi_found_ht
    out["nsi only"] = t.nsi_ground + t.nsi_found_ht
    bands = [0, 1960, 1975, 1990, 2005, 2100]
    med = o.groupby(pd.cut(o.nsi_year, bands), observed=True).ffh.median()
    out["era transfer"] = t.e2018_lag + pd.cut(t.nsi_year, bands).map(med).astype(float).fillna(o.ffh.median())
    g = lgb.LGBMRegressor(**ev.P).fit(o[NAT], o.ffh)
    out["gbm transfer"] = t.e2018_lag + g.predict(t[NAT])
    return out


def auc(y, s):
    m = np.isfinite(s)
    return roc_auc_score(y[m], s[m]) if y[m].nunique() > 1 else np.nan


def risk_scores(t, floor):
    """Higher = more likely to flood. floor = an FFE estimate (ft NAVD88)."""
    s = {}
    s["FEMA zone"] = t.zone.map({"SFHA": 2, "X 0.2%": 1, "X minimal": 0}).astype(float)
    s["BFE - floor (no BFE = low)"] = np.where(np.isfinite(t.bfe), t.bfe - floor, -50.0)
    s["- floor above nearest water (REM)"] = -((floor - t.e2018_lag) + t.rem)
    s["- ground above nearest water"] = -t.rem
    s["depression depth"] = t.dep
    s["- relative elevation (1 km)"] = -t.rel
    if (t.surge_min_cat <= 5).any():
        s["NOAA surge: - lowest category"] = -t.surge_min_cat.astype(float)
    return s


def design(t, floor):
    return pd.DataFrame({
        "sfha": (t.zone == "SFHA").astype(float), "x02": (t.zone == "X 0.2%").astype(float),
        "bfe_margin": np.where(np.isfinite(t.bfe), t.bfe - floor, -10.0).clip(-10, 10),
        "floor_above_water": ((floor - t.e2018_lag) + t.rem).clip(-5, 60),
        "dep": t.dep.clip(0, 5), "rel": t.rel.clip(-20, 20),
        "log_dist": np.log1p(t.dist_water_m.fillna(4000)),
    }, index=t.index).fillna(0)


def main():
    A = {a: load(a) for a in ("B", "C")}
    pd.set_option("display.width", 220)
    print("# Coverage test (national inputs only)\n")
    print("## 1. Floor without neighbours (front-door FFE, ft; precision A+B)\n")
    fl = {}
    for a, o in (("B", "C"), ("C", "B")):
        t, oo = A[a], A[o]
        fl[a] = floors(t, oo[oo.tier != "C"])
        hb = t.tier != "C"
        rows = {k: metrics((fl[a][k] - t.ffe)[hb]) for k in fl[a].columns}
        print(f"### Area {a} (learned from {o} where marked transfer/const)")
        print(pd.DataFrame(rows).T.round(3).to_markdown(), "\n")
        print(f"NSI foundation types matched: {t.nsi_found_type.value_counts().to_dict()}; "
              f"NSI default height by type: {t.groupby('nsi_found_type').nsi_found_ht.median().to_dict()}; "
              f"NSI ground minus lidar LAG median {np.nanmedian(t.nsi_ground - t.e2018_lag):.2f} ft\n")
    print("## 2. Risk ranking, single signals (ROC AUC; 0.5 = none)\n")
    for a in ("B", "C"):
        t = A[a]
        hv = pd.read_parquet(D / a / "harvey_houses.parquet", columns=["oid", "water_over_floor", "water_over_est_floor"]) \
            if (D / a / "harvey_houses.parquet").exists() else None
        res = {}
        for lab in ("fl_any", "fl_harvey"):
            y = t[lab].astype(int)
            col = {}
            for fname, floor in (("measured floor", t.ffe), ("national floor (gbm transfer)", fl[a]["gbm transfer"])):
                for k, v in risk_scores(t, floor).items():
                    col[(k, fname)] = auc(y, np.asarray(v, dtype=float))
            if hv is not None and lab == "fl_harvey":
                j = t[["oid"]].merge(hv, on="oid", how="left")
                col[("PRIMo Harvey hindcast water - floor (event-specific, local)", "measured floor")] = auc(y, j.water_over_floor.values)
            res[lab] = col
        df = pd.DataFrame(res)
        df.index = pd.MultiIndex.from_tuples(df.index, names=["signal", "floor used"])
        print(f"### Area {a}: flooded any event {int(t.fl_any.sum())}, Harvey {int(t.fl_harvey.sum())} of {len(t)}")
        print(df.round(3).to_markdown(), "\n")
    print("## 3. Combined risk model (logistic): local block CV vs trained in the OTHER area\n")
    rows = {}
    for a, o in (("B", "C"), ("C", "B")):
        t, oo = A[a], A[o]
        for lab in ("fl_any", "fl_harvey"):
            y = t[lab].astype(int)
            Xt = design(t, fl[a]["gbm transfer"])
            # local CV
            p = np.zeros(len(t))
            for tr, te in GroupKFold(5).split(Xt, groups=t.block):
                if y.iloc[tr].nunique() < 2:
                    continue
                p[te] = LogisticRegression(max_iter=2000).fit(Xt.iloc[tr], y.iloc[tr]).predict_proba(Xt.iloc[te])[:, 1]
            # transfer: the training area is a region WITH measurements, so it uses its measured floor;
            # the target area gets only its national floor estimate (never its own answer key or labels)
            Xo = design(oo, oo.ffe)
            yo = oo[lab].astype(int)
            q = LogisticRegression(max_iter=2000).fit(Xo, yo).predict_proba(Xt)[:, 1] if yo.nunique() > 1 else np.full(len(t), np.nan)
            rows[(a, lab)] = {"local 1 km block CV": roc_auc_score(y, p), "trained in other area": auc(y, q),
                              "FEMA zone alone": auc(y, Xt.sfha * 2 + Xt.x02)}
    print(pd.DataFrame(rows).T.round(3).to_markdown())


if __name__ == "__main__":
    main()
