"""
Download reference data for the retail centre naming pipeline.

Downloads ONS boundary files, OS Open Names, and other reference datasets
needed by naming.py and generate_names.py.

Some datasets (OS Open Names, Boundary-Line) may require manual download
from OS Data Hub with an API key. The script will flag these.
"""

import os
import zipfile
import requests
import geopandas as gpd
from shapely.geometry import Point

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ─── ONS Open Geography Portal (ArcGIS REST) ────────────────────────────
# These use the ONS geoportal GeoJSON/Shapefile download endpoints.
# For large boundary files we use generalised (BGC/BFC) versions.

DATASETS = {
    # ── England & Wales ──
    # Note: Local Authority / County / Region are pre-joined onto the input
    # centres gpkg, so no LAD boundary file is downloaded here.
    "msoa_boundaries": {
        "description": "MSOA (Dec 2021) England & Wales BGC V3",
        "url": "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/6b282db29762450881ed5159259a6e4e/geoPackage?layers=0",
        "filename": "MSOA_Dec2021_EW.gpkg",
        "subfolder": "",
    },
    # ── Scotland ──
    "scottish_iz": {
        "description": "Scottish Intermediate Zones (2011)",
        "url": "https://maps.gov.scot/ATOM/shapefiles/SG_IntermediateZoneBdry_2011.zip",
        "filename": "SG_IntermediateZone_2011.zip",
        "subfolder": "scotland",
        "is_zip": True,
    },
    # ── Northern Ireland ──
    # NI neighbourhoods use Super Data Zones (SDZ), which the loader globs for
    # as *SDZ* files. There is no clean direct-download URL, so SDZ is a manual
    # download — see MANUAL_DATASETS below.
}

# OS Open Names and Boundary-Line require OS Data Hub registration
MANUAL_DATASETS = {
    "os_open_names": {
        "description": "OS Open Names (GeoPackage format, ~2GB)",
        "instructions": (
            "1. Go to https://osdatahub.os.uk/downloads/open/OpenNames\n"
            "2. Download the GeoPackage format\n"
            "3. Extract to data/os_open_names/ so that\n"
            "   data/os_open_names/Data/opname_gb.gpkg exists"
        ),
        "check_path": os.path.join(DATA_DIR, "os_open_names", "Data", "opname_gb.gpkg"),
    },
    "ni_sdz": {
        "description": "NI Super Data Zones 2021 (neighbourhood geography)",
        "instructions": (
            "1. Go to https://www.nisra.gov.uk/support/geography/northern-ireland-super-data-zones\n"
            "2. Download the SDZ2021 boundaries (shapefile or GeoPackage)\n"
            "3. Extract to data/northern_ireland/ so that a *SDZ* .shp/.gpkg file is present"
        ),
        "check_path": os.path.join(DATA_DIR, "northern_ireland"),
    },
}


# ─── OSM place nodes via Overpass ───────────────────────────────────────
# Two inputs naming.py expects but that have no clean direct-download URL.
# Both share the schema [name, place_type, geometry(Point)] in EPSG:27700.
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_HEADERS = {"User-Agent": "RetailCentres-naming/1.0 (OSM place grab)"}

OSM_PLACES = {
    "osm_neighbourhoods.parquet": {
        "description": "OSM place=neighbourhood/quarter nodes (UK-wide)",
        "query": (
            '[out:json][timeout:600];'
            'area["ISO3166-1"="GB"][admin_level=2]->.uk;'
            'node["place"~"^(neighbourhood|quarter)$"]["name"](area.uk);'
            'out body;'
        ),
    },
    "osm_ni_places.parquet": {
        "description": "OSM place=city/town/village/suburb/hamlet nodes (NI bbox)",
        # NI bounding box; slight ROI overshoot is filtered downstream in naming.py.
        "query": (
            '[out:json][timeout:600];'
            'node["place"~"^(city|town|village|suburb|hamlet)$"]["name"]'
            '(54.00,-8.20,55.35,-5.35);'
            'out body;'
        ),
    },
}


def grab_osm_places(query):
    """Run an Overpass query, returning a name/place_type/geometry GDF (EPSG:27700)."""
    data = requests.post(OVERPASS, data={"data": query},
                         headers=OVERPASS_HEADERS, timeout=600).json()
    rows = [
        {"name": el["tags"]["name"],
         "place_type": el["tags"]["place"],
         "geometry": Point(el["lon"], el["lat"])}
        for el in data["elements"]
        if el["type"] == "node" and "name" in el.get("tags", {})
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs("EPSG:27700")


def download_file(url, dest_path, description=""):
    """Download a file with progress indication."""
    print(f"  Downloading: {description or os.path.basename(dest_path)}")
    print(f"  URL: {url}")

    try:
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERROR: Download failed: {e}")
        return False

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(dest_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  Progress: {pct}% ({downloaded // 1024}KB / {total // 1024}KB)", end="", flush=True)

    print(f"\n  Saved: {dest_path}")
    return True


def extract_zip(zip_path, extract_to):
    """Extract a zip file."""
    print(f"  Extracting: {zip_path}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_to)
    print(f"  Extracted to: {extract_to}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 70)
    print("Retail Centre Naming Pipeline - Data Download")
    print("=" * 70)

    # Download automated datasets
    for key, ds in DATASETS.items():
        print(f"\n--- {ds['description']} ---")
        subfolder = os.path.join(DATA_DIR, ds["subfolder"]) if ds["subfolder"] else DATA_DIR
        os.makedirs(subfolder, exist_ok=True)

        dest = os.path.join(subfolder, ds["filename"])

        # Check if already exists (for zips, check extracted folder)
        if ds.get("is_zip"):
            extract_dir = os.path.join(subfolder, os.path.splitext(ds["filename"])[0])
            if os.path.exists(extract_dir) and os.listdir(extract_dir):
                print(f"  Already exists: {extract_dir}")
                continue
        else:
            if os.path.exists(dest):
                print(f"  Already exists: {dest}")
                continue

        ok = download_file(ds["url"], dest, ds["description"])
        if ok and ds.get("is_zip"):
            extract_dir = os.path.join(subfolder, os.path.splitext(ds["filename"])[0])
            os.makedirs(extract_dir, exist_ok=True)
            try:
                extract_zip(dest, extract_dir)
            except zipfile.BadZipFile:
                print(f"  ERROR: Bad zip file: {dest}")

    # OSM place nodes (Overpass)
    for filename, ds in OSM_PLACES.items():
        print(f"\n--- {ds['description']} ---")
        dest = os.path.join(DATA_DIR, filename)
        if os.path.exists(dest):
            print(f"  Already exists: {dest}")
            continue
        try:
            gdf = grab_osm_places(ds["query"])
            gdf.to_parquet(dest)
            print(f"  Saved: {dest} ({len(gdf)} nodes)")
        except Exception as e:  # Overpass can rate-limit or time out
            print(f"  ERROR: Overpass grab failed: {e}")

    # Check manual datasets
    print("\n" + "=" * 70)
    print("MANUAL DOWNLOADS REQUIRED")
    print("=" * 70)

    all_manual_ok = True
    for key, ds in MANUAL_DATASETS.items():
        check = ds["check_path"]
        if os.path.exists(check):
            print(f"\n[OK] {ds['description']}: Found at {check}")
        else:
            all_manual_ok = False
            print(f"\n[MISSING] {ds['description']}")
            print(ds["instructions"])

    if all_manual_ok:
        print("\nAll manual datasets present.")

    print("\n" + "=" * 70)
    print("Download complete. Check above for any errors or missing files.")
    print("=" * 70)


if __name__ == "__main__":
    main()
