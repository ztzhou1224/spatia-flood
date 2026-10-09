"""Puts the pipeline script directories on sys.path (they are scripts, not a package)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for d in ("pipeline/assemble", "pipeline/train", "pipeline/lidar", "pipeline/phase0", "pipeline"):
    sys.path.insert(0, str(ROOT / d))
