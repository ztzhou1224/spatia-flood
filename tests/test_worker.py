"""(h) the viewer Worker's data-path allowlist: only _flood/viewer/<FIPS>/<release>/ files of the known shapes."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SRC = (Path(__file__).resolve().parents[1] / "viewer" / "src" / "worker.js").read_text()
DATA_PATH = re.search(r"const DATA_PATH = (/.*/);", SRC).group(1)
BUILDING_ID = re.search(r"const BUILDING_ID = (/.*/);", SRC).group(1)

PATHS = {
    "/data/12103/pinellas-r0/geo/872a6e0d5ffffff.json": True,
    "/data/12103/pinellas-r0/county.json": True,
    "/data/12103/../secret/county.json": False,
    "/data/12103/%2e%2e/county.json": False,
    "/data/12103/pinellas-r0/geo/872a6e0d5ffffff0.json": False,  # long cell
    "/data/12103/pinellas-r0/rec/../../x.json": False,
    "/data/1210/pinellas-r0/county.json": False,
    "/data/12103/pinellas-r0/manifest.json": False,
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_worker_regexes_in_javascript():
    js = (
        f"const D = {DATA_PATH}; const B = {BUILDING_ID};"
        f"const paths = {json.dumps(list(PATHS))};"
        "console.log(JSON.stringify({d: paths.map((p) => D.test(p)),"
        " b: [B.test('f12c07c3-59dc-4d6a-9287-a5095ebca151'), B.test('../x'),"
        " B.test('F12C07C3-59DC-4D6A-9287-A5095EBCA151')]}));"
    )
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out["d"] == list(PATHS.values())
    assert out["b"] == [True, False, False]
