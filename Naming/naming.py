"""
Naming Lookup Generation for UK Retail Centres.

Replicates the logic of 4_Naming_Lookup.R:
  1a. ONS naming — spatial intersection with admin boundaries
  1b. OS Open Names — nearest place search (10km buffer)
  1c. OS Open Names — internal place extraction (100m buffer)
  1d. Street naming — Foursquare POI address frequency analysis

Outputs four CSV lookup files to exports/.
"""

import os
import glob
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
GPKG_PATH = os.path.join(BASE_DIR, "rc2025_foursquare_ignoreCounty.gpkg")
FSQ_PATH = os.path.join(BASE_DIR, "foursquare_quality_retail_filtered.parquet")
OSM_LANDUSE_PATH = os.path.join(DATA_DIR, "retail_landuse.parquet")

CRS_BNG = "EPSG:27700"
PREFER_ENGLISH_NAMES = True  # Use English place names instead of Gaelic/Welsh where available


def load_retail_centres():
    """Load the main retail centre polygons."""
    print("Loading retail centres...")
    rc = gpd.read_file(GPKG_PATH)
    rc = rc.to_crs(CRS_BNG)
    rc["RC_ID"] = rc["RC_ID"].astype(str)
    print(f"  Loaded {len(rc)} centres")
    return rc


# ═══════════════════════════════════════════════════════════════════════
# 1a. ONS NAMING — Spatial intersection with admin boundaries
# ═══════════════════════════════════════════════════════════════════════

