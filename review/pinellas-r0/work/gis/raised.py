import sys, duckdb
D = sys.argv[1]; c = duckdb.connect()
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"; X = f"read_parquet('{D}/lidar/pinellas_2018/features.parquet')"
print(c.sql(f"""SELECT count(*) n, count(*) FILTER (WHERE b.raised_flag) raised, round(quantile_cont(b.ffh_ft,0.5),2) med_ffh_modeled FROM {B} b WHERE b.ground_ft < 0 AND b.ffh_class='modeled'"""))
print(c.sql(f"""SELECT count(*) n, count(*) FILTER (WHERE b.raised_flag) raised, round(quantile_cont(b.ffh_ft,0.5),2) med_ffh FROM {B} b JOIN {X} x USING (building_id) WHERE x.g_hag - x.g_lag > 3 AND b.ffh_class='modeled'"""))
print(c.sql(f"""SELECT round(quantile_cont(ffh_ft,0.5),2) med_ffh_all_modeled, count(*) FILTER (WHERE raised_flag) raised_all FROM {B} WHERE ffh_class='modeled'"""))
# record ffh vs modeled ffh definitions: on record buildings, cert floor - cert LAG vs cert floor - ground_ft
print(c.sql(f"""SELECT count(*) n, round(quantile_cont(ffe_ft - ground_ft - ffh_ft, 0.5),3) med_offset_ringmin_vs_certLAG, round(quantile_cont(ffe_ft - ground_ft - ffh_ft, 0.9),3) p90 FROM {B} WHERE ffh_class='record' AND ground_ft IS NOT NULL"""))
