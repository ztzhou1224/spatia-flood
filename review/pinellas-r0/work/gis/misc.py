import sys, duckdb, json
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
X = f"read_parquet('{D}/lidar/pinellas_2018/features.parquet')"
L = f"read_parquet('{D}/train/labels_12103.parquet')"
F = f"read_parquet('{D}/assemble/fdem_lag_12103.parquet')"
Z = f"read_parquet('{D}/assemble/zones_12103_raw.parquet')"
q(f"SELECT firm_effective_date, round(min(lon),3) lon0, round(max(lon),3) lon1, round(min(lat),3) lat0, round(max(lat),3) lat1, count(*) n, count(*) FILTER (WHERE touches_sfha) sfha FROM {B} GROUP BY ALL", "FIRM date geography")
q(f"SELECT firm_panel_eff_date_max d, fld_zone, zone_subty, count(*) FROM {Z} WHERE dfirm_id='12103C' AND firm_panel_eff_date_max < DATE '2021-01-01' GROUP BY ALL ORDER BY 1, 4 DESC", "pre-2021 Pinellas polygons by zone")
q(f"""SELECT count(*) n, round(quantile_cont(f.cert_lag_ft - b.ground_ft, 0.5),2) med_certlag_minus_ground, round(quantile_cont(f.cert_lag_ft,0.5),2) med_cert_lag, round(quantile_cont(b.ground_ft,0.5),2) med_ground, round(quantile_cont(x.g_med,0.5),2) med_ring_median
       FROM {B} b JOIN {L} l USING (building_id) JOIN {F} f USING (cert_objectid) JOIN {X} x USING (building_id) WHERE b.ground_ft < 0 AND f.cert_lag_ft BETWEEN -20 AND 200""", "ground<0 buildings that have a certificate: certificate LAG vs ring min / median")
q(f"""SELECT count(*) n, round(quantile_cont(ffe_ft,0.5),2) med_ffe, count(*) FILTER (WHERE ffe_ft < 1) n_ffe_lt1ft, count(*) FILTER (WHERE ffe_ft < 1 AND bfe_call='below') below_lt1 FROM {B} WHERE ground_ft < 0 AND ffe_class='modeled'""", "ground<0 modeled floors")
q(f"""SELECT count(*) n_modeled_below, count(*) FILTER (WHERE ffe_ft < 2.0) n_ffe_lt2 FROM {B} WHERE ffe_class='modeled' AND bfe_call='below'""", "modeled below calls with FFE under 2 ft NAVD88 (below typical MHHW+freeboard; implausible for a lived-in floor)")
q(f"SELECT building_id, round(ground_ft,2) g, round(bfe_ft,1) bfe, round(ffe_ft,2) ffe, bfe_call, zone_main, round(sfha_share,3) sh FROM {B} WHERE bfe_ft > ground_ft + 15 ORDER BY bfe_ft - ground_ft DESC", "BFE > ground+15 detail")
q(f"""SELECT count(*) FILTER (WHERE parcels_at_centroid > 1) stacked, count(*) FILTER (WHERE parcels_at_centroid > 1 AND ffh_class='modeled') stacked_modeled, count(*) FILTER (WHERE parcels_at_centroid > 1 AND bfe_call='below') stacked_below, count(*) FILTER (WHERE parcels_at_centroid > 1 AND bfe_call='above') stacked_above, count(*) FILTER (WHERE parcels_at_centroid > 1 AND touches_sfha) stacked_sfha FROM {B}""", "stacked parcels (condos)")
q(f"SELECT dor_use_code, count(*) n, count(*) FILTER (WHERE ffh_class='modeled') modeled, count(*) FILTER (WHERE bfe_call='below') below FROM {B} WHERE parcels_at_centroid > 1 GROUP BY ALL ORDER BY n DESC LIMIT 6", "stacked by DOR use")
q(f"SELECT count(*) FILTER (WHERE zones_null='no_coverage') no_zone FROM {B}", "no zone polygon")
q(f"SELECT bfe_source FROM {B} WHERE bfe_method='static' AND bfe_source NOT LIKE '%DFIRM 12103C%' LIMIT 3", "static BFE from non-Pinellas DFIRM")
q(f"SELECT count(*) FROM {B} WHERE bfe_method='static' AND bfe_source NOT LIKE '%DFIRM 12103C%'", "count static BFE from non-Pinellas DFIRM")
q(f"SELECT sfha_tf, fld_zone, count(*) FROM {Z} WHERE dfirm_id <> '12103C' GROUP BY ALL ORDER BY 3 DESC LIMIT 8", "non-Pinellas DFIRM polygons in the read")
