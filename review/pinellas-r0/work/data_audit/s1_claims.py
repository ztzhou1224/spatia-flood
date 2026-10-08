"""Step 1: claim-by-claim verification against the local table."""
import sys, json, duckdb, hashlib
import pandas as pd, numpy as np
A = sys.argv[1]  # assemble dir
B = f"{A}/buildings_12103.parquet"; P = f"{A}/parcels_12103.parquet"
con = duckdb.connect(); con.execute("LOAD spatial")
def q(sql): return con.execute(sql).fetchall()
def one(sql): return con.execute(sql).fetchone()[0]
rows = []
def claim(src, name, claimed, measured, tol=0):
    ok = (abs(float(claimed) - float(measured)) <= tol) if isinstance(claimed,(int,float)) else (claimed == measured)
    rows.append((src, name, claimed, measured, "PASS" if ok else "FAIL"))
con.execute(f"CREATE VIEW b AS SELECT * EXCLUDE (geometry) FROM read_parquet('{B}')")
con.execute(f"CREATE VIEW p AS SELECT * FROM read_parquet('{P}')")
# sha
h = hashlib.sha256(open(B,'rb').read()).hexdigest()
claim("§10","sha256 prefix/suffix ecea7173…a6d93b7", True, h.startswith("ecea7173") and h.endswith("a6d93b7"))
rows.append(("§10","sha256 full","ecea7173…a6d93b7",h,"info"))
claim("§8/§9/json","rows (county buildings)", 372764, one("SELECT count(*) FROM b"))
claim("check.txt","columns incl geometry (check says 96)", 96, one(f"SELECT count(*) FROM (DESCRIBE SELECT * FROM read_parquet('{B}'))"))
claim("§8/json","in_risk_area", 290540, one("SELECT count(*) FROM b WHERE in_risk_area"))
claim("§8/json","touches_sfha", 92243, one("SELECT count(*) FROM b WHERE touches_sfha"))
claim("§8","static BFE (bfe_method='static') 83,024", 83024, one("SELECT count(*) FROM b WHERE bfe_method='static'"))
claim("json","bfe_ft not null (json 'bfe_static' 88,274)", 88274, one("SELECT count(*) FROM b WHERE bfe_ft IS NOT NULL"))
claim("§8","interpolated BFE 5,250", 5250, one("SELECT count(*) FROM b WHERE bfe_method='interpolated'"))
claim("§8","bfe_null not_determinable 567", 567, one("SELECT count(*) FROM b WHERE bfe_null='not_determinable'"))
claim("§8","bfe interpolation no_coverage 59 (bfe_null no_coverage among SFHA non-A-only)", 59, one("SELECT count(*) FROM b WHERE bfe_null='no_coverage' AND touches_sfha AND bfe_call_null='no_coverage' AND zone_main NOT IN ('A')"))
claim("json","bfe_null no_coverage 3,402", 3402, one("SELECT count(*) FROM b WHERE bfe_null='no_coverage'"))
claim("json","bfe_null not_applicable 280,521", 280521, one("SELECT count(*) FROM b WHERE bfe_null='not_applicable'"))
claim("§8","median interpolated band 1.4", 1.4, one("SELECT round(median(bfe_band_hi-bfe_band_lo),2) FROM b WHERE bfe_method='interpolated'"), 0.01)
# floor
claim("§8 (handoff)","ffh record 7,482", 7482, one("SELECT count(*) FROM b WHERE ffh_class='record'"))
claim("json run13","ffh record 7,427", 7427, one("SELECT count(*) FROM b WHERE ffh_class='record'"))
claim("§8 (handoff)","ffh modeled 240,305", 240305, one("SELECT count(*) FROM b WHERE ffh_class='modeled'"))
claim("json run13","ffh modeled 240,356", 240356, one("SELECT count(*) FROM b WHERE ffh_class='modeled'"))
claim("§8 (handoff)","ffh null 124,949", 124949, one("SELECT count(*) FROM b WHERE ffh_ft IS NULL"))
claim("json run13","ffh null 124,981", 124981, one("SELECT count(*) FROM b WHERE ffh_ft IS NULL"))
claim("json","ffe record (floor.record 7,461)", 7461, one("SELECT count(*) FROM b WHERE ffe_class='record'"))
claim("json","ffh_null not_determinable 36", 36, one("SELECT count(*) FROM b WHERE ffh_null='not_determinable'"))
claim("json","ffh_null not_evaluated 121,907", 121907, one("SELECT count(*) FROM b WHERE ffh_null='not_evaluated'"))
claim("json","ffh_null no_coverage 3,038", 3038, one("SELECT count(*) FROM b WHERE ffh_null='no_coverage'"))
claim("§8","median modeled ffh band 2.15", 2.15, one("SELECT round(median(ffh_band_hi-ffh_band_lo),2) FROM b WHERE ffh_class='modeled'"), 0.005)
claim("§8 (handoff)","ffe_record_lidar_conflict 298", 298, one("SELECT count(*) FROM b WHERE ffe_record_lidar_conflict"))
claim("json run13","record_lidar_conflict 300", 300, one("SELECT count(*) FROM b WHERE ffe_record_lidar_conflict"))
claim("§9/json","certificates rejected vs lidar 54 (record_note like 'not used')", 54, one("SELECT count(*) FROM b WHERE record_note LIKE '%not used%'"))
claim("json","record_ffh_not_usable 34", 34, one("SELECT count(*) FROM b WHERE ffe_class='record' AND ffh_class IS NULL"))
claim("json","record_without_cert_lag 32", 32, one("SELECT count(*) FROM b WHERE record_note LIKE 'certificate has no usable lowest adjacent grade%'"))
claim("json","model_eligible 247,653 (model_version not null)", 247653, one("SELECT count(*) FROM b WHERE model_version IS NOT NULL"))
claim("json","raised_flag True 41,918", 41918, one("SELECT count(*) FROM b WHERE raised_flag"))
claim("json","raised_flag False 205,735", 205735, one("SELECT count(*) FROM b WHERE raised_flag = false"))
claim("json","raised_flag null 125,111", 125111, one("SELECT count(*) FROM b WHERE raised_flag IS NULL"))
claim("§8","record_vintage_note set (261 LLM estimates; §8 says 264 none + 1 bad)", 261, one("SELECT count(*) FROM b WHERE record_vintage_note IS NOT NULL"))
# calls
for k,v in {"above":7796,"below":33032,"too_close":35973}.items():
    claim("§8 (handoff)", f"bfe_call {k} {v}", v, one(f"SELECT count(*) FROM b WHERE bfe_call='{k}'"))
