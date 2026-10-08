"""Step 2 internal consistency + Step 3 distributions."""
import sys, json, duckdb, numpy as np, pandas as pd
A = sys.argv[1]; B=f"{A}/buildings_12103.parquet"; P=f"{A}/parcels_12103.parquet"
con = duckdb.connect(); con.execute("LOAD spatial")
con.execute(f"CREATE VIEW b AS SELECT * EXCLUDE (geometry) FROM read_parquet('{B}')")
con.execute(f"CREATE VIEW p AS SELECT * FROM read_parquet('{P}')")
def q(s): return con.execute(s).df()
def one(s): return con.execute(s).fetchone()[0]
out = {}
print("== STEP 2 ==")
out["dup building_id"] = one("SELECT count(*)-count(DISTINCT building_id) FROM b")
out["lon/lat null"] = one("SELECT count(*) FROM b WHERE lon IS NULL OR lat IS NULL")
out["centroid outside footprint bbox"] = one(f"SELECT count(*) FROM read_parquet('{B}') WHERE NOT (lon BETWEEN ST_XMin(geometry) AND ST_XMax(geometry) AND lat BETWEEN ST_YMin(geometry) AND ST_YMax(geometry))")
out["lon/lat outside Pinellas bbox (-83.0..-82.4, 27.5..28.2)"] = one("SELECT count(*) FROM b WHERE NOT (lon BETWEEN -83.0 AND -82.4 AND lat BETWEEN 27.5 AND 28.2)")
out["lon/lat range"] = [one("SELECT min(lon) FROM b"), one("SELECT max(lon) FROM b"), one("SELECT min(lat) FROM b"), one("SELECT max(lat) FROM b")]
out["geometry invalid"] = one(f"SELECT count(*) FROM read_parquet('{B}') WHERE NOT ST_IsValid(geometry)")
out["geometry null"] = one(f"SELECT count(*) FROM read_parquet('{B}') WHERE geometry IS NULL")
for s in ("ffh","ffe","bfe"):
    out[f"{s}: modeled band violates lo<=v<=hi"] = one(f"SELECT count(*) FROM b WHERE {s}_class='modeled' AND NOT ({s}_band_lo <= {s}_ft + 1e-9 AND {s}_ft <= {s}_band_hi + 1e-9)")
    out[f"{s}: modeled without band"] = one(f"SELECT count(*) FROM b WHERE {s}_class='modeled' AND ({s}_band_lo IS NULL OR {s}_band_hi IS NULL)")
    out[f"{s}: band on non-modeled"] = one(f"SELECT count(*) FROM b WHERE coalesce({s}_class,'')<>'modeled' AND {s}_band_lo IS NOT NULL")
out["ffe != ground+ffh (modeled, >1e-6)"] = one("SELECT count(*) FROM b WHERE ffe_class='modeled' AND abs(ffe_ft-(ground_ft+ffh_ft))>1e-6")
out["ffe band != ground+ffh band (modeled)"] = one("SELECT count(*) FROM b WHERE ffe_class='modeled' AND (abs(ffe_band_lo-(ground_ft+ffh_band_lo))>1e-6 OR abs(ffe_band_hi-(ground_ft+ffh_band_hi))>1e-6)")
out["ffh modeled but ffe not modeled / vice versa"] = one("SELECT count(*) FROM b WHERE (ffh_class='modeled') <> (ffe_class='modeled')")
out["ffh record but ffe not record"] = one("SELECT count(*) FROM b WHERE ffh_class='record' AND coalesce(ffe_class,'')<>'record'")
# record ffh == ffe - certificate LAG
con.execute(f"CREATE VIEW lab AS SELECT * FROM read_parquet('{A}/../train/labels_12103.parquet')")
con.execute(f"CREATE VIEW lag AS SELECT * FROM read_parquet('{A}/fdem_lag_12103.parquet')")
out["labels dup building_id"] = one("SELECT count(*)-count(DISTINCT building_id) FROM lab")
out["fdem_lag dup objectid"] = one("SELECT count(*)-count(DISTINCT cert_objectid) FROM lag")
out["record ffh != ffe - cert LAG (>1e-6)"] = one("""SELECT count(*) FROM b JOIN lab USING (building_id) JOIN lag USING (cert_objectid)
   WHERE b.ffh_class='record' AND abs(b.ffh_ft - (lab.ffe_ft - lag.cert_lag_ft))>1e-6""")
