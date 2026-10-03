"""M3 v2 measurement (after the 2026-10-03 review). Builds on m3_measure.py; changes:

1. Camera roll: frames flagged rot180 (m3_views2) are rotated 180 deg before rendering.
2. Spherical seam: panorama sampling wraps around the 360 deg seam instead of clamping.
3. Prompts "door. garage door. house." Garage doors on the target give a second ground reference
   (garage slab bottom ~ the driveway apron).
4. Door-scale gate: an 80-inch (2.032 m) door seen between rows top/bottom implies
   R_door = 2.032 / (tan e_top - tan e_bottom). ratio = R_door / R_footprint is stored; a door whose
   ratio is far from 1 is a wrong door, a recessed door or a bad R.
5. Highest-door rule: among doors on the target that pass the gate (0.75 <= ratio <= 1.33), the one
   with the HIGHEST bottom (largest elevation angle) is taken: on raised houses the front door is at
   the top of the stairs, an enclosure door below it. If none pass, the best-scoring door is kept and
   flagged ungated.
6. Dark frames (mean luminance of the virtual view < 60) are skipped.
Per view: ffh_house_ft (ground = house-mask bottom), ffh_garage_ft (ground = garage-door bottom),
ffh_doorscale_ft (house ground, R from the door scale), ratio, gated, cam_h_ft checks inputs.
The answer key is NOT read here. Output: data/harris_mini/<AREA>/m3_measure2.parquet
Usage: python m3_measure2.py AREA [LIMIT]
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image
from scipy.spatial.transform import Rotation
from shapely import wkt
from shapely.geometry import Point
from shapely.strtree import STRtree
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor, Sam2Model, Sam2Processor

sys.path.insert(0, str(Path(__file__).parent))
from m3_measure import D, DEM, TO_UTM, USFT, VH, VW, buildings, first_hit, mask_bottom, pix_to_angles, project  # noqa: E402

DOOR_M = 2.032
torch.set_num_threads(2)


def level_view(img: np.ndarray, Rwc, ctype, cp, az_deg, hfov):
    h, w = img.shape[:2]
    f = VW / 2 / np.tan(np.radians(hfov / 2))
    i, j = np.meshgrid(np.arange(VW) + 0.5 - VW / 2, np.arange(VH) + 0.5 - VH / 2)
    az = np.radians(az_deg)
    fwd, right, up = np.array([np.sin(az), np.cos(az), 0.0]), np.array([np.cos(az), -np.sin(az), 0.0]), np.array([0.0, 0, 1])
    dw = (fwd[None, None] * f + right[None, None] * i[..., None] - up[None, None] * j[..., None]).reshape(-1, 3)
    dw /= np.linalg.norm(dw, axis=1, keepdims=True)
    dc = dw @ Rwc.T
    pano = ctype in ("spherical", "equirectangular")
    if pano:  # wrap the seam: compute u, v directly
        s = max(w, h)
        lon = np.arctan2(dc[:, 0], dc[:, 2]); lat = np.arctan2(-dc[:, 1], np.hypot(dc[:, 0], dc[:, 2]))
        u = (lon / (2 * np.pi)) * s + w / 2 - 0.5
        v = (-lat / (2 * np.pi)) * s + h / 2 - 0.5
        ok = (v >= 0) & (v <= h - 1.001)
        u = np.mod(u, w)
    else:
        u, v, ok = project(dc, ctype, cp, w, h)
        u = np.clip(u, 0, w - 1.001)
    v = np.clip(v, 0, h - 1.001)
    u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
    u1 = (u0 + 1) % w if pano else np.minimum(u0 + 1, w - 1)
    du, dv = (u - u0)[:, None], (v - v0)[:, None]
    a = img.astype(np.float32)
    out = (a[v0, u0] * (1 - du) * (1 - dv) + a[v0, u1] * du * (1 - dv) + a[v0 + 1, u0] * (1 - du) * dv + a[v0 + 1, u1] * du * dv)
    out[~ok] = 128
    return Image.fromarray(out.reshape(VH, VW, 3).clip(0, 255).astype(np.uint8)), f, ok.reshape(VH, VW)


def main(area: str, limit: int | None) -> None:
    views = pd.read_parquet(D / area / "m3_views2.parquet")
    views = views[views.path.notna()]
    if limit:
        views = views.head(limit)
    houses = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "fp_wkt"]).set_index("oid")
    blds = buildings(area); btree = STRtree(blds); dem = DEM(area)
    dp = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
    dm = AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-tiny").eval()
    sp = Sam2Processor.from_pretrained("facebook/sam2.1-hiera-tiny")
    sm = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny").eval()
    out_path = D / area / "m3_measure2.parquet"
    done = pd.read_parquet(out_path) if out_path.exists() else pd.DataFrame()
    seen = set(zip(done.get("oid", []), done.get("image_id", [])))
    vdir = D / area / "m3_virtual2"; vdir.mkdir(exist_ok=True)
    rows, t0, cache = [], time.time(), {}
    for r in views.itertuples():
        if (r.oid, r.image_id) in seen:
            continue
        rec = dict(oid=r.oid, image_id=r.image_id, camera_type=r.camera_type, sequence=r.sequence,
                   captured=r.captured, rot180=bool(r.rot180), status="ok")
        try:
            fp = wkt.loads(houses.loc[r.oid, "fp_wkt"])
            cx, cy = TO_UTM.transform(r.cam_lon, r.cam_lat); cam = Point(cx, cy); c = fp.centroid
            az = float(np.degrees(np.arctan2(c.x - cx, c.y - cy)) % 360)
            angs = [np.degrees(np.arctan2(px - cx, py - cy)) for px, py in fp.exterior.coords]
            half = max(abs((a - az + 180) % 360 - 180) for a in angs)
            hfov = float(np.clip(2 * half + 25, 50, 100))
            if r.image_id not in cache:
                cache.clear()
                im = np.asarray(Image.open(r.path).convert("RGB"))
                cache[r.image_id] = np.rot90(im, 2).copy() if r.rot180 else im
            Rwc = Rotation.from_rotvec(np.array(r.computed_rotation)).as_matrix()
            vimg, f, cov = level_view(cache[r.image_id], Rwc, r.camera_type, r.camera_parameters, az, hfov)
            lum = float(np.asarray(vimg.convert("L"))[cov].mean()) if cov.any() else 0.0
            rec.update(view_cov=float(cov.mean()), luminance=lum, R_cam_m=cam.distance(fp))
            if cov.mean() < 0.3:
                rec["status"] = "view_out_of_frame"; rows.append(rec); continue
            if lum < 60:
                rec["status"] = "dark"; rows.append(rec); continue
            vimg.save(vdir / f"{r.oid}_{r.image_id}.jpg", quality=88)
            with torch.no_grad():
                inp = dp(images=vimg, text="a door. a garage door. a house.", return_tensors="pt")
                res = dp.post_process_grounded_object_detection(dm(**inp), inp.input_ids, threshold=0.25,
                                                                 text_threshold=0.2, target_sizes=[(VH, VW)])[0]
            labels = [str(x) for x in res.get("text_labels", res.get("labels"))]
            doors, garages, housebox = [], [], None
            for b, s, lab in zip(res["boxes"].numpy(), res["scores"].numpy(), labels):
                bc = (b[0] + b[2]) / 2
                a_az, e_bot = pix_to_angles(bc, b[3], f, az)
                R, hit = first_hit(cam, a_az, fp, blds, btree)
                if R is None:
                    continue
                if "garage" in lab:
                    garages.append((s, b, R))
                elif "door" in lab:
                    if (b[3] - b[1]) < 1.2 * (b[2] - b[0]):
                        continue
                    _, e_top = pix_to_angles(bc, b[1], f, az)
                    r_door = DOOR_M / max(np.tan(e_top) - np.tan(e_bot), 1e-6)
                    doors.append(dict(s=s, b=b, R=R, hit=hit, e_bot=e_bot, ratio=r_door / R))
                elif "house" in lab and (housebox is None or s > housebox[0]):
                    housebox = (s, b)
            if not doors:
                rec["status"] = "no_door_on_target"; rows.append(rec); continue
            gated = [d for d in doors if 0.75 <= d["ratio"] <= 1.33 and d["s"] >= 0.3]
            d = max(gated, key=lambda t: t["e_bot"]) if gated else max(doors, key=lambda t: t["s"])
            g = max(garages, key=lambda t: t[0]) if garages else None
            boxes_in = [list(map(float, d["b"]))] + ([list(map(float, housebox[1]))] if housebox else []) \
                + ([list(map(float, g[1]))] if g else [])
            with torch.no_grad():
                si = sp(images=vimg, input_boxes=[boxes_in], return_tensors="pt")
                so = sm(**si, multimask_output=False)
            masks = sp.post_process_masks(so.pred_masks, si["original_sizes"])[0][:, 0].numpy() > 0
            db = d["b"]; R = d["R"]; hit = d["hit"]
            door_row = mask_bottom(masks[0], db[0], db[2])
            if not np.isfinite(door_row):
                door_row = float(db[3])
            _, e_door = pix_to_angles((db[0] + db[2]) / 2, door_row, f, az)
            dz_door = R * np.tan(e_door)
            _, e_top = pix_to_angles((db[0] + db[2]) / 2, db[1], f, az)
            R_ds = DOOR_M / max(np.tan(e_top) - np.tan(e_door), 1e-6)
            ffh_house = ffh_ds = ffh_gar = dz_g = np.nan
            if housebox is not None:
                grow = mask_bottom(masks[1], db[0], db[2])
                if np.isfinite(grow) and grow > door_row:
                    _, e_g = pix_to_angles((db[0] + db[2]) / 2, grow, f, az)
                    dz_g = R * np.tan(e_g)
                    ffh_house = (dz_door - dz_g) / USFT
                    ffh_ds = R_ds * (np.tan(e_door) - np.tan(e_g)) / USFT
            if g is not None:
                gm = masks[-1]; gb = g[1]
                grow = mask_bottom(gm, gb[0], gb[2])
                if not np.isfinite(grow):
                    grow = float(gb[3])
                _, e_gg = pix_to_angles((gb[0] + gb[2]) / 2, grow, f, az)
                ffh_gar = (dz_door - g[2] * np.tan(e_gg)) / USFT
            ux, uy = (cam.x - hit.x) / max(R, 1e-6), (cam.y - hit.y) / max(R, 1e-6)
            rec.update(door_score=float(d["s"]), n_doors=len(doors), gated=bool(gated), ratio=float(d["ratio"]),
                       R_m=float(R), R_doorscale_m=float(R_ds), has_garage=g is not None,
                       dz_door_ft=dz_door / USFT, dz_ground_ft=dz_g / USFT if np.isfinite(dz_g) else np.nan,
                       ffh_house_ft=ffh_house, ffh_garage_ft=ffh_gar, ffh_doorscale_ft=ffh_ds,
                       g_wall_ft=dem.at(hit.x + ux, hit.y + uy), g_cam_ft=dem.at(cam.x, cam.y))
        except Exception as e:  # noqa: BLE001
            rec["status"] = f"error:{type(e).__name__}:{str(e)[:80]}"
        rows.append(rec)
        if len(rows) % 25 == 0:
            pd.concat([done, pd.DataFrame(rows)]).to_parquet(out_path, index=False)
            el = time.time() - t0
            print(f"{area}: {len(rows)} views in {el:.0f}s; status {pd.DataFrame(rows).status.value_counts().to_dict()}", flush=True)
    pd.concat([done, pd.DataFrame(rows)]).to_parquet(out_path, index=False)
    print(f"{area}: done, {len(rows)} new views")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else None)
