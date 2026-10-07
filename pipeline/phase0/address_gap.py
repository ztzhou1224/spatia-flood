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
    c.execute("""CREATE TABLE has_pt AS SELECT DISTINCT br.id FROM br JOIN ad
                 ON ad.lon BETWEEN ST_XMin(br.geom) AND ST_XMax(br.geom) AND ad.lat BETWEEN ST_YMin(br.geom) AND ST_YMax(br.geom)
                 WHERE ST_Intersects(br.geom, ST_Point(ad.lon, ad.lat))""")
    c.execute("""CREATE TABLE in_pa AS SELECT br.id, any_value(pa.parcel_id) AS parcel_id, any_value(pa.dor_uc) AS dor_uc,
                 bool_or(nullif(trim(pa.phy_addr1), '') IS NOT NULL) AS situs
                 FROM br JOIN pa ON ST_Intersects(pa.geom, ST_Point(br.lon, br.lat)) GROUP BY br.id""")
    r = c.execute("""SELECT count(*) AS buildings,
            count(*) FILTER (WHERE h.id IS NOT NULL) AS with_address_point,
            count(*) FILTER (WHERE h.id IS NULL AND p.situs) AS parcel_situs_only,
            count(*) FILTER (WHERE h.id IS NULL AND coalesce(p.situs, false) = false) AS no_free_address,
            count(*) FILTER (WHERE p.id IS NULL) AS no_parcel,
            count(DISTINCT p.parcel_id) AS parcels_with_building,
            count(DISTINCT p.parcel_id) FILTER (WHERE p.dor_uc < '100') AS residential_parcels_with_building
          FROM br LEFT JOIN has_pt h USING (id) LEFT JOIN in_pa p USING (id)""").df().iloc[0].to_dict()
    res = {"fips": fips, **{k: int(v) for k, v in r.items()}}
    (OUT / f"address_gap_{fips}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1), f"\n{time.time() - t0:.0f} s")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main(sys.argv[1])