out["record ffe != certificate ffe"] = one("SELECT count(*) FROM b JOIN lab USING (building_id) WHERE b.ffe_class='record' AND abs(b.ffe_ft-lab.ffe_ft)>1e-6")
out["record ffh outside -1..30"] = one("SELECT count(*) FROM b WHERE ffh_class='record' AND NOT (ffh_ft BETWEEN -1 AND 30)")
out["record ffe - ground outside -1..30 (where ground)"] = one("SELECT count(*) FROM b WHERE ffe_class='record' AND ground_ft IS NOT NULL AND NOT (ffe_ft-ground_ft BETWEEN -1 AND 30)")
out["cert LAG datum values"] = q("SELECT cert_datum, count(*) n FROM lag GROUP BY 1").to_dict("records")
out["record rows whose cert LAG datum is not navd_1988"] = one("SELECT count(*) FROM b JOIN lab USING (building_id) JOIN lag USING (cert_objectid) WHERE b.ffh_class='record' AND coalesce(lag.cert_datum,'')<>'navd_1988'")
out["floor_minus_bfe != ffe-bfe"] = one("SELECT count(*) FROM b WHERE floor_minus_bfe_ft IS NOT NULL AND abs(floor_minus_bfe_ft-(ffe_ft-bfe_ft))>1e-6")
out["floor_minus_bfe null although ffe & bfe present"] = one("SELECT count(*) FROM b WHERE floor_minus_bfe_ft IS NULL AND ffe_ft IS NOT NULL AND bfe_ft IS NOT NULL")
out["floor_minus_bfe present but not touching SFHA"] = one("SELECT count(*) FROM b WHERE floor_minus_bfe_ft IS NOT NULL AND NOT touches_sfha")
out["fmb band lo != flo - bhi"] = one("""SELECT count(*) FROM b WHERE floor_minus_bfe_band_lo IS NOT NULL AND
  abs(floor_minus_bfe_band_lo - (coalesce(ffe_band_lo,ffe_ft) - coalesce(bfe_band_hi,bfe_ft)))>1e-6""")
# bfe_call vs the rule
rule = """SELECT building_id, bfe_call, bfe_call_basis, touches_sfha, ffe_class, bfe_method, bfe_precision_ft, ffe_ft, bfe_ft,
  coalesce(ffe_band_lo,ffe_ft) flo, coalesce(ffe_band_hi,ffe_ft) fhi, coalesce(bfe_band_lo,bfe_ft) blo, coalesce(bfe_band_hi,bfe_ft) bhi,
  ffe_record_lidar_conflict FROM b"""
