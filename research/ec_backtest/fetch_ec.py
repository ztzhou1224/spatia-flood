import json,urllib.request,urllib.parse,concurrent.futures as cf
U="https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/arcgis/rest/services/Public_FDEM_Elevation_Certificates/FeatureServer/0/query"
F="OBJECTID,propertyId,streetAddress,zipcode,nfipCommunityNumber,floodZone,baseFloodElevation,topOfBottomFloor,topOfNextHigherFloor,lowestAdjacentGrade,highestAdjacentGrade,buildingDiagramNumber,verticalDatum,buildingElevationSource,formYear,issuedAt,firmPanelEffectiveDate,buildingUse"
def get(off):
    q=urllib.parse.urlencode({"where":"1=1","outFields":F,"orderByFields":"OBJECTID","resultOffset":off,"resultRecordCount":2000,"outSR":4326,"returnGeometry":"true","f":"json"})
    for a in range(4):
        try:
            d=json.load(urllib.request.urlopen(U+"?"+q,timeout=120)); return d["features"]
        except Exception as e: err=e
    raise err
out=[]
with cf.ThreadPoolExecutor(8) as ex:
    for feats in ex.map(get, range(0,212000,2000)):
        for f in feats:
            a=f["attributes"]; g=f.get("geometry") or {}
            pts=g.get("points") or ([[g["x"],g["y"]]] if "x" in g else [])
            a["lon"],a["lat"]=(pts[0] if pts else (None,None)); out.append(a)
json.dump(out,open("ec_all.json","w")); print(len(out))
