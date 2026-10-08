import sys, duckdb
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
X = f"read_parquet('{D}/lidar/pinellas_2018/features.parquet')"
q(f"""SELECT count(*) n, round(quantile_cont(x.g_med - b.ground_ft,0.5),2) med_minus_min_med, round(quantile_cont(x.g_hag - b.ground_ft,0.5),2) ring_range_med,
       count(*) FILTER (WHERE x.g_med >= 0) n_med_ge0, count(*) FILTER (WHERE b.ffh_class='modeled') modeled, count(*) FILTER (WHERE b.bfe_call='below') below, count(*) FILTER (WHERE b.bfe_call='above') above, count(*) FILTER (WHERE b.bfe_call='too_close') too_close
       FROM {B} b JOIN {X} x USING (building_id) WHERE b.ground_ft < 0""", "ground<0 buildings: ring median vs min, calls")
q(f"""SELECT count(*) n, count(*) FILTER (WHERE x.g_hag - x.g_lag > 3) spread_gt3, count(*) FILTER (WHERE x.g_hag - x.g_lag > 3 AND b.bfe_call='below') spread_gt3_below, count(*) FILTER (WHERE x.g_hag - x.g_lag > 3 AND b.bfe_call='below' AND b.ffe_class='modeled' AND b.ffe_ft + (x.g_med - x.g_lag) >= b.bfe_ft) below_flips_if_median
       FROM {B} b JOIN {X} x USING (building_id) WHERE b.touches_sfha AND b.ground_ft IS NOT NULL""", "SFHA buildings: ring spread > 3 ft and below calls sensitive to ring choice")
q(f"""SELECT count(*) FILTER (WHERE bfe_call='below') below, count(*) FILTER (WHERE bfe_call='below' AND ffe_class='modeled' AND floor_minus_bfe_band_hi > -1) below_within_1ft_band, count(*) FILTER (WHERE bfe_call='below' AND ffe_class='modeled' AND floor_minus_bfe_ft > -2) below_point_within_2ft FROM {B}""", "how marginal are the below calls")
q(f"SELECT building_id, lon, lat, zone_main, sfha_share, bfe_ft, bfe_method, bfe_band_lo, bfe_band_hi, ground_ft, bfe_source FROM {B} WHERE bfe_ft > 40 ORDER BY bfe_ft DESC LIMIT 10", "BFE > 40 ft rows")
q(f"SELECT building_id, lon, lat, zone_main, bfe_ft, bfe_method, ground_ft, ffe_ft, bfe_call, left(bfe_source, 160) src FROM {B} WHERE bfe_ft > ground_ft + 15 ORDER BY bfe_ft - ground_ft DESC", "BFE > ground + 15 rows")
q(f"SELECT dfirm_id, source_type, count(*), min(elev_ft_navd88_ft), max(elev_ft_navd88_ft) FROM read_parquet('{D}/assemble/bfe_lines_12103.parquet') GROUP BY ALL ORDER BY 1,2", "lines by dfirm")
q(f"SELECT dfirm_id, count(*) FROM read_parquet('{D}/assemble/bfe_lines_12103.parquet') WHERE elev_ft_navd88_ft > 100 GROUP BY ALL", "lines > 100 ft by dfirm")
# AO rows with static BFE: which polygons give it
q(f"SELECT zone_main, sfha_share, zones, bfe_ft, bfe_method FROM {B} WHERE zone_main='AO' AND bfe_ft IS NOT NULL LIMIT 6", "AO with BFE: zone lists")
q(f"""SELECT count(*) n, count(*) FILTER (WHERE bfe_method='static') n_static, count(*) FILTER (WHERE bfe_call='below') below, count(*) FILTER (WHERE bfe_call='above') above, count(*) FILTER (WHERE bfe_call='too_close') too_close FROM {B} WHERE zone_main='AO'""", "AO calls")
q(f"""SELECT count(*) n, count(bfe_ft) n_bfe, count(*) FILTER (WHERE bfe_call IN ('above','below')) decided FROM {B} WHERE list_contains(list_transform(zones, z -> z.zone), 'AO')""", "any-AO buildings")
q(f"""SELECT count(*) n, count(bfe_ft) n_bfe FROM {B} WHERE list_contains(list_transform(zones, z -> z.zone), 'AH')""", "any-AH buildings")
# VE above calls margin
q(f"SELECT bfe_call_basis, count(*) n, count(*) FILTER (WHERE floor_minus_bfe_ft < 1.0) within_1ft, count(*) FILTER (WHERE floor_minus_bfe_ft < 2.0) within_2ft FROM {B} WHERE bfe_call='above' AND list_contains(list_transform(zones, z -> z.zone), 'VE') GROUP BY ALL", "VE above calls: margin above BFE (V-zone rule uses the lowest horizontal member)")
# Multi-polygon BFE: highest vs largest-share
