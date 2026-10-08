import sys, numpy as np, pandas as pd
D = sys.argv[1]
b = pd.read_parquet(D+"/assemble/buildings_12103.parquet")
p = pd.read_parquet(D+"/assemble/parcels_12103.parquet")
print("=== parcel table duplicates")
dup = p[p.parcel_key.duplicated(keep=False)]
print("duplicated parcel_key rows:", len(dup), "distinct keys:", dup.parcel_key.nunique(), "max copies:", p.parcel_key.value_counts().max())
k = dup.parcel_key.value_counts().index[0]
print("example key rows (geom_group, buildings, below):", dup[dup.parcel_key==k][["geom_group","buildings","below","any_building_below_bfe"]].values.tolist()[:5])
same_geom = dup.groupby("parcel_key").geom_group.nunique()
print("duplicated keys whose copies have DIFFERENT geometry groups:", int((same_geom>1).sum()), "of", len(same_geom))
diff_call = dup.groupby("parcel_key").any_building_below_bfe.nunique()
print("duplicated keys whose copies DISAGREE on any_building_below_bfe:", int((diff_call>1).sum()))
pr = pd.read_parquet(D+"/assemble/parcels_raw_12103.parquet", columns=["parcel_id"])
print("parcels_raw rows", len(pr), "unique parcel_id", pr.parcel_id.nunique())
print("buildings whose parcel_key is duplicated in the parcel table:", int(b.parcel_key.isin(set(dup.parcel_key)).sum()))

print("\n=== touches_sfha True but every sfha zone share rounds to 0 (99 rows)")
def ssum(z): return sum(e["share"] for e in z if e["sfha"]) if z is not None and len(z) else 0.0
ss = np.array([ssum(z) for z in b.zones])
m = b.touches_sfha.values & (ss == 0)
print("count", m.sum(), "sfha_share of those: max", b.sfha_share[m].max(), "| their bfe_call:", b.bfe_call[m].value_counts(dropna=False).to_dict(), "| bfe_ft set:", int(b.bfe_ft[m].notna().sum()))
print("example zones:", b.zones[m].iloc[0].tolist(), "sfha_share", b.sfha_share[m].iloc[0])
print("touches_sfha with sfha_share < 0.001:", int((b.touches_sfha & (b.sfha_share < 0.001)).sum()), "| of which bfe_call below/above/too_close:", b.bfe_call[b.touches_sfha & (b.sfha_share < 0.001)].value_counts().to_dict())
print("footprint_area_m2 * sfha_share < 1 m2 and touches:", int((b.touches_sfha & (b.footprint_area_m2 * b.sfha_share < 1)).sum()))

print("\n=== 3 rows: ffe_null not_determinable but ffh_null not_evaluated")
x = b[(b.ffe_null=="not_determinable") & (b.ffh_null=="not_evaluated")]
print(x[["in_risk_area","dor_use_code","ffh_null","ffe_null","raised_flag_null","ffe_record_lidar_conflict","ffe_class","ffh_class"]].to_string())
print("record_note:", x.record_note.str.replace(r"\d+(\.\d+)?","N",regex=True).tolist())
print("\n=== record rows: ffh null but ffe record and model-eligible (model_version set):", int(((b.ffe_class=="record") & b.ffh_ft.isna() & b.model_version.notna()).sum()))
print("=== record-class rows that also are model-eligible (raised_flag set):", int(((b.ffe_class=="record") & b.raised_flag.notna()).sum()), "raised True among them:", int(((b.ffe_class=="record") & (b.raised_flag==True)).sum()))
print("=== conflict flag True but ffe_class not record (rejected):", int(((b.ffe_record_lidar_conflict==True) & (b.ffe_class!="record")).sum()), " these ffe_class:", b.ffe_class[(b.ffe_record_lidar_conflict==True) & (b.ffe_class!="record")].value_counts(dropna=False).to_dict())
print("=== ffe_vintage LLM windows among record rows:", int(((b.ffe_class=="record") & b.ffe_vintage.str.contains("/")).sum()), "| record_vintage_note set:", int(b.record_vintage_note.notna().sum()))
print("=== bfe_call for record ffe with interpolated bfe where ffe inside band but called:", b[(b.ffe_class=="record") & (b.bfe_method=="interpolated")].bfe_call.value_counts().to_dict())
# ffe_source contains OBJECTID (would be in viewer export)
print("=== ffe_source example pattern:", b.ffe_source[b.ffe_class=="record"].iloc[0][:60])
print("=== year_built min/max", b.year_built.min(), b.year_built.max(), "| living area max", b.living_area_sqft.max())
print("=== footprint_area_m2 > 2000 in risk:", int((b.in_risk_area & (b.footprint_area_m2 > 2000)).sum()), "roof_null not_evaluated in risk:", int((b.in_risk_area & (b.roof_null=="not_evaluated")).sum()))
