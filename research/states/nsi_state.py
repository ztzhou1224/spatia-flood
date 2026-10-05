"""USACE National Structure Inventory, whole state, from the NSI 2022 bulk download (public, no owner data).

Source: https://nsi.sec.usace.army.mil/downloads/nsi_2022/nsi_2022_<FIPS>.gpkg.zip (unzipped into data/raw_nsi).
Kept: the fetch_nsi.KEEP columns present in the bulk file (the bulk file has no static_bfe). x, y are lon / lat.
Output: data/states/nsi_<FIPS>.parquet (37 NC, 51 VA) or data/fl/nsi_fl.parquet (12).
Usage: python nsi_state.py 37 51 12
"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coverage"))
from fetch_nsi import KEEP  # noqa: E402

D = Path(__file__).resolve().parents[2] / "data"


def main(fips):
    src = D / "raw_nsi" / f"nsi_2022_{fips}.gpkg"
    out = D / "fl" / "nsi_fl.parquet" if fips == "12" else D / "states" / f"nsi_{fips}.parquet"
    con = duckdb.connect()
    con.execute("LOAD spatial")
    have = set(con.execute(f"select * from ST_Read('{src}') limit 0").df().columns)
    cols = ", ".join(c for c in KEEP if c in have)
    con.execute(f"COPY (select {cols} from ST_Read('{src}')) TO '{out}' (FORMAT parquet)")
    n, res1 = con.execute(f"select count(*), count(*) filter (where occtype like 'RES1%') from '{out}'").fetchone()
    print(f"{fips}: {n} structures, {res1} RES1 -> {out.relative_to(D.parent)}")


if __name__ == "__main__":
    for f in sys.argv[1:]:
        main(f)
