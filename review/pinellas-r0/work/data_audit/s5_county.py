"""Step 5: fresh held-out score of the table's modeled floor against the Pinellas COUNTY certificate layer."""
import sys, json, numpy as np, pandas as pd, shapely
from pyproj import Transformer
A, L, T, C = sys.argv[1:5]  # assemble, lidar run, train, labels_pinellas
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
b = pd.read_parquet(f"{A}/buildings_12103.parquet", columns=["building_id","ffh_class","ffe_class","ffe_ft","ffe_band_lo","ffe_band_hi","ffh_ft","ffh_band_lo","ffh_band_hi","ground_ft","bfe_ft","bfe_method","bfe_band_lo","bfe_band_hi","bfe_call","bfe_call_basis","touches_sfha","zone_main","raised_flag","lon","lat","record_note","ffe_record_lidar_conflict","sfha_share"])
cl = pd.read_parquet(f"{C}/labels_pinellas_12103.parquet")
fd = pd.read_parquet(f"{T}/labels_12103.parquet")
f = pd.read_parquet(f"{L}/features.parquet", columns=["building_id","g_lag","g_inside","g_med","lpc_status","roof_p95"])
bands = json.load(open(f"{T}/bands_12103.json")); test_blocks = set(bands["test_blocks"])
print("county labels", len(cl), "by route", cl.vertical_datum_route.value_counts().to_dict(), "match", cl.match.value_counts().to_dict())
print("FDEM labels", len(fd), "; county buildings also in FDEM labels:", cl.building_id.isin(fd.building_id).sum())
# --- A. both-source agreement (label noise)
both = fd.merge(cl, on="building_id", suffixes=("_f","_c"))
d = both.ffe_ft_c - both.ffe_ft_f
same_day = (both.issued_at_c - both.issued_at_f).abs() < 1.5*86400000
print(f"\n[A] buildings with both FDEM and county cert: {len(both)}; same issue date (±1.5 d): {int(same_day.sum())}; same diagram: {(both.diagram_f==both.diagram_c).mean():.3f}")
for name, m in (("all", np.ones(len(both),bool)), ("native route", (both.vertical_datum_route=='navd88_native').values), ("same day", same_day.values), ("different dates", (~same_day & both.issued_at_c.notna() & both.issued_at_f.notna()).values)):
    x = d[m]; print(f"  {name:16s} n={len(x):5d} MAE={x.abs().mean():.3f} median={x.median():+.3f} |d|<=0.5: {(x.abs()<=0.5).mean():.3f} |d|<=1: {(x.abs()<=1).mean():.3f} |d|>3: {(x.abs()>3).mean():.3f}")
print("  exact same value (|d|<0.01):", int((d.abs()<0.01).sum()), " of", len(both))
# --- B. county-only buildings scored against the table's modeled floor
cl = cl[cl.vertical_datum_route=="navd88_native"]
co = cl[~cl.building_id.isin(set(fd.building_id))].merge(b, on="building_id").merge(f, on="building_id", how="left")
print(f"\n[B] county-only (native NAVD88) certificates matched to table rows: {len(co)}; ffh_class: {co.ffh_class.value_counts(dropna=False).to_dict()}")
m = co[co.ffh_class=="modeled"].copy()
print(f"   modeled rows: {len(m)}")
m["dh"] = m.ffe_ft_x - m.g_lag   # county cert floor minus lidar ground (the training target definition)
screen = (m.roof_p95 - m.dh < 6) | (m.dh < -1) | m.roof_p95.isna()
print(f"   train.py label screen removes {int(screen.sum())} (roof_p95-dh<6: {int(((m.roof_p95-m.dh)<6).sum())}, dh<-1: {int((m.dh<-1).sum())}, no roof_p95: {int(m.roof_p95.isna().sum())}) -> {int((~screen).sum())} scored")
tr = Transformer.from_crs("EPSG:4326","EPSG:6442",always_xy=True)
x, y = tr.transform(m.lon.values, m.lat.values)
m["block"] = (np.floor(x/1000).astype(int)).astype(str) + "_" + (np.floor(y/1000).astype(int)).astype(str)
m["in_test_block"] = m.block.isin(test_blocks)
m["grp"] = np.where(m.diagram.isin(["1A","1B"]), "slab 1A/1B", np.where(m.diagram.str[0].isin(list("56789")), "elevated 5-9", "2-4 basement/split"))
def score(d, label):
    y = d.ffe_ft_x.values; p = d.ffe_ft_y.values; e = p - y
    cov = (y >= d.ffe_band_lo.values - 1e-9) & (y <= d.ffe_band_hi.values + 1e-9)
    s = d.touches_sfha.values & d.bfe_ft.notna().values
    bfe = d.bfe_ft.values
    side = ((y >= bfe) == (p >= bfe))[s]
    dec = d.bfe_call.isin(["above","below"]).values & s
    truth_above = (y >= bfe)
    dec_ok = ((d.bfe_call.values == "above") == truth_above)[dec]
    # with the county's own BFE
    sb = d.cert_bfe_ft.notna().values & d.touches_sfha.values
    side_c = ((y >= d.cert_bfe_ft.values) == (p >= d.cert_bfe_ft.values))[sb]
    w = (d.ffe_band_hi - d.ffe_band_lo).values
    fl = d.raised_flag.fillna(False).values.astype(bool)
    r = dict(n=len(d), MAE=np.abs(e).mean(), bias_median=np.median(e), bias_mean=e.mean(), within_1ft=(np.abs(e)<=1).mean(), within_2ft=(np.abs(e)<=2).mean(),
             coverage=cov.mean(), cov_flagged=cov[fl].mean() if fl.any() else np.nan, cov_unflagged=cov[~fl].mean() if (~fl).any() else np.nan,
             n_flagged=int(fl.sum()), width_med_unflagged=np.median(w[~fl]) if (~fl).any() else np.nan, width_med_flagged=np.median(w[fl]) if fl.any() else np.nan,
             n_sfha_bfe=int(s.sum()), bfe_side=side.mean() if s.any() else np.nan, decided_share=dec[s].mean() if s.any() else np.nan, n_decided=int(dec.sum()), decided_correct=dec_ok.mean() if dec.any() else np.nan,
             n_cert_bfe=int(sb.sum()), bfe_side_vs_cert_bfe=side_c.mean() if sb.any() else np.nan,
             table_bfe_vs_cert_bfe_MAE=np.abs(bfe[sb & s] - d.cert_bfe_ft.values[sb & s]).mean() if (sb&s).any() else np.nan,
             truth_above_share=truth_above[s].mean() if s.any() else np.nan, raised_truth_share=(d.dh.values>3).mean(), raised_recall=((d.dh.values>3)&fl).sum()/max(1,(d.dh.values>3).sum()))
    return pd.Series(r, name=label)
