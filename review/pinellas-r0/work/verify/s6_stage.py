import sys, duckdb, pandas as pd
A, T = sys.argv[1:3]
a = pd.read_parquet(A)[["OBJECTID","buildingElevationSource"]]
c = duckdb.connect(); c.register("a", a)
c.execute(f"CREATE VIEW b AS SELECT building_id, ffe_class, ffh_class, touches_sfha, bfe_call, CAST(regexp_extract(ffe_source,'OBJECTID (\\d+)',1) AS BIGINT) oid FROM read_parquet('{T}') WHERE ffe_class='record'")
print("record rows", c.execute("SELECT count(*), count(oid) FROM b").fetchall())
print(c.execute("SELECT coalesce(nullif(buildingElevationSource,''),'(null)') s, count(*) FROM b LEFT JOIN a ON a.OBJECTID=b.oid GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("non-finished: n, touches_sfha, calls", c.execute("SELECT count(*), count(*) FILTER (WHERE touches_sfha), count(*) FILTER (WHERE bfe_call='above'), count(*) FILTER (WHERE bfe_call='below'), count(*) FILTER (WHERE bfe_call='too_close') FROM b JOIN a ON a.OBJECTID=b.oid WHERE buildingElevationSource <> 'finished_construction'").fetchall())
print("matched attrs by source (all 7515):", c.execute("SELECT coalesce(nullif(buildingElevationSource,''),'(null)'), count(*) FROM a GROUP BY 1").fetchall())
