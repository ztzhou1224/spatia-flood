import sys, json
import numpy as np, pandas as pd, pyarrow.parquet as pq, pyproj
from pyproj import CRS
D = sys.argv[1]
print("numpy", np.__version__, "pandas", pd.__version__, "pyproj", pyproj.__version__)
for code in ("EPSG:6442","EPSG:6443","EPSG:3086","EPSG:6360","EPSG:3857"):
    c = CRS(code); print(code, "|", c.name, "|", [(a.name, a.unit_name, a.unit_conversion_factor) for a in c.axis_info])
print("US survey ft 30 ft diff vs intl:", 30*(1200/3937)/0.3048 - 30, "ft; ppm", (1200/3937/0.3048-1)*1e6)
t = pq.read_table(D+"/assemble/buildings_12103.parquet")
print("rows", t.num_rows, "cols", t.num_columns)
md = t.schema.metadata
print("metadata keys", list(md.keys()))
print(json.dumps(json.loads(md[b"spatia_flood"]), indent=0)[:1500])
print(t.schema)
