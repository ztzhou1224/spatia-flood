import sys, duckdb
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
q(f"SELECT count(ground_ft) n, round(min(ground_ft),2) mn, round(max(ground_ft),2) mx, round(quantile_cont(ground_ft,0.5),2) med, count(*) FILTER (WHERE ground_ft < 0) n_lt0, count(*) FILTER (WHERE ground_ft < -1) n_lt_m1, count(*) FILTER (WHERE ground_ft > 60) n_gt60, count(*) FILTER (WHERE ground_ft > 100) n_gt100 FROM {B}", "ground_ft range")
q(f"SELECT round(lat,2) latb, round(min(ground_ft),1) mn, round(max(ground_ft),1) mx, count(ground_ft) n FROM {B} WHERE ground_ft > 60 GROUP BY ALL ORDER BY latb", "where ground > 60 ft")
q(f"SELECT building_id, lon, lat, ground_ft, zone_main, address FROM {B} WHERE ground_ft < 0 ORDER BY ground_ft LIMIT 10", "lowest ground rows")
q(f"SELECT zone_main, count(*) n, round(quantile_cont(ground_ft,0.5),2) med_ground FROM {B} WHERE ground_ft < 0 GROUP BY ALL ORDER BY n DESC", "ground<0 by zone")
q(f"SELECT ffe_class, count(ffe_ft) n, round(min(ffe_ft),2) mn, round(max(ffe_ft),2) mx, round(quantile_cont(ffe_ft,0.5),2) med, count(*) FILTER (WHERE ffe_ft < ground_ft - 1) n_ffe_below_ground_m1, count(*) FILTER (WHERE ffe_ft < ground_ft) n_ffe_below_ground FROM {B} WHERE ffe_ft IS NOT NULL GROUP BY ALL", "ffe_ft range by class")
q(f"SELECT ffh_class, count(ffh_ft) n, round(min(ffh_ft),2) mn, round(max(ffh_ft),2) mx, round(quantile_cont(ffh_ft,0.5),2) med, count(*) FILTER (WHERE ffh_ft < -1) n_lt_m1, count(*) FILTER (WHERE ffh_ft < 0) n_lt0 FROM {B} WHERE ffh_ft IS NOT NULL GROUP BY ALL", "ffh_ft range")
q(f"SELECT building_id, ground_ft, ffe_ft, ffh_ft, ffe_class, ffe_record_lidar_conflict, bfe_call FROM {B} WHERE ffe_ft < ground_ft - 1 ORDER BY ffe_ft - ground_ft LIMIT 10", "ffe < ground - 1 rows")
q(f"SELECT count(*) n, count(*) FILTER (WHERE ffe_class='record' AND ffe_ft - ground_ft < -1) rec_viol, count(*) FILTER (WHERE ffe_class='record' AND ffe_ft - ground_ft > 30) rec_hi FROM {B} WHERE ffe_class='record'", "record FFE vs ground screen")
q(f"SELECT round(quantile_cont(ffe_ft - ground_ft, 0.5),2) med, round(quantile_cont(ffe_ft - ground_ft,0.05),2) p05, round(quantile_cont(ffe_ft - ground_ft,0.95),2) p95 FROM {B} WHERE ffe_class='record' AND ground_ft IS NOT NULL", "record FFE minus lidar ground")
q(f"SELECT round(quantile_cont(bfe_ft,0.5),1) med, min(bfe_ft), max(bfe_ft), count(*) FILTER (WHERE bfe_ft > ground_ft + 15) n_bfe_15ft_above_ground FROM {B} WHERE bfe_ft IS NOT NULL AND ground_ft IS NOT NULL", "bfe range")
