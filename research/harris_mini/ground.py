"""Per-house lidar ground from USGS 3DEP 1 m DEMs, around each house's footprint.

Inputs (data/harris_mini): l23 (answer key; used here ONLY for the house list and footprint match,
never for any value), l24 (structure type, year built), l25/l26 (footprints), the 1 m DEM tiles.
Output: data/harris_mini/houses.parquet, one row per front-door SFR answer-key point.

Ground stats (ft NAVD88, metres converted with the US survey foot) per DEM epoch:
  lag  = min of DEM in a 0.5-2.5 m ring outside the footprint (lowest adjacent grade)
  p10/med/hag = 10th pct / median / max in that ring; inside = median under the footprint
  far  = median in a 10-30 m ring (neighbourhood grade)
The DEMs are EPSG:26915 (NAD83 UTM 15N, m); footprints and points come in EPSG:6344
(NAD83(2011) UTM 15N): same projection, the NAD83 realisation difference is a few cm, ignored.
"""
import glob, json
from pathlib import Path
import numpy as np, pyarrow as pa, pyarrow.parquet as pq, rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import Polygon, Point, mapping
from shapely.strtree import STRtree

import sys
D = Path(__file__).resolve().parents[2] / "data" / "harris_mini" / (sys.argv[1] if len(sys.argv) > 1 else "B")
USFT = 1200 / 3937  # m per US survey foot

def polys(name):
    out = []
    for r in pq.read_table(D / name).to_pylist():
        rings = json.loads(r["rings"]) if r.get("rings") else None
        if not rings: continue
        p = Polygon(rings[0], rings[1:]).buffer(0)
        if p.area > 20: out.append((p, r))
    return out

def main():
    truth = pq.read_table(D / "l23.parquet").to_pylist()
    si = {}
    for r in pq.read_table(D / "l24.parquet").to_pylist():
        si.setdefault(r["HCAD_NUM"], []).append(r)
    f26, f25 = polys("l26.parquet"), polys("l25.parquet")
    by_hcad = {}
    for p, r in f26: by_hcad.setdefault(r["HCAD_NUM"], []).append(p)
    t25 = STRtree([p for p, _ in f25])
    dems = {}
    for f in glob.glob(str(D / "*.tif")):
        ep = "e2018" if "2018" in f else "e2024"
        dems.setdefault(ep, []).append(rasterio.open(f))
    rows = []
    for t in truth:
        if t["Location"] not in ("Front Door", "Garage Door"): continue
        s = [x for x in si.get(t["HCAD_NUM"], []) if x["WWCStrucType"] == "SFR"]
        if not s: continue
        pt = Point(t["gx"], t["gy"])
        cands = by_hcad.get(t["HCAD_NUM"], [])
        fp, src = None, None
        if cands:
            fp = min(cands, key=lambda p: p.distance(pt)); src = "hcad2017"
            if fp.distance(pt) > 10: fp = None
        if fp is None:
            idx = t25.query(pt.buffer(10))
            if len(idx):
                fp = min((f25[i][0] for i in idx), key=lambda p: p.distance(pt)); src = "lidar2018"
        if fp is None: continue
        yb = max((x["YearBuilt"] or 0) for x in s) or None
        row = dict(oid=t["OBJECTID"], hcad=t["HCAD_NUM"], loc=t["Location"], x=t["gx"], y=t["gy"],
                   lon=t["X"], lat=t["Y"], ffe=t["Z"], prec=t["Ht_Precision"], rec=t["RecordedAt"],
                   delivery=t["Source"], year_built=yb, fp_src=src, fp_area_m2=fp.area,
                   fp_wkt=fp.wkt)
        ring = fp.buffer(2.5).difference(fp.buffer(0.5))
        far = fp.buffer(30).difference(fp.buffer(10))
        for ep, rs in dems.items():
            for r in rs:
                b = r.bounds
                if not (b.left < fp.bounds[0] - 31 and fp.bounds[2] + 31 < b.right and b.bottom < fp.bounds[1] - 31 and fp.bounds[3] + 31 < b.top):
                    continue
                win = from_bounds(fp.bounds[0] - 31, fp.bounds[1] - 31, fp.bounds[2] + 31, fp.bounds[3] + 31, r.transform).round_offsets().round_lengths()
                a = r.read(1, window=win, masked=True).filled(np.nan).astype("float64")
                tr = r.window_transform(win)
                def stat(g):
                    m = ~geometry_mask([mapping(g)], a.shape, tr, all_touched=False)
                    v = a[m]; v = v[np.isfinite(v)]
                    return v / USFT if v.size else None
                v = stat(ring); vi = stat(fp); vf = stat(far)
                if v is not None and v.size >= 5:
                    row[f"{ep}_lag"] = float(v.min()); row[f"{ep}_p10"] = float(np.percentile(v, 10))
                    row[f"{ep}_med"] = float(np.median(v)); row[f"{ep}_hag"] = float(v.max())
                if vi is not None and vi.size >= 5: row[f"{ep}_inside"] = float(np.median(vi))
                if vf is not None and vf.size >= 20: row[f"{ep}_far"] = float(np.median(vf))
                break
        rows.append(row)
    pq.write_table(pa.Table.from_pylist(rows), D / "houses.parquet")
    print(len(rows), "houses written")

if __name__ == "__main__":
    main()
