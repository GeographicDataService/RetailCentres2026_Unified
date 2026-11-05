"""Download the planning centre designations that validation/planning.py scores (paper Table 4, Appendix D sources).

Saves under validation/data/ (EPSG:27700): ni/, spatialhub_scotland_all.geojson, london_boroughs/ (+ sources.csv),
liverpool/ and cities/ (the other eight Core Cities). Cardiff publishes no GIS: run prep/digitise_cardiff.py.
Spatial Hub needs a free key in ~/.spatialhub_key. Layers are as published on the download date; the paper's were
downloaded in October 2026, so a fresh download can differ.
Run from repo root:  .venv/bin/python validation/prep/fetch_planning.py
"""
import io
import json
import re
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

DATA = Path(__file__).resolve().parents[1] / "data"
Q = "query?where={}&outFields=*&outSR=27700&f=geojson"
ALL = Q.format("1%3D1")
NI = "https://services1.arcgis.com/i8LHQZrSk9zIffRU/arcgis/rest/services/town_city_centres/FeatureServer/5/"
SPATIAL_HUB = ("https://geo.spatialhub.scot/geoserver/sh_townc/wfs?service=wfs&version=2.0.0&request=GetFeature"
               "&typeName=sh_townc:pub_townc&outputFormat=application/json&srsName=EPSG:27700&authkey={}")
LIVERPOOL = ("https://geoserver.liverpool.gov.uk/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature"
             "&outputFormat=application/json&srsName=EPSG:27700&typeNames=Planning_NewLocalPlan:pla_lp_")
# GLA Planning Local Plan Data (https://data.london.gov.uk/dataset/2zjmn, OGL): one service per planning authority; Barnet absent
LONDON = "https://services.arcgis.com/drifeOPKLpgnJ8Qa/arcgis/rest/services/planning_local_plan_data_{:02d}/FeatureServer"
LONDON_RETAIL = r"centre|center|parade|shop|frontage|retail|town|CAZ"
BHM = "https://maps.birmingham.gov.uk/server/rest/services/BLP/BirminghamLocalPlan/MapServer/"
BRS = "https://maps2.bristol.gov.uk/server2/rest/services/ext/Policies_2023/MapServer/"
LDS = "https://mapservices.leeds.gov.uk/arcgis/rest/services/Public/Strategic_Planning/MapServer/"
MCR = "https://services3.arcgis.com/HFpQvhZ7zqF7O2S8/arcgis/rest/services/Local_Plan_Draft_for_Consultation_Regulation_19/FeatureServer/"
NTM = "https://maps164.nottinghamcity.gov.uk/server/rest/services/Public_Projects/LAPP/MapServer/"
SHF = "https://sheffieldcitycouncil.cloud.esriuk.com/server/rest/services/Planning/Main_Modifications_Sheffield_Plan_Policies_Map/FeatureServer/"
CITIES = {  # file name under data/cities/: layer query
    "birmingham__city_centre": BHM + "45/" + ALL,
    "birmingham__centres": BHM + "7/" + Q.format("HIERACHY%3C%3E%27Outside+BCC%27"),
    "bristol__city_centre": BRS + "14/" + ALL,
    "bristol__centres": BRS + "15/" + ALL,
    "leeds__city_centre": LDS + "16/" + Q.format("LDFPOLICYID%3D%27CST015%27"),  # Core Strategy (2014) policy CC1 extent
    "leeds__centres": LDS + "4/" + ALL,
    "manchester__city_centre": MCR + "1/" + ALL,
    "manchester__district_centres": MCR + "3/" + ALL,
    **{f"nottingham__{n}": NTM + f"{i}/" + ALL for n, i in
       [("city_centre", 4), ("town_centres", 99), ("district_centres", 100), ("local_centres", 98), ("neighbourhood_centres", 101)]},
    "sheffield__city_centre": SHF + "13/" + ALL,
    "sheffield__district_centres": SHF + "36/" + Q.format("policyarea%3D%27District+Centre%27"),
    "sheffield__local_centres": SHF + "36/" + Q.format("policyarea%3D%27Local+Centre%27"),
}
NEWCASTLE = "https://datamillnorth.org/download/244yn/1gs/Newcastle%20Local%20Plan.zip"  # shapefiles, OGL
NEWCASTLE_LAYERS = {"newcastle__urban_core": "Boundaries/CSUCP_UrbanCoreBoundary.shp",
                    "newcastle__centres": "EconomicProsperity/DAP_DistrictandLocalRetailCentres_DM3.shp"}


def get(url):
    r = requests.get(url, timeout=300)
    r.raise_for_status()
    g = gpd.read_file(r.text)
    return g.set_crs(27700, allow_override=True) if g.total_bounds[2] > 1000 else g.to_crs(27700)  # ArcGIS mislabels BNG as WGS84


def save(g, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(path, driver="GeoJSON")
    print(f"{path.relative_to(DATA)}: {len(g)} features")


def london():
    """Polygon layers of every London service whose name looks retail-related (planning.py picks the centre ones)."""
    dest, rows = DATA / "london_boroughs", []
    dest.mkdir(parents=True, exist_ok=True)
    for n in range(1, 36):
        svc = LONDON.format(n)
        meta = requests.get(svc + "?f=json", timeout=120).json()
        for lyr in [x for x in meta.get("layers", []) if re.search(LONDON_RETAIL, x["name"], re.I)]:
            url = f"{svc}/{lyr['id']}"
            if requests.get(url + "?f=json", timeout=120).json().get("geometryType") != "esriGeometryPolygon":
                continue  # frontages published as lines, points
            feats, off = [], 0
            while True:  # services cap each response, so page
                page = requests.get(f"{url}/{ALL}&resultOffset={off}&resultRecordCount=1000", timeout=300).json()
                feats += page.get("features", [])
                off += 1000
                if len(page.get("features", [])) < 1000:
                    break
            f = dest / f"{n:02d}__{lyr['id']}.geojson"
            f.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
            rows.append(dict(file=f.name, service=n, layer=lyr["name"], url=url, features=len(feats),
                             retrieved=pd.Timestamp.today().date().isoformat()))
    pd.DataFrame(rows).to_csv(dest / "sources.csv", index=False)
    print(f"london_boroughs: {len(rows)} layers")


def main():
    save(get(NI + ALL), DATA / "ni/dfi_town_city_centres.geojson")
    key = (Path.home() / ".spatialhub_key").read_text().strip()
    sh = get(SPATIAL_HUB.format(key)).explode(index_parts=False).reset_index(drop=True)
    save(sh, DATA / "spatialhub_scotland_all.geojson")
    london()
    for layer in ["city_centre_boundary", "district_centres", "local_centres", "retail_out_of_centre"]:
        save(get(LIVERPOOL + layer), DATA / f"liverpool/Planning_NewLocalPlan_pla_lp_{layer}.geojson")
    for name, url in CITIES.items():
        save(get(url), DATA / f"cities/{name}.geojson")
    with zipfile.ZipFile(io.BytesIO(requests.get(NEWCASTLE, timeout=300).content)) as z:
        z.extractall(DATA / "cities/newcastle_zip")
    for name, rel in NEWCASTLE_LAYERS.items():
        save(gpd.read_file(DATA / "cities/newcastle_zip/Newcastle Local Plan/Shapefiles" / rel).to_crs(27700), DATA / f"cities/{name}.geojson")


if __name__ == "__main__":
    main()
