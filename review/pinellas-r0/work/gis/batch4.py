import sys, json, glob, duckdb, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
D = sys.argv[1]; RAW = sys.argv[2]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"; X = f"read_parquet('{D}/lidar/pinellas_2018/features.parquet')"
q(f"""SELECT count(*) n, round(quantile_cont(b.ffh_ft,0.5),2) med_record_ffh_cert_minus_certLAG, round(quantile_cont(b.ffe_ft - b.ground_ft,0.5),2) med_cert_floor_minus_ringmin,
      count(*) FILTER (WHERE b.ffh_ft > 3) n_cert_ffh_gt3, count(*) FILTER (WHERE b.ffe_ft - b.ground_ft > 3) n_ringmin_ffh_gt3, count(*) FILTER (WHERE b.raised_flag) n_model_raised
      FROM {B} b JOIN {X} x USING (building_id) WHERE x.g_hag - x.g_lag > 3 AND b.ffh_class='record'""", "record rows on lots with ring spread > 3 ft: certificate floor height vs floor minus ring min")
q(f"""SELECT count(*) n, round(quantile_cont(b.ffh_ft,0.5),2) med_record_ffh, round(quantile_cont(b.ffe_ft - b.ground_ft,0.5),2) med_floor_minus_ringmin, count(*) FILTER (WHERE b.ffh_ft > 3) n_cert_ffh_gt3, count(*) FILTER (WHERE b.ffe_ft - b.ground_ft > 3) n_ringmin_gt3, count(*) FILTER (WHERE b.raised_flag) n_model_raised
      FROM {B} b JOIN {X} x USING (building_id) WHERE x.g_hag - x.g_lag <= 3 AND b.ffh_class='record'""", "same for ring spread <= 3 ft")
q(f"SELECT count(*) FILTER (WHERE NOT in_risk_area AND touches_sfha) sfha_outside_risk, count(*) FILTER (WHERE NOT in_risk_area AND zone_main_subtype LIKE '%0.2%') pct02_outside_risk, count(*) FILTER (WHERE NOT in_risk_area AND list_contains(list_transform(zones, z -> coalesce(z.subtype, '')), '0.2 PCT ANNUAL CHANCE FLOOD HAZARD')) any02_outside FROM {B}", "risk polygon coverage of SFHA / 0.2% buildings")
# V-zone rule: C2c bottom of lowest horizontal member vs BFE, for VE above calls, from the county EC layer (navd88 native only)
lp = pd.read_parquet(f"{D}/labels_pinellas/labels_pinellas_12103.parquet", columns=["building_id","county_objectid","vertical_datum_route","diagram"])
rows = {}
for p in sorted(glob.glob(f"{RAW}/page_*.json")):
    for f in json.load(open(p))["features"]:
        a = f["attributes"]; rows[a["OBJECTID"]] = (a.get("C2C_BOTTOM_LOW_STRUCT_EL"), a.get("C2A_TOP_BOTTOM_FLOOR_EL"), a.get("C2B_TOP_NEXT_HIGHER_FL_EL"), a.get("VERTICAL_DATUM"), a.get("B8_FLOOD_ZONE"))
lp["c2c"] = lp.county_objectid.map(lambda o: rows.get(o, (None,))[0])
lp["c2c"] = pd.to_numeric(lp.c2c, errors="coerce")
lp["c2a"] = pd.to_numeric(lp.county_objectid.map(lambda o: rows.get(o, (None,None))[1]), errors="coerce")
lp["c2b"] = pd.to_numeric(lp.county_objectid.map(lambda o: rows.get(o, (None,None,None))[2]), errors="coerce")
lp["b8"] = lp.county_objectid.map(lambda o: rows.get(o, (None,)*5)[4])
b = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","zones","bfe_ft","bfe_call","ffe_ft","ffe_class","floor_minus_bfe_ft"]).to_pandas()
b["any_ve"] = b.zones.map(lambda L: L is not None and any(e["zone"] == "VE" for e in L))
j = b[b.any_ve & (b.bfe_call == "above")].merge(lp, on="building_id")
print("VE 'above' buildings with a county certificate:", len(j), "; navd88_native:", int((j.vertical_datum_route == "navd88_native").sum()), "; with C2c filled:", int(j.c2c.notna().sum()))
k = j[(j.vertical_datum_route == "navd88_native") & j.c2c.notna() & (j.c2c > -20) & (j.c2c < 200)]
print("county B8 zone of those:", k.b8.value_counts().head(5).to_dict())
print("C2c (bottom of lowest horizontal member) below our BFE:", int((k.c2c < k.bfe_ft).sum()), "of", len(k), "; C2c - BFE median", round(float((k.c2c - k.bfe_ft).median()),2) if len(k) else None, "; our floor_minus_bfe median", round(float(k.floor_minus_bfe_ft.median()),2) if len(k) else None)
print("C2c vs our ffe: median (ffe - c2c) ft", round(float((k.ffe_ft - k.c2c).median()),2) if len(k) else None)
# whole VE population with a native certificate and C2c: how often C2c < BFE while floor >= BFE
j2 = b[b.any_ve & b.bfe_ft.notna()].merge(lp, on="building_id")
k2 = j2[(j2.vertical_datum_route == "navd88_native") & j2.c2c.notna() & (j2.c2c > -20) & (j2.c2c < 200) & j2.ffe_ft.notna()]
print("VE with native county cert + C2c:", len(k2), "; floor >= BFE but C2c < BFE:", int(((k2.ffe_ft >= k2.bfe_ft) & (k2.c2c < k2.bfe_ft)).sum()), "; our call distribution there:", k2[(k2.ffe_ft >= k2.bfe_ft) & (k2.c2c < k2.bfe_ft)].bfe_call.value_counts().to_dict())
