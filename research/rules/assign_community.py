"""Assign each measured house (research/states houses_all.parquet) to its NFIP community.

A house inside an incorporated Census place (TIGER 2020 PLACE, CLASSFP C*) belongs to that municipality's community;
otherwise to its county's community (TIGER 2020 COUNTY; Virginia independent cities are county-equivalents named
'... city'). The community id (CID) comes from the NFIP Community Status Book by name: municipality 'NAME, CITY OF /
TOWN OF / VILLAGE OF ...', county 'NAME COUNTY'. Staten Island is New York City, CID 360497.
Output: data/rules/house_community.parquet, data/rules/communities.csv (CID, name, houses).
Usage: python assign_community.py
"""
import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data"
OUT = D / "rules"
FIPS = {"FL": "12", "NC": "37", "VA": "51", "HAR": "48", "NYC": "36"}
ABBR = {"FL": "FL", "NC": "NC", "VA": "VA", "HAR": "TX", "NYC": "NY"}


def norm(s):
    return re.sub(r"[^A-Z ]", "", str(s).upper()).strip()


def main():
    OUT.mkdir(exist_ok=True)
    t = pd.read_parquet(D / "states" / "houses_all.parquet")
    t["hid"] = np.arange(len(t))
    con = duckdb.connect(); con.execute("LOAD spatial")
    con.register("h", t[["hid", "lon", "lat", "state"]])
    rows = []
    for st, f in FIPS.items():
        pl = f"/vsizip/{D}/tiger/tl_2020_{f}_place.zip/tl_2020_{f}_place.shp"
        q = f"""select h.hid, p.NAME place, p.CLASSFP from (select * from h where state = '{st}') h
                join ST_Read('{pl}') p on ST_Intersects(p.geom, ST_Point(h.lon, h.lat)) where p.CLASSFP like 'C%'"""
        rows.append(con.execute(q).df())
    places = pd.concat(rows).drop_duplicates("hid").set_index("hid")
    cty = f"/vsizip/{D}/tiger/tl_2020_us_county.zip/tl_2020_us_county.shp"
    counties = con.execute(f"""select h.hid, c.NAME county, c.NAMELSAD county_lsad, c.STATEFP from h
                               join ST_Read('{cty}') c on ST_Intersects(c.geom, ST_Point(h.lon, h.lat))""").df().drop_duplicates("hid").set_index("hid")
    t = t.join(places, on="hid").join(counties, on="hid")
    books = {s: pd.read_parquet(D / "nfip" / f"csb_full_{s}.parquet") for s in set(ABBR.values())}
    cache = {}

    def cid(st, place, county, lsad):
        key = (st, place, county)
        if key in cache:
            return cache[key]
        if st == "NYC":
            out = ("360497", "NEW YORK, CITY OF")
        else:
            b = books[ABBR[st]]
            names = b.communityName.map(norm)
            out = (None, None)
            if isinstance(place, str):
                m = b[names.str.startswith(norm(place) + " CITY OF") | names.str.startswith(norm(place) + " TOWN OF") |
                      names.str.startswith(norm(place) + " VILLAGE OF")]
                if len(m):
                    out = (m.communityIdNumber.iloc[0], m.communityName.iloc[0])
            if out[0] is None and isinstance(county, str):
                if str(lsad).lower().endswith(" city"):  # Virginia independent city
                    m = b[names.str.startswith(norm(county) + " CITY OF")]
                else:
                    m = b[names.str.match(rf"^{norm(county)} COUNTY") | names.str.match(rf"^{norm(county)} PARISH")]
                if len(m):
                    out = (m.communityIdNumber.iloc[0], m.communityName.iloc[0])
        cache[key] = out
        return out
    res = [cid(r.state, r.place, r.county, r.county_lsad) for r in t.itertuples()]
    t["cid"], t["community"] = [r[0] for r in res], [r[1] for r in res]
    t[["hid", "state", "place", "county", "cid", "community"]].to_parquet(OUT / "house_community.parquet", index=False)
    c = t.groupby(["state", "cid", "community"], dropna=False).size().rename("houses").reset_index().sort_values("houses", ascending=False)
    c.to_csv(OUT / "communities.csv", index=False)
    print(f"houses {len(t)}; with a community {t.cid.notna().mean():.1%}; communities {c.cid.nunique()}")
    cum = c.dropna(subset=["cid"]).houses.cumsum() / t.cid.notna().sum()
    for k in (10, 20, 40, 60, 100):
        print(f"top {k} communities cover {cum.iloc[min(k, len(cum)) - 1]:.0%} of matched houses")
    print(c.head(25).to_markdown(index=False))
    print("unmatched (top):", t[t.cid.isna()].groupby(["state", "county"]).size().sort_values(ascending=False).head(8).to_dict())


if __name__ == "__main__":
    main()
