"""The persisted train / calibrate / test split by 1 km block (r1 plan docs/09 D1 and §4, owner decision Q8).

r0 drew its split with a seed-0 shuffle over the blocks of ITS labels, so any new label batch reshuffled every block
and put r0's held-out houses into training (review M7: 1,139 of 1,782 gate houses). From r1 the split is a file,
pipeline/train/split_<FIPS>.json, and a block's part never changes once written:
  - r0's blocks keep their r0 part (reproduced here from r0's labels + the r0 rule, and checked against r0's
    bands json `test_blocks`); r0's 102 test blocks are the permanent BENCHMARK.
  - a block first seen later is assigned by its id: int(sha256(block_id), 16) % 100 < 20 -> test, < 40 -> cal,
    else fit. So each new batch keeps its own ~20% held out without moving anyone else.
Block id = "<floor(x / 1000)>_<floor(y / 1000)>" of the building centroid in EPSG:6442 (train.features).
Usage: python pipeline/train/split.py 12103 pinellas_2018 --init-from data/flood_v1/train_r0   (writes the file once)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def path(fips: str) -> Path:
    return HERE / f"split_{fips}.json"


def hash_part(block: str) -> str:
    h = int(hashlib.sha256(block.encode()).hexdigest(), 16) % 100
    return "test" if h < 20 else "cal" if h < 40 else "fit"


def screened(lab: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    """train.py's label screen (the population every split and score is drawn from)."""
    from train import screen  # train.py imports this module; import it here, not at the top

    return screen(lab, f)


def r0_parts(blocks: Iterable[str]) -> dict[str, str]:
    """r0's rule (train.py before r1): sorted blocks, seed-0 shuffle, first 20% test, next 20% cal."""
    b = np.array(sorted(set(blocks)))
    np.random.default_rng(0).shuffle(b)
    k = len(b)
    return {x: "test" if i < round(0.2 * k) else "cal" if i < round(0.4 * k) else "fit" for i, x in enumerate(b)}


def load(fips: str) -> dict:
    return json.loads(path(fips).read_text())


def extend(fips: str, blocks: Iterable[str], batch: str) -> tuple[dict[str, str], dict[str, int]]:
    """Add every unseen block (hash rule), never change an existing one; returns {block: part} and the new counts."""
    s = load(fips)
    new = sorted(set(blocks) - set(s["blocks"]))
    for b in new:
        s["blocks"][b] = {"part": hash_part(b), "origin": f"hash ({batch})"}
    if new:
        path(fips).write_text(json.dumps(s, indent=1, sort_keys=True))
    counts = pd.Series([s["blocks"][b]["part"] for b in new]).value_counts().to_dict() if new else {}
    return {b: v["part"] for b, v in s["blocks"].items()}, counts


def benchmark(fips: str) -> set[str]:
    return {b for b, v in load(fips)["blocks"].items() if v["origin"] == "r0" and v["part"] == "test"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--init-from", type=Path, required=True, help="r0's train dir (labels + bands json)")
    a = ap.parse_args()
    sys.path.insert(0, str(HERE))
    from train import features  # train.py imports this module; import it here, not at the top

    if path(a.fips).exists():
        sys.exit(f"{path(a.fips)} exists; a split is written once and only extended (train.py)")
    lab = pd.read_parquet(a.init_from / f"labels_{a.fips}.parquet")
    d = screened(lab, features(a.fips, a.run))
    parts = r0_parts(d.block)
    bands = json.loads((a.init_from / f"bands_{a.fips}.json").read_text())
    test = sorted(b for b, p in parts.items() if p == "test")
    assert test == sorted(bands["test_blocks"]), "r0's test blocks are not reproduced"
    counts = {p: int((d.block.map(parts) == p).sum()) for p in ("fit", "cal", "test")}
    assert counts["test"] == bands["n_test"] and counts["fit"] == bands["n_fit"] and counts["cal"] == bands["n_cal"]
    s = {
        "fips": a.fips,
        "rule": "r0 blocks keep their r0 part; later blocks: int(sha256(block_id), 16) % 100 < 20 test, < 40 cal, "
        "else fit; never changed once written",
        "block_id": "floor(x/1000)_floor(y/1000) of the building centroid, EPSG:6442",
        "benchmark": "origin r0 and part test",
        "blocks": {b: {"part": p, "origin": "r0"} for b, p in sorted(parts.items())},
    }
    path(a.fips).write_text(json.dumps(s, indent=1, sort_keys=True))
    print(f"{path(a.fips)}: {len(parts)} r0 blocks ({len(test)} benchmark), houses {counts}")


if __name__ == "__main__":
    main()
