import sys, json, glob, numpy as np, pandas as pd, duckdb
RAW, A8, CO, T = sys.argv[1:5]
rows=[]
for p in sorted(glob.glob(RAW+"/page_*.json")):
    for f in json.load(open(p))["features"]: rows.append(f["attributes"])
e=pd.DataFrame(rows).set_index("OBJECTID")
a=[]
for p in sorted(glob.glob(A8+"/page_*.json")):
    for f in json.load(open(p))["features"]: a.append(f["attributes"])
a=pd.DataFrame(a).set_index("OBJECTID")
co=pd.read_parquet(CO); co=co[co.vertical_datum_route=="navd88_native"]
pair = e.C2a_88.notna() & e.C2a_29.notna()
e["bottom"]=np.where(pair, e.C2a_88, e.C2A_TOP_BOTTOM_FLOOR_EL); e["next"]=np.where(pair, e.C2b_88, e.C2B_TOP_NEXT_HIGHER_FL_EL)
co=co.join(e[["bottom","next"]], on="county_objectid").join(a, on="county_objectid")
tb=pd.read_parquet(T, columns=["building_id","ffe_ft","ffe_class","ffe_source","bfe_ft","bfe_call","touches_sfha"])
tb["diag"]=tb.ffe_source.str.extract(r"diagram ([^,]+),")[0]
r=tb[(tb.ffe_class=="record")].merge(co, on="building_id", suffixes=("","_c"))
nh = r.diag.astype(str).str[0].isin(list("2346789"))
x = r[nh & r.bottom.notna() & r.next.notna()].copy()
print("r0 record rows diag 2-4/6-9 with county C2A and C2B:", len(x), "| county C2B within 0.5 ft of r0 ffe:", int(((x.next-x.ffe_ft).abs()<=0.5).sum()))
ab = x[x.bfe_call=="above"]
print("of those 'above':", len(ab), "| C2A < BFE:", int((ab.bottom<ab.bfe_ft).sum()), f"({(ab.bottom<ab.bfe_ft).mean():.1%})", "| C2A-BFE median", round((ab.bottom-ab.bfe_ft).median(),2), "IQR", (ab.bottom-ab.bfe_ft).quantile([.25,.75]).round(2).tolist())
allc = co[co.bottom.notna()&co.next.notna()]; print("county-wide next-bottom median ft:", round((allc.next-allc.bottom).median(),2), "n", len(allc))
# NFIP enclosure compliance for diagrams 6-9 'above' rows that flip: >=2 openings and net area >= 1 sq in per sq ft, or engineered
fl = ab[(ab.bottom<ab.bfe_ft) & ab.diag.astype(str).str[0].isin(list("6789"))].copy()
for c in ["A8A_SQR_FT_CRWLSPC_ENCL","A8B_NUMBER_FLOOD_OPENINGS","A8c_NET_AREA_OPENINGS_SQR_INCH","A9A_SQR_FT_ATTACHED_GARAGE","A9B_NUMBER_FLOOD_OPENINGS","A9c_NET_AREA_OPENINGS_SQR_INCH"]:
    fl[c]=pd.to_numeric(fl[c], errors="coerce")
print("flip rows diag 6-9:", len(fl), "| A8A enclosure sqft present:", int(fl.A8A_SQR_FT_CRWLSPC_ENCL.notna().sum()), ">0:", int((fl.A8A_SQR_FT_CRWLSPC_ENCL>0).sum()), "| A8B openings present:", int(fl.A8B_NUMBER_FLOOD_OPENINGS.notna().sum()), "| A8c net area present:", int(fl.A8c_NET_AREA_OPENINGS_SQR_INCH.notna().sum()))
print("A8D engineered values:", fl.A8D_ENGINEERED_FLOOD_OPENINGS.value_counts(dropna=False).to_dict())
enc = fl[fl.A8A_SQR_FT_CRWLSPC_ENCL>0]
eng = enc.A8D_ENGINEERED_FLOOD_OPENINGS.astype(str).str.strip().str.upper().isin(["Y","YES","TRUE","1"])
ok = (enc.A8B_NUMBER_FLOOD_OPENINGS>=2) & (enc.A8c_NET_AREA_OPENINGS_SQR_INCH >= enc.A8A_SQR_FT_CRWLSPC_ENCL)
print("enclosure>0 sqft:", len(enc), "| meets 2-openings & 1 sq in/sq ft:", int(ok.sum()), "| engineered flag:", int(eng.sum()), "| either:", int((ok|eng).sum()), "| no openings recorded (A8B null/0):", int(((enc.A8B_NUMBER_FLOOD_OPENINGS.fillna(0))==0).sum()))
print("enclosure A8A null/0 among flips (cannot say):", int(((fl.A8A_SQR_FT_CRWLSPC_ENCL.fillna(0))==0).sum()))
print("E5_BOTTOM_FLOOR_ELEVATED values:", fl.E5_BOTTOM_FLOOR_ELEVATED.value_counts(dropna=False).head(5).to_dict())
