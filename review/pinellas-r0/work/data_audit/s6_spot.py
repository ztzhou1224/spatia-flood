import sys, numpy as np, pandas as pd
A, L, T, C = sys.argv[1:5]
pd.set_option("display.width", 300); pd.set_option("display.max_columns", 50); pd.set_option("display.max_colwidth", 70)
b = pd.read_parquet(f"{A}/buildings_12103.parquet").drop(columns="geometry")
lab = pd.read_parquet(f"{T}/labels_12103.parquet"); lag = pd.read_parquet(f"{A}/fdem_lag_12103.parquet")
f = pd.read_parquet(f"{L}/features.parquet", columns=["building_id","g_lag","g_inside","g_med","roof_p95","eave_main","ridge","lpc_status","bldg_share","ground_in_share","ring_low_share"])
cl = pd.read_parquet(f"{C}/labels_pinellas_12103.parquet")
print("== 6a: 10 random record rows vs the FDEM label parquet ==")
r = b[b.ffe_class=="record"].sample(10, random_state=7).merge(lab, on="building_id").merge(lag, on="cert_objectid")
r["diagram_src"] = r.ffe_source.str.extract(r"diagram (\S+),")
r["issued"] = pd.to_datetime(r.issued_at, unit="ms").dt.strftime("%Y-%m-%d")
print(r[["building_id","ffe_ft_x","ffe_ft_y","ffh_ft","cert_lag_ft","bfe_ft","cert_bfe_ft","cert_zone","zone_main","bfe_call","diagram","diagram_src","ffe_vintage","issued","ffe_record_lidar_conflict"]].round(2).to_string())
print("agree ffe:", (np.abs(r.ffe_ft_x-r.ffe_ft_y)<1e-6).all(), "; ffh==ffe-lag:", (np.abs(r.ffh_ft-(r.ffe_ft_y-r.cert_lag_ft))<1e-6).sum(), "/", r.ffh_ft.notna().sum(), "; diagram agree:", (r.diagram==r.diagram_src).all(), "; vintage==issued:", (r.ffe_vintage==r.issued).sum())
print("table bfe vs certificate bfe: |diff|", (r.bfe_ft-r.cert_bfe_ft).abs().round(2).tolist())
# all record rows: table bfe vs cert bfe
ra = b[(b.ffe_class=="record") & b.bfe_ft.notna()].merge(lab, on="building_id")
d = (ra.bfe_ft - ra.cert_bfe_ft)
print(f"ALL record rows with a table BFE and a cert BFE: n={d.notna().sum()}, |diff|<=0.5: {(d.abs()<=0.5).mean():.3f}, median diff {d.median():+.2f}, |diff|>=2: {(d.abs()>=2).sum()}; cert zone vs zone_main agree: {(ra.cert_zone.str.upper().str[:2]==ra.zone_main.str[:2]).mean():.3f}")
print("  call flips if the certificate's own BFE were used:", int((((ra.ffe_ft_x>=ra.bfe_ft)!=(ra.ffe_ft_x>=ra.cert_bfe_ft)) & ra.cert_bfe_ft.notna() & ra.touches_sfha).sum()), "of", int((ra.cert_bfe_ft.notna() & ra.touches_sfha).sum()))
print("\n== 6b: 5 of the ffe_record_lidar_conflict rows ==")
c = b[b.ffe_record_lidar_conflict==True].sample(5, random_state=3).merge(f, on="building_id", how="left").merge(lab, on="building_id").merge(lag, on="cert_objectid").merge(cl[["building_id","ffe_ft","diagram","issued_at"]].rename(columns={"ffe_ft":"county_ffe","diagram":"county_diag"}), on="building_id", how="left")
c["dh"] = c.ffe_ft_y - c.g_lag
print(c[["building_id","ffe_class","ffe_ft_x","ffe_ft_y","county_ffe","diagram","county_diag","cert_lag_ft","ground_ft","g_inside","dh","roof_p95","eave_main","bfe_ft","bfe_call","bfe_call_basis","match","footprint_area_m2","record_note"]].round(2).to_string())
allc = b[b.ffe_record_lidar_conflict==True].merge(f, on="building_id", how="left").merge(lab, on="building_id").merge(lag, on="cert_objectid")
allc["dh"] = allc.ffe_ft_y - allc.g_lag
print(f"all {len(allc)} conflict rows: dh<-1: {(allc.dh<-1).sum()}, roof_p95-dh<6: {((allc.roof_p95-allc.dh)<6).sum()}, cert LAG - lidar ground: median {(allc.cert_lag_ft-allc.g_lag).median():+.2f}, |>3 ft|: {((allc.cert_lag_ft-allc.g_lag).abs()>3).sum()}, match nearest_10m share {(allc.match=='nearest_10m').mean():.2f} (vs all records {(lab.match=='nearest_10m').mean():.2f}); calls: {allc.bfe_call.value_counts(dropna=False).to_dict()}")
cc = allc.merge(cl[["building_id","ffe_ft"]].rename(columns={"ffe_ft":"county_ffe"}), on="building_id")
print(f"  conflict rows with a county cert: {len(cc)}; county ffe == FDEM ffe (|d|<0.5): {((cc.county_ffe-cc.ffe_ft_y).abs()<0.5).sum()}")
print("\n== 6c: 10 random modeled SFHA 'above' calls with floor_minus_bfe < 1 ft ==")
a = b[(b.bfe_call=="above") & (b.ffe_class=="modeled") & (b.floor_minus_bfe_ft < 1)]
print("population:", len(a), "; margin band_lo - bfe(hi): median", round(float((a.ffe_band_lo - a.bfe_band_hi.fillna(a.bfe_ft)).median()),3), "min", round(float((a.ffe_band_lo - a.bfe_band_hi.fillna(a.bfe_ft)).min()),4))
s = a.sample(10, random_state=11).merge(f, on="building_id", how="left")
s["margin_lo"] = s.ffe_band_lo - s.bfe_band_hi.fillna(s.bfe_ft); s["ring_vs_inside"] = s.g_inside - s.g_lag
print(s[["building_id","zone_main","bfe_ft","bfe_method","ffe_ft","ffe_band_lo","ffe_band_hi","margin_lo","ground_ft","ring_vs_inside","ffh_ft","ffh_band_lo","ffh_band_hi","roof_ft","eave_ft","raised_flag","year_built","dor_use_code","floor_minus_bfe_ft"]].round(2).to_string())
ac = a.merge(cl[["building_id","ffe_ft","diagram"]].rename(columns={"ffe_ft":"county_ffe"}), on="building_id")
ac = ac[~ac.building_id.isin(lab.building_id)]
print(f"\n  of the {len(a)} near-margin modeled 'above' rows, {len(ac)} have a county-only certificate: county floor >= table bfe (call right): {(ac.county_ffe>=ac.bfe_ft).sum()}, county floor < bfe (call WRONG): {(ac.county_ffe<ac.bfe_ft).sum()}; county floor inside the band: {((ac.county_ffe>=ac.ffe_band_lo)&(ac.county_ffe<=ac.ffe_band_hi)).sum()}")
print(ac[["building_id","diagram","county_ffe","ffe_ft","ffe_band_lo","ffe_band_hi","bfe_ft","bfe_method","floor_minus_bfe_ft"]].round(2).head(12).to_string())
# same for 'below' near margin
bl = b[(b.bfe_call=="below") & (b.ffe_class=="modeled") & (b.floor_minus_bfe_ft > -1)]
bc = bl.merge(cl[["building_id","ffe_ft"]].rename(columns={"ffe_ft":"county_ffe"}), on="building_id"); bc = bc[~bc.building_id.isin(lab.building_id)]
print(f"  near-margin modeled 'below' rows (floor_minus_bfe > -1): {len(bl)}; with county-only cert: {len(bc)}; county floor < bfe (right): {(bc.county_ffe<bc.bfe_ft).sum()}, >= bfe (WRONG): {(bc.county_ffe>=bc.bfe_ft).sum()}")
# all modeled decided calls vs county, by margin band
al = b[b.bfe_call.isin(["above","below"]) & (b.ffe_class=="modeled")].merge(cl[["building_id","ffe_ft"]].rename(columns={"ffe_ft":"county_ffe"}), on="building_id"); al = al[~al.building_id.isin(lab.building_id)]
al["margin"] = np.where(al.bfe_call=="above", al.ffe_band_lo - al.bfe_band_hi.fillna(al.bfe_ft), al.bfe_band_lo.fillna(al.bfe_ft) - al.ffe_band_hi)
al["right"] = (al.county_ffe >= al.bfe_ft) == (al.bfe_call=="above")
al["mb"] = pd.cut(al.margin, [-1e-9, 0.5, 1, 2, 4, 100])
print("\n  modeled decided calls vs county-only certs, by band margin:"); print(al.groupby(["bfe_call","mb"], observed=True).right.agg(n="size", correct="mean").round(3).to_string())
