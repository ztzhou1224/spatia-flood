"""How many measured houses does a NEW region need, and how should they be used?

Scenario: a target region B has no model; donors are regions >= 100 km away (similarity_test.py set-up: 0.25 deg
cells with >= 300 houses, <= 3,000 training houses per region). From B, n measured 'probe' houses are known
(n = 0, 5, 10, 20, 30, 50, 100; the first n of a fixed random order); every method is scored on the same held-out
B houses (B's evaluation sample minus its first 100 houses), so the probe houses are never scored.
Methods:
  pooled donors            one model on all donors (n = 0 baseline, label-free)
  pooled + bias            pooled donors + median residual on the probe houses
  probe-picked donor       the single donor whose model has the lowest MAE on the probe houses
  probe-picked + bias      that donor + median probe residual
  probe-picked top 3       the 3 donors with the lowest probe MAE, pooled into one model
  probe houses only        a model trained on the n probe houses alone
  local (reference)        B's own model trained on up to 3,000 B houses
Usage: python probe_curve.py
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

S = Path(__file__).resolve().parents[2] / "data" / "states"
X = ["nsi_ft", "nsi_fh", "nsi_story", "nsi_year", "year", "sfha", "ve", "bfe_minus_ground"]
P = dict(objective="l1", n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=30, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.8, verbose=-1)
PS = dict(P, min_child_samples=3, n_estimators=100)
MIN_N, NTR, NEV, CELL, FAR = 300, 3000, 1000, 0.25, 100
NS = [0, 5, 10, 20, 30, 50, 100]


def main():
    t = pd.read_parquet(S / "houses_all.parquet")
    t["region"] = t.state + "_" + (t.lon // CELL).astype(int).astype(str) + "_" + (t.lat // CELL).astype(int).astype(str)
    cnt = t.region.value_counts()
    t = t[t.region.isin(cnt[cnt >= MIN_N].index)]
    regs = sorted(t.region.unique())
    tr, ev, models, cen = {}, {}, {}, {}
    for r in regs:
        g = t[t.region == r].sample(frac=1, random_state=0)
        ev[r] = g.iloc[:min(NEV, len(g) // 3)]
        tr[r] = g.iloc[len(ev[r]):][:NTR]
        models[r] = lgb.LGBMRegressor(**P).fit(tr[r][X], tr[r].y)
        cen[r] = (g.lat.mean(), g.lon.mean())
    km = lambda a, b: np.hypot((cen[a][0] - cen[b][0]) * 111, (cen[a][1] - cen[b][1]) * 111 * np.cos(np.radians(cen[a][0])))
    res = {}
    for b in regs:
        donors = [a for a in regs if a != b and km(a, b) >= FAR]
        if len(donors) < 5 or len(ev[b]) < 150:
            continue
        probe_all, test = ev[b].iloc[:100], ev[b].iloc[100:]
        pool = pd.concat([tr[a].sample(min(len(tr[a]), 600), random_state=0) for a in donors])
        pm = lgb.LGBMRegressor(**P).fit(pool[X], pool.y)
        p_pool_test, p_pool_probe = pm.predict(test[X]), pm.predict(probe_all[X])
        dpred_test = {a: models[a].predict(test[X]) for a in donors}
        dpred_probe = {a: models[a].predict(probe_all[X]) for a in donors}
        err = lambda p: np.mean(np.abs(p - test.y.values))
        res[(b, "local (reference)", 0)] = err(models[b].predict(test[X]))
        for n in NS:
            pr = probe_all.iloc[:n]
            res[(b, "pooled donors", n)] = err(p_pool_test)
            if n == 0:
                continue
            res[(b, "pooled + bias", n)] = err(p_pool_test + np.median(pr.y.values - p_pool_probe[:n]))
            score = {a: np.mean(np.abs(dpred_probe[a][:n] - pr.y.values)) for a in donors}
            order = sorted(score, key=score.get)
            best = order[0]
            res[(b, "probe-picked donor", n)] = err(dpred_test[best])
            res[(b, "probe-picked + bias", n)] = err(dpred_test[best] + np.median(pr.y.values - dpred_probe[best][:n]))
            top3 = pd.concat([tr[a] for a in order[:3]])
            res[(b, "probe-picked top 3", n)] = err(lgb.LGBMRegressor(**P).fit(top3[X], top3.y).predict(test[X]))
            if n >= 10:
                res[(b, "probe houses only", n)] = err(lgb.LGBMRegressor(**PS).fit(pr[X], pr.y).predict(test[X]))
    r = pd.Series(res).rename_axis(["region", "method", "n"]).reset_index(name="mae")
    tab = r.groupby(["method", "n"]).mae.mean().unstack("n")
    order = ["local (reference)", "pooled donors", "pooled + bias", "probe-picked donor", "probe-picked + bias", "probe-picked top 3", "probe houses only"]
    print(f"target regions: {r.region.nunique()}; donors >= {FAR} km away; mean MAE (ft) over target regions, by number of measured probe houses n\n")
    print(tab.reindex(order).round(2).to_markdown())
    by_state = r[r.n.isin([0, 30])].assign(state=r.region.str.split("_").str[0])
    print("\nby state, n = 30 (n = 0 for pooled donors / local):")
    sel = by_state[((by_state.n == 30) & by_state.method.isin(["probe-picked + bias", "pooled + bias"])) |
                   by_state.method.isin(["local (reference)"]) | ((by_state.n == 0) & (by_state.method == "pooled donors"))]
    print(sel.groupby(["state", "method"]).mae.mean().unstack("method").round(2).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
