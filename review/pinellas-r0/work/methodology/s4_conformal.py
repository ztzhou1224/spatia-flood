"""Retrain train.py's split in the work dir to check q, the FIT/CAL/TEST handling, block adjacency, label density."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.model_selection import GroupKFold
ROOT = Path("/home/user/spatia-flood"); W = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "pipeline" / "train"))
from train import DATA, FEATS, P, features, score, abs_q, C, fit  # noqa
fips, run = "12103", "pinellas_2018"
f = features(fips, run)
lab = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
d = lab.merge(f, on="building_id", how="inner")
d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy(); d["dh"] = d.ffe_ft - d.g_lag
d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))].reset_index(drop=True)
blocks = np.array(sorted(d.block.unique())); rng = np.random.default_rng(0); rng.shuffle(blocks); k = len(blocks)
test_b, cal_b = set(blocks[: round(0.2 * k)]), set(blocks[round(0.2 * k): round(0.4 * k)])
bands = json.loads((DATA / "train" / f"bands_{fips}.json").read_text())
print("test blocks match saved:", test_b == set(bands["test_blocks"]), "| fit/cal/test disjoint:", not (test_b & cal_b))
part = np.where(d.block.isin(test_b), "test", np.where(d.block.isin(cal_b), "cal", "fit"))
fit_d, cal_d, test_d = (d[part == x].reset_index(drop=True) for x in ("fit", "cal", "test"))
print("sizes", len(fit_d), len(cal_d), len(test_d))
oof = np.full(len(fit_d), np.nan)
for a, b_ in GroupKFold(5).split(fit_d, groups=fit_d.block):
    oof[b_] = fit(fit_d.loc[a, FEATS], fit_d.dh.iloc[a]).predict(fit_d.loc[b_, FEATS])
diff = lgb.LGBMRegressor(**{**P, "objective": "l2"}).fit(fit_d[FEATS].assign(p=oof), np.abs(fit_d.dh.values - oof))
def s_of(x, p): return np.maximum(diff.predict(x[FEATS].assign(p=p)), 0.05)
m_fit = fit(fit_d[FEATS], fit_d.dh)
pc = m_fit.predict(cal_d[FEATS])
q = abs_q(np.abs(cal_d.dh.values - pc) / s_of(cal_d, pc), C)
n = len(cal_d); kq = int(np.ceil((n + 1) * C))
print(f"q reproduced {q:.4f} (saved {bands['q']:.4f}); finite-sample k = ceil((n+1)*0.9) = {kq} of n = {n}; np.quantile would give {np.quantile(np.abs(cal_d.dh.values - pc) / s_of(cal_d, pc), C):.4f}")
model = fit(pd.concat([fit_d, cal_d])[FEATS], pd.concat([fit_d, cal_d]).dh)
# the saved final model: compare predictions on test
saved = lgb.Booster(model_file=str(DATA / "train" / f"model_{fips}.txt"))
pt_saved = saved.predict(test_d[FEATS]); pt = model.predict(test_d[FEATS])
print("retrained final model vs saved: max |diff| on test", np.abs(pt - pt_saved).max().round(4))
# CAL coverage of the FINAL model with q (in-sample for the final model) vs m_fit on CAL
for name, m in (("m_fit (what q was calibrated on)", m_fit), ("final FIT+CAL model (what ships)", model)):
    p = m.predict(cal_d[FEATS]); s = s_of(cal_d, p)
    print(f"CAL coverage, {name}: {((cal_d.dh >= p - q * s) & (cal_d.dh <= p + q * s)).mean():.3f}, CAL MAE {np.abs(p - cal_d.dh).mean():.3f}")
    p = m.predict(test_d[FEATS]); s = s_of(test_d, p)
    print(f"TEST coverage, {name}: {((test_d.dh >= p - q * s) & (test_d.dh <= p + q * s)).mean():.3f}, TEST MAE {np.abs(p - test_d.dh).mean():.3f}, median width {np.median(2*q*s):.3f}")
# How would a proper split calibration for the final model look? Swap roles: calibrate on FIT OOF? Not possible; instead check q sensitivity to the CAL draw: other 20% block subsets
qs = []
rng2 = np.random.default_rng(5)
nontest = np.array(sorted(set(blocks) - test_b))
for _ in range(20):
    rng2.shuffle(nontest); cb = set(nontest[: round(0.2 * k)])
    cd, fd = d[d.block.isin(cb)].reset_index(drop=True), d[~d.block.isin(cb | test_b)].reset_index(drop=True)
    mf = fit(fd[FEATS], fd.dh); pcc = mf.predict(cd[FEATS])
    qs.append(abs_q(np.abs(cd.dh.values - pcc) / s_of(cd, pcc), C))
print("q over 20 alternative CAL draws (same difficulty model): mean %.3f sd %.3f min %.3f max %.3f" % (np.mean(qs), np.std(qs), np.min(qs), np.max(qs)))
# block adjacency: test blocks with a fit or cal neighbour (8-neighbourhood, 1 km grid)
def xy(bk): x, y = bk.split("_"); return int(x), int(y)
fitcal = {xy(b_) for b_ in blocks if b_ not in test_b}
adj = [any((x + dx, y + dy) in fitcal for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)) for x, y in map(xy, test_b)]
print(f"test blocks {len(test_b)}: {np.mean(adj):.2f} share with a FIT/CAL block among the 8 neighbours")
# label density for the modeled population: modeled rows in blocks with 0 labels; distance to nearest label block
import pyarrow.parquet as pq
bb = pq.read_table(ROOT / "data/flood_v1/assemble/buildings_12103.parquet", columns=["building_id", "ffh_class", "zone_main", "touches_sfha"]).to_pandas()
mm = bb[bb.ffh_class == "modeled"].merge(f[["building_id", "block"]], on="building_id", how="left")
lab_blocks = set(d.block)
lab_xy = np.array([xy(b_) for b_ in lab_blocks])
mxy = np.array([xy(b_) for b_ in mm.block])
from scipy.spatial import cKDTree
dist = cKDTree(lab_xy).query(mxy)[0]
print(f"modeled rows {len(mm)}: in a block with >=1 screened label {np.isin(mm.block, list(lab_blocks)).mean():.3f}; nearest labelled block >= 2 km away {(dist >= 2).mean():.3f}, >= 5 km {(dist >= 5).mean():.3f}")
print("by touches_sfha: share in a labelled block", mm.groupby(mm.touches_sfha.fillna(False)).block.apply(lambda s: np.isin(s, list(lab_blocks)).mean()).round(3).to_dict())
print("labelled blocks", len(lab_blocks), "modeled rows' blocks", mm.block.nunique())
