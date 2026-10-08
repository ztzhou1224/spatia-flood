"""Check the assembled building table against the value conventions of plan §3.1 (docs/06-layer-schema-v1.md).

For every value column x that has x_null: exactly one of x and x_null is set; x_null is one of the six reasons;
x_class is set exactly when x is; x_source and x_vintage are set whenever x is; modeled values carry a band that
contains them. Also: bfe_call is never null without bfe_call_null; no owner / personal column is present; the parcel
table has one row per (parcel_key, geom_group) (review docs/07 DA4 / I2).
Prints one line per rule with the number of violating rows; exits 1 when any rule is violated.
Usage: python pipeline/assemble/check.py 12103 [DIR]   (DIR defaults to data/flood_v1/assemble)
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REASONS = {"not_applicable", "no_coverage", "not_determinable", "stale", "withheld", "not_evaluated"}
FORBIDDEN = ("own", "owner", "taxpayer", "phone", "email")


def main(fips: str, d: Path) -> None:
    b = pd.read_parquet(d / f"buildings_{fips}.parquet")
    bad: dict[str, int] = {}
    stems = [c[:-5] for c in b.columns if c.endswith("_null")]
    values = [(s, s if s in b.columns else f"{s}_ft") for s in stems]
    assert all(x in b.columns for _, x in values), [x for _, x in values if x not in b.columns]
    for stem, x in values:
        v, n = b[x].notna(), b[f"{stem}_null"].notna()
        bad[f"{x}: value xor null reason"] = int((v == n).sum())
        bad[f"{x}: reason in the six"] = int((n & ~b[f"{stem}_null"].isin(REASONS)).sum())
        for suffix in ("class", "source", "vintage"):
            col = f"{stem}_{suffix}"
            if col in b.columns:
                bad[f"{col} set iff value"] = int((b[col].notna() != v).sum())
        if f"{stem}_band_lo" in b.columns:
            m = b[f"{stem}_class"] == "modeled"
            lo, hi = b[f"{stem}_band_lo"], b[f"{stem}_band_hi"]
            bad[f"{stem}: modeled has a band containing the value"] = int(
                (m & ~((lo <= b[x] + 1e-9) & (b[x] <= hi + 1e-9))).sum()
            )
            bad[f"{stem}: band only on modeled"] = int((~m & lo.notna()).sum())
    bad["bfe_call: null without reason"] = int((b.bfe_call.isna() & b.bfe_call_null.isna()).sum())
    bad["owner / personal columns"] = sum(any(f in c.lower().split("_") for f in FORBIDDEN) for c in b.columns)
    # r1 acceptance rules (docs/09), checked when the r1 columns exist
    if "floor_definition" in b.columns:
        bad["E1: floor_definition set iff a floor"] = int((b.floor_definition.notna() != b.ffe_ft.notna()).sum())
        one = b.ffe_source.fillna("").str.contains(r"diagram (?:1A|1B|5),", regex=True)
        both = one & b.bfe_call.notna() & b.bfe_call_lowest_floor.notna()
        bad["E1: living and lowest-floor calls agree on 1A / 1B / 5"] = int(
            (both & (b.bfe_call != b.bfe_call_lowest_floor)).sum()
        )
        bad["E2: no record_lidar_conflict basis"] = int(b.bfe_call_basis.fillna("").str.contains("conflict").sum())
        bad["E2: no call on a conflicting record"] = int(
            (
                (b.ffe_class == "record")
                & b.ffe_record_lidar_conflict.fillna(False)
                & b.bfe_call.isin(["above", "below", "too_close"])
            ).sum()
        )
        rec_h = b.ffh_class == "record"
        bad["E3: raised_flag agrees with a record height"] = int(
            (rec_h & b.raised_flag.notna() & (b.raised_flag.fillna(False).astype(bool) != (b.ffh_ft > 3))).sum()
        )
        bad["E4: no BFE on an AO building"] = int(((b.zone_main == "AO") & b.bfe_ft.notna()).sum())
        bad["E9: model_version only on modeled floors"] = int(
            (b.model_version.notna() != (b.ffh_class == "modeled")).sum()
        )
        both_null = b.ffe_ft.isna() & b.ffh_ft.isna()
        bad["E9: ffe / ffh null reasons agree"] = int((both_null & (b.ffe_null != b.ffh_null)).sum())
        bad["E13: no band above the roof"] = int(
            ((b.ffh_class == "modeled") & (b.ffh_band_hi > b.roof_ft + 1e-9) & (b.ffh_ft <= b.roof_ft)).sum()
        )
    if "ground_ring_masked_cells" in b.columns:
        bad["C2: observed ground has unmasked ring cells"] = int((b.ground_ft.notna() & b.ground_class.isna()).sum())
    p = pd.read_parquet(d / f"parcels_{fips}.parquet")
    bad["parcel table: (parcel_key, geom_group) unique"] = int(p.duplicated(["parcel_key", "geom_group"]).sum())
    bad["parcel table: owner / personal columns"] = sum(
        any(f in c.lower().split("_") for f in FORBIDDEN) for c in p.columns
    )
    print(f"{len(b)} rows, {len(b.columns)} columns; value columns checked: {', '.join(x for _, x in values)}")
    for k, n in bad.items():
        print(f"{'ok  ' if n == 0 else 'FAIL'} {k}: {n}")
    sys.exit(1 if any(bad.values()) else 0)


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "flood_v1" / "assemble")
