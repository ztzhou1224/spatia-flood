"""Read street-view crops with an OPEN-WEIGHT vision-language model we run ourselves (no external API).

Replaces the Gemini reader (vlm_multi.py) for recognition: owner decision 2026-10-05, the product must run its own
model. Default model Qwen/Qwen3-VL-4B-Instruct (Apache-2.0, Hugging Face); any Qwen3-VL size works. Same prompt
and output fields as vlm_multi.py (prompt v3: door threshold height, steps, foundation, lower enclosure, living
stories), asked for as JSON and parsed from the text. The model sees only the image and the camera distance; never the
answer key, the lidar or the records. Responses are cached per image + model in data/harris_mini/<AREA>/local_vlm/.
CPU here (bfloat16, 4 threads); a GPU is needed for production volumes.
Output: data/harris_mini/<AREA>/<PREFIX>_reads_<TAG>.parquet (provider column copied from the input).
Usage: python local_vlm.py AREA INPUT_PARQUET PREFIX TAG [HF_MODEL] [MAX_PIXELS]
"""
import json
import re
import sys
import time

import pandas as pd
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor
from vlm_multi import PROMPT

from mapillary_views import D

KEYS = ["house_visible", "front_door_visible", "steps_to_door", "door_threshold_height_above_ground_ft", "foundation",
        "lower_level_enclosure_visible", "living_stories", "confidence", "notes"]


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    d = json.loads(m.group(0)) if m else {}
    return {k: d.get(k) for k in KEYS}


def main(area, inp, prefix, tag, model_id="Qwen/Qwen3-VL-4B-Instruct", max_pixels=768 * 28 * 28):
    torch.set_num_threads(4)
    proc = AutoProcessor.from_pretrained(model_id, max_pixels=int(max_pixels))
    model = AutoModelForImageTextToText.from_pretrained(model_id, torch_dtype=torch.bfloat16).eval()
    v = pd.read_parquet(D / area / inp)
    v = v[v.path.notna()]
    cache = D / area / "local_vlm"
    cache.mkdir(exist_ok=True)
    mname = model_id.split("/")[-1]
    rows, t0 = [], time.time()
    for n, r in enumerate(v.itertuples(), 1):
        cp = cache / f"{r.oid}_{r.sequence}_{int(r.idx)}_{mname}_v3_{tag}.json"
        if cp.exists():
            text = json.loads(cp.read_text())["text"]
        else:
            msgs = [{"role": "user", "content": [{"type": "image", "image": Image.open(r.path).convert("RGB")},
                                                 {"type": "text", "text": PROMPT.format(dist=r.dist_m)
                                                  + "\nAnswer with the JSON object only."}]}]
            x = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True,
                                         return_tensors="pt")
            with torch.no_grad():
                out = model.generate(**x, max_new_tokens=256, do_sample=False)
            text = proc.batch_decode(out[:, x["input_ids"].shape[1]:], skip_special_tokens=True)[0]
            cp.write_text(json.dumps({"model": model_id, "text": text}))
        row = {"oid": r.oid, "sequence": r.sequence, "idx": int(r.idx)}
        try:
            row.update(parse(text))
            row["parse_ok"] = True
        except Exception:  # noqa: BLE001
            row["parse_ok"] = False
        rows.append(row)
        if n % 5 == 0:
            print(f"{n}/{len(v)} images, {(time.time() - t0) / n:.0f} s per image", flush=True)
    df = pd.DataFrame(rows).assign(model=model_id, provider=v.provider.iloc[0] if "provider" in v else None)
    for c in ("house_visible", "front_door_visible", "lower_level_enclosure_visible"):
        df[c] = df[c].map(lambda b: b if isinstance(b, bool) else None)
    for c in ("door_threshold_height_above_ground_ft", "steps_to_door", "living_stories", "confidence"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.to_parquet(D / area / f"{prefix}_reads_{tag}.parquet", index=False)
    print(f"{area}: {len(df)} reads with {mname}, parsed {int(df.parse_ok.sum())}; house visible "
          f"{int(df.house_visible.fillna(False).sum())}, door visible {int(df.front_door_visible.fillna(False).sum())}, "
          f"height {int(df.door_threshold_height_above_ground_ft.notna().sum())}")


if __name__ == "__main__":
    main(*sys.argv[1:5], *(sys.argv[5:6] or []), *([int(sys.argv[6])] if len(sys.argv) > 6 else []))
