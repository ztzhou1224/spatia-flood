import sys, json, pyarrow.parquet as pq
for p in sys.argv[1:]:
    f = pq.ParquetFile(p)
    print("=====", p, f.metadata.num_rows, "rows")
    s = f.schema_arrow
    for n, t in zip(s.names, s.types):
        print("  ", n, t)
    md = s.metadata or {}
    for k, v in md.items():
        if k in (b"geo", b"spatia_flood"):
            print("META", k.decode(), ":", v.decode()[:3000])
