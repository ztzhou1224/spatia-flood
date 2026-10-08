import sys, os
from pyproj import datadir, Transformer
datadir.append_data_dir(sys.argv[1])
pts = [(-82.7873, 27.9659, "Clearwater"), (-82.6403, 27.7731, "St Pete"), (-82.7457, 27.7206, "St Pete Beach"), (-82.7826, 28.1416, "Tarpon Springs"), (-82.6995, 27.8690, "Pinellas Park")]
pipes = {"GEOID12B": "+proj=pipeline +step +proj=vgridshift +grids=us_noaa_g2012bu0.tif",
         "GEOID18": "+proj=pipeline +step +proj=vgridshift +grids=us_noaa_g2018u0.tif"}
res = {}
for name, p in pipes.items():
    t = Transformer.from_pipeline(p)
    res[name] = [t.transform(lon, lat, 0.0)[2] for lon, lat, _ in pts]
for (lon, lat, nm), a, b in zip(pts, res["GEOID12B"], res["GEOID18"], strict=True):
    # vgridshift forward: H = h - N, so transform(…,0)[2] = -N
    n12, n18 = -a, -b
    print(f"{nm:16s} lon={lon} lat={lat} N12B={n12:.4f} m N18={n18:.4f} m  N18-N12B={n18-n12:+.4f} m = {(n18-n12)/0.3048006096:+.3f} ftUS -> NAVD88 height(GEOID18) - height(GEOID12B) for the same ellipsoidal height = {-(n18-n12)/0.3048006096:+.3f} ft")
