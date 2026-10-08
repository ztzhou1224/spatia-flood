import sys, duckdb
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
Z = f"read_parquet('{D}/assemble/zones_12103_raw.parquet')"
q(f"SELECT fld_zone, zone_subty, sfha_tf, count(*) n, count(static_bfe_navd88_ft) n_bfe FROM {Z} GROUP BY ALL ORDER BY fld_zone, n DESC", "NFHL polygons: zone / subtype")
q(f"SELECT zone_main, zone_main_subtype, count(*) n, count(*) FILTER (WHERE touches_sfha) touch, count(bfe_ft) n_bfe, count(*) FILTER (WHERE bfe_call IN ('above','below')) decided, count(*) FILTER (WHERE bfe_call='below') below FROM {B} GROUP BY ALL ORDER BY n DESC", "buildings: zone_main / subtype")
q(f"SELECT zone_main, bfe_null, count(*) n FROM {B} WHERE bfe_ft IS NULL AND touches_sfha GROUP BY ALL ORDER BY n DESC", "SFHA buildings without BFE by zone_main")
q(f"SELECT bfe_call, bfe_call_basis, count(*) n FROM {B} WHERE zone_main='VE' GROUP BY ALL ORDER BY n DESC", "VE zone_main calls")
q(f"SELECT count(*) n_any_ve, count(*) FILTER (WHERE bfe_call IN ('above','below')) decided, count(*) FILTER (WHERE bfe_call='above') above FROM {B} WHERE list_contains(list_transform(zones, z -> z.zone), 'VE')", "buildings with any VE element")
q(f"SELECT firm_effective_date, count(*) n FROM {B} GROUP BY ALL ORDER BY n DESC", "firm_effective_date")
q(f"SELECT dfirm_id, firm_panel_eff_date_min, firm_panel_eff_date_max, count(*) n FROM {Z} GROUP BY ALL ORDER BY n DESC", "zones_raw panel dates")
q(f"SELECT bfe_vintage, bfe_method, count(*) n FROM {B} WHERE bfe_ft IS NOT NULL GROUP BY ALL ORDER BY n DESC LIMIT 12", "bfe_vintage")
q(f"SELECT count(*) n, count(*) FILTER (WHERE sfha_share < 0.01) sliver, count(*) FILTER (WHERE sfha_share < 0.01 AND bfe_call='below') sliver_below, count(*) FILTER (WHERE sfha_share < 0.05) under5 FROM {B} WHERE touches_sfha", "touches_sfha slivers")
# buildings overlapping >1 SFHA polygon with different static BFE: does 'highest' matter
q(f"""WITH e AS (SELECT building_id, bfe_ft, bfe_call, list_count(list_filter(zones, z -> z.sfha)) n_sfha_el FROM {B} WHERE touches_sfha)
      SELECT n_sfha_el, count(*) FROM e GROUP BY ALL ORDER BY 1""", "number of distinct SFHA zone/subtype elements per building")
# AO / AH
q(f"SELECT zone_main, count(*) n, count(bfe_ft) n_bfe, bfe_null, bfe_method FROM {B} WHERE zone_main IN ('AO','AH','A','A99','V') GROUP BY ALL ORDER BY n DESC", "AO/AH/A handling")
q(f"SELECT sfha_tf, fld_zone, zone_subty, count(*) FROM {Z} WHERE fld_zone IN ('AO','AH','A') GROUP BY ALL", "AO/AH/A polygons raw")
q(f"SELECT static_bfe_navd88_status, count(*) FROM {Z} WHERE fld_zone='AO' GROUP BY ALL", "AO static_bfe status")
q(f"SELECT zone_main, zone_main_subtype, sfha_share, bfe_ft, bfe_method, bfe_call, bfe_call_basis, ffe_class FROM {B} WHERE zone_main='AO' LIMIT 8", "AO sample")
