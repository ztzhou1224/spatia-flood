"""How many measured local houses does a new area need? Model from the other two areas + a small local sample.

For each test area: the pooled model (other two areas, benchmark method E features) gives a first estimate p0; the
label-free raised flag (bands.flag_raised: record basement / lower level / two-story crawl space, or p0 > 3 ft) picks
the sample: n_flag flagged + n_unf unflagged houses at random (the houses one would send a surveyor to). Methods,
fixed before scoring:
  pooled            model from the other two areas only (k = 0)
  pooled + local    the same LightGBM refit on the other two areas + the local sample, local rows weight W
                    (W = 1 and W = 10 both reported)
  local only        LightGBM on the local sample alone (min_child_samples 5)
  + override        any of the above with benchmark method F's physical override on flagged houses
Scored on the area's other houses (screened answer key); the pooled model is also scored on the SAME held-out set
of every draw ("pooled (no local labels), same scored set"), so k = 0 and k > 0 compare like for like (review fix,
2026-10-06: the k = 0 row alone is scored on all houses, including the sampled ones). In B only 34 houses are flagged,
so at most 17 are sampled; row labels give the counts actually used: MAE, raised (door > 3 ft) MAE and recall, BFE side; mean of
20 draws. Answer key: scorer, and the local sample's measured heights (as a surveyor would supply).
Usage: python eval_local.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from bands import flag_raised  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_transfer import load  # noqa: E402

COLS = SETS["E + eave estimate"]
SIZES = ((30, 20), (60, 40), (120, 80))
DRAWS = 20
P1 = {**el.P, "n_jobs": 1}  # one thread: 0.6 s per fit vs 71 s with the default on a loaded 4-core machine


def override(f, p):
    flag = flag_raised(f, p)
    phys = f.est_split.values
    return np.where(flag & np.isfinite(phys) & (phys > 3), phys, p)


def score(f, p, m):
    y, e = f.dh.values[m], p[m] - f.dh.values[m]
    r = y > 3
    s = (f.zone.values[m] == "SFHA") & f.bfe.notna().values[m]
    side = ((f.ffe.values[m][s] >= f.bfe.values[m][s]) == (f.e2018_lag.values[m][s] + p[m][s] >= f.bfe.values[m][s])).mean()
    return {"MAE": np.abs(e).mean(), "raised MAE": np.abs(e[r]).mean(), "raised recall": (p[m][r] > 3).mean(),
            "BFE side": side}


def main():
    a = {k: load(k) for k in ("A", "B", "C")}
    rng = np.random.default_rng(20261006)
    for te, f in a.items():
        tr = pd.concat([a[o] for o in a if o != te], ignore_index=True)
        p0 = lgb.LGBMRegressor(**P1).fit(tr[COLS], tr.dh).predict(f[COLS])
        g = flag_raised(f, p0)
        ok = f.key_ok.values
        res = {}
        base = {"pooled": p0, "pooled + override": override(f, p0)}
        for nm, p in base.items():
            res[(nm, "k = 0")] = score(f, p, ok)
        for n_unf, n_flag in SIZES:
            acc = {}
            for _ in range(DRAWS):
                nf = min(n_flag, int(g.sum()) // 2)  # B has few flagged houses: keep half of them for scoring
                cal = np.r_[rng.choice(np.where(g)[0], nf, replace=False), rng.choice(np.where(~g)[0], n_unf, replace=False)]
                ev = ok.copy()
                ev[cal] = False
                loc = f.iloc[cal]
                preds = {"pooled (no local labels), same scored set": p0}
                for w in (1, 10):
                    x = pd.concat([tr[COLS], loc[COLS]], ignore_index=True)
                    y = np.r_[tr.dh.values, loc.dh.values]
                    sw = np.r_[np.ones(len(tr)), np.full(len(loc), float(w))]
                    preds[f"pooled + local (W {w})"] = lgb.LGBMRegressor(**P1).fit(x, y, sample_weight=sw).predict(f[COLS])
                preds["local only"] = lgb.LGBMRegressor(**{**P1, "min_child_samples": 5}).fit(loc[COLS], loc.dh).predict(f[COLS])
                for nm in list(preds):
                    preds[f"{nm} + override"] = override(f, preds[nm])
                for nm, p in preds.items():
                    acc.setdefault(nm, []).append(score(f, p, ev))
            nf = min(n_flag, int(g.sum()) // 2)
            for nm, v in acc.items():
                res[(nm, f"k = {n_unf} unflagged + {nf} flagged")] = pd.DataFrame(v).mean().to_dict()
        print(f"\n## {te}: model from {'+'.join(o for o in a if o != te)} plus k measured local houses "
              f"(screened key; flagged houses in the area {int(g.sum())}; mean of {DRAWS} draws)\n")
        print(pd.DataFrame(res).T.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
