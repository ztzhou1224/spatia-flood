"""Benchmark non-image floor-elevation methods against the HCFCD front-door answer key.

Target: front-door floor elevation FFE (ft NAVD88, GEOID12B). Ground: 2018 3DEP 1 m DEM (GEOID12B).
Spatial CV: 1 km blocks, 5 group folds. Neighbour values come from TRAINING folds only (and leave
the house itself out for training rows). The answer key is used only as target/neighbour labels.
Rows marked SIMULATED add a noisy copy of the true floor height to stand in for an image reading.
Usage: python evaluate.py AREA [AREA ...]
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import KDTree

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
K, RMAX = 5, 300.0
rng = np.random.default_rng(0)

def load(area):
    h = pd.read_parquet(D / area / "houses.parquet")
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].copy()
    h["area"] = area
    h["ffh"] = h.ffe - h.e2018_lag
    for c in ("p10", "med", "hag", "inside", "far"):
        h[f"g_{c}"] = h[f"e2018_{c}"] - h.e2018_lag
    h["block"] = area + (h.x // 1000).astype(int).astype(str) + "_" + (h.y // 1000).astype(int).astype(str)
    h["tier"] = np.where(h.prec <= 3, "A", np.where(h.prec <= 6, "B", "C"))
    return h

def nb_feats(pool, query):
    """Neighbour stats from the certificate pool, never including the query house itself."""
    tree = KDTree(pool[["x", "y"]].values)
    dist, idx = tree.query(query[["x", "y"]].values, k=K + 1)
    same = pool.index.values[idx] == query.index.values[:, None]
    keep = np.argsort(same, axis=1, kind="stable")[:, :K]  # drop self if present
    dist, idx = np.take_along_axis(dist, keep, 1), np.take_along_axis(idx, keep, 1)
    ffe, ffh = pool.ffe.values[idx], pool.ffh.values[idx]
    m = dist <= RMAX
    w = np.where(m, 1 / np.maximum(dist, 5.0), 0)
    def med(a): return np.array([np.median(r[mm]) if mm.any() else np.nan for r, mm in zip(a, m)])
    out = pd.DataFrame(index=query.index)
    out["nb_ffe_med"], out["nb_ffh_med"] = med(ffe), med(ffh)
    with np.errstate(invalid="ignore", divide="ignore"):
        out["nb_ffe_idw"] = (ffe * w).sum(1) / w.sum(1)
        out["nb_ffh_idw"] = (ffh * w).sum(1) / w.sum(1)
    out["nb_ffh_std"] = np.array([np.std(r[mm]) if mm.sum() > 1 else np.nan for r, mm in zip(ffh, m)])
    out["nb_n"] = m.sum(1)
    out["nb_dist"] = np.where(m, dist, np.nan).mean(1)
    return out

BASE = ["year_built", "fp_area_m2"]
GROUND = ["g_p10", "g_med", "g_hag", "g_inside", "g_far"]
P = dict(objective="l1", n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=30,
         subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)

def run(h, density):
    """A random `density` share of houses play 'has a certificate' (the pool). Every other house is
    estimated. Models train on pool houses in other spatial blocks only; neighbour features always
    come from the pool, leaving the house itself out."""
    names = ["N0 neighbour median FFE", "G0 lidar LAG + typical height", "G1 lidar LAG + neighbour height",
             "GBM no ground", "GBM + lidar ground", "GBM + lidar + image σ0.72 (SIMULATED)",
             "GBM + lidar + image σ1.5 (SIMULATED)"]
    pred = {k: pd.Series(np.nan, index=h.index) for k in names}
    pool_mask = pd.Series(rng.random(len(h)) < density, index=h.index)
    nb = nb_feats(h[pool_mask], h)
    img = {s: h.ffh + rng.normal(0, s, len(h)) for s in (0.72, 1.5)}
    Xa = lambda d: pd.concat([d[BASE], nb.loc[d.index, ["nb_ffe_med", "nb_ffe_idw", "nb_n", "nb_dist"]]], axis=1)
    Xb = lambda d: pd.concat([d[BASE + GROUND], nb.loc[d.index, ["nb_ffh_med", "nb_ffh_idw", "nb_ffh_std", "nb_n", "nb_dist"]]], axis=1)
    for tr_i, te_i in GroupKFold(5).split(h, groups=h.block):
        tr, te = h.iloc[tr_i], h.iloc[te_i]
        tr, te = tr[pool_mask[tr.index]], te[~pool_mask[te.index]]
        gffe, gffh = tr.ffe.median(), tr.ffh.median()
        n = nb.loc[te.index]
        pred["N0 neighbour median FFE"][te.index] = n.nb_ffe_med.fillna(gffe)
        pred["G0 lidar LAG + typical height"][te.index] = te.e2018_lag + gffh
        pred["G1 lidar LAG + neighbour height"][te.index] = te.e2018_lag + n.nb_ffh_med.fillna(gffh)
        m = lgb.LGBMRegressor(**P).fit(Xa(tr), tr.ffe)
        pred["GBM no ground"][te.index] = m.predict(Xa(te))
        m = lgb.LGBMRegressor(**P).fit(Xb(tr), tr.ffh)
        pred["GBM + lidar ground"][te.index] = te.e2018_lag + m.predict(Xb(te))
        for s, name in ((0.72, names[5]), (1.5, names[6])):
            m = lgb.LGBMRegressor(**P).fit(Xb(tr).assign(img=img[s][tr.index]), tr.ffh)
            pred[name][te.index] = te.e2018_lag + m.predict(Xb(te).assign(img=img[s][te.index]))
    return pred, nb

def score(h, pred, mask):
    rows = []
    for k, p in pred.items():
        e = (p - h.ffe)[mask].dropna()
        rows.append(dict(method=k, n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(),
                         within_1=(e.abs() <= 1).mean(), p90=e.abs().quantile(0.9), bias=e.mean()))
    return pd.DataFrame(rows)

if __name__ == "__main__":
    pd.set_option("display.width", 200)
    for area in sys.argv[1:]:
        h = load(area)
        print(f"\n## Area {area}: {len(h)} front-door SFR houses with lidar ground, {h.block.nunique()} blocks")
        print(f"tiers {h.tier.value_counts().to_dict()}; FFH above LAG q10/50/90 {np.percentile(h.ffh, [10, 50, 90]).round(2)}")
        for density in (0.10, 0.25):
            pred, nb = run(h, density)
            mask = (h.tier != "C") & pred["G0 lidar LAG + typical height"].notna()
            print(f"\n### certificate pool {density:.0%}; scored = houses without one, precision A+B "
                  f"(median neighbour distance {nb.nb_dist[mask].median():.0f} m, "
                  f"share with >=1 neighbour in {RMAX:.0f} m {(nb.nb_n[mask] > 0).mean():.0%})")
            print(score(h, pred, mask).round(3).to_markdown(index=False))
            if density == 0.10:
                yb = pd.cut(h.year_built, [0, 1975, 2000, 2030], labels=["<1975", "1975-1999", "2000+"])
                print("\nMAE by year built (pool 10%, A+B)")
                t = {k: (p - h.ffe).abs()[mask].groupby(yb[mask]).mean() for k, p in pred.items()}
                print(pd.DataFrame(t).T.round(3).to_markdown())
