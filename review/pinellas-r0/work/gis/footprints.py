import sys, duckdb
D = sys.argv[1]
c = duckdb.connect(); c.execute("INSTALL spatial; LOAD spatial")
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
q(f"SELECT count(*) n, count(*) FILTER (WHERE NOT ST_Contains(geometry, ST_Point(lon, lat))) centroid_outside, count(*) FILTER (WHERE NOT ST_Contains(geometry, ST_Centroid(geometry))) centroid2_outside FROM {B}", "centroid outside own footprint")
q(f"SELECT round(quantile_cont(footprint_area_m2,0.01),1) p01, round(quantile_cont(footprint_area_m2,0.1),1) p10, round(quantile_cont(footprint_area_m2,0.5),1) p50, round(quantile_cont(footprint_area_m2,0.9),1) p90, round(quantile_cont(footprint_area_m2,0.99),1) p99, round(max(footprint_area_m2),0) mx, count(*) FILTER (WHERE footprint_area_m2 > 2000) n_gt2000, count(*) FILTER (WHERE footprint_area_m2 > 2000 AND in_risk_area) n_gt2000_risk, count(*) FILTER (WHERE footprint_area_m2 < 20) n_lt20, count(*) FILTER (WHERE footprint_area_m2 < 20 AND in_risk_area) n_lt20_risk FROM {B}", "footprint area")
q(f"SELECT roof_null, count(*) FROM {B} WHERE footprint_area_m2 > 2000 AND in_risk_area GROUP BY ALL", ">2000 m2 roof_null")
q(f"SELECT parcels_at_centroid, count(*) n, count(*) FILTER (WHERE ffh_class='modeled') modeled, count(*) FILTER (WHERE bfe_call IN ('above','below')) decided FROM {B} GROUP BY ALL ORDER BY 1", "parcels_at_centroid")
q(f"SELECT spans_parcels, count(*) FROM {B} GROUP BY ALL", "spans_parcels")
q(f"SELECT ST_GeometryType(geometry) t, count(*) FROM {B} GROUP BY ALL", "geometry types")
q(f"SELECT count(*) FILTER (WHERE NOT ST_IsValid(geometry)) invalid FROM {B}", "invalid footprints")
# area check: compare EPSG:3086 area vs 6442 area for a sample
q(f"""SELECT round(avg(a3086/a6442),6) ratio_mean, round(min(a3086/a6442),6) mn, round(max(a3086/a6442),6) mx FROM (
   SELECT footprint_area_m2 a3086, ST_Area(ST_Transform(geometry, 'EPSG:4326', 'EPSG:6442', always_xy := true)) a6442 FROM {B} USING SAMPLE 20000)""", "area 3086 vs 6442 (sample)")
