"""(g) check.py as a pytest, and the gate self-test: they need the built tables (data/ is not in git), so they skip
where the data is absent."""

import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "flood_v1" / "assemble_dev"
PY = sys.executable


@pytest.mark.skipif(not (DEV / "buildings_12103.parquet").exists(), reason="no dev build")
def test_check_passes_on_the_dev_build_and_fails_on_a_broken_copy(tmp_path):
    ok = subprocess.run([PY, ROOT / "pipeline/assemble/check.py", "12103", str(DEV)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout[-2000:]
    b = pd.read_parquet(DEV / "buildings_12103.parquet")
    i = b.index[b.ffe_ft.notna()][0]
    b.loc[i, "ffe_null"] = "not_determinable"  # a value AND a null reason
    b.to_parquet(tmp_path / "buildings_12103.parquet")
    shutil.copy(DEV / "parcels_12103.parquet", tmp_path / "parcels_12103.parquet")
    bad = subprocess.run(
        [PY, ROOT / "pipeline/assemble/check.py", "12103", str(tmp_path)], capture_output=True, text=True
    )
    assert bad.returncode == 1 and "FAIL ffe_ft: value xor null reason: 1" in bad.stdout


@pytest.mark.skipif(not (ROOT / "data/flood_v1/train_r0/model_12103.txt").exists(), reason="no r0 artefacts")
def test_gate_self_test():
    r = subprocess.run(
        [
            PY,
            ROOT / "pipeline/train/gate.py",
            "12103",
            "pinellas_2018",
            "--baseline",
            str(ROOT / "data/flood_v1/train_r0"),
            "--release",
            "pytest-selftest",
            "--self-test",
            "--boot",
            "300",
        ],
        capture_output=True,
        text=True,
    )
    (ROOT / "pipeline/train/out/gate_12103_pytest-selftest.json").unlink(missing_ok=True)
    assert r.returncode == 0, r.stdout[-2000:]
