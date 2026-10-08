import sys, duckdb, h3
from collections import Counter
D = sys.argv[1]; c = duckdb.connect()
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"; C = f"read_parquet('{D}/assemble/coverage_12103_r8.parquet')"
Z = f"read_parquet('{D}/assemble/zones_12103_raw.parquet')"
def q(t, s): print("---", t); print(c.sql(s))
q("(4) firm_effective_date counts", f"SELECT firm_effective_date, count(*) n, count(*) FILTER (WHERE touches_sfha) sfha FROM {B} GROUP BY 1 ORDER BY 2 DESC")
q("(4) polygons 12103C pre-2021", f"SELECT count(*) n, count(*) FILTER (WHERE sfha_tf='T') sfha FROM {Z} WHERE dfirm_id='12103C' AND firm_panel_eff_date_max < DATE '2021-01-01'")
q("(4) bfe_vintage 2003 by method", f"SELECT bfe_method, count(*) n FROM {B} WHERE bfe_vintage='2003-09-03' GROUP BY 1")
q("(8) condo stacks", f"SELECT count(*) FILTER (WHERE parcels_at_centroid>1) stacked, count(*) FILTER (WHERE parcels_at_centroid>1 AND ffh_class='modeled') modeled, count(*) FILTER (WHERE parcels_at_centroid>1 AND bfe_call='below') below, max(parcels_at_centroid) mx FROM {B}")
q("(8) stacked by DOR", f"SELECT dor_use_code, count(*) n, count(*) FILTER (WHERE ffh_class='modeled') modeled FROM {B} WHERE parcels_at_centroid>1 GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
q("(7) coverage sums", f"SELECT count(*) cells, sum(buildings) b, sum(in_risk_area) r, sum(touches_sfha) s, sum(floor_record) rec, sum(floor_modeled) mod FROM {C}")
rows = c.sql(f"SELECT lon, lat FROM {B}").fetchall()
cnt = Counter(h3.latlng_to_cell(la, lo, 8) for lo, la in rows)
cov = dict(c.sql(f"SELECT cell, buildings FROM {C}").fetchall())
print("(7) independent h3 r8 recount: cells", len(cnt), "sum", sum(cnt.values()), "file cells", len(cov), "mismatched cells", sum(1 for k, v in cnt.items() if cov.get(k) != v), "file cells missing from recount", sum(1 for k in cov if k not in cnt))
# (2) AO
q("(2) zone_main=AO", f"SELECT count(*) n, count(*) FILTER (WHERE bfe_method='static') static, count(*) FILTER (WHERE bfe_method='static' AND bfe_ft=8.0) static_8, count(*) FILTER (WHERE bfe_null='no_coverage') no_cov FROM {B} WHERE zone_main='AO'")
q("(2) AO bfe_call", f"SELECT bfe_call, bfe_null, count(*) n FROM {B} WHERE zone_main='AO' GROUP BY ALL ORDER BY 3 DESC")
q("(2) AO static rows: the non-AO SFHA element share", f"""SELECT building_id, bfe_ft, list_filter(zones, z -> z.zone<>'AO')[1].zone other_zone, list_filter(zones, z -> z.zone<>'AO')[1].subtype other_sub, list_filter(zones, z -> z.zone<>'AO')[1].share other_share, list_filter(zones, z -> z.zone='AO')[1].share ao_share FROM {B} WHERE zone_main='AO' AND bfe_method='static' ORDER BY other_share LIMIT 6""")
q("(2) AO static rows: min/max share of non-AO element", f"SELECT count(*) n, round(min(s),4) mn, round(max(s),4) mx FROM (SELECT list_max(list_transform(list_filter(zones, z -> z.zone<>'AO' AND z.sfha), z -> z.share)) s FROM {B} WHERE zone_main='AO' AND bfe_method='static')")
q("(2) buildings touching any AO polygon", f"SELECT count(*) n, count(*) FILTER (WHERE bfe_call IN ('below','above')) decided FROM {B} WHERE list_contains(list_transform(zones, z -> z.zone), 'AO')")
q("(2) AO polygons in NFHL", f"SELECT fld_zone, static_bfe_navd88_status, count(*) n FROM {Z} WHERE fld_zone IN ('AO','AH') GROUP BY ALL")
print("(2) zones_raw columns:", c.sql(f"SELECT * FROM {Z} LIMIT 0").columns)
