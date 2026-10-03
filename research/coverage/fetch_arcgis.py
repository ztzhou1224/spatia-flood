"""Generic ArcGIS REST layer pull inside a bbox, geometry in EPSG:6344 (UTM 15N, m).

Usage: python fetch_arcgis.py AREA NAME LAYER_URL minlon minlat maxlon maxlat [WHERE]
Output: data/harris_mini/<AREA>/<NAME>.parquet (attributes + esri geometry JSON).
"""
import json, sys, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq, requests

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"

def fetch(url, bbox, where="1=1"):
    rows, off = [], 0
    while True:
        p = dict(f="json", where=where, outFields="*", returnGeometry="true", outSR=6344,
                 geometry=",".join(map(str, bbox)), geometryType="esriGeometryEnvelope", inSR=4326,
                 spatialRel="esriSpatialRelIntersects", resultOffset=off, resultRecordCount=1000)
        for a in range(5):
            try:
                d = requests.get(f"{url}/query", params=p, timeout=180).json()
                if "error" not in d: break
            except Exception:
                pass
            time.sleep(2 ** a)
        if "error" in d: raise RuntimeError(d["error"])
        if d["features"]:
            sr = d.get("spatialReference", {}); assert sr.get("latestWkid", sr.get("wkid")) == 6344, sr
        for f in d["features"]:
            a = dict(f["attributes"]); a["geometry"] = json.dumps(f.get("geometry")); rows.append(a)
        off += len(d["features"])
        if not d.get("exceededTransferLimit") or not d["features"]: break
    return rows

if __name__ == "__main__":
    area, name, url = sys.argv[1:4]
    bbox = [float(v) for v in sys.argv[4:8]]
    rows = fetch(url, bbox, sys.argv[8] if len(sys.argv) > 8 else "1=1")
    if rows: pq.write_table(pa.Table.from_pylist(rows), D / area / f"{name}.parquet")
    print(area, name, len(rows))
