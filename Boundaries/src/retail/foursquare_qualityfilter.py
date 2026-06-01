import re
import math
import polars as pl
import geopandas as gpd
from pathlib import Path
from typing import Optional
import networkx as nx
import h3
import gc
import glob
import os

import config


# =============================================================================
# UTILITY FUNCTIONS (Private Helpers)
# =============================================================================

# --- Text Normalization ---

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
    result = result.str.replace_all("['']", "", literal=False)

    # Remove hyphens (Kwik-Save → kwiksave, but keep spaces)
    result = result.str.replace_all("-", "", literal=False)

    # Collapse multiple spaces to single space
    result = result.str.replace_all(r'\s+', ' ', literal=False)

    # Final strip
    result = result.str.strip_chars()

    return result


# --- String Matching ---

def _levenshtein(a: str, b: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
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


# --- Geographic Utils ---

def _haversine_distance_polars(lat1_col: str, lon1_col: str, lat2_col: str, lon2_col: str) -> pl.Expr:
    """
    Calculate haversine distance in meters using Polars expressions.

    Vectorized implementation for efficient distance calculation between lat/lng coordinates.

    Parameters:
    - lat1_col: Name of column containing first latitude
    - lon1_col: Name of column containing first longitude
    - lat2_col: Name of column containing second latitude
    - lon2_col: Name of column containing second longitude

    Returns:
    - Polars expression computing distance in meters
    """
    R = 6371000  # Earth radius in meters

    lat1_rad = pl.col(lat1_col) * (math.pi / 180)
    lat2_rad = pl.col(lat2_col) * (math.pi / 180)
    delta_lat = (pl.col(lat2_col) - pl.col(lat1_col)) * (math.pi / 180)
    delta_lon = (pl.col(lon2_col) - pl.col(lon1_col)) * (math.pi / 180)

    a = (
        (delta_lat / 2).sin().pow(2) +
        lat1_rad.cos() * lat2_rad.cos() * (delta_lon / 2).sin().pow(2)
    )

    c = 2 * pl.arctan2(a.sqrt(), (1 - a).sqrt())

    return R * c


# --- Data Loading ---

def _load_onspd_batched(onspd_dir: str, batch_size: int = 20) -> pl.DataFrame:
    """
    Load ONSPD in batches to reduce memory spikes.

    Parameters:
    - onspd_dir: Directory containing ONSPD CSV files
    - batch_size: Number of CSV files to load at once

    Returns:
    - Polars DataFrame with postcodes
    """
    csv_files = glob.glob(f"{onspd_dir}/*.csv")

    if len(csv_files) == 0:
        raise FileNotFoundError(f"No ONSPD files found in {onspd_dir}")

    print(f"  Loading {len(csv_files)} ONSPD files in batches of {batch_size}...")

    all_dfs = []

    for i in range(0, len(csv_files), batch_size):
        batch_files = csv_files[i:i + batch_size]

        batch_dfs = []
        for csv_file in batch_files:
            df = pl.read_csv(
                csv_file,
                columns=["pcds", "lat", "long"],
                schema_overrides={"pcds": pl.Utf8, "lat": pl.Float64, "long": pl.Float64}
            )
            batch_dfs.append(df)

        # Concatenate this batch
        batch_df = pl.concat(batch_dfs)
        all_dfs.append(batch_df)

        # Clean up batch
        del batch_dfs
        gc.collect()

        print(f"    Loaded {min(i + batch_size, len(csv_files))}/{len(csv_files)} files...")

    # Concatenate all batches
    print("  Combining batches...")
    onspd = pl.concat(all_dfs)

    # Clean up
    del all_dfs
    gc.collect()

    # Process ONSPD
    onspd = onspd.rename({"pcds": "postcode", "lat": "pc_latitude", "long": "pc_longitude"})

    # Filter and normalize
    onspd = onspd.filter(
        pl.col("postcode").is_not_null() &
        pl.col("pc_latitude").is_not_null() &
        pl.col("pc_longitude").is_not_null()
    )

    onspd = onspd.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ')
    )

    # Remove duplicates to reduce memory
    onspd = onspd.unique(subset=["postcode"])

    print(f"  Loaded {len(onspd):,} unique postcodes")

    return onspd


