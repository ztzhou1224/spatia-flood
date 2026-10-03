"""Pull HCFCD Structure_Inventory layers 23-26 inside one bbox, coordinates in EPSG:6344 (UTM 15N, m).

Layer 23 is the ANSWER KEY (scorer-only). Output: data/harris_mini/l{23,24,25,26}.parquet.
Usage: python fetch_hcfcd.py AREA minlon minlat maxlon maxlat [LAYER ...]  (default 23 24 25 26)
"""
import json, sys, time
from pathlib import Path
import pyarrow as pa, pyarrow.parquet as pq, requests

BASE = "https://services7.arcgis.com/NQSCMzARMhPjRo7j/arcgis/rest/services/Structure_Inventory/FeatureServer"
OUT = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
DROP = {"StreetSmartURL", "Address"}  # no street addresses kept from the flooded-structure layers

def fetch(layer: int, bbox: list[float]) -> list[dict]:
    rows, off = [], 0
    while True:
        p = dict(f="json", where="1=1", outFields="*", returnGeometry="true", outSR=6344,
                 geometry=",".join(map(str, bbox)), geometryType="esriGeometryEnvelope", inSR=4326,
                 spatialRel="esriSpatialRelIntersects", orderByFields="OBJECTID",
                 resultOffset=off, resultRecordCount=2000)
        for attempt in range(4):
            try:
                d = requests.get(f"{BASE}/{layer}/query", params=p, timeout=120).json(); break
            except Exception:
                time.sleep(2 ** attempt)
        if "error" in d: raise RuntimeError(d["error"])
        sr = d.get("spatialReference", {})
        if d["features"]:
            assert sr.get("latestWkid", sr.get("wkid")) == 6344, sr
        for f in d["features"]:
            a = {k: v for k, v in f["attributes"].items() if k not in DROP}
            g = f.get("geometry") or {}
            if "x" in g: a["gx"], a["gy"] = g["x"], g["y"]
            if "rings" in g: a["rings"] = json.dumps(g["rings"])
            rows.append(a)
        off += len(d["features"])
        if not d.get("exceededTransferLimit") and len(d["features"]) < 2000: break
    return rows

if __name__ == "__main__":
    OUT = OUT / sys.argv[1]
    bbox = [float(v) for v in sys.argv[2:6]]
    OUT.mkdir(parents=True, exist_ok=True)
    for L in [int(v) for v in sys.argv[6:]] or (23, 24, 25, 26):
        rows = fetch(L, bbox)
        pq.write_table(pa.Table.from_pylist(rows), OUT / f"l{L}.parquet")
        print(L, len(rows))
