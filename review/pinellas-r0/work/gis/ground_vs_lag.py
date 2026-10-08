import sys, duckdb
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
L = f"read_parquet('{D}/train/labels_12103.parquet')"
F = f"read_parquet('{D}/assemble/fdem_lag_12103.parquet')"
X = f"read_parquet('{D}/lidar/pinellas_2018/features.parquet')"
q(f"""WITH j AS (SELECT b.building_id, b.ground_ft, x.g_lag, x.g_p10, x.g_med, x.g_hag, x.g_inside, x.g_far, f.cert_lag_ft, l.match, l.diagram, b.ffe_class
      FROM {B} b JOIN {L} l USING (building_id) JOIN {F} f USING (cert_objectid) JOIN {X} x USING (building_id)
      WHERE b.ground_ft IS NOT NULL AND f.cert_lag_ft BETWEEN -20 AND 200)
      SELECT count(*) n,
        round(quantile_cont(cert_lag_ft - ground_ft, 0.5),3) med_min, round(quantile_cont(cert_lag_ft - ground_ft, 0.1),3) p10_min, round(quantile_cont(cert_lag_ft - ground_ft, 0.9),3) p90_min,
        round(avg((abs(cert_lag_ft - ground_ft) > 1)::INT),3) share_gt1ft_min, round(avg((abs(cert_lag_ft - ground_ft) > 2)::INT),3) share_gt2ft_min,
        round(quantile_cont(cert_lag_ft - g_p10, 0.5),3) med_p10, round(avg((abs(cert_lag_ft - g_p10) > 1)::INT),3) share_gt1_p10,
        round(quantile_cont(cert_lag_ft - g_med, 0.5),3) med_med, round(quantile_cont(cert_lag_ft - g_med, 0.1),3) p10_med, round(quantile_cont(cert_lag_ft - g_med, 0.9),3) p90_med, round(avg((abs(cert_lag_ft - g_med) > 1)::INT),3) share_gt1_med,
        round(quantile_cont(cert_lag_ft - g_inside, 0.5),3) med_inside, round(avg((abs(cert_lag_ft - g_inside) > 1)::INT),3) share_gt1_inside,
        round(quantile_cont(cert_lag_ft - g_hag, 0.5),3) med_hag,
        round(avg(abs(cert_lag_ft - ground_ft)),3) mae_min, round(avg(abs(cert_lag_ft - g_med)),3) mae_med, round(avg(abs(cert_lag_ft - g_p10)),3) mae_p10, round(avg(abs(cert_lag_ft - g_inside)),3) mae_inside
      FROM j""", "certificate LAG minus lidar ring stats (all matched certificates with a LAG)")
q(f"""WITH j AS (SELECT b.ground_ft, x.g_med, f.cert_lag_ft, l.match
      FROM {B} b JOIN {L} l USING (building_id) JOIN {F} f USING (cert_objectid) JOIN {X} x USING (building_id)
      WHERE b.ground_ft IS NOT NULL AND f.cert_lag_ft BETWEEN -20 AND 200)
      SELECT match, count(*) n, round(quantile_cont(cert_lag_ft - ground_ft, 0.5),3) med_min, round(avg((abs(cert_lag_ft - ground_ft) > 1)::INT),3) gt1_min, round(quantile_cont(cert_lag_ft - g_med, 0.5),3) med_med, round(avg((abs(cert_lag_ft - g_med) > 1)::INT),3) gt1_med FROM j GROUP BY ALL""", "by match kind")
q(f"""WITH j AS (SELECT b.ground_ft, x.g_med, x.g_hag, x.g_p10, f.cert_lag_ft
      FROM {B} b JOIN {L} l USING (building_id) JOIN {F} f USING (cert_objectid) JOIN {X} x USING (building_id)
      WHERE b.ground_ft IS NOT NULL AND f.cert_lag_ft BETWEEN -20 AND 200)
      SELECT round(quantile_cont(g_hag - ground_ft, 0.5),2) ring_range_med, round(quantile_cont(g_hag - ground_ft, 0.9),2) ring_range_p90, round(quantile_cont(g_med - ground_ft, 0.5),2) med_minus_min_med,
      round(avg((cert_lag_ft < ground_ft)::INT),3) share_cert_below_ringmin, round(avg((cert_lag_ft > g_hag)::INT),3) share_cert_above_ringmax FROM j""", "ring spread and where the certificate LAG sits")
# ring_range on the whole population
q(f"SELECT round(quantile_cont(g_hag - g_lag, 0.5),2) med, round(quantile_cont(g_hag - g_lag, 0.9),2) p90, round(quantile_cont(g_hag - g_lag, 0.99),2) p99, count(*) FILTER (WHERE g_hag - g_lag > 3) n_gt3ft, count(*) FROM {X} WHERE g_lag IS NOT NULL", "ring max-min spread, all risk-area buildings")