# =============================================================================
# FILTER FUNCTIONS
# =============================================================================

def filter_postcode_mismatch_pois(
    foursquare: pl.DataFrame,
    onspd_dir: str = "data/inputs/onspd",
    distance_threshold_m: float = 1000.0,
    batch_size: int = 100000,
    save_removed: bool = True,
    output_dir: str = "data/intermediate/postcode_mismatch_removed"
) -> pl.DataFrame:
    """
    Memory-optimized postcode mismatch filter.

    Processes POIs in batches to avoid memory issues.

    Parameters:
    - foursquare: DataFrame with POI data
    - onspd_dir: Path to ONSPD directory
    - distance_threshold_m: Distance threshold in meters
    - batch_size: Number of POIs to process at once (default: 100k)
    - save_removed: Whether to save removed POIs
    - output_dir: Output directory

    Returns:
    - Filtered DataFrame
    """
    print(f"Filtering postcode mismatches (threshold: {distance_threshold_m}m, low-memory mode)...")

    initial_count = len(foursquare)

    # Separate POIs with/without postcodes
    has_postcode = foursquare.filter(pl.col("postcode").is_not_null())
    without_postcode = foursquare.filter(pl.col("postcode").is_null())

    print(f"  POIs with postcode: {len(has_postcode):,} ({100*len(has_postcode)/initial_count:.1f}%)")
    print(f"  POIs without postcode: {len(without_postcode):,} ({100*len(without_postcode)/initial_count:.1f}%)")

    if len(has_postcode) == 0:
        print("  No POIs with postcodes to check")
        return foursquare

    # Load ONSPD (batched)
    print(f"  Loading ONSPD from {onspd_dir}...")
    try:
        onspd = _load_onspd_batched(onspd_dir, batch_size=20)
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"ONSPD files not found in {onspd_dir}. "
            f"Postcode mismatch filtering requires ONSPD data. "
            f"Please download ONSPD data and place CSV files in {onspd_dir}/"
        ) from e

    # Clean postcodes
    has_postcode = has_postcode.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ').alias("postcode_clean")
    )

    # Process in batches to reduce memory
    print(f"  Processing POIs in batches of {batch_size:,}...")

    num_batches = (len(has_postcode) + batch_size - 1) // batch_size

    all_passed = []
    all_mismatches = []

    for batch_idx in range(num_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, len(has_postcode))

        batch = has_postcode[start_idx:end_idx]

        # Join with ONSPD
        joined = batch.join(
            onspd,
            left_on="postcode_clean",
            right_on="postcode",
            how="left"
        )

        # Filter valid lookups
        valid = joined.filter(
            pl.col("pc_latitude").is_not_null() &
            (pl.col("pc_latitude") != 99.999999) &
            (pl.col("pc_longitude") != 0.0)
        )

        if len(valid) == 0:
            continue

        # Calculate distances using Polars (no Pandas!)
        valid = valid.with_columns(
            _haversine_distance_polars("lat", "lng", "pc_latitude", "pc_longitude").alias("distance_m")
        )

        # Split into passed/mismatches
        batch_mismatches = valid.filter(pl.col("distance_m") > distance_threshold_m)
        batch_passed = valid.filter(pl.col("distance_m") <= distance_threshold_m)

        # Drop temp columns from passed
        batch_passed = batch_passed.drop(["postcode_clean", "pc_latitude", "pc_longitude", "distance_m"], strict=False)

        all_passed.append(batch_passed)
        if len(batch_mismatches) > 0:
            all_mismatches.append(batch_mismatches)

        # Clean up
        del joined, valid, batch_passed, batch_mismatches, batch
        gc.collect()

        if (batch_idx + 1) % 5 == 0 or batch_idx == num_batches - 1:
            print(f"    Processed {min(end_idx, len(has_postcode)):,}/{len(has_postcode):,} POIs...")

    # Clean up ONSPD
    del onspd
    gc.collect()

    # Combine results
    print("  Combining results...")

    if len(all_passed) > 0:
        passed = pl.concat(all_passed)
        del all_passed
        gc.collect()
    else:
        passed = pl.DataFrame()

    if len(all_mismatches) > 0:
        mismatches = pl.concat(all_mismatches)
        del all_mismatches
        gc.collect()
    else:
        mismatches = pl.DataFrame()

    print(f"  Mismatches found: {len(mismatches):,} ({100*len(mismatches)/len(has_postcode) if len(has_postcode) > 0 else 0:.2f}%)")

    # Save mismatches
    if save_removed and len(mismatches) > 0:
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/postcode_mismatch_gt{int(distance_threshold_m)}m.parquet"
        mismatches.write_parquet(output_path)
        print(f"  Saved removed POIs: {output_path}")

        # Save CSV (select columns only)
        csv_path = f"{output_dir}/postcode_mismatch_gt{int(distance_threshold_m)}m.csv"
        mismatches.select([
            "fsq_place_id", "name", "lat", "lng", "postcode", "distance_m"
        ]).write_csv(csv_path)
        print(f"  Saved CSV: {csv_path}")

    # Combine passed + without_postcode
    if len(passed) > 0:
        filtered = pl.concat([passed, without_postcode])
    else:
        filtered = without_postcode

    # Clean up
    del passed, without_postcode, mismatches
    gc.collect()

    print(f"POIs remaining after postcode mismatch removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_defunct_retailers(
    foursquare: pl.DataFrame,
    defunct_csv_path: str = None,
    save_removed: bool = True,
    output_dir: str = "data/intermediate/defunct_removed",
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
    - output_dir: Directory to save removed POI files (default: "data/intermediate/defunct_removed")
    - top_n_brands: Number of top brands to save as separate GeoParquet files (default: 10)
    - save_all_removed: Whether to save complete file with ALL removed POIs (default: True)

    Returns:
    - polars.DataFrame with defunct retailers removed
    """

    # Use config path if none provided
    if defunct_csv_path is None:
        defunct_csv_path = str(config.DEFUNCT_RETAILERS_PATH)

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
    boundary_path: str = "../data/inputs/boundaries/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
    buffer_m: int = 50,
    batch_size: int = 200000,
    save_outside: bool = False,
    output_path: Optional[str] = None
) -> pl.DataFrame:
    """
    Filter Foursquare POIs to keep only those within the UK boundary (batched for low memory).

    Parameters:
    - foursquare: polars.DataFrame containing Foursquare POI data with 'lat' and 'lng' columns
    - boundary_path: Path to UK boundary geopackage file
    - buffer_m: Buffer distance in meters to extend boundary (default: 50m)
    - batch_size: Number of POIs to process at once (default: 200k, reduce if out of memory)
    - save_outside: Whether to save POIs outside the boundary for inspection (default: False)
    - output_path: Path to save outside POIs if save_outside=True

    Returns:
    - polars.DataFrame containing only POIs within the buffered UK boundary
    """
    total_pois = len(foursquare)

    # Load UK boundary once (outside loop)
    print("  Loading UK boundary...")
    uk_boundary = gpd.read_file(boundary_path).to_crs(epsg=27700)
    uk_boundary = uk_boundary.dissolve()
    uk_boundary["geometry"] = uk_boundary.buffer(buffer_m)

    # Process in batches
    print(f"  Processing {total_pois:,} POIs in batches of {batch_size:,}...")

    num_batches = (total_pois + batch_size - 1) // batch_size
    all_inside = []
    all_outside = []
    expected_schema = None  # Store schema from first batch

    for batch_idx in range(num_batches):
        start_idx = batch_idx * batch_size
        end_idx = min(start_idx + batch_size, total_pois)

        batch = foursquare[start_idx:end_idx]

        # Convert batch to GeoDataFrame
        pdf = batch.to_pandas()
        batch_gdf = gpd.GeoDataFrame(
            pdf,
            geometry=gpd.points_from_xy(pdf["lng"], pdf["lat"]),
            crs="EPSG:4326"
        ).to_crs(epsg=27700)

        # Spatial join
        joined = gpd.sjoin(batch_gdf, uk_boundary, how="left", predicate="within")

        # Split inside/outside
        batch_inside = joined[joined.index_right.notna()].drop(columns=["index_right", "geometry"], errors="ignore")
        batch_outside = joined[joined.index_right.isna()].drop(columns=["index_right", "geometry"], errors="ignore")

        # Convert back to Polars with schema consistency
        if len(batch_inside) > 0:
            batch_inside_pl = pl.from_pandas(batch_inside)
            if expected_schema is None:
                expected_schema = batch_inside_pl.schema
            else:
                # Cast to expected schema to ensure consistency
                batch_inside_pl = batch_inside_pl.cast(expected_schema)
            all_inside.append(batch_inside_pl)

        if len(batch_outside) > 0:
            batch_outside_pl = pl.from_pandas(batch_outside)
            if expected_schema is not None:
                # Cast to expected schema to ensure consistency
                batch_outside_pl = batch_outside_pl.cast(expected_schema)
            all_outside.append(batch_outside_pl)

        # Cleanup
        del batch, pdf, batch_gdf, joined, batch_inside, batch_outside
        gc.collect()

        if (batch_idx + 1) % 3 == 0 or batch_idx == num_batches - 1:
            print(f"    Processed {end_idx:,}/{total_pois:,} POIs...")

    # Combine results
    inside_uk = pl.concat(all_inside) if all_inside else pl.DataFrame()
    outside_uk = pl.concat(all_outside) if all_outside else pl.DataFrame()

    print(f"Total POIs: {total_pois:,}")
    print(f"Outside UK boundary ({buffer_m}m buffer): {len(outside_uk):,}")
    print(f"Inside UK boundary: {len(inside_uk):,}")

    # Save outside POIs
    if save_outside and len(outside_uk) > 0:
        if output_path is None:
            output_path = "../data/intermediate/foursquare_outside_uk.parquet"
        outside_uk.write_parquet(output_path)
        print(f"Outside POIs saved to: {output_path}")

    return inside_uk


def filter_duplicate_pois(
    foursquare: pl.DataFrame,
    name_threshold: float = 0.6,
    dist_thresh: float = 15.0,
    save_removed: bool = True,
    output_dir: str = "data/intermediate/duplicates_removed"
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
    - output_dir: Directory to save removed POI files (default: "data/intermediate/duplicates_removed")

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
            _haversine_distance_polars("lat", "lng", "lat_r", "lng_r").alias("dist_m"),
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
        return df

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

    # For each group, find most recent (row_id for deterministic tiebreak)
    keep_ids = (
        duplicates_with_groups
        .sort(["group_id", "refresh_date", "row_id"], descending=[False, True, False])
        .group_by("group_id")
        .agg(pl.first("row_id").alias("keep_row_id"))
    )

    # Mark which to keep/remove
    duplicates_final = (
        duplicates_with_groups
        .join(keep_ids, on="group_id", how="left")
        .with_columns((pl.col("row_id") == pl.col("keep_row_id")).alias("keep"))
    )

    to_remove = duplicates_final.filter(~pl.col("keep"))
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
    ).filter(pl.col("remove").is_null()).drop("remove", strict=False)

    print(f"POIs remaining after duplicate removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_business_change_pois(
    foursquare: pl.DataFrame,
    coord_precision: int = 5,
    enable_same_date_safeguard: bool = True,
    save_removed: bool = True,
    output_dir: str = "data/intermediate/business_changes_removed"
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
    print("Detecting business changes (exact category + location match)...")
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
        return df

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

    # Find most recent POI per group (row_id for deterministic tiebreak)
    keep_ids = (
        groups_to_filter
        .sort(["group_key", "created_date", "row_id"], descending=[False, True, False])
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

    to_remove = business_changes_final.filter(~pl.col("keep"))

    print(f"  POIs to remove: {len(to_remove):,}")

    # Save removed POIs
    if save_removed and len(to_remove) > 0:
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
    ).filter(pl.col("remove").is_null()).drop("remove", strict=False)

    print(f"POIs remaining after business change removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


def filter_foreign_address_pois(
    foursquare: pl.DataFrame,
    save_removed: bool = True,
    output_dir: str = "data/intermediate/foreign_addresses_removed"
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
    print("Filtering foreign addresses...")

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


# =============================================================================
# REGISTERED OFFICE POSTCODES FILTER
# =============================================================================

# Postcodes known to be business registration addresses (virtual offices, company
# formation agents) rather than physical retail locations. These have high Foursquare
# POI counts but low/no LDC presence.
REGISTERED_OFFICE_POSTCODES = {
    "EC1V2NX",  # Old Street area - company formation services
    "N17GU",    # King's Cross - virtual office providers
    "EC2A4NE",  # Shoreditch - registered office services
    "G24JR",    # Glasgow - business registration address
}


def filter_registered_office_postcodes(
    foursquare: pl.DataFrame,
    save_removed: bool = True,
    output_dir: str = "data/intermediate/registered_offices_removed"
) -> pl.DataFrame:
    """
    Filter POIs at postcodes known to be business registration addresses.

    These postcodes have high Foursquare POI counts but low/no LDC presence because
    businesses are registered there (virtual offices, company formation agents) rather
    than having a physical retail presence.

    Parameters:
    - foursquare: polars.DataFrame with POI data (must have 'postcode' column)
    - save_removed: Whether to save removed POIs (default: True)
    - output_dir: Directory to save removed POI files

    Returns:
    - polars.DataFrame with registered office POIs removed
    """
    print("Filtering registered office postcodes...")

    initial_count = len(foursquare)

    postcodes_to_remove = REGISTERED_OFFICE_POSTCODES

    print(f"  Postcodes to filter: {sorted(postcodes_to_remove)}")

    # Normalise postcodes for matching (remove spaces, uppercase)
    foursquare = foursquare.with_columns(
        pl.col("postcode")
        .str.replace_all(r"\s+", "")
        .str.to_uppercase()
        .alias("_pc_norm")
    )

    # Identify POIs to remove
    to_remove = foursquare.filter(pl.col("_pc_norm").is_in(postcodes_to_remove))

    if len(to_remove) == 0:
        print("  No registered office POIs detected")
        return foursquare.drop("_pc_norm")

    print(f"  Registered office POIs detected: {len(to_remove):,}")

    # Show breakdown by postcode
    breakdown = to_remove.group_by("_pc_norm").agg(pl.count().alias("count")).sort("count", descending=True)
    for row in breakdown.iter_rows(named=True):
        print(f"    {row['_pc_norm']}: {row['count']:,}")

    # Save removed POIs
    if save_removed:
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}/registered_offices_removed.parquet"
        to_remove.drop("_pc_norm").write_parquet(output_path)
        print(f"  Saved removed POIs: {output_path}")

    # Create filtered dataset (keep nulls - only remove matching postcodes)
    filtered = foursquare.filter(
        pl.col("_pc_norm").is_null() | ~pl.col("_pc_norm").is_in(postcodes_to_remove)
    ).drop("_pc_norm")

    print(f"POIs remaining after registered office removal: {len(filtered):,}")
    print(f"Removed: {initial_count - len(filtered):,} ({100 * (initial_count - len(filtered)) / initial_count:.3f}%)")

    return filtered


# =============================================================================
# ORCHESTRATOR/LOADER FUNCTIONS
# =============================================================================

def load_and_apply_presaved_filters(
    foursquare: pl.DataFrame,
    filter_ids_path: str = "data/intermediate/poi_filtered/quality_filter_ids.parquet"
) -> pl.DataFrame:
    """
    Apply presaved quality filter results by removing POIs based on saved IDs.

    This is a fast alternative to running all quality filters from scratch.
    Use this when you've already run filter_foursquare_quality with save_filter_ids=True.

    Parameters:
    - foursquare: polars.DataFrame containing Foursquare POI data with 'fsq_place_id' column
    - filter_ids_path: Path to the parquet file containing filter results

    Returns:
    - polars.DataFrame with quality-filtered POIs (POIs from filter_ids removed)
    """
    print("\n" + "="*60)
    print("=== Applying Presaved Quality Filters ===")
    print("="*60)

    if not Path(filter_ids_path).exists():
        raise FileNotFoundError(
            f"Filter IDs file not found: {filter_ids_path}\n"
            f"Run filter_foursquare_quality with save_filter_ids=True first."
        )

    print(f"Loading filter IDs from: {filter_ids_path}")
    removed_ids = pl.read_parquet(filter_ids_path)

    # Show breakdown
    print("\nFilter breakdown:")
    breakdown = removed_ids.group_by("filter_type").agg(pl.len().alias("count"))
    for row in breakdown.iter_rows(named=True):
        print(f"  - {row['filter_type']}: {row['count']:,}")

    total_to_remove = len(removed_ids.select("row_id").unique())
    print(f"\nTotal rows to remove: {total_to_remove:,}")

    # Add the same row_id used when the filter IDs were saved (input row position).
    if "row_id" in foursquare.columns:
        foursquare = foursquare.drop("row_id")
    foursquare = foursquare.with_row_index("row_id")

    initial_count = len(foursquare)

    # Remove rows using row_id anti-join (preserves intra-POI dedup decisions
    # that an fsq_place_id-only anti-join would miss).
    filtered = foursquare.join(
        removed_ids.select("row_id").unique(),
        on="row_id",
        how="anti"
    ).drop("row_id")

    print(f"\nStarting POIs: {initial_count:,}")
    print(f"POIs removed: {initial_count - len(filtered):,}")
    print(f"POIs remaining: {len(filtered):,}")
    print(f"Removal rate: {100 * (initial_count - len(filtered)) / initial_count:.2f}%")

    print("="*60)

    return filtered


def filter_foursquare_quality(
    foursquare: pl.DataFrame,
    boundary_path: str = "data/inputs/boundaries/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
    buffer_m: int = 50,
    save_outside: bool = False,
    filter_defunct: bool = True,
    defunct_csv_path: str = None,
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
    postcode_mismatch_batch_size: int = 100000,
    onspd_dir: str = "data/inputs/onspd",
    save_postcode_mismatch_removed: bool = True,
    filter_registered_offices: bool = True,
    save_registered_offices_removed: bool = True,
    save_filter_ids: bool = False,
    filter_ids_path: str = "data/intermediate/poi_filtered/quality_filter_ids.parquet"
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
    - postcode_mismatch_batch_size: Number of POIs to process at once (default: 100k, reduce if out of memory)
    - onspd_dir: Path to directory containing ONSPD CSV files
    - save_postcode_mismatch_removed: Whether to save removed postcode mismatches (default: True)
    - filter_registered_offices: Whether to apply registered office postcode filter (default: True)
    - save_registered_offices_removed: Whether to save removed registered office POIs (default: True)
    - save_filter_ids: Whether to save POI IDs removed by each filter for reuse (default: False)
    - filter_ids_path: Path to save filter IDs parquet file (default: "data/intermediate/poi_filtered/quality_filter_ids.parquet")

    Returns:
    - polars.DataFrame after applying quality filters.
    """

    print("\n" + "="*60)
    print("=== Applying Quality Filters ===")
    print("="*60)
    print(f"Starting POIs: {len(foursquare):,}")

    # Add a stable row_id (input row position) so filter tracking is row-level,
    # not just fsq_place_id-level. The duplicate filter removes individual rows
    # of POIs that may have multiple entries; saving only fsq_place_id loses
    # that information and makes --use_presaved_filters diverge from the
    # from-scratch run. Dropped before returning.
    if "row_id" in foursquare.columns:
        foursquare = foursquare.drop("row_id")
    foursquare = foursquare.with_row_index("row_id")
    foursquare_filt = foursquare

    # Track removed row_ids if saving is enabled
    removed_ids_by_filter = {}

    # Ensure fsq_place_id exists for tracking
    if "fsq_place_id" not in foursquare.columns:
        print("Warning: fsq_place_id column not found. Cannot save filter IDs.")
        save_filter_ids = False

    # Filter for open locations (remove closed venues)
    print("\n0. Filtering closed venues...")
    print("-" * 60)
    initial_count = len(foursquare_filt)
    if save_filter_ids:
        closed_venues = foursquare_filt.filter(pl.col("date_closed").is_not_null())
        removed_ids_by_filter["closed"] = closed_venues.select(["row_id", "fsq_place_id"])
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
            output_dir="data/intermediate/defunct_removed",
            top_n_brands=10
        )
        if save_filter_ids:
            removed_defunct = foursquare.filter(
                ~pl.col("row_id").is_in(foursquare_filt.get_column("row_id"))
            ).select(["row_id", "fsq_place_id"])
            if len(removed_defunct) > 0:
                removed_ids_by_filter["defunct"] = removed_defunct

    # Apply UK boundary filter
    print("\n2. Filtering by UK boundary...")
    print("-" * 60)
    pre_filter_ids = foursquare_filt.select(["row_id", "fsq_place_id"]) if save_filter_ids else None
    foursquare_filt = filter_by_uk_boundary(
        foursquare_filt,
        boundary_path=boundary_path,
        buffer_m=buffer_m,
        save_outside=save_outside
    )
    if save_filter_ids:
        removed_outside_uk = pre_filter_ids.join(
            foursquare_filt.select("row_id"),
            on="row_id",
            how="anti"
        )
        if len(removed_outside_uk) > 0:
            removed_ids_by_filter["outside_uk"] = removed_outside_uk

    # Apply foreign address filter
    if filter_foreign_addresses:
        print("\n3. Filtering foreign addresses...")
        print("-" * 60)
        pre_filter_ids = foursquare_filt.select(["row_id", "fsq_place_id"]) if save_filter_ids else None
        foursquare_filt = filter_foreign_address_pois(
            foursquare_filt,
            save_removed=save_foreign_addresses_removed,
            output_dir="data/intermediate/foreign_addresses_removed"
        )
        if save_filter_ids:
            removed_foreign = pre_filter_ids.join(
                foursquare_filt.select("row_id"),
                on="row_id",
                how="anti"
            )
            if len(removed_foreign) > 0:
                removed_ids_by_filter["foreign_addresses"] = removed_foreign

    # Apply postcode mismatch filter
    if filter_postcode_mismatch:
        print("\n4. Filtering postcode mismatches...")
        print("-" * 60)
        pre_filter_ids = foursquare_filt.select(["row_id", "fsq_place_id"]) if save_filter_ids else None
        foursquare_filt = filter_postcode_mismatch_pois(
            foursquare_filt,
            onspd_dir=onspd_dir,
            distance_threshold_m=postcode_mismatch_threshold_m,
            batch_size=postcode_mismatch_batch_size,
            save_removed=save_postcode_mismatch_removed,
            output_dir="data/intermediate/postcode_mismatch_removed"
        )
        if save_filter_ids:
            removed_postcode = pre_filter_ids.join(
                foursquare_filt.select("row_id"),
                on="row_id",
                how="anti"
            )
            if len(removed_postcode) > 0:
                removed_ids_by_filter["postcode_mismatch"] = removed_postcode

    # Apply duplicate POI filter
    if filter_duplicates:
        print("\n5. Filtering duplicate POIs...")
        print("-" * 60)
        pre_filter_ids = foursquare_filt.select(["row_id", "fsq_place_id"]) if save_filter_ids else None
        foursquare_filt = filter_duplicate_pois(
            foursquare_filt,
            name_threshold=duplicate_name_threshold,
            dist_thresh=duplicate_dist_thresh,
            save_removed=save_duplicates_removed,
            output_dir="data/intermediate/duplicates_removed"
        )
        if save_filter_ids:
            removed_duplicates = pre_filter_ids.join(
                foursquare_filt.select("row_id"),
                on="row_id",
                how="anti"
            )
            if len(removed_duplicates) > 0:
                removed_ids_by_filter["duplicates"] = removed_duplicates

    # Apply business change filter (after duplicates to minimize cascade)
    if filter_business_changes:
        print("\n6. Filtering business changes...")
        print("-" * 60)
        pre_filter_ids = foursquare_filt.select(["row_id", "fsq_place_id"]) if save_filter_ids else None
        foursquare_filt = filter_business_change_pois(
            foursquare_filt,
            coord_precision=5,
            enable_same_date_safeguard=business_change_same_date_safeguard,
            save_removed=save_business_changes_removed,
            output_dir="data/intermediate/business_changes_removed"
        )
        if save_filter_ids:
            removed_business_changes = pre_filter_ids.join(
                foursquare_filt.select("row_id"),
                on="row_id",
                how="anti"
            )
            if len(removed_business_changes) > 0:
                removed_ids_by_filter["business_changes"] = removed_business_changes

    # Apply registered office postcode filter
    if filter_registered_offices:
        print("\n7. Filtering registered office postcodes...")
        print("-" * 60)
        pre_filter_ids = foursquare_filt.select(["row_id", "fsq_place_id"]) if save_filter_ids else None
        foursquare_filt = filter_registered_office_postcodes(
            foursquare_filt,
            save_removed=save_registered_offices_removed,
            output_dir="data/intermediate/registered_offices_removed"
        )
        if save_filter_ids:
            removed_registered = pre_filter_ids.join(
                foursquare_filt.select("row_id"),
                on="row_id",
                how="anti"
            )
            if len(removed_registered) > 0:
                removed_ids_by_filter["registered_offices"] = removed_registered

    # Save filter IDs if requested
    if save_filter_ids and removed_ids_by_filter:
        print("\n" + "="*60)
        print("=== Saving Filter IDs ===")
        print("="*60)

        # Combine all removed IDs with filter type labels
        all_removed = []
        for filter_name, ids_df in removed_ids_by_filter.items():
            ids_with_filter = ids_df.with_columns(
                pl.lit(filter_name).alias("filter_type")
            )
            all_removed.append(ids_with_filter)

        combined_removed = pl.concat(all_removed)

        # Save to parquet
        output_dir = Path(filter_ids_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        combined_removed.write_parquet(filter_ids_path)

        print(f"Filter IDs saved to: {filter_ids_path}")
        print(f"Total removed IDs: {len(combined_removed):,}")
        print("\nBreakdown by filter:")
        for filter_name, ids_df in removed_ids_by_filter.items():
            print(f"  - {filter_name}: {len(ids_df):,}")

    print("\n" + "="*60)
    print("=== Quality Filtering Complete ===")
    print("="*60)
    print(f"POIs removed: {len(foursquare) - len(foursquare_filt):,}")
    print(f"POIs remaining: {len(foursquare_filt):,}")
    print(f"Removal rate: {100 * (len(foursquare) - len(foursquare_filt)) / len(foursquare):.2f}%")

    return foursquare_filt.drop("row_id", strict=False)