claim("§8 (handoff)","bfe_call null 15,442", 15442, one("SELECT count(*) FROM b WHERE bfe_call IS NULL"))
for k,v in {"above":7767,"below":33039,"too_close":35994,"not_applicable":280521}.items():
    claim("json run13", f"bfe_call {k} {v}", v, one(f"SELECT count(*) FROM b WHERE bfe_call='{k}'"))
claim("json run13","bfe_call null 15,443", 15443, one("SELECT count(*) FROM b WHERE bfe_call IS NULL"))
for k,v in {"modeled_band":65725,"record":6161,"modeled_band+interpolated_bfe":4365,"record+interpolated_bfe":303,"record_lidar_conflict":245,"record_lidar_conflict+interpolated_bfe":1}.items():
    claim("json", f"bfe_call_basis {k} {v}", v, one(f"SELECT count(*) FROM b WHERE bfe_call_basis='{k}'"))
for k,v in {"not_evaluated":10512,"no_coverage":4363,"not_determinable":568}.items():
    claim("json", f"bfe_call_null {k} {v}", v, one(f"SELECT count(*) FROM b WHERE bfe_call_null='{k}'"))
claim("§8","SFHA decided share 44.3% (json 0.442)", 0.442, round(one("SELECT avg(CASE WHEN bfe_call IN ('above','below') THEN 1 ELSE 0 END) FROM b WHERE touches_sfha AND in_risk_area"),3), 0.0015)
claim("json","sfha_buildings (touches & risk) 92,243", 92243, one("SELECT count(*) FROM b WHERE touches_sfha AND in_risk_area"))
# zones
claim("§8/06","touches_sfha with share < 1%: 1,240", 1240, one("SELECT count(*) FROM b WHERE sfha_share > 0 AND sfha_share < 0.01"))
claim("json","no_zone_polygon 12 (zones_null)", 12, one("SELECT count(*) FROM b WHERE zones_null IS NOT NULL"))
claim("json","share_sum_over_1.01: 0", 0, one("SELECT count(*) FROM (SELECT list_sum(list_transform(zones, z -> z.share)) s FROM b WHERE zones IS NOT NULL) WHERE s > 1.01"))
# lidar
claim("json","ground_ft not null (lag 290,540)", 290540, one("SELECT count(*) FROM b WHERE ground_ft IS NOT NULL"))
claim("json","roof_ft not null 280,361", 280361, one("SELECT count(*) FROM b WHERE roof_ft IS NOT NULL"))
claim("json","eave_ft not null 280,025", 280025, one("SELECT count(*) FROM b WHERE eave_ft IS NOT NULL"))
claim("json","roof_null not_evaluated 84,598", 84598, one("SELECT count(*) FROM b WHERE roof_null='not_evaluated'"))
claim("json","roof_null not_determinable 7,805", 7805, one("SELECT count(*) FROM b WHERE roof_null='not_determinable'"))
claim("json","eave_null not_determinable 8,141", 8141, one("SELECT count(*) FROM b WHERE eave_null='not_determinable'"))
claim("json","buildings_per_workunit 372,764", 372764, one("SELECT count(*) FROM b WHERE lidar_workunit='FL_Peninsular_Pinellas_2018'"))
# parcels
claim("json","buildings_with_parcel 368,800", 368800, one("SELECT count(*) FROM b WHERE parcel_key IS NOT NULL"))
claim("json","buildings_on_residential_parcel 315,459", 315459, one("SELECT count(*) FROM b WHERE parcel_key IS NOT NULL AND coalesce(dor_use_code,'999') < '010'"))
claim("json","risk_buildings_on_residential_parcel 248,073", 248073, one("SELECT count(*) FROM b WHERE in_risk_area AND parcel_key IS NOT NULL AND coalesce(dor_use_code,'999') < '010'"))
claim("json","parcel rows 432,360", 432360, one("SELECT count(*) FROM p"))
claim("json","parcel distinct geom_group 315,982", 315982, one("SELECT count(DISTINCT geom_group) FROM p"))
claim("json","parcels with_building 414,888", 414888, one("SELECT count(*) FROM p WHERE buildings > 0"))
claim("json","parcels any_building_below_bfe 56,619", 56619, one("SELECT count(*) FROM p WHERE any_building_below_bfe"))
claim("json","buildings_spanning_parcels 29,992", 29992, one("SELECT count(*) FROM b WHERE spans_parcels"))
# addresses
ad = dict(q("SELECT coalesce(address_source,'none'), count(*) FROM b GROUP BY 1"))
for k,v in {"overture_addresses (point in footprint)":298440,"fl_parcels situs address (DOR NAL)":73453,"geocodio reverse (Pinellas (Pinellas County), rooftop)":692,"none":144,"geocodio reverse (OpenStreetMap Contributors, nearest_street)":6}.items():
    claim("json", f"address_source {k} {v}", v, ad.get(k,0))
