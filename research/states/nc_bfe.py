"""FEMA zone and static BFE (ft NAVD88) at each NC measured building, from the spatia-data national flood-zone layer.

The NC Risk Building Footprints layer has no BFE elevation: its STATIC_BFE field is a coded yes/no + confidence flag
(domain D_YES_NO_CONFIDENCE, e.g. 1000 'NO - FIELD DERIVED - HIGH CONFIDENCE', 1010 'YES - ...'). The BFE comes from
R2 layer fema_flood_zones (NFHL S_FLD_HAZ_AR, static_bfe_navd88_ft; NaN where the zone has no single static BFE, as on
most riverine AE reaches). Highest static BFE among the polygons containing the point.
Output: data/states/nc_nfhl.parquet (OBJECTID, nfhl_zone, nfhl_bfe88).  Usage: python nc_bfe.py  (needs R2 credentials)
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coverage"))
import r2duck  # noqa: E402

S = Path(__file__).resolve().parents[2] / "data" / "states"


def main():
    n = pd.read_parquet(S / "nc_measured.parquet", columns=["OBJECTID", "lon", "lat"])
    c = r2duck.con()
    c.register("pts", n)
    src = r2duck.path("fema_flood_zones")
    x0, y0, x1, y1 = n.lon.min(), n.lat.min(), n.lon.max(), n.lat.max()
    c.execute(f"""create table z as select fld_zone, static_bfe_navd88_ft bfe88, geom, xmin, ymin, xmax, ymax
                  from read_parquet('{src}', hive_partitioning=true)
                  where state = 'NC' and xmax >= {x0} and xmin <= {x1} and ymax >= {y0} and ymin <= {y1}""")
    print("NC zone polygons", c.execute("select count(*) from z").fetchone()[0], flush=True)
    j = c.execute("""select p.OBJECTID, max(z.bfe88) nfhl_bfe88,
                            arg_min(z.fld_zone, case when z.fld_zone like 'V%' then 0 when z.fld_zone like 'A%' then 1 else 2 end) nfhl_zone
                     from pts p join z on p.lon between z.xmin and z.xmax and p.lat between z.ymin and z.ymax
                                       and ST_Contains(z.geom, ST_Point(p.lon, p.lat))
                     group by p.OBJECTID""").df()
    j.to_parquet(S / "nc_nfhl.parquet", index=False)
    print(f"buildings {len(n)}; in a zone polygon {len(j)}; with a static BFE {j.nfhl_bfe88.notna().sum()}")
    print("zones:", j.nfhl_zone.value_counts().head(8).to_dict())


if __name__ == "__main__":
    main()
