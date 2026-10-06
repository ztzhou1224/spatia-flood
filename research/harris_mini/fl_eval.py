"""Out-of-county test: the Harris method scored on Florida elevation certificates (area P, fl_build.py).

Fixed before scoring. Target (scorer only): certificate first living floor (fl_build.py) minus the 1 m DEM lowest
adjacent grade, ft; screened with the Harris rule (eval_transfer.load: roof_p95 - target < 6 ft or target < -1 ft
fails). Harris training data: areas A + B + C (tiers A+B, front-door target). Florida's assessor schema (DOR NAL) has
no stories / foundation / lower level / basement, so the Harris record features are either
  missing   left NaN (LightGBM routes them as missing), or
  mapped    stories <- NSI stories, im_sq_ft <- NAL living area; the rest NaN.
The label-free eave estimates use NSI instead of HCAD: reference = NSI slab houses (found_type S) per NSI story count
(Harris uses HCAD slab houses without a lower level); est_split = eave_p50 estimate for one-story, eave_main for
two-story. The raised flag (bands.flag_raised) has no record part in Florida, so it is "estimate > 3 ft" only.
Methods:
  0 national default        NSI foundation height
  1 Harris, national inputs benchmark method B features (DEM ground, NSI), trained on A + B + C
  2 Harris E, records missing   method E features
  3 Harris E, records mapped
  4 Florida within-area     method E features (mapped), 5 folds by 1 km block on P itself (best case: all local labels)
  5 Harris E mapped + 50 local certificates (30 unflagged + 20 flagged, weight 10), 20 draws, scored on the held-out
    houses with method 3 on the same sets
  6 local only              LightGBM on the 50 certificates alone
Metrics: n, MAE, within 1 ft, raised (> 3 ft) MAE and recall, BFE side (SFHA houses with a certificate BFE); by
diagram group (slab 1A / 1B; elevated or enclosed 5-9; other). Bands: 90% finite-sample conformal (bands.conf_q),
Mondrian by flag; borrowed = residual pool of Harris cross-area pseudo-experiments (method E), local = residuals of the
50 certificates (cross-fitted, 5 folds); coverage, median width, BFE decided / correct.
Usage: python fl_eval.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from bands import conf_q, flag_raised  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_stories import SLAB_FT  # noqa: E402
from eval_transfer import DEM, load  # noqa: E402

D = HERE.parents[1] / "data" / "harris_mini"
COLS = SETS["E + eave estimate"]
P1 = {**el.P, "n_jobs": 1}
DRAWS = 20


def fit(x, y, w=None, **kw):
    return lgb.LGBMRegressor(**{**P1, **kw}).fit(x, y, sample_weight=w)


def florida(mapped):
    f = load("P")
    rec = pd.read_parquet(D / "P" / "records.parquet")
    f = f.merge(rec[["oid", "tot_lvg_ar"]], on="oid", how="left")
    if mapped:
        f["stories"] = pd.to_numeric(f.nsi_stories, errors="coerce").clip(1, 2)
        f["im_sq_ft"] = f.tot_lvg_ar
    st = pd.to_numeric(f.nsi_stories, errors="coerce").clip(1, 2)
    ref = f[(f.nsi_found_type == "S") & st.notna()]
    for e in ("eave_p50", "eave_main"):
        f[f"est_{e}"] = f[e] - st.map(ref.groupby(st[ref.index])[e].median()) + SLAB_FT
    f["est_split"] = np.where(st == 1, f.est_eave_p50, f.est_eave_main)
    f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
    return f.reset_index(drop=True)


def score(f, p, m):
    y, e = f.dh.values[m], p[m] - f.dh.values[m]
    ok = np.isfinite(e)
    y, e, pm = y[ok], e[ok], p[m][ok]
    r = y > 3
    s = (f.zone.values[m][ok] == "SFHA") & f.bfe.notna().values[m][ok]
    ffe, bfe, lag = f.ffe.values[m][ok][s], f.bfe.values[m][ok][s], f.e2018_lag.values[m][ok][s]
    return {"n": int(ok.sum()), "MAE": np.abs(e).mean(), "within 1 ft": (np.abs(e) <= 1).mean(),
            "raised n": int(r.sum()), "raised MAE": np.abs(e[r]).mean() if r.any() else np.nan,
            "raised recall": (pm[r] > 3).mean() if r.any() else np.nan,
            "BFE side": ((ffe >= bfe) == (lag + pm[s] >= bfe)).mean() if s.any() else np.nan}


def groups(f):
    dg = f.diagram.astype(str)
    return {"all": np.ones(len(f), bool), "slab 1A/1B": dg.isin(["1A", "1B"]).values,
            "elevated / enclosed 5-9": dg.str[0].isin(list("56789")).values}


def harris_pool(h):
    """Residuals of Harris cross-area pseudo-experiments (method E), by flag."""
    r, g = [], []
    for o in h:
        for q in h:
            if q != o:
                p = fit(h[q][COLS], h[q].dh).predict(h[o][COLS])
                r.append(h[o].dh.values - p)
                g.append(flag_raised(h[o], p))
    r, g = np.concatenate(r), np.concatenate(g)
    return {True: r[g], False: r[~g]}


def band_stats(f, p, g, lo, hi, m):
    y = f.dh.values
    cov = (y >= lo) & (y <= hi)
    s = m & (f.zone.values == "SFHA") & f.bfe.notna().values
    lag, bfe, ffe = f.e2018_lag.values[s], f.bfe.values[s], f.ffe.values[s]
    above, below = lag + lo[s] >= bfe, lag + hi[s] < bfe
    dec = above | below
    return {"coverage": cov[m].mean(), "coverage flagged": cov[m & g].mean() if (m & g).any() else np.nan,
            "coverage not flagged": cov[m & ~g].mean(), "median width flagged": np.median((hi - lo)[m & g]) if (m & g).any() else np.nan,
            "median width not flagged": np.median((hi - lo)[m & ~g]), "BFE decided": dec.mean() if s.any() else np.nan,
            "decided correct": ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean() if dec.any() else np.nan}


def main():
    h = {k: load(k) for k in ("A", "B", "C")}
    tr = pd.concat(h.values(), ignore_index=True)
    fm, fn = florida(True), florida(False)
    ok = fm.key_ok.values
    print(f"P: {len(fm)} certificate houses (screen fails {int((~ok).sum())}); target > 3 ft {int((fm.dh > 3).sum())}; "
          f"SFHA with BFE {int(((fm.zone == 'SFHA') & fm.bfe.notna()).sum())}; diagrams "
          f"{fm.diagram.value_counts().head(8).to_dict()}; roof measured {fm.roof_p50.notna().mean():.1%}; "
          f"NSI matched {fm.nsi_found_ht.notna().mean():.1%}")
    preds = {"0 national default (NSI height)": pd.to_numeric(fm.nsi_found_ht, errors="coerce").values,
             "1 Harris, national inputs": fit(tr[DEM], tr.dh).predict(fm[DEM]),
             "2 Harris E, records missing": fit(tr[COLS], tr.dh).predict(fn[COLS]),
             "3 Harris E, records mapped": fit(tr[COLS], tr.dh).predict(fm[COLS])}
    p = np.full(len(fm), np.nan)
    for a, b in GroupKFold(5).split(fm, groups=fm.block):
        p[b] = fit(fm.loc[a, COLS], fm.dh.iloc[a]).predict(fm.loc[b, COLS])
    preds["4 Florida within-area (5-fold by 1 km block)"] = p
    rows = {}
    for gname, gm in groups(fm).items():
        for k, v in preds.items():
            rows[(gname, k)] = score(fm, v, ok & gm)
    print("\n## Florida (St. Petersburg), screened certificates: first living floor above the DEM lowest adjacent grade\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())

    p3 = preds["3 Harris E, records mapped"]
    g = flag_raised(fm, p3)
    rng = np.random.default_rng(20261008)
    acc, bnd = {}, {}
    pool = harris_pool(h)
    for _ in range(DRAWS):
        nf = min(20, int(g.sum()) // 2)
        cal = np.r_[rng.choice(np.where(g)[0], nf, replace=False), rng.choice(np.where(~g)[0], 50 - nf, replace=False)]
        ev = ok.copy()
        ev[cal] = False
        loc = fm.iloc[cal]
        x = pd.concat([tr[COLS], loc[COLS]], ignore_index=True)
        sw = np.r_[np.ones(len(tr)), np.full(len(loc), 10.0)]
        p5 = fit(x, np.r_[tr.dh.values, loc.dh.values], sw).predict(fm[COLS])
        p6 = fit(loc[COLS], loc.dh, min_child_samples=5).predict(fm[COLS])
        for gname, gm in groups(fm).items():
            for k, v in (("3 Harris E mapped (same set)", p3), ("5 Harris + 50 local certificates (W 10)", p5), ("6 local only (50)", p6)):
                acc.setdefault((gname, k), []).append(score(fm, v, ev & gm) | {"flagged in sample": nf})
        # bands: borrowed Harris pool on method 3; local cross-fitted residuals on method 5
        lo, hi = np.full(len(fm), np.nan), np.full(len(fm), np.nan)
        for grp in (True, False):
            ql, qh = conf_q(pool[grp], 0.9)
            idx = g == grp
            lo[idx], hi[idx] = p3[idx] + ql, p3[idx] + qh
        bnd.setdefault("borrowed from Harris (method 3)", []).append(band_stats(fm, p3, g, lo, hi, ev))
        res = np.empty(len(cal))
        for part in np.array_split(rng.permutation(len(cal)), 5):
            keep = np.setdiff1d(np.arange(len(cal)), part)
            sub = loc.iloc[keep]
            xx = pd.concat([tr[COLS], sub[COLS]], ignore_index=True)
            ww = np.r_[np.ones(len(tr)), np.full(len(sub), 10.0)]
            res[part] = loc.dh.values[part] - fit(xx, np.r_[tr.dh.values, sub.dh.values], ww).predict(loc.iloc[part][COLS])
        g5 = flag_raised(fm, p5)
        lo, hi = np.full(len(fm), np.nan), np.full(len(fm), np.nan)
        for grp in (True, False):
            r = res[g5[cal] == grp] if (g5[cal] == grp).sum() >= 10 else res
            ql, qh = conf_q(r, 0.9)
            idx = g5 == grp
            lo[idx], hi[idx] = p5[idx] + ql, p5[idx] + qh
        bnd.setdefault("local, 50 certificates cross-fitted (method 5)", []).append(band_stats(fm, p5, g5, lo, hi, ev))
    print(f"\n## Florida: Harris model + 50 local certificates (30 unflagged + up to 20 flagged; mean of {DRAWS} draws; "
          f"held-out houses)\n")
    print(pd.DataFrame({k: pd.DataFrame(v).mean() for k, v in acc.items()}).T.round(3).to_markdown())
    print(f"\n## Florida: 90% conformal bands (mean of {DRAWS} draws; held-out houses)\n")
    print(pd.DataFrame({k: pd.DataFrame(v).mean() for k, v in bnd.items()}).T.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
