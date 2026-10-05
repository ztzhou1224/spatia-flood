"""Several Mapillary views per house for the triage list + controls (same houses as beemaps_multi.py), rendered correctly.

Mapillary imagery is CC BY-SA 4.0 (attribution; share-alike on derived data). Rows are tagged provider=mapillary.
The token comes from MAPILLARY_ACCESS_TOKEN (repo .env) and is never printed; the answer key is never read.
Per house:
1. candidates as mapillary_views.candidates (area index + a small local query; camera 8-45 m from the footprint,
   line of sight to the centroid not crossing another footprint);
2. image metadata: camera_type, camera_parameters (focal, k1, k2), computed_rotation (OpenSfM angle-axis,
   world -> camera), computed_geometry (SfM-corrected position), captured_at; images without a computed pose are
   dropped (their direction is not known well enough to centre the house);
3. up to K images, diversified: at most 2 per sequence, panoramas first, then the smallest |distance - 18 m|;
4. each image re-rendered as a LEVEL, undistorted virtual view aimed at the footprint centroid with the camera model
   and the SfM rotation (m3_measure.level_view), field of view = footprint angular width + 2 x 8 deg (25-70 deg);
   an audit copy marks the footprint's left / right edges (magenta) to check the house matching by eye; views whose
   central third is < 80% covered by the source image (house outside the camera's field of view) are dropped, and so
   are views whose SfM rotation puts the camera's down axis less than 60 deg below horizontal (bad pose).
   Images are fetched at full resolution (thumb_original_url).
Output: data/harris_mini/<AREA>/mapillary_multi.parquet, views in mapillary_multi/ (audit copies in mapillary_multi_audit/).
Usage: python mapillary_multi.py AREA K
"""
import sys

import numpy as np
import pandas as pd
from m3_measure import VW, level_view
from mapillary_views import TO_UTM, D, candidates, fetch_img, graph
from PIL import ImageDraw
from scipy.spatial.transform import Rotation
from shapely import wkt

FIELDS = ("id,width,height,camera_type,camera_parameters,computed_rotation,computed_geometry,captured_at,sequence,"
          "thumb_2048_url,thumb_original_url")


def main(area: str, k: int):
    out, aud = D / area / "mapillary_multi", D / area / "mapillary_multi_audit"
    out.mkdir(exist_ok=True)
    aud.mkdir(exist_ok=True)
    tried = pd.read_parquet(D / area / "beemaps_multi.parquet").drop_duplicates("oid")[["oid", "group"]]
    hs = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "fp_wkt"]).merge(tried, on="oid")
    cand = candidates(area, hs)
    print(f"{area}: houses {len(hs)}; candidate images {len(cand)}; houses with >= 1 candidate {cand.oid.nunique()}")
    ids = cand.image_id.astype(str).unique().tolist()
    meta = {}
    for s in range(0, len(ids), 50):
        meta.update(graph(ids[s:s + 50], FIELDS))
    cand["has_pose"] = cand.image_id.astype(str).map(lambda i: bool(meta.get(i, {}).get("computed_rotation")))
    cand["sequence"] = cand.image_id.astype(str).map(lambda i: meta.get(i, {}).get("sequence"))
    fps = hs.set_index("oid").fp_wkt
    rows, n_flipped = [], 0
    for oid, g in cand[cand.has_pose].groupby("oid"):
        g = g.assign(pref=(~g.is_pano).astype(int), dd=(g.dist_m - 18).abs()).sort_values(["pref", "dd"])
        chosen, per_seq = [], {}
        for r in g.itertuples():
            if per_seq.get(r.sequence, 0) >= 2:
                continue
            chosen.append(r)
            per_seq[r.sequence] = per_seq.get(r.sequence, 0) + 1
            if len(chosen) == k:
                break
        fp = wkt.loads(fps[oid])
        c = fp.centroid
        for r in chosen:
            m = meta[str(r.image_id)]
            lon, lat = m["computed_geometry"]["coordinates"]
            cx, cy = TO_UTM.transform(lon, lat)
            az = np.degrees(np.arctan2(c.x - cx, c.y - cy)) % 360
            angs = [(np.degrees(np.arctan2(px - cx, py - cy)) - az + 180) % 360 - 180 for px, py in fp.exterior.coords]
            hfov = float(np.clip(max(abs(a) for a in angs) * 2 + 16, 25, 70))
            # full resolution: a 2048 px thumbnail of a 360 deg panorama is ~5.7 px per degree, too blurry for steps
            img = np.asarray(fetch_img(m.get("thumb_original_url") or m["thumb_2048_url"]).convert("RGB"))
            ctype = "spherical" if r.is_pano else (m.get("camera_type") or "perspective")
            Rwc = Rotation.from_rotvec(np.array(m["computed_rotation"])).as_matrix()
            view, f, cov = level_view(img, Rwc, ctype, m.get("camera_parameters") or [], az, hfov)
            ccov = float(cov[:, VW // 3: 2 * VW // 3].mean())
            if ccov < 0.8:  # the house is outside this camera's field of view
                continue
            # pose sanity: the camera's "down" axis (row 1 of world->camera) must point down in the world; a wrong SfM
            # rotation (seen: a 2026 phone image rendered upside down) fails this. (A brightness test was tried first
            # and rejected: it dropped upright views with a dark tree canopy over a bright lawn.)
            if Rwc[1, 2] > -0.5:
                n_flipped += 1
                view.save(aud / f"{oid}_{r.image_id}_DROPPED_bad_pose.jpg", quality=85)
                continue
            p = out / f"{oid}_{r.image_id}.jpg"
            view.save(p, quality=92)
            a = view.copy()
            d = ImageDraw.Draw(a)
            for ang in (min(angs), max(angs)):
                col = VW / 2 + f * np.tan(np.radians(ang))
                d.line([(col, 0), (col, a.height)], fill=(255, 0, 255), width=3)
            a.save(aud / f"{oid}_{r.image_id}.jpg", quality=85)
            rows.append({"oid": oid, "group": hs.set_index("oid").group[oid], "sequence": str(r.image_id), "idx": 0,
                         "image_id": str(r.image_id), "is_pano": bool(r.is_pano), "camera_type": ctype,
                         "captured": pd.to_datetime(m.get("captured_at"), unit="ms", utc=True), "dist_m": r.dist_m,
                         "hfov": hfov, "centre_coverage": ccov, "path": str(p)})
    df = pd.DataFrame(rows).assign(provider="mapillary")
    df.to_parquet(D / area / "mapillary_multi.parquet", index=False)
    per = df.groupby("oid").size()
    seen = df.groupby("group").oid.nunique()
    print(f"houses with a rendered view: {per.size} ({seen.to_dict()} of {tried.group.value_counts().to_dict()}); views per house "
          f"median {per.median():.0f}, max {per.max()}; panoramas {df.is_pano.mean():.0%}; candidates without a pose "
          f"dropped {int((~cand.has_pose).sum())} of {len(cand)}; views dropped for a bad pose (camera down axis not down) {n_flipped}")
    print("capture years:", df.captured.dt.year.value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