ms = m[~screen]
rows = [score(ms, "county-only, screened, all"), score(m, "county-only, UNSCREENED, all"), score(ms[ms.in_test_block], "screened, r0 TEST blocks only"), score(ms[~ms.in_test_block], "screened, FIT/CAL blocks")]
for g, d in ms.groupby("grp"): rows.append(score(d, f"screened, {g}"))
rows.append(score(ms[ms.raised_flag.fillna(False).astype(bool)], "screened, flagged")); rows.append(score(ms[~ms.raised_flag.fillna(False).astype(bool)], "screened, not flagged"))
rows.append(score(ms[ms.match=="within"], "screened, cert point within footprint")); rows.append(score(ms[ms.match=="nearest_10m"], "screened, nearest_10m match"))
rows.append(score(ms[(ms.g_inside - ms.g_lag) > 3], "screened, ring min >3 ft below inside ground")); rows.append(score(ms[ms.ground_ft < 0], "screened, ground_ft < 0"))
rows.append(score(ms[ms.sfha_share >= 0.5], "screened, sfha_share>=0.5"))
R = pd.DataFrame(rows).round(3)
print("\n[B] scores (error = table modeled ffe_ft - county certificate first living floor):"); print(R.T.to_string())
R.to_csv("s5_scores.csv")
print("\n   published gate (train.py, FDEM held-out, n=1315): MAE 1.039 / coverage 0.918 / BFE side 0.898 / decided 0.579, decided correct 0.983")
# decided-call confusion on screened SFHA rows
s = ms[ms.touches_sfha & ms.bfe_ft.notna()]
truth = np.where(s.ffe_ft_x >= s.bfe_ft, "above", "below")
print("\n   confusion (rows: table bfe_call; cols: county certificate side vs table bfe_ft):"); print(pd.crosstab(s.bfe_call, truth))
print("   by basis:"); print(pd.crosstab([s.bfe_call_basis, s.bfe_call], truth))
# error by diagram
print("\n   by diagram (screened):"); print(ms.assign(e=ms.ffe_ft_y-ms.ffe_ft_x).groupby("diagram").e.agg(n="size", MAE=lambda x: x.abs().mean(), median="median").round(2).to_string())
# worst errors
w = ms.assign(e=ms.ffe_ft_y-ms.ffe_ft_x).sort_values("e")
print("\n   10 largest under-estimates (model far below cert):"); print(w[["building_id","diagram","ffe_ft_x","ffe_ft_y","ground_ft","g_inside","ffh_ft","ffh_band_lo","ffh_band_hi","bfe_ft","bfe_call","raised_flag","match","e"]].head(10).round(2).to_string())
print("\n   10 largest over-estimates:"); print(w[["building_id","diagram","ffe_ft_x","ffe_ft_y","ground_ft","ffh_ft","ffh_band_lo","ffh_band_hi","bfe_ft","bfe_call","raised_flag","match","e"]].tail(10).round(2).to_string())
# unscreened: what did screen remove and how do those score
print("\n   rows removed by the screen (dh<-1 or roof-dh<6): error stats:", m[screen].assign(e=m.ffe_ft_y-m.ffe_ft_x).e.describe().round(2).to_dict())
# C. county-only record rows? (buildings with county cert and FDEM record) are excluded; also count county certs on rows with ffh_class record = should be 0
ms.to_parquet("s5_scored.parquet", index=False)
# D. record rows vs county (the FDEM record in the table vs the county's number for the same building)
rb = cl.merge(b[b.ffe_class=="record"], on="building_id")
e = rb.ffe_ft_y - rb.ffe_ft_x
print(f"\n[D] table RECORD rows that also have a county cert: {len(rb)}; table ffe - county ffe: MAE {e.abs().mean():.3f}, |d|<=0.5 {(e.abs()<=0.5).mean():.3f}, |d|>3 {(e.abs()>3).mean():.3f}")
sb = rb.touches_sfha & rb.bfe_ft.notna()
print(f"   BFE-side agreement of the table's record call with the county cert: {((rb.ffe_ft_y>=rb.bfe_ft)==(rb.ffe_ft_x>=rb.bfe_ft))[sb].mean():.3f} (n={int(sb.sum())})")
