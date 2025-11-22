import os
import argparse
import re
import math
import polars as pl
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from pathlib import Path
from typing import Optional
import networkx as nx
import h3
from utils import utils as ut


# Make sure NLTK names are available
import nltk
nltk.download('names')


def _make_key(col: pl.Expr) -> pl.Expr:
    """
    Enhanced normalization for defunct brand matching.

    Handles:
    - Case normalization
    - Whitespace stripping
    - Company suffixes (Ltd, Limited, Stores, etc.)
    - Apostrophes (Jack's → jacks)
    - Hyphens (Kwik-Save → kwiksave)
    - Multiple spaces collapsed
    """
    # Lowercase and strip
    result = col.str.strip_chars().str.to_lowercase()

    # Strip common company suffixes
    suffixes = [
        r'\s+(ltd|limited|plc|group|stores?|shops?|uk|inc|corp|co\.?)',
        r'\s+\(uk\)',
        r'\s+\(.*?\)',  # Any bracketed text at end
        r'\s+supermarket'
    ]
    for suffix in suffixes:
        result = result.str.replace(suffix + r'$', '', literal=False)

    # Remove apostrophes (Jack's → jacks)
    result = result.str.replace_all("'", "", literal=False)
    result = result.str.replace_all("'", "", literal=False)  # curly apostrophe

    # Remove hyphens (Kwik-Save → kwiksave, but keep spaces)
    result = result.str.replace_all("-", "", literal=False)

    # Collapse multiple spaces to single space
    result = result.str.replace_all(r'\s+', ' ', literal=False)

    # Final strip
    result = result.str.strip_chars()

    return result


def filter_defunct_retailers(
    foursquare: pl.DataFrame,
    defunct_csv_path: str = "data/input_files/defunct_uk_retailers_wikipedia_full.csv",
    save_removed: bool = True,
    output_dir: str = "data/POI_files/defunct_removed",
    top_n_brands: int = 10,
    save_all_removed: bool = True
) -> pl.DataFrame:
    """
    Filter out defunct UK retailers from Foursquare POI data.

    Matches POI names against a list of defunct retailers and removes them.
    Optionally saves removed POIs and creates GeoParquet files for top N brands.

    Parameters:
    - foursquare: polars.DataFrame containing Foursquare POI data with 'name', 'lat', 'lng' columns
    - defunct_csv_path: Path to CSV file with defunct retailers (must have 'Brand' column)
    - save_removed: Whether to save removed POIs and brand statistics (default: True)
    - output_dir: Directory to save removed POI files (default: "data/POI_files/defunct_removed")
    - top_n_brands: Number of top brands to save as separate GeoParquet files (default: 10)
    - save_all_removed: Whether to save complete file with ALL removed POIs (default: True)

    Returns:
    - polars.DataFrame with defunct retailers removed
    """

    print(f"Loading defunct retailers from: {defunct_csv_path}")
    defunct_retailers = pl.read_csv(defunct_csv_path)

    # Clean defunct retailers list: drop duplicates and remove bracketed text
    defunct_retailers = (
        defunct_retailers
        .unique(subset=["Brand"])
        .with_columns(
            pl.col("Brand").str.replace(r"\s*\(.*?\)", "", literal=False)
        )
    )

    print(f"Loaded {len(defunct_retailers):,} unique defunct retailers")

    # Build normalized keys for matching
    defunct = defunct_retailers.with_columns(brand_key=_make_key(pl.col("Brand")))
    fs = foursquare.with_columns(brand_key=_make_key(pl.col("name")))

    # Find POIs to remove (inner join on normalized brand name)
    removed = fs.join(defunct.select("brand_key").unique(), on="brand_key", how="inner")

    # Count removed POIs
    removed_counts = (
        removed
        .group_by("brand_key")
        .len()
        .rename({"len": "removed_poi_count"})
        .sort("removed_poi_count", descending=True)
    )

    total_removed = removed_counts.select(pl.col("removed_poi_count").sum()).item()
    print(f"Found {total_removed:,} POIs matching defunct retailers")
    print(f"Unique defunct brands matched: {len(removed_counts):,}")

    # Save removed POIs and brand statistics
    if save_removed and total_removed > 0:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save top brands summary
        top_brands = removed_counts.head(top_n_brands)

        # Add human-readable brand names
        defunct_lookup = defunct.select(["brand_key", "Brand"]).unique()
        top_brands_readable = (
            top_brands
            .join(defunct_lookup, on="brand_key", how="left")
            .select(["Brand", "removed_poi_count"])
        )

        summary_path = output_path / "defunct_removed_summary.csv"
        top_brands_readable.write_csv(summary_path)
        print(f"\nTop {top_n_brands} removed brands saved to: {summary_path}")
        print(top_brands_readable)

        # Get top N brand keys for detailed GeoParquet export
        top_n_keys = removed_counts.select("brand_key").head(top_n_brands)

        # Keep only removed POIs for those top N brands
        top_n_removed = removed.join(top_n_keys, on="brand_key", how="inner")

        # Add human-readable brand back in
        top_n_removed = (
            top_n_removed
            .join(defunct_lookup, on="brand_key", how="left")
            .rename({"Brand": "defunct_brand"})
        )

        # Ensure lat/lng present
        top_n_removed = top_n_removed.filter(
            pl.all_horizontal(
                pl.col("lat").is_not_null(),
                pl.col("lng").is_not_null()
            )
        )

        # Write one GeoParquet per brand
        if len(top_n_removed) > 0:
            parts = top_n_removed.partition_by("defunct_brand", as_dict=False)

            print(f"\nSaving top {len(parts)} brands as GeoParquet files:")
            for i, df in enumerate(parts, start=1):
                pdf = df.to_pandas()
                gdf = gpd.GeoDataFrame(
                    pdf,
                    geometry=gpd.points_from_xy(pdf["lng"], pdf["lat"]),
                    crs="EPSG:4326"
                )
                # Use brand name in filename (sanitized)
                brand_name = pdf["defunct_brand"].iloc[0]
                safe_name = re.sub(r'[^\w\-_]', '_', brand_name)
                fname = output_path / f"{safe_name}.geo.parquet"
                gdf.to_parquet(fname)
                print(f"  - {fname.name}: {len(gdf):,} POIs")

        # Save ALL removed POIs to a single GeoParquet file
        if save_all_removed:
            print(f"\nSaving all {total_removed:,} removed POIs to single file...")

            # Add defunct_brand column to all removed POIs
            all_removed = (
                removed
                .join(defunct_lookup, on="brand_key", how="left")
                .rename({"Brand": "defunct_brand"})
                .filter(
                    pl.all_horizontal(
                        pl.col("lat").is_not_null(),
                        pl.col("lng").is_not_null()
                    )
                )
            )

            if len(all_removed) > 0:
                pdf = all_removed.to_pandas()
                gdf = gpd.GeoDataFrame(
                    pdf,
                    geometry=gpd.points_from_xy(pdf["lng"], pdf["lat"]),
                    crs="EPSG:4326"
                )
                all_geoparquet = output_path / "all_removed_pois.geo.parquet"
                gdf.to_parquet(all_geoparquet)
                print(f"  ✓ Saved: {all_geoparquet.name} ({len(gdf):,} POIs)")

    # Keep POIs that didn't match defunct retailers (anti-join)
    filtered = fs.join(defunct.select("brand_key").unique(), on="brand_key", how="anti")

    # Drop the temporary brand_key column
    filtered = filtered.drop("brand_key")

    print(f"\nPOIs remaining after defunct filter: {len(filtered):,}")

    return filtered


