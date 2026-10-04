"""Overture building footprints (release 2026-08-19.0, public S3) for each Florida test tile.
Output: data/fl/footprints_<tx>_<ty>.parquet (WKT in EPSG:26917 metres; Overture is CDLA-Permissive / ODbL by source)."""
import sys, duckdb, pandas as pd
from pathlib import Path
from pyproj import Transformer
D = Path(__file__).resolve().parents[2] / "data" / "fl"
inv = Transformer.from_crs("EPSG:26917", "EPSG:4326", always_xy=True)
c = duckdb.connect(); c.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'"); c.execute("CREATE SECRET anon (TYPE S3, KEY_ID '', SECRET '', REGION 'us-west-2')")
src = "s3://overturemaps-us-west-2/release/2026-08-19.0/theme=buildings/type=building/*.parquet"
for r in pd.read_csv(D / "tile_urls.csv").itertuples():
    out = D / f"footprints_{r.tx}_{r.ty}.parquet"
    if out.exists(): continue
    (x0, y0), (x1, y1) = inv.transform(r.tx * 10000, r.ty * 10000 - 10000), inv.transform(r.tx * 10000 + 10000, r.ty * 10000)
    q = f"""COPY (SELECT id, ST_AsText(ST_Transform(geometry, 'EPSG:4326', 'EPSG:26917', always_xy := true)) AS wkt
        FROM read_parquet('{src}', hive_partitioning=1)
        WHERE bbox.xmin < {x1} AND bbox.xmax > {x0} AND bbox.ymin < {y1} AND bbox.ymax > {y0}) TO '{out}' (FORMAT parquet)"""
    c.execute(q)
    print(r.tx, r.ty, c.execute(f"select count(*) from '{out}'").fetchone(), flush=True)
