"""Do soil, climate, terrain and flood-rule context define housing similarity better than the inputs alone?

Same regions, models, train / evaluation split and transfer matrix as similarity_test.py (mae_matrix.parquet).
Region context: region_context.py (soil, climate, terrain, rules). Label-free measures, standardized Euclidean
distance between region vectors:
  geo_km, desc_all            as in similarity_test.py (for comparison)
  ctx_soil, ctx_climate, ctx_terrain, ctx_rules, ctx_all, desc_all + ctx_all
  learned                     a GBM that predicts MAE[A, B] from |differences| of every descriptor and context
                              variable + distance + same state, fitted on pairs NOT involving the target region
                              (leave-one-target-out), then used to rank donors for the target
Tests: (1) donor choice as in similarity_test.py (Spearman, top-1, top-3 pooled; all donors and donors >= 100 km);
(2) pooled fallback for a new area (donors >= 100 km): one model on all donors' houses with the house inputs only,
vs + the region context as features, vs + context and descriptors.
Usage: python context_test.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import similarity_test as st  # noqa: E402

D = HERE.parents[1] / "data"
X, P = st.X, st.P


def main():
    t = pd.read_parquet(D / "states" / "houses_all.parquet")
    t["region"] = t.state + "_" + (t.lon // st.CELL).astype(int).astype(str) + "_" + (t.lat // st.CELL).astype(int).astype(str)
    cnt = t.region.value_counts()
    t = t[t.region.isin(cnt[cnt >= st.MIN_N].index)].copy()
    regs = sorted(t.region.unique())
    tr, ev = {}, {}
    for r in regs:
        g = t[t.region == r].sample(frac=1, random_state=0)
        ev[r] = g.iloc[:min(st.NEV, len(g) // 3)]
        tr[r] = g.iloc[len(ev[r]):][:st.NTR]
    mae = pd.read_parquet(D / "similarity" / "mae_matrix.parquet").loc[regs, regs]
    desc = t.groupby("region").apply(st.descriptors).loc[regs]
    ctx = pd.read_csv(D / "similarity" / "region_context.csv", index_col="region").loc[regs]
    ctx = ctx.drop(columns=["county_fips", "soil_units", "rule_communities"])
    ctx = ctx.fillna(ctx.median())
    dcols = ["f_slab", "f_crawl", "f_bsmt", "f_pier", "f_fh", "a_year", "a_new", "x_sfha", "x_ve", "x_bfe_g"]
    groups = {"ctx_soil": [c for c in ctx if c.startswith("soil_")], "ctx_climate": [c for c in ctx if c.startswith("clim_")],
              "ctx_terrain": [c for c in ctx if c.startswith("terr_")], "ctx_rules": [c for c in ctx if c.startswith("rule_")]}
    groups["ctx_all"] = sum(groups.values(), [])
    full = pd.concat([desc[dcols], ctx], axis=1)
    z = ((full - full.mean()) / full.std()).fillna(0)
    meas = {}
    lat, lon = desc.lat.values, desc.lon.values
    geo = pd.DataFrame(np.hypot((lat[:, None] - lat[None]) * 111, (lon[:, None] - lon[None]) * 111 * np.cos(np.radians(lat.mean()))),
                       index=regs, columns=regs)
    meas["geo_km"] = geo
    groups = {"desc_all": dcols, **groups, "desc_all + ctx_all": dcols + groups["ctx_all"]}
    for k, cols in groups.items():
        v = z[cols].values
        meas[k] = pd.DataFrame(np.sqrt(((v[:, None] - v[None]) ** 2).sum(-1)), index=regs, columns=regs)
    # learned similarity: pairwise |differences| -> transfer MAE, leave-one-target-out
    stt = np.array([r.split("_")[0] for r in regs])
    zv = z.values
    pairs = [(i, j) for i in range(len(regs)) for j in range(len(regs)) if i != j]
    F = np.array([np.r_[np.abs(zv[i] - zv[j]), geo.values[i, j], float(stt[i] == stt[j])] for i, j in pairs])
    yv = np.array([mae.values[i, j] for i, j in pairs])
    pi, pj = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    learned = pd.DataFrame(np.nan, index=regs, columns=regs)
    for b in range(len(regs)):
        keep = (pj != b) & (pi != b)
        mdl = lgb.LGBMRegressor(objective="l2", n_estimators=300, learning_rate=0.05, num_leaves=15, verbose=-1).fit(F[keep], yv[keep])
        rows = pj == b
        learned.iloc[pi[rows], b] = mdl.predict(F[rows])
    meas["learned (pairs, leave target out)"] = learned
    out = {}
    for far in (0, 100):
        tag = "all donors" if far == 0 else f"donors >= {far} km"
        for name, M in meas.items():
            rhos, top1, top3 = [], [], []
            for b in regs:
                donors = [a for a in regs if a != b and geo.loc[a, b] >= far]
                if len(donors) < 5:
                    continue
                m_b, e_b = M.loc[donors, b], mae.loc[donors, b]
                rhos.append(spearmanr(m_b, e_b).correlation)
                order = m_b.sample(frac=1, random_state=1).sort_values(kind="stable").index
                top1.append(e_b[order[0]])
                pool = pd.concat([tr[a] for a in order[:3]])
                top3.append(np.mean(np.abs(lgb.LGBMRegressor(**P).fit(pool[X], pool.y).predict(ev[b][X]) - ev[b].y)))
            out[(tag, name)] = dict(spearman_with_error=np.nanmean(rhos), top1_donor_MAE=np.mean(top1), top3_pooled_MAE=np.mean(top3))
    print("## Donor choice by each measure (MAE ft; earlier run: best possible donor 1.51 / 1.56 far, random 3.23 / 3.32,\n"
          "## 30 measured houses 1.58 / 1.63)\n")
    print(pd.DataFrame(out).T.round(3).to_markdown())
    # pooled fallback with context as features
    hf = t[["region"]].join(ctx, on="region").join(desc[dcols], on="region")
    t2 = pd.concat([t, hf.drop(columns="region")], axis=1)
    feats = {"house inputs only": X, "+ region context": X + groups["ctx_all"], "+ context + descriptors": X + groups["ctx_all"] + dcols}
    res = {k: [] for k in feats}
    for b in regs:
        donors = [a for a in regs if a != b and geo.loc[a, b] >= 100]
        if len(donors) < 5:
            continue
        idx = pd.concat([tr[a].sample(min(len(tr[a]), 600), random_state=0) for a in donors]).index
        pool, test = t2.loc[idx], t2.loc[ev[b].index]
        for k, cols in feats.items():
            res[k].append(np.mean(np.abs(lgb.LGBMRegressor(**P).fit(pool[cols], pool.y).predict(test[cols]) - test.y)))
    print("\n## Pooled model for a new area (donors >= 100 km), mean MAE over target regions (ft)\n")
    print(pd.Series({k: np.mean(v) for k, v in res.items()}, name="MAE").round(3).to_markdown())
    imp = lgb.LGBMRegressor(objective="l2", n_estimators=300, learning_rate=0.05, num_leaves=15, verbose=-1).fit(F, yv)
    names = [f"|d {c}|" for c in full.columns] + ["distance km", "same state"]
    print("\nlearned-similarity importance (gain, top 10):")
    print(pd.Series(imp.booster_.feature_importance("gain"), index=names).sort_values(ascending=False).head(10).round(0).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
