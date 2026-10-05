"""Which measure of 'housing similarity' predicts whether a floor-height model from region A works in region B?

Data: research/states houses_all.parquet (261,783 single-family houses with a measured living floor; FL, NC, VA,
NYC = Staten Island, HAR = Harris County). Regions: 0.25 deg grid cells with >= MIN_N houses.
Transfer matrix: one GBM per region (inputs as cross_state.py; <= 3,000 training houses), applied to an
evaluation sample (<= 1,000 houses) of every other region -> MAE[A, B] (ft).

Candidate similarity measures (all label-free except 'probe'):
  geo_km        distance between region centroids
  same_state    1 if same state
  desc_*        standardized Euclidean distance between region descriptors computed from the inputs only:
                foundation (NSI type shares, median NSI height), age (median year, share built 1990+), flood
                (SFHA share, V share, median BFE - ground), all (every descriptor)
  mmd           energy distance between the two regions' input distributions (standardized, 300 houses each)
  di            area-of-applicability dissimilarity (Meyer & Pebesma 2021): mean over B's houses of the
                importance-weighted distance to the nearest A training house / mean nearest-neighbour distance
                within A's training set
  probe30       MAE of A's model on 30 measured houses of B (needs a small survey in B; the rest of B is scored)
Tests: (1) Spearman correlation, within each target B, between each measure and MAE[A, B] over donors A,
averaged over targets; (2) donor choice: for each B, the most similar donor (top-1) and the 3 most similar
pooled into one model; mean MAE vs the best possible donor (oracle), a random donor, and all donors pooled.
Run for all donors and for donors >= 100 km away (a new area with no nearby measured data).
Usage: python similarity_test.py
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

S = Path(__file__).resolve().parents[2] / "data" / "states"
OUT = Path(__file__).resolve().parents[2] / "data" / "similarity"
X = ["nsi_ft", "nsi_fh", "nsi_story", "nsi_year", "year", "sfha", "ve", "bfe_minus_ground"]
P = dict(objective="l1", n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=30, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.8, verbose=-1)
MIN_N, NTR, NEV, CELL = 300, 3000, 1000, 0.25
rng = np.random.default_rng(0)


def descriptors(g):
    ft = g.nsi_ft
    return pd.Series({
        "f_slab": (ft == 0).mean(), "f_crawl": (ft == 1).mean(), "f_bsmt": (ft == 2).mean(), "f_pier": ft.isin([3, 4, 5]).mean(),
        "f_fh": g.nsi_fh.median(), "a_year": g.year.median(), "a_new": (g.year >= 1990).mean(),
        "x_sfha": g.sfha.mean(), "x_ve": g.ve.mean(), "x_bfe_g": g.bfe_minus_ground.median(),
        "lat": g.lat.mean(), "lon": g.lon.mean()})


def energy(a, b):
    def md(u, v):
        return np.mean(np.sqrt(((u[:, None, :] - v[None, :, :]) ** 2).sum(-1)))
    return 2 * md(a, b) - md(a, a) - md(b, b)


def main():
    OUT.mkdir(exist_ok=True)
    t = pd.read_parquet(S / "houses_all.parquet")
    t["region"] = t.state + "_" + (t.lon // CELL).astype(int).astype(str) + "_" + (t.lat // CELL).astype(int).astype(str)
    cnt = t.region.value_counts()
    t = t[t.region.isin(cnt[cnt >= MIN_N].index)].copy()
    regs = sorted(t.region.unique())
    print(f"regions with >= {MIN_N} houses: {len(regs)} ({t.groupby('region').state.first().value_counts().to_dict()}); houses {len(t)}")
    tr, ev, models = {}, {}, {}
    for r in regs:
        g = t[t.region == r].sample(frac=1, random_state=0)
        ev[r] = g.iloc[:min(NEV, len(g) // 3)]
        tr[r] = g.iloc[len(ev[r]):][:NTR]
        models[r] = lgb.LGBMRegressor(**P).fit(tr[r][X], tr[r].y)
    mae = pd.DataFrame(np.nan, index=regs, columns=regs)
    for a in regs:
        for b in regs:
            mae.loc[a, b] = np.mean(np.abs(models[a].predict(ev[b][X]) - ev[b].y))
    mae.to_parquet(OUT / "mae_matrix.parquet")
    local = pd.Series(np.diag(mae.values), index=regs)
    print(f"local MAE (model of the same region, held-out houses): median {local.median():.2f} ft; "
          f"cross-region MAE median {np.nanmedian(mae.values[~np.eye(len(regs), dtype=bool)]):.2f} ft")

    # ----- similarity measures -----
    desc = t.groupby("region").apply(descriptors).loc[regs]
    groups = {"desc_foundation": ["f_slab", "f_crawl", "f_bsmt", "f_pier", "f_fh"], "desc_age": ["a_year", "a_new"],
              "desc_flood": ["x_sfha", "x_ve", "x_bfe_g"], "desc_all": ["f_slab", "f_crawl", "f_bsmt", "f_pier", "f_fh", "a_year",
                                                                           "a_new", "x_sfha", "x_ve", "x_bfe_g"]}
    z = (desc - desc.mean()) / desc.std()
    z = z.fillna(0)
    meas = {}
    lat, lon = desc.lat.values, desc.lon.values
    meas["geo_km"] = pd.DataFrame(np.hypot((lat[:, None] - lat[None]) * 111, (lon[:, None] - lon[None]) * 111 * np.cos(np.radians(lat.mean()))),
                                  index=regs, columns=regs)
    st = np.array([r.split("_")[0] for r in regs])
    meas["same_state"] = pd.DataFrame(-(st[:, None] == st[None]).astype(float), index=regs, columns=regs)  # lower = more similar
    for k, cols in groups.items():
        v = z[cols].values
        meas[k] = pd.DataFrame(np.sqrt(((v[:, None] - v[None]) ** 2).sum(-1)), index=regs, columns=regs)
    allx = t[X].astype(float)
    mu, sd = allx.mean(), allx.std()
    std = {r: ((g[X].astype(float) - mu) / sd).fillna(0).values for r, g in ev.items()}
    stdtr = {r: ((g[X].astype(float) - mu) / sd).fillna(0).values for r, g in tr.items()}
    samp = {r: v[rng.choice(len(v), min(300, len(v)), replace=False)] for r, v in std.items()}
    meas["mmd"] = pd.DataFrame([[energy(samp[a], samp[b]) for b in regs] for a in regs], index=regs, columns=regs)
    imp = lgb.LGBMRegressor(**P).fit(t[X], t.y).booster_.feature_importance("gain")
    w = imp / imp.sum()
    from sklearn.neighbors import NearestNeighbors
    di = pd.DataFrame(np.nan, index=regs, columns=regs)
    for a in regs:
        A = stdtr[a] * w
        nn = NearestNeighbors(n_neighbors=2).fit(A)
        dbar = nn.kneighbors(A)[0][:, 1].mean() + 1e-9
        for b in regs:
            di.loc[a, b] = nn.kneighbors(std[b] * w, n_neighbors=1)[0][:, 0].mean() / dbar
    meas["di"] = di
    probe = pd.DataFrame(np.nan, index=regs, columns=regs)
    for b in regs:
        pb = ev[b].iloc[:30]
        for a in regs:
            probe.loc[a, b] = np.mean(np.abs(models[a].predict(pb[X]) - pb.y))
    meas["probe30"] = probe

    # ----- tests -----
    rows, choice = {}, {}
    for far in (0, 100):
        tag = "all donors" if far == 0 else f"donors >= {far} km away"
        for name, M in meas.items():
            rhos, top1, top3 = [], [], []
            for b in regs:
                donors = [a for a in regs if a != b and meas["geo_km"].loc[a, b] >= far]
                if len(donors) < 5:
                    continue
                m_b, e_b = M.loc[donors, b], mae.loc[donors, b]
                if m_b.nunique() > 1:
                    rhos.append(spearmanr(m_b, e_b).correlation)
                order = m_b.sample(frac=1, random_state=1).sort_values(kind="stable").index  # ties broken at random
                top1.append(e_b[order[0]])
                pool = pd.concat([tr[a] for a in order[:3]])
                top3.append(np.mean(np.abs(lgb.LGBMRegressor(**P).fit(pool[X], pool.y).predict(ev[b][X]) - ev[b].y)))
            rows[(tag, name)] = dict(spearman_with_error=np.nanmean(rhos), top1_donor_MAE=np.mean(top1), top3_pooled_MAE=np.mean(top3))
        orc, rnd, poolall, loc = [], [], [], []
        for b in regs:
            donors = [a for a in regs if a != b and meas["geo_km"].loc[a, b] >= far]
            if len(donors) < 5:
                continue
            orc.append(mae.loc[donors, b].min()); rnd.append(mae.loc[donors, b].mean()); loc.append(mae.loc[b, b])
            pool = pd.concat([tr[a].sample(min(len(tr[a]), 600), random_state=0) for a in donors])
            poolall.append(np.mean(np.abs(lgb.LGBMRegressor(**P).fit(pool[X], pool.y).predict(ev[b][X]) - ev[b].y)))
        choice[tag] = dict(local_model=np.mean(loc), oracle_best_donor=np.mean(orc), random_donor=np.mean(rnd), all_donors_pooled=np.mean(poolall),
                           targets=len(orc))
    res = pd.DataFrame(rows).T
    res.index.names = ["donors", "measure"]
    print("\n## How well each similarity measure picks a donor region (MAE in ft; lower is better)\n")
    print(res.round(3).to_markdown())
    print("\n## Reference points\n")
    print(pd.DataFrame(choice).T.round(3).to_markdown())
    desc.to_csv(OUT / "region_descriptors.csv")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