r = q(rule)
sig = r.bfe_precision_ft.fillna(0).values
rec = r.ffe_class.values == "record"
have = r.touches_sfha.values & r.ffe_ft.notna().values & r.bfe_ft.notna().values
rec_call = np.where(np.abs(r.ffe_ft-r.bfe_ft) < 1.645*sig, "too_close", np.where(r.ffe_ft >= r.bhi, "above", np.where(r.ffe_ft < r.blo, "below", "too_close")))
mod_call = np.where(r.flo >= r.bhi, "above", np.where(r.fhi < r.blo, "below", "too_close"))
exp = np.where(~r.touches_sfha.values, "not_applicable", np.where(have, np.where(rec, rec_call, mod_call), None))
mism = (pd.Series(exp) != r.bfe_call) & ~(pd.Series(exp).isna() & r.bfe_call.isna())
out["bfe_call != rule"] = int(mism.sum())
# record call at exactly BFE
out["record ffe == bfe exactly -> call"] = q("SELECT bfe_call, count(*) n FROM b WHERE ffe_class='record' AND bfe_method='static' AND ffe_ft=bfe_ft GROUP BY 1").to_dict("records")
out["bfe_precision_ft distinct (static)"] = q("SELECT bfe_precision_ft, count(*) n FROM b WHERE bfe_method='static' GROUP BY 1 ORDER BY 2 DESC").to_dict("records")
out["bfe_datum distinct"] = q("SELECT bfe_datum, count(*) n FROM b WHERE bfe_ft IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").to_dict("records")
out["record too_close calls (sigma>0)"] = one("SELECT count(*) FROM b WHERE bfe_call='too_close' AND ffe_class='record'")
# basis
exp_basis = np.where(have, np.where(rec, np.where(r.ffe_record_lidar_conflict.fillna(False).values.astype(bool), "record_lidar_conflict","record"), "modeled_band") + np.where(r.bfe_method.values=="interpolated","+interpolated_bfe",""), None)
out["bfe_call_basis != rule"] = int(((pd.Series(exp_basis) != r.bfe_call_basis) & ~(pd.Series(exp_basis).isna() & r.bfe_call_basis.isna())).sum())
# parcel sums
pc = q("""WITH bp AS (SELECT parcel_key, sum(CASE WHEN bfe_call='below' THEN 1 ELSE 0 END) bl, sum(CASE WHEN bfe_call='above' THEN 1 ELSE 0 END) ab,
  sum(CASE WHEN bfe_call='too_close' THEN 1 ELSE 0 END) tc, count(*) n FROM b WHERE parcel_key IS NOT NULL GROUP BY 1)
  SELECT count(*) parcels_compared, sum(CASE WHEN p.below<>bp.bl THEN 1 ELSE 0 END) below_diff, sum(CASE WHEN p.above<>bp.ab THEN 1 ELSE 0 END) above_diff,
  sum(CASE WHEN p.too_close<>bp.tc THEN 1 ELSE 0 END) tc_diff, sum(CASE WHEN p.buildings<>bp.n THEN 1 ELSE 0 END) n_diff FROM p JOIN bp USING (parcel_key)""")
