"""M3 v2 view selection (after the 2026-10-03 review).

Changes from m3_views.py:
- FRONT-SIDE filter (no answer key): the house front is taken to face its nearest TIGER road
  (local / secondary / primary, within 60 m of the footprint). A camera is kept only if the angle
  between (camera - centroid) and (nearest road point - centroid) is <= 60 deg. Houses with no road
  within 60 m keep every candidate.
- Up to MAXV = 4 views per house (was 2).
- FULL-resolution frames for every camera type (thumb_original_url; 2048 px only as a fallback).
- Camera roll: |roll| > 135 deg means the served image is rotated 180 deg against the camera model
  (B's 2026 3616x2712 sequences); flagged rot180 and fixed in m3_measure2. 45-135 deg is skipped.
Output: data/harris_mini/<AREA>/m3_views2.parquet, frames in frames_full/.
Usage: python m3_views2.py AREA N
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree
from shapely import wkt

sys.path.insert(0, str(Path(__file__).parent))
from mapillary_views import D, REF, candidates, fetch_img, graph, sample  # noqa: E402
from m3_views import FIELDS, hfov  # noqa: E402

MAXV = 4
FRONT_DEG = 60.0


def roads(area: str):
    out = []
    for name in ("roads_8", "roads_6", "roads_2"):
        p = D / area / f"{name}.parquet"
        if p.exists():
            for g in pd.read_parquet(p).geometry:
                paths = json.loads(g).get("paths") or []
                if paths:
                    out.append(MultiLineString(paths) if len(paths) > 1 else LineString(paths[0]))
    return out


def roll_deg(rv) -> float:
    R = Rotation.from_rotvec(np.array(rv)).as_matrix()
    up = R @ np.array([0.0, 0.0, 1.0])
    return float(np.degrees(np.arctan2(up[0], -up[1])))


def main(area: str, n: int) -> None:
    hs = sample(area, n)
    cand = candidates(area, hs)
    rd = roads(area)
    rt = STRtree(rd)
    fps = {o: wkt.loads(w) for o, w in zip(hs.oid, hs.fp_wkt)}
    front = {}
    for o, fp in fps.items():
        j = rt.query_nearest(fp, max_distance=60)
        if len(j):
            c = fp.centroid
            q = nearest_points(rd[j[0]], c)[0]
            front[o] = np.degrees(np.arctan2(q.x - c.x, q.y - c.y)) % 360
    ids = sorted(cand.image_id.unique())
    meta: dict = {}
    for s in range(0, len(ids), 50):
        meta.update(graph(ids[s:s + 50], FIELDS))
    cand = cand[cand.image_id.map(lambda i: bool(meta.get(i, {}).get("computed_rotation")))].copy()
    cand["camera_type"] = cand.image_id.map(lambda i: meta[i].get("camera_type"))
    cand["hfov"] = cand.image_id.map(lambda i: hfov(meta[i]))
    cand["roll"] = cand.image_id.map(lambda i: roll_deg(meta[i]["computed_rotation"]))
    # bearing from the house to the camera vs the house's front direction
    cam_dir = (cand.bearing + 180) % 360
    fd = cand.oid.map(front)
    cand["front_off"] = ((cam_dir - fd + 180) % 360 - 180).abs()
    n0 = len(cand)
    ok = ((cand.hfov >= 359) | (cand.off.abs() <= cand.hfov / 2 - 3)) & ~cand.roll.abs().between(45, 135)
    ok &= fd.isna() | (cand.front_off <= FRONT_DEG)
    cand = cand[ok].copy()
    cand["rot180"] = cand.roll.abs() > 135
    cand["age_days"] = (cand.captured - REF).dt.days.abs()
    cand["rank_key"] = (cand.age_days // 182) * 1000 + (cand.dist_m - 20).abs()
    sel = cand.sort_values(["oid", "rank_key"]).groupby("oid").head(MAXV).reset_index(drop=True)
    for k in ("width", "height", "camera_parameters", "computed_rotation", "sequence"):
        sel[k] = sel.image_id.map(lambda i, k=k: meta[i].get(k))
    sel["cam_lon"] = sel.image_id.map(lambda i: meta[i]["computed_geometry"]["coordinates"][0])
    sel["cam_lat"] = sel.image_id.map(lambda i: meta[i]["computed_geometry"]["coordinates"][1])
    out = D / area / "frames_full"
    out.mkdir(exist_ok=True)

    def job(iid: str):
        path = out / f"{iid}.jpg"
        if path.exists():
            return str(path)
        m = meta[iid]
        for url in (m.get("thumb_original_url"), m.get("thumb_2048_url")):
            if not url:
                continue
            try:
                fetch_img(url).convert("RGB").save(path, quality=92)
                return str(path)
            except Exception as e:  # noqa: BLE001
                print("fail", iid, type(e).__name__, file=sys.stderr)
        return None

    uniq = sorted(sel.image_id.unique())
    with ThreadPoolExecutor(8) as ex:
        paths = dict(zip(uniq, ex.map(job, uniq)))
    sel["path"] = sel.image_id.map(paths)
    sel["camera_parameters"] = sel.camera_parameters.map(lambda v: list(v) if v else None)
    sel["computed_rotation"] = sel.computed_rotation.map(lambda v: list(v) if v else None)
    sel.to_parquet(D / area / "m3_views2.parquet", index=False)
    print(f"{area}: {len(hs)} sampled; houses with a road within 60 m {len(front)}; candidates {n0} -> "
          f"{len(cand)} after FOV/roll/front filters; selected {len(sel)} views for {sel.oid.nunique()} houses "
          f"({int(sel.rot180.sum())} rot180); types {sel.camera_type.value_counts().to_dict()}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
