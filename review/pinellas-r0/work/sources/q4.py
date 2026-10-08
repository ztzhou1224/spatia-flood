import sys, json, urllib.request, urllib.parse, time
import pandas as pd
lab = pd.read_parquet(sys.argv[1]); ids = sorted(lab.cert_objectid.astype(int).tolist()); print("matched certs", len(ids))
URL = "https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/arcgis/rest/services/Public_FDEM_Elevation_Certificates/FeatureServer/0/query"
rows = []
for i in range(0, len(ids), 500):
    q = urllib.parse.urlencode({"where": f"OBJECTID IN ({','.join(map(str, ids[i:i+500]))})", "outFields": "OBJECTID,buildingElevationSource,verticalDatum,elevationDatum,benchmarkUtilized,elevationDatumComments,baseFloodElevationDatum,formYear,issuedAt,firmPanelEffectiveDate,buildingUse,buildingDiagramNumber", "returnGeometry": "false", "f": "json"})
    for t in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, data=q.encode()), timeout=120) as r: d = json.loads(r.read())
            if "error" in d: raise RuntimeError(d["error"])
            break
        except Exception as e:
            print("retry", t, e, file=sys.stderr); time.sleep(3)
    rows += [f["attributes"] for f in d["features"]]
f = pd.DataFrame(rows); print("fetched", len(f))
f.to_parquet(sys.argv[2], index=False)
print("buildingElevationSource:", f.buildingElevationSource.fillna("(null)").value_counts().to_dict())
print("verticalDatum:", f.verticalDatum.fillna("(null)").value_counts().to_dict())
print("elevationDatum (BFE datum, B11):", f.elevationDatum.fillna("(null)").value_counts().to_dict())
print("baseFloodElevationDatum:", f.baseFloodElevationDatum.fillna("(null)").value_counts().head(6).to_dict())
print("benchmarkUtilized non-empty:", int(f.benchmarkUtilized.fillna("").str.strip().ne("").sum()))
c = f.elevationDatumComments.fillna("").str.strip(); print("elevationDatumComments non-empty:", int(c.ne("").sum()), " mentioning geoid:", int(c.str.contains("geoid", case=False).sum()), " examples:", c[c.str.contains("geoid", case=False)].str[:80].head(5).tolist())
print("formYear:", f.formYear.fillna(-1).astype(int).value_counts().to_dict())
# which of these are in the assembled table as record rows
b = pd.read_parquet(sys.argv[3], columns=["building_id","ffe_class","ffe_source","touches_sfha","bfe_call","bfe_call_basis"])
b = b[b.ffe_class=="record"].copy(); b["oid"] = b.ffe_source.str.extract(r"OBJECTID (\d+)")[0].astype(int)
m = b.merge(f[["OBJECTID","buildingElevationSource"]], left_on="oid", right_on="OBJECTID", how="left")
print("record rows", len(m), "by buildingElevationSource:", m.buildingElevationSource.fillna("(null)").value_counts().to_dict())
print("  of those not finished_construction: touches_sfha", int((m.buildingElevationSource.ne("finished_construction") & m.touches_sfha).sum()), " with bfe_call above/below:", m[m.buildingElevationSource.ne("finished_construction")].bfe_call.value_counts(dropna=False).to_dict())
