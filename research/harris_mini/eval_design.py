"""Pre-registered test of the local-label design (independent review 2026-10-06, next experiment 2 and 3).

PROTOCOL (fixed before any run; this file is committed before its first run):
  Selection areas A and B, confirmation area C. In selection, the model for A comes from B only and the model for B
  from A only, so nothing from C enters any choice. In confirmation, the model for C comes from A + B. Method E
  features, LightGBM (eval_lpc.P, one thread). 50 local labels per area, 20 draws per setting, scored on the area's
  other screened houses, and the pooled model (no local labels) on the SAME held-out set of each draw.
Part 1, scattered labels. Candidates: sampling in {random 50, 30 unflagged + 20 flagged, 50 flagged (capped at half
  the flagged houses, rest random)} x weight W in {1, 3, 10}, plus "local only" (LightGBM on the 50 labels alone,
  min_child_samples 5) per sampling: 12 candidates. Flag = bands.flag_raised on the pooled model's estimate.
  Primary criterion: mean over A and B of the held-out MAE; the candidate with the lowest value is chosen; ties
  within 0.005 ft go to the higher mean BFE side. The choice is printed before C is scored. Confirmation: the chosen
  candidate on C vs the pooled model on the same sets (all candidates are also printed for C, marked exploratory).
  Bands for the chosen candidate on C: 90% finite-sample conformal (bands.conf_q), Mondrian by flag, calibrated on the
  50 labels' CROSS-FITTED residuals (5 folds over the 50: refit without the fold, predict the fold), a group with
  < 10 labels uses all 50; coverage, median width, BFE decided and decided-correct on the held-out houses.
Part 2, clustered labels (certificate-like): the 50 labels are the SFHA houses nearest to a random SFHA seed house
  (at most half the area's SFHA houses). Candidates: global refit with W in {1, 3, 10}; trust region: the refit with
  W = 10 used only within R in {250, 1000} m of a label, the pooled model elsewhere: 5 candidates. Same selection
  rule on A and B (models from the other selection area), confirmation on C (model from A + B). Errors also by
  distance to the nearest label (< 250, 250-1,000, > 1,000 m).
Usage: python eval_design.py
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
from bands import conf_q, flag_raised  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_transfer import load  # noqa: E402

COLS = SETS["E + eave estimate"]
P1 = {**el.P, "n_jobs": 1}
K, DRAWS, WS = 50, 20, (1, 3, 10)
SAMPLINGS = ("random 50", "30 unflagged + 20 flagged", "50 flagged")


def fit(x, y, w=None, **kw):
    return lgb.LGBMRegressor(**{**P1, **kw}).fit(x, y, sample_weight=w)


def refit(tr, loc, f, w):
    x = pd.concat([tr[COLS], loc[COLS]], ignore_index=True)
    sw = np.r_[np.ones(len(tr)), np.full(len(loc), float(w))]
    return fit(x, np.r_[tr.dh.values, loc.dh.values], sw).predict(f[COLS])


def score(f, p, m):
    y, e = f.dh.values[m], p[m] - f.dh.values[m]
    r = y > 3
    s = (f.zone.values[m] == "SFHA") & f.bfe.notna().values[m]
    side = ((f.ffe.values[m][s] >= f.bfe.values[m][s]) == (f.e2018_lag.values[m][s] + p[m][s] >= f.bfe.values[m][s])).mean()
    return {"MAE": np.abs(e).mean(), "raised MAE": np.abs(e[r]).mean() if r.any() else np.nan,
            "raised recall": (p[m][r] > 3).mean() if r.any() else np.nan, "BFE side": side}


def draw_scattered(rng, g, how):
    if how == "random 50":
        return rng.choice(len(g), K, replace=False)
    nf = min(20 if how.startswith("30") else K, int(g.sum()) // 2)
    a = rng.choice(np.where(g)[0], nf, replace=False)
    pool = np.where(~g)[0] if how.startswith("30") else np.setdiff1d(np.arange(len(g)), a)
    return np.r_[a, rng.choice(pool, K - nf, replace=False)]


def draw_cluster(rng, f):
    s = np.where(f.zone.values == "SFHA")[0]
    n = min(K, len(s) // 2)
    seed = rng.choice(s)
    d = np.hypot(f.x.values[s] - f.x.values[seed], f.y.values[s] - f.y.values[seed])
    return s[np.argsort(d)[:n]]


def scattered(tr, f, rng):
    """{candidate: list of per-draw scores}, plus the pooled model on the same sets."""
    ok = f.key_ok.values
    p0 = fit(tr[COLS], tr.dh).predict(f[COLS])
    g = flag_raised(f, p0)
    acc = {}
    for _ in range(DRAWS):
        for how in SAMPLINGS:
            cal = draw_scattered(rng, g, how)
            ev = ok.copy()
            ev[cal] = False
            loc = f.iloc[cal]
            acc.setdefault(("pooled (same set)", how), []).append(score(f, p0, ev) | {"flagged in sample": int(g[cal].sum())})
            for w in WS:
                acc.setdefault((f"W {w}", how), []).append(score(f, refit(tr, loc, f, w), ev))
            acc.setdefault(("local only", how), []).append(score(f, fit(loc[COLS], loc.dh, min_child_samples=5).predict(f[COLS]), ev))
    return acc


def clustered(tr, f, rng):
    ok = f.key_ok.values
    p0 = fit(tr[COLS], tr.dh).predict(f[COLS])
    acc, byd = {}, {}
    for _ in range(DRAWS):
        cal = draw_cluster(rng, f)
        ev = ok.copy()
        ev[cal] = False
        loc = f.iloc[cal]
        d, _ = cKDTree(np.c_[f.x.values[cal], f.y.values[cal]]).query(np.c_[f.x.values, f.y.values])
        preds = {"pooled (same set)": p0}
        for w in WS:
            preds[f"global refit W {w}"] = refit(tr, loc, f, w)
        for rr in (250, 1000):
            preds[f"trust region {rr} m (W 10)"] = np.where(d <= rr, preds["global refit W 10"], p0)
        for nm, p in preds.items():
            acc.setdefault(nm, []).append(score(f, p, ev))
            for lab, m in (("< 250 m", d < 250), ("250-1000 m", (d >= 250) & (d < 1000)), ("> 1000 m", d >= 1000)):
                mm = ev & m
                if mm.sum() >= 20:
                    byd.setdefault((nm, lab), []).append(score(f, p, mm) | {"n": int(mm.sum())})
    return acc, byd


def mean(acc):
    return pd.DataFrame({k: pd.DataFrame(v).mean() for k, v in acc.items()}).T


def choose(tabs):
    """Pre-registered rule: lowest mean MAE over the selection areas; ties within 0.005 ft -> higher BFE side."""
    cand = [k for k in tabs[0].index if not str(k[0] if isinstance(k, tuple) else k).startswith("pooled")]
    mae = pd.Series({k: np.mean([t.loc[[k], "MAE"].iloc[0] for t in tabs]) for k in cand})
    side = pd.Series({k: np.mean([t.loc[[k], "BFE side"].iloc[0] for t in tabs]) for k in cand})
    near = mae[mae <= mae.min() + 0.005].index
    return side[near].idxmax(), mae, side


def bands_for(tr, f, rng, how, w):
    """Chosen scattered design on the confirmation area: cross-fitted conformal 90% bands from the 50 labels."""
    ok = f.key_ok.values
    p0 = fit(tr[COLS], tr.dh).predict(f[COLS])
    g = flag_raised(f, p0)
    rec = []
    for _ in range(DRAWS):
        cal = draw_scattered(rng, g, how)
        ev = ok.copy()
        ev[cal] = False
        loc = f.iloc[cal]
        p = refit(tr, loc, f, w) if w else fit(loc[COLS], loc.dh, min_child_samples=5).predict(f[COLS])
        res = np.empty(len(cal))
        for j, part in enumerate(np.array_split(rng.permutation(len(cal)), 5)):
            keep = np.setdiff1d(np.arange(len(cal)), part)
            sub = loc.iloc[keep]
            pp = refit(tr, sub, loc.iloc[part], w) if w else fit(sub[COLS], sub.dh, min_child_samples=5).predict(loc.iloc[part][COLS])
            res[part] = loc.dh.values[part] - pp
        gp = flag_raised(f, p)
        gc = gp[cal]
        lo, hi = np.full(len(f), np.nan), np.full(len(f), np.nan)
        for grp in (True, False):
            r = res[gc == grp] if (gc == grp).sum() >= 10 else res
            ql, qh = conf_q(r, 0.9)
            idx = gp == grp
            lo[idx], hi[idx] = p[idx] + ql, p[idx] + qh
        y = f.dh.values
        cov = (y >= lo) & (y <= hi)
        s = ev & (f.zone.values == "SFHA") & f.bfe.notna().values
        lag, bfe, ffe = f.e2018_lag.values[s], f.bfe.values[s], f.ffe.values[s]
        above, below = lag + lo[s] >= bfe, lag + hi[s] < bfe
        dec = above | below
        rec.append({"coverage all": cov[ev].mean(), "coverage flagged": cov[ev & gp].mean(), "coverage not flagged": cov[ev & ~gp].mean(),
                    "median width flagged": np.median((hi - lo)[ev & gp]), "median width not flagged": np.median((hi - lo)[ev & ~gp]),
                    "BFE decided": dec.mean(), "decided correct": ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan})
    return pd.DataFrame(rec).mean()


def main():
    a = {k: load(k) for k in ("A", "B", "C")}
    rng = np.random.default_rng(20261007)
    sel = {"A": "B", "B": "A"}
    print("# Part 1: scattered labels (50 per area)")
    tabs = []
    for te, trn in sel.items():
        t = mean(scattered(a[trn], a[te], rng))
        tabs.append(t)
        print(f"\n## selection area {te} (model from {trn} only)\n")
        print(t.round(3).to_markdown())
    chosen, mae, side = choose(tabs)
    print("\n## selection: mean over A and B (lowest MAE; ties within 0.005 ft -> higher BFE side)\n")
    print(pd.DataFrame({"mean MAE": mae, "mean BFE side": side}).sort_values("mean MAE").round(3).to_markdown())
    print(f"\nCHOSEN (before C is scored): {chosen}")
    tc = mean(scattered(pd.concat([a["A"], a["B"]], ignore_index=True), a["C"], rng))
    base = tc.loc[[("pooled (same set)", chosen[1])]]
    print("\n## confirmation area C (model from A + B): chosen candidate vs pooled model on the same sets\n")
    print(pd.concat([tc.loc[[chosen]], base]).round(3).to_markdown())
    print("\n## C, all candidates (exploratory, not part of the confirmation)\n")
    print(tc.round(3).to_markdown())
    w = int(chosen[0].split()[1]) if chosen[0].startswith("W") else 0
    print(f"\n## C, chosen candidate: 90% cross-fitted conformal bands from the 50 labels (mean of {DRAWS} draws)\n")
    print(bands_for(pd.concat([a["A"], a["B"]], ignore_index=True), a["C"], rng, chosen[1], w).round(3).to_frame().T.to_markdown(index=False))

    print("\n# Part 2: clustered labels (50 SFHA houses nearest a random SFHA house)")
    tabs = []
    for te, trn in sel.items():
        acc, byd = clustered(a[trn], a[te], rng)
        t = mean(acc)
        tabs.append(t)
        print(f"\n## selection area {te} (model from {trn} only)\n")
        print(t.round(3).to_markdown())
        print(mean(byd).round(3).to_markdown())
    chosen2, mae, side = choose(tabs)
    print("\n## selection: mean over A and B\n")
    print(pd.DataFrame({"mean MAE": mae, "mean BFE side": side}).sort_values("mean MAE").round(3).to_markdown())
    print(f"\nCHOSEN (before C is scored): {chosen2}")
    acc, byd = clustered(pd.concat([a["A"], a["B"]], ignore_index=True), a["C"], rng)
    tc = mean(acc)
    print("\n## confirmation area C (model from A + B): chosen vs pooled on the same sets\n")
    print(tc.loc[[chosen2, "pooled (same set)"]].round(3).to_markdown())
    print("\n## C, all candidates and by distance to the nearest label (exploratory)\n")
    print(tc.round(3).to_markdown())
    print(mean(byd).round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
