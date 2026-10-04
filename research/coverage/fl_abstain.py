"""Florida, 1 m lidar subset: how often is the above/below-BFE call right if the product says
'too close to call' when the estimated floor is within M ft of the BFE?
Estimate = lidar ring median + floor height from the GBM trained on OTHER counties (fl_lidar.py, no NFIP).
Usage: python fl_abstain.py
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

import fl_lidar

D = Path(__file__).resolve().parents[2] / "data" / "fl"
P = dict(objective="l1", n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.8, verbose=-1)


def main():
    ec = fl_lidar.load()
    X, y = fl_lidar.features(ec), ec.floor - ec.lag
    p = pd.Series(np.nan, index=ec.index)
    for tr, te in GroupKFold(5).split(X, groups=ec.county_fips):
        p.iloc[te] = lgb.LGBMRegressor(**P).fit(X.iloc[tr], y.iloc[tr]).predict(X.iloc[te])
    g = pd.read_parquet(D / "lidar_ground.parquet")
    t = ec.loc[g.index].join(g)
    t = t[t.bfe.notna()]
    est = t.l_med + p.loc[t.index]
    gap = est - t.bfe
    right = (est >= t.bfe) == (t.floor >= t.bfe)
    print(f"certificates with a BFE: {len(t)}; truly below BFE {(t.floor < t.bfe).mean():.1%}")
    rows = {}
    for m in (0, 0.5, 1.0, 1.5, 2.0, 3.0):
        call = gap.abs() >= m
        rows[f"{m} ft"] = dict(answered=call.mean(), right_when_answered=right[call].mean(),
                               below_BFE_found=((est < t.bfe) & (t.floor < t.bfe) & call).sum() / max((t.floor < t.bfe).sum(), 1))
    print(pd.DataFrame(rows).T.round(3).to_markdown())


if __name__ == "__main__":
    main()
