import sys, duckdb
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
q(f"SELECT v_datum, len_unit, static_bfe_navd88_status, count(*) n, count(static_bfe) n_bfe, min(static_bfe_navd88_sigma_ft) smin, max(static_bfe_navd88_sigma_ft) smax, min(static_bfe_navd88_spread_ft) spmin, max(static_bfe_navd88_spread_ft) spmax FROM read_parquet('{D}/assemble/zones_12103_raw.parquet') GROUP BY ALL ORDER BY n DESC", "zones_raw: source datum / unit / status")
q(f"SELECT v_datum, elev_ft_navd88_status, source_type, count(*) n, count(elev_ft_navd88_ft) n_elev, min(elev_ft_navd88_sigma_ft), max(elev_ft_navd88_sigma_ft), min(elev_ft), max(elev_ft) FROM read_parquet('{D}/assemble/bfe_lines_12103.parquet') GROUP BY ALL ORDER BY n DESC", "bfe_lines: datum / status / type")
q(f"SELECT bfe_method, bfe_datum, bfe_precision_ft, count(*) n FROM {B} WHERE bfe_ft IS NOT NULL GROUP BY ALL ORDER BY n DESC", "buildings: bfe_datum / precision")
q(f"SELECT cert_datum, count(*) n, count(cert_lag_ft) n_lag, min(cert_lag_ft), max(cert_lag_ft) FROM read_parquet('{D}/assemble/fdem_lag_12103.parquet') GROUP BY ALL", "fdem_lag: cert_datum")
q(f"SELECT ffe_class, ffe_datum, count(*) n FROM {B} GROUP BY ALL ORDER BY n DESC", "buildings: ffe_datum")
q(f"SELECT ground_geoid, ground_precision_ft, lidar_ql, ground_class, count(*) n FROM {B} GROUP BY ALL ORDER BY n DESC", "buildings: ground_geoid / precision")
q(f"SELECT bfe_call_basis, count(*) n FROM {B} WHERE bfe_call IN ('above','below') GROUP BY ALL ORDER BY n DESC", "decided calls by basis")
q(f"SELECT count(*) FILTER (WHERE bfe_precision_ft > 0) n_sigma_gt0, count(*) FILTER (WHERE bfe_precision_ft > 0 AND bfe_call='too_close' AND ffe_class='record') n_rec_too_close_sigma FROM {B}", "sigma>0 rows")
