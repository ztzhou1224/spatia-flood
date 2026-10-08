import sys, duckdb
D = sys.argv[1]; c = duckdb.connect()
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"; X = f"read_parquet('{D}/lidar/pinellas_2018/features.parquet')"
L = f"read_parquet('{D}/train/labels_12103.parquet')"; F = f"read_parquet('{D}/assemble/fdem_lag_12103.parquet')"
def q(t, s): print("---", t); print(c.sql(s))
q("(i) ground_ft < 0 / < -1 / total", f"SELECT count(ground_ft) n_ground, count(*) FILTER (WHERE ground_ft<0) lt0, count(*) FILTER (WHERE ground_ft<-1) lt_m1, round(min(ground_ft),3) mn FROM {B}")
q("(i) ground<0 by zone_main", f"SELECT zone_main, count(*) n FROM {B} WHERE ground_ft<0 GROUP BY 1 ORDER BY 2 DESC")
q("(i) ground<0: ring median above min (features)", f"SELECT count(*) n, round(quantile_cont(x.g_med-b.ground_ft,0.5),2) med_minus_min_med, round(quantile_cont(x.g_hag-x.g_lag,0.5),2) ring_range_med FROM {B} b JOIN {X} x USING(building_id) WHERE b.ground_ft<0")
# (ii) certificate rows
J = f"""(SELECT b.building_id, b.ground_ft, x.g_lag, x.g_med, x.g_p10, x.g_hag, f.cert_lag_ft FROM {B} b JOIN {L} l USING(building_id) JOIN {F} f USING(cert_objectid) JOIN {X} x USING(building_id)
        WHERE b.ground_ft IS NOT NULL AND f.cert_lag_ft BETWEEN -20 AND 200)"""
q("(ii) labels/fdem join sanity", f"SELECT (SELECT count(*) FROM {L}) labels, (SELECT count(DISTINCT building_id) FROM {L}) labels_bld, (SELECT count(*) FROM {F}) fdem, (SELECT count(*) FROM {J}) joined")
q("(ii) cert LAG minus ring min / median", f"""SELECT count(*) n, round(quantile_cont(cert_lag_ft-ground_ft,0.5),3) med_min, round(quantile_cont(cert_lag_ft-g_med,0.5),3) med_med,
   round(avg(abs(cert_lag_ft-ground_ft)),3) mae_min, round(avg(abs(cert_lag_ft-g_med)),3) mae_med, round(avg(abs(cert_lag_ft-g_p10)),3) mae_p10,
   round(avg((abs(cert_lag_ft-ground_ft)>1)::INT),3) gt1_min, round(avg((abs(cert_lag_ft-g_med)>1)::INT),3) gt1_med,
   round(avg((cert_lag_ft<ground_ft)::INT),3) cert_below_min, round(avg((cert_lag_ft>g_hag)::INT),3) cert_above_max,
   round(quantile_cont(cert_lag_ft-ground_ft,0.1),3) p10_min, round(quantile_cont(cert_lag_ft-ground_ft,0.9),3) p90_min FROM {J}""")
q("(ii) same but ground_ft == g_lag check", f"SELECT count(*) FILTER (WHERE abs(ground_ft-g_lag)>1e-9) n_diff FROM {J}")
q("(ii) ground<0 with certificate", f"SELECT count(*) n, round(quantile_cont(cert_lag_ft-ground_ft,0.5),2) med_diff, round(quantile_cont(cert_lag_ft,0.5),2) med_cert, round(quantile_cont(g_med,0.5),2) med_ringmed FROM {J} WHERE ground_ft<0")
# (iii) raised_flag
q("(iii) raised on ring range > 3 ft (modeled rows)", f"SELECT count(*) n, count(*) FILTER (WHERE raised_flag) raised, round(quantile_cont(ffh_ft,0.5),2) med_ffh FROM {B} b JOIN {X} x USING(building_id) WHERE x.g_hag-x.g_lag>3 AND ffh_class='modeled'")
q("(iii) raised on ALL rows with raised_flag not null and ring range > 3", f"SELECT count(*) n, count(*) FILTER (WHERE raised_flag) raised FROM {B} b JOIN {X} x USING(building_id) WHERE x.g_hag-x.g_lag>3 AND raised_flag IS NOT NULL")
q("(iii) raised total modeled", f"SELECT count(*) FILTER (WHERE raised_flag) raised_all, count(raised_flag) n_flag, count(*) FILTER (WHERE raised_flag AND ffh_class='modeled') raised_modeled FROM {B}")
q("(iii) record rows, ring range > 3: cert ffh>3 vs floor-ringmin>3 vs model raised", f"""SELECT count(*) n, count(*) FILTER (WHERE ffh_ft>3) cert_ffh_gt3, count(*) FILTER (WHERE ffe_ft-ground_ft>3) floor_minus_min_gt3, count(*) FILTER (WHERE raised_flag) model_raised, count(raised_flag) n_flagged_rows,
   count(*) FILTER (WHERE ffe_ft-x.g_med>3) floor_minus_med_gt3 FROM {B} b JOIN {X} x USING(building_id) WHERE x.g_hag-x.g_lag>3 AND ffh_class='record'""")
