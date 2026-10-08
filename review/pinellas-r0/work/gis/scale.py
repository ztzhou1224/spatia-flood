from pyproj import Proj
import json, sys
p = Proj("EPSG:3086")
for lon, lat, nm in [(-82.7873, 27.9659, "Clearwater"), (-82.6403, 27.7731, "St Pete"), (-82.7826, 28.1416, "Tarpon")]:
    f = p.get_factors(lon, lat)
    print(nm, "meridional", round(f.meridional_scale,5), "parallel", round(f.parallel_scale,5), "areal", round(f.areal_scale,6))
t = json.load(open(sys.argv[1]))
print("tiles.json keys", list(t.keys()), "project", t.get("project"), "ept srs", t.get("ept", {}).get("srs"), "metric", t.get("ept", {}).get("metric_crs"), "vertical", t.get("ept", {}).get("vertical"))
print("n dem tiles", len(t["dem"]), "first dem url", t["dem"][0]["url"] if t["dem"] else None)
