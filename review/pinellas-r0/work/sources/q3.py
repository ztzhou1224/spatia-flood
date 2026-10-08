import sys, json, glob
import pandas as pd, numpy as np
from pathlib import Path
raw=Path(sys.argv[1]); fd=pd.read_parquet(sys.argv[2])
rows=[]
for p in sorted(glob.glob(str(raw/"page_*.json"))):
    for f in json.loads(Path(p).read_text())["features"]:
        a=dict(f["attributes"]); a["lon"],a["lat"]=f["geometry"]["x"],f["geometry"]["y"]; rows.append(a)
e=pd.DataFrame(rows)
pair=e.C2a_88.notna(); vd=e.VERTICAL_DATUM.fillna("").str.strip().str.upper(); bm=e.C2_BENCHMARK_VERT_DATUM.fillna("").astype(str).str.strip().str.upper()
nodat = ~pair & ~vd.isin(["NAVD1988","NGVD1929","NGVD1927"])
print("no_pair & no VERTICAL_DATUM (build.py drops):", int(nodat.sum()))
print("  of which C2_BENCHMARK_VERT_DATUM:", bm[nodat].replace("", "(blank)").value_counts().head(6).to_dict())
print("  of which B11_ELEVATION_DATUM:", e.B11_ELEVATION_DATUM.fillna("").str.strip().str.upper()[nodat].replace("", "(blank)").value_counts().head(5).to_dict())
rec = nodat & (bm=="NAVD1988") & (e.A4_BUILDING_USE.fillna("").str.strip().str.upper()=="RES")
dg=e.A7_BUILDING_DIAG_NUM.fillna("").str.upper().str.replace(r"[-\s,]","",regex=True).str.lstrip("0")
VALID={"1A","1B","2","2A","2B","2C","2D","3","4","5","6","7","8","9"}
rec2 = rec & dg.isin(VALID) & e.C2A_TOP_BOTTOM_FLOOR_EL.notna()
print("  dropped-for-datum but benchmark NAVD1988, RES, valid diagram, C2A filled:", int(rec2.sum()), " diagram 5-9:", int((rec2 & dg.str[0].isin(list("56789"))).sum()))
d=pd.to_datetime(pd.to_numeric(e.D_DATE,errors="coerce"),unit="ms",errors="coerce")
print("  their D_DATE years:", d[rec2].dt.year.value_counts().sort_index().to_dict())
# also check how the pair fields relate: when pair filled, is VERTICAL_DATUM blank?
print("pair filled & VERTICAL_DATUM blank:", int((pair & (vd=="")).sum()), " pair filled & benchmark datum:", bm[pair].replace("", "(blank)").value_counts().head(4).to_dict())
# vintage overlap of county vs lidar
print("records with any floor and D_DATE > 2019-03-08 and <2027:", int(((d>"2019-03-08")&(d<"2027")&e.C2A_TOP_BOTTOM_FLOOR_EL.notna()).sum()))
