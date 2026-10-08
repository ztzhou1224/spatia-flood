from pyproj import Transformer, CRS
from pyproj.transformer import TransformerGroup
import math
pt = (-82.7873, 27.9659)
t0 = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
print("default WGS84->NAD83(2011)/FL West:", t0.description, "| accuracy", t0.accuracy)
x0, y0 = t0.transform(*pt)
# treat the WGS84 lon/lat as ITRF2014 at epoch 2020.0 (what a modern GNSS/imagery-derived WGS84 coordinate effectively is)
try:
    t1 = Transformer.from_crs("EPSG:9000", "EPSG:6318", always_xy=True)  # ITRF2014 -> NAD83(2011) geographic
    print("ITRF2014->NAD83(2011):", t1.description, "| accuracy", t1.accuracy)
    lon1, lat1 = t1.transform(pt[0], pt[1], 0, 2020.0)[:2]
    x1, y1 = Transformer.from_crs("EPSG:6318", "EPSG:6442", always_xy=True).transform(lon1, lat1)
    print(f"offset if the footprint coordinate is really ITRF2014@2020: dx={x1-x0:.3f} m dy={y1-y0:.3f} m |d|={math.hypot(x1-x0,y1-y0):.3f} m")
except Exception as e:
    print("ERR", e)
tg = TransformerGroup("EPSG:4326", "EPSG:6442", always_xy=True)
print("available ops:", [t.description for t in tg.transformers][:4], "| unavailable:", [u.name for u in tg.unavailable_operations][:4])