def filter_by_uk_boundary(
    foursquare: pl.DataFrame,
    boundary_path: str = "../data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
    buffer_m: int = 50,
    save_outside: bool = False,
    output_path: Optional[str] = None
) -> pl.DataFrame:
    """
    Filter Foursquare POIs to keep only those within the UK boundary (with optional buffer).

    POIs slightly outside the UK boundary are often mislocated but real POIs. The buffer
    helps catch these edge cases, though a tight buffer (50-100m) is recommended to avoid
    including genuinely offshore POIs.

    Parameters:
    - foursquare: polars.DataFrame containing Foursquare POI data with 'lat' and 'lng' columns
    - boundary_path: Path to UK boundary geopackage file (default: Countries_December_2022 .gpkg)
    - buffer_m: Buffer distance in meters to extend boundary (default: 50m)
    - save_outside: Whether to save POIs outside the boundary for inspection (default: False)
    - output_path: Path to save outside POIs if save_outside=True (default: "../data/POI_files/foursquare_outside_uk.parquet")

    Returns:
    - polars.DataFrame containing only POIs within the buffered UK boundary
    """

    # Convert Polars -> Pandas -> GeoDataFrame
    pdf = foursquare.to_pandas()
    foursquare_gdf = gpd.GeoDataFrame(
        pdf,
        geometry=gpd.points_from_xy(pdf["lng"], pdf["lat"]),
        crs="EPSG:4326"
    ).to_crs(epsg=27700)

    # Load UK boundary
    uk_boundary = gpd.read_file(boundary_path).to_crs(epsg=27700)

    # Dissolve into a single polygon and add buffer
    uk_boundary = uk_boundary.dissolve()
    uk_boundary["geometry"] = uk_boundary.buffer(buffer_m)

    # Spatial join: keep POIs that intersect buffered boundary
    joined = gpd.sjoin(
        foursquare_gdf, uk_boundary, how="left", predicate="within"
    )

    # POIs with no boundary match = outside UK (+ buffer)
    outside_uk = joined[joined.index_right.isna()]
    inside_uk = joined[joined.index_right.notna()]

    print(f"Total POIs: {len(foursquare_gdf):,}")
    print(f"Outside UK boundary ({buffer_m}m buffer): {len(outside_uk):,}")
    print(f"Inside UK boundary: {len(inside_uk):,}")

    # Optionally save outside POIs for inspection
    if save_outside:
        if output_path is None:
            output_path = "../data/POI_files/foursquare_outside_uk.parquet"
        outside_uk.to_parquet(output_path, index=False)
        print(f"Outside POIs saved to: {output_path}")

    # Drop the spatial join columns (index_right) and convert back to Polars
    inside_uk = inside_uk.drop(columns=["index_right"], errors="ignore")

    # Convert back to Polars DataFrame (drop geometry column)
    inside_uk_df = inside_uk.drop(columns=["geometry"])
    result = pl.from_pandas(inside_uk_df)

    return result


# === Duplicate POI Detection Helper Functions ===

