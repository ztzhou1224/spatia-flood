import duckdb, sys
T = "/home/user/spatia-flood/data/flood_v1/assemble/buildings_12103.parquet"
c = duckdb.connect(); c.execute("INSTALL spatial; LOAD spatial;")
c.execute(f"CREATE VIEW b AS SELECT * EXCLUDE (geometry) FROM read_parquet('{T}')")
def q(label, sql):
    print("##", label); 
    for r in c.execute(sql).fetchall(): print("  ", r)
q("ffh_class", "SELECT ffh_class, count(*) FROM b GROUP BY 1 ORDER BY 1")
q("bfe_call", "SELECT bfe_call, count(*) FROM b GROUP BY 1 ORDER BY 1")
q("conflict flag", "SELECT ffe_record_lidar_conflict, count(*) FROM b GROUP BY 1")
q("decided share of SFHA with call", "SELECT round(sum(bfe_call IN ('above','below'))*1.0/sum(bfe_call IS NOT NULL AND bfe_call<>'not_applicable'),4) FROM b")
# (h) conflict certs calls
q("(h) record conflict calls", "SELECT bfe_call, count(*) FROM b WHERE ffe_class='record' AND ffe_record_lidar_conflict GROUP BY 1")
q("(h) basis record_lidar_conflict", "SELECT bfe_call, count(*) FROM b WHERE bfe_call_basis LIKE 'record_lidar_conflict%' GROUP BY 1")
q("(h) record above within 0.5/0.1/0 of BFE", "SELECT count(*) FILTER (WHERE bfe_call='above'), count(*) FILTER (WHERE bfe_call='above' AND abs(ffe_ft-bfe_ft)<=0.5), count(*) FILTER (WHERE bfe_call='above' AND abs(ffe_ft-bfe_ft)<=0.1), count(*) FILTER (WHERE bfe_call='above' AND ffe_ft=bfe_ft), count(*) FILTER (WHERE bfe_call='below' AND abs(ffe_ft-bfe_ft)<=0.5) FROM b WHERE ffe_class='record'")
q("(h) record above within 0.5 strict <", "SELECT count(*) FROM b WHERE ffe_class='record' AND bfe_call='above' AND abs(ffe_ft-bfe_ft)<0.5")
# (d) ground sentinel
q("(d) ground_ft -1.999865 / <-1.99 / <0", "SELECT count(*) FILTER (WHERE abs(ground_ft+1.999865)<1e-5), count(*) FILTER (WHERE ground_ft < -1.99), count(*) FILTER (WHERE ground_ft < 0) FROM b")
q("(d) most frequent ground_ft values", "SELECT ground_ft, count(*) n FROM b WHERE ground_ft IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 5")
q("(d) sentinel rows by ffh_class and call", "SELECT ffh_class, bfe_call, count(*) FROM b WHERE abs(ground_ft+1.999865)<1e-5 GROUP BY 1,2 ORDER BY 1,2")
q("(d) 4 most extreme floor_minus_bfe", "SELECT round(floor_minus_bfe_ft,2), round(ground_ft,4), bfe_ft, zone_main, bfe_call, ffh_class FROM b WHERE floor_minus_bfe_ft IS NOT NULL ORDER BY floor_minus_bfe_ft LIMIT 6")
q("(d) below share for -1.99<ground<0 vs all SFHA-called", "SELECT CASE WHEN ground_ft>-1.99 AND ground_ft<0 THEN 'neg' ELSE 'other' END g, count(*), round(avg((bfe_call='below')::int),3) FROM b WHERE bfe_call IN ('above','below','too_close') GROUP BY 1")
# (i) slivers
q("(i) touches_sfha & all sfha zone shares round to 0", "SELECT count(*), count(*) FILTER (WHERE bfe_ft IS NOT NULL) FROM b WHERE touches_sfha AND NOT EXISTS (SELECT 1 FROM unnest(zones) z WHERE z.sfha AND z.share > 0)")
q("(i) sfha_share<0.001 & touches", "SELECT bfe_call, count(*) FROM b WHERE touches_sfha AND sfha_share < 0.001 GROUP BY 1")
q("(i) area*share<1 m2 & touches", "SELECT count(*), count(*) FILTER (WHERE bfe_call IN ('above','below')) FROM b WHERE touches_sfha AND footprint_area_m2*sfha_share < 1")
q("(i) max |sfha_share - sum zone sfha shares|", "SELECT max(abs(sfha_share - coalesce((SELECT sum(z.share) FROM unnest(zones) z WHERE z.sfha),0))) FROM b")
# (f) year built
q("(f) year_built>=2019 by ffh_class", "SELECT ffh_class, count(*) FROM b WHERE year_built>=2019 GROUP BY 1")
q("(f) modeled & >=2020 calls", "SELECT bfe_call, count(*) FROM b WHERE ffh_class='modeled' AND year_built>=2020 GROUP BY 1")
q("(f) modeled & >=2019 calls", "SELECT bfe_call, count(*) FROM b WHERE ffh_class='modeled' AND year_built>=2019 GROUP BY 1")
q("(f) ffe_vintage modeled>=2020", "SELECT ffe_vintage, count(*) FROM b WHERE ffh_class='modeled' AND year_built>=2020 GROUP BY 1")
q("(f) year_built max, >=2025", "SELECT max(year_built), count(*) FILTER (WHERE year_built>=2025) FROM b")
# data_audit 5: conflict flag by class
q("DA5 conflict by ffe_class", "SELECT ffe_class, count(*) FROM b WHERE ffe_record_lidar_conflict GROUP BY 1")
q("DA5 conflict record_note 'not used'", "SELECT ffe_class, count(*) FROM b WHERE record_note LIKE '%not used%' GROUP BY 1")
q("DA5 conflict issued after lidar / yb>=2019", "SELECT count(*) FILTER (WHERE ffe_vintage > '2019-03-08'), count(*) FILTER (WHERE year_built>=2019) FROM b WHERE ffe_record_lidar_conflict")
# data_audit 6
q("DA6 record (ffe-ground)-ffh > 3", "SELECT count(*), round(median((ffe_ft-ground_ft)-ffh_ft),3), count(*) FILTER (WHERE abs((ffe_ft-ground_ft)-ffh_ft)>3), round(max(abs((ffe_ft-ground_ft)-ffh_ft)),2) FROM b WHERE ffh_class='record' AND ground_ft IS NOT NULL")
q("DA6 record ffh max, >20", "SELECT round(max(ffh_ft),2), count(*) FILTER (WHERE ffh_ft>20), round(max(floor_minus_bfe_ft),2) FROM b WHERE ffh_class='record'")
# data_audit 7 band widths
q("DA7 modeled band >10ft", "SELECT count(*), count(*) FILTER (WHERE ffh_band_hi-ffh_band_lo>10), count(*) FILTER (WHERE ffh_band_hi-ffh_band_lo>10 AND NOT raised_flag), round(quantile_cont(ffh_band_hi-ffh_band_lo,0.95),2), round(max(ffh_band_hi-ffh_band_lo),1), round(median(ffh_band_hi-ffh_band_lo) FILTER (WHERE raised_flag),2), round(median(ffh_band_hi-ffh_band_lo) FILTER (WHERE NOT raised_flag),2) FROM b WHERE ffh_class='modeled'")
# methodology 1 diagram counts of record rows
q("M1 record rows diagram", "SELECT regexp_extract(ffe_source, 'diagram ([^,]+),', 1) d, count(*), count(*) FILTER (WHERE bfe_call='above') FROM b WHERE ffe_class='record' GROUP BY 1 ORDER BY 2 DESC")
# methodology 2 modeled above raised
q("M1 modeled above raised_flag", "SELECT count(*) FROM b WHERE ffh_class='modeled' AND bfe_call='above' AND raised_flag")
q("M8 too_close modeled flagged", "SELECT count(*), count(*) FILTER (WHERE raised_flag) FROM b WHERE ffh_class='modeled' AND bfe_call='too_close'")
# methodology 4 interpolated
q("M4 interpolated bfe_source pair types", "SELECT bfe_source, count(*) FROM b WHERE bfe_method='interpolated' GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
q("M4 interpolated calls", "SELECT bfe_call, count(*) FROM b WHERE bfe_method='interpolated' GROUP BY 1")
q("M4 interp band widths", "SELECT round(median(bfe_band_hi-bfe_band_lo),2), count(*) FILTER (WHERE bfe_band_hi-bfe_band_lo>2), max(bfe_band_hi-bfe_band_lo) FROM b WHERE bfe_method='interpolated'")
q("bfe_precision by method", "SELECT bfe_method, bfe_precision_ft, count(*) FROM b GROUP BY 1,2")
# licences
q("licences", "SELECT l, count(*) FROM (SELECT unnest(input_licences) l FROM b) GROUP BY 1")
q("provider", "SELECT provider, count(*) FROM b GROUP BY 1")
q("ground_geoid", "SELECT ground_geoid, count(*) FROM b GROUP BY 1")
q("lift_or_rebuild_null", "SELECT lift_or_rebuild_null, count(*) FROM b GROUP BY 1")
q("model_version on record rows / raised_flag on record", "SELECT count(*) FILTER (WHERE model_version IS NOT NULL), count(*) FILTER (WHERE raised_flag IS NOT NULL) FROM b WHERE ffh_class='record'")
q("impl4 ffe_null not_determinable & ffh_null not_evaluated", "SELECT count(*) FROM b WHERE ffe_null='not_determinable' AND ffh_null='not_evaluated'")
q("impl4 address null not_evaluated", "SELECT address_null, in_risk_area, count(*) FROM b WHERE address IS NULL GROUP BY 1,2")
q("record vintages by year", "SELECT substr(ffe_vintage,1,4) y, count(*) FROM b WHERE ffe_class='record' GROUP BY 1 ORDER BY 1")
q("record vintage >= 2024-09-26", "SELECT count(*) FROM b WHERE ffe_class='record' AND ffe_vintage >= '2024-09-26'")
