"""Per-house error bands (split / cross conformal, Mondrian by a label-free raised flag), and what they mean for the BFE.

Point estimate: method E or F of benchmark.py (out-of-fold, 5 folds by 1 km block). For houses in test fold k, the band
is p + [q_lo, q_hi], where q_lo / q_hi are the (1-c)/2 and (1+c)/2 quantiles of the signed out-of-fold residuals
(truth - estimate) of the houses in the OTHER folds of the same group. Groups (Mondrian, label-free): flagged raised
(record basement / lower level / two-story crawl space, or estimate > 3 ft) vs not flagged. For a new area, the
residuals come from the training area (its own out-of-fold estimates) and are applied unchanged.
Reported per group: empirical coverage of the 80% and 90% bands and their mean width; for SFHA houses with a BFE:
share of houses whose 90% band lies entirely above or below the BFE ("decided"), and the share of decided houses
on the correct side. Answer key = scorer only; results with all houses and with the screened answer key.
Usage: python bands.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
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


def bands_same_area(f, p):
    """Cross-conformal within an area: residuals from the other folds of the same group."""
    g = flag_raised(f, p)
    res = f.dh.values - p
    lo = {c: np.full(len(f), np.nan) for c in LEVELS}
    hi = {c: np.full(len(f), np.nan) for c in LEVELS}
    for tr, te in GroupKFold(5).split(f, groups=f.block):
        for grp in (True, False):
            r = res[tr][(g[tr] == grp) & np.isfinite(res[tr])]
            idx = te[g[te] == grp]
            for c in LEVELS:
                lo[c][idx] = p[idx] + np.quantile(r, (1 - c) / 2)
                hi[c][idx] = p[idx] + np.quantile(r, (1 + c) / 2)
    return g, lo, hi


def bands_new_area(ftr, ptr, fte, pte):
    gtr, gte = flag_raised(ftr, ptr), flag_raised(fte, pte)
    res = ftr.dh.values - ptr
    lo = {c: np.full(len(fte), np.nan) for c in LEVELS}
    hi = {c: np.full(len(fte), np.nan) for c in LEVELS}
    for grp in (True, False):
        r = res[(gtr == grp) & np.isfinite(res)]
        idx = np.where(gte == grp)[0]
        for c in LEVELS:
            lo[c][idx] = pte[idx] + np.quantile(r, (1 - c) / 2)
            hi[c][idx] = pte[idx] + np.quantile(r, (1 + c) / 2)
    return gte, lo, hi


def report(f, p, g, lo, hi, title):
    rows = {}
    for lab, m in (("all", np.ones(len(f), bool)), ("screened", f.key_ok.values)):
        for grp_name, gm in (("flagged raised", g), ("not flagged", ~g), ("all houses", np.ones(len(f), bool))):
            mm = m & gm & np.isfinite(p)
            row = {"n": int(mm.sum()), "raised_in_group": int((f.dh.values[mm] > 3).sum())}
            for c in LEVELS:
                y = f.dh.values[mm]
                row[f"cover_{int(c * 100)}"] = ((y >= lo[c][mm]) & (y <= hi[c][mm])).mean()
                row[f"width_{int(c * 100)}_ft"] = (hi[c][mm] - lo[c][mm]).mean()
            s = mm & (f.zone == "SFHA").values & f.bfe.notna().values
            if s.sum():
                lag, bfe, ffe = f.e2018_lag.values[s], f.bfe.values[s], f.ffe.values[s]
                above, below = lag + lo[0.9][s] >= bfe, lag + hi[0.9][s] < bfe
                dec = above | below
                row["SFHA_n"] = int(s.sum())
                row["BFE_decided_90"] = dec.mean()
                row["decided_correct"] = ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan
            rows[(lab, grp_name)] = row
    print(f"\n## {title}\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())


def local_calibration(fte, pte, sizes=(30, 50, 100), draws=50, c=0.9, n_flagged=0):
    """New area, model from elsewhere, bands recalibrated on k random LOCAL measured houses (Mondrian; a group with
    < 10 calibration houses falls back to all k residuals). Coverage / width / BFE decisions on the other houses."""
    g = flag_raised(fte, pte)
    res = fte.dh.values - pte
    rng = np.random.default_rng(20261006)
    out = {}
    for k in sizes:
        rec = []
        for _ in range(draws):
            if n_flagged:  # stratified: n_flagged flagged houses + k unflagged houses (label-free choice)
                cal = np.r_[rng.choice(np.where(g)[0], n_flagged, replace=False), rng.choice(np.where(~g)[0], k, replace=False)]
            else:
                cal = rng.choice(len(fte), k, replace=False)
            ev = np.setdiff1d(np.arange(len(fte)), cal)
            lo, hi = np.full(len(fte), np.nan), np.full(len(fte), np.nan)
            for grp in (True, False):
                r = res[cal][g[cal] == grp]
                if len(r) < 10:
                    r = res[cal]
                idx = ev[g[ev] == grp]
                lo[idx], hi[idx] = pte[idx] + np.quantile(r, (1 - c) / 2), pte[idx] + np.quantile(r, (1 + c) / 2)
            y = fte.dh.values[ev]
            cov = (y >= lo[ev]) & (y <= hi[ev])
            fl = g[ev]
            s_ = ev[(fte.zone.values[ev] == "SFHA") & fte.bfe.notna().values[ev]]
            lag, bfe, ffe = fte.e2018_lag.values[s_], fte.bfe.values[s_], fte.ffe.values[s_]
            above, below = lag + lo[s_] >= bfe, lag + hi[s_] < bfe
            dec = above | below
            rec.append({"cover_all": cov.mean(), "cover_flagged": cov[fl].mean() if fl.any() else np.nan,
                        "width_all": np.nanmean(hi[ev] - lo[ev]), "BFE_decided": dec.mean(),
                        "decided_correct": ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan})
        out[f"k = {k} local houses" + (f" + {n_flagged} flagged" if n_flagged else "")] = pd.DataFrame(rec).mean()
    return pd.DataFrame(out).T


def main():
    a = {k: load(k) for k in ("B", "C")}
    for f in a.values():
        f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    oof = {k: predictions(a[k], a[k], True) for k in a}
    for meth in ("E + eave estimate", "F E, physical override"):
        for k, f in a.items():
            p = oof[k][meth]
            g, lo, hi = bands_same_area(f, p)
            report(f, p, g, lo, hi, f"{k}, {meth}: cross-conformal within the area")
        for tr, te in (("C", "B"), ("B", "C")):
            pte = predictions(a[tr], a[te], False)[meth]
            g, lo, hi = bands_new_area(a[tr], oof[tr][meth], a[te], pte)
            report(a[te], pte, g, lo, hi, f"{te}, {meth}: model AND bands from {tr} (new area)")
            print(f"\n## {te}, {meth}: model from {tr}, 90% bands recalibrated on k random local houses (mean of 50 draws)\n")
            print(pd.concat([local_calibration(a[te], pte), local_calibration(a[te], pte, sizes=(30,), n_flagged=20)]).round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
