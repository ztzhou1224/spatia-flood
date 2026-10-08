import sys, json, re
import numpy as np, pandas as pd, pyarrow.parquet as pq, shapely, geopandas as gpd
D = sys.argv[1]
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 50); pd.set_option("display.max_rows", 200)
b = pd.read_parquet(D+"/assemble/buildings_12103.parquet")
def sec(t): print("\n=== " + t)
sec("row counts / uniqueness")
print("rows", len(b), "building_id unique", b.building_id.is_unique, "nulls", b.building_id.isna().sum())
feat = pd.read_parquet(D+"/lidar/pinellas_2018/features.parquet"); runb = pd.read_parquet(D+"/lidar/pinellas_2018/buildings.parquet")
lab = pd.read_parquet(D+"/train/labels_12103.parquet"); lagf = pd.read_parquet(D+"/assemble/fdem_lag_12103.parquet")
rec = pd.read_parquet(D+"/train/records_12103.parquet")
print("features rows", len(feat), "unique", feat.building_id.is_unique, "| run buildings", len(runb), runb.building_id.is_unique)
print("labels rows", len(lab), "unique building", lab.building_id.is_unique, "unique cert_objectid", lab.cert_objectid.is_unique)
print("fdem_lag rows", len(lagf), "unique", lagf.cert_objectid.is_unique, "cols", list(lagf.columns), "datum", lagf.cert_datum.value_counts(dropna=False).to_dict())
print("records rows", len(rec), rec.building_id.is_unique)
print("in_risk_area", b.in_risk_area.sum(), "run set in county", runb.building_id.isin(b.building_id).all())
print("labels in county", lab.building_id.isin(b.building_id).sum(), "labels in run", lab.building_id.isin(runb.building_id).sum())
print("issued_at dtype", lab.issued_at.dtype, "null", lab.issued_at.isna().sum())

sec("modeled arithmetic")
m = b.ffh_class == "modeled"
print("modeled", m.sum(), "record", (b.ffh_class=="record").sum())
d = (b.ffe_ft - (b.ground_ft + b.ffh_ft))[m]
print("ffe != ground+ffh (modeled), |d|>1e-6:", int((d.abs()>1e-6).sum()), "max", d.abs().max())
for lohi in ("lo","hi"):
    d = (b[f"ffe_band_{lohi}"] - (b.ground_ft + b[f"ffh_band_{lohi}"]))[m]
    print(f"ffe_band_{lohi} mismatch:", int((d.abs()>1e-6).sum()))
print("ffe_class==ffh_class mismatch:", int((b.ffe_class.fillna("x") != b.ffh_class.fillna("x")).sum()))
print(pd.crosstab(b.ffe_class.fillna("<null>"), b.ffh_class.fillna("<null>")))
print("record ffe with null ffh (no usable cert LAG):", int(((b.ffe_class=="record") & b.ffh_ft.isna()).sum()))
print("ffh band contains ffh (modeled) violations:", int((m & ~((b.ffh_band_lo <= b.ffh_ft+1e-9) & (b.ffh_ft <= b.ffh_band_hi+1e-9))).sum()))
print("ffh_ft range record", b.ffh_ft[b.ffh_class=="record"].describe()[["min","50%","max"]].to_dict(), " modeled", b.ffh_ft[m].describe()[["min","50%","max"]].to_dict())
print("record ffh outside -1..30:", int(((b.ffh_class=="record") & ~b.ffh_ft.between(-1,30)).sum()))
print("ffe_record - ground outside -1..30 (where ground present):", int(((b.ffe_class=="record") & b.ground_ft.notna() & ~(b.ffe_ft-b.ground_ft).between(-1,30)).sum()))

