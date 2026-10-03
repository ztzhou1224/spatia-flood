"""Pull FEMA NFHL layers inside one bbox (geometry in EPSG:6344, UTM 15N metres).

28 Flood Hazard Zones, 16 Base Flood Elevation lines, 3 FIRM panels, 1 LOMRs.
Output: data/harris_mini/<AREA>/nfhl_<layer>.parquet (attributes + geometry JSON).
Usage: python fetch_nfhl.py AREA minlon minlat maxlon maxlat
"""
import json, sys, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq, requests

NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
OUT = Path(__file__).resolve().parents[2] / "data" / "harris_mini"

def fetch(layer, bbox):
    rows, off = [], 0
    while True:
        p = dict(f="json", where="1=1", outFields="*", returnGeometry="true", outSR=6344,
                 geometry=",".join(map(str, bbox)), geometryType="esriGeometryEnvelope", inSR=4326,
                 spatialRel="esriSpatialRelIntersects", orderByFields="OBJECTID",
                 resultOffset=off, resultRecordCount=1000)
        for attempt in range(5):
            try:
                d = requests.get(f"{NFHL}/{layer}/query", params=p, timeout=180).json()
                if "error" not in d: break
            except Exception:
                pass
            time.sleep(2 ** attempt)
        if "error" in d: raise RuntimeError(d["error"])
        if d["features"]:
            sr = d.get("spatialReference", {})
            assert sr.get("latestWkid", sr.get("wkid")) == 6344, sr
        for f in d["features"]:
            a = dict(f["attributes"]); a["geometry"] = json.dumps(f.get("geometry"))
            rows.append(a)
        off += len(d["features"])
        if not d.get("exceededTransferLimit"): break
    return rows

if __name__ == "__main__":
    area, bbox = sys.argv[1], [float(v) for v in sys.argv[2:6]]
    for L in (28, 16, 3, 1):
        rows = fetch(L, bbox)
        if rows: pq.write_table(pa.Table.from_pylist(rows), OUT / area / f"nfhl_{L}.parquet")
        print(area, L, len(rows))
