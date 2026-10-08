import pyproj, os
from pyproj import CRS, datadir, network
print("pyproj", pyproj.__version__, "PROJ", pyproj.proj_version_str)
print("data dir", datadir.get_data_dir())
print("network enabled", network.is_network_enabled())
for code in ("EPSG:6442", "EPSG:6443", "EPSG:3086", "EPSG:26917", "EPSG:6360", "EPSG:5703", "EPSG:3857", "EPSG:4326", "OGC:CRS84"):
    c = CRS(code)
    print(code, "|", c.name, "|", [(a.name, a.unit_name, a.direction) for a in c.axis_info], "| type", c.type_name)
# geoid grids present?
d = datadir.get_data_dir()
files = sorted(os.listdir(d))
print("grid-like files:", [f for f in files if any(k in f.lower() for k in ("geoid", "g2012", "g2018", "gtx", "tif"))][:40])
print("n files", len(files))
# can we build a NAVD88(GEOID12B) -> NAVD88(GEOID18) pipeline?  Try transforms ellipsoidal NAD83(2011) h -> NAVD88 with each geoid
from pyproj import Transformer
from pyproj.transformer import TransformerGroup
for name, src, dst in (("NAD83(2011) 3D -> NAVD88 ftUS (6360 compound 6318+6360?)", "EPSG:6319", "EPSG:6318+6360"),):
    try:
        tg = TransformerGroup(src, dst, always_xy=True)
        print(name, "n transformers", len(tg.transformers), "best available", tg.best_available)
        for t in tg.transformers[:6]:
            print("   ", t.description, "| grids", [(g.short_name, g.available) for g in t.unavailable_operations[:0]] )
        for u in tg.unavailable_operations[:6]:
            print("   UNAVAILABLE", u.name)
    except Exception as e:
        print(name, "ERR", e)
# US survey foot vs international foot
usft = 1200/3937
print("usft m", usft, "ratio intl/us", 0.3048/usft, "diff at 10/30/60/100 ft (ft):", [round(h*(1-0.3048/usft),6) for h in (10,30,60,100)])