sec("floor minus bfe")
fmb = b.ffe_ft - b.bfe_ft
print("floor_minus_bfe mismatch:", int(((b.floor_minus_bfe_ft - fmb).abs() > 1e-9).sum()), "| set where ffe or bfe null:", int((b.floor_minus_bfe_ft.notna() & (b.ffe_ft.isna()|b.bfe_ft.isna())).sum()))
blo, bhi = b.bfe_band_lo.fillna(b.bfe_ft), b.bfe_band_hi.fillna(b.bfe_ft)
flo, fhi = b.ffe_band_lo.fillna(b.ffe_ft), b.ffe_band_hi.fillna(b.ffe_ft)
banded = b.ffe_band_lo.notna() | b.bfe_band_lo.notna()
lo_exp = (flo - bhi).where(banded); hi_exp = (fhi - blo).where(banded)
print("band_lo mismatch:", int(((b.floor_minus_bfe_band_lo - lo_exp).abs() > 1e-9).sum() + (b.floor_minus_bfe_band_lo.isna() != lo_exp.isna()).sum()))
print("band_hi mismatch:", int(((b.floor_minus_bfe_band_hi - hi_exp).abs() > 1e-9).sum() + (b.floor_minus_bfe_band_hi.isna() != hi_exp.isna()).sum()))
print("band present but ffe or bfe null:", int((b.floor_minus_bfe_band_lo.notna() & b.floor_minus_bfe_ft.isna()).sum()))

sec("bfe_call recompute (docs/06 rule)")
Z90 = 1.645
sig = b.bfe_precision_ft.fillna(0)
isrec = b.ffe_class == "record"
ffe, bfe = b.ffe_ft, b.bfe_ft
rec_call = np.where((ffe-bfe).abs() < Z90*sig, "too_close", np.where(ffe >= bhi, "above", np.where(ffe < blo, "below", "too_close")))
mod_call = np.where(flo >= bhi, "above", np.where(fhi < blo, "below", "too_close"))
have = b.touches_sfha & bfe.notna() & ffe.notna()
exp = pd.Series(np.where(~b.touches_sfha, "not_applicable", np.where(have, np.where(isrec, rec_call, mod_call), None)), index=b.index)
print("bfe_call mismatch:", int((exp.fillna("<null>") != b.bfe_call.fillna("<null>")).sum()))
print("bfe_call values:", b.bfe_call.value_counts(dropna=False).to_dict())
print("bfe_call_basis values:", b.bfe_call_basis.value_counts(dropna=False).to_dict())
# rows where too_close via sigma rule
print("record too_close from sigma rule:", int((have & isrec & ((ffe-bfe).abs() < Z90*sig)).sum()), "| sigma>0 rows:", int((sig>0).sum()), "sigma values", b.bfe_precision_ft.value_counts(dropna=False).head(8).to_dict())
# calls with touches_sfha but bfe_call null: reasons
print("bfe_call_null values:", b.bfe_call_null.value_counts(dropna=False).to_dict())
print("bfe_call null & bfe_call_null null:", int((b.bfe_call.isna() & b.bfe_call_null.isna()).sum()))
print("sfha & call null & bfe present & ffe null -> bfe_call_null==ffe_null mismatches:", int((b.touches_sfha & b.bfe_call.isna() & bfe.notna() & (b.bfe_call_null.fillna("x") != b.ffe_null.fillna("x"))).sum()))

sec("raised_flag / touches / zone_main / sfha_share")
print("raised_flag == (model point > 3) on modeled rows mismatch:", int((m & (b.raised_flag.astype(object) != (b.ffh_ft > 3))).sum()))
print("raised_flag set but ffh not modeled (record or null):", pd.crosstab(b.raised_flag.astype(object).fillna("<NA>"), b.ffh_class.fillna("<null>")))
print("raised_flag null & raised_flag_null null:", int((b.raised_flag.isna() & b.raised_flag_null.isna()).sum()), "| raised set & reason set:", int((b.raised_flag.notna() & b.raised_flag_null.notna()).sum()))
zs = b.zones
def sfha_sum(z): return sum(e["share"] for e in z if e["sfha"]) if z is not None and len(z) else 0.0
ss = np.array([sfha_sum(z) for z in zs])
print("sfha_share vs sum(zones sfha shares) |d|>1e-3:", int((np.abs(ss - b.sfha_share.values) > 1e-3).sum()), "max |d|", np.abs(ss - b.sfha_share.values).max())
print("touches_sfha != (sfha_share>0):", int((b.touches_sfha != (b.sfha_share > 0)).sum()), "| touches != any zone sfha:", int((b.touches_sfha.values != (ss > 0)).sum()))
zm = np.array([z[0]["zone"] if z is not None and len(z) else None for z in zs], dtype=object)
zst = np.array([z[0]["subtype"] if z is not None and len(z) else None for z in zs], dtype=object)
print("zone_main != zones[0].zone:", int((pd.Series(zm) != b.zone_main.values).sum() - (pd.isna(zm) & b.zone_main.isna().values).sum()))
print("zone_main_subtype != zones[0].subtype:", int(((pd.Series(zst).fillna("<n>") != b.zone_main_subtype.fillna("<n>").values)).sum()))
print("zones sorted desc by share violations:", sum(1 for z in zs if z is not None and len(z) > 1 and any(z[i]["share"] < z[i+1]["share"] for i in range(len(z)-1))))
print("share sums >1.01:", int((np.array([sum(e["share"] for e in z) if z is not None and len(z) else 0 for z in zs]) > 1.01).sum()))
print("zones_null values:", b.zones_null.value_counts(dropna=False).to_dict(), "| zones None but zones_null None:", int(((zs.isna()) & b.zones_null.isna()).sum()))
print("zone_main counts:", b.zone_main.value_counts(dropna=False).to_dict())
print("bfe_method x zone_main (interpolated):", b[b.bfe_method=="interpolated"].zone_main.value_counts().to_dict())
print("bfe static but zone_main not SFHA:", pd.crosstab(b.bfe_method.fillna("<null>"), b.touches_sfha))

