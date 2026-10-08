"""Paired bootstrap of the gate metrics between two models on the same test houses (FIT-only vs shipped);
Clopper-Pearson for above/below precision; covariate shift restricted to modeled rows with a call; record ffh distribution."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb, pyarrow.parquet as pq
from scipy.stats import beta
ROOT = Path("/home/user/spatia-flood"); W = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "pipeline" / "train"))
from train import DATA, FEATS, P, features, score, fit  # noqa
fips, run = "12103", "pinellas_2018"
t = pd.read_parquet(W / "test_scored.parquet")
# FIT-only model as the "other model" (same houses) -> paired difference noise
f = features(fips, run); lab = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
d = lab.merge(f, on="building_id"); d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy(); d["dh"] = d.ffe_ft - d.g_lag
d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))].reset_index(drop=True)
bands = json.loads((DATA / "train" / f"bands_{fips}.json").read_text())
blocks = np.array(sorted(d.block.unique())); rng = np.random.default_rng(0); rng.shuffle(blocks); k = len(blocks)
test_b, cal_b = set(blocks[: round(0.2 * k)]), set(blocks[round(0.2 * k): round(0.4 * k)])
fit_d = d[~d.block.isin(test_b | cal_b)]
m_fit = fit(fit_d[FEATS], fit_d.dh)
diff = lgb.Booster(model_file=str(DATA / "train" / f"difficulty_{fips}.txt")); q = bands["q"]
assert (t.building_id.values == d[d.block.isin(test_b)].building_id.values).all()
p2 = m_fit.predict(t[FEATS]); s2 = np.maximum(diff.predict(t[FEATS].assign(p=p2)), 0.05); lo2, hi2 = p2 - q * s2, p2 + q * s2
p1, lo1, hi1 = t.p.values, t.lo.values, t.hi.values
sc1, sc2 = score(t, p1, lo1, hi1), score(t, p2, lo2, hi2)
print("shipped:", {k_: round(float(sc1[k_]), 4) for k_ in ("MAE", "coverage", "BFE side", "decided correct")})
print("FIT-only:", {k_: round(float(sc2[k_]), 4) for k_ in ("MAE", "coverage", "BFE side", "decided correct")})
rng = np.random.default_rng(2); N = len(t); D = {k_: [] for k_ in ("MAE", "coverage", "BFE side", "decided correct")}
for _ in range(1000):
    i = rng.integers(0, N, N); tb = t.iloc[i].reset_index(drop=True)
    a, b_ = score(tb, p1[i], lo1[i], hi1[i]), score(tb, p2[i], lo2[i], hi2[i])
    for k_ in D: D[k_].append(a[k_] - b_[k_])
for k_, v in D.items():
    v = np.array(v); print(f"paired bootstrap, shipped minus FIT-only, {k_}: mean {v.mean():+.4f}, sd {v.std():.4f}, 95% CI [{np.quantile(v, .025):+.4f}, {np.quantile(v, .975):+.4f}]")
# Clopper-Pearson for above precision on test
def cp(kk, n): return beta.ppf(.025, kk, n - kk + 1) if kk else 0, beta.ppf(.975, kk + 1, n - kk) if kk < n else 1
sfha = t.cert_zone.astype(str).str.upper().str[:1].isin(["A", "V"]).values & t.cert_bfe_ft.notna().values
lag, bfe, ffe = t.g_lag.values, t.cert_bfe_ft.values, t.ffe_ft.values
above = (lag + lo1 >= bfe) & sfha; below = (lag + hi1 < bfe) & sfha; ta = ffe >= bfe
for nm, m, ok in (("above", above, ta), ("below", below, ~ta)):
    kk, n = int(ok[m].sum()), int(m.sum()); print(f"{nm}: {kk}/{n} right, wrong rate {(n-kk)/n:.3f}, 95% CI of wrong rate [{1-cp(kk,n)[1]:.3f}, {1-cp(kk,n)[0]:.3f}]")
# what if record-style 'at BFE counts as above' with 0.5 ft tolerance was applied to truths: share of SFHA test truths within 0.5 ft
print("SFHA test truths |ffe-bfe|<=0.5:", int((sfha & (np.abs(ffe - bfe) <= 0.5)).sum()), "of", int(sfha.sum()))
# covariate shift restricted to modeled rows that received a call (SFHA with BFE)
b = pq.read_table(ROOT / "data/flood_v1/assemble/buildings_12103.parquet", columns=["ffe_class", "ground_ft", "year_built", "living_area_sqft", "footprint_area_m2", "roof_ft", "eave_ft", "bfe_call", "touches_sfha", "ffh_ft", "raised_flag", "ffh_class"]).to_pandas()
rec = b.ffe_class == "record"; mc = (b.ffe_class == "modeled") & b.bfe_call.isin(["above", "below", "too_close"])
print("modeled rows with a call:", mc.sum())
num = ["year_built", "living_area_sqft", "footprint_area_m2", "ground_ft", "roof_ft", "eave_ft"]
any_out = np.zeros(mc.sum(), bool)
for c in num:
    r, m = b.loc[rec, c].astype(float), b.loc[mc, c].astype(float)
    out = (m < r.quantile(.01)) | (m > r.quantile(.99)); any_out |= out.values
    print(f"  {c}: modeled-with-call median {m.median():.1f} vs record median {r.median():.1f}; outside record 1-99 pct: {out.mean():.3f}")
print("modeled-with-call rows with ANY feature outside record 1-99 pct:", any_out.mean().round(3))
mca = (b.ffe_class == "modeled") & (b.bfe_call == "above")
print("modeled ABOVE rows: ground_ft median", b.loc[mca, "ground_ft"].median().round(2), "| outside record ground 1-99:", ((b.loc[mca, "ground_ft"] < b.loc[rec, "ground_ft"].quantile(.01)) | (b.loc[mca, "ground_ft"] > b.loc[rec, "ground_ft"].quantile(.99))).mean().round(3))
# record ffh distribution vs 3 ft threshold
rf = b.loc[b.ffh_class == "record", "ffh_ft"].astype(float)
print("record ffh_ft (cert FFE - cert LAG) quantiles", rf.quantile([.05, .25, .5, .75, .9, .95]).round(2).to_dict(), "| share > 3 ft", (rf > 3).mean().round(3), "| share within 2..4 ft", rf.between(2, 4).mean().round(3), "| share within 2.5..3.5", rf.between(2.5, 3.5).mean().round(3))
