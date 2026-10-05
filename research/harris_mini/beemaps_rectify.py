"""Rectified, target-centred views from Bee Maps frames (fixes the crop of beemaps_multi.py).

beemaps_multi.py cropped columns with a pinhole formula and the GPS heading. The Bee camera has strong lens
distortion (OpenCV rational + thin-prism + tilt model from /devices) and each frame has its own camera yaw / pitch /
roll relative to the GPS heading; the audit (audit_beemaps.py) found the crop centre a median ~100 px (up to ~270 px)
from the target. Here every frame is re-rendered as a LEVEL virtual pinhole view aimed at the target footprint:
  ray of each output pixel (virtual camera at azimuth = bearing to the footprint centroid, level)
  -> source camera frame (azimuth = GPS heading + yaw, then pitch, then roll)
  -> source pixel via cv2.projectPoints with the device distortion -> cv2.remap.
Field of view = angular width of the footprint + 2 x 8 deg margin (25-70 deg). Pitch sign is checked on the frames
themselves (horizon of the virtual view must stay level / at the image centre row); see PITCH_SIGN.
Raw frames are downloaded once to data/harris_mini/<AREA>/beemaps_raw/ (one billed view each, provider=beemaps).
Output: data/harris_mini/<AREA>/beemaps_rect/<oid>_<sequence>_<idx>.jpg and beemaps_rect.parquet.
Usage: python beemaps_rectify.py AREA [PITCH_SIGN]
"""
import json
import sys
import time

import cv2
import numpy as np
import pandas as pd
import requests
from audit_beemaps import camera
from beemaps_multi import API, LOG, box, key
from mapillary_views import D, fetch_img
from scipy.spatial.transform import Rotation
from shapely import wkt

W, H = 1024, 768


def frame_meta(r):
    g = requests.post(f"{API}/latest/poly", params={"headings": "true"}, json=box(r.cx - 2, r.cy - 2, r.cx + 2, r.cy + 2),
                      headers={"Authorization": "Basic " + key()}, timeout=120).json()
    m = [f for f in g.get("frames", []) if f.get("sequence") == r.sequence and f.get("idx") == r.idx]
    return m[0] if m else None


def source_rotation(heading, yaw, pitch, roll, pitch_sign):
    """Rotation taking ENU vectors (x east, y north, z up) to the source camera frame (x right, y down, z fwd)."""
    az = np.radians(heading + yaw)
    # level camera looking at azimuth az: rows = right, down, forward expressed in ENU
    level = np.array([[np.cos(az), -np.sin(az), 0], [0, 0, -1], [np.sin(az), np.cos(az), 0]])
    tilt = Rotation.from_euler("xz", [pitch_sign * pitch, roll], degrees=True).as_matrix()  # about camera x, then z
    return tilt @ level


def render(img, K, dist, R_src, az_target, hfov):
    f = W / 2 / np.tan(np.radians(hfov / 2))
    i, j = np.meshgrid(np.arange(W) - W / 2 + 0.5, np.arange(H) - H / 2 + 0.5)
    a = np.radians(az_target)
    right, down, fwd = np.array([np.cos(a), -np.sin(a), 0]), np.array([0, 0, -1.0]), np.array([np.sin(a), np.cos(a), 0])
    rays = i[..., None] * right + j[..., None] * down + f * fwd  # ENU directions, (H, W, 3)
    c = rays.reshape(-1, 3) @ R_src.T
    ok = c[:, 2] > 1e-6
    uv = np.full((len(c), 2), -1.0, np.float32)
    uv[ok] = cv2.projectPoints(c[ok].reshape(-1, 1, 3), np.zeros(3), np.zeros(3), K, dist)[0].reshape(-1, 2)
    mx, my = uv[:, 0].reshape(H, W).astype(np.float32), uv[:, 1].reshape(H, W).astype(np.float32)
    return cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(128, 128, 128)), f


def main(area, pitch_sign=1.0):
    raw, out = D / area / "beemaps_raw", D / area / "beemaps_rect"
    raw.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    devs = requests.get(f"{API}/devices", timeout=60).json()
    v = pd.read_parquet(D / area / "beemaps_multi.parquet")
    v = v[v.path.notna()]
    fps = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "fp_wkt"]).set_index("oid").fp_wkt
    meta_p = raw / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    rows = []
    for r in v.itertuples():
        k = f"{r.sequence}_{int(r.idx)}"
        rp = raw / f"{k}.jpg"
        if k not in meta or not rp.exists():
            fr = frame_meta(r)
            if fr is None:
                continue
            fetch_img(fr.pop("url")).convert("RGB").save(rp, quality=95)
            with open(LOG, "a") as fl:
                fl.write(json.dumps({"t": time.time(), "kind": "view", "sequence": r.sequence, "idx": int(r.idx),
                                     "usd": 0.005, "purpose": "raw for rectification"}) + "\n")
            meta[k] = fr
            meta_p.write_text(json.dumps(meta))
        fr = meta[k]
        img = cv2.imread(str(rp))
        h, w = img.shape[:2]
        K, dist = camera(devs[fr["device"]], w, h)
        R = source_rotation(fr["position"]["heading"], fr.get("yaw") or 0.0, fr.get("pitch") or 0.0, fr.get("roll") or 0.0,
                            pitch_sign)
        fp = wkt.loads(fps[r.oid])
        c = fp.centroid
        az = np.degrees(np.arctan2(c.x - r.cx, c.y - r.cy)) % 360
        angs = [np.degrees(np.arctan2(px - r.cx, py - r.cy)) for px, py in fp.exterior.coords]
        half = max(abs((a_ - az + 180) % 360 - 180) for a_ in angs)
        hfov = float(np.clip(2 * half + 16, 25, 70))
        view, f = render(img, K, dist, R, az, hfov)
        p = out / f"{r.oid}_{k}.jpg"
        cv2.imwrite(str(p), view, [cv2.IMWRITE_JPEG_QUALITY, 92])
        rows.append({"oid": r.oid, "sequence": r.sequence, "idx": int(r.idx), "dist_m": r.dist_m, "az": az, "hfov": hfov,
                     "focal_px": f, "yaw": fr.get("yaw"), "pitch": fr.get("pitch"), "roll": fr.get("roll"),
                     "grey_share": float((view == 128).all(axis=2).mean()), "path": str(p)})
    df = pd.DataFrame(rows).assign(provider="beemaps")
    df.to_parquet(D / area / "beemaps_rect.parquet", index=False)
    print(df[["oid", "dist_m", "hfov", "yaw", "pitch", "roll", "grey_share"]].round(2).to_string())


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1.0)