sec("string columns: distinct values / truncation check")
for col in ("bfe_class","bfe_method","bfe_null","ground_class","ground_null","roof_null","eave_null","year_built_null","living_area_sqft_null","raised_flag_null","ffh_class","ffh_null","ffe_class","ffe_null","bfe_call","bfe_call_basis","bfe_call_null","address_null","lift_or_rebuild_null","zones_null","provider","release","lidar_ql","ground_geoid","address_source","county_fips"):
    print(col, b[col].value_counts(dropna=False).to_dict() if b[col].nunique() < 15 else f"{b[col].nunique()} distinct, e.g. {b[col].dropna().unique()[:3].tolist()}")
print("ffe_datum:", b.ffe_datum.value_counts(dropna=False).to_dict())
print("bfe_datum:", b.bfe_datum.value_counts(dropna=False).to_dict())
print("ground_vintage:", b.ground_vintage.value_counts(dropna=False).to_dict())
print("ffe_vintage unknown:", int((b.ffe_vintage=="unknown").sum()), "| windows:", int(b.ffe_vintage.fillna("").str.contains("/").sum()), " examples", b.ffe_vintage[b.ffe_vintage.fillna("").str.contains("/")].unique()[:5].tolist())
print("ffh_vintage != ffe_vintage where both set:", int(((b.ffh_vintage.notna()&b.ffe_vintage.notna()) & (b.ffh_vintage != b.ffe_vintage)).sum()))
rv = b.ffe_vintage[(b.ffe_class=="record")]
dates = pd.to_datetime(rv.where(rv.str.match(r"^\d{4}-\d{2}-\d{2}$")), errors="coerce")
print("record vintage date range:", dates.min(), dates.max(), "| > built 2026-10-07:", int((dates > "2026-10-07").sum()), "| < 1990:", int((dates < "1990-01-01").sum()))
print("firm_effective_date range:", b.firm_effective_date.min(), b.firm_effective_date.max(), "| > 2026-10-08:", int((b.firm_effective_date > "2026-10-08").sum()), "| bfe_vintage > today:", int((b.bfe_vintage.fillna("") > "2026-10-08").sum()), b.bfe_vintage[b.bfe_vintage.fillna("") > "2026-10-08"].value_counts().to_dict())
print("firm_effective_date null:", b.firm_effective_date.isna().sum(), "'NaT' strings:", int((b.firm_effective_date=="NaT").sum()))

sec("addresses")
print("address null:", b.address.isna().sum(), "| in risk & null:", int((b.address.isna() & b.in_risk_area).sum()))
print("address ending ' nan' or containing 'nan':", int(b.address.fillna("").str.contains(r"\bnan\b").sum()), "| 'None':", int(b.address.fillna("").str.contains(r"\bNone\b").sum()), "| ending ', ':", int(b.address.fillna("").str.endswith(",").sum()), "| starting ', ':", int(b.address.fillna("").str.startswith(",").sum()))
print(b.address[b.address.fillna("").str.contains(r"\bnan\b")].head(3).str.replace(r"^\d+", "N", regex=True).tolist())
print("address_source:", b.address_source.value_counts(dropna=False).to_dict())
print("empty-ish address (len<8):", int((b.address.fillna("").str.len().between(1,7)).sum()), b.address[b.address.fillna("").str.len().between(1,7)].unique()[:10].tolist())

