"""M3: measure the front-door bottom from street images (ELEV-VISION-SAM-style, reimplemented).

For every (house, view) in m3_views.parquet:
1. Render a LEVEL virtual pinhole view (no pitch/roll) from the source frame, aimed at the house
   (world azimuth of the footprint centroid), using the frame's camera model and Mapillary's
   computed_rotation (OpenSfM angle-axis, world->camera; world = local ENU). In that view a pixel
   row maps exactly to an elevation angle and a column to an azimuth.
2. Grounding DINO (IDEA-Research/grounding-dino-tiny, Apache-2.0) finds "door" and "house" boxes;
   SAM 2.1 hiera-tiny (Apache-2.0) refines each box to a mask.
3. The door is the best-scoring door box whose bottom-centre ray, cast in 2-D from the camera,
   hits the TARGET footprint before any other building (HCAD 2017 + lidar 2018 outlines);
   R = horizontal distance to that wall point.
4. Heights relative to the camera: door bottom dz_door = R tan(elev_door); wall-ground line
   (bottom of the house mask in the door's columns) dz_ground = R tan(elev_ground).
   FFH_img = dz_door - dz_ground (camera height cancels; pitch error largely cancels).
   Lidar (2018 1 m DEM): G_wall at the wall point 1 m toward the camera, G_cam under the camera.
   Outputs per view: ffh_img_ft, g_wall_ft, dz_door_ft, dz_ground_ft, g_cam_ft, R_m, scores.
The answer key is NOT read here. Output: data/harris_mini/<AREA>/m3_measure.parquet.
Usage: python m3_measure.py AREA [LIMIT]
"""
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
import torch
from PIL import Image
from pyproj import Transformer
from scipy.spatial.transform import Rotation
from shapely import wkt
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor, Sam2Model, Sam2Processor

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
USFT = 1200 / 3937
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:6344", always_xy=True)
VW, VH = 1280, 960
torch.set_num_threads(2)


