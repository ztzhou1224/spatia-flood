"""Do we need a separate floor-height model per state? Cross-state test on houses_all.parquet (build_table.py).

For each place T (FL, NC, VA, NYC = Staten Island, HAR = Harris County):
  NSI default    the national inventory's foundation height, no model
  other places   one model trained on the OTHER four places only (what a new state gets on day one)
  pooled         trained on the other four places + T's houses in other spatial blocks (GroupKFold, 5 folds)
  local only     trained on T's houses in other spatial blocks only (a separate per-state model)
plus a pairwise matrix: train on one place, test on another. Every training place is capped at 30,000 houses
(fixed seed) so the big places do not swamp the rest. Target and inputs: build_table.py. Metric: MAE of floor
height (ft), within 1 ft, and raised-house (> 6 ft) MAE. Usage: python cross_state.py
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

S = Path(__file__).resolve().parents[2] / "data" / "states"
X = ["nsi_ft", "nsi_fh", "nsi_story", "nsi_year", "year", "sfha", "ve", "bfe_minus_ground"]
P = dict(objective="l1", n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.8, verbose=-1)
CAP = 30000
PLACES = ["FL", "NC", "VA", "NYC", "HAR"]


def cap(d):
    return d.groupby("state", group_keys=False).apply(lambda g: g.sample(min(len(g), CAP), random_state=0))


def fit(d):
    return lgb.LGBMRegressor(**P).fit(d[X], d.y)


def m(e, raised):
    e = pd.Series(e)
    return dict(MAE=e.abs().mean(), within_1=(e.abs() <= 1).mean(), raised_MAE=e[raised].abs().mean())


def main():
    t = pd.read_parquet(S / "houses_all.parquet")
    print(f"houses: {t.state.value_counts().reindex(PLACES).to_dict()}")
    print(t.groupby("state").agg(houses=("y", "size"), median_height=("y", "median"), raised_share=("y", lambda s: (s > 6).mean()),
                                 nsi_default_median=("nsi_fh", "median")).reindex(PLACES).round(2).to_markdown())
    rows = {}
    for T in PLACES:
        test = t[t.state == T]
        others = cap(t[t.state != T])
        raised = (test.y > 6).values
        res = {"NSI default": m(test.nsi_fh - test.y, raised)}
        res["other places"] = m(fit(others).predict(test[X]) - test.y.values, raised)
        pooled, local = np.full(len(test), np.nan), np.full(len(test), np.nan)
        for tr, te in GroupKFold(5).split(test, groups=test.block):
            tr_d = cap(test.iloc[tr])
            pooled[te] = fit(pd.concat([others, tr_d])).predict(test.iloc[te][X])
            local[te] = fit(tr_d).predict(test.iloc[te][X])
        res["pooled (others + this state)"] = m(pooled - test.y.values, raised)
        res["local only (this state)"] = m(local - test.y.values, raised)
        for k, v in res.items():
            rows[(T, k)] = v
    out = pd.DataFrame(rows).T
    out.index.names = ["test place", "model"]
    print("\n## Floor height error (ft) by test place and model\n")
    print(out.round(2).to_markdown())
    print("\n## Pairwise: MAE (ft) training on ONE place (rows) and testing on another (columns); diagonal = local 5-fold\n")
    mat = pd.DataFrame(index=PLACES, columns=PLACES, dtype=float)
    for A in PLACES:
        mdl = fit(cap(t[t.state == A]))
        for B in PLACES:
            if A != B:
                tb = t[t.state == B]
                mat.loc[A, B] = np.mean(np.abs(mdl.predict(tb[X]) - tb.y))
        mat.loc[A, A] = out.loc[(A, "local only (this state)"), "MAE"]
    print(mat.round(2).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
