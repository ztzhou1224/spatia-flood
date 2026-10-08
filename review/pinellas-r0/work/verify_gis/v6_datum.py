from pyproj import Transformer
from pyproj.transformer import TransformerGroup
t = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
print("picked:", t.description, "| accuracy:", t.accuracy)
print("definition:", t.definition[:300])
tg = TransformerGroup("EPSG:4326", "EPSG:6442", always_xy=True)
for x in tg.transformers[:5]: print("  avail:", x.description, "| acc", x.accuracy)
print("unavailable:", [u.name for u in tg.unavailable_operations][:5])
# same for DEM CRS 26917 (NAD83 UTM17)
t2 = Transformer.from_crs("EPSG:4326", "EPSG:26917", always_xy=True); print("26917 picked:", t2.description, "| acc", t2.accuracy)
# null shift magnitude check: identity in geographic
t3 = Transformer.from_crs("EPSG:4326", "EPSG:6318", always_xy=True); print("4326->6318:", t3.description, t3.transform(-82.7873, 27.9659))