q("(iii) record rows, ring range <= 3", f"""SELECT count(*) n, count(*) FILTER (WHERE ffh_ft>3) cert_ffh_gt3, count(*) FILTER (WHERE ffe_ft-ground_ft>3) floor_minus_min_gt3, count(*) FILTER (WHERE raised_flag) model_raised FROM {B} b JOIN {X} x USING(building_id) WHERE x.g_hag-x.g_lag<=3 AND ffh_class='record'""")
q("(iii) record rows ring>3: confusion cert_ffh>3 vs model raised", f"""SELECT ffh_ft>3 cert_raised, raised_flag model_raised, count(*) n FROM {B} b JOIN {X} x USING(building_id) WHERE x.g_hag-x.g_lag>3 AND ffh_class='record' GROUP BY ALL ORDER BY 1,2""")
# (iv) sentinel
q("(iv) ground_ft within 1e-5 of -1.999865", f"SELECT count(*) n FROM {B} WHERE abs(ground_ft - (-1.999865)) < 1e-5")
q("(iv) ground_ft within 1e-3 of -2.0", f"SELECT count(*) n FROM {B} WHERE abs(ground_ft + 2.0) < 1e-3")
q("(iv) most frequent ground_ft values among ground<0", f"SELECT ground_ft, count(*) n FROM {B} WHERE ground_ft<0 GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("(iv) most frequent g_lag values overall (features)", f"SELECT g_lag, round(g_lag*1200/3937,6) metres, count(*) n FROM {X} GROUP BY 1 ORDER BY 3 DESC LIMIT 8")
q("(iv) sentinel rows: g_med / g_hag / g_p10 / g_inside on rows with g_lag within 1e-5 of -1.999865", f"SELECT count(*) n, round(quantile_cont(g_med,0.5),2) med_g_med, round(quantile_cont(g_p10,0.5),2) med_p10, round(quantile_cont(g_hag,0.5),2) med_hag, count(*) FILTER (WHERE abs(g_med-(-1.999865))<1e-5) med_also_sentinel, count(*) FILTER (WHERE abs(g_inside-(-1.999865))<1e-5) inside_also_sentinel, count(*) FILTER (WHERE abs(g_p10-(-1.999865))<1e-5) p10_also_sentinel FROM {X} WHERE abs(g_lag-(-1.999865))<1e-5")
q("(iv) values below -1.999865 (i.e. deeper than the constant)", f"SELECT count(*) n, round(min(g_lag),3) mn FROM {X} WHERE g_lag < -1.999875")
q("(iv) ground<0 rows: how many are the sentinel vs other", f"SELECT abs(ground_ft-(-1.999865))<1e-5 is_sentinel, count(*) n, count(*) FILTER (WHERE raised_flag) raised, count(*) FILTER (WHERE bfe_call='below') below FROM {B} WHERE ground_ft<0 GROUP BY 1")
q("(iv) ring_low_share on sentinel rows vs others (water returns?)", f"SELECT abs(g_lag-(-1.999865))<1e-5 s, count(*) n, round(quantile_cont(ring_low_share,0.5),3) rls_med FROM {X} WHERE g_lag IS NOT NULL GROUP BY 1")
