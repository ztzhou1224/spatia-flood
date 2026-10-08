import sys, duckdb, pandas as pd, numpy as np, h3
A = sys.argv[1]
b = pd.read_parquet(f"{A}/buildings_12103.parquet", columns=["building_id","lon","lat","bfe_call","ffh_class","ffh_ft","ffe_ft","ground_ft","bfe_ft","bfe_method","zone_main","touches_sfha","raised_flag","in_risk_area","ffh_band_hi","ffh_band_lo"])
b["cell"] = [h3.latlng_to_cell(la, lo, 8) for la, lo in zip(b.lat, b.lon)]
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
s = b[b.touches_sfha & b.bfe_call.isin(["above","below","too_close"])]
g = s.groupby("cell").agg(n=("bfe_call","size"), below=("bfe_call", lambda x: (x=="below").mean()), above=("bfe_call", lambda x: (x=="above").mean()), med_bfe=("bfe_ft","median"), med_ground=("ground_ft","median"), med_ffe=("ffe_ft","median"), lat=("lat","mean"), lon=("lon","mean"))
print("cells with >=30 decided-or-too_close SFHA buildings:", (g.n>=30).sum(), "of", len(g))
hot = g[(g.n>=30) & (g.below>0.85)].sort_values("below", ascending=False)
print(f"cells n>=30 and below share > 0.85: {len(hot)}")
print(hot.round(3).head(15).to_string())
# decided only
d = b[b.touches_sfha & b.bfe_call.isin(["above","below"])]
gd = d.groupby("cell").agg(n=("bfe_call","size"), below=("bfe_call", lambda x: (x=="below").mean()), med_bfe=("bfe_ft","median"), med_ground=("ground_ft","median"), lat=("lat","mean"), lon=("lon","mean"))
hd = gd[(gd.n>=30)&(gd.below>0.85)]
print(f"decided-only: cells n>=30 and below share > 0.85: {len(hd)} of {(gd.n>=30).sum()}; of these with med_bfe - med_ground > 8 ft: {(hd.med_bfe-hd.med_ground>8).sum()}")
print(hd.sort_values('n', ascending=False).round(2).head(10).to_string())
# modeled ffe below ground
m = b[b.ffh_class=="modeled"]
print("modeled ffe < ground anywhere:", int((m.ffe_ft < m.ground_ft).sum()))
gm = m.groupby("cell").agg(n=("ffh_ft","size"), med_ffh=("ffh_ft","median"), flagged=("raised_flag","mean"), lat=("lat","mean"), lon=("lon","mean"), med_ground=("ground_ft","median"), med_w=("ffh_band_hi", lambda x: 0))
gm["med_w"] = m.assign(w=m.ffh_band_hi-m.ffh_band_lo).groupby("cell").w.median()
top = gm[gm.n>=20].sort_values("med_ffh", ascending=False).head(10)
print("cells (n>=20 modeled) with highest median modeled ffh:"); print(top.round(2).to_string())
print("cells n>=20 with median modeled ffh > 6 ft:", int(((gm.n>=20)&(gm.med_ffh>6)).sum()), "; > 4 ft:", int(((gm.n>=20)&(gm.med_ffh>4)).sum()))
# inland check: use lon; barrier islands are lon < -82.78 roughly (Gulf side) ; print lon for the >6 cells
hi6 = gm[(gm.n>=20)&(gm.med_ffh>6)]
print(hi6.round(2).to_string())
g.to_csv("s4_cells_sfha.csv"); gm.to_csv("s4_cells_modeled.csv")
