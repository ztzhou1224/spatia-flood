"""Read each Bee Maps multi-frame crop (beemaps_multi.py) with a Gemini VLM: door height, steps, foundation, stories.

Same method as vlm_read.py (prompt v2 plus a story count = v3). The model sees only the image crop and the
camera-to-footprint distance; never the answer key, the lidar or the records. Every response is cached as JSON in
data/harris_mini/<AREA>/vlm_multi/ (keyed by model + prompt version), so reruns cost nothing; every billed call is
appended to data/harris_mini/vlm_calls.jsonl, and the script refuses to exceed BUDGET calls in that log.
Output: data/harris_mini/<AREA>/beemaps_multi_reads.parquet (provider=beemaps).
Usage: python vlm_multi.py AREA [INPUT_PARQUET OUTPUT_TAG]   (model from GEMINI_MODEL; default inputs = the crops)
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from vlm_read import LOCK, LOG, MODEL, calls_so_far, jpeg_b64

from mapillary_views import D

PROMPT_V = "v3"
BUDGET = 5000
PROMPT = """You are inspecting a house in a street-level dashcam photo. The TARGET house is the one in the
horizontal CENTRE of this image; ignore other houses. The camera was about {dist:.0f} m from the target's
footprint. Grey bars at the image edges are padding, not content.
1. Estimate how high the front-door threshold (the floor level at the main entry door) sits above the ground
directly in front of the house. Use visible cues: number of steps up to the door (a typical step is about 0.6 ft /
7 in), stoop or porch height, exposed foundation, piers, crawlspace vents, garage-door top vs door, brick courses
(about 0.22 ft each) and siding laps. Slab-on-grade houses in Houston usually have the door 0.5-1.5 ft above ground;
raised houses can be 3-12 ft.
2. Count the stories of living space above the ground or above any garage / enclosure level under the house.
Return JSON only with exactly these keys:
house_visible (bool), front_door_visible (bool), steps_to_door (integer or null),
door_threshold_height_above_ground_ft (number or null; null if you cannot judge it),
foundation ("slab" | "raised_crawlspace" | "piers_or_stilts" | "unknown"),
lower_level_enclosure_visible (bool; an enclosed or garage level under a raised living floor),
living_stories (integer or null), confidence (number 0-1 for the height estimate), notes (string, at most 20 words)."""
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "house_visible": {"type": "BOOLEAN"},
        "front_door_visible": {"type": "BOOLEAN"},
        "steps_to_door": {"type": "INTEGER", "nullable": True},
        "door_threshold_height_above_ground_ft": {"type": "NUMBER", "nullable": True},
        "foundation": {"type": "STRING", "enum": ["slab", "raised_crawlspace", "piers_or_stilts", "unknown"]},
        "lower_level_enclosure_visible": {"type": "BOOLEAN"},
        "living_stories": {"type": "INTEGER", "nullable": True},
        "confidence": {"type": "NUMBER"},
        "notes": {"type": "STRING"},
    },
    "required": ["house_visible", "front_door_visible", "steps_to_door", "door_threshold_height_above_ground_ft",
                 "foundation", "lower_level_enclosure_visible", "living_stories", "confidence", "notes"],
}


def call(path: str, dist: float) -> dict:
    body = {
        "contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": jpeg_b64(path)}},
                                {"text": PROMPT.format(dist=dist)}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "mediaResolution": "MEDIA_RESOLUTION_HIGH", "thinkingConfig": {"thinkingBudget": 1024}},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for attempt in range(6):
        with LOCK:
            if calls_so_far() >= BUDGET:
                raise SystemExit(f"VLM budget of {BUDGET} calls reached")
        r = requests.post(url, json=body, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=180)
        if r.status_code in (200, 400):
            with LOCK, open(LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "model": MODEL, "status": r.status_code,
                                    "usage": r.json().get("usageMetadata", {})}) + "\n")
        if r.status_code == 200:
            return r.json()
        print("http", r.status_code, r.text[:200], file=sys.stderr)
        if r.status_code == 400:
            raise RuntimeError(r.text[:300])
        time.sleep(min(60, 2 ** attempt * 2))
    raise RuntimeError("gemini failed")


def read_one(r, area) -> dict:
    cache = D / area / "vlm_multi" / f"{r.oid}_{r.sequence}_{int(r.idx)}_{MODEL}_{PROMPT_V}{TAG}.json"
    if cache.exists():
        resp = json.loads(cache.read_text())
    else:
        resp = call(r.path, r.dist_m)
        cache.write_text(json.dumps(resp))
    out = {"oid": r.oid, "sequence": r.sequence, "idx": int(r.idx)}
    try:
        out.update(json.loads(resp["candidates"][0]["content"]["parts"][-1]["text"]))
        out["parse_ok"] = True
    except Exception:  # noqa: BLE001
        out["parse_ok"] = False
    return out


TAG = ""


def main(area, inp="beemaps_multi.parquet", tag=""):
    global TAG
    TAG = f"_{tag}" if tag else ""
    v = pd.read_parquet(D / area / inp)
    v = v[v.path.notna()]
    (D / area / "vlm_multi").mkdir(exist_ok=True)
    with ThreadPoolExecutor(6) as ex:
        rows = list(ex.map(lambda r: read_one(r, area), v.itertuples()))
    df = pd.DataFrame(rows).assign(provider="beemaps")
    df.assign(model=MODEL).to_parquet(D / area / f"beemaps_multi_reads{TAG}.parquet", index=False)
    print(f"{area}: {len(df)} reads, parsed {int(df.parse_ok.sum())}; house visible {int(df.house_visible.fillna(False).sum())}, "
          f"door visible {int(df.front_door_visible.fillna(False).sum())}, height {int(df.door_threshold_height_above_ground_ft.notna().sum())}; "
          f"billed calls in log: {calls_so_far()}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
