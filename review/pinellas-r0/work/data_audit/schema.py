import sys, pyarrow.parquet as pq, json
p = sys.argv[1]
t = pq.read_metadata(p)
print("rows", t.num_rows, "cols", t.num_columns)
s = pq.read_schema(p)
for f in s: print(f.name, f.type)
md = s.metadata or {}
for k in md:
    if k != b"geo": print(k, md[k][:3000])
    else: print("geo", md[k][:600])
