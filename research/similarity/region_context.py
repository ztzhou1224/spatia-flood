"""Physical and regulatory context of each region (label-free), for the housing-similarity test.

Regions: as similarity_test.py (0.25 deg cells with >= 300 measured houses). Per region, 40 sampled house locations:
  soil     USDA Soil Data Access, map units under the 40 points (multipoint intersection), muaggatt:
           wtdepannmin (annual minimum water-table depth, cm; null = deeper than 200), drainage class (share poorly /
           very poorly drained), flooding frequency (share not 'None'), hydrologic group D share
  climate  Open-Meteo ERA5 archive at the region centroid, daily mean temperature and precipitation 1991-2020:
           freezing index (mean winter sum of degree-days below 0 C), January mean temperature, annual precipitation
  terrain  NSI ground elevation (ft) at the national inventory points: median slope to the 5 nearest NSI points of
           each sampled house (ft per ft), and the standard deviation of NSI ground in the region
  rules    county of the centroid (Census geocoder), NFIP Community Status Book communities in that county:
           mean CRS class (10 = not in CRS; lower = stricter higher standards), median year of first FIRM
Output: data/similarity/region_context.csv.  Usage: python region_context.py
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from pyproj import Transformer
from sklearn.neighbors import KDTree

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data"
OUT = D / "similarity"
MIN_N, CELL, NPT = 300, 0.25, 40
NSI = {"FL": D / "fl" / "nsi_fl.parquet", "NC": D / "states" / "nsi_37.parquet", "VA": D / "states" / "nsi_51.parquet",
       "NYC": D / "states" / "si_nsi.parquet", "HAR": [D / "harris_mini" / "B" / "nsi.parquet", D / "harris_mini" / "C" / "nsi.parquet"]}
ST = {"FL": "FL", "NC": "NC", "VA": "VA", "NYC": "NY", "HAR": "TX"}


def soil(pts):
    wkt = "multipoint(" + ",".join(f"({x:.5f} {y:.5f})" for x, y in pts) + ")"
    q = ("SELECT a.mukey, a.wtdepannmin, a.drclassdcd, a.flodfreqdcd, a.hydgrpdcd FROM "
         f"SDA_Get_Mukey_from_intersection_with_WktWgs84('{wkt}') m JOIN muaggatt a ON a.mukey = m.mukey")
    for _ in range(4):
        try:
            r = requests.post("https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest", json={"format": "JSON", "query": q}, timeout=300).json()
            rows = pd.DataFrame(r.get("Table", []), columns=["mukey", "wt", "drain", "flood", "hyd"])
            wt = pd.to_numeric(rows.wt, errors="coerce").fillna(200)
            return dict(soil_wt_cm=wt.mean(), soil_poor_drain=rows.drain.fillna("").str.contains("oorly").mean(),
                        soil_flood_freq=(~rows.flood.fillna("None").isin(["None"])).mean(), soil_hyd_d=rows.hyd.fillna("").str.contains("D").mean(),
                        soil_units=len(rows))
        except Exception:  # noqa: BLE001
            pass
    return {}


def climate(lat, lon):
    def get(start, end):
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=dict(
            latitude=lat, longitude=lon, start_date=start, end_date=end,
            daily="temperature_2m_mean,precipitation_sum", timezone="UTC"), timeout=300).json()
        return pd.DataFrame(r["daily"])
    # one 30-year request; if the connection keeps failing (it does for one coastal NC cell), the same days in three
    # 10-year requests
    for chunks in ([("1991-01-01", "2020-12-31")],) * 3 + ([("1991-01-01", "2000-12-31"), ("2001-01-01", "2010-12-31"),
                                                         ("2011-01-01", "2020-12-31")],) * 2:
        try:
            d = pd.concat([get(a, b) for a, b in chunks], ignore_index=True)
            d["time"] = pd.to_datetime(d.time)
            d["winter"] = d.time.dt.year + (d.time.dt.month >= 7)
            fi = d.assign(c=(-d.temperature_2m_mean).clip(lower=0)).groupby("winter").c.sum().iloc[1:-1].mean()
            return dict(clim_freeze_index=fi, clim_jan_c=d[d.time.dt.month == 1].temperature_2m_mean.mean(),
                        clim_precip_mm=d.groupby(d.time.dt.year).precipitation_sum.sum().mean())
        except Exception:  # noqa: BLE001
            pass
    return {}


def county(lat, lon):
    for _ in range(4):
        try:
            r = requests.get("https://geocoding.geo.census.gov/geocoder/geographies/coordinates", params=dict(
                x=lon, y=lat, benchmark="Public_AR_Current", vintage="Current_Current", layers="Counties", format="json"), timeout=120).json()
            c = r["result"]["geographies"]["Counties"][0]
            return c["GEOID"], c["NAME"]
        except Exception:  # noqa: BLE001
            pass
    return None, None


def csb(state):
    p = D / "nfip" / f"csb_full_{state}.parquet"
    if not p.exists():
        r = requests.get("https://www.fema.gov/api/open/v1/NfipCommunityStatusBook",
                         params={"$filter": f"state eq '{state}'", "$top": 10000, "$format": "json"}, timeout=300).json()
        pd.DataFrame(r["NfipCommunityStatusBook"]).to_parquet(p)
    return pd.read_parquet(p)


def main():
    OUT.mkdir(exist_ok=True)
    t = pd.read_parquet(D / "states" / "houses_all.parquet")
    t["region"] = t.state + "_" + (t.lon // CELL).astype(int).astype(str) + "_" + (t.lat // CELL).astype(int).astype(str)
    cnt = t.region.value_counts()
    t = t[t.region.isin(cnt[cnt >= MIN_N].index)]
    regs = sorted(t.region.unique())
    samp = {r: t[t.region == r].sample(min(NPT, (t.region == r).sum()), random_state=0) for r in regs}
    cen = {r: (t[t.region == r].lat.mean(), t[t.region == r].lon.mean()) for r in regs}
    with ThreadPoolExecutor(4) as ex:
        soils = dict(zip(regs, ex.map(lambda r: soil(list(zip(samp[r].lon, samp[r].lat))), regs)))
        ctys = dict(zip(regs, ex.map(lambda r: county(*cen[r]), regs)))
    # Open-Meteo weighs a 30-year daily request heavily and has a daily limit: fetch one region at a time and cache
    # each result, so a run stopped by the limit resumes where it left off
    import time
    cache_p = OUT / "climate_cache.json"
    clims = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    for r in [r for r in regs if not clims.get(r)]:
        v = climate(*cen[r])
        if v:
            clims[r] = {k: float(x) for k, x in v.items()}
            cache_p.write_text(json.dumps(clims))
        time.sleep(2)
    missing = [r for r in regs if not clims.get(r)]
    if missing:
        raise SystemExit(f"climate missing for {len(missing)} of {len(regs)} regions (Open-Meteo limit?); rerun later to resume")
    terr = {}
    for st in ("FL", "NC", "VA", "NYC", "HAR"):
        src = NSI[st]
        n = pd.concat([pd.read_parquet(p, columns=["x", "y", "ground_elv"]) for p in (src if isinstance(src, list) else [src])])
        n = n.dropna()
        tr = Transformer.from_crs("EPSG:4326", "EPSG:5070", always_xy=True)  # CONUS Albers, metres
        nx, ny = tr.transform(n.x.values, n.y.values)
        kd = KDTree(np.c_[nx, ny])
        g = n.ground_elv.values
        for r in [r for r in regs if r.startswith(st + "_")]:
            px, py = tr.transform(samp[r].lon.values, samp[r].lat.values)
            dist, idx = kd.query(np.c_[px, py], k=6)
            base = g[idx[:, 0]]
            sl = np.abs(g[idx[:, 1:]] - base[:, None]) * 0.3048 / np.maximum(dist[:, 1:] - dist[:, :1], 1.0)
            x0, y0 = tr.transform(t[t.region == r].lon.min(), t[t.region == r].lat.min())
            x1, y1 = tr.transform(t[t.region == r].lon.max(), t[t.region == r].lat.max())
            inbox = (nx >= x0) & (nx <= x1) & (ny >= y0) & (ny <= y1)
            terr[r] = dict(terr_slope=float(np.median(sl)), terr_relief_ft=float(np.std(g[inbox])) if inbox.sum() > 10 else np.nan)
    books = {s: csb(s) for s in set(ST.values())}
    rules = {}
    for r in regs:
        fips, name = ctys[r]
        b = books[ST[r.split("_")[0]]]
        if name is None:
            rules[r] = {}
            continue
        c = b[b.county.fillna("").str.upper().str.contains(name.upper().replace(" COUNTY", "").replace(" PARISH", ""), regex=False)]
        cls = pd.to_numeric(c.classRating, errors="coerce").fillna(10)
        rules[r] = dict(county_fips=fips, rule_crs_class=cls.mean() if len(c) else np.nan,
                        rule_firm_year=pd.to_datetime(c.initialFloodInsuranceRateMap, errors="coerce").dt.year.median() if len(c) else np.nan,
                        rule_communities=len(c))
    ctx = pd.DataFrame({r: {**soils[r], **clims[r], **terr.get(r, {}), **rules[r]} for r in regs}).T
    ctx.index.name = "region"
    ctx = ctx.apply(lambda c: pd.to_numeric(c, errors="coerce") if c.name != "county_fips" else c)
    ctx.to_csv(OUT / "region_context.csv")
    print(f"regions {len(ctx)}; missing per column: {ctx.isna().sum().to_dict()}")
    print(ctx.assign(state=ctx.index.str.split('_').str[0]).groupby("state").median(numeric_only=True).round(2).T.to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
