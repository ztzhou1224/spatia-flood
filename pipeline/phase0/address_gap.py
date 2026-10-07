"""Phase 0: how many risk-area buildings in one county lack a free address (sizes any Geocodio bill).

Buildings: spatia-data overture_buildings inside the risk polygon (data/flood_v1/risk_<FIPS>.parquet, from
risk_area.py). Free address sources, in order:
1. an Overture address point (spatia-data overture_addresses) inside the building footprint;
2. else the situs address (phy_addr1) of the fl_parcels parcel containing the footprint centroid.
Buildings left with neither are what a Geocodio reverse lookup would be needed for. Also counts the residential
parcels touched (DOR use codes 000-099 with a building), the unit a RentCast records lookup would be bought for.
Only counts are output; no addresses or owner fields are written.
Usage: python pipeline/phase0/address_gap.py 12103
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

from risk_area import BLDG, DATA, OUT, connect

ADDR = "layers/national/overture_addresses.parquet"
PARCELS = "layers/state/FL/fl_parcels.parquet"


def main(fips: str) -> None:
    c, b = connect()
    t0 = time.time()
    c.execute(f"CREATE TABLE risk AS SELECT geom FROM read_parquet('{DATA}/risk_{fips}.parquet')")
    x0, y0, x1, y1 = c.execute("SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) FROM risk").fetchone()
    box = f"BETWEEN {x0} AND {x1}", f"BETWEEN {y0} AND {y1}"
    c.execute(f"""CREATE TABLE bl AS SELECT id, geom, lon, lat FROM read_parquet('{b}/{BLDG}') b
                  WHERE lon {box[0]} AND lat {box[1]}""")
    c.execute("CREATE TABLE br AS SELECT bl.* FROM bl, risk WHERE ST_Intersects(risk.geom, ST_Point(bl.lon, bl.lat))")
    c.execute(f"""CREATE TABLE ad AS SELECT lon, lat FROM read_parquet('{b}/{ADDR}')
                  WHERE lon {box[0]} AND lat {box[1]}""")
    c.execute(f"""CREATE TABLE pa AS SELECT parcel_id, dor_uc, phy_addr1, geom FROM read_parquet('{b}/{PARCELS}')
                  WHERE county_fips = '{fips}' AND bbox.xmax >= {x0} AND bbox.xmin <= {x1}
                    AND bbox.ymax >= {y0} AND bbox.ymin <= {y1}""")
    print(f"read: {c.execute('SELECT count(*) FROM br').fetchone()[0]} buildings, "
          f"{c.execute('SELECT count(*) FROM ad').fetchone()[0]} address points, "
          f"{c.execute('SELECT count(*) FROM pa').fetchone()[0]} parcels in {time.time() - t0:.0f} s", flush=True)
    # point-in-polygon matching with shapely's STRtree (DuckDB's range join over these tables ran > 25 min)
    br = c.execute("SELECT id, ST_AsWKB(geom) AS wkb, lon, lat FROM br").df()
    ad = c.execute("SELECT lon, lat FROM ad").df()
    pa = c.execute("SELECT parcel_id, dor_uc, nullif(trim(phy_addr1), '') IS NOT NULL AS situs, ST_AsWKB(geom) AS wkb FROM pa").df()
    fp = shapely.from_wkb(br.wkb.map(bytes).values)
    _, bi = shapely.STRtree(fp).query(shapely.points(ad.lon.values, ad.lat.values), predicate="within")
    has_pt = np.zeros(len(br), bool)
    has_pt[bi] = True
    pg = shapely.from_wkb(pa.wkb.map(bytes).values)
    bj, pj = shapely.STRtree(pg).query(shapely.points(br.lon.values, br.lat.values), predicate="within")
    first = pd.DataFrame({"b": bj, "p": pj}).drop_duplicates("b")
    parcel = np.full(len(br), -1)
    parcel[first.b.values] = first.p.values
    has_pa = parcel >= 0
    situs = np.zeros(len(br), bool)
    situs[has_pa] = pa.situs.values[parcel[has_pa]]
    pid = pd.Series(np.where(has_pa, pa.parcel_id.values[np.maximum(parcel, 0)], None))
    res_uc = pd.Series(np.where(has_pa, pa.dor_uc.values[np.maximum(parcel, 0)], None)).fillna("999") < "100"
    r = {"buildings": len(br), "with_address_point": int(has_pt.sum()),
         "parcel_situs_only": int((~has_pt & situs).sum()), "no_free_address": int((~has_pt & ~situs).sum()),
         "no_parcel": int((~has_pa).sum()), "parcels_with_building": int(pid.nunique()),
         "residential_parcels_with_building": int(pid[res_uc].nunique())}
    res = {"fips": fips, **r}
    (OUT / f"address_gap_{fips}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1), f"\n{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main(sys.argv[1])
