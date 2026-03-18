"""
Name Assembly & Export for UK Retail Centres.

Replicates the logic of 5_Generate_Exports.R:
  2a. Classification hierarchy (already in gpkg — used directly)
  2b. Name assembly from 4 lookup tables
  2c. Sub-area naming
  2d. Cleanup & deduplication
  2e. Export to gpkg + CSV

Reads lookup CSVs from exports/ and the input gpkg.
"""

import os
import re
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd

warnings.filterwarnings("ignore", category=FutureWarning)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
GPKG_PATH = os.path.join(BASE_DIR, "rc2025_foursquare_ignoreCounty.gpkg")
CRS_BNG = "EPSG:27700"

# ─── Shopping Outlets (hardcoded from R code) ─────────────────────────
SHOPPING_OUTLETS = [
    ("Regional Shopping Centre", "Westfield London", 51.50769, -0.22088),
    ("Regional Shopping Centre", "Metrocentre", 54.95721, -1.66745),
    ("Regional Shopping Centre", "Trafford Centre", 53.46510, -2.34764),
    ("Regional Shopping Centre", "Westfield Stratford City", 51.54426, -0.00433),
    ("Regional Shopping Centre", "Bluewater", 51.43912, 0.27160),
    ("Regional Shopping Centre", "intu Merry Hill", 52.48139, -2.11066),
    ("Regional Shopping Centre", "Lakeside Shopping Centre", 51.48941, 0.28538),
    ("Regional Shopping Centre", "Meadowhall", 53.41411, -1.41112),
    ("Regional Shopping Centre", "East Kilbride Shopping Centre", 55.76021, -4.17709),
    ("Regional Shopping Centre", "Silverburn Centre", 55.82113, -4.34125),
    ("Regional Shopping Centre", "intu Braehead", 55.87600, -4.36464),
    ("Regional Shopping Centre", "White Rose Centre", 53.75868, -1.57349),
    ("Large Outlet Shopping Centre", "Ashford Designer Outlet", 51.13739, 0.88017),
    ("Large Outlet Shopping Centre", "Astle Park West Bromwich", 52.52010, -1.99603),
    ("Large Outlet Shopping Centre", "Bicester Outlet Village", 51.89238, -1.15608),
    ("Large Outlet Shopping Centre", "Bideford Atlantic Village", 51.00756, -4.23733),
    ("Large Outlet Shopping Centre", "Burberry Factory Outlet London", 51.54651, -0.05093),
    ("Large Outlet Shopping Centre", "Castleford Junction 32 Outlet", 53.71246, -1.33884),
    ("Large Outlet Shopping Centre", "Chatham Dockside Outlet Centre", 51.40160, 0.53771),
    ("Large Outlet Shopping Centre", "Cheshire Oaks Designer Outlet", 53.26539, -2.88090),
    ("Large Outlet Shopping Centre", "Clacton Factory Outlet", 51.81859, 1.16821),
    ("Large Outlet Shopping Centre", "Clarks Village Outlet Somerset", 51.12833, -2.74159),
    ("Large Outlet Shopping Centre", "Dalton Park Outlet", 54.81537, -1.37392),
    ("Large Outlet Shopping Centre", "Doncaster Lakeside Village", 53.50769, -1.11360),
    ("Large Outlet Shopping Centre", "Dover De Bradelei Wharf Outlet", 51.12211, 1.31417),
    ("Large Outlet Shopping Centre", "East Midlands Outlet Junction 28", 53.10808, -1.31266),
    ("Large Outlet Shopping Centre", "Freeport Braintree", 51.87007, 0.57148),
    ("Large Outlet Shopping Centre", "Freeport Fleetwood Outlet", 53.91786, -3.01185),
    ("Large Outlet Shopping Centre", "Freeport Talke Stoke-on-Trent", 53.07060, -2.26308),
    ("Large Outlet Shopping Centre", "Gloucester Quays Outlet", 51.85953, -2.25162),
    ("Large Outlet Shopping Centre", "Hertfordshire Galleria Outlet Shopping", 51.76141, -0.24022),
    ("Large Outlet Shopping Centre", "Hornsea Freeport Outlet", 53.89849, -0.17242),
    ("Large Outlet Shopping Centre", "Kilver Court Designer Village", 51.19064, -2.53532),
    ("Large Outlet Shopping Centre", "London Designer Outlet Wembley", 51.55647, -0.28320),
    ("Large Outlet Shopping Centre", "Lowry Outlet Salford Quays", 53.47092, -2.29251),
    ("Large Outlet Shopping Centre", "Newcastle Royal Quays Outlet", 54.99533, -1.46428),
    ("Large Outlet Shopping Centre", "Portsmouth Gunwharf Quays", 50.79546, -1.10382),
    ("Large Outlet Shopping Centre", "Springfields Spalding Outlet", 52.79944, -0.12633),
    ("Large Outlet Shopping Centre", "Swindon Designer Outlet", 51.56272, -1.79719),
    ("Large Outlet Shopping Centre", "The Mill Outlet Batley", 53.71292, -1.62513),
    ("Large Outlet Shopping Centre", "York Designer Outlet", 53.92233, -1.07687),
    ("Large Outlet Shopping Centre", "Banbridge Village Outlet", 54.33172, -6.27615),
    ("Large Outlet Shopping Centre", "Cribbs Causeway", 51.52455, -2.59552),
    ("Large Outlet Shopping Centre", "Bridgend Designer Outlets Wales", 51.53241, -3.57684),
    ("Large Outlet Shopping Centre", "Gretna Gateway Outlet Village", 54.99688, -3.05652),
    ("Large Outlet Shopping Centre", "Livingston Designer Outlet", 55.88311, -3.52014),
    ("Large Outlet Shopping Centre", "Sterling Mills Outlet", 56.14927, -3.74005),
    ("Large Shopping Centre", "Salford Shopping Centre", 53.48880, -2.28913),
]