def intersect_with_proportions(rc, boundaries, rc_id_col="RC_ID",
                               bnd_code_col="code", bnd_name_col="name",
                               max_ranks=3, threshold=0.1):
    """
    Spatial intersection of RC polygons with boundary polygons.
    Returns top-N overlapping boundaries per RC, ranked by area proportion.
    Matches R logic: >10% threshold, keep top 1-3.
    """
    print(f"  Intersecting {len(rc)} centres with {len(boundaries)} boundaries...")

    # Ensure same CRS
    boundaries = boundaries.to_crs(rc.crs)

    # Spatial intersection
    intersection = gpd.overlay(
        rc[[rc_id_col, "geometry"]],
        boundaries[[bnd_code_col, bnd_name_col, "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    if len(intersection) == 0:
        return pd.DataFrame()

    # Compute area proportion per RC
    intersection["area_km2"] = intersection.geometry.area * 1e-6
    total_area = intersection.groupby(rc_id_col)["area_km2"].sum().rename("total_area")
    intersection = intersection.merge(total_area, on=rc_id_col)
    intersection["prop"] = intersection["area_km2"] / intersection["total_area"]

    # Filter by threshold
    intersection = intersection[intersection["prop"] > threshold].copy()

    # Rank within each RC by descending proportion
    intersection = intersection.sort_values([rc_id_col, "prop"], ascending=[True, False])
    intersection["rank"] = intersection.groupby(rc_id_col).cumcount() + 1
    intersection = intersection[intersection["rank"] <= max_ranks]

    return intersection[[rc_id_col, bnd_code_col, bnd_name_col, "prop", "rank"]]


def pivot_ranked(df, rc_id_col, code_col, name_col, prefix, max_ranks=3):
    """Pivot ranked intersection results into wide format."""
    rows = []
    for rc_id, group in df.groupby(rc_id_col):
        row = {rc_id_col: rc_id}
        for _, r in group.iterrows():
            rank = int(r["rank"])
            row[f"{prefix}CD_{rank}"] = r[code_col]
            row[f"{prefix}NM_{rank}"] = r[name_col]
            row[f"{prefix}_{rank}_Prop"] = r["prop"]
        rows.append(row)
    return pd.DataFrame(rows)


def load_lad_boundaries():
    """Load LAD boundaries."""
    p = os.path.join(DATA_DIR, "LAD_Dec2024_UK.gpkg")
    if os.path.exists(p):
        print(f"  Loading LAD from {p}")
        gdf = gpd.read_file(p)
        gdf = gdf.rename(columns={"LAD24CD": "LAD_CD", "LAD24NM": "LAD_NM"})
        gdf["LocalAuthorityTY"] = "LAD24CD"
        gdf.loc[gdf["LAD_CD"].str.startswith("S"), "LocalAuthorityTY"] = "CouncilArea24CD"
        gdf.loc[gdf["LAD_CD"].str.startswith("N"), "LocalAuthorityTY"] = "LGD14CD"
        return gdf[["LAD_CD", "LAD_NM", "LocalAuthorityTY", "geometry"]]
    print("  WARNING: LAD boundaries not found")
    return None


def load_bua_boundaries():
    """Load Built-Up Area + Scottish Localities + NI Settlements."""
    parts = []

    # England/Wales/Scotland BUA
    bua_path = os.path.join(DATA_DIR, "BUA_Dec2022_EW.gpkg")
    if os.path.exists(bua_path):
        print("  Loading BUA (GB)...")
        bua = gpd.read_file(bua_path)
        bua = bua.rename(columns={"BUA22CD": "CityCD", "BUA22NM": "CityNM"})
        bua["CityTY"] = "BUA22CD"
        parts.append(bua[["CityCD", "CityNM", "CityTY", "geometry"]])

    # Scottish Localities
    scot_dir = os.path.join(DATA_DIR, "scotland")
    scot_locs = glob.glob(os.path.join(scot_dir, "**/*Localit*.*"), recursive=True)
    scot_locs = [f for f in scot_locs if f.endswith((".shp", ".gpkg", ".geojson"))]
    if scot_locs:
        print(f"  Loading Scottish Localities from {scot_locs[0]}...")
        sl = gpd.read_file(scot_locs[0])
        # Columns vary by version; look for code/name patterns
        for c in sl.columns:
            if c.lower() in ("code", "lc_id", "loc_code"):
                sl = sl.rename(columns={c: "CityCD"})
            if c.lower() in ("name", "lc_name", "loc_name"):
                sl = sl.rename(columns={c: "CityNM"})
        if "CityCD" not in sl.columns:
            sl["CityCD"] = sl.index.astype(str)
        if "CityNM" not in sl.columns and "Name" in sl.columns:
            sl = sl.rename(columns={"Name": "CityNM"})
        sl["CityTY"] = "Localities20CD"
        parts.append(sl[["CityCD", "CityNM", "CityTY", "geometry"]])

    # NI Settlements
    ni_dir = os.path.join(DATA_DIR, "northern_ireland")
    ni_sett = glob.glob(os.path.join(ni_dir, "*ettlement*.*"))
    ni_sett = [f for f in ni_sett if f.endswith((".shp", ".gpkg", ".geojson", ".json"))]
    if ni_sett:
        print(f"  Loading NI Settlements from {ni_sett[0]}...")
        ns = gpd.read_file(ni_sett[0])
        # Known columns: Code, Name
        ns = ns.rename(columns={"Code": "CityCD", "Name": "CityNM"})
        ns["CityTY"] = "Settlements15CD"
        parts.append(ns[["CityCD", "CityNM", "CityTY", "geometry"]])

    if parts:
        # Ensure all parts in same CRS before concat
        parts = [p.to_crs(CRS_BNG) if p.crs != CRS_BNG else p for p in parts]
        return pd.concat(parts, ignore_index=True)
    print("  WARNING: No BUA/City boundaries found")
    return None


def load_neighbourhood_boundaries():
    """Load MSOA (E&W) + IZ (Scotland) + SOA (NI)."""
    parts = []

    # England/Wales MSOA
    msoa_path = os.path.join(DATA_DIR, "MSOA_Dec2021_EW.gpkg")
    if os.path.exists(msoa_path):
        print("  Loading MSOA (E&W)...")
        msoa = gpd.read_file(msoa_path)
        msoa = msoa.rename(columns={"MSOA21CD": "NbhdCD", "MSOA21NM": "NbhdNM"})
        msoa["NbhdTY"] = "MSOA21CD"
        parts.append(msoa[["NbhdCD", "NbhdNM", "NbhdTY", "geometry"]])

    # Scottish Intermediate Zones
    scot_dir = os.path.join(DATA_DIR, "scotland")
    iz_files = glob.glob(os.path.join(scot_dir, "**/*IntermediateZone*.shp"), recursive=True)
    if iz_files:
        print(f"  Loading Scottish IZ from {iz_files[0]}...")
        iz = gpd.read_file(iz_files[0])
        # Columns: InterZone, Name
        iz = iz.rename(columns={"InterZone": "NbhdCD", "Name": "NbhdNM"})
        iz["NbhdTY"] = "IZ11CD"
        parts.append(iz[["NbhdCD", "NbhdNM", "NbhdTY", "geometry"]])

    # NI SOA
    ni_dir = os.path.join(DATA_DIR, "northern_ireland")
    soa_files = glob.glob(os.path.join(ni_dir, "**/*SOA*.*"), recursive=True)
    soa_files = [f for f in soa_files if f.endswith((".shp", ".gpkg", ".geojson", ".json"))]
    if soa_files:
        print(f"  Loading NI SOA from {soa_files[0]}...")
        soa = gpd.read_file(soa_files[0])
        # Try common column name patterns
        for c in soa.columns:
            if "CODE" in c.upper() and "SOA" in c.upper():
                soa = soa.rename(columns={c: "NbhdCD"})
            elif "LABEL" in c.upper() and "SOA" in c.upper():
                soa = soa.rename(columns={c: "NbhdNM"})
        if "NbhdCD" not in soa.columns and "SOA_CODE" in soa.columns:
            soa = soa.rename(columns={"SOA_CODE": "NbhdCD"})
        if "NbhdNM" not in soa.columns and "SOA_LABEL" in soa.columns:
            soa = soa.rename(columns={"SOA_LABEL": "NbhdNM"})
        soa["NbhdTY"] = "SOA11CD"
        if "NbhdCD" in soa.columns and "NbhdNM" in soa.columns:
            parts.append(soa[["NbhdCD", "NbhdNM", "NbhdTY", "geometry"]])
    else:
        print("  WARNING: NI SOA boundaries not found (download manually from NISRA)")

    if parts:
        parts = [p.to_crs(CRS_BNG) if p.crs != CRS_BNG else p for p in parts]
        return pd.concat(parts, ignore_index=True)
    print("  WARNING: No neighbourhood boundaries found")
    return None


def generate_ons_naming(rc):
    """
    ONS Naming: spatial intersection of centres with LAD, County, BUA, Neighbourhood.
    Produces RC_Naming_ONS.csv.
    """
    print("\n=== 1a. ONS Naming ===")

    # We already have pre-joined LA/County/Region in the gpkg.
    # Build the ONS naming table from those + spatial intersection for neighbourhood and city.
    result = rc[["RC_ID"]].copy()

    # Country and Region from pre-joined columns
    result["Country"] = ""
    result["RegionNM"] = rc["RegionName"].values
    result["RegionCD"] = ""

    # Derive country from gsscode prefix or RegionName
    result.loc[rc["RegionName"].isin(["North East", "North West", "Yorkshire and The Humber",
        "East Midlands", "West Midlands", "East of England", "London",
        "South East", "South West"]), "Country"] = "England"
    result.loc[rc["RegionName"] == "Wales", "Country"] = "Wales"
    result.loc[rc["RegionName"] == "Scotland", "Country"] = "Scotland"
    result.loc[rc["RegionName"] == "Northern Ireland", "Country"] = "Northern Ireland"

    # For Wales/Scotland/NI, Region == Country
    result.loc[result["Country"] == "Wales", "RegionNM"] = "Wales"
    result.loc[result["Country"] == "Scotland", "RegionNM"] = "Scotland"
    result.loc[result["Country"] == "Northern Ireland", "RegionNM"] = "Northern Ireland"

    # Pre-joined LA names
    result["LocalAuthorityNM_1"] = rc["LocalAuthorityNM_1"].values
    result["LocalAuthorityNM_2"] = rc["LocalAuthorityNM_2"].values
    result["LocalAuthorityNM_3"] = rc.get("LocalAuthorityNM_3", pd.Series(dtype=str)).values if "LocalAuthorityNM_3" in rc.columns else None
    result["CountyNM_1"] = rc["CountyName"].values

    # Neighbourhood (MSOA/IZ/SOA) — spatial intersection if data available
    nbhd = load_neighbourhood_boundaries()
    if nbhd is not None:
        nbhd_int = intersect_with_proportions(
            rc, nbhd, bnd_code_col="NbhdCD", bnd_name_col="NbhdNM",
            max_ranks=3, threshold=0.1
        )
        if len(nbhd_int) > 0:
            nbhd_wide = pivot_ranked(nbhd_int, "RC_ID", "NbhdCD", "NbhdNM", "Nbhd", max_ranks=3)
            # Merge type from first code
            nbhd_types = nbhd.drop_duplicates("NbhdCD")[["NbhdCD", "NbhdTY"]]
            nbhd_wide = nbhd_wide.merge(nbhd_types, left_on="NbhdCD_1", right_on="NbhdCD", how="left")
            nbhd_wide = nbhd_wide.drop(columns=["NbhdCD"], errors="ignore")
            result = result.merge(nbhd_wide, on="RC_ID", how="left")
        else:
            print("  No neighbourhood intersections found")
    else:
        print("  Skipping neighbourhood (no boundary data)")

    # City/BUA — spatial intersection if data available
    bua = load_bua_boundaries()
    if bua is not None:
        city_int = intersect_with_proportions(
            rc, bua, bnd_code_col="CityCD", bnd_name_col="CityNM",
            max_ranks=2, threshold=0.1
        )
        if len(city_int) > 0:
            city_wide = pivot_ranked(city_int, "RC_ID", "CityCD", "CityNM", "City", max_ranks=2)
            city_types = bua.drop_duplicates("CityCD")[["CityCD", "CityTY"]]
            city_wide = city_wide.merge(city_types, left_on="CityCD_1", right_on="CityCD", how="left")
            city_wide = city_wide.drop(columns=["CityCD"], errors="ignore")
            result = result.merge(city_wide, on="RC_ID", how="left")
        else:
            print("  No city/BUA intersections found")
    else:
        print("  Skipping City/BUA (no boundary data)")

    return result


# ═══════════════════════════════════════════════════════════════════════
# 1b. OS Open Names — Nearest Place Search
# ═══════════════════════════════════════════════════════════════════════

def load_os_open_names(prefer_english=True):
    """Load and filter OS Open Names for populated places.
    If prefer_english=True, swap Gaelic/Welsh name1 to English name2 where available.
    Supports both GeoPackage (.gpkg) and CSV formats.
    """
    os_dir = os.path.join(DATA_DIR, "os_open_names")

    # Try GeoPackage first (faster, single file)
    gpkg_candidates = glob.glob(os.path.join(os_dir, "**", "*.gpkg"), recursive=True)
    if gpkg_candidates:
        gpkg_path = gpkg_candidates[0]
        print(f"  Loading OS Open Names from GeoPackage: {gpkg_path}")
        open_names = gpd.read_file(gpkg_path)

        # GeoPackage uses lowercase column names
        open_names = open_names.rename(columns={
            "name1": "NAME1", "name2": "NAME2",
            "name1_lang": "NAME1_LANG", "name2_lang": "NAME2_LANG",
            "type": "TYPE", "local_type": "LOCAL_TYPE",
        })

        # If prefer_english flag is set, swap to English name2 where name1 is non-English
        if prefer_english:
            use_name2 = (
                open_names["NAME1_LANG"].isin(["gla", "cym"]) &
                (open_names["NAME2_LANG"] == "eng") &
                open_names["NAME2"].notna()
            )
            open_names.loc[use_name2, "NAME1"] = open_names.loc[use_name2, "NAME2"]
            print(f"  Swapped {use_name2.sum()} non-English names to English")

        # Filter for populated places (and transport for completeness)
        open_names = open_names[open_names["TYPE"].isin(["populatedPlace", "transportNetwork"])]
        open_names = open_names[["NAME1", "TYPE", "LOCAL_TYPE", "geometry"]]
        open_names = open_names.to_crs(CRS_BNG)
        print(f"  Loaded {len(open_names)} place names")
        return open_names

    # Fallback: CSV format
    header_candidates = glob.glob(os.path.join(os_dir, "**", "*Header*"), recursive=True)
    if not header_candidates:
        print("  WARNING: OS Open Names not found (no .gpkg or CSV header)")
        return None

    header = pd.read_csv(header_candidates[0]).columns.tolist()
    data_dir_candidates = glob.glob(os.path.join(os_dir, "**", "DATA"), recursive=True)
    if not data_dir_candidates:
        print("  WARNING: OS Open Names DATA directory not found")
        return None

    data_dir = data_dir_candidates[0]
    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    print(f"  Loading {len(csv_files)} OS Open Names CSV files...")

    chunks = []
    for f in csv_files:
        df = pd.read_csv(f, header=None, names=header, na_values=["", "NA", "NULL"])
        df = df[df["TYPE"].isin(["populatedPlace", "transportNetwork"])]
        df = df[["NAME1", "TYPE", "LOCAL_TYPE", "GEOMETRY_X", "GEOMETRY_Y"]]
        chunks.append(df)

    open_names = pd.concat(chunks, ignore_index=True)
    print(f"  Loaded {len(open_names)} place names")

    open_names = gpd.GeoDataFrame(
        open_names,
        geometry=gpd.points_from_xy(open_names["GEOMETRY_X"], open_names["GEOMETRY_Y"]),
        crs=CRS_BNG,
    )
    return open_names


PLACE_TYPES = ["City", "Town", "Village", "Suburban Area", "Other Settlement", "Hamlet"]
PLACE_SHORT = {"City": "City", "Town": "Town", "Village": "Village",
               "Suburban Area": "Suburban", "Other Settlement": "Settlement", "Hamlet": "Hamlet"}


def generate_os_nearest(rc, open_names):
    """
    OS Naming (nearest): for each centre, find nearest place of each type
    within 10km buffer. Fallback to full dataset if not found.
    Uses KDTree for performance.
    """
    print("\n=== 1b. OS Open Names — Nearest ===")

    if open_names is None:
        print("  Skipping (no OS Open Names data)")
        return pd.DataFrame({"RC_ID": rc["RC_ID"]})

    # Compute centroids
    centroids = rc.geometry.centroid
    cent_coords = np.array([(c.x, c.y) for c in centroids])

    results = []

    for ptype in PLACE_TYPES:
        short = PLACE_SHORT[ptype]
        subset = open_names[open_names["LOCAL_TYPE"] == ptype].copy()
        if len(subset) == 0:
            print(f"  No {ptype} places found")
            continue

        coords = np.array([(g.x, g.y) for g in subset.geometry])
        tree = cKDTree(coords)
        names_arr = subset["NAME1"].values

        # Query nearest for all centroids
        dists, idxs = tree.query(cent_coords, k=1)

        # Within 10km
        name_col = []
        dist_col = []
        for i in range(len(rc)):
            if dists[i] <= 10000:
                name_col.append(names_arr[idxs[i]])
                dist_col.append(dists[i])
            else:
                # Fallback: nearest overall (already computed)
                name_col.append(names_arr[idxs[i]])
                dist_col.append(dists[i])

        results.append(pd.DataFrame({
            f"{short}": name_col,
            f"{short}D": dist_col,
        }))

    result = pd.concat([rc[["RC_ID"]].reset_index(drop=True)] + results, axis=1)
    return result


# ═══════════════════════════════════════════════════════════════════════
# 1c. OS Open Names — Internal Place Extraction
# ═══════════════════════════════════════════════════════════════════════

def generate_os_internal(rc, open_names):
    """
    OS Naming (internal): find places within 100m buffer of each centre.
    If multiple places of same type, keep nearest to centroid.
    """
    print("\n=== 1c. OS Open Names — Internal ===")

    if open_names is None:
        print("  Skipping (no OS Open Names data)")
        return pd.DataFrame({"RC_ID": rc["RC_ID"]})

    # Filter to populated place types
    places = open_names[open_names["LOCAL_TYPE"].isin(PLACE_TYPES)].copy()

    # Buffer centres by 100m
    print("  Buffering centres by 100m and finding internal places...")
    rc_buffered = rc[["RC_ID", "geometry"]].copy()
    rc_buffered["geometry"] = rc_buffered.geometry.buffer(100)

    # Spatial join: places within buffered centres
    joined = gpd.sjoin(places, rc_buffered, how="inner", predicate="within")
    if len(joined) == 0:
        print("  No internal places found")
        return pd.DataFrame({"RC_ID": rc["RC_ID"]})

    # Compute distances to centroid for deduplication
    centroids = rc.set_index("RC_ID").geometry.centroid
    joined["centroid_dist"] = joined.apply(
        lambda row: row.geometry.distance(centroids[row["RC_ID"]]) if row["RC_ID"] in centroids.index else np.inf,
        axis=1,
    )

    # For each RC_ID + LOCAL_TYPE, keep the nearest to centroid
    joined = joined.sort_values("centroid_dist")
    best = joined.groupby(["RC_ID", "LOCAL_TYPE"]).first().reset_index()

    # Pivot to wide format
    result_rows = []
    for rc_id, group in best.groupby("RC_ID"):
        row = {"RC_ID": rc_id}
        for _, r in group.iterrows():
            short = PLACE_SHORT.get(r["LOCAL_TYPE"])
            if short:
                row[short] = r["NAME1"]
        result_rows.append(row)

    result = pd.DataFrame(result_rows)
    # Ensure all RC_IDs present
    all_rc = rc[["RC_ID"]].copy()
    result = all_rc.merge(result, on="RC_ID", how="left")
    return result


# ═══════════════════════════════════════════════════════════════════════
# 1d. Street Naming from Foursquare POIs
# ═══════════════════════════════════════════════════════════════════════

# Common UK street suffixes for validation
UK_STREET_SUFFIXES = {
    "street", "road", "lane", "drive", "avenue", "close", "way", "place",
    "court", "crescent", "terrace", "gardens", "grove", "park", "hill",
    "row", "square", "walk", "rise", "mews", "gate", "parade", "broadway",
    "passage", "yard", "path", "green", "view", "mount", "vale", "bridge",
    "wharf", "quay", "circus", "cross", "end", "market", "meadow", "village",
    "strand", "mall", "arcade", "precinct", "esplanade", "promenade",
    "high street", "st", "rd", "ave", "dr", "ln", "ct", "pl", "cres",
}


STREET_ABBREVIATIONS = {
    "St": "Street",
    "Rd": "Road",
    "Ave": "Avenue",
    "Dr": "Drive",
    "Pl": "Place",
    "Ct": "Court",
    "Ln": "Lane",
    "Cres": "Crescent",
    "Tce": "Terrace",
    "Ter": "Terrace",
    "Blvd": "Boulevard",
    "Sq": "Square",
    "Cl": "Close",
    "Gdns": "Gardens",
    "Gdn": "Garden",
    "Grn": "Green",
    "Hts": "Heights",
    "Mt": "Mount",
    "Pk": "Park",
    "Cir": "Circle",
    # Directional abbreviations
    "N": "North",
    "S": "South",
    "E": "East",
    "W": "West",
}


def normalise_street_name(name):
    """Normalise a street name for consistent grouping.
    - Strip dots and hyphens from words
    - Expand abbreviations in the last two words (to catch 'Rd South' etc)
      but protect known prefixes like 'St' before a proper noun
    - Collapse whitespace
    """
    if pd.isna(name) or not name:
        return name
    import re
    # Remove dots and hyphens between word parts (e.g. "Rd." -> "Rd", "Rd-South" -> "Rd South")
    name = name.replace(".", "").replace("-", " ")
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    words = name.split()
    if not words:
        return name
    # Expand abbreviations in last two positions (covers "Rd South", "Rd S", "Ave N" etc)
    for i in range(max(0, len(words) - 2), len(words)):
        w = words[i]
        if w in STREET_ABBREVIATIONS:
            # Protect "St" before a capitalised proper noun (e.g. "St Albans")
            # but not before direction words which are also capitalised
            if w == "St" and i < len(words) - 1:
                next_w = words[i + 1]
                if next_w[0:1].isupper() and next_w not in ("North", "South", "East", "West", "N", "S", "E", "W"):
                    continue
            words[i] = STREET_ABBREVIATIONS[w]
    return " ".join(words)


_OS_ROAD_NAMES = None

def _load_os_road_names():
    """Lazy-load OS Open Names road set for street validation."""
    global _OS_ROAD_NAMES
    if _OS_ROAD_NAMES is not None:
        return _OS_ROAD_NAMES
    os_names_path = os.path.join(DATA_DIR, "os_open_names", "Data", "opname_gb.gpkg")
    if os.path.exists(os_names_path):
        print("  Loading OS road names for street validation...")
        osn = gpd.read_file(os_names_path,
            where="type = 'transportNetwork' AND local_type = 'Named Road'",
            columns=["name1"])
        _OS_ROAD_NAMES = set(osn["name1"].str.lower().str.strip().unique())
        print(f"  Loaded {len(_OS_ROAD_NAMES)} unique road names")
    else:
        _OS_ROAD_NAMES = set()
    return _OS_ROAD_NAMES


def extract_street_name(address):
    """
    Extract street name from Foursquare address field.
    Strips leading house number, then validates against OS road names
    first, falling back to street suffix matching.
    """
    if pd.isna(address) or not address.strip():
        return None

    addr = str(address).strip()

    # If address contains comma, take first part (which is usually the street)
    if "," in addr:
        addr = addr.split(",")[0].strip()

    # Strip leading unit/house number patterns like "12 ", "Unit 5 ", "12-14 "
    import re
    addr = re.sub(r"^(Unit\s+\d+\s*[-/]?\s*\d*\s*)", "", addr, flags=re.IGNORECASE).strip()
    addr = re.sub(r"^\d+\s*[-/]\s*\d+\s+", "", addr).strip()
    addr = re.sub(r"^\d+[a-zA-Z]?\s+", "", addr).strip()

    if not addr:
        return None

    # Check against OS road names first (skip very short matches)
    os_roads = _load_os_road_names()
    if len(addr) >= 5 and addr.lower() in os_roads:
        return addr.title()

    # Fallback: validate against street suffix list
    words = addr.lower().split()
    if any(w in UK_STREET_SUFFIXES for w in words):
        return addr.title()

    # Also check two-word suffixes
    if len(words) >= 2:
        two_word = " ".join(words[-2:])
        if two_word in UK_STREET_SUFFIXES:
            return addr.title()

    return None


def generate_osm_retail_park_names(rc):
    """
    OSM retail park naming: match OSM landuse=retail polygons to retail park
    centres. Use 31% area proportion rule — include every OSM name whose
    polygon covers >31% of total named OSM area within the centre.
    Deduplicate identical names.
    """
    print("\n=== 1e. OSM Retail Park Naming ===")

    if not os.path.exists(OSM_LANDUSE_PATH):
        print("  WARNING: OSM retail landuse not found")
        return pd.DataFrame({"RC_ID": rc["RC_ID"]})

    rl = gpd.read_parquet(OSM_LANDUSE_PATH).to_crs(CRS_BNG)
    named_rl = rl[rl["name"].notna()].copy()
    print(f"  Loaded {len(rl)} OSM retail polygons ({len(named_rl)} named)")

    rp = rc[rc["centre_type"] == "retail_park"]
    print(f"  Matching against {len(rp)} retail parks...")

    matched = gpd.sjoin(named_rl, rp[["RC_ID", "geometry"]], how="inner", predicate="intersects")

    # Only keep OSM polygons fully contained (>95%) within the RC
    rows = []
    for _, m in matched.iterrows():
        rp_geom = rp.loc[rp["RC_ID"] == m["RC_ID"], "geometry"].iloc[0]
        osm_area = m.geometry.area
        inter_area = m.geometry.intersection(rp_geom).area
        pct_in = inter_area / osm_area if osm_area > 0 else 0
        if pct_in > 0.95:
            rows.append({"RC_ID": m["RC_ID"], "osm_name": m["name"], "osm_area": osm_area})

    if not rows:
        print("  No contained OSM matches found")
        return pd.DataFrame({"RC_ID": rc["RC_ID"]})

    df = pd.DataFrame(rows)
    print(f"  {len(df)} contained OSM polygons across {df['RC_ID'].nunique()} parks")

    # 31% rule: include every name above 31% of total named area per park
    results = []
    for rc_id, group in df.groupby("RC_ID"):
        group = group.sort_values("osm_area", ascending=False)
        total_area = group["osm_area"].sum()
        group["pct"] = group["osm_area"] / total_area

        above = group[group["pct"] > 0.31]
        if len(above) == 0:
            above = group.iloc[:1]  # fallback to largest

        # Deduplicate: exact matches and near-dupes (one is substring of another)
        raw_names = list(dict.fromkeys(above["osm_name"].tolist()))
        names = []
        for n in raw_names:
            n_lower = n.lower().strip()
            is_dupe = False
            for existing in names:
                e_lower = existing.lower().strip()
                if n_lower in e_lower or e_lower in n_lower:
                    is_dupe = True
                    break
            if not is_dupe:
                names.append(n)

        results.append({"RC_ID": rc_id, "OSM_RetailParkName": " & ".join(names)})

    result = pd.DataFrame(results)
    all_rc = rc[["RC_ID"]].copy()
    result = all_rc.merge(result, on="RC_ID", how="left")

    n_named = result["OSM_RetailParkName"].notna().sum()
    n_combo = result["OSM_RetailParkName"].str.contains(" & ", na=False).sum()
    print(f"  OSM names assigned: {n_named} ({n_combo} combined)")

    return result


def generate_street_naming(rc):
    """
    Street naming: spatial join Foursquare POIs to centres,
    extract street names, compute frequency per centre.
    """
    print("\n=== 1d. Street Naming (Foursquare) ===")

    print("  Loading Foursquare POI data...")
    fsq = gpd.read_parquet(FSQ_PATH)
    fsq = fsq.to_crs(CRS_BNG)
    print(f"  Loaded {len(fsq)} POIs")

    # Spatial join: POIs within centres
    print("  Spatial join POIs to centres...")
    joined = gpd.sjoin(fsq[["address", "locality", "geometry"]],
                       rc[["RC_ID", "geometry"]],
                       how="inner", predicate="within")
    print(f"  {len(joined)} POIs matched to centres")

    # Extract street names and expand abbreviations
    print("  Extracting street names...")
    joined["street"] = joined["address"].apply(extract_street_name).apply(normalise_street_name)
    joined = joined[joined["street"].notna() & (joined["street"] != "")].copy()
    print(f"  {len(joined)} POIs with valid street names")

    # Frequency analysis per centre
    print("  Computing street frequencies...")
    proportions = (
        joined.groupby(["RC_ID", "street"])
        .size()
        .reset_index(name="n")
    )
    totals = proportions.groupby("RC_ID")["n"].sum().rename("total")
    proportions = proportions.merge(totals, on="RC_ID")
    proportions["freq"] = proportions["n"] / proportions["total"]
    proportions = proportions.sort_values(["RC_ID", "freq"], ascending=[True, False])

    # Keep top 2 per centre
    proportions["rank"] = proportions.groupby("RC_ID").cumcount() + 1
    top2 = proportions[proportions["rank"] <= 2].copy()

    # Pivot to wide
    result_rows = []
    for rc_id, group in top2.groupby("RC_ID"):
        row = {"RC_ID": rc_id}
        for _, r in group.iterrows():
            rank = int(r["rank"])
            row[f"Str_1"] = row.get("Str_1", r["street"] if rank == 1 else None)
            row[f"Str_1_P"] = row.get("Str_1_P", r["freq"] if rank == 1 else None)
            if rank == 2:
                row["Str_2"] = r["street"]
                row["Str_2_P"] = r["freq"]
        result_rows.append(row)

    result = pd.DataFrame(result_rows)
    # Ensure all RC_IDs present
    all_rc = rc[["RC_ID"]].copy()
    result = all_rc.merge(result, on="RC_ID", how="left")

    # Also extract locality info and branded names for retail park naming
    print("  Extracting locality and branded names for retail parks...")
    rp = rc[rc["centre_type"] == "retail_park"]["RC_ID"].tolist()

    # Extract branded retail park names from POI address fields
    import re
    park_pattern = re.compile(
        r'([\w\s\'&-]+(?:Retail & Leisure Park|Retail Park|Shopping Park|Leisure Park|Trading Estate|Shopping Centre|Retail Centre))',
        re.IGNORECASE,
    )
    if len(rp) > 0:
        rp_addr = gpd.sjoin(
            fsq[["address", "locality", "geometry"]].dropna(subset=["address"]),
            rc[rc["centre_type"] == "retail_park"][["RC_ID", "geometry"]],
            how="inner", predicate="within",
        )
        if len(rp_addr) > 0:
            # Extract branded park names from addresses
            def _extract_branded(a):
                m = park_pattern.search(str(a))
                if not m:
                    return None
                name = m.group(1).strip()
                # Strip leading house numbers (but not "Phase 2" etc)
                name = re.sub(r"^\d+\s+", "", name).strip()
                # Strip leading "Unit N" patterns
                name = re.sub(r"^Unit\s+\d+\s*", "", name, flags=re.IGNORECASE).strip()
                # Strip leading single characters (e.g. "c Madford Retail Park")
                name = re.sub(r"^[a-zA-Z]\s+", "", name).strip()
                return name if name else None
            rp_addr["branded"] = rp_addr["address"].apply(_extract_branded)
            branded = rp_addr[rp_addr["branded"].notna()].copy()
            if len(branded) > 0:
                branded_counts = (
                    branded.groupby(["RC_ID", "branded"])
                    .size()
                    .reset_index(name="n")
                    .sort_values(["RC_ID", "n"], ascending=[True, False])
                )
                # Keep the most common branded name per park
                branded_top = branded_counts.groupby("RC_ID").first().reset_index()
                branded_top = branded_top.rename(columns={"branded": "RetailParkBranded"})
                result = result.merge(branded_top[["RC_ID", "RetailParkBranded"]], on="RC_ID", how="left")
                print(f"  Found branded names for {result['RetailParkBranded'].notna().sum()} retail parks")

            # Locality fallback
            rp_locs = rp_addr[rp_addr["locality"].notna()]
            if len(rp_locs) > 0:
                rp_locality = (
                    rp_locs.groupby(["RC_ID", "locality"])
                    .size()
                    .reset_index(name="n")
                    .sort_values(["RC_ID", "n"], ascending=[True, False])
                )
                rp_top = rp_locality.groupby("RC_ID").first().reset_index()
                rp_top = rp_top.rename(columns={"locality": "RetailParkLocality"})
                result = result.merge(rp_top[["RC_ID", "RetailParkLocality"]], on="RC_ID", how="left")

    # Ensure columns exist even if no parks
    for col in ["RetailParkBranded", "RetailParkLocality"]:
        if col not in result.columns:
            result[col] = None

    return result


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    os.makedirs(EXPORTS_DIR, exist_ok=True)

    rc = load_retail_centres()

    # 1a. ONS Naming
    ons = generate_ons_naming(rc)
    ons_path = os.path.join(EXPORTS_DIR, "RC_Naming_ONS.csv")
    ons.to_csv(ons_path, index=False)
    print(f"  Saved: {ons_path} ({len(ons)} rows)")

    # Load OS Open Names (shared between 1b and 1c)
    open_names = load_os_open_names(prefer_english=PREFER_ENGLISH_NAMES)

    # 1b. OS Nearest
    os_nearest = generate_os_nearest(rc, open_names)
    os_path = os.path.join(EXPORTS_DIR, "RC_Naming_OS.csv")
    os_nearest.to_csv(os_path, index=False)
    print(f"  Saved: {os_path} ({len(os_nearest)} rows)")

    # 1c. OS Internal
    os_internal = generate_os_internal(rc, open_names)
    os_int_path = os.path.join(EXPORTS_DIR, "RC_Naming_OS_Internal.csv")
    os_internal.to_csv(os_int_path, index=False)
    print(f"  Saved: {os_int_path} ({len(os_internal)} rows)")

    # 1d. Street Naming
    streets = generate_street_naming(rc)
    str_path = os.path.join(EXPORTS_DIR, "RC_Naming_Streets.csv")
    streets.to_csv(str_path, index=False)
    print(f"  Saved: {str_path} ({len(streets)} rows)")

    # 1e. OSM Retail Park Names
    osm_rp = generate_osm_retail_park_names(rc)
    osm_rp_path = os.path.join(EXPORTS_DIR, "RC_Naming_OSM_RetailParks.csv")
    osm_rp.to_csv(osm_rp_path, index=False)
    print(f"  Saved: {osm_rp_path} ({len(osm_rp)} rows)")

    print("\n=== Naming lookup generation complete ===")


if __name__ == "__main__":
    main()
