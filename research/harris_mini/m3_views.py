"""Full-frame Mapillary views + camera geometry for M3 (ELEV-VISION-SAM-style measurement).

Reuses mapillary_views.sample/candidates (same seeded random house order, same geometric and
occlusion filters; the answer key is never read). Unlike mapillary_views.py it keeps the WHOLE
image (no crop) and the camera model needed to turn a pixel into a ray:
camera_type, camera_parameters, computed_rotation (OpenSfM angle-axis, world->camera),
computed_geometry (camera position), sequence. Images are downloaded once per image id.
Output: data/harris_mini/<AREA>/m3_views.parquet, images in data/harris_mini/<AREA>/frames/.
Usage: python m3_views.py AREA N
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from mapillary_views import D, MAXV, REF, candidates, fetch_img, graph, sample  # noqa: E402

FIELDS = ("id,width,height,camera_type,camera_parameters,computed_rotation,computed_geometry,"
          "computed_compass_angle,sequence,captured_at,thumb_2048_url,thumb_original_url")


def hfov(m: dict) -> float:
    if m.get("camera_type") in ("spherical", "equirectangular"):
        return 360.0
    cp = m.get("camera_parameters") or []
    if not cp or cp[0] <= 0:
        return np.nan
    w, h = m.get("width") or 1, m.get("height") or 1
    return 2 * np.degrees(np.arctan(0.5 * w / max(w, h) / cp[0]))


def main(area: str, n: int) -> None:
    hs = sample(area, n)
    hs[["oid", "rank"]].to_csv(D / area / "image_sample.csv", index=False)
    cand = candidates(area, hs)
    ids = sorted(cand.image_id.unique())
    meta: dict = {}
    for s in range(0, len(ids), 50):
        meta.update(graph(ids[s:s + 50], FIELDS))
    cand["camera_type"] = cand.image_id.map(lambda i: meta.get(i, {}).get("camera_type"))
    cand["hfov"] = cand.image_id.map(lambda i: hfov(meta.get(i, {})))
    has_pose = cand.image_id.map(lambda i: bool(meta.get(i, {}).get("computed_rotation")))
    inview = (cand.hfov >= 359) | (cand.off.abs() <= cand.hfov / 2 - 3)
    cand = cand[inview & has_pose].copy()
    cand["age_days"] = (cand.captured - REF).dt.days.abs()
    cand["rank_key"] = (cand.age_days // 182) * 1000 + (cand.dist_m - 20).abs()
    sel = cand.sort_values(["oid", "rank_key"]).groupby("oid").head(MAXV).reset_index(drop=True)
    for k in ("width", "height", "camera_parameters", "computed_rotation", "sequence"):
        sel[k] = sel.image_id.map(lambda i, k=k: meta[i].get(k))
    sel["cam_lon"] = sel.image_id.map(lambda i: meta[i]["computed_geometry"]["coordinates"][0])
    sel["cam_lat"] = sel.image_id.map(lambda i: meta[i]["computed_geometry"]["coordinates"][1])
    out = D / area / "frames"
    out.mkdir(exist_ok=True)

    def job(iid: str) -> str | None:
        path = out / f"{iid}.jpg"
        if path.exists():
            return str(path)
        m = meta[iid]
        url = m.get("thumb_original_url") if m.get("camera_type") == "spherical" else m.get("thumb_2048_url")
        try:
            fetch_img(url or m["thumb_2048_url"]).convert("RGB").save(path, quality=92)
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
    sel.to_parquet(D / area / "m3_views.parquet", index=False)
    print(f"{area}: {len(hs)} sampled houses, {sel.oid.nunique()} with a posed view in FOV; "
          f"{len(sel)} views, {len(uniq)} unique frames; camera types "
          f"{sel.camera_type.value_counts().to_dict()}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
