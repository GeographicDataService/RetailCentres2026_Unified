"""
Download reference data for the retail centre naming pipeline.

Downloads ONS boundary files, OS Open Names, and other reference datasets
needed by naming.py and generate_names.py.

Some datasets (OS Open Names, Boundary-Line) may require manual download
from OS Data Hub with an API key. The script will flag these.
"""

import os
import io
import zipfile
import requests
import shutil

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# ─── ONS Open Geography Portal (ArcGIS REST) ────────────────────────────
# These use the ONS geoportal GeoJSON/Shapefile download endpoints.
# For large boundary files we use generalised (BGC/BFC) versions.

DATASETS = {
    # ── England & Wales ──
    "lad_boundaries": {
        "description": "Local Authority Districts (Dec 2024) UK BFC",
        "url": "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/e00959b3cb35408db26e89e08036d8c0/geoPackage?layers=0",
        "filename": "LAD_Dec2024_UK.gpkg",
        "subfolder": "",
    },
    "bua_boundaries": {
        "description": "Built-Up Areas (Dec 2022) GB",
        "url": "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/ad30b234308f4b02b4bb9b0f4766f7bb/geoPackage?layers=0",
        "filename": "BUA_Dec2022_EW.gpkg",
        "subfolder": "",
    },
    "msoa_boundaries": {
        "description": "MSOA (Dec 2021) England & Wales BGC V3",
        "url": "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/6b282db29762450881ed5159259a6e4e/geoPackage?layers=0",
        "filename": "MSOA_Dec2021_EW.gpkg",
        "subfolder": "",
    },
    "lad_to_region": {
        "description": "LAD to Region lookup (Dec 2024)",
        "url": "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/3959874c514b470e9dd160acdc00c97a/csv?layers=0",
        "filename": "LAD_to_Region_Dec2024.csv",
        "subfolder": "",
    },
    "lad_to_county": {
        "description": "LAD to County/UA lookup (Dec 2024)",
        "url": "https://open-geography-portalx-ons.hub.arcgis.com/api/download/v1/items/1b80e7fe67e34cf5b084ba23700d7974/csv?layers=0",
        "filename": "LAD_to_County_Dec2024.csv",
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
    "scottish_localities": {
        "description": "Scottish Localities (2020)",
        "url": "https://maps.gov.scot/ATOM/shapefiles/SG_Localities_2020.zip",
        "filename": "SG_Localities_2020.zip",
        "subfolder": "scotland",
        "is_zip": True,
    },
    # ── Northern Ireland ──
    "ni_soa": {
        "description": "NI Super Output Areas (2011)",
        "url": "https://www.nisra.gov.uk/sites/nisra.gov.uk/files/publications/SOA2011_Esri_Shapefile_0.zip",
        "filename": "NI_SOA2011.zip",
        "subfolder": "northern_ireland",
        "is_zip": True,
    },
    "ni_settlements": {
        "description": "NI Settlements (2015)",
        "url": "https://admin.opendatani.gov.uk/dataset/e3757f15-4833-496f-882a-8968c98f3cb4/resource/a1daf6e3-83da-4729-b444-84c7cfca18cc/download/settlements-2015.json",
        "filename": "NI_Settlements_2015.geojson",
        "subfolder": "northern_ireland",
    },
}

# OS Open Names and Boundary-Line require OS Data Hub registration
MANUAL_DATASETS = {
    "os_open_names": {
        "description": "OS Open Names (CSV format, ~106MB zip)",
        "instructions": (
            "1. Go to https://osdatahub.os.uk/downloads/open/OpenNames\n"
            "2. Download the CSV format (opname_csv_gb.zip)\n"
            "3. Extract to data/os_open_names/ so that data/os_open_names/DATA/ contains CSV files\n"
            "   and data/os_open_names/DOC/ contains the header file"
        ),
        "check_path": os.path.join(DATA_DIR, "os_open_names", "DATA"),
    },
    "boundary_line_counties": {
        "description": "OS Boundary-Line Ceremonial Counties",
        "instructions": (
            "1. Go to https://osdatahub.os.uk/downloads/open/BoundaryLine\n"
            "2. Download the GeoPackage format\n"
            "3. Extract and copy the ceremonial counties layer to data/boundary_line_counties.gpkg\n"
            "   (or the full Boundary-Line gpkg to data/bdline_gb.gpkg)"
        ),
        "check_path": os.path.join(DATA_DIR, "bdline_gb.gpkg"),
    },
}


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
