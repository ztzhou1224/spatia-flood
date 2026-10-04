"""Coastal coverage of the core inputs, population-weighted (us_population_h3 r10 pop_night).
Coast = counties with FEMA NRI coastal flooding expected annual loss > 0 (CFLD_EALT > 0)."""
from r2duck import *
import time
c=con(); t=time.time()
c.execute(f"""CREATE TABLE coast AS SELECT STCOFIPS AS fips FROM read_parquet('{path('fema_nri_county')}') WHERE CFLD_EALT > 0""")
print('coastal counties', c.execute("select count(*) from coast").fetchone())
c.execute(f"""CREATE TABLE cells AS
  SELECT p.h3_index, p.county_fips, p.state, p.pop_night,
         ST_Point(h3_cell_to_lng(p.h3_index), h3_cell_to_lat(p.h3_index)) AS pt
  FROM read_parquet('{path('us_population_h3')}', hive_partitioning=true) p JOIN coast ON p.county_fips = coast.fips
  WHERE p.pop_night > 0""")
print('cells', c.execute("select count(*), sum(pop_night) from cells").fetchone(), round(time.time()-t))
c.execute(f"""CREATE TABLE lidar AS SELECT ql, onemeter_category, geom FROM read_parquet('{path('us_3dep_lidar_availability')}')""")
for name, cond in (("lidar_any", "true"),
                   ("lidar_1m_ql012", "ql IN ('QL 0','QL 1','QL 2') AND onemeter_category IN ('Meets','Meets with variance')")):
    c.execute(f"""CREATE TABLE {name} AS SELECT DISTINCT cells.h3_index FROM cells JOIN (SELECT geom FROM lidar WHERE {cond}) l
                 ON ST_Intersects(cells.pt, l.geom)""")
    print(name, c.execute(f"select count(*) from {name}").fetchone(), round(time.time()-t))
c.execute(f"""CREATE TABLE slr AS SELECT DISTINCT cells.h3_index FROM cells JOIN read_parquet('{path('noaa_slr_inundation_footprint')}') f ON ST_Intersects(cells.pt, f.geom)""")
c.execute(f"""CREATE TABLE fz AS SELECT DISTINCT h3_index FROM read_parquet('{path('fema_flood_zones_h3')}', hive_partitioning=true) WHERE h3_resolution = 8""")
c.execute("""CREATE TABLE fz_cells AS SELECT DISTINCT cells.h3_index FROM cells JOIN fz ON h3_cell_to_parent(cells.h3_index, 8) = fz.h3_index""")
q = """SELECT {g} AS grp, count(DISTINCT county_fips) AS counties, round(sum(pop_night)/1e6,2) AS residents_m,
  round(sum(CASE WHEN h3_index IN (SELECT h3_index FROM lidar_any) THEN pop_night END)/sum(pop_night),3) AS lidar_any,
  round(sum(CASE WHEN h3_index IN (SELECT h3_index FROM lidar_1m_ql012) THEN pop_night END)/sum(pop_night),3) AS lidar_1m_ql012,
  round(sum(CASE WHEN h3_index IN (SELECT h3_index FROM fz_cells) THEN pop_night END)/sum(pop_night),3) AS fema_digital_zones,
  round(sum(CASE WHEN h3_index IN (SELECT h3_index FROM slr) THEN pop_night END)/sum(pop_night),3) AS noaa_slr_footprint
  FROM cells GROUP BY 1 ORDER BY residents_m DESC"""
import pandas as pd; pd.set_option('display.width',200)
df=pd.concat([c.execute(q.format(g="'ALL COAST'")).df(), c.execute(q.format(g="state")).df()])
print(df.to_markdown(index=False))
df.to_csv('/home/user/spatia-flood/data/coast_coverage.csv', index=False)
print('wall', round(time.time()-t))
