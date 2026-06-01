#!/usr/bin/env python3
"""
Postcode location mismatch filter using ONS Postcode Directory.

Detects POIs where coordinates don't match postcode location.

Detection criteria:
- POI has a UK postcode
- Look up postcode in ONSPD (Office for National Statistics Postcode Directory)
- Calculate distance between POI coords and postcode coords
- Flag if distance exceeds threshold (test 100m, 250m, 500m, 1000m)

Uses local ONSPD data - fast offline lookup.
"""

import polars as pl
import sys
import numpy as np
import glob
import geopandas as gpd
from shapely.geometry import Point

sys.path.insert(0, 'src')

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
    print("="*80)
    print("POSTCODE LOCATION MISMATCH FILTER TEST (ONSPD)")
    print("="*80)
    print("\nDetection criteria:")
    print("  - POI has UK postcode")
    print("  - Look up postcode in ONS Postcode Directory")
    print("  - Flag if distance > threshold")
    print("  - Test thresholds: 100m, 250m, 500m, 1000m, 2000m")

    # Load ONSPD
    print(f"\n[1/4] Loading ONS Postcode Directory...")
    onspd = load_onspd()

    # Load POI data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[2/4] Loading POI data: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    # Filter to POIs with postcodes
    print(f"\n[3/4] Filtering to POIs with postcodes...")
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
    print(f"\n[4/4] Looking up postcodes in ONSPD...")
    joined = sample_df.join(
        onspd,
        left_on="postcode_clean",
        right_on="postcode",
        how="left"
    )

    # Filter out invalid/placeholder coordinates (99.999999, 0.0)
    # These are used in ONSPD for Jersey, Guernsey, Isle of Man postcodes
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

    # Filter threshold: 1km
    FILTER_THRESHOLD = 1000
    
    # Analyze mismatches at different thresholds
    print(f"\n{'='*80}")
    print("ANALYSIS: Postcode Location Mismatches")
    print(f"{'='*80}")

    thresholds = [100, 250, 500, 1000, 2000]

    print("\nMismatch counts by threshold:")
    print(f"{'Threshold':>12} | {'Count':>8} | {'Percentage':>10} | {'Description'}")
    print("-" * 60)

    for thresh in thresholds:
        mismatches = results_df.filter(pl.col("distance_m") > thresh)
        count = len(mismatches)
        pct = 100 * count / len(results_df)

        if thresh <= 100:
            desc = "Very precise"
        elif thresh <= 250:
            desc = "Same street"
        elif thresh <= 500:
            desc = "Same area"
        elif thresh <= 1000:
            desc = "Nearby"
        else:
            desc = "Different area"

        print(f"{thresh:>12}m | {count:>8,} | {pct:>9.2f}% | {desc}")

    # Distance distribution
    print("\nDistance distribution:")
    distance_stats = results_df.select([
        pl.col("distance_m").min().alias("min"),
        pl.col("distance_m").quantile(0.25).alias("p25"),
        pl.col("distance_m").median().alias("median"),
        pl.col("distance_m").quantile(0.75).alias("p75"),
        pl.col("distance_m").quantile(0.95).alias("p95"),
        pl.col("distance_m").quantile(0.99).alias("p99"),
        pl.col("distance_m").max().alias("max"),
        pl.col("distance_m").mean().alias("mean")
    ])

    for row in distance_stats.iter_rows(named=True):
        print(f"  Min:    {row['min']:.0f}m")
        print(f"  P25:    {row['p25']:.0f}m")
        print(f"  Median: {row['median']:.0f}m")
        print(f"  P75:    {row['p75']:.0f}m")
        print(f"  P95:    {row['p95']:.0f}m")
        print(f"  P99:    {row['p99']:.0f}m")
        print(f"  Max:    {row['max']:.0f}m")
        print(f"  Mean:   {row['mean']:.0f}m")

    # Examples of large mismatches
    print(f"{'='*80}")
    print(f"EXAMPLES: Large mismatches (>{FILTER_THRESHOLD}m)")
    print(f"{'='*80}")

    large_mismatches = results_df.filter(pl.col("distance_m") > FILTER_THRESHOLD).sort("distance_m", descending=True)

    print(f"\nFound {len(large_mismatches):,} mismatches >{FILTER_THRESHOLD}m")
    print(f"Percentage: {100 * len(large_mismatches) / len(results_df):.2f}%")

    print("\nTop 30 largest mismatches:")
    for i, row in enumerate(large_mismatches.head(30).iter_rows(named=True), 1):
        print(f"\n{i:2d}. {row['name']}")
        print(f"    Postcode: {row['postcode']}")
        print(f"    POI coords:      {row['lat']:.6f}, {row['lng']:.6f}")
        print(f"    Postcode coords: {row['latitude']:.6f}, {row['longitude']:.6f}")
        print(f"    Distance: {row['distance_m']:.0f}m")
        cat = str(row.get('fsq_category_labels', ''))[:50] if row.get('fsq_category_labels') else 'Unknown'
        print(f"    Category: {cat}")

    # Category analysis
    print(f"{'='*80}")
    print(f"CATEGORY ANALYSIS: POIs with >{FILTER_THRESHOLD}m mismatch")
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
    output_dir = "data/POI_files/postcode_mismatch/"
    os.makedirs(output_dir, exist_ok=True)

    # Save all with distances
    all_path = f"{output_dir}postcode_distances_all.parquet"
    results_df.write_parquet(all_path)
    print(f"\n✓ All results: {all_path}")

    # Save large mismatches (>1km)
    large_mismatches = results_df.filter(pl.col("distance_m") > FILTER_THRESHOLD).sort("distance_m", descending=True)
    mismatch_path = f"{output_dir}postcode_mismatch_gt{FILTER_THRESHOLD}m.parquet"
    large_mismatches.write_parquet(mismatch_path)
    print(f"✓ Mismatches >{FILTER_THRESHOLD}m: {mismatch_path}")

    # Save CSV for review - ALL removed POIs with requested columns
    csv_path = f"{output_dir}removed_pois_gt{FILTER_THRESHOLD}m.csv"
    large_mismatches.select([
        "name", "lat", "lng", "address", "postcode", "distance_m"
    ]).write_csv(csv_path)
    print(f"✓ Removed POIs CSV (all {len(large_mismatches):,} POIs): {csv_path}")

    # Create GeoParquet for 1km threshold
    geoparquet_1km_path = f"{output_dir}removed_pois_gt{FILTER_THRESHOLD}m.geoparquet"
    gdf_1km = gpd.GeoDataFrame(
        large_mismatches.to_pandas(),
        geometry=gpd.points_from_xy(
            large_mismatches.to_pandas()["lng"],
            large_mismatches.to_pandas()["lat"]
        ),
        crs="EPSG:4326"
    )
    gdf_1km.to_parquet(geoparquet_1km_path, index=False)
    print(f"✓ GeoParquet >{FILTER_THRESHOLD}m: {geoparquet_1km_path}")

    # Also create 100m threshold geoparquet
    large_mismatches_100m = results_df.filter(pl.col("distance_m") > 100).sort("distance_m", descending=True)
    geoparquet_100m_path = f"{output_dir}removed_pois_gt100m.geoparquet"
    gdf_100m = gpd.GeoDataFrame(
        large_mismatches_100m.to_pandas(),
        geometry=gpd.points_from_xy(
            large_mismatches_100m.to_pandas()["lng"],
            large_mismatches_100m.to_pandas()["lat"]
        ),
        crs="EPSG:4326"
    )
    gdf_100m.to_parquet(geoparquet_100m_path, index=False)
    print(f"✓ GeoParquet >100m: {geoparquet_100m_path} ({len(large_mismatches_100m):,} POIs)")

    # Save 100m CSV as well
    csv_100m_path = f"{output_dir}removed_pois_gt100m.csv"
    large_mismatches_100m.select([
        "name", "lat", "lng", "address", "postcode", "distance_m"
    ]).write_csv(csv_100m_path)
    print(f"✓ Removed POIs CSV >100m: {csv_100m_path}")

    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")

    # Based on distribution, recommend threshold
    p95_dist = distance_stats.select(pl.col("p95")).item()

    print(f"\n95th percentile distance: {p95_dist:.0f}m")

    if p95_dist < 100:
        print("Recommendation: Use 250m threshold (catches outliers, low false positive risk)")
    elif p95_dist < 250:
        print("Recommendation: Use 500m threshold (safer to avoid false positives)")
    elif p95_dist < 500:
        print("Recommendation: Use 1000m threshold (conservative, low false positive risk)")
    else:
        print("Recommendation: Use 2000m threshold (data quality issues, very conservative)")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
