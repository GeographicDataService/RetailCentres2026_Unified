#!/usr/bin/env python3
"""
Postcode location mismatch filter using ONS Postcode Directory.

This version applies retail filter and quality filters FIRST before testing
postcode mismatch.

Detection criteria:
- POI has a UK postcode
- Look up postcode in ONSPD (Office for National Statistics Postcode Directory)
- Calculate distance between POI coords and postcode coords
- Flag if distance exceeds 1000m threshold

Uses local ONSPD data - fast offline lookup.
"""

import polars as pl
import sys
import numpy as np
import glob
import geopandas as gpd
from shapely.geometry import Point

sys.path.insert(0, 'src')

# Import filter functions
from retail.retailfilter import filter_foursquare
from retail.foursquare_qualityfilter import filter_foursquare_quality


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate haversine distance between two points in meters.
    """
    R = 6371000  # Earth radius in meters

    lat1_rad = np.radians(lat1)
    lat2_rad = np.radians(lat2)
    delta_lat = np.radians(lat2 - lat1)
    delta_lon = np.radians(lon2 - lon1)

    a = np.sin(delta_lat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    distance = R * c

    return distance


def load_onspd(onspd_dir="data/input_files/onspd"):
    """
    Load ONS Postcode Directory from CSV files.

    Returns:
    - Polars DataFrame with columns: postcode, latitude, longitude
    """
    print(f"Loading ONSPD from {onspd_dir}...")

    # Find all CSV files
    csv_files = glob.glob(f"{onspd_dir}/*.csv")
    print(f"  Found {len(csv_files)} CSV files")

    # Load and combine all CSV files
    # Only load columns we need: pcds (postcode), lat, long
    dfs = []
    for i, csv_file in enumerate(csv_files, 1):
        df = pl.read_csv(
            csv_file,
            columns=["pcds", "lat", "long"],
            dtypes={"pcds": pl.Utf8, "lat": pl.Float64, "long": pl.Float64}
        )
        dfs.append(df)

        if i % 20 == 0:
            print(f"    Loaded {i}/{len(csv_files)} files...")

    # Combine all dataframes
    onspd = pl.concat(dfs)

    # Rename columns
    onspd = onspd.rename({"pcds": "postcode", "lat": "latitude", "long": "longitude"})

    # Clean: uppercase, remove nulls
    onspd = onspd.filter(
        pl.col("postcode").is_not_null() &
        pl.col("latitude").is_not_null() &
        pl.col("longitude").is_not_null()
    )

    # Normalize postcode format (uppercase, single space)
    onspd = onspd.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ').alias("postcode")
    )

    print(f"  Loaded {len(onspd):,} postcodes")

    return onspd


def main():
    FILTER_THRESHOLD = 1000  # 1000m threshold

    print("="*80)
    print("POSTCODE LOCATION MISMATCH FILTER TEST (WITH RETAIL + QUALITY FILTERS)")
    print("="*80)
    print(f"\nThreshold: {FILTER_THRESHOLD}m")
    print("\nPipeline:")
    print("  1. Load raw Foursquare POI data")
    print("  2. Apply retail category filter")
    print("  3. Apply quality filters (defunct, UK boundary, duplicates, etc.)")
    print("  4. Test postcode mismatch on filtered data")

    # Load raw POI data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/5] Loading raw POI data: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total raw POIs: {len(foursquare):,}")

    # Apply retail filter
    print(f"\n[2/5] Applying retail category filter...")
    print("="*80)
    foursquare = filter_foursquare(foursquare)
    print(f"After retail filter: {len(foursquare):,}")

    # Apply quality filters
    print(f"\n[3/5] Applying quality filters...")
    print("="*80)
    foursquare = filter_foursquare_quality(
        foursquare,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False,
        filter_defunct=True,
        save_defunct_removed=True,
        filter_duplicates=True,
        save_duplicates_removed=True,
        filter_business_changes=True,
        save_business_changes_removed=True,
        filter_foreign_addresses=True,
        save_foreign_addresses_removed=True
    )
    print(f"After quality filters: {len(foursquare):,}")

    # Load ONSPD
    print(f"\n[4/5] Loading ONS Postcode Directory...")
    print("="*80)
    onspd = load_onspd()

    # Filter to POIs with postcodes
    print(f"\n[5/5] Testing postcode mismatch on filtered data...")
    print("="*80)
    has_postcode = foursquare.filter(pl.col("postcode").is_not_null())
    print(f"POIs with postcode: {len(has_postcode):,} ({100*len(has_postcode)/len(foursquare):.1f}%)")

    # Use full dataset
    sample_df = has_postcode
    print(f"Processing {len(sample_df):,} POIs")

    # Clean postcodes to match ONSPD format
    sample_df = sample_df.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ').alias("postcode_clean")
    )

    # Join with ONSPD to get postcode coordinates
    print(f"\nLooking up postcodes in ONSPD...")
    joined = sample_df.join(
        onspd,
        left_on="postcode_clean",
        right_on="postcode",
        how="left"
    )

    # Filter out invalid/placeholder coordinates (99.999999, 0.0)
    valid_lookups = joined.filter(
        pl.col("latitude").is_not_null() &
        (pl.col("latitude") != 99.999999) &
        (pl.col("longitude") != 0.0)
    )
    print(f"  Successfully looked up: {len(valid_lookups):,} ({100*len(valid_lookups)/len(sample_df):.1f}%)")

    invalid_coords = joined.filter(
        pl.col("latitude").is_not_null() &
        ((pl.col("latitude") == 99.999999) | (pl.col("longitude") == 0.0))
    )
    if len(invalid_coords) > 0:
        print(f"  Excluded placeholder coordinates: {len(invalid_coords):,}")

    if len(valid_lookups) == 0:
        print("\nNo postcodes successfully looked up. Exiting.")
        return

    # Calculate distances
    print(f"\nCalculating distances...")
    results_pd = valid_lookups.to_pandas()

    results_pd['distance_m'] = haversine_distance(
        results_pd['lat'].values,
        results_pd['lng'].values,
        results_pd['latitude'].values,
        results_pd['longitude'].values
    )

    # Convert back to polars
    results_df = pl.from_pandas(results_pd)

    # Filter for threshold
    large_mismatches = results_df.filter(pl.col("distance_m") > FILTER_THRESHOLD).sort("distance_m", descending=True)

    # Analysis
    print(f"\n{'='*80}")
    print(f"RESULTS: Postcode Location Mismatches >{FILTER_THRESHOLD}m")
    print(f"{'='*80}")

    print(f"\nFound {len(large_mismatches):,} mismatches >{FILTER_THRESHOLD}m")
    print(f"Percentage: {100 * len(large_mismatches) / len(results_df):.2f}%")
    print(f"POIs passing: {len(results_df) - len(large_mismatches):,} ({100 * (len(results_df) - len(large_mismatches)) / len(results_df):.2f}%)")

    # Distance distribution for mismatches
    if len(large_mismatches) > 0:
        print("\nDistance distribution (mismatches only):")
        mismatch_stats = large_mismatches.select([
            pl.col("distance_m").min().alias("min"),
            pl.col("distance_m").quantile(0.25).alias("p25"),
            pl.col("distance_m").median().alias("median"),
            pl.col("distance_m").quantile(0.75).alias("p75"),
            pl.col("distance_m").max().alias("max"),
            pl.col("distance_m").mean().alias("mean")
        ])

        for row in mismatch_stats.iter_rows(named=True):
            print(f"  Min:    {row['min']:.0f}m")
            print(f"  P25:    {row['p25']:.0f}m")
            print(f"  Median: {row['median']:.0f}m")
            print(f"  P75:    {row['p75']:.0f}m")
            print(f"  Max:    {row['max']:.0f}m")
            print(f"  Mean:   {row['mean']:.0f}m")

        # Examples of large mismatches
        print(f"\nTop 30 largest mismatches:")
        for i, row in enumerate(large_mismatches.head(30).iter_rows(named=True), 1):
            print(f"\n{i:2d}. {row['name']}")
            print(f"    Postcode: {row['postcode']}")
            print(f"    POI coords:      {row['lat']:.6f}, {row['lng']:.6f}")
            print(f"    Postcode coords: {row['latitude']:.6f}, {row['longitude']:.6f}")
            print(f"    Distance: {row['distance_m']:.0f}m")
            cat = str(row.get('fsq_category_labels', ''))[:50] if row.get('fsq_category_labels') else 'Unknown'
            print(f"    Category: {cat}")

        # Category analysis
        print(f"\n{'='*80}")
        print(f"CATEGORY ANALYSIS")
        print(f"{'='*80}")

        cat_breakdown = (
            large_mismatches
            .group_by("fsq_category_labels")
            .agg(pl.len().alias("count"))
            .sort("count", descending=True)
            .head(20)
        )

        print("\nTop 20 categories:")
        for row in cat_breakdown.iter_rows(named=True):
            label = str(row["fsq_category_labels"])[:60] if row["fsq_category_labels"] else "Unknown"
            print(f"  {row['count']:4d} - {label}")

    # Save results
    print(f"\n{'='*80}")
    print("SAVING RESULTS")
    print(f"{'='*80}")

    import os
    output_dir = "data/POI_files/postcode_mismatch_filtered/"
    os.makedirs(output_dir, exist_ok=True)

    # Save all with distances
    all_path = f"{output_dir}postcode_distances_all.parquet"
    results_df.write_parquet(all_path)
    print(f"\n✓ All results: {all_path}")

    # Save large mismatches (>1km)
    mismatch_path = f"{output_dir}postcode_mismatch_gt{FILTER_THRESHOLD}m.parquet"
    large_mismatches.write_parquet(mismatch_path)
    print(f"✓ Mismatches >{FILTER_THRESHOLD}m: {mismatch_path}")

    # Save CSV for review
    csv_path = f"{output_dir}removed_pois_gt{FILTER_THRESHOLD}m.csv"
    large_mismatches.select([
        "name", "lat", "lng", "address", "postcode", "distance_m"
    ]).write_csv(csv_path)
    print(f"✓ Removed POIs CSV: {csv_path}")

    # Create GeoParquet
    geoparquet_path = f"{output_dir}removed_pois_gt{FILTER_THRESHOLD}m.geoparquet"
    gdf = gpd.GeoDataFrame(
        large_mismatches.to_pandas(),
        geometry=gpd.points_from_xy(
            large_mismatches.to_pandas()["lng"],
            large_mismatches.to_pandas()["lat"]
        ),
        crs="EPSG:4326"
    )
    gdf.to_parquet(geoparquet_path, index=False)
    print(f"✓ GeoParquet: {geoparquet_path}")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