# ---------- camera models (OpenSfM conventions; camera frame x right, y down, z forward) ----------
def project(dc: np.ndarray, ctype: str, cp: list, w: int, h: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Camera-frame unit rays (N,3) -> pixel u, v in the source image, and a validity mask."""
    s = max(w, h)
    x, y, z = dc[:, 0], dc[:, 1], dc[:, 2]
    if ctype in ("spherical", "equirectangular"):
        lon = np.arctan2(x, z)
        lat = np.arctan2(-y, np.hypot(x, z))
        xn, yn = lon / (2 * np.pi), -lat / (2 * np.pi)
        ok = np.ones_like(x, dtype=bool)
    elif ctype == "fisheye":
        f, k1, k2 = (list(cp) + [0, 0, 0])[:3]
        r = np.hypot(x, y)
        th = np.arctan2(r, z)
        d = f * th * (1 + k1 * th**2 + k2 * th**4)
        with np.errstate(invalid="ignore", divide="ignore"):
            xn, yn = np.where(r > 0, d * x / r, 0), np.where(r > 0, d * y / r, 0)
        ok = th < np.radians(95)
    else:  # perspective / brown
        f, k1, k2 = (list(cp) + [0, 0, 0])[:3]
        with np.errstate(invalid="ignore", divide="ignore"):
            xp, yp = x / z, y / z
        r2 = xp**2 + yp**2
        dist = 1 + k1 * r2 + k2 * r2**2
        xn, yn = f * dist * xp, f * dist * yp
        ok = (z > 0.05) & (r2 < 4)
    u = xn * s + w / 2 - 0.5
    v = yn * s + h / 2 - 0.5
    ok &= (u >= 0) & (u <= w - 1) & (v >= 0) & (v <= h - 1)
    return u, v, ok


def level_view(img: np.ndarray, Rwc: np.ndarray, ctype: str, cp: list, az_deg: float, hfov: float):
    """Render a level pinhole view looking at world azimuth az (deg from north, clockwise)."""
    h, w = img.shape[:2]
    f = VW / 2 / np.tan(np.radians(hfov / 2))
    i, j = np.meshgrid(np.arange(VW) + 0.5 - VW / 2, np.arange(VH) + 0.5 - VH / 2)
    az = np.radians(az_deg)
    fwd = np.array([np.sin(az), np.cos(az), 0.0])
    right = np.array([np.cos(az), -np.sin(az), 0.0])
    up = np.array([0.0, 0.0, 1.0])
    dw = (fwd[None, None] * f + right[None, None] * i[..., None] - up[None, None] * j[..., None]).reshape(-1, 3)
    dw /= np.linalg.norm(dw, axis=1, keepdims=True)
    dc = dw @ Rwc.T
    u, v, ok = project(dc, ctype, cp, w, h)
    u, v = np.clip(u, 0, w - 1.001), np.clip(v, 0, h - 1.001)
    u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
    du, dv = (u - u0)[:, None], (v - v0)[:, None]
    a = img.astype(np.float32)
    out = (a[v0, u0] * (1 - du) * (1 - dv) + a[v0, u0 + 1] * du * (1 - dv)
           + a[v0 + 1, u0] * (1 - du) * dv + a[v0 + 1, u0 + 1] * du * dv)
    out[~ok] = 128
    coverage = ok.reshape(VH, VW)
    return Image.fromarray(out.reshape(VH, VW, 3).clip(0, 255).astype(np.uint8)), f, coverage


def pix_to_angles(col: float, row: float, f: float, az_deg: float) -> tuple[float, float]:
    """Level virtual view pixel -> (world azimuth deg, elevation rad)."""
    x, y = col + 0.5 - VW / 2, row + 0.5 - VH / 2
    return az_deg + np.degrees(np.arctan2(x, f)), float(np.arctan2(-y, np.hypot(x, f)))


# ---------- scene ----------
def buildings(area: str) -> list[Polygon]:
    out = []
    for name in ("l25.parquet", "l26.parquet"):
        for r in pq.read_table(D / area / name, columns=["rings"]).to_pylist():
            if r["rings"]:
                rings = json.loads(r["rings"])
                p = Polygon(rings[0], rings[1:]).buffer(0)
                if p.area > 20:
                    out.append(p)
    return out


def first_hit(cam: Point, az_deg: float, target: Polygon, blds: list, btree: STRtree, maxd: float = 80.0):
    """Cast a 2-D ray; return (distance to the target wall, hit point) if the target is hit first."""
    az = np.radians(az_deg)
    end = Point(cam.x + maxd * np.sin(az), cam.y + maxd * np.cos(az))
    ray = LineString([cam, end])
    best_d, best_is_target, best_pt = np.inf, False, None
    cands = [blds[k] for k in btree.query(ray)] + [target]
    for b in cands:
        inter = ray.intersection(b.exterior) if b.geom_type == "Polygon" else ray.intersection(b.boundary)
        if inter.is_empty:
            continue
        pts = [inter] if inter.geom_type == "Point" else list(getattr(inter, "geoms", []))
        for p in pts:
            if p.geom_type != "Point":
                continue
            d = cam.distance(p)
            is_t = b.equals(target) or b.intersection(target).area > 0.5 * min(b.area, target.area)
            if d < best_d - 0.3 or (abs(d - best_d) <= 0.3 and is_t):
                best_d, best_is_target, best_pt = d, is_t, p
    return (best_d, best_pt) if best_is_target else (None, None)


class DEM:
    def __init__(self, area: str):
        self.srcs = [rasterio.open(f) for f in glob.glob(str(D / area / "*2018*.tif"))]

    def at(self, x: float, y: float) -> float:
        for s in self.srcs:
            b = s.bounds
            if b.left < x < b.right and b.bottom < y < b.top:
                v = next(s.sample([(x, y)]))[0]
                return float(v) / USFT if v > -1e5 else np.nan
        return np.nan


def mask_bottom(mask: np.ndarray, c0: float, c1: float) -> float:
    """Median over the middle 60% of columns [c0, c1] of the lowest mask row."""
    a, b = int(c0 + 0.2 * (c1 - c0)), int(c1 - 0.2 * (c1 - c0)) + 1
    rows = []
    for c in range(max(a, 0), min(b, mask.shape[1])):
        r = np.nonzero(mask[:, c])[0]
        if r.size:
            rows.append(r.max())
    return float(np.median(rows)) if rows else np.nan


def main(area: str, limit: int | None) -> None:
    views = pd.read_parquet(D / area / "m3_views.parquet")
    views = views[views.path.notna()]
    if limit:
        views = views.head(limit)
    houses = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "fp_wkt"]).set_index("oid")
    blds = buildings(area)
    btree = STRtree(blds)
    dem = DEM(area)
    dp = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
    dm = AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-tiny").eval()
    sp = Sam2Processor.from_pretrained("facebook/sam2.1-hiera-tiny")
    sm = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny").eval()
    out_path = D / area / "m3_measure.parquet"
    done = pd.read_parquet(out_path) if out_path.exists() else pd.DataFrame()
    seen = set(zip(done.get("oid", []), done.get("image_id", [])))
    vdir = D / area / "m3_virtual"
    vdir.mkdir(exist_ok=True)
    rows, t0, cache = [], time.time(), {}
    for n, r in enumerate(views.itertuples()):
        if (r.oid, r.image_id) in seen:
            continue
        rec = dict(oid=r.oid, image_id=r.image_id, camera_type=r.camera_type, sequence=r.sequence,
                   captured=r.captured, status="ok")
        try:
            fp = wkt.loads(houses.loc[r.oid, "fp_wkt"])
            cx, cy = TO_UTM.transform(r.cam_lon, r.cam_lat)
            cam = Point(cx, cy)
            c = fp.centroid
            az = float(np.degrees(np.arctan2(c.x - cx, c.y - cy)) % 360)
            angs = [np.degrees(np.arctan2(px - cx, py - cy)) for px, py in fp.exterior.coords]
            half = max(abs((a - az + 180) % 360 - 180) for a in angs)
            hfov = float(np.clip(2 * half + 25, 50, 100))
            if r.image_id not in cache:
                cache.clear()
                cache[r.image_id] = np.asarray(Image.open(r.path).convert("RGB"))
            Rwc = Rotation.from_rotvec(np.array(r.computed_rotation)).as_matrix()
            vimg, f, cov = level_view(cache[r.image_id], Rwc, r.camera_type, r.camera_parameters, az, hfov)
            rec.update(R_cam_m=cam.distance(fp), view_cov=float(cov.mean()),
                       compass_check=float((np.degrees(np.arctan2(*(Rwc.T @ [0, 0, 1])[:2])) - r.compass + 180) % 360 - 180))
            if cov.mean() < 0.3:
                rec["status"] = "view_out_of_frame"
                rows.append(rec)
                continue
            vimg.save(vdir / f"{r.oid}_{r.image_id}.jpg", quality=88)
            with torch.no_grad():
                inp = dp(images=vimg, text="a door. a house.", return_tensors="pt")
                res = dp.post_process_grounded_object_detection(
                    dm(**inp), inp.input_ids, threshold=0.25, text_threshold=0.2, target_sizes=[(VH, VW)])[0]
            labels = res.get("text_labels", res.get("labels"))
            boxes, scores = res["boxes"].numpy(), res["scores"].numpy()
            doors, housebox = [], None
            for b, s, lab in zip(boxes, scores, labels):
                lab = str(lab)
                bc = (b[0] + b[2]) / 2
                a_az, _ = pix_to_angles(bc, b[3], f, az)
                if "door" in lab and "garage" not in lab:
                    if (b[3] - b[1]) < 1.2 * (b[2] - b[0]):
                        continue  # wider than tall: garage door or window band
                    R, hit = first_hit(cam, a_az, fp, blds, btree)
                    if R is not None:
                        doors.append((s, b, R, hit))
                elif "house" in lab:
                    R, _ = first_hit(cam, a_az, fp, blds, btree)
                    if R is not None and (housebox is None or s > housebox[0]):
                        housebox = (s, b)
            if not doors:
                rec["status"] = "no_door_on_target"
                rows.append(rec)
                continue
            s, db, R, hit = max(doors, key=lambda t: t[0])
            prompt = [[list(map(float, db))]] + ([] if housebox is None else [])
            boxes_in = [list(map(float, db))] + ([list(map(float, housebox[1]))] if housebox else [])
            with torch.no_grad():
                si = sp(images=vimg, input_boxes=[boxes_in], return_tensors="pt")
                so = sm(**si, multimask_output=False)
            masks = sp.post_process_masks(so.pred_masks, si["original_sizes"])[0][:, 0].numpy() > 0
            door_row = mask_bottom(masks[0], db[0], db[2])
            if not np.isfinite(door_row):
                door_row = float(db[3])
            ground_row = mask_bottom(masks[1], db[0], db[2]) if housebox else np.nan
            _, e_door = pix_to_angles((db[0] + db[2]) / 2, door_row, f, az)
            dz_door = R * np.tan(e_door)
            dz_ground = np.nan
            if np.isfinite(ground_row) and ground_row > door_row:
                _, e_g = pix_to_angles((db[0] + db[2]) / 2, ground_row, f, az)
                dz_ground = R * np.tan(e_g)
            # lidar ground at the wall point, stepped 1 m toward the camera
            ux, uy = (cam.x - hit.x) / max(R, 1e-6), (cam.y - hit.y) / max(R, 1e-6)
            g_wall = dem.at(hit.x + ux, hit.y + uy)
            g_cam = dem.at(cam.x, cam.y)
            rec.update(door_score=float(s), house_score=float(housebox[0]) if housebox else np.nan,
                       R_m=float(R), door_box_rows=float(db[3] - db[1]), door_row=door_row, ground_row=ground_row,
                       dz_door_ft=dz_door / USFT, dz_ground_ft=dz_ground / USFT,
                       ffh_img_ft=(dz_door - dz_ground) / USFT if np.isfinite(dz_ground) else np.nan,
                       g_wall_ft=g_wall, g_cam_ft=g_cam)
        except Exception as e:  # noqa: BLE001
            rec["status"] = f"error:{type(e).__name__}:{str(e)[:80]}"
        rows.append(rec)
        if len(rows) % 25 == 0:
            pd.concat([done, pd.DataFrame(rows)]).to_parquet(out_path, index=False)
            el = time.time() - t0
            print(f"{area}: {len(rows)} views in {el:.0f}s ({el / len(rows):.1f}s/view); "
                  f"status {pd.DataFrame(rows).status.value_counts().to_dict()}", flush=True)
    pd.concat([done, pd.DataFrame(rows)]).to_parquet(out_path, index=False)
    print(f"{area}: done, {len(rows)} new views")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
