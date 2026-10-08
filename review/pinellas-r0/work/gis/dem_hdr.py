import sys, os
os.environ["CURL_CA_BUNDLE"] = "/root/.ccr/ca-bundle.crt"; os.environ["GDAL_HTTP_PROXY"] = os.environ.get("HTTPS_PROXY", ""); os.environ["GDAL_CURL_CA_BUNDLE"]="/root/.ccr/ca-bundle.crt"
import rasterio
from pyproj import CRS
url = sys.argv[1]
with rasterio.open(f"/vsicurl/{url}") as r:
    c = CRS.from_user_input(r.crs)
    print("DEM crs", c.to_string(), "| name", c.name, "| compound", c.is_compound, "| axis", [(a.name, a.unit_name) for a in c.axis_info])
    print("res", r.res, "dtype", r.dtypes, "nodata", r.nodata, "tags", {k: v for k, v in r.tags().items() if len(str(v)) < 200})
    print("wkt head", c.to_wkt()[:400])
