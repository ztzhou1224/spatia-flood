"""Fetch Pinellas-area FDEM public certificates (no owner/address fields) to re-run labels.py's dedupe rule."""
import sys, json, time, requests, pandas as pd, shapely
out = sys.argv[1]; D = sys.argv[2]
FDEM = "https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/arcgis/rest/services/Public_FDEM_Elevation_Certificates/FeatureServer/0"
meta = requests.get(FDEM, params={"f": "json"}, timeout=60).json()
names = [f["name"] for f in meta["fields"]]
print("fields:", names)
print("maxRecordCount", meta.get("maxRecordCount"))
b = pd.read_parquet(D+"/lidar/pinellas_2018/buildings.parquet")
x0, y0, x1, y1 = shapely.total_bounds(shapely.from_wkb(b.wkb.values))
want = [n for n in ("OBJECTID","propertyId","issuedAt","verticalDatum","buildingUse","buildingDiagramNumber","topOfBottomFloor","topOfNextHigherFloor","lowestAdjacentGrade","floodZone","baseFloodElevation","formYear","firmPanelEffectiveDate") if n in names]
rows, off = [], 0
while True:
    r = requests.get(FDEM + "/query", params={"where": "verticalDatum='navd_1988' AND buildingUse='residential'", "geometry": f"{x0},{y0},{x1},{y1}", "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": ",".join(want), "returnGeometry": "true", "resultOffset": off, "resultRecordCount": 2000, "f": "json"}, timeout=120)
    r.raise_for_status(); j = r.json()
    if "error" in j: print(j); break
    for f in j["features"]:
        a = f["attributes"]; pts = (f.get("geometry") or {}).get("points") or [[None, None]]; g = {"x": pts[0][0], "y": pts[0][1]}
        rows.append({**a, "lon": g.get("x"), "lat": g.get("y")})
    print("page", off, len(j["features"]), flush=True)
    if not j.get("exceededTransferLimit"): break
    off += len(j["features"]); time.sleep(0.5)
df = pd.DataFrame(rows)
df.to_parquet(out + "/fdem_pinellas_bbox.parquet", index=False)
print("rows", len(df), "cols", list(df.columns))
