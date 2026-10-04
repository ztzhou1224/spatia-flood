"""Detect doors, stairs, windows, garage doors and the house in level views of the NYC test houses.

For each view in data/nyc/views.parquet: a LEVEL virtual pinhole view (1280 x 960) aimed at the target
footprint centroid (m3_measure2.level_view: Mapillary computed_rotation, rot180 fix, panorama seam wrap),
then Grounding DINO tiny with "a front door. stairs. a window. a garage door. a house.".
Every box is stored (label, score, x0, y0, x1, y1 in view pixels) with the view's focal length and the
target's angular half-width, so the rules in nyc_eval.py can be changed without re-running detection.
The answer key is NOT read here. Output: data/nyc/detections.parquet (one row per view, boxes as JSON),
views in data/nyc/virtual/.  Usage: python nyc_detect.py [LIMIT]
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image
from scipy.spatial.transform import Rotation
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
from m3_measure import VH, VW  # noqa: E402
from m3_measure2 import level_view  # noqa: E402

D = HERE.parents[1] / "data" / "nyc"
PROMPT = "a front door. stairs. a window. a garage door. a house."
torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))


def main(limit=None):
    views = pd.read_parquet(D / "views.parquet")
    views = views[views.path.notna()]
    views = views.assign(_p=views.camera_type != "spherical").sort_values(["_p", "bin"]).reset_index(drop=True)  # panoramas first
    if limit:
        views = views.head(limit)
    out_path = D / "detections.parquet"
    done = pd.read_parquet(out_path) if out_path.exists() else pd.DataFrame()
    seen = set(zip(done.get("bin", []), done.get("image_id", [])))
    vdir = D / "virtual"; vdir.mkdir(exist_ok=True)
    dp = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-tiny")
    dm = AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-tiny").eval()
    rows, t0, cache = [], time.time(), {}
    for r in views.itertuples():
        if (r.bin, r.image_id) in seen:
            continue
        rec = dict(bin=r.bin, image_id=r.image_id, camera_type=r.camera_type, captured=r.captured, dist_m=r.dist_m,
                   half_w=r.half_w, provider=r.provider, status="ok")
        try:
            hfov = float(np.clip(2 * r.half_w + 25, 50, 100))
            if r.image_id not in cache:
                cache.clear()
                im = np.asarray(Image.open(r.path).convert("RGB"))
                cache[r.image_id] = np.rot90(im, 2).copy() if r.rot180 else im
            Rwc = Rotation.from_rotvec(np.array(r.computed_rotation)).as_matrix()
            vimg, f, cov = level_view(cache[r.image_id], Rwc, r.camera_type, r.camera_parameters, float(r.bearing), hfov)
            lum = float(np.asarray(vimg.convert("L"))[cov].mean()) if cov.any() else 0.0
            rec.update(focal_px=float(f), hfov=hfov, view_cov=float(cov.mean()), luminance=lum)
            if cov.mean() < 0.3:
                rec["status"] = "view_out_of_frame"
            elif lum < 60:
                rec["status"] = "dark"
            else:
                vimg.save(vdir / f"{r.bin}_{r.image_id}.jpg", quality=88)
                with torch.no_grad():
                    inp = dp(images=vimg, text=PROMPT, return_tensors="pt")
                    res = dp.post_process_grounded_object_detection(dm(**inp), inp.input_ids, threshold=0.2,
                                                                     text_threshold=0.2, target_sizes=[(VH, VW)])[0]
                labels = [str(x) for x in res.get("text_labels", res.get("labels"))]
                rec["boxes"] = json.dumps([[lab, round(float(s), 3)] + [round(float(v), 1) for v in b]
                                           for b, s, lab in zip(res["boxes"].numpy(), res["scores"].numpy(), labels)])
        except Exception as e:  # noqa: BLE001
            rec["status"] = f"error:{type(e).__name__}:{str(e)[:80]}"
        rows.append(rec)
        if len(rows) % 25 == 0:
            pd.concat([done, pd.DataFrame(rows)]).to_parquet(out_path, index=False)
            print(f"{len(rows)} views in {time.time() - t0:.0f}s; {pd.DataFrame(rows).status.value_counts().to_dict()}", flush=True)
    pd.concat([done, pd.DataFrame(rows)]).to_parquet(out_path, index=False)
    print(f"done: {len(rows)} new views in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
