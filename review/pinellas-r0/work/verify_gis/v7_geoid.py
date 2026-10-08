import sys
from pyproj import datadir, Transformer
datadir.append_data_dir(sys.argv[1])
pts = [(-82.7873, 27.9659), (-82.6403, 27.7731), (-82.7457, 27.7206), (-82.7826, 28.1416), (-82.6995, 27.8690)]
# NAD83 ellipsoidal h=10 m -> NAVD88 H via each geoid; H = h - N
H12 = Transformer.from_pipeline("+proj=pipeline +step +proj=vgridshift +grids=us_noaa_g2012bu0.tif")
H18 = Transformer.from_pipeline("+proj=pipeline +step +proj=vgridshift +grids=us_noaa_g2018u0.tif")
mx = 0
for lon, lat in pts:
    a = H12.transform(lon, lat, 10.0)[2]; b = H18.transform(lon, lat, 10.0)[2]
    d = (b - a) / (1200/3937); mx = max(mx, abs(d))
    print(f"lon={lon} lat={lat} H12B={a:.4f} m H18={b:.4f} m  H18-H12B={d:+.4f} ftUS")
print("max |H18-H12B| ftUS:", round(mx, 4))