def load_data():
    """Load retail centres and lookup CSVs."""
    print("Loading retail centres...")
    rc = gpd.read_file(GPKG_PATH).to_crs(CRS_BNG)
    rc["RC_ID"] = rc["RC_ID"].astype(str)

    lookups = {}
    for name in ["RC_Naming_ONS", "RC_Naming_OS", "RC_Naming_OS_Internal", "RC_Naming_Streets", "RC_Naming_OSM_RetailParks"]:
        path = os.path.join(EXPORTS_DIR, f"{name}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, dtype={"RC_ID": str})
            lookups[name] = df
            print(f"  Loaded {name}: {len(df)} rows")
        else:
            print(f"  WARNING: {path} not found")
            lookups[name] = pd.DataFrame({"RC_ID": rc["RC_ID"]})

    return rc, lookups


def match_outlets_to_centres(rc):
    """Match hardcoded shopping outlet coordinates to RC_IDs."""
    outlets = pd.DataFrame(SHOPPING_OUTLETS, columns=["SubType", "Name", "Lat", "Lon"])
    outlets_gdf = gpd.GeoDataFrame(
        outlets,
        geometry=gpd.points_from_xy(outlets["Lon"], outlets["Lat"]),
        crs="EPSG:4326",
    ).to_crs(CRS_BNG)

    # Spatial join to find which centre each outlet falls in
    matched = gpd.sjoin(outlets_gdf, rc[["RC_ID", "geometry"]], how="left", predicate="within")
    matched = matched[matched["RC_ID"].notna()]
    return matched[["SubType", "Name", "RC_ID"]].drop_duplicates("Name")


def assemble_name_components(components, include_parentheses=True):
    """
    Assemble name from components: [street, neighbourhood, la, region, country].
    Format: Street; Neighbourhood; LA (Region; Country)
    """
    street, neighbourhood, la, region, country = [
        str(c) if pd.notna(c) and str(c).strip() else "" for c in components
    ]

    parts = []
    if street:
        parts.append(street)
    if neighbourhood:
        parts.append(neighbourhood)
    if la:
        parts.append(la)

    if include_parentheses and (region or country):
        region_country = "; ".join(filter(None, [region, country]))
        if region_country:
            parts.append(f"({region_country})")

    name = "; ".join(parts)
    return name


def clean_name(name):
    """Apply all name cleanup rules."""
    if pd.isna(name) or not name:
        return name

    # Collapse repeated separators
    while "; ; " in name:
        name = name.replace("; ; ", "; ")

    # Remove leading/trailing separators
    name = name.strip("; ")

    # Fix country duplication
    name = name.replace("Scotland; Scotland", "Scotland")
    name = name.replace("Wales; Wales", "Wales")
    name = name.replace("Northern Ireland; Northern Ireland", "Northern Ireland")

    # Fix "; (" -> " ("
    name = name.replace("; (", " (")

    # Fix LA inversions
    name = name.replace("Bristol, City of", "City of Bristol")
    name = name.replace("Kingston upon Hull, City of", "City of Kingston upon Hull")
    name = name.replace("Herefordshire, County of", "County of Herefordshire")

    return name


def generate_names():
    """Main name generation pipeline."""
    rc, lookups = load_data()

    ons = lookups["RC_Naming_ONS"]
    os_nearest = lookups["RC_Naming_OS"]
    os_internal = lookups["RC_Naming_OS_Internal"]
    streets = lookups["RC_Naming_Streets"]
    osm_rp = lookups["RC_Naming_OSM_RetailParks"]

    # ─── Classification: use what's in the gpkg ────────────────────
    print("\n=== 2a. Classification ===")
    classification = rc[["RC_ID", "Classification"]].copy()
    print(f"  Classifications:\n{classification['Classification'].value_counts().to_string()}")

    # Match shopping outlets
    outlets = match_outlets_to_centres(rc)
    print(f"  Matched {len(outlets)} shopping outlets to centres")

    # Override classification for matched outlets
    for _, row in outlets.iterrows():
        mask = classification["RC_ID"] == row["RC_ID"]
        if mask.any():
            classification.loc[mask, "Classification"] = row["SubType"]

    # ─── Level 1: Street Name ──────────────────────────────────────
    print("\n=== 2b. Name Assembly ===")
    print("  Level 1: Street names...")
    level1 = streets[["RC_ID"]].copy()
    level1["Street"] = None

    if "Str_1" in streets.columns and "Str_1_P" in streets.columns:
        str1 = streets["Str_1"]
        str1_p = pd.to_numeric(streets["Str_1_P"], errors="coerce")
        str2 = streets.get("Str_2", pd.Series(dtype=str))
        str2_p = pd.to_numeric(streets.get("Str_2_P", pd.Series(dtype=float)), errors="coerce")

        # 31% threshold: if top street > 31%, use alone; else combine top two
        level1["Street"] = np.where(
            str1_p > 0.31,
            str1.astype(str),
            np.where(
                str2_p > 0.31,
                str1.astype(str) + " & " + str2.astype(str),
                None,
            ),
        )
        # Clean up 'nan' strings
        level1.loc[level1["Street"].isin(["nan", "None", "nan & nan"]), "Street"] = None
        # Title case
        level1["Street"] = level1["Street"].apply(
            lambda x: x.title() if pd.notna(x) else x
        )

    # ─── Level 2: Neighbourhood (OS place name) ───────────────────
    print("  Level 2: Neighbourhood names...")

    # From OS nearest: pick type with minimum distance
    level2 = os_nearest[["RC_ID"]].copy()
    level2["nearest"] = None

    dist_cols = {}
    name_cols = {}
    for short in ["City", "Town", "Village", "Suburban", "Settlement", "Hamlet"]:
        if short in os_nearest.columns:
            name_cols[short] = short
        if f"{short}D" in os_nearest.columns:
            dist_cols[short] = f"{short}D"

    if dist_cols:
        # Find minimum distance type for each centre
        dist_df = os_nearest[list(dist_cols.values())].apply(pd.to_numeric, errors="coerce")
        min_type = dist_df.idxmin(axis=1)  # Column name of minimum distance

        for i, (idx, mt) in enumerate(min_type.items()):
            if pd.notna(mt):
                short = mt.replace("D", "")
                if short in os_nearest.columns:
                    val = os_nearest.loc[idx, short]
                    if pd.notna(val):
                        level2.loc[idx, "nearest"] = val

    # Override with internal names where available (prefer internal)
    # Build internal pick independently using priority chain (like R code),
    # then override nearest wherever internal has a value.
    if "RC_ID" in os_internal.columns:
        merged = level2.merge(os_internal, on="RC_ID", how="left")
        merged["inner"] = None
        for ptype in ["City", "Village", "Town", "Suburban", "Settlement", "Hamlet"]:
            if ptype not in merged.columns:
                continue
            has_value = merged[ptype].notna() & (merged[ptype].str.strip() != "")
            not_yet_set = merged["inner"].isna()
            merged.loc[has_value & not_yet_set, "inner"] = (
                merged.loc[has_value & not_yet_set, ptype].str.split(";").str[0].str.strip()
            )
        # Override nearest with internal pick where available
        has_inner = merged["inner"].notna()
        merged.loc[has_inner, "nearest"] = merged.loc[has_inner, "inner"]
        level2["nearest"] = merged["nearest"]

    # NI centres: OS Open Names doesn't cover NI, so clear the bogus
    # Scottish nearest place and use SOA neighbourhood name instead.
    # Identify NI centres from rc["RegionName"] since ONS Country may be NaN.
    ni_ids = rc.loc[rc["RegionName"].isin(["NI", "Northern Ireland"]), "RC_ID"].tolist()
    if ni_ids:
        # Clear OS-derived names for NI centres
        level2.loc[level2["RC_ID"].isin(ni_ids), "nearest"] = None

        # Use SOA neighbourhood from ONS if available
        if "NbhdNM_1" in ons.columns:
            for rc_id in ni_ids:
                nbhd = ons.loc[ons["RC_ID"] == rc_id, "NbhdNM_1"]
                if len(nbhd) > 0 and pd.notna(nbhd.iloc[0]):
                    nbhd_clean = re.sub(r"_*\d+", "", str(nbhd.iloc[0])).strip()
                    level2.loc[level2["RC_ID"] == rc_id, "nearest"] = nbhd_clean

    # ─── Merge and assemble final names ────────────────────────────
    print("  Assembling final names...")

    naming = rc[["RC_ID"]].copy()

    # Get LA, Region, Country from ONS lookup or pre-joined columns
    if "LocalAuthorityNM_1" in ons.columns:
        naming = naming.merge(ons[["RC_ID", "LocalAuthorityNM_1", "Country", "RegionNM"]].drop_duplicates("RC_ID"),
                              on="RC_ID", how="left")
    else:
        naming["LocalAuthorityNM_1"] = rc["LocalAuthorityNM_1"].values
        naming["Country"] = rc.get("Country", "").values if "Country" in rc.columns else ""
        naming["RegionNM"] = rc["RegionName"].values

    # Fill country/region if missing
    if naming["Country"].isna().any() or (naming["Country"] == "").any():
        region_map = rc.set_index("RC_ID")["RegionName"]
        for idx in naming.index:
            if pd.isna(naming.loc[idx, "Country"]) or naming.loc[idx, "Country"] == "":
                rc_id = naming.loc[idx, "RC_ID"]
                rgn = region_map.get(rc_id, "")
                if rgn in ["North East", "North West", "Yorkshire and The Humber",
                           "East Midlands", "West Midlands", "East of England",
                           "London", "South East", "South West"]:
                    naming.loc[idx, "Country"] = "England"
                    naming.loc[idx, "RegionNM"] = rgn
                elif rgn == "Wales":
                    naming.loc[idx, "Country"] = "Wales"
                    naming.loc[idx, "RegionNM"] = "Wales"
                elif rgn == "Scotland":
                    naming.loc[idx, "Country"] = "Scotland"
                    naming.loc[idx, "RegionNM"] = "Scotland"
                elif rgn in ("Northern Ireland", "NI"):
                    naming.loc[idx, "Country"] = "Northern Ireland"
                    naming.loc[idx, "RegionNM"] = "Northern Ireland"

    naming = naming.merge(classification, on="RC_ID", how="left")
    naming = naming.merge(level1[["RC_ID", "Street"]], on="RC_ID", how="left")
    naming = naming.merge(level2[["RC_ID", "nearest"]].rename(columns={"nearest": "Neighbourhood"}),
                          on="RC_ID", how="left")

    # Assemble names based on classification
    naming["RC_Name"] = ""

    for idx in naming.index:
        cls = naming.loc[idx, "Classification"]
        street = naming.loc[idx, "Street"]
        nbhd = naming.loc[idx, "Neighbourhood"]
        la = naming.loc[idx, "LocalAuthorityNM_1"]
        region = naming.loc[idx, "RegionNM"]
        country = naming.loc[idx, "Country"]

        if cls in ("Regional Centre", "Major Town Centre", "Town Centre"):
            # No street — Neighbourhood; LA (Region; Country)
            name = assemble_name_components([None, nbhd, la, region, country])
        else:
            # Street; Neighbourhood; LA (Region; Country)
            name = assemble_name_components([street, nbhd, la, region, country])

        naming.loc[idx, "RC_Name"] = name

    # ─── Retail park naming ────────────────────────────────────────
    # Priority: 1) OSM landuse name  2) Foursquare branded  3) street-based + "Retail Park"
    print("  Retail park naming...")
    rp_mask = naming["Classification"].isin(["Large Retail Park", "Small Retail Park"])
    if rp_mask.any():
        # Track which parks got a proper name
        rp_named = set()

        # 1) OSM landuse names (first choice)
        if "OSM_RetailParkName" in osm_rp.columns:
            for _, row in osm_rp[osm_rp["OSM_RetailParkName"].notna()].iterrows():
                mask = (naming["RC_ID"] == row["RC_ID"]) & rp_mask
                if not mask.any():
                    continue
                la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
                region = naming.loc[mask, "RegionNM"].iloc[0]
                country = naming.loc[mask, "Country"].iloc[0]
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, row["OSM_RetailParkName"], la, region, country]
                )
                rp_named.add(row["RC_ID"])
            print(f"    OSM named: {len(rp_named)} retail parks")

        # 2) Foursquare branded names (fallback for parks without OSM name)
        rp_cols = ["RC_ID"]
        for col in ["RetailParkBranded", "RetailParkLocality"]:
            if col in streets.columns:
                rp_cols.append(col)
        rp_info = streets[rp_cols].copy()

        fsq_count = 0
        for _, row in rp_info.iterrows():
            if row["RC_ID"] in rp_named:
                continue  # already named by OSM
            mask = (naming["RC_ID"] == row["RC_ID"]) & rp_mask
            if not mask.any():
                continue
            branded = row.get("RetailParkBranded")
            if pd.notna(branded):
                la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
                region = naming.loc[mask, "RegionNM"].iloc[0]
                country = naming.loc[mask, "Country"].iloc[0]
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, branded, la, region, country]
                )
                rp_named.add(row["RC_ID"])
                fsq_count += 1
        print(f"    Foursquare branded: {fsq_count} retail parks")

    # 3) Append "Retail Park" to first name component for remaining retail parks
    for idx in naming[rp_mask].index:
        rc_id = naming.loc[idx, "RC_ID"]
        if rc_id in rp_named:
            continue  # already has a proper name
        name = naming.loc[idx, "RC_Name"]
        parts = name.split("; ")
        if parts:
            parts[0] = parts[0].strip() + " Retail Park"
            naming.loc[idx, "RC_Name"] = "; ".join(p.strip() for p in parts)

    # ─── Shopping centre / outlet naming ───────────────────────────
    print("  Shopping centre naming...")
    outlets = match_outlets_to_centres(rc)
    for _, row in outlets.iterrows():
        mask = naming["RC_ID"] == row["RC_ID"]
        if mask.any():
            la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
            region = naming.loc[mask, "RegionNM"].iloc[0]
            country = naming.loc[mask, "Country"].iloc[0]
            naming.loc[mask, "RC_Name"] = assemble_name_components(
                [None, row["Name"], la, region, country]
            )

    # ─── Sub-area naming ──────────────────────────────────────────
    # Parent_ID is a group number, NOT an RC_ID. First build a "parent"
    # name for each group (the joined centre), then give each sub-area
    # its own name using its local neighbourhood prefixed to the parent name.
    print("\n=== 2c. Sub-area Naming ===")
    sub_areas = rc[rc["was_split"] == True][["RC_ID", "Parent_ID", "tr_retailN"]].copy()
    sub_areas["Parent_ID"] = sub_areas["Parent_ID"].astype(int).astype(str)
    sub_areas["tr_retailN"] = pd.to_numeric(sub_areas["tr_retailN"], errors="coerce").fillna(0)
    print(f"  {len(sub_areas)} sub-areas across {sub_areas['Parent_ID'].nunique()} parent groups")

    for _, group in sub_areas.groupby("Parent_ID"):
        member_ids = group["RC_ID"].tolist()

        # Determine the parent centre name: use the City-type OS name from
        # the group (closest City across all members), falling back to Town
        city_name = None
        best_dist = float("inf")
        for mid in member_ids:
            row = os_nearest[os_nearest["RC_ID"] == mid]
            if len(row) == 0:
                continue
            for ptype in ["City", "Town"]:
                dcol = f"{ptype}D"
                if ptype in row.columns and dcol in row.columns:
                    d = pd.to_numeric(row.iloc[0][dcol], errors="coerce")
                    nm = row.iloc[0][ptype]
                    if pd.notna(d) and d < best_dist and pd.notna(nm):
                        best_dist = d
                        city_name = str(nm).split(";")[0].strip()

        # Primary sub-area = highest retail count
        primary_rc_id = group.sort_values("tr_retailN", ascending=False).iloc[0]["RC_ID"]
        primary_mask = naming["RC_ID"] == primary_rc_id
        if not primary_mask.any():
            continue

        # Build parent name: City; LA (Region; Country)
        la = naming.loc[primary_mask, "LocalAuthorityNM_1"].iloc[0]
        region = naming.loc[primary_mask, "RegionNM"].iloc[0]
        country = naming.loc[primary_mask, "Country"].iloc[0]
        parent_name = assemble_name_components([None, city_name, la, region, country])

        # All sub-areas in this group get the parent name
        for mid in member_ids:
            mask = naming["RC_ID"] == mid
            if mask.any():
                naming.loc[mask, "RC_Name"] = parent_name

    # ─── Cleanup ──────────────────────────────────────────────────
    print("\n=== 2d. Cleanup & Deduplication ===")
    naming["RC_Name"] = naming["RC_Name"].apply(clean_name)

    # Handle empty names
    naming.loc[naming["RC_Name"].isna() | (naming["RC_Name"] == ""), "RC_Name"] = (
        naming.loc[naming["RC_Name"].isna() | (naming["RC_Name"] == ""), "LocalAuthorityNM_1"]
    )

    # Deduplicate: append " - 2", " - 3" etc.
    # Sort by classification hierarchy so higher-ranked centres keep the clean name
    class_priority = {
        "Regional Centre": 0, "Major Town Centre": 1, "Town Centre": 2,
        "Market Town": 3, "District Centre": 4, "Local Centre": 5,
        "Small Local Centre": 6, "Large Retail Park": 7, "Small Retail Park": 8,
        "Large Shopping Centre": 9, "Small Shopping Centre": 10,
    }
    name_counts = naming["RC_Name"].value_counts()
    duplicates = name_counts[name_counts > 1].index.tolist()

    for dup_name in duplicates:
        dup_mask = naming["RC_Name"] == dup_name
        dup_rows = naming.loc[dup_mask].copy()
        dup_rows["_class_priority"] = dup_rows["Classification"].map(class_priority).fillna(99)
        dup_indices = dup_rows.sort_values("_class_priority").index.tolist()
        # First (highest-ranked) keeps original name
        for i, idx in enumerate(dup_indices[1:], start=1):
            naming.loc[idx, "RC_Name"] = f"{dup_name} - {i}"

    # ─── Export ────────────────────────────────────────────────────
    print("\n=== 2e. Export ===")
    os.makedirs(EXPORTS_DIR, exist_ok=True)

    # CSV lookup
    csv_cols = ["RC_ID", "Street", "Neighbourhood", "LocalAuthorityNM_1",
                "RegionNM", "Country", "RC_Name", "Classification"]
    csv_out = naming[[c for c in csv_cols if c in naming.columns]].copy()
    csv_path = os.path.join(EXPORTS_DIR, "rc2025_naming_lookup.csv")
    csv_out.to_csv(csv_path, index=False)
    print(f"  Saved: {csv_path}")

    # GeoPackage
    rc_named = rc.merge(naming[["RC_ID", "RC_Name"]], on="RC_ID", how="left")
    gpkg_path = os.path.join(EXPORTS_DIR, "rc2025_named.gpkg")
    rc_named.to_file(gpkg_path, driver="GPKG")
    print(f"  Saved: {gpkg_path}")

    # GeoParquet
    parquet_path = os.path.join(EXPORTS_DIR, "rc2025_named.parquet")
    rc_named.to_parquet(parquet_path)
    print(f"  Saved: {parquet_path}")

    # Summary
    print(f"\n=== Complete ===")
    print(f"  Total centres named: {naming['RC_Name'].notna().sum()} / {len(naming)}")
    print(f"  Unique names: {naming['RC_Name'].nunique()}")

    # Spot-check: show some Regional Centres
    regional = naming[naming["Classification"] == "Regional Centre"]["RC_Name"].head(10)
    if len(regional) > 0:
        print(f"\n  Sample Regional Centres:")
        for name in regional:
            print(f"    {name}")

    # Show some retail parks
    rps = naming[naming["Classification"].isin(["Large Retail Park", "Small Retail Park"])]["RC_Name"].head(5)
    if len(rps) > 0:
        print(f"\n  Sample Retail Parks:")
        for name in rps:
            print(f"    {name}")

    return naming


if __name__ == "__main__":
    generate_names()