out["parcel table vs centroid-parcel building sums (NOTE: parcel table uses >=10% overlap, not centroid)"] = pc.to_dict("records")
out["parcel totals: below/above/too_close sums"] = q("SELECT sum(below) below, sum(above) above, sum(too_close) too_close, sum(buildings) buildings FROM p").to_dict("records")
out["building totals below/above/too_close"] = q("SELECT sum(CASE WHEN bfe_call='below' THEN 1 ELSE 0 END) below, sum(CASE WHEN bfe_call='above' THEN 1 ELSE 0 END) above, sum(CASE WHEN bfe_call='too_close' THEN 1 ELSE 0 END) too_close FROM b").to_dict("records")
out["parcel any_building_below_bfe != below>0"] = one("SELECT count(*) FROM p WHERE any_building_below_bfe <> (coalesce(below,0)>0)")
out["parcel dup parcel_key"] = one("SELECT count(*)-count(DISTINCT parcel_key) FROM p")
out["parcel primary_building_id not in building table"] = one("SELECT count(*) FROM p WHERE primary_building_id IS NOT NULL AND primary_building_id NOT IN (SELECT building_id FROM b)")
out["building parcel_key not in parcel table"] = one("SELECT count(*) FROM b WHERE parcel_key IS NOT NULL AND parcel_key NOT IN (SELECT parcel_key FROM p)")
out["parcel: buildings count > 0 but all of below/above/too_close null"] = one("SELECT count(*) FROM p WHERE buildings>0 AND below IS NULL")
# zones
z = q("SELECT building_id, zones, zone_main, zone_main_subtype, sfha_share, touches_sfha, zones_null FROM b")
zz = z[z.zones.notna()]
ssum = zz.zones.map(lambda L: sum(d["share"] for d in L))
out["zones share sum < 0.99"] = int((ssum < 0.99).sum()); out["zones share sum > 1.01"] = int((ssum > 1.01).sum())
out["zones share sum distribution"] = ssum.describe(percentiles=[.001,.01,.05,.5]).round(4).to_dict()
out["zone_main != first element"] = int((zz.zone_main.values != zz.zones.map(lambda L: L[0]["zone"]).values).sum())
out["first element not max share"] = int(zz.zones.map(lambda L: L[0]["share"] < max(d["share"] for d in L) - 1e-9).sum())
out["zone_main_subtype != first element subtype"] = int((zz.zone_main_subtype.fillna("<n>").values != zz.zones.map(lambda L: L[0]["subtype"] or "<n>").values).sum())
sf = zz.zones.map(lambda L: min(1.0, sum(d["share"] for d in L if d["sfha"])))
out["sfha_share != sum sfha shares (>1e-3)"] = int((np.abs(sf.values - zz.sfha_share.values) > 1e-3).sum())
out["touches_sfha != sfha_share>0"] = int((zz.touches_sfha.values != (zz.sfha_share.values > 0)).sum())
out["touches_sfha with zones null"] = int(z[z.zones.isna()].touches_sfha.sum())
out["zones null but zone_main set"] = int(z[z.zones.isna()].zone_main.notna().sum())
out["zone list: sfha flag by zone"] = {str(k): int(v) for k, v in zz.zones.explode().map(lambda d: (d["zone"], d["sfha"])).value_counts().items()}
out["raised_flag != ffh modeled > 3 (model-eligible)"] = one("SELECT count(*) FROM b WHERE ffh_class='modeled' AND raised_flag <> (ffh_ft > 3)")
out["raised_flag set but ffh not modeled (record or null)"] = q("SELECT ffh_class, count(*) n FROM b WHERE raised_flag IS NOT NULL AND coalesce(ffh_class,'')<>'modeled' GROUP BY 1").to_dict("records")
out["distinct provider/release/model_version/footprint_release"] = q("SELECT provider, release, model_version, footprint_release, count(*) n FROM b GROUP BY 1,2,3,4").to_dict("records")
out["input_licences distinct tags"] = q("SELECT tag, count(*) n FROM (SELECT unnest(input_licences) tag FROM b) GROUP BY 1 ORDER BY 2 DESC").to_dict("records")
out["input_licences: fdem tag vs record_note/ffe record"] = q("""SELECT list_contains(input_licences,'fdem_certificates:terms_unread') fdem, ffe_class='record' rec, record_note IS NOT NULL note, count(*) n FROM b GROUP BY 1,2,3""").to_dict("records")
out["input_licences: 3dep tag vs in_risk_area"] = one("SELECT count(*) FROM b WHERE list_contains(input_licences,'usgs_3dep:public_domain') <> in_risk_area")
REASONS = ("not_applicable","no_coverage","not_determinable","stale","withheld","not_evaluated")
nulls = [c for c in q("DESCRIBE b").column_name if c.endswith("_null")]
bad = {}
for c in nulls:
    n = one(f"SELECT count(*) FROM b WHERE {c} IS NOT NULL AND {c} NOT IN {REASONS}")
    if n: bad[c] = n
out["*_null outside six reasons"] = bad
out["_null distincts"] = {c: q(f"SELECT {c} v, count(*) n FROM b GROUP BY 1 ORDER BY 2 DESC").to_dict("records") for c in nulls}
# vintages
vint = {}
for c in ("bfe_vintage","ground_vintage","roof_vintage","eave_vintage","year_built_vintage","living_area_sqft_vintage","ffh_vintage","ffe_vintage","firm_effective_date"):
    d = q(f"SELECT {c} v, count(*) n FROM b WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
    import re
    pat = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{4})(/(\d{4}-\d{2}-\d{2}))?$")
    badv = d[~d.v.map(lambda s: bool(pat.match(s)))]
    vint[c] = {"distinct": len(d), "top": d.head(4).to_dict("records"), "nonparsing_distinct": len(badv), "nonparsing_rows": int(badv.n.sum()), "examples": badv.v.head(5).tolist(), "min": d.v.min(), "max": d.v.max()}
