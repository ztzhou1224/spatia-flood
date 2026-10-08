"""Re-score held-out test blocks from saved artefacts; subgroup coverage; bootstrap; raised flag. Read-only on repo."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, lightgbm as lgb
ROOT = Path("/home/user/spatia-flood")
sys.path.insert(0, str(ROOT / "pipeline" / "train"))
from train import DATA, FEATS, features, score, abs_q  # noqa
W = Path(sys.argv[1])
fips, run = "12103", "pinellas_2018"
f = features(fips, run)
lab = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
d_all = lab.merge(f, on="building_id")
d_all = d_all[d_all.g_lag.notna() & (d_all.lpc_status == "ok")].copy()
d_all["dh"] = d_all.ffe_ft - d_all.g_lag
scr = (d_all.roof_p95 - d_all.dh < 6) | (d_all.dh < -1)
d = d_all[~scr].copy()
bands = json.loads((DATA / "train" / f"bands_{fips}.json").read_text())
test = set(bands["test_blocks"])
t = d[d.block.isin(test)].reset_index(drop=True)
t_scr = d_all[scr & d_all.block.isin(test)].reset_index(drop=True)
model = lgb.Booster(model_file=str(DATA / "train" / f"model_{fips}.txt"))
diff = lgb.Booster(model_file=str(DATA / "train" / f"difficulty_{fips}.txt"))
q = bands["q"]
def predict(x):
    p = model.predict(x[FEATS]); s = np.maximum(diff.predict(x[FEATS].assign(p=p)), 0.05)
    return p, s, p - q * s, p + q * s
p, s, lo, hi = predict(t)
print("n test", len(t), "test blocks", len(test), "screened-out labels in test blocks", len(t_scr), "of", len(t) + len(t_scr))
sc = score(t, p, lo, hi)
print("GATE REPRO:", {k: round(float(v), 4) for k, v in sc.items()})
# screened-out test labels: how would they be covered?
ps, ss, los, his = predict(t_scr)
print("screened-out test labels: MAE", np.abs(ps - t_scr.dh).mean().round(3), "coverage", ((t_scr.dh >= los) & (t_scr.dh <= his)).mean().round(3),
      "dh quantiles", np.quantile(t_scr.dh, [0, .1, .5, .9, 1]).round(2))
cov_all = ((d_all.dh.values >= 0) & True)
# precision of above / below separately on the test set
sfha = t.cert_zone.astype(str).str.upper().str[:1].isin(["A", "V"]).values & t.cert_bfe_ft.notna().values
lag, bfe, ffe = t.g_lag.values, t.cert_bfe_ft.values, t.ffe_ft.values
above = (lag + lo >= bfe) & sfha; below = (lag + hi < bfe) & sfha
truth_above = ffe >= bfe
print("TEST calls: above n", above.sum(), "precision", (truth_above[above]).mean().round(4), "| below n", below.sum(), "precision", (~truth_above[below]).mean().round(4),
      "| too_close n", (sfha & ~above & ~below).sum(), "| base rate truly above among SFHA", truth_above[sfha].mean().round(3))
# wrong above calls: how far
wa = above & ~truth_above
print("wrong above calls: ffe-bfe", np.round((ffe - bfe)[wa], 2), "band lo - bfe", np.round((lag + lo - bfe)[wa], 2))
wb = below & truth_above
print("wrong below calls: ffe-bfe", np.round((ffe - bfe)[wb], 2))
# also with 0.5 ft tolerance on record exact-at-BFE: how many test truths are exactly at BFE
print("test SFHA certs with ffe == bfe exactly", int(((ffe == bfe) & sfha).sum()), "within 0.5", int(((np.abs(ffe - bfe) <= 0.5) & sfha).sum()))

# ---------------- subgroups
t["p"], t["lo"], t["hi"], t["s"] = p, lo, hi, s
t["cov"] = (t.dh >= t.lo) & (t.dh <= t.hi)
t["ae"] = np.abs(t.p - t.dh)
t["flag"] = t.p > 3
t["truly_raised"] = t.dh > 3
dg = t.diagram.astype(str)
t["dgroup"] = np.where(dg.isin(["1A", "1B"]), "slab 1A/1B", np.where(dg.str[0].isin(list("56789")), "elev 5-9", "other 2-4"))
z = t.cert_zone.astype(str).str.upper().str.strip()
t["zone"] = np.where(z.str.startswith("V"), "V", np.where(z.str.startswith("A"), "A", np.where(z.str.startswith("X"), "X/other", "other:" + z)))
t["decade"] = (t.year_built // 10 * 10).astype("Int64").astype(str)
for c in ("g_lag", "fp_area_m2", "living_area"):
    t[c + "_terc"] = pd.qcut(t[c], 3, labels=["low", "mid", "high"]).astype(str)
rows = []
def add(name, g):
    for k, gg in t.groupby(g, dropna=False):
        rows.append({"group": name, "level": str(k), "n": len(gg), "coverage": gg["cov"].mean(), "MAE": gg.ae.mean(),
                     "flagged_share": gg.flag.mean(), "median_width": (gg.hi - gg.lo).median(), "truly_raised_share": gg.truly_raised.mean()})
add("dgroup x flagged", ["dgroup", "flag"]); add("dgroup", "dgroup"); add("zone", "zone"); add("decade", "decade")
add("g_lag tercile", "g_lag_terc"); add("fp_area tercile", "fp_area_m2_terc"); add("living_area tercile", "living_area_terc")
add("raised_flag", "flag"); add("truly_raised x flagged", ["truly_raised", "flag"]); add("zone x flagged", ["zone", "flag"])
add("dgroup x truly_raised", ["dgroup", "truly_raised"])
R = pd.DataFrame(rows)
R.to_csv(W / "subgroups.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(R.round(3).to_string())
print("\nUNDER-COVERED (n>=50, coverage<0.85):")
print(R[(R.n >= 50) & (R.coverage < 0.85)].round(3).to_string())

# ---------------- bootstrap of test metrics
rng = np.random.default_rng(1)
N = len(t); B = 1000
m_mae, m_cov, m_side, m_dec = [], [], [], []
for _ in range(B):
    i = rng.integers(0, N, N)
    tb = t.iloc[i].reset_index(drop=True)
    scb = score(tb, p[i], lo[i], hi[i])
    m_mae.append(scb["MAE"]); m_cov.append(scb["coverage"]); m_side.append(scb["BFE side"]); m_dec.append(scb["decided correct"])
for nm, v in (("MAE", m_mae), ("coverage", m_cov), ("BFE side", m_side), ("decided correct", m_dec)):
    v = np.array(v); print(f"bootstrap {nm}: sd {v.std():.4f}, 95% CI [{np.quantile(v, .025):.4f}, {np.quantile(v, .975):.4f}]")
# also block bootstrap (resample test blocks)
blocks = t.block.values; ub = np.unique(blocks)
bm, bc, bs = [], [], []
for _ in range(B):
    chosen = rng.choice(ub, len(ub), replace=True)
    idx = np.concatenate([np.where(blocks == c)[0] for c in chosen])
    tb = t.iloc[idx].reset_index(drop=True)
    scb = score(tb, p[idx], lo[idx], hi[idx])
    bm.append(scb["MAE"]); bc.append(scb["coverage"]); bs.append(scb["BFE side"])
for nm, v in (("MAE", bm), ("coverage", bc), ("BFE side", bs)):
    v = np.array(v); print(f"BLOCK bootstrap {nm}: sd {v.std():.4f}, 95% CI [{np.quantile(v, .025):.4f}, {np.quantile(v, .975):.4f}]")

# ---------------- raised flag
for name, g in (("all", np.ones(len(t), bool)), ("slab", (t.dgroup == "slab 1A/1B").values), ("elev", (t.dgroup == "elev 5-9").values), ("other", (t.dgroup == "other 2-4").values)):
    tr, fl = t.truly_raised.values[g], t.flag.values[g]
    print(f"raised_flag {name}: n {g.sum()}, truly raised {tr.sum()}, flagged {fl.sum()}, precision {(tr[fl].mean() if fl.sum() else float('nan')):.3f}, recall {(fl[tr].mean() if tr.sum() else float('nan')):.3f}")
print("test dh quantiles", np.quantile(t.dh, [.05, .1, .25, .5, .75, .9, .95]).round(2))
print("all screened label dh quantiles", np.quantile(d.dh, [.05, .1, .25, .5, .75, .9, .95]).round(2), "share dh>3", (d.dh > 3).mean().round(3),
      "share 2<dh<=4", ((d.dh > 2) & (d.dh <= 4)).mean().round(3))
# missed raised: coverage of truly raised & unflagged
mr = t.truly_raised & ~t.flag
print("truly raised & unflagged: n", mr.sum(), "coverage", t["cov"][mr].mean().round(3), "MAE", t.ae[mr].mean().round(3), "median width", (t.hi - t.lo)[mr].median().round(2))
t.drop(columns=[c for c in t.columns if c.startswith("wkb")], errors="ignore").to_parquet(W / "test_scored.parquet", index=False)
