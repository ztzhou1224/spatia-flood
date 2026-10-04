"""Street views of the NYC test houses (Staten Island east shore) from Mapillary (CC BY-SA 4.0).

Houses: the 6,190 BES single-family houses in data/nyc/nyc_scored.parquet (their measured floor is the
answer key and is NOT read here; only BIN and the footprint are used). Footprints: NYC BUILDING dataset
(data/nyc/footprints_si_east.parquet), metres in EPSG:26918 (UTM 18N).
A view qualifies when the camera is 6-40 m from the target footprint, not inside a building, the line from
the camera to the footprint centroid crosses no other building, the house is in the field of view, and the
camera roll is not 45-135 deg (|roll| > 135 = image served upside down, flagged rot180).
Ranking: newest capture first (post-Sandy elevations ran into 2020), then distance nearest 15 m.
Up to MAXV views per house. Full-resolution frames to data/nyc/frames/.
Output: data/nyc/views.parquet.  Usage: python nyc_views.py
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
from m3_views import FIELDS, hfov  # noqa: E402
from m3_views2 import roll_deg  # noqa: E402
from mapillary_views import fetch_img, graph  # noqa: E402

ROOT = HERE.parents[1]
D = ROOT / "data" / "nyc"
TO = Transformer.from_crs("EPSG:4326", "EPSG:26918", always_xy=True).transform
DMIN, DMAX, MAXV = 6.0, 40.0, 3


def norm_bin(v):
    return pd.to_numeric(v, errors="coerce").astype("Int64").astype(str)


def main():
    h = pd.read_parquet(D / "nyc_scored.parquet", columns=["bin"]).assign(bin=lambda d: norm_bin(d.bin))
    fp = pd.read_parquet(D / "footprints_si_east.parquet", columns=["bin", "the_geom"]).assign(bin=lambda d: norm_bin(d.bin))
    fp["geom"] = [transform(TO, shape(json.loads(g))).buffer(0) for g in fp.the_geom]
    allb = list(fp.geom)
    bt = STRtree(allb)
    tg = fp.drop_duplicates("bin").set_index("bin").geom
    h = h[h.bin.isin(tg.index)].reset_index(drop=True)
    ix = pd.read_parquet(ROOT / "data" / "harris_mini" / "NYC_SI" / "mapillary_index.parquet")
    ix = ix.dropna(subset=["computed_compass_angle"]).reset_index(drop=True)
    ix["cx"], ix["cy"] = TO(ix.lon.values, ix.lat.values)
    it = STRtree([Point(x, y) for x, y in zip(ix.cx, ix.cy)])
    rows = []
    for b in h.bin:
        f = tg[b]; c = f.centroid
        for j in it.query(f.buffer(DMAX)):
            cam = Point(ix.cx.iat[j], ix.cy.iat[j]); dist = f.distance(cam)
            if not DMIN <= dist <= DMAX:
                continue
            seg = LineString([cam, c]); blocked = False
            for k in bt.query(seg):
                o = allb[k]
                if o.contains(cam):
                    blocked = True; break
                if o.intersection(f).area > 0.3 * min(o.area, f.area):
                    continue
                if o.intersects(seg):
                    blocked = True; break
            if blocked:
                continue
            brg = np.degrees(np.arctan2(c.x - cam.x, c.y - cam.y)) % 360
            angs = [np.degrees(np.arctan2(px - cam.x, py - cam.y)) for px, py in f.exterior.coords]
            half = max(abs((a - brg + 180) % 360 - 180) for a in angs)
            off = (brg - ix.computed_compass_angle.iat[j] + 180) % 360 - 180
            rows.append(dict(bin=b, image_id=ix.id.iat[j], dist_m=dist, bearing=brg, half_w=half, off=off,
                             captured=pd.to_datetime(ix.captured_at.iat[j], unit="ms", utc=True)))
    cand = pd.DataFrame(rows)
    print(f"candidates (6-40 m, line of sight): {len(cand)} for {cand.bin.nunique()} of {len(h)} houses", flush=True)
    ids = sorted(cand.image_id.unique())
    meta = {}
    for s in range(0, len(ids), 50):
        meta.update(graph(ids[s:s + 50], FIELDS))
    cand = cand[cand.image_id.map(lambda i: bool(meta.get(i, {}).get("computed_rotation")))].copy()
    cand["camera_type"] = cand.image_id.map(lambda i: meta[i].get("camera_type"))
    cand["hfov"] = cand.image_id.map(lambda i: hfov(meta[i]))
    cand["roll"] = cand.image_id.map(lambda i: roll_deg(meta[i]["computed_rotation"]))
    ok = ((cand.hfov >= 359) | (cand.off.abs() <= cand.hfov / 2 - 3)) & ~cand.roll.abs().between(45, 135)
    cand = cand[ok].copy()
    cand["rot180"] = cand.roll.abs() > 135
    cand = cand.sort_values(["bin", "captured", "dist_m"], ascending=[True, False, True])
    sel = cand.groupby("bin").head(MAXV).reset_index(drop=True)
    for k in ("width", "height", "camera_parameters", "computed_rotation", "sequence"):
        sel[k] = sel.image_id.map(lambda i, k=k: meta[i].get(k))
    sel["cam_lon"] = sel.image_id.map(lambda i: meta[i]["computed_geometry"]["coordinates"][0])
    sel["cam_lat"] = sel.image_id.map(lambda i: meta[i]["computed_geometry"]["coordinates"][1])
    out = D / "frames"; out.mkdir(exist_ok=True)

    def job(iid):
        p = out / f"{iid}.jpg"
        if p.exists():
            return str(p)
        for url in (meta[iid].get("thumb_original_url"), meta[iid].get("thumb_2048_url")):
            if url:
                try:
                    fetch_img(url).convert("RGB").save(p, quality=92)
                    return str(p)
                except Exception as e:  # noqa: BLE001
                    print("fail", iid, type(e).__name__, file=sys.stderr)
        return None
    uniq = sorted(sel.image_id.unique())
    with ThreadPoolExecutor(8) as ex:
        paths = dict(zip(uniq, ex.map(job, uniq)))
    sel["path"] = sel.image_id.map(paths)
    sel["camera_parameters"] = sel.camera_parameters.map(lambda v: list(v) if v else None)
    sel["computed_rotation"] = sel.computed_rotation.map(lambda v: list(v) if v else None)
    sel["provider"] = "mapillary"
    sel.to_parquet(D / "views.parquet", index=False)
    print(f"selected {len(sel)} views ({len(uniq)} frames) for {sel.bin.nunique()} houses; "
          f"types {sel.camera_type.value_counts().to_dict()}; years {sel.captured.dt.year.value_counts().sort_index().to_dict()}")


if __name__ == "__main__":
    main()