def _norm_text_dup(s: str) -> str:
    """Normalize text for duplicate detection."""
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_site_dup(s: str) -> str:
    """Normalize website URLs for duplicate detection."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"^https?://(www\.)?", "", s)
    s = s.rstrip("/")
    return s


def _levenshtein(a: str, b: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    if len(a) > len(b): a, b = b, a
    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, start=1):
        curr = [j]
        for i, ca in enumerate(a, start=1):
            curr.append(min(prev[i] + 1, curr[i - 1] + 1, prev[i - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _lev_ratio(a: str, b: str) -> float:
    """Calculate Levenshtein similarity ratio (0-1, higher = more similar)."""
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return 0.0
    return 1.0 - (_levenshtein(a, b) / max(la, lb))


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    """Calculate haversine distance in meters between two lat/lng points."""
    EARTH_R_M = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def filter_duplicate_pois(
    foursquare: pl.DataFrame,
    name_threshold: float = 0.6,
    dist_thresh: float = 15.0,
    save_removed: bool = True,
    output_dir: str = "data/POI_files/duplicates_removed"
) -> pl.DataFrame:
    """
    Remove duplicate POIs based on distance, address, and name/tel/website matching.

    Duplicate criteria:
    - Distance < dist_thresh meters (default: 15m)
    - Address same OR one has no address
    - At least one of: name match (≥ name_threshold), tel match, website match

    From each duplicate group, keeps only the most recently refreshed POI.

    Parameters:
    - foursquare: polars.DataFrame with POI data (must have lat, lng, name, address, tel, website, date_refreshed, h3_11)
    - name_threshold: Minimum name similarity ratio (0-1) to consider a match (default: 0.6)
    - dist_thresh: Maximum distance in meters to consider POIs nearby (default: 15m)
    - save_removed: Whether to save removed POIs and statistics (default: True)
    - output_dir: Directory to save removed POI files (default: "data/POI_files/duplicates_removed")

    Returns:
    - polars.DataFrame with duplicate POIs removed
    """

    print(f"\nFinding duplicate POIs (distance < {dist_thresh}m, name threshold: {name_threshold})...")

    # Add row_id if not present
    df = foursquare
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    initial_count = len(df)

    # Normalize columns
    dfn = (
        df.with_columns([
            pl.col("lat").cast(pl.Float64),
            pl.col("lng").cast(pl.Float64),
            pl.col("name").map_elements(_norm_text_dup, return_dtype=str).alias("name_norm"),
            pl.col("address").map_elements(_norm_text_dup, return_dtype=str).alias("address_norm"),
            pl.col("tel").map_elements(_norm_text_dup, return_dtype=str).alias("tel_norm"),
            pl.col("website").map_elements(_norm_site_dup, return_dtype=str).alias("website_norm"),
        ])
        .select([
            "row_id", "lat", "lng", "h3_11", "fsq_category_id",
            "name_norm", "address_norm", "tel_norm", "website_norm"
        ])
    )

    # Use H3 for efficient spatial lookup
    unique_cells = dfn.select("h3_11").unique()

    neighbors = (
        unique_cells
        .with_columns(
            pl.col("h3_11")
              .map_elements(lambda h: list(h3.grid_disk(h, 1)), return_dtype=pl.List(pl.Utf8))
              .alias("cand_cells")
        )
        .explode("cand_cells")
        .rename({"h3_11": "src_cell", "cand_cells": "cand_cell"})
    )

    # Expand to neighbors
    dfn_exp = (
        dfn.join(neighbors, left_on="h3_11", right_on="src_cell", how="inner")
           .select([
               "row_id", "lat", "lng", "h3_11", "fsq_category_id",
               "name_norm", "address_norm", "tel_norm", "website_norm",
               "cand_cell"
           ])
    )

    # Self-join on H3 neighbors + same category
    pairs_raw = (
        dfn_exp.join(
            dfn,
            left_on=["cand_cell", "fsq_category_id"],
            right_on=["h3_11", "fsq_category_id"],
            how="inner",
            suffix="_r",
        )
        .filter(pl.col("row_id") < pl.col("row_id_r"))
    )

    # Pre-filter by bbox
    pairs_pre = pairs_raw.filter(
        ((pl.col("lat") - pl.col("lat_r")).abs() <= 0.0002) &
        ((pl.col("lng") - pl.col("lng_r")).abs() <= 0.0002)
    )

    # Apply all filter criteria
    pairs = (
        pairs_pre
        .with_columns([
            # Distance
            pl.struct(["lat","lng","lat_r","lng_r"])
              .map_elements(lambda s: _haversine_m(s["lat"], s["lng"], s["lat_r"], s["lng_r"]), return_dtype=pl.Float64)
              .alias("dist_m"),
            # Address checks
            (pl.col("address_norm") == "").alias("addr1_empty"),
            (pl.col("address_norm_r") == "").alias("addr2_empty"),
            (pl.col("address_norm") == pl.col("address_norm_r")).alias("addr_same"),
            # Matching fields
            (pl.col("tel_norm") == pl.col("tel_norm_r")).alias("m_tel"),
            (pl.col("website_norm") == pl.col("website_norm_r")).alias("m_website"),
            pl.struct(["name_norm","name_norm_r"])
              .map_elements(lambda s: _lev_ratio(s["name_norm"], s["name_norm_r"]), return_dtype=pl.Float64)
              .alias("name_sim"),
        ])
        .with_columns([
            (pl.col("name_sim") >= name_threshold).alias("m_name"),
            (pl.col("addr_same") | pl.col("addr1_empty") | pl.col("addr2_empty")).alias("addr_ok"),
        ])
        .with_columns(
            (
                (pl.col("dist_m") <= dist_thresh) &
                pl.col("addr_ok") &
                (pl.col("m_tel") | pl.col("m_website") | pl.col("m_name"))
            ).alias("is_match")
        )
        .filter(pl.col("is_match"))
        .select(["row_id", "row_id_r"])
    )

    print(f"  Found {len(pairs):,} duplicate pairs")

    if len(pairs) == 0:
        print("  No duplicates found")
        return df.drop("row_id", strict=False)

    # Build connected components (duplicate groups)
    G = nx.Graph()
    for row in pairs.iter_rows():
        G.add_edge(row[0], row[1])

    components = list(nx.connected_components(G))
    print(f"  Duplicate groups: {len(components):,}")

    # Create group_id mapping
    group_mapping = []
    for group_id, component in enumerate(components):
        for row_id in component:
            group_mapping.append({"row_id": row_id, "group_id": group_id, "group_size": len(component)})

    group_df = pl.DataFrame(group_mapping)
    print(f"  Total POIs in duplicate groups: {len(group_df):,}")

    # Determine which POIs to keep (most recently refreshed)
    duplicates_with_groups = (
        df.join(group_df, on="row_id", how="inner")
        .with_columns(
            pl.when(pl.col("date_refreshed").is_null())
              .then(pl.col("date_created"))
              .otherwise(pl.col("date_refreshed"))
              .str.strptime(pl.Datetime, format="%Y-%m-%d", strict=False)
              .alias("refresh_date")
        )
    )

    # For each group, find most recent
    keep_ids = (
        duplicates_with_groups
        .sort(["group_id", "refresh_date"], descending=[False, True])
        .group_by("group_id")
        .agg(pl.first("row_id").alias("keep_row_id"))
    )

    # Mark which to keep/remove
    duplicates_final = (
        duplicates_with_groups
        .join(keep_ids, on="group_id", how="left")
        .with_columns((pl.col("row_id") == pl.col("keep_row_id")).alias("keep"))
    )

    to_remove = duplicates_final.filter(pl.col("keep") == False)
    print(f"  POIs to remove: {len(to_remove):,}")

    # Save removed POIs
    if save_removed and len(to_remove) > 0:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save all removed POIs
        remove_path = output_path / "duplicates_removed.parquet"
        to_remove.write_parquet(remove_path)
        print(f"  ✓ Saved removed POIs: {remove_path}")

        # Save summary
        summary = (
            to_remove
            .group_by("group_size")
            .agg((pl.len() / pl.first("group_size")).cast(pl.Int32).alias("num_groups"))
            .sort("group_size", descending=True)
        )
        summary_path = output_path / "duplicate_summary.csv"
        summary.write_csv(summary_path)
        print(f"  ✓ Saved summary: {summary_path}")

    # Create filtered dataset (remove duplicates)
    filtered = df.join(
        to_remove.select("row_id").with_columns(pl.lit(True).alias("remove")),
        on="row_id",
        how="left"
    ).filter(pl.col("remove").is_null()).drop("remove", "row_id", strict=False)

    print(f"POIs remaining after duplicate removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_business_change_pois(
    foursquare: pl.DataFrame,
    coord_precision: int = 5,
    enable_same_date_safeguard: bool = True,
    save_removed: bool = True,
    output_dir: str = "data/POI_files/business_changes_removed"
) -> pl.DataFrame:
    """
    Filter POIs where business changed but location wasn't properly refreshed.

    Detects locations where multiple POIs share:
    - Exact coordinates (within ~1m = 5 decimal places)
    - Same fsq_category_id
    - Different business names

    Keeps only the POI with most recent date_created from each group.

    SAFEGUARD: Groups where all POIs have same creation date are kept entirely
    (likely bulk imports of current state, e.g., outlet centers).

    Parameters:
    - foursquare: DataFrame with POI data
    - coord_precision: Decimal places for coordinate rounding (default: 5 for ~1m)
    - enable_same_date_safeguard: Protect bulk-imported groups (default: True)
    - save_removed: Whether to save removed POIs (default: True)
    - output_dir: Directory to save removed POI files

    Returns:
    - DataFrame with business change duplicates removed
    """
    print(f"Detecting business changes (exact category + location match)...")
    print(f"  Coordinate precision: {coord_precision} decimal places (~1m)")
    print(f"  Same-date safeguard: {'ENABLED' if enable_same_date_safeguard else 'DISABLED'}")

    initial_count = len(foursquare)
    df = foursquare

    # Add row_id if not present
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Round coordinates and normalize names
    df_with_location = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text_dup, return_dtype=str).alias("name_norm"),
    ])

    # Group by location + exact category
    keys = ["lat_round", "lng_round", "fsq_category_id"]

    location_groups = (
        df_with_location
        .group_by(keys)
        .agg([
            pl.count("name").alias("poi_count"),
            pl.n_unique("name_norm").alias("unique_names"),
            pl.col("row_id").alias("all_row_ids"),
        ])
        .filter(pl.col("poi_count") > 1)
        .filter(pl.col("unique_names") > 1)
    )

    if len(location_groups) == 0:
        print("  No business changes detected")
        return df.drop("row_id", strict=False)

    print(f"  Locations with business changes: {len(location_groups):,}")

    # Flatten to get all POIs in business change groups
    business_change_pois = (
        location_groups
        .explode("all_row_ids")
        .select(["lat_round", "lng_round", "fsq_category_id", "poi_count", "unique_names", "all_row_ids"])
        .rename({"all_row_ids": "row_id"})
    )

    # Join with original data
    business_changes_full = (
        business_change_pois
        .join(df, on="row_id", how="inner")
        .with_columns([
            pl.col("date_created").str.strptime(pl.Datetime, format="%Y-%m-%d", strict=False).alias("created_date"),
            pl.concat_str([
                pl.col("lat_round").cast(pl.Utf8), pl.lit("_"),
                pl.col("lng_round").cast(pl.Utf8), pl.lit("_"),
                pl.col("fsq_category_id").cast(pl.Utf8)
            ]).alias("group_key")
        ])
    )

    # Apply same-date safeguard
    if enable_same_date_safeguard:
        same_date_groups = (
            business_changes_full
            .group_by("group_key")
            .agg([pl.col("created_date").n_unique().alias("unique_dates"), pl.first("poi_count").alias("count")])
            .filter(pl.col("unique_dates") == 1)
        )

        if len(same_date_groups) > 0:
            print(f"  Same-date groups (keeping ALL): {len(same_date_groups):,} groups, {same_date_groups.select(pl.col('count').sum()).item():,} POIs")

        business_changes_full = business_changes_full.join(
            same_date_groups.select("group_key").with_columns(pl.lit(True).alias("is_same_date_group")),
            on="group_key", how="left"
        )

        groups_to_filter = business_changes_full.filter(pl.col("is_same_date_group").is_null())
    else:
        groups_to_filter = business_changes_full

    # Find most recent POI per group
    keep_ids = (
        groups_to_filter
        .sort(["group_key", "created_date"], descending=[False, True])
        .group_by("group_key")
        .agg(pl.first("row_id").alias("keep_row_id"))
    )

    # Mark keep/remove
    business_changes_final = (
        business_changes_full
        .join(keep_ids, on="group_key", how="left")
        .with_columns(
            ((pl.col("is_same_date_group").fill_null(False)) | (pl.col("row_id") == pl.col("keep_row_id"))).alias("keep")
            if enable_same_date_safeguard
            else (pl.col("row_id") == pl.col("keep_row_id")).alias("keep")
        )
    )

    to_remove = business_changes_final.filter(pl.col("keep") == False)

    print(f"  POIs to remove: {len(to_remove):,}")

    # Save removed POIs
    if save_removed and len(to_remove) > 0:
        import os
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/business_changes_removed.parquet"
        to_remove.select([
            "row_id", "fsq_place_id", "name", "lat", "lng", "fsq_category_id",
            "date_created", "date_refreshed", "group_key", "poi_count"
        ]).write_parquet(output_path)
        print(f"  Saved removed POIs: {output_path}")

    # Create filtered dataset
    filtered = df.join(
        to_remove.select("row_id").with_columns(pl.lit(True).alias("remove")),
        on="row_id", how="left"
    ).filter(pl.col("remove").is_null()).drop("remove", "row_id", strict=False)

    print(f"POIs remaining after business change removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_foreign_address_pois(
    foursquare: pl.DataFrame,
    save_removed: bool = True,
    output_dir: str = "data/POI_files/foreign_addresses_removed"
) -> pl.DataFrame:
    """
    Filter POIs with clearly non-UK addresses.

    Detection criteria:
    - Foreign state/province codes (US, CA, AU)
    - OR foreign country names
    - OR foreign postal code patterns (US, Canadian, Dutch, Irish)
    - OR 5-digit patterns + US address keywords (Suite, Highway, Road, etc.)
    - AND no UK postcode present (safeguard)
    - EXCEPT Northern Ireland and UK place names (safe pass)

    Parameters:
    - foursquare: DataFrame with POI data
    - save_removed: Whether to save removed POIs (default: True)
    - output_dir: Directory to save removed POI files

    Returns:
    - DataFrame with foreign addresses removed
    """
    print(f"Filtering foreign addresses...")

    initial_count = len(foursquare)

    # Foreign address patterns
    US_STATE_CODES = [
        "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY","LA",
        "MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY","OH","OK",
        "OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","DC"
    ]
    US_STATE_NAMES = [
        "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware",
        "Florida","Georgia","Hawaii","Iowa","Idaho","Illinois","Indiana","Kansas","Kentucky",
        "Louisiana","Massachusetts","Maryland","Maine","Michigan","Minnesota","Missouri","Mississippi",
        "Montana","North Carolina","North Dakota","Nebraska","New Hampshire","New Jersey","New Mexico",
        "Nevada","New York","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina",
        "South Dakota","Tennessee","Texas","Utah","Virginia","Vermont","Washington","Wisconsin",
        "West Virginia","District of Columbia"
    ]
    CA_PROV_CODES = ["AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"]
    CA_PROV_NAMES = [
        "Alberta","British Columbia","Manitoba","New Brunswick","Newfoundland and Labrador","Nova Scotia",
        "Northwest Territories","Nunavut","Ontario","Prince Edward Island","Quebec","Saskatchewan","Yukon"
    ]
    AU_STATE_CODES = ["NSW","VIC","QLD","SA","WA","TAS","ACT","NT"]
    AU_STATE_NAMES = [
        "New South Wales","Victoria","Queensland","South Australia","Western Australia","Tasmania",
        "Australian Capital Territory","Northern Territory"
    ]
    COUNTRY_WORDS = [
        r"United\s+States", r"U\.?S\.?A\.?", r"Canada", r"France", r"Germany", r"Deutschland",
        r"Spain", r"España", r"Italy", r"Italia", r"Australia", r"Ireland",
        r"Republic\s+of\s+Ireland", r"Netherlands", r"Nederland", r"Belgium", r"Belgique",
        r"Luxembourg", r"Switzerland", r"Suisse", r"Sweden", r"Norway", r"Denmark",
        r"Finland", r"Austria", r"Portugal", r"Poland", r"Czech", r"Hungary", r"Greece"
    ]

    # Postal code patterns
    PAT_US_ZIP_END = r"\d{5}(?:-\d{4})?$"
    PAT_CA_PC_END = r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d$"
    PAT_NL_PC_END = r"\d{4}\s?[A-Z]{2}$"
    PAT_IE_EIR_END = r"[A-Z]\d{2}\s?[A-Z0-9]{4}$"
    PAT_FIVE_DIGITS = r'\b\d{5}\b'
    PAT_US_ADDRESS_CONTEXT = r'(?i)\b(suite|highway|avenue|boulevard|drive|street|road|lane|court|circle|way|dr|rd|ave|blvd|st|ln|hwy)\b'

    # Build regex patterns
    PAT_US_STATE_TAIL = rf"(?:,?\s*)\b({'|'.join(US_STATE_CODES)})\b(?:\s*{PAT_US_ZIP_END})?$"
    PAT_US_STATE_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(US_STATE_NAMES)})\b(?:\s*{PAT_US_ZIP_END})?$"
    PAT_US_STATE_ABBR = rf"\b({'|'.join(US_STATE_CODES)})\b"
    PAT_CA_PROV_TAIL = rf"(?:,?\s*)\b({'|'.join(CA_PROV_CODES)})\b(?:\s*{PAT_CA_PC_END})?$"
    PAT_CA_PROV_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(CA_PROV_NAMES)})\b(?:\s*{PAT_CA_PC_END})?$"
    PAT_AU_STATE_TAIL = rf"(?:,?\s*)\b({'|'.join(AU_STATE_CODES)})\b(?:\s*\d{{4}})?$"
    PAT_AU_STATE_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(AU_STATE_NAMES)})\b(?:\s*\d{{4}})?$"
    PAT_COUNTRY_WORDS_REGEX = rf"(?i)\b({'|'.join(COUNTRY_WORDS)})\b"

    # Safe passes for UK place names
    SAFE_PASSES = [
        r"(?i)\bNorthern\s+Ireland\b",
        r"(?i)\bDenmark\s+Hill\b",
        r"(?i)\bDenmark\s+St(?:reet)?\b",
        r"(?i)\bCanada\s+Place\b",
        r"(?i)\bCanada\s+Water\b",
        r"(?i)\bNew\s+England\b",
    ]
    SAFE_PASS_PATTERN = "|".join(f"({p})" for p in SAFE_PASSES)

    # Build foreign indicator (only for POIs with addresses)
    has_address = pl.col("address").is_not_null()
    has_uk_postcode = pl.col("postcode").is_not_null()

    foreign_indicator = has_address & (
        pl.col("address").str.contains(PAT_COUNTRY_WORDS_REGEX, literal=False)
        | pl.col("address").str.contains(PAT_US_STATE_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_US_STATE_NAME_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_CA_PROV_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_CA_PROV_NAME_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_AU_STATE_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_AU_STATE_NAME_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_CA_PC_END, literal=False)
        | pl.col("address").str.contains(PAT_NL_PC_END, literal=False)
        | pl.col("address").str.contains(PAT_IE_EIR_END, literal=False)
        # Enhanced: 5-digit patterns with US address context
        | (
            pl.col("address").str.contains(PAT_FIVE_DIGITS, literal=False) &
            (
                pl.col("address").str.contains(PAT_US_ADDRESS_CONTEXT, literal=False) |
                pl.col("address").str.contains(PAT_US_STATE_ABBR, literal=False) |
                pl.col("address").str.contains(r'(?i)(USA|United States|America)', literal=False)
            )
        )
    ) & (~pl.col("address").str.contains(SAFE_PASS_PATTERN, literal=False))

    # Filter: foreign indicator AND no UK postcode
    to_remove = foursquare.filter(foreign_indicator & ~has_uk_postcode)

    if len(to_remove) == 0:
        print("  No foreign addresses detected")
        return foursquare

    print(f"  Foreign addresses detected: {len(to_remove):,}")

    # Save removed POIs
    if save_removed:
        import os
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/foreign_addresses_removed.parquet"
        to_remove.select([
            "fsq_place_id", "name", "address", "postcode", "lat", "lng", "fsq_category_labels"
        ]).write_parquet(output_path)
        print(f"  Saved removed POIs: {output_path}")

    # Create filtered dataset
    filtered = foursquare.filter(~(foreign_indicator & ~has_uk_postcode))

    print(f"POIs remaining after foreign address removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_postcode_mismatch_pois(
    foursquare: pl.DataFrame,
    onspd_dir: str = "data/input_files/onspd",
    distance_threshold_m: float = 1000.0,
    save_removed: bool = True,
    output_dir: str = "data/POI_files/postcode_mismatch_removed"
) -> pl.DataFrame:
    """
    Filter POIs where coordinates don't match postcode location.

    Uses ONS Postcode Directory (ONSPD) to look up official postcode coordinates
    and removes POIs where the distance exceeds the threshold.

    Detection criteria:
    - POI has a UK postcode
    - Look up postcode in ONSPD
    - Calculate distance between POI coords and postcode coords
    - Flag if distance exceeds threshold

    Parameters:
    - foursquare: DataFrame with POI data (must have lat, lng, postcode columns)
    - onspd_dir: Path to directory containing ONSPD CSV files
    - distance_threshold_m: Maximum allowed distance in meters (default: 1000m)
    - save_removed: Whether to save removed POIs (default: True)
    - output_dir: Directory to save removed POI files

    Returns:
    - DataFrame with postcode mismatches removed
    """
    import glob
    import numpy as np

    def haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate haversine distance between two points in meters."""
        R = 6371000
        lat1_rad = np.radians(lat1)
        lat2_rad = np.radians(lat2)
        delta_lat = np.radians(lat2 - lat1)
        delta_lon = np.radians(lon2 - lon1)
        a = np.sin(delta_lat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
        return R * c

    print(f"Filtering postcode mismatches (threshold: {distance_threshold_m}m)...")

    initial_count = len(foursquare)

    # Filter to POIs with postcodes
    has_postcode = foursquare.filter(pl.col("postcode").is_not_null())
    without_postcode = foursquare.filter(pl.col("postcode").is_null())

    print(f"  POIs with postcode: {len(has_postcode):,} ({100*len(has_postcode)/initial_count:.1f}%)")
    print(f"  POIs without postcode: {len(without_postcode):,} ({100*len(without_postcode)/initial_count:.1f}%)")

    if len(has_postcode) == 0:
        print("  No POIs with postcodes to check")
        return foursquare

    # Load ONSPD
    print(f"  Loading ONSPD from {onspd_dir}...")
    csv_files = glob.glob(f"{onspd_dir}/*.csv")

    if len(csv_files) == 0:
        print(f"  WARNING: No ONSPD files found in {onspd_dir}")
        print(f"  Skipping postcode mismatch filter")
        return foursquare

    dfs = []
    for csv_file in csv_files:
        df = pl.read_csv(
            csv_file,
            columns=["pcds", "lat", "long"],
            schema_overrides={"pcds": pl.Utf8, "lat": pl.Float64, "long": pl.Float64}
        )
        dfs.append(df)

    onspd = pl.concat(dfs)
    onspd = onspd.rename({"pcds": "postcode", "lat": "pc_latitude", "long": "pc_longitude"})
    onspd = onspd.filter(
        pl.col("postcode").is_not_null() &
        pl.col("pc_latitude").is_not_null() &
        pl.col("pc_longitude").is_not_null()
    )
    onspd = onspd.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ').alias("postcode")
    )

    print(f"  Loaded {len(onspd):,} postcodes")

    # Clean postcodes to match ONSPD format
    has_postcode = has_postcode.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ').alias("postcode_clean")
    )

    # Join with ONSPD
    print(f"  Looking up postcodes in ONSPD...")
    joined = has_postcode.join(
        onspd,
        left_on="postcode_clean",
        right_on="postcode",
        how="left"
    )

    # Filter out invalid/placeholder coordinates (99.999999, 0.0)
    valid_lookups = joined.filter(
        pl.col("pc_latitude").is_not_null() &
        (pl.col("pc_latitude") != 99.999999) &
        (pl.col("pc_longitude") != 0.0)
    )

    print(f"  Successfully looked up: {len(valid_lookups):,} ({100*len(valid_lookups)/len(has_postcode):.1f}%)")

    if len(valid_lookups) == 0:
        print("  No postcodes successfully looked up")
        return foursquare

    # Calculate distances
    print(f"  Calculating distances...")
    results_pd = valid_lookups.to_pandas()

    results_pd['distance_m'] = haversine_distance(
        results_pd['lat'].values,
        results_pd['lng'].values,
        results_pd['pc_latitude'].values,
        results_pd['pc_longitude'].values
    )

    # Convert back to polars
    results_df = pl.from_pandas(results_pd)

    # Find mismatches
    mismatches = results_df.filter(pl.col("distance_m") > distance_threshold_m)

    print(f"  Mismatches found: {len(mismatches):,} ({100*len(mismatches)/len(results_df):.2f}%)")

    # Save removed POIs
    if save_removed and len(mismatches) > 0:
        import os
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/postcode_mismatch_gt{int(distance_threshold_m)}m.parquet"
        mismatches.write_parquet(output_path)
        print(f"  Saved removed POIs: {output_path}")

        # Save CSV summary
        csv_path = f"{output_dir}/postcode_mismatch_gt{int(distance_threshold_m)}m.csv"
        mismatches.select([
            "fsq_place_id", "name", "lat", "lng", "postcode", "distance_m"
        ]).write_csv(csv_path)
        print(f"  Saved CSV summary: {csv_path}")

    # Create filtered dataset: keep POIs that passed the check + POIs without postcodes
    passed = results_df.filter(pl.col("distance_m") <= distance_threshold_m)

    # Drop the temporary columns
    passed = passed.drop(["postcode_clean", "pc_latitude", "pc_longitude", "distance_m"], strict=False)

    # Combine with POIs that weren't checked (no postcode or no lookup)
    not_checked = foursquare.filter(
        pl.col("postcode").is_null() |
        ~pl.col("fsq_place_id").is_in(results_df.select("fsq_place_id"))
    )

    filtered = pl.concat([passed, not_checked])

    print(f"POIs remaining after postcode mismatch removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_foursquare_quality(
    foursquare: pl.DataFrame,
    boundary_path: str = "data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
    buffer_m: int = 50,
    save_outside: bool = False,
    filter_defunct: bool = True,
    defunct_csv_path: str = "data/input_files/defunct_uk_retailers_wikipedia_full.csv",
    save_defunct_removed: bool = True,
    filter_duplicates: bool = True,
    duplicate_name_threshold: float = 0.6,
    duplicate_dist_thresh: float = 15.0,
    save_duplicates_removed: bool = True,
    filter_business_changes: bool = True,
    business_change_same_date_safeguard: bool = True,
    save_business_changes_removed: bool = True,
    filter_foreign_addresses: bool = True,
    save_foreign_addresses_removed: bool = True,
    filter_postcode_mismatch: bool = True,
    postcode_mismatch_threshold_m: float = 1000.0,
    onspd_dir: str = "data/input_files/onspd",
    save_postcode_mismatch_removed: bool = True
) -> pl.DataFrame:
    """
    Apply quality filters to the Foursquare DataFrame to remove low-quality entries.

    Currently applies:
    1. Defunct retailers filter: Removes POIs matching defunct UK retailers
    2. UK boundary filter: Removes POIs outside the UK boundary (+ buffer)
    3. Duplicate POI filter: Removes duplicate POIs (keeps most recent from each group)
    4. Business change filter: Removes old POIs where business changed at same location
    5. Foreign address filter: Removes POIs with clearly non-UK addresses
    6. Postcode mismatch filter: Removes POIs where coordinates don't match postcode location

    Parameters:
    - foursquare: polars.DataFrame containing Foursquare POI data with 'lat', 'lng', 'name' columns
    - boundary_path: Path to UK boundary geopackage file
    - buffer_m: Buffer distance in meters to extend boundary (default: 50m)
    - save_outside: Whether to save POIs outside the boundary for inspection (default: False)
    - filter_defunct: Whether to apply defunct retailers filter (default: True)
    - defunct_csv_path: Path to defunct retailers CSV file
    - save_defunct_removed: Whether to save removed defunct POIs and statistics (default: True)
    - filter_duplicates: Whether to apply duplicate POI filter (default: True)
    - duplicate_name_threshold: Name similarity threshold for duplicates (default: 0.6)
    - duplicate_dist_thresh: Distance threshold in meters for duplicates (default: 15m)
    - save_duplicates_removed: Whether to save removed duplicate POIs (default: True)
    - filter_business_changes: Whether to apply business change filter (default: True)
    - business_change_same_date_safeguard: Protect bulk-imported outlet centers (default: True)
    - save_business_changes_removed: Whether to save removed business change POIs (default: True)
    - filter_foreign_addresses: Whether to apply foreign address filter (default: True)
    - save_foreign_addresses_removed: Whether to save removed foreign addresses (default: True)
    - filter_postcode_mismatch: Whether to apply postcode mismatch filter (default: True)
    - postcode_mismatch_threshold_m: Distance threshold in meters for postcode mismatch (default: 1000m)
    - onspd_dir: Path to directory containing ONSPD CSV files
    - save_postcode_mismatch_removed: Whether to save removed postcode mismatches (default: True)

    Returns:
    - polars.DataFrame after applying quality filters.
    """

    print("\n" + "="*60)
    print("=== Applying Quality Filters ===")
    print("="*60)
    print(f"Starting POIs: {len(foursquare):,}")

    foursquare_filt = foursquare

    # Filter for open locations (remove closed venues)
    print("\n0. Filtering closed venues...")
    print("-" * 60)
    initial_count = len(foursquare_filt)
    foursquare_filt = foursquare_filt.filter(pl.col("date_closed").is_null())
    closed_count = initial_count - len(foursquare_filt)
    print(f"Removed {closed_count:,} closed venues")
    print(f"Remaining: {len(foursquare_filt):,} POIs")

    # Apply defunct retailers filter
    if filter_defunct:
        print("\n1. Filtering defunct retailers...")
        print("-" * 60)
        foursquare_filt = filter_defunct_retailers(
            foursquare_filt,
            defunct_csv_path=defunct_csv_path,
            save_removed=save_defunct_removed,
            output_dir="data/POI_files/defunct_removed",
            top_n_brands=10
        )

    # Apply UK boundary filter
    print("\n2. Filtering by UK boundary...")
    print("-" * 60)
    foursquare_filt = filter_by_uk_boundary(
        foursquare_filt,
        boundary_path=boundary_path,
        buffer_m=buffer_m,
        save_outside=save_outside
    )

    # Apply duplicate POI filter
    if filter_duplicates:
        print("\n3. Filtering duplicate POIs...")
        print("-" * 60)
        foursquare_filt = filter_duplicate_pois(
            foursquare_filt,
            name_threshold=duplicate_name_threshold,
            dist_thresh=duplicate_dist_thresh,
            save_removed=save_duplicates_removed,
            output_dir="data/POI_files/duplicates_removed"
        )

    # Apply business change filter
    if filter_business_changes:
        print("\n4. Filtering business changes...")
        print("-" * 60)
        foursquare_filt = filter_business_change_pois(
            foursquare_filt,
            coord_precision=5,
            enable_same_date_safeguard=business_change_same_date_safeguard,
            save_removed=save_business_changes_removed,
            output_dir="data/POI_files/business_changes_removed"
        )

    # Apply foreign address filter
    if filter_foreign_addresses:
        print("\n5. Filtering foreign addresses...")
        print("-" * 60)
        foursquare_filt = filter_foreign_address_pois(
            foursquare_filt,
            save_removed=save_foreign_addresses_removed,
            output_dir="data/POI_files/foreign_addresses_removed"
        )

    # Apply postcode mismatch filter
    if filter_postcode_mismatch:
        print("\n6. Filtering postcode mismatches...")
        print("-" * 60)
        foursquare_filt = filter_postcode_mismatch_pois(
            foursquare_filt,
            onspd_dir=onspd_dir,
            distance_threshold_m=postcode_mismatch_threshold_m,
            save_removed=save_postcode_mismatch_removed,
            output_dir="data/POI_files/postcode_mismatch_removed"
        )

    print("\n" + "="*60)
    print("=== Quality Filtering Complete ===")
    print("="*60)
    print(f"POIs removed: {len(foursquare) - len(foursquare_filt):,}")
    print(f"POIs remaining: {len(foursquare_filt):,}")
    print(f"Removal rate: {100 * (len(foursquare) - len(foursquare_filt)) / len(foursquare):.2f}%")

    return foursquare_filt