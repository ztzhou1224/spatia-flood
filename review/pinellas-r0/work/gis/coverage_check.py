import sys, duckdb, h3
D = sys.argv[1]
c = duckdb.connect()
def q(sql, title):
    print("---", title); print(c.sql(sql))
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
C = f"read_parquet('{D}/assemble/coverage_12103_r8.parquet')"
q(f"SELECT count(*) cells, sum(buildings) b, sum(in_risk_area) r, sum(touches_sfha) s, sum(floor_record) rec, sum(floor_modeled) mod, sum(sfha_decided) decided FROM {C}", "coverage sums")
q(f"SELECT count(*) b, count(*) FILTER (WHERE in_risk_area) r, count(*) FILTER (WHERE touches_sfha) s, count(*) FILTER (WHERE ffh_class='record') rec, count(*) FILTER (WHERE ffh_class='modeled') mod FROM {B}", "building totals")
# recompute cells independently and compare
rows = c.sql(f"SELECT lon, lat FROM {B}").fetchall()
from collections import Counter
cnt = Counter(h3.latlng_to_cell(la, lo, 8) for lo, la in rows)
cov = dict(c.sql(f"SELECT cell, buildings FROM {C}").fetchall())
print("cells recomputed", len(cnt), "cells in file", len(cov), "mismatch", sum(1 for k, v in cnt.items() if cov.get(k) != v))
# wrong-order test: lon,lat swapped would give cells elsewhere
bad = Counter(h3.latlng_to_cell(lo, la, 8) for lo, la in rows[:1000])
print("swapped-order cells overlap with file:", sum(1 for k in bad if k in cov), "of", len(bad))
# cell polygon vs centroid of the buildings in it
import shapely, pyarrow.parquet as pq
t = pq.read_table(f"{D}/assemble/coverage_12103_r8.parquet", columns=["cell", "geometry"]).to_pandas()
g = shapely.from_wkb(t.geometry.values)
ok = 0
for cell, poly in zip(t.cell, g):
    la, lo = h3.cell_to_latlng(cell)
    ok += poly.contains(shapely.Point(lo, la))
print("cell polygons containing their own h3 centre:", ok, "of", len(t))
