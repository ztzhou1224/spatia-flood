import sys, json, numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, "/home/user/spatia-flood/pipeline/train")
import train as T
D = "/home/user/spatia-flood/data/flood_v1"
f = T.features("12103", "pinellas_2018")
model = lgb.Booster(model_file=f"{D}/train/model_12103.txt"); diff = lgb.Booster(model_file=f"{D}/train/difficulty_12103.txt")
bands = json.load(open(f"{D}/train/bands_12103.json")); q = bands["q"]
def predict(x):
    p = model.predict(x[T.FEATS]); s = np.maximum(diff.predict(x[T.FEATS].assign(p=p)), 0.05); return p, p-q*s, p+q*s
lab = pd.read_parquet(f"{D}/train/labels_12103.parquet")
d = lab.merge(f, on="building_id"); d = d[d.g_lag.notna() & (d.lpc_status=="ok")].copy(); d["dh"] = d.ffe_ft - d.g_lag
n0=len(d); d = d[~((d.roof_p95-d.dh<6)|(d.dh<-1))]
t = d[d.block.isin(set(bands["test_blocks"]))].reset_index(drop=True)
p, lo, hi = predict(t)
sc = T.score(t, p, lo, hi); print("GATE reproduction n/MAE/cov/BFE side/decided correct:", sc["n"], round(sc["MAE"],3), round(sc["coverage"],3), round(sc["BFE side"],3), round(sc["decided correct"],3), "q", round(q,4), "screened-out", n0-len(d))
# finite-sample quantile check on CAL
cov = (t.dh>=lo)&(t.dh<=hi); flag = p>3; raised = t.dh>3; dg = t.diagram.astype(str)
def cv(m, name): print(f"  coverage {name}: n {int(m.sum())} cov {cov[m].mean():.3f} MAE {np.abs(p[m]-t.dh[m]).mean():.2f}")
cv(raised & ~flag, "truly raised & unflagged"); cv(dg.str[0].isin(list("56789")) & ~flag, "diagram 5-9 & unflagged"); cv(dg.isin(["1A","1B"]) & raised, "slab 1A/1B truly raised"); cv(dg.str[0].isin(list("56789")) & raised, "diag 5-9 truly raised")
cv(flag, "flagged"); cv(~flag, "unflagged"); cv(t.cert_zone.astype(str).str.upper().str[:1].isin(["A","V"]), "zone A/V"); cv(~t.cert_zone.astype(str).str.upper().str[:1].isin(["A","V"]), "zone X/other")
print("  misses above band / below band:", int((t.dh>hi).sum()), int((t.dh<lo).sum()))
print("  raised flag: truly raised", int(raised.sum()), "flagged", int(flag.sum()), "precision", round(float(raised[flag].mean()),3), "recall", round(float(flag[raised].mean()),3), "slab precision", round(float(raised[flag & dg.isin(["1A","1B"])].mean()),3))
# ---------------- county certificates vs modeled rows
tb = pd.read_parquet(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","ffe_ft","ffe_class","ffh_class","ffe_band_lo","ffe_band_hi","bfe_ft","bfe_call","touches_sfha","raised_flag","ground_ft","year_built","zone_main"])
co = pd.read_parquet(f"{D}/labels_pinellas/labels_pinellas_12103.parquet")
print("county labels", len(co), co.vertical_datum_route.value_counts().to_dict(), co.ffe_field.value_counts().to_dict(), co.label_source.value_counts().to_dict())
co = co[co.vertical_datum_route=="navd88_native"]
fd = set(lab.building_id)
x = co.merge(tb, on="building_id", suffixes=("_c",""))
print("native matched to table:", len(x), "| on FDEM-labelled buildings:", int(x.building_id.isin(fd).sum()), "| ffe_class:", x.ffe_class.value_counts(dropna=False).to_dict())
m = x[~x.building_id.isin(fd)]
print("county-only (no FDEM label):", len(m), "modeled:", int((m.ffe_class=="modeled").sum()), "record(!):", int((m.ffe_class=="record").sum()))
m = m[m.ffe_class=="modeled"].merge(f[["building_id","g_lag","roof_p95","block"]], on="building_id")
m["dh"] = m.ffe_ft_c - m.g_lag
scr = (m.roof_p95 - m.dh < 6) | (m.dh < -1); print("train.py screen removes", int(scr.sum()), "->", int((~scr).sum()))
m = m[~scr].copy()
m["err"] = m.ffe_ft - m.ffe_ft_c; m["cov"] = (m.ffe_ft_c>=m.ffe_band_lo)&(m.ffe_ft_c<=m.ffe_band_hi)
m["dgrp"] = np.where(m.diagram.isin(["1A","1B"]), "slab 1A/1B", np.where(m.diagram.astype(str).str[0].isin(list("56789")), "elevated 5-9", "other"))
def rep(s, name):
    sf = s[s.touches_sfha & s.bfe_ft.notna()]
    side = ((sf.ffe_ft>=sf.bfe_ft)==(sf.ffe_ft_c>=sf.bfe_ft)).mean() if len(sf) else np.nan
    dec = sf[sf.bfe_call.isin(["above","below"])]
    ok = ((dec.bfe_call=="above")&(dec.ffe_ft_c>=dec.bfe_ft))|((dec.bfe_call=="below")&(dec.ffe_ft_c<dec.bfe_ft))
    print(f"  {name:28s} n {len(s):5d} MAE {s.err.abs().mean():.3f} med {s.err.median():+.2f} within1 {(s.err.abs()<=1).mean():.3f} cov {s['cov'].mean():.3f} cov_flag {s['cov'][s.raised_flag==True].mean():.3f} cov_unfl {s['cov'][s.raised_flag==False].mean():.3f} BFEside {side:.3f} decided {len(dec)/max(len(sf),1):.3f} correct {ok.mean() if len(dec) else float('nan'):.3f} ({int(ok.sum())}/{len(dec)})")
rep(m, "county-only modeled screened")
rep(m[m.block.isin(set(bands["test_blocks"]))], "  of which r0 TEST blocks")
for g in ["slab 1A/1B","elevated 5-9","other"]: rep(m[m.dgrp==g], g)
for dgm in ["5","6","7","8","9"]: s=m[m.diagram==dgm]; print(f"   diagram {dgm}: n {len(s)} median err {s.err.median():+.2f} cov {s['cov'].mean():.3f}")
dec = m[m.touches_sfha & m.bfe_call.isin(["above","below"])]
print("  confusion: above right/wrong", int(((dec.bfe_call=="above")&(dec.ffe_ft_c>=dec.bfe_ft)).sum()), int(((dec.bfe_call=="above")&(dec.ffe_ft_c<dec.bfe_ft)).sum()), "| below right/wrong", int(((dec.bfe_call=="below")&(dec.ffe_ft_c<dec.bfe_ft)).sum()), int(((dec.bfe_call=="below")&(dec.ffe_ft_c>=dec.bfe_ft)).sum()))
print("  ground_ft<0 rows: n", int((m.ground_ft<0).sum()), "MAE", round(m.err[m.ground_ft<0].abs().mean(),2), "median", round(m.err[m.ground_ft<0].median(),2))
# same-day pair noise FDEM vs county
both = co.merge(lab, on="building_id", suffixes=("_c","_f"))
same = both[(both.issued_at_c==both.issued_at_f)]; dif = both[(both.issued_at_c!=both.issued_at_f)&both.issued_at_c.notna()&both.issued_at_f.notna()]
print("both-cert buildings", len(both), "same-day", len(same), "MAE", round((same.ffe_ft_c-same.ffe_ft_f).abs().mean(),3), "| different dates", len(dif), "MAE", round((dif.ffe_ft_c-dif.ffe_ft_f).abs().mean(),2))
m.to_parquet("county_scored.parquet", index=False)