out["vintages"] = vint
out["ffe_vintage window (a/b) count"] = one("SELECT count(*) FROM b WHERE ffe_class='record' AND ffe_vintage LIKE '%/%'")
out["ffe_vintage = unknown"] = one("SELECT count(*) FROM b WHERE ffe_vintage='unknown'")
out["ffe_vintage > built date 2026-10-07"] = one("SELECT count(*) FROM b WHERE ffe_class='record' AND ffe_vintage NOT LIKE '%/%' AND ffe_vintage > '2026-10-07'")
out["ffe_vintage window end > 2026-10-07 or start>end"] = one("SELECT count(*) FROM b WHERE ffe_vintage LIKE '%/%' AND ffe_class='record' AND (split_part(ffe_vintage,'/',2) > '2026-10-07' OR split_part(ffe_vintage,'/',1) > split_part(ffe_vintage,'/',2))")
out["ffe_record_lidar_conflict distinct"] = q("SELECT ffe_record_lidar_conflict v, ffe_class, count(*) n FROM b GROUP BY 1,2 ORDER BY 3 DESC").to_dict("records")
out["ground_geoid distinct"] = q("SELECT ground_geoid, ground_precision_ft, lidar_ql, count(*) n FROM b GROUP BY 1,2,3").to_dict("records")
out["ffe_datum distinct"] = q("SELECT ffe_datum, count(*) n FROM b GROUP BY 1").to_dict("records")
out["county_fips distinct"] = q("SELECT county_fips, count(*) n FROM b GROUP BY 1").to_dict("records")
out["address_null distinct / address null count"] = [q("SELECT address_null, count(*) n FROM b GROUP BY 1").to_dict("records"), one("SELECT count(*) FROM b WHERE address IS NULL")]
out["address empty-ish ('' or ', ' only)"] = one("SELECT count(*) FROM b WHERE address IS NOT NULL AND length(regexp_replace(address,'[ ,]',''))<3")
out["address starts with ', ' (no number/street)"] = one("SELECT count(*) FROM b WHERE address LIKE ',%' OR address LIKE ' %'")
out["address examples odd"] = q("SELECT address, address_source FROM b WHERE address IS NOT NULL AND (address LIKE ',%' OR length(regexp_replace(address,'[ ,]',''))<6) LIMIT 5").to_dict("records")

print("== STEP 3 ==")
d3 = {}
for cls in ("record","modeled"):
    d3[f"ffh_ft {cls}"] = q(f"SELECT count(*) n, min(ffh_ft) mn, quantile_cont(ffh_ft,0.01) p1, quantile_cont(ffh_ft,0.05) p5, median(ffh_ft) p50, quantile_cont(ffh_ft,0.95) p95, quantile_cont(ffh_ft,0.99) p99, max(ffh_ft) mx, sum(CASE WHEN ffh_ft<0 THEN 1 ELSE 0 END) neg, sum(CASE WHEN ffh_ft<-1 THEN 1 ELSE 0 END) lt_m1, sum(CASE WHEN ffh_ft>20 THEN 1 ELSE 0 END) gt20, sum(CASE WHEN ffh_ft>12 THEN 1 ELSE 0 END) gt12 FROM b WHERE ffh_class='{cls}'").round(3).to_dict("records")
    d3[f"ffe_ft {cls}"] = q(f"SELECT count(*) n, min(ffe_ft) mn, quantile_cont(ffe_ft,0.01) p1, median(ffe_ft) p50, quantile_cont(ffe_ft,0.99) p99, max(ffe_ft) mx FROM b WHERE ffe_class='{cls}'").round(3).to_dict("records")
