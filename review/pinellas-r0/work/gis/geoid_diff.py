import os, sys
os.environ.setdefault("PROJ_NETWORK", "ON")
import pyproj
from pyproj import network, Transformer, CRS
network.set_network_enabled(True)
print("network enabled", network.is_network_enabled(), "ca bundle", network.get_ca_bundle_path() if hasattr(network, "get_ca_bundle_path") else None)
# NAD83(2011) ellipsoidal height (EPSG:6319) -> NAVD88 m (EPSG:5703) via GEOID12B and GEOID18 explicitly
pts = [(-82.7873, 27.9659, "Clearwater"), (-82.6403, 27.7731, "St Pete"), (-82.7457, 27.7206, "St Pete Beach"), (-82.7826, 28.1416, "Tarpon Springs"), (-82.6995, 27.8690, "Pinellas Park")]
pipes = {"GEOID12B": "+proj=pipeline +step +proj=vgridshift +grids=us_noaa_g2012bu0.tif",
         "GEOID18": "+proj=pipeline +step +proj=vgridshift +grids=us_noaa_g2018u0.tif"}
res = {}
for name, p in pipes.items():
    try:
        t = Transformer.from_pipeline(p)
        res[name] = [t.transform(lon, lat, 0.0)[2] for lon, lat, _ in pts]
        print(name, [round(v, 4) for v in res[name]])
    except Exception as e:
        print(name, "ERR", repr(e)[:300])
if len(res) == 2:
    for (lon, lat, nm), a, b in zip(pts, res["GEOID12B"], res["GEOID18"], strict=True):
        # transform(lon,lat,0) with vgridshift forward gives h - N  -> value = -N ; difference in N = (N18 - N12B)
        print(f"{nm:16s} N12B={-a:.4f} m N18={-b:.4f} m  N18-N12B={(-b)-(-a):.4f} m = {((-b)-(-a))/0.3048006096:.3f} ftUS  (NAVD88 height change for the same ellipsoidal height: -(N18-N12B))")
