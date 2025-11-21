import os
import argparse
import re
import polars as pl
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from pathlib import Path
from typing import Optional
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


def filter_foursquare_quality(
    foursquare: pl.DataFrame,
    boundary_path: str = "data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
    buffer_m: int = 50,
    save_outside: bool = False,
    filter_defunct: bool = True,
    defunct_csv_path: str = "data/input_files/defunct_uk_retailers_wikipedia_full.csv",
    save_defunct_removed: bool = True
) -> pl.DataFrame:
    """
    Apply quality filters to the Foursquare DataFrame to remove low-quality entries.

    Currently applies:
    1. Defunct retailers filter: Removes POIs matching defunct UK retailers
    2. UK boundary filter: Removes POIs outside the UK boundary (+ buffer)

    Parameters:
    - foursquare: polars.DataFrame containing Foursquare POI data with 'lat', 'lng', 'name' columns
    - boundary_path: Path to UK boundary geopackage file
    - buffer_m: Buffer distance in meters to extend boundary (default: 50m)
    - save_outside: Whether to save POIs outside the boundary for inspection (default: False)
    - filter_defunct: Whether to apply defunct retailers filter (default: True)
    - defunct_csv_path: Path to defunct retailers CSV file (default: "data/input_files/defunct_uk_retailers_wikipedia_full.csv")
    - save_defunct_removed: Whether to save removed defunct POIs and statistics (default: True)

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

    print("\n" + "="*60)
    print("=== Quality Filtering Complete ===")
    print("="*60)
    print(f"POIs removed: {len(foursquare) - len(foursquare_filt):,}")
    print(f"POIs remaining: {len(foursquare_filt):,}")
    print(f"Removal rate: {100 * (len(foursquare) - len(foursquare_filt)) / len(foursquare):.2f}%")

    return foursquare_filt