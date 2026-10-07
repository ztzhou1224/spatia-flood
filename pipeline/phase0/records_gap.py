"""Phase 0: free sources of floor count and foundation type for the risk-area houses of one county.

Houses = risk-area buildings (spatia-data overture_buildings, centroid in data/flood_v1/risk_<FIPS>.parquet) whose
centroid lies in a residential fl_parcels parcel (DOR use codes 000-009). Per house, which free source answers:
  floors      Overture num_floors (spatia-data overture_buildings; source per row is not carried in this layer)
  foundation  FDEM elevation certificate (data/fl/ec_all.json, NAVD88, residential, latest per property) inside the
              footprint: building diagram number (1A/1B slab, 2-4 basement / split / crawl, 5-9 elevated / enclosure)
  both        USACE NSI 2022 point inside the footprint: num_story, found_type (licence: built partly from commercial
              inputs, internal only until USACE terms are read; reported separately, not counted as a clean source)
Counts only; no addresses or owner fields are read or written.
Usage: python pipeline/phase0/records_gap.py 12103
"""
import json
import sys
import time

import numpy as np
import pandas as pd
import shapely

from risk_area import BLDG, DATA, OUT, ROOT, connect

PARCELS = "layers/state/FL/fl_parcels.parquet"


def main(fips: str) -> None:
    c, b = connect()
    t0 = time.time()
    c.execute(f"CREATE TABLE risk AS SELECT geom FROM read_parquet('{DATA}/risk_{fips}.parquet')")
    x0, y0, x1, y1 = c.execute("SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) FROM risk").fetchone()
    br = c.execute(f"""SELECT bl.id, ST_AsWKB(bl.geom) AS wkb, bl.lon, bl.lat, bl.num_floors, bl.height
                       FROM read_parquet('{b}/{BLDG}') bl, risk
                       WHERE bl.lon BETWEEN {x0} AND {x1} AND bl.lat BETWEEN {y0} AND {y1}
                         AND ST_Intersects(risk.geom, ST_Point(bl.lon, bl.lat))""").df()
    pa = c.execute(f"""SELECT dor_uc, ST_AsWKB(geom) AS wkb FROM read_parquet('{b}/{PARCELS}')
                       WHERE county_fips = '{fips}' AND dor_uc < '010' AND bbox.xmax >= {x0} AND bbox.xmin <= {x1}
                         AND bbox.ymax >= {y0} AND bbox.ymin <= {y1}""").df()
    print(f"read {len(br)} buildings, {len(pa)} residential parcels in {time.time() - t0:.0f} s", flush=True)
    fp = shapely.from_wkb(br.wkb.map(bytes).values)
    bj, _ = shapely.STRtree(shapely.from_wkb(pa.wkb.map(bytes).values)).query(
        shapely.points(br.lon.values, br.lat.values), predicate="within")
    house = np.zeros(len(br), bool)
    house[bj] = True
    tree = shapely.STRtree(fp)

    def inside(lon, lat):
        """index of the footprint holding each point (first hit), -1 when none."""
        pi, fi = tree.query(shapely.points(lon, lat), predicate="within")
        out = np.full(len(lon), -1)
        out[pi[::-1]] = fi[::-1]
        return out

    n = pd.read_parquet(ROOT / "data" / "fl" / "nsi_fl.parquet", columns=["x", "y", "num_story", "found_type"])
    n = n[n.x.between(x0, x1) & n.y.between(y0, y1)].reset_index(drop=True)
    n["fp"] = inside(n.x.values, n.y.values)
    n = n[n.fp >= 0].drop_duplicates("fp")
    nsi_story = np.zeros(len(br), bool)
    nsi_story[n.fp[n.num_story.notna() & (n.num_story > 0)].values] = True
    nsi_found = np.zeros(len(br), bool)
    nsi_found[n.fp[n.found_type.notna() & (n.found_type.astype(str).str.strip() != "")].values] = True

    e = pd.DataFrame(json.loads((ROOT / "data" / "fl" / "ec_all.json").read_text()))
    e = e[(e.verticalDatum == "navd_1988") & (e.buildingUse == "residential") & e.lon.notna()]
    e = e.sort_values("issuedAt").drop_duplicates("propertyId", keep="last")
    e = e[e.lon.between(x0, x1) & e.lat.between(y0, y1) & e.buildingDiagramNumber.notna()]
    cert = np.zeros(len(br), bool)
    k = inside(e.lon.values, e.lat.values)
    cert[k[k >= 0]] = True

    floors = br.num_floors.notna().values & (br.num_floors.fillna(0).values > 0)
    h = house
    res = {"fips": fips, "risk_buildings": len(br), "houses_on_residential_parcels": int(h.sum()),
           "overture_num_floors": int((h & floors).sum()), "overture_height": int((h & br.height.notna().values).sum()),
           "fdem_certificate_foundation": int((h & cert).sum()),
           "free_clean_floors_and_foundation": int((h & floors & cert).sum()),
           "free_clean_neither": int((h & ~floors & ~cert).sum()),
           "nsi_point_in_footprint_num_story": int((h & nsi_story).sum()),
           "nsi_point_in_footprint_found_type": int((h & nsi_found).sum())}
    (OUT / f"records_gap_{fips}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1), f"\n{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main(sys.argv[1])
