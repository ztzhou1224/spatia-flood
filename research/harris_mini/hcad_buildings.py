"""HCAD (Harris Central Appraisal District) building records per account: stories, lower levels, foundation type.

Source: https://download.hcad.org/data/CAMA/<YEAR>/Real_building_land.zip (public record; listed by
hcad.org/pdata/pdata-property-downloads.html). Only building fields are read: no owner, address or the free-text
appraiser notes (the owner file Real_acct_owner.zip is never downloaded). Main building (bld_num 1) per account.
  building_res      year built (date_erected), living / base / gross area (im_sq_ft, base_ar, gross_ar)
  exterior          sub-areas by level (last letter of the code: U upper, L lower): upper living area = BAU base
                    area upper + FSU/MSU one-story frame/masonry upper + HFU/HMU half story; lower: BAL base area
                    lower, FGL/MGL garage lower, OFL porch lower, ... and BFF/BPF basement / part basement
  structural_elem1  FND foundation type (Slab / Crawl Space / Full or Partial Basement)
Per account: upper_base (upper living area), upper_any, lower_any, lower_base, lower_garage, basement (sq ft),
stories = 1 + (upper living area > 0), foundation.
Output: data/hcad/bld_<YEAR>.parquet.  Usage: python hcad_buildings.py 2018
"""
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd

D = Path(__file__).resolve().parents[2] / "data" / "hcad"


def read(z, name, cols):
    with z.open(name) as f:
        t = pd.read_csv(io.TextIOWrapper(f, encoding="latin-1"), sep="\t", usecols=cols, dtype=str, quoting=3)
    return t.apply(lambda c: c.str.strip())


def main(year):
    z = zipfile.ZipFile(D / f"Real_building_land_{year}.zip")
    b = read(z, "building_res.txt", ["acct", "bld_num", "property_use_cd", "date_erected", "im_sq_ft", "base_ar", "gross_ar"])
    b = b[b.bld_num == "1"].drop(columns="bld_num").drop_duplicates("acct")
    e = read(z, "exterior.txt", ["acct", "bld_num", "sar_cd", "area"])
    e = e[e.bld_num == "1"]
    e["area"] = pd.to_numeric(e.area, errors="coerce").fillna(0)
    lvl = e.sar_cd.str[-1]  # level letter: P primary, U upper, L lower (C = canopy / common, others)
    e["upper_base"] = e.sar_cd.isin(["BAU", "FSU", "MSU", "HFU", "HMU"]) * e.area  # upper living area
    e["upper_any"] = (lvl == "U") * e.area
    e["basement"] = e.sar_cd.isin(["BFF", "BPF"]) * e.area  # BASEMENT / PART BASEMENT: codes end in F, not L
    e["lower_any"] = ((lvl == "L") | e.sar_cd.isin(["BFF", "BPF"])) * e.area
    e["lower_base"] = (e.sar_cd == "BAL") * e.area
    e["lower_garage"] = e.sar_cd.isin(["FGL", "MGL"]) * e.area
    agg = e.groupby("acct")[["upper_base", "upper_any", "lower_any", "lower_base", "lower_garage", "basement"]].sum()
    s = read(z, "structural_elem1.txt", ["acct", "bld_num", "type", "category_dscr"])
    fnd = s[(s.bld_num == "1") & (s.type == "FND")].drop_duplicates("acct").set_index("acct").category_dscr.rename("foundation")
    out = b.set_index("acct").join(agg).join(fnd).reset_index()
    for c in ("date_erected", "im_sq_ft", "base_ar", "gross_ar"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out[agg.columns] = out[agg.columns].fillna(0)
    out["stories"] = 1 + (out.upper_base > 0).astype(int)
    out.to_parquet(D / f"bld_{year}.parquet", index=False)
    print(f"{year}: {len(out)} main residential buildings; stories {out.stories.value_counts().to_dict()}; "
          f"with a lower level {(out.lower_any > 0).mean():.1%}; foundation {out.foundation.value_counts().to_dict()}")


if __name__ == "__main__":
    main(sys.argv[1])
