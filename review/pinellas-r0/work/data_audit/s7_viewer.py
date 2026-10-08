import sys, gzip, json, glob, random, pandas as pd, numpy as np, math, h3
V = sys.argv[1]; A = sys.argv[2]
files = sorted(glob.glob(f"{V}/rec/*.json")); print("rec files", len(files), "geo files", len(glob.glob(f"{V}/geo/*.json")))
idx = json.loads(gzip.decompress(open(f"{V}/index.json","rb").read())); print("index cells", len(idx), "sum n", sum(c["n"] for c in idx))
county = json.loads(gzip.decompress(open(f"{V}/county.json","rb").read())); print("county.json keys", list(county.keys()))
b = pd.read_parquet(f"{A}/buildings_12103.parquet").drop(columns="geometry"); b.index = b.building_id.values
random.seed(1); cells = random.sample(files, 3)
mism = 0; checked = 0; cols = None
for fpath in cells:
    rec = json.loads(gzip.decompress(open(fpath,"rb").read()))
    cols = sorted(set(k for r in rec.values() for k in r))
    ids = random.sample(list(rec), 5)
    for i in ids:
        row = b.loc[i]
        for k, v in rec[i].items():
            t = row[k]
            if k in ("zones","input_licences"):
                continue
            if isinstance(v, (int,float)) and not isinstance(v, bool):
                if t is None or (isinstance(t,float) and math.isnan(t)): mism += 1; print("MISMATCH", i, k, v, t); continue
                nd = 6 if k in ("lon","lat") else 3
                if abs(float(t) - float(v)) > 10**-nd + 1e-9: mism += 1; print("MISMATCH", i, k, v, t)
            elif v is None:
                if not (t is None or (isinstance(t,float) and math.isnan(t)) or t is pd.NA): mism += 1; print("MISMATCH", i, k, v, t)
            else:
                if str(v) != str(t) and not (isinstance(t, (bool, np.bool_)) and bool(t)==v): mism += 1; print("MISMATCH", i, k, v, t)
            checked += 1
print("values checked", checked, "mismatches", mism)
print("rec columns:", cols)
print("columns in rec not in table:", [c for c in cols if c not in b.columns], "; table cols not in rec:", [c for c in b.columns if c not in cols])
# look for personal / internal fields in a rec sample
rec = json.loads(gzip.decompress(open(cells[0],"rb").read())); r0 = rec[next(iter(rec))]
print("sample record keys with OBJECTID / name / pdf / url:", [k for k in r0 if any(s in k.lower() for s in ("objectid","name","pdf","url","owner","phone","mail"))])
print("string fields that embed OBJECTID:", [k for k,v in r0.items() if isinstance(v,str) and "OBJECTID" in v])
srcs = [r.get("ffe_source") for r in rec.values() if r.get("ffe_class")=="record"][:2]; print("ffe_source sample:", srcs)
print("record_note sample:", [r.get("record_note") for r in rec.values() if r.get("record_note")][:2])
print("record_vintage_note sample:", [r.get("record_vintage_note") for r in rec.values() if r.get("record_vintage_note")][:1])
geo = json.loads(gzip.decompress(open(cells[0].replace("/rec/","/geo/"),"rb").read()))
print("geo properties keys:", list(geo["features"][0]["properties"].keys()), "n", len(geo["features"]), "rec n", len(rec))
cov = json.loads(gzip.decompress(open(f"{V}/coverage.json","rb").read())); print("coverage features", len(cov["features"]), "props", list(cov["features"][0]["properties"].keys()))
print("county.json:", {k: (v if not isinstance(v,(dict,list)) else type(v).__name__) for k,v in county.items()})
