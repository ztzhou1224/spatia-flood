from r2duck import *
import pandas as pd
c=con()
c.execute(f"CREATE TABLE coast AS SELECT STCOFIPS AS fips FROM read_parquet('{path('fema_nri_county')}') WHERE CFLD_EALT > 0")
c.execute(f"""CREATE TABLE cells AS SELECT p.h3_index, p.county_fips, p.state, p.pop_night, h3_cell_to_parent(p.h3_index, 8) AS p8
  FROM read_parquet('{path('us_population_h3')}', hive_partitioning=true) p JOIN coast ON p.county_fips = coast.fips WHERE p.pop_night > 0""")
c.execute(f"""CREATE TABLE fz AS SELECT h3_index, max(CASE WHEN sfha_tf='T' THEN 1 ELSE 0 END) sfha,
  max(CASE WHEN fld_zone='X' AND zone_subty_label LIKE '0.2%' THEN 1 ELSE 0 END) x02
  FROM read_parquet('{path('fema_flood_zones_h3')}', hive_partitioning=true) WHERE h3_resolution=8 GROUP BY 1""")
c.execute("CREATE TABLE j AS SELECT cells.*, fz.sfha, fz.x02, fz.h3_index IS NOT NULL AS mapped FROM cells LEFT JOIN fz ON cells.p8 = fz.h3_index")
c.execute("CREATE TABLE cty AS SELECT county_fips, bool_or(mapped) digital FROM j GROUP BY 1")
q="""SELECT {g} grp, round(sum(pop_night)/1e6,2) residents_m,
 round(sum(CASE WHEN cty.digital THEN pop_night END)/sum(pop_night),3) in_county_with_digital_fema_map,
 round(sum(CASE WHEN sfha=1 THEN pop_night END)/sum(pop_night),3) in_r8_cell_touching_sfha
 FROM j JOIN cty USING (county_fips) GROUP BY 1 ORDER BY residents_m DESC"""
df=pd.concat([c.execute(q.format(g="'ALL COAST'")).df(), c.execute(q.format(g="state")).df()])
print('coastal counties with digital FEMA map:', c.execute("select sum(digital::int), count(*) from cty").fetchone())
print(df.head(12).to_markdown(index=False)); df.to_csv('/home/user/spatia-flood/data/coast_fema.csv',index=False)
