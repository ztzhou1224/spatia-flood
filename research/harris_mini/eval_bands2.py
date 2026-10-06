"""Narrower honest bands from ~50 local labels: normalised conformal (protocol fixed before the first run).

Setting: the chosen design of eval_design.py. Test area T in {A, B, C} (model from the other two Harris areas) or P
(Florida, model from A + B + C); 50 local labels (30 unflagged + up to 20 flagged, bands.flag_raised on the pooled
estimate); point estimate = refit with the 50 labels at weight 10; the labels' residuals are cross-fitted (5 folds:
refit without the fold, predict it). Scored on the other screened houses, 20 draws.
Bands (all 90%, finite-sample conformal; bands.conf_q for two-sided, and the ceil((n+1) c)-th order statistic for
absolute scores):
  mondrian      current method: signed residual quantiles per flag group (group < 10 labels -> all 50)
  normalised    score |r| / s(x), s = a difficulty model, band p +- q s(x), q from all 50 labels (one scale)
  norm+flag     the same, q per flag group when the group has >= 19 labels, else all 50
Difficulty model s(x): LightGBM (objective l2) predicting |residual| from method E features plus the estimate, trained
on residuals of cross-area pseudo-experiments among the training areas only (model trained on one area, residuals on
another; never the test area), floored at 0.25 ft. Label-free at application.
Reported: coverage all / flagged / not flagged, median width flagged / not flagged, SFHA BFE decided and decided correct.
Usage: python eval_bands2.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from bands import conf_q, flag_raised  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_transfer import load  # noqa: E402
from fl_eval import florida  # noqa: E402

COLS = SETS["E + eave estimate"]
P1 = {**el.P, "n_jobs": 1}
DRAWS, C = 20, 0.9


def fit(x, y, w=None, **kw):
    return lgb.LGBMRegressor(**{**P1, **kw}).fit(x, y, sample_weight=w)


def abs_q(s, c=C):
    s = np.sort(np.asarray(s, float))
    k = int(np.ceil((len(s) + 1) * c))
    return s[k - 1] if k <= len(s) else np.inf


def difficulty(train):
    """|residual| model from cross-area pseudo-experiments among the training areas."""
    X, y = [], []
    for o in train:
        for q in train:
            if q != o:
                p = fit(train[q][COLS], train[q].dh).predict(train[o][COLS])
                X.append(train[o][COLS].assign(est=p))
                y.append(np.abs(train[o].dh.values - p))
    m = fit(pd.concat(X, ignore_index=True), np.concatenate(y), objective="l2")
    return lambda f, p: np.maximum(m.predict(f[COLS].assign(est=p)), 0.25)


def stats(f, lo, hi, g, ev):
    y = f.dh.values
    cov = (y >= lo) & (y <= hi)
    s = ev & (f.zone.values == "SFHA") & f.bfe.notna().values
    lag, bfe, ffe = f.e2018_lag.values[s], f.bfe.values[s], f.ffe.values[s]
    above, below = lag + lo[s] >= bfe, lag + hi[s] < bfe
    dec = above | below
    w = hi - lo
    return {"coverage": cov[ev].mean(), "coverage flagged": cov[ev & g].mean() if (ev & g).any() else np.nan,
            "coverage not flagged": cov[ev & ~g].mean(), "median width flagged": np.median(w[ev & g]) if (ev & g).any() else np.nan,
            "median width not flagged": np.median(w[ev & ~g]), "BFE decided": dec.mean() if s.any() else np.nan,
            "decided correct": ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan}


def run(train, f, rng, label):
    tr = pd.concat(train.values(), ignore_index=True)
    sfun = difficulty(train)
    ok = f.key_ok.values
    p0 = fit(tr[COLS], tr.dh).predict(f[COLS])
    g0 = flag_raised(f, p0)
    out = {}
    for _ in range(DRAWS):
        nf = min(20, int(g0.sum()) // 2)
        cal = np.r_[rng.choice(np.where(g0)[0], nf, replace=False), rng.choice(np.where(~g0)[0], 50 - nf, replace=False)]
        ev = ok.copy()
        ev[cal] = False
        loc = f.iloc[cal]

        def refit(sub, target):
            x = pd.concat([tr[COLS], sub[COLS]], ignore_index=True)
            w = np.r_[np.ones(len(tr)), np.full(len(sub), 10.0)]
            return fit(x, np.r_[tr.dh.values, sub.dh.values], w).predict(target[COLS])
        p = refit(loc, f)
        res, pc = np.empty(len(cal)), np.empty(len(cal))
        for part in np.array_split(rng.permutation(len(cal)), 5):
            keep = np.setdiff1d(np.arange(len(cal)), part)
            pc[part] = refit(loc.iloc[keep], loc.iloc[part])
            res[part] = loc.dh.values[part] - pc[part]
        g = flag_raised(f, p)
        gc = g[cal]
        s_all = sfun(f, p)
        s_cal = sfun(loc, pc)
        bands = {}
        lo, hi = np.full(len(f), np.nan), np.full(len(f), np.nan)
        for grp in (True, False):
            r = res[gc == grp] if (gc == grp).sum() >= 10 else res
            ql, qh = conf_q(r, C)
            lo[g == grp], hi[g == grp] = p[g == grp] + ql, p[g == grp] + qh
        bands["mondrian (current)"] = (lo.copy(), hi.copy())
        q = abs_q(np.abs(res) / s_cal)
        bands["normalised"] = (p - q * s_all, p + q * s_all)
        lo, hi = np.full(len(f), np.nan), np.full(len(f), np.nan)
        for grp in (True, False):
            sc = np.abs(res) / s_cal
            qq = abs_q(sc[gc == grp]) if (gc == grp).sum() >= 19 else q
            lo[g == grp], hi[g == grp] = p[g == grp] - qq * s_all[g == grp], p[g == grp] + qq * s_all[g == grp]
        bands["norm+flag"] = (lo, hi)
        for k, (lo, hi) in bands.items():
            out.setdefault(k, []).append(stats(f, lo, hi, g, ev))
    print(f"\n## {label}: 90% bands from 50 local labels (mean of {DRAWS} draws; held-out screened houses)\n")
    print(pd.DataFrame({k: pd.DataFrame(v).mean() for k, v in out.items()}).T.round(3).to_markdown())


def main():
    a = {k: load(k) for k in ("A", "B", "C")}
    rng = np.random.default_rng(20261009)
    for te in a:
        run({o: a[o] for o in a if o != te}, a[te], rng, f"{te} (model from {'+'.join(o for o in a if o != te)})")
    run(a, florida(True), rng, "P Florida (model from A+B+C)")


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
