"""Per-house error bands (split / cross conformal, Mondrian by a label-free raised flag), and what they mean for the BFE.

Point estimate: method E or F of benchmark.py. Band = p + [q_lo, q_hi] from signed residuals (truth - estimate) of
calibration houses in the same group (Mondrian, label-free): flagged raised (record basement / lower level / two-story
crawl space, or estimate > 3 ft) vs not flagged. q_lo / q_hi are the FINITE-SAMPLE conformal order statistics
(conf_q): the floor((n+1)(1-c)/2)-th and ceil((n+1)(1+c)/2)-th smallest of n residuals, -inf / +inf when the
calibration set is too small for the level (n < 2/(1-c) - 1, i.e. n < 19 at 90%). (Before 2026-10-06 this used
np.quantile, which interpolates and under-covers on small calibration sets: independent review, BANDS.md.)
Calibration settings:
  within an area   cross-conformal: estimates out-of-fold (5 folds by 1 km block), residuals from the OTHER folds
  new area         model from the other two areas; residual pool from CROSS-AREA pseudo-experiments among those two
                   (model trained on one, residuals on the other, both ways), i.e. the same regime as the test (before
                   2026-10-06 the pool came from within-area out-of-fold residuals, an easier regime: review item 4)
  local sample     model from the other two areas; residuals of k measured local houses (random, or n_unf unflagged
                   + n_flag flagged chosen label-free); a group with fewer than 10 calibration houses uses all k
Reported per group: coverage of the 80% / 90% bands, median width and share of infinite bands; for SFHA houses with
a BFE: share whose 90% band lies entirely above or below the BFE ("decided") and the share of decided houses on the
correct side. Also (scorer) the precision / recall of the records part of the raised flag and the eave_p50 AUC per area.
Answer key = scorer only (and the local sample's measured heights).
Usage: python bands.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from benchmark import predictions  # noqa: E402
from eval_transfer import load  # noqa: E402

LEVELS = (0.8, 0.9)


def flag_raised(f, p):
    rec = ((f.basement > 0) | (f.lower_any > 0) | f.foundation.str.contains("Basement", na=False)
           | ((f.foundation == "Crawl Space") & (f.stories == 2))).values
    return rec | (p > 3)


def records_flag(f):
    return ((f.basement > 0) | (f.lower_any > 0) | f.foundation.str.contains("Basement", na=False)
            | ((f.foundation == "Crawl Space") & (f.stories == 2))).values


def conf_q(r, c):
    """Finite-sample split-conformal offsets (lo, hi) for a central c band from residuals r."""
    r = np.sort(np.asarray(r, float)[np.isfinite(r)])
    n = len(r)
    k_lo = int(np.floor((n + 1) * (1 - c) / 2))
    k_hi = int(np.ceil((n + 1) * (1 + c) / 2))
    lo = r[k_lo - 1] if k_lo >= 1 else -np.inf
    hi = r[k_hi - 1] if k_hi <= n else np.inf
    return lo, hi


def apply_bands(p, g, pools):
    """pools: {group (True/False): residual array}. Returns lo, hi dicts per level."""
    lo = {c: np.full(len(p), np.nan) for c in LEVELS}
    hi = {c: np.full(len(p), np.nan) for c in LEVELS}
    for grp, r in pools.items():
        idx = np.where(g == grp)[0]
        for c in LEVELS:
            ql, qh = conf_q(r, c)
            lo[c][idx], hi[c][idx] = p[idx] + ql, p[idx] + qh
    return lo, hi


def bands_same_area(f, p):
    """Cross-conformal within an area: residuals from the other folds of the same group."""
    g = flag_raised(f, p)
    res = f.dh.values - p
    lo = {c: np.full(len(f), np.nan) for c in LEVELS}
    hi = {c: np.full(len(f), np.nan) for c in LEVELS}
    for tr, te in GroupKFold(5).split(f, groups=f.block):
        for grp in (True, False):
            r = res[tr][g[tr] == grp]
            idx = te[g[te] == grp]
            for c in LEVELS:
                ql, qh = conf_q(r, c)
                lo[c][idx], hi[c][idx] = p[idx] + ql, p[idx] + qh
    return g, lo, hi


def cross_pool(a, others, meth):
    """Residual pool from cross-area pseudo-experiments among the training areas: train on one, residuals on the other."""
    r, g = [], []
    for o in others:
        for q in others:
            if q == o:
                continue
            p = predictions(a[q], a[o], False)[meth]
            r.append(a[o].dh.values - p)
            g.append(flag_raised(a[o], p))
    r, g = np.concatenate(r), np.concatenate(g)
    return {True: r[g], False: r[~g]}


def decided(f, lo, hi, s):
    lag, bfe, ffe = f.e2018_lag.values[s], f.bfe.values[s], f.ffe.values[s]
    above, below = lag + lo[s] >= bfe, lag + hi[s] < bfe
    dec = above | below
    return dec.mean(), (((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan)


def report(f, p, g, lo, hi, title):
    rows = {}
    for lab, m in (("all", np.ones(len(f), bool)), ("screened", f.key_ok.values)):
        for grp_name, gm in (("flagged raised", g), ("not flagged", ~g), ("all houses", np.ones(len(f), bool))):
            mm = m & gm & np.isfinite(p)
            row = {"n": int(mm.sum()), "raised_in_group": int((f.dh.values[mm] > 3).sum())}
            y = f.dh.values[mm]
            for c in LEVELS:
                w = hi[c][mm] - lo[c][mm]
                row[f"cover_{int(c * 100)}"] = ((y >= lo[c][mm]) & (y <= hi[c][mm])).mean()
                row[f"median_width_{int(c * 100)}_ft"] = np.median(w) if len(w) else np.nan
                row[f"infinite_{int(c * 100)}"] = np.isinf(w).mean() if len(w) else np.nan
            s = mm & (f.zone == "SFHA").values & f.bfe.notna().values
            if s.sum():
                row["SFHA_n"] = int(s.sum())
                row["BFE_decided_90"], row["decided_correct"] = decided(f, lo[0.9], hi[0.9], s)
            rows[(lab, grp_name)] = row
    print(f"\n## {title}\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())


def local_calibration(fte, pte, designs, draws=50, c=0.9, seed=20261006):
    """New area, model from elsewhere, 90% bands recalibrated on k measured LOCAL houses. designs: list of
    (n_random, n_unflagged, n_flagged). Coverage / width / BFE decisions on the other houses (screened key)."""
    g = flag_raised(fte, pte)
    res = fte.dh.values - pte
    ok = fte.key_ok.values
    rng = np.random.default_rng(seed)
    out = {}
    for n_rand, n_unf, n_flag in designs:
        nf = min(n_flag, int(g.sum()) // 2)
        rec = []
        for _ in range(draws):
            cal = np.r_[rng.choice(len(fte), n_rand, replace=False)] if n_rand else np.r_[
                rng.choice(np.where(g)[0], nf, replace=False), rng.choice(np.where(~g)[0], n_unf, replace=False)]
            ev = ok.copy()
            ev[cal] = False
            pools = {}
            for grp in (True, False):
                r = res[cal][g[cal] == grp]
                pools[grp] = r if len(r) >= 10 else res[cal]
            ql = {grp: conf_q(r, c) for grp, r in pools.items()}
            lo, hi = np.full(len(fte), np.nan), np.full(len(fte), np.nan)
            for grp in (True, False):
                idx = np.where(g == grp)[0]
                lo[idx], hi[idx] = pte[idx] + ql[grp][0], pte[idx] + ql[grp][1]
            y = fte.dh.values
            cov = (y >= lo) & (y <= hi)
            s = ev & (fte.zone.values == "SFHA") & fte.bfe.notna().values
            dec, cor = decided(fte, lo, hi, s)
            rec.append({"cover_all": cov[ev].mean(), "cover_flagged": cov[ev & g].mean(), "cover_not_flagged": cov[ev & ~g].mean(),
                        "median_width_flagged": np.median((hi - lo)[ev & g]), "median_width_not_flagged": np.median((hi - lo)[ev & ~g]),
                        "BFE_decided": dec, "decided_correct": cor})
        lab = f"{n_rand} random" if n_rand else f"{n_unf} unflagged + {nf} flagged"
        out[lab] = pd.DataFrame(rec).mean()
    return pd.DataFrame(out).T


def main():
    a = {k: load(k) for k in ("A", "B", "C")}
    for f in a.values():
        f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    rows = {}
    for k, f in a.items():
        s, rf, r = f.key_ok.values, records_flag(f), f.dh.values > 3
        m = s & f.eave_p50.notna().values
        rows[k] = {"records flag n": int((s & rf).sum()), "precision": (s & rf & r).sum() / max((s & rf).sum(), 1),
                   "recall": (s & rf & r).sum() / max((s & r).sum(), 1), "raised (key)": int((s & r).sum()),
                   "eave_p50 AUC for raised": roc_auc_score(r[m], f.eave_p50.values[m])}
    print("\n## Records part of the raised flag, per area (scorer; screened key)\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())
    oof = {k: predictions(a[k], a[k], True) for k in a}
    designs = [(30, 0, 0), (50, 0, 0), (100, 0, 0), (0, 30, 20), (0, 30, 40), (0, 30, 60)]
    for meth in ("E + eave estimate", "F E, physical override"):
        for k, f in a.items():
            p = oof[k][meth]
            g, lo, hi = bands_same_area(f, p)
            report(f, p, g, lo, hi, f"{k}, {meth}: cross-conformal within the area")
        for te, fte in a.items():
            others = [o for o in a if o != te]
            ftr = pd.concat([a[o] for o in others], ignore_index=True)
            pte = predictions(ftr, fte, False)[meth]
            g = flag_raised(fte, pte)
            lo, hi = apply_bands(pte, g, cross_pool(a, others, meth))
            report(fte, pte, g, lo, hi, f"{te}, {meth}: model from {'+'.join(others)}, bands from cross-area pseudo-"
                                        f"experiments between {' and '.join(others)} (new area)")
            print(f"\n## {te}, {meth}: model from {'+'.join(others)}, 90% bands recalibrated on k measured local houses "
                  f"(mean of 50 draws; scored on the other screened houses)\n")
            print(local_calibration(fte, pte, designs).round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