d3["ffe-ground (record, where ground)"] = q("SELECT count(*) n, min(ffe_ft-ground_ft) mn, quantile_cont(ffe_ft-ground_ft,0.01) p1, median(ffe_ft-ground_ft) p50, quantile_cont(ffe_ft-ground_ft,0.99) p99, max(ffe_ft-ground_ft) mx FROM b WHERE ffe_class='record' AND ground_ft IS NOT NULL").round(3).to_dict("records")
d3["record ffh vs ffe-ground diff (cert LAG - lidar ground)"] = q("SELECT count(*) n, min((ffe_ft-ground_ft)-ffh_ft) mn, quantile_cont((ffe_ft-ground_ft)-ffh_ft,0.05) p5, median((ffe_ft-ground_ft)-ffh_ft) p50, quantile_cont((ffe_ft-ground_ft)-ffh_ft,0.95) p95, max((ffe_ft-ground_ft)-ffh_ft) mx, sum(CASE WHEN abs((ffe_ft-ground_ft)-ffh_ft)>3 THEN 1 ELSE 0 END) gt3 FROM b WHERE ffh_class='record' AND ground_ft IS NOT NULL").round(3).to_dict("records")
d3["ground_ft"] = q("SELECT count(*) n, min(ground_ft) mn, quantile_cont(ground_ft,0.001) p01, median(ground_ft) p50, quantile_cont(ground_ft,0.999) p999, max(ground_ft) mx, sum(CASE WHEN ground_ft<-2 THEN 1 ELSE 0 END) lt_m2, sum(CASE WHEN ground_ft<0 THEN 1 ELSE 0 END) lt0, sum(CASE WHEN ground_ft>60 THEN 1 ELSE 0 END) gt60 FROM b WHERE ground_ft IS NOT NULL").round(3).to_dict("records")
d3["year_built"] = q("SELECT count(*) n, min(year_built) mn, quantile_cont(year_built,0.001) p01, median(year_built) p50, max(year_built) mx, sum(CASE WHEN year_built>2026 THEN 1 ELSE 0 END) future, sum(CASE WHEN year_built<1850 THEN 1 ELSE 0 END) lt1850, sum(CASE WHEN year_built<1900 THEN 1 ELSE 0 END) lt1900 FROM b WHERE year_built IS NOT NULL").to_dict("records")
d3["year_built lowest 10 distinct"] = q("SELECT year_built, count(*) n FROM b WHERE year_built IS NOT NULL GROUP BY 1 ORDER BY 1 LIMIT 10").to_dict("records")
d3["living_area"] = q("SELECT count(*) n, min(living_area_sqft) mn, quantile_cont(living_area_sqft,0.001) p01, median(living_area_sqft) p50, quantile_cont(living_area_sqft,0.999) p999, max(living_area_sqft) mx, sum(CASE WHEN living_area_sqft<=0 THEN 1 ELSE 0 END) le0, sum(CASE WHEN living_area_sqft<100 THEN 1 ELSE 0 END) lt100, sum(CASE WHEN living_area_sqft>50000 THEN 1 ELSE 0 END) gt50k FROM b WHERE living_area_sqft IS NOT NULL").round(1).to_dict("records")
d3["footprint_area_m2"] = q("SELECT min(footprint_area_m2) mn, quantile_cont(footprint_area_m2,0.001) p01, median(footprint_area_m2) p50, quantile_cont(footprint_area_m2,0.999) p999, max(footprint_area_m2) mx, sum(CASE WHEN footprint_area_m2<5 THEN 1 ELSE 0 END) lt5, sum(CASE WHEN footprint_area_m2<1 THEN 1 ELSE 0 END) lt1, sum(CASE WHEN footprint_area_m2>2000 THEN 1 ELSE 0 END) gt2000, sum(CASE WHEN footprint_area_m2>2000 AND ffh_class='modeled' THEN 1 ELSE 0 END) gt2000_modeled FROM b").round(2).to_dict("records")
d3["modeled ffh band width"] = q("SELECT count(*) n, min(ffh_band_hi-ffh_band_lo) mn, quantile_cont(ffh_band_hi-ffh_band_lo,0.05) p5, median(ffh_band_hi-ffh_band_lo) p50, quantile_cont(ffh_band_hi-ffh_band_lo,0.95) p95, max(ffh_band_hi-ffh_band_lo) mx, sum(CASE WHEN ffh_band_hi-ffh_band_lo>10 THEN 1 ELSE 0 END) gt10, sum(CASE WHEN ffh_band_hi-ffh_band_lo>10 AND raised_flag THEN 1 ELSE 0 END) gt10_flagged, sum(CASE WHEN ffh_band_hi-ffh_band_lo>5 THEN 1 ELSE 0 END) gt5 FROM b WHERE ffh_class='modeled'").round(3).to_dict("records")
d3["band width by raised_flag (modeled)"] = q("SELECT raised_flag, count(*) n, median(ffh_band_hi-ffh_band_lo) med_w, median(ffh_ft) med_ffh, quantile_cont(ffh_band_hi-ffh_band_lo,0.9) p90_w FROM b WHERE ffh_class='modeled' GROUP BY 1").round(3).to_dict("records")
d3["band width > 10 ft, by flag share"] = q("SELECT raised_flag, count(*) n FROM b WHERE ffh_class='modeled' AND ffh_band_hi-ffh_band_lo>10 GROUP BY 1").to_dict("records")
d3["bfe_ft static"] = q("SELECT count(*) n, min(bfe_ft) mn, quantile_cont(bfe_ft,0.01) p1, median(bfe_ft) p50, quantile_cont(bfe_ft,0.99) p99, max(bfe_ft) mx, sum(CASE WHEN bfe_ft<=0 THEN 1 ELSE 0 END) le0, sum(CASE WHEN bfe_ft>30 THEN 1 ELSE 0 END) gt30, sum(CASE WHEN bfe_ft<5 THEN 1 ELSE 0 END) lt5 FROM b WHERE bfe_method='static'").round(3).to_dict("records")
d3["bfe_ft static distinct values"] = q("SELECT bfe_ft, count(*) n FROM b WHERE bfe_method='static' GROUP BY 1 ORDER BY 1").to_dict("records")
d3["bfe_ft interpolated"] = q("SELECT count(*) n, min(bfe_ft) mn, median(bfe_ft) p50, max(bfe_ft) mx, sum(CASE WHEN bfe_ft<=0 THEN 1 ELSE 0 END) le0, sum(CASE WHEN bfe_ft>30 THEN 1 ELSE 0 END) gt30, max(bfe_band_hi-bfe_band_lo) max_w, sum(CASE WHEN bfe_band_hi-bfe_band_lo>5 THEN 1 ELSE 0 END) w_gt5 FROM b WHERE bfe_method='interpolated'").round(3).to_dict("records")
d3["bfe by zone_main (static)"] = q("SELECT zone_main, count(*) n, min(bfe_ft) mn, median(bfe_ft) med, max(bfe_ft) mx FROM b WHERE bfe_method='static' GROUP BY 1 ORDER BY 2 DESC").to_dict("records")
d3["static BFE non-integer"] = one("SELECT count(*) FROM b WHERE bfe_method='static' AND bfe_ft <> round(bfe_ft)")
d3["firm_effective_date distinct"] = q("SELECT firm_effective_date, count(*) n FROM b GROUP BY 1 ORDER BY 2 DESC").to_dict("records")
d3["bfe_vintage distinct"] = q("SELECT bfe_vintage, bfe_method, count(*) n FROM b WHERE bfe_ft IS NOT NULL GROUP BY 1,2 ORDER BY 3 DESC").to_dict("records")
d3["floor_minus_bfe"] = q("SELECT ffe_class, count(*) n, min(floor_minus_bfe_ft) mn, quantile_cont(floor_minus_bfe_ft,0.01) p1, median(floor_minus_bfe_ft) p50, quantile_cont(floor_minus_bfe_ft,0.99) p99, max(floor_minus_bfe_ft) mx, sum(CASE WHEN floor_minus_bfe_ft>15 THEN 1 ELSE 0 END) gt15, sum(CASE WHEN floor_minus_bfe_ft<-10 THEN 1 ELSE 0 END) lt_m10 FROM b WHERE floor_minus_bfe_ft IS NOT NULL GROUP BY 1").round(3).to_dict("records")
d3["floor_minus_bfe > 15 sample"] = q("SELECT building_id, ffe_class, ffe_ft, ground_ft, ffh_ft, bfe_ft, bfe_method, zone_main, bfe_call, roof_ft, round(lon,5) lon, round(lat,5) lat, left(record_note,60) note FROM b WHERE floor_minus_bfe_ft>15 ORDER BY floor_minus_bfe_ft DESC LIMIT 6").to_dict("records")
d3["floor_minus_bfe < -10 sample"] = q("SELECT building_id, ffe_class, ffe_ft, ground_ft, ffh_ft, bfe_ft, bfe_method, zone_main, bfe_call, roof_ft, round(lon,5) lon, round(lat,5) lat, ffe_record_lidar_conflict FROM b WHERE floor_minus_bfe_ft<-10 ORDER BY floor_minus_bfe_ft LIMIT 6").to_dict("records")
d3["modeled ffe below ground (ffh<0)"] = q("SELECT count(*) n, sum(CASE WHEN ffh_ft < -0.5 THEN 1 ELSE 0 END) lt_m05, sum(CASE WHEN ffh_ft < -1 THEN 1 ELSE 0 END) lt_m1 FROM b WHERE ffh_class='modeled' AND ffh_ft<0").to_dict("records")
d3["roof/eave"] = q("SELECT min(roof_ft) rmin, median(roof_ft) rmed, max(roof_ft) rmax, sum(CASE WHEN roof_ft<5 THEN 1 ELSE 0 END) roof_lt5, min(eave_ft) emin, median(eave_ft) emed, max(eave_ft) emax, sum(CASE WHEN eave_ft<=0 THEN 1 ELSE 0 END) eave_le0, sum(CASE WHEN eave_ft>roof_ft THEN 1 ELSE 0 END) eave_gt_roof FROM b").round(2).to_dict("records")
d3["modeled ffh > roof_ft"] = one("SELECT count(*) FROM b WHERE ffh_class='modeled' AND ffh_ft > roof_ft")
d3["modeled ffh > eave_ft"] = one("SELECT count(*) FROM b WHERE ffh_class='modeled' AND ffh_ft > eave_ft")
d3["modeled ffh by dor_use_code top"] = q("SELECT dor_use_code, count(*) n, round(median(ffh_ft),2) med FROM b WHERE ffh_class='modeled' GROUP BY 1 ORDER BY 2 DESC LIMIT 8").to_dict("records")
d3["modeled rows with footprint>2000 or dor non-res"] = one("SELECT count(*) FROM b WHERE ffh_class='modeled' AND (footprint_area_m2>2000 OR coalesce(dor_use_code,'999')>='010')")
d3["ffh modeled by footprint area band"] = q("SELECT CASE WHEN footprint_area_m2<30 THEN '<30' WHEN footprint_area_m2<60 THEN '30-60' WHEN footprint_area_m2<120 THEN '60-120' ELSE '>=120' END band, count(*) n, round(median(ffh_ft),2) med, round(avg(CASE WHEN raised_flag THEN 1 ELSE 0 END),3) flagged FROM b WHERE ffh_class='modeled' GROUP BY 1 ORDER BY 1").to_dict("records")
out["step3"] = d3
json.dump(out, open("s2_s3_results.json","w"), indent=1, default=str)
for k,v in out.items():
    if k in ("_null distincts","vintages","step3"): continue
    print(f"{k}: {v}")
print("-- null distincts"); print(json.dumps(out["_null distincts"], default=str))
print("-- vintages"); print(json.dumps(out["vintages"], default=str, indent=0))
print("-- step3"); 
for k,v in d3.items(): print(f"{k}: {v}")