sec("dor_use_code")
duc = b.dor_use_code
print("dtype", duc.dtype, "null", duc.isna().sum(), "lengths", duc.dropna().str.len().value_counts().to_dict())
print("codes starting with 0 (<'010' lexical):", (duc.fillna("999") < "010").sum(), "| 3-digit zero padded 000-009:", duc.fillna("").str.match(r"^00\d$").sum())
print("codes lexically < '010' but not 000-009:", duc[(duc.fillna("999") < "010") & ~duc.fillna("").str.match(r"^00\d$")].value_counts().to_dict())
print("sample codes", duc.value_counts().head(12).to_dict())

sec("ground / lidar")
print("ground_ft in risk null:", int((b.in_risk_area & b.ground_ft.isna()).sum()), " outside risk non-null:", int((~b.in_risk_area & b.ground_ft.notna()).sum()))
print("ground_precision values:", b.ground_precision_ft.value_counts(dropna=False).to_dict())
print("lidar_workunit:", b.lidar_workunit.value_counts(dropna=False).to_dict())
print("in risk but no workunit:", int((b.in_risk_area & b.lidar_workunit.isna()).sum()))
f2 = b[["building_id","in_risk_area","ground_ft","roof_ft","eave_ft","roof_null","ground_null","ffh_null","raised_flag_null"]].merge(feat, on="building_id", how="left")
print("ground_ft != g_lag (risk):", int((f2.in_risk_area & ((f2.ground_ft - f2.g_lag).abs() > 1e-9)).sum()))
print("roof_ft != ridge where lpc ok:", int(((f2.lpc_status=="ok") & f2.in_risk_area & ((f2.roof_ft - f2.ridge).abs() > 1e-9)).sum()), "| eave != eave_main:", int(((f2.lpc_status=="ok") & f2.in_risk_area & ((f2.eave_ft - f2.eave_main).abs() > 1e-9) & f2.eave_main.notna()).sum()))
print("lpc_status x roof_null:"); print(pd.crosstab(f2.lpc_status.fillna("<none>"), f2.roof_null.fillna("<value>")))
print("ground_status x ground_null:"); print(pd.crosstab(f2.ground_status.fillna("<none>"), f2.ground_null.fillna("<value>")))

sec("null-reason crosstabs: ffh_null x in_risk x residential x lpc")
resid = (b.dor_use_code.fillna("999") < "010") & b.parcel_key.notna()
x = pd.DataFrame({"ffh_null": b.ffh_null.fillna("<value>:"+b.ffh_class.fillna("")), "risk": b.in_risk_area, "parcel": b.parcel_key.notna(), "resid": resid, "lpc": f2.lpc_status.fillna("<none>").values, "ground": b.ground_ft.notna()})
print(x.groupby(["risk","parcel","resid","lpc","ground","ffh_null"]).size().to_string())
print("\nffe_null x ffh_null:"); print(pd.crosstab(b.ffe_null.fillna("<value>"), b.ffh_null.fillna("<value>")))
print("\nraised_flag_null x ffh_null:"); print(pd.crosstab(b.raised_flag_null.fillna("<value>"), b.ffh_null.fillna("<value>")))
print("\nbfe_null x touches_sfha:"); print(pd.crosstab(b.bfe_null.fillna("<value>"), b.touches_sfha))
print("\nyear_built_null x parcel:"); print(pd.crosstab(b.year_built_null.fillna("<value>"), b.parcel_key.notna()))
print("record_note count:", b.record_note.notna().sum(), "| conflict:", b.ffe_record_lidar_conflict.value_counts(dropna=False).to_dict())
print("record_note kinds:", b.record_note.dropna().str.replace(r"\d+(\.\d+)?", "N", regex=True).str.slice(0,80).value_counts().to_dict())
print("model_version set x ffh_class:"); print(pd.crosstab(b.model_version.notna(), b.ffh_class.fillna("<null>")))
print("parcels_at_centroid:", b.parcels_at_centroid.value_counts().head(6).to_dict(), "| parcel_key null but parcels_at_centroid>0:", int((b.parcel_key.isna() & (b.parcels_at_centroid>0)).sum()), "| parcel set but 0:", int((b.parcel_key.notna() & (b.parcels_at_centroid==0)).sum()))
