"""Scattered real numbers: how few labels help, and bands that know how far the nearest label is.

Setting (as eval_local.py): for each test area, the model comes from the other two areas (benchmark method E
features, LightGBM, single thread) and k measured houses of the test area are added with weight 10. Scored on the
area's other houses, screened answer key (scorer only; the k labels stand for whatever measurements arrive).
1) Density curve: k = 0, 5, 10, 20, 50 labels, three ways labels arrive (mean of 20 draws):
     random       any house
     mixed        60% random, 40% from the label-free raised flag (bands.flag_raised)
     flagged      only flagged houses (what elevation certificates look like: mostly raised flood-zone houses)
2) Bands by distance to the nearest label (k = 20 and 50, mixed): conformal 90% bands, Mondrian by raised flag x
   distance to the nearest local label (< 250 m, 250-1,000 m, > 1,000 m). The residual pool is built without the test
   area: pseudo-experiments in each of the other two areas (model from the remaining area + k labels there, 5 draws),
   so the pool comes from the same situation one level down (one training area instead of two: conservative).
   Compared with bands by flag only from the same pool. Coverage, width, BFE decided and decided-correct per group
   (10 draws).
Usage: python eval_sparse.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from bands import flag_raised  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_transfer import load  # noqa: E402

COLS = SETS["E + eave estimate"]
P1 = {**el.P, "n_jobs": 1}
W = 10.0
KS = (5, 10, 20, 50)
DIST = (250, 1000)
C = 0.9


def refit(tr, loc, f):
    if loc is None or len(loc) == 0:
        return lgb.LGBMRegressor(**P1).fit(tr[COLS], tr.dh).predict(f[COLS])
    x = pd.concat([tr[COLS], loc[COLS]], ignore_index=True)
    sw = np.r_[np.ones(len(tr)), np.full(len(loc), W)]
    return lgb.LGBMRegressor(**P1).fit(x, np.r_[tr.dh.values, loc.dh.values], sample_weight=sw).predict(f[COLS])


def sample(rng, g, k, how):
    if how == "random":
        return rng.choice(len(g), k, replace=False)
    nf = k if how == "flagged" else round(0.4 * k)
    nf = min(nf, int(g.sum()) // 2)
    nr = k - nf
    a = rng.choice(np.where(g)[0], nf, replace=False)
    rest = np.setdiff1d(np.arange(len(g)), a)
    return np.r_[a, rng.choice(rest, nr, replace=False)] if nr else a


def score(f, p, m):
    y, e = f.dh.values[m], p[m] - f.dh.values[m]
    r = y > 3
    s = (f.zone.values[m] == "SFHA") & f.bfe.notna().values[m]
    side = ((f.ffe.values[m][s] >= f.bfe.values[m][s]) == (f.e2018_lag.values[m][s] + p[m][s] >= f.bfe.values[m][s])).mean()
    return {"MAE": np.abs(e).mean(), "raised MAE": np.abs(e[r]).mean(), "raised recall": (p[m][r] > 3).mean(), "BFE side": side}


def dist_bin(f, cal):
    d, _ = cKDTree(np.c_[f.x.values[cal], f.y.values[cal]]).query(np.c_[f.x.values, f.y.values])
    return np.digitize(d, DIST)  # 0: < 250 m, 1: 250-1000 m, 2: > 1000 m


def experiment(tr, f, k, rng):
    """One draw: k mixed labels in f, model from tr; residual, flag, distance bin of every house; label mask."""
    ok = f.key_ok.values
    g0 = flag_raised(f, refit(tr, None, f))
    cal = sample(rng, g0, k, "mixed")
    p = refit(tr, f.iloc[cal], f)
    ev = ok.copy()
    ev[cal] = False
    return p, flag_raised(f, p), dist_bin(f, cal), ev


def main():
    a = {k: load(k) for k in ("A", "B", "C")}
    rng = np.random.default_rng(20261006)
    for te, f in a.items():
        others = [o for o in a if o != te]
        tr = pd.concat([a[o] for o in others], ignore_index=True)
        ok = f.key_ok.values
        p0 = refit(tr, None, f)
        g0 = flag_raised(f, p0)
        res = {("none", "k = 0"): score(f, p0, ok)}
        for how in ("random", "mixed", "flagged"):
            for k in KS:
                acc = []
                for _ in range(20):
                    cal = sample(rng, g0, k, how)
                    ev = ok.copy()
                    ev[cal] = False
                    acc.append(score(f, refit(tr, f.iloc[cal], f), ev))
                res[(how, f"k = {k}")] = pd.DataFrame(acc).mean().to_dict()
        print(f"\n## {te}: model from {'+'.join(others)} plus k scattered labels (weight 10; mean of 20 draws; screened)\n")
        print(pd.DataFrame(res).T.round(3).to_markdown())

        for k in (20, 50):
            pool = []  # residual, flag, distance bin from pseudo-experiments without the test area
            for o in others:
                q = next(x for x in others if x != o)
                for _ in range(5):
                    p, g, db, ev = experiment(a[q], a[o], k, rng)
                    pool.append(pd.DataFrame({"r": (a[o].dh.values - p)[ev], "g": g[ev], "d": db[ev]}))
            pool = pd.concat(pool, ignore_index=True)
            rows = {}
            for _ in range(10):
                p, g, db, ev = experiment(tr, f, k, rng)
                y = f.dh.values
                for scheme in ("flag only", "flag x distance"):
                    lo, hi = np.full(len(f), np.nan), np.full(len(f), np.nan)
                    for gg in (True, False):
                        for d in (0, 1, 2):
                            idx = (g == gg) & (db == d)
                            r = pool[(pool.g == gg) & ((pool.d == d) if scheme == "flag x distance" else True)].r
                            if len(r) < 30:
                                r = pool[pool.g == gg].r
                            lo[idx], hi[idx] = p[idx] + np.quantile(r, (1 - C) / 2), p[idx] + np.quantile(r, (1 + C) / 2)
                    for gg in (True, False):
                        for d in (0, 1, 2):
                            m = ev & (g == gg) & (db == d)
                            if m.sum() == 0:
                                continue
                            s = m & (f.zone.values == "SFHA") & f.bfe.notna().values
                            lag, bfe, ffe = f.e2018_lag.values[s], f.bfe.values[s], f.ffe.values[s]
                            above, below = lag + lo[s] >= bfe, lag + hi[s] < bfe
                            dec = above | below
                            key = (scheme, "flagged" if gg else "not flagged", ("< 250 m", "250-1000 m", "> 1000 m")[d])
                            rows.setdefault(key, []).append({
                                "n": int(m.sum()), "coverage": ((y[m] >= lo[m]) & (y[m] <= hi[m])).mean(),
                                "width ft": (hi[m] - lo[m]).mean(), "SFHA n": int(s.sum()),
                                "BFE decided": dec.mean() if s.any() else np.nan,
                                "decided correct": ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan})
            out = pd.DataFrame({key: pd.DataFrame(v).mean() for key, v in rows.items()}).T
            print(f"\n## {te}: 90% bands with k = {k} mixed labels; pool from pseudo-experiments in {'+'.join(others)} "
                  f"(pool {len(pool)} residuals); mean of 10 draws\n")
            print(out.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