claim("§8","Geocodio 727 lookups (rows with geocodio address_source)", 727, one("SELECT count(*) FROM b WHERE address_source LIKE 'geocodio%'"))
claim("§8","Geocodio 717 rooftop", 717, one("SELECT count(*) FROM b WHERE address_source LIKE 'geocodio%rooftop%'"))
gc = pd.read_parquet(f"{A}/geocodio_12103.parquet")
rows.append(("§8","geocodio cache rows", 727, len(gc), "PASS" if len(gc)==727 else "FAIL"))
claim("json","addresses_missing_in_risk_area 0", 0, one("SELECT count(*) FROM b WHERE address IS NULL AND in_risk_area"))
# 06: 1,193 centroids outside footprint
claim("06","centroids outside own footprint 1,193", 1193, one(f"SELECT count(*) FROM (SELECT ST_Contains(geometry, ST_Point(lon,lat)) c FROM read_parquet('{B}')) WHERE NOT c"))
# gate recheck in metadata
import pyarrow.parquet as pq
md = json.loads(pq.read_schema(B).metadata[b"spatia_flood"])
claim("json/metadata","metadata gate MAE 1.039", 1.039, md["gate"]["MAE"]); claim("json/metadata","metadata gate coverage 0.918", 0.918, md["gate"]["coverage"])
claim("06","model_version E-lgbm-12103-<12 hex>", "E-lgbm-12103-62f502979c3b", one("SELECT DISTINCT model_version FROM b WHERE model_version IS NOT NULL"))
# provenance distincts
rows.append(("info","distinct release", "", str(q("SELECT DISTINCT release FROM b")), "info"))
rows.append(("info","distinct provider", "", str(q("SELECT DISTINCT provider FROM b")), "info"))
rows.append(("info","distinct footprint_release", "", str(q("SELECT DISTINCT footprint_release FROM b")), "info"))
df = pd.DataFrame(rows, columns=["source","claim","claimed","measured","result"])
pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 80); pd.set_option("display.max_rows", 500)
print(df.to_string())
df.to_csv("claims.csv", index=False)
print("\nFAILS:\n", df[df.result=="FAIL"].to_string())
