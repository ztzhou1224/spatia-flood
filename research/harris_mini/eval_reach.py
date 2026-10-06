"""How far does a measured house inform its neighbours? (the overlapping-circles idea)

Residual r = answer-key door height - benchmark method E, out-of-fold (5 folds by 1 km block), screened key.
1) Correlation of r between pairs of houses by distance (what a measured house says about a house d metres away).
2) Neighbour correction: E + mean r of measured houses within R metres that lie in OTHER 1 km blocks (so the
   correction never uses the house's own block), for R = 250, 500, 1,000, 2,000 m, vs E alone; houses without
   such neighbours keep E. Areas A, B, C.
3) The overlapping-circles case: model from the OTHER two areas (no local labels); the west half of the area
   (x below its median) is measured, the east half is not. East-half houses: error of the pooled model, of the pooled
   model refit with the west half (weight 10, as eval_local.py), and of the pooled model + mean residual of measured
   west-half houses within 1 km, by distance from the measured half (0-500, 500-1,000, 1,000-2,000, > 2,000 m).
Usage: python eval_reach.py
"""
import sys
from itertools import pairwise
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from benchmark import SETS, predictions  # noqa: E402
from eval_transfer import load  # noqa: E402

BINS = [0, 100, 250, 500, 1000, 2000, 4000]
RADII = (250, 500, 1000, 2000)
COLS = SETS["E + eave estimate"]
P1 = {**el.P, "n_jobs": 1}


def circles(a):
    for te, f in a.items():
        tr = pd.concat([a[o] for o in a if o != te], ignore_index=True)
        f = f[f.key_ok].reset_index(drop=True)
        west = (f.x < f.x.median()).values
        p0 = lgb.LGBMRegressor(**P1).fit(tr[COLS], tr.dh).predict(f[COLS])
        x = pd.concat([tr[COLS], f.loc[west, COLS]], ignore_index=True)
        sw = np.r_[np.ones(len(tr)), np.full(west.sum(), 10.0)]
        p1 = lgb.LGBMRegressor(**P1).fit(x, np.r_[tr.dh.values, f.dh.values[west]], sample_weight=sw).predict(f[COLS])
        r0 = f.dh.values - p0
        wtree = cKDTree(np.c_[f.x[west], f.y[west]])
        exy = np.c_[f.x[~west], f.y[~west]]
        dist, _ = wtree.query(exy)
        nb = wtree.query_ball_point(exy, 1000)
        rw = r0[west]
        p2 = p0[~west] + np.array([rw[n].mean() if n else 0.0 for n in nb])
        y = f.dh.values[~west]
        rows = {}
        for lo, hi in ((0, 500), (500, 1000), (1000, 2000), (2000, 1e9)):
            m = (dist >= lo) & (dist < hi)
            if m.sum() < 30:
                continue
            r = m & (y > 3)
            rows[f"{lo}-{hi if hi < 1e9 else 'max'} m from the measured half"] = {
                "houses": int(m.sum()), "raised": int(r.sum()),
                "MAE pooled": np.abs(p0[~west][m] - y[m]).mean(), "MAE refit with west half": np.abs(p1[~west][m] - y[m]).mean(),
                "MAE pooled + neighbour residual": np.abs(p2[m] - y[m]).mean(),
                "raised MAE pooled": np.abs(p0[~west][r] - y[r]).mean(), "raised MAE refit": np.abs(p1[~west][r] - y[r]).mean(),
                "raised MAE + neighbour residual": np.abs(p2[r] - y[r]).mean()}
        print(f"\n## {te}: model from the other areas, west half measured, east half scored\n")
        print(pd.DataFrame(rows).T.round(3).to_markdown())


def main():
    circles({k: load(k) for k in ("A", "B", "C")})
    for area in ("A", "B", "C"):
        f = load(area)
        f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
        f["E"] = predictions(f, f, True)["E + eave estimate"]
        f = f[f.key_ok].reset_index(drop=True)
        r = (f.dh - f.E).values
        xy = np.c_[f.x, f.y]
        tree = cKDTree(xy)
        pairs = tree.query_pairs(BINS[-1], output_type="ndarray")
        d = np.hypot(*(xy[pairs[:, 0]] - xy[pairs[:, 1]]).T)
        rows = {}
        for lo, hi in pairwise(BINS):
            m = (d >= lo) & (d < hi)
            a, b = r[pairs[m, 0]], r[pairs[m, 1]]
            ra, rb = f.dh.values[pairs[m, 0]] > 3, f.dh.values[pairs[m, 1]] > 3
            rows[f"{lo}-{hi} m"] = {"pairs": int(m.sum()), "corr of residuals": np.corrcoef(np.r_[a, b], np.r_[b, a])[0, 1],
                                    "corr of raised (door > 3 ft)": np.corrcoef(np.r_[ra, rb], np.r_[rb, ra])[0, 1]}
        print(f"\n## {area}: residual of method E between two houses, by distance (screened key, {len(f)} houses)\n")
        print(pd.DataFrame(rows).T.round(3).to_markdown())
        blk = f.block.values
        res = {"E alone": {"MAE": np.abs(r).mean(), "raised MAE": np.abs(r[f.dh.values > 3]).mean(), "corrected share": 0.0}}
        for R in RADII:
            nb = tree.query_ball_point(xy, R)
            corr = np.array([np.mean(r[[j for j in n if blk[j] != blk[i]]]) if any(blk[j] != blk[i] for j in n) else 0.0
                             for i, n in enumerate(nb)])
            has = np.array([any(blk[j] != blk[i] for j in n) for i, n in enumerate(nb)])
            e = r - corr
            res[f"E + mean residual of measured houses within {R} m (other blocks)"] = {
                "MAE": np.abs(e).mean(), "raised MAE": np.abs(e[f.dh.values > 3]).mean(), "corrected share": has.mean()}
        print(f"\n## {area}: neighbour correction\n")
        print(pd.DataFrame(res).T.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
