import sys, json, glob
import pandas as pd, numpy as np
from pathlib import Path
raw = Path(sys.argv[1]); lp = sys.argv[2]; fd = sys.argv[3]; feat = sys.argv[4]
L = json.loads((raw/"layer.json").read_text())
print("layer name:", L.get("name"), "| description:", (L.get("description") or "")[:600])
print("copyrightText:", repr(L.get("copyrightText"))); print("serviceItemId:", L.get("serviceItemId")); print("editingInfo:", L.get("editingInfo"))
print("n fields:", len(L["fields"])); print([f["name"] for f in L["fields"]])
F = json.loads((raw/"fetch.json").read_text()); print("fetch:", {k:v for k,v in F.items() if k!="out_fields"})
rows=[]
for p in sorted(glob.glob(str(raw/"page_*.json"))):
    for f in json.loads(Path(p).read_text())["features"]:
        a=dict(f["attributes"]); rows.append(a)
e=pd.DataFrame(rows); print("records", len(e)); print("cols fetched", list(e.columns))
print("VERTICAL_DATUM:", e.VERTICAL_DATUM.fillna("(null)").str.strip().str.upper().value_counts().head(8).to_dict())
print("C2_BENCHMARK_VERT_DATUM:", e.C2_BENCHMARK_VERT_DATUM.fillna("(null)").astype(str).str.strip().str.upper().value_counts().head(6).to_dict())
print("B11_ELEVATION_DATUM:", e.B11_ELEVATION_DATUM.fillna("(null)").astype(str).str.strip().str.upper().value_counts().head(6).to_dict())
print("MEASUREMENT_UNITS:", e.MEASUREMENT_UNITS.fillna("(null)").astype(str).str.strip().str.upper().value_counts().head(6).to_dict())
print("C2A non-null:", int(e.C2A_TOP_BOTTOM_FLOOR_EL.notna().sum()), " C2a_88 non-null:", int(e.C2a_88.notna().sum()), " any floor (C2A or C2a_88 or C2B or C2b_88):", int((e.C2A_TOP_BOTTOM_FLOOR_EL.notna()|e.C2a_88.notna()|e.C2B_TOP_NEXT_HIGHER_FL_EL.notna()|e.C2b_88.notna()).sum()))
print("C2F LAG non-null:", int(e.C2F_LAG_ELEV.notna().sum()), " C2f_88:", int(e.C2f_88.notna().sum()))
d=pd.to_datetime(pd.to_numeric(e.D_DATE,errors="coerce"),unit="ms",errors="coerce")
print("D_DATE non-null", int(d.notna().sum()), "min", d.min(), "max (valid<2027)", d[d<"2027"].max())
print("D_DATE years:", d[d<"2027"].dt.year.value_counts().sort_index().tail(12).to_dict())
print("D_DATE >= 2019-03-08:", int((d[d<"2027"]>="2019-03-08").sum()), " >= 2020-06:", int((d[d<"2027"]>="2020-06-01").sum()))
le=pd.to_datetime(pd.to_numeric(e.LAST_EDITED_DATE,errors="coerce"),unit="ms",errors="coerce"); print("LAST_EDITED_DATE max", le.max(), " CREATED_DATE max", pd.to_datetime(pd.to_numeric(e.CREATED_DATE,errors="coerce"),unit="ms",errors="coerce").max())
print("A7 diagram raw top:", e.A7_BUILDING_DIAG_NUM.fillna("(null)").astype(str).str.strip().str.upper().value_counts().head(15).to_dict())
print("REDACTED:", e.REDACTED.fillna("(null)").astype(str).value_counts().head(5).to_dict())
print("POINT_TYPE:", e.POINT_TYPE.fillna("(null)").astype(str).value_counts().head(5).to_dict())
# labels
c=pd.read_parquet(lp); f=pd.read_parquet(fd); print("\ncounty labels", len(c), "fdem labels", len(f), "fdem distinct bldg", f.building_id.nunique())
print("county licence:", c.licence.value_counts().to_dict(), " route:", c.vertical_datum_route.value_counts().to_dict())
new = c[~c.building_id.isin(set(f.building_id))]; print("county buildings not in FDEM labels:", len(new), " of which navd88_native:", int((new.vertical_datum_route=='navd88_native').sum()))
nn = new[new.vertical_datum_route=='navd88_native']
print("new native: diagram 5-9:", int(nn.diagram.str[0].isin(list('56789')).sum()), " diagram counts:", nn.diagram.value_counts().to_dict())
ft=pd.read_parquet(feat, columns=["building_id","g_lag","lpc_status","roof_p95"]); nn=nn.merge(ft,on="building_id",how="left"); nn["dh"]=nn.ffe_ft-nn.g_lag
print("new native with dh>3:", int((nn.dh>3).sum()), " either:", int(((nn.dh>3)|nn.diagram.str[0].isin(list('56789'))).sum()))
both = c.merge(f, on="building_id"); print("overlap buildings", len(both), " |diff|<=0.5:", round(float(((both.ffe_ft_x-both.ffe_ft_y).abs()<=0.5).mean()),3))
print("county issued_at max:", pd.to_datetime(c.issued_at,unit="ms").max(), " fdem issued_at max:", pd.to_datetime(f.issued_at,unit="ms",errors="coerce").max())
comb=pd.read_parquet(sys.argv[5]); print("combined", len(comb), comb.label_source.value_counts().to_dict(), comb.licence.value_counts().to_dict())
