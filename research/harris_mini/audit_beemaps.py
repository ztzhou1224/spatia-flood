"""Audit the Bee Maps frames of beemaps_multi.py: is the target house where the crop assumed, and is it the right house?

For every downloaded frame: the full frame is fetched again (one billed view each; provider=beemaps, kept in data/),
and the target footprint (HCAD 2017, EPSG:6344) is projected into it with the device's own camera model from
/devices (OpenCV rational + thin-prism + tilt distortion, fx = fy = focal x max(w, h), principal point at the centre)
and two orientations: GPS heading only (what beemaps_multi.py assumed) and GPS heading + the frame's `yaw`.
Footprint drawn at ground (lowest adjacent grade) and at roof height (lpc roof p95); neighbouring footprints thin red.
Camera height: ground at the house + 1.4 m (dashcam). Also reports, per frame, the pixel column the crop assumed
(pinhole: w/2 + f tan(offset)) vs the projected footprint centre with distortion.
Output: data/harris_mini/<AREA>/beemaps_audit/<oid>_<sequence>_<idx>.jpg and audit.csv.
Usage: python audit_beemaps.py AREA
"""
import json
import os
import sys
import time

import cv2
import numpy as np
import pandas as pd
import requests
from beemaps_multi import API, LOG, TO_LL, box, key
from mapillary_views import D, buildings, fetch_img
from shapely import wkt
from shapely.strtree import STRtree

USFT = 1200 / 3937
CAM_H = 1.4  # m above ground


def camera(dev, w, h):
    f = dev["focal"] * max(w, h)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], float)
    dist = np.array([dev.get(k, 0.0) for k in ("k1", "k2", "p1", "p2", "k3", "k4", "k5", "k6", "s1", "s2", "s3", "s4", "tauX", "tauY")])
    return K, dist


def project(pts, cam, az_deg, K, dist):
    """World points (x east, y north, z up; m) -> pixels for a level camera looking at azimuth az_deg."""
    a = np.radians(az_deg)
    fwd, right = np.array([np.sin(a), np.cos(a), 0.0]), np.array([np.cos(a), -np.sin(a), 0.0])
    d = np.asarray(pts, float) - cam
    c = np.c_[d @ right, -d[:, 2], d @ fwd]  # OpenCV camera: x right, y down, z forward
    ok = c[:, 2] > 0.5
    px = np.full((len(c), 2), np.nan)
    if ok.any():
        px[ok] = cv2.projectPoints(c[ok].reshape(-1, 1, 3), np.zeros(3), np.zeros(3), K, dist)[0].reshape(-1, 2)
    return px


def draw(img, ring, color, width):
    p = ring[np.isfinite(ring).all(axis=1)]
    if len(p) >= 2:
        cv2.polylines(img, [p.astype(np.int32).reshape(-1, 1, 2)], True, color, width)


def main(area):
    out = D / area / "beemaps_audit"
    out.mkdir(exist_ok=True)
    devs = requests.get(f"{API}/devices", timeout=60).json()
    v = pd.read_parquet(D / area / "beemaps_multi.parquet")
    v = v[v.path.notna()]
    hs = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "fp_wkt", "e2018_lag"]).set_index("oid")
    roof = pd.read_parquet(D / area / "lpc_features.parquet").set_index("oid").roof_p95
    blds = buildings(area)
    bt = STRtree(blds)
    rows = []
    for r in v.itertuples():
        g = requests.post(f"{API}/latest/poly", params={"headings": "true"}, json=box(r.cx - 2, r.cy - 2, r.cx + 2, r.cy + 2),
                          headers={"Authorization": "Basic " + key()}, timeout=120).json()
        m = [f for f in g.get("frames", []) if f.get("sequence") == r.sequence and f.get("idx") == r.idx]
        if not m:
            rows.append({"oid": r.oid, "sequence": r.sequence, "idx": r.idx, "note": "not returned"})
            continue
        fr = m[0]
        img = cv2.cvtColor(np.array(fetch_img(fr["url"]).convert("RGB")), cv2.COLOR_RGB2BGR)
        with open(LOG, "a") as fl:
            fl.write(json.dumps({"t": time.time(), "kind": "view", "sequence": r.sequence, "idx": int(r.idx), "usd": 0.005,
                                 "purpose": "audit"}) + "\n")
        h, w = img.shape[:2]
        K, dist = camera(devs[fr["device"]], w, h)
        fp = wkt.loads(hs.fp_wkt[r.oid])
        g0 = hs.e2018_lag[r.oid] * USFT
        top = g0 + (roof.get(r.oid, 15.0) if np.isfinite(roof.get(r.oid, np.nan)) else 15.0) * USFT
        cam = np.array([r.cx, r.cy, g0 + CAM_H])
        heading, yaw = fr["position"]["heading"], fr.get("yaw") or 0.0
        xy = np.asarray(fp.exterior.coords)
        rec = {"oid": r.oid, "sequence": r.sequence, "idx": int(r.idx), "w": w, "heading": heading, "yaw": yaw,
               "dist_m": r.dist_m, "off": r.off, "crop_cx_pinhole": w / 2 + K[0, 0] * np.tan(np.radians(r.off))}
        for nb in bt.query(fp.buffer(40)):
            b = blds[nb]
            if b.equals(fp) or b.intersection(fp).area > 0.5 * fp.area:
                continue
            bxy = np.asarray(b.exterior.coords)
            draw(img, project(np.c_[bxy, np.full(len(bxy), g0)], cam, heading + yaw, K, dist), (0, 0, 255), 1)
        for lab, az, col in (("heading", heading, (0, 255, 255)), ("heading+yaw", heading + yaw, (0, 255, 0))):
            ground = project(np.c_[xy, np.full(len(xy), g0)], cam, az, K, dist)
            rooftop = project(np.c_[xy, np.full(len(xy), top)], cam, az, K, dist)
            draw(img, ground, col, 3)
            draw(img, rooftop, col, 2)
            c = project(np.array([[fp.centroid.x, fp.centroid.y, g0 + 1.5]]), cam, az, K, dist)[0]
            rec[f"proj_cx_{lab}"] = c[0]
            rec[f"in_frame_{lab}"] = bool(np.isfinite(c[0]) and 0 <= c[0] < w)
        cv2.line(img, (int(rec["crop_cx_pinhole"]), 0), (int(rec["crop_cx_pinhole"]), h), (255, 0, 255), 2)
        cv2.imwrite(str(out / f"{r.oid}_{r.sequence}_{int(r.idx)}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        rows.append(rec)
    a = pd.DataFrame(rows).assign(provider="beemaps")
    a["crop_vs_projected_px"] = a["proj_cx_heading+yaw"] - a.crop_cx_pinhole
    a.to_csv(out / "audit.csv", index=False)
    print(a[["oid", "dist_m", "off", "yaw", "crop_cx_pinhole", "proj_cx_heading", "proj_cx_heading+yaw",
             "crop_vs_projected_px", "in_frame_heading+yaw"]].round(0).to_string())
    print("median |crop centre - projected centre| (px):", float(a.crop_vs_projected_px.abs().median()),
          "| frame width", int(a.w.iloc[0]))


if __name__ == "__main__":
    os.environ.setdefault("BEEMAPS_API_KEY", "")
    main(sys.argv[1])
