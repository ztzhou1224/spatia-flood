"""Does the deck / landing surface (lpc_ring.py) measure the floor of raised houses, or help the model?

Scorer only. For each area: share of houses with a deck_h, and deck_h - target (median signed, median absolute,
within 1 ft) for raised (target > 3 ft) and other houses; then method E within the area (5 folds by 1 km block)
with and without deck_h / deck_n / flat_n as features. Areas: Harris (eval_transfer.load) or P (fl_eval.florida).
Usage: python eval_ring.py C P
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
from benchmark import SETS  # noqa: E402
from eval_transfer import load  # noqa: E402
from fl_eval import florida  # noqa: E402

D = HERE.parents[1] / "data" / "harris_mini"
COLS = SETS["E + eave estimate"]
RING = ["deck_h", "deck_n", "flat_n"]
P1 = {**el.P, "n_jobs": 1}


def main(areas):
    for area in areas:
        f = florida(True) if area == "P" else load(area)
        f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
        f = f.merge(pd.read_parquet(D / area / "lpc_ring.parquet"), on="oid", how="left").reset_index(drop=True)
        s = f[f.key_ok]
        rows = {}
        for nm, m in (("raised (> 3 ft)", s.dh > 3), ("not raised", s.dh <= 3)):
            x = s[m]
            e = (x.deck_h - x.dh).dropna()
            rows[nm] = {"n": len(x), "deck found": x.deck_h.notna().mean(), "median signed": e.median(),
                        "median abs": e.abs().median(), "within 1 ft": (e.abs() <= 1).mean()}
        print(f"\n## {area}: deck / landing height vs target (screened)\n")
        print(pd.DataFrame(rows).T.round(3).to_markdown())
        res = {}
        for nm, cols in (("E", COLS), ("E + deck", COLS + RING)):
            p = np.full(len(f), np.nan)
            for a, b in GroupKFold(5).split(f, groups=f.block):
                p[b] = lgb.LGBMRegressor(**P1).fit(f.loc[a, cols], f.dh.iloc[a]).predict(f.loc[b, cols])
            ok = f.key_ok.values
            e = p[ok] - f.dh.values[ok]
            r = f.dh.values[ok] > 3
            res[nm] = {"MAE": np.abs(e).mean(), "raised MAE": np.abs(e[r]).mean(), "raised recall": (p[ok][r] > 3).mean()}
        print(f"\n## {area}: method E within the area, with and without the deck features\n")
        print(pd.DataFrame(res).T.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1:])
