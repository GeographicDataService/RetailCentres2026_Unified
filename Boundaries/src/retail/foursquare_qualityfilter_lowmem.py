#!/usr/bin/env python3
"""
Memory-optimized version of postcode mismatch filter.

Key optimizations:
1. Load ONSPD incrementally with progress tracking
2. Process POIs in batches to avoid large joins
3. Use Polars native operations (no Pandas conversion)
4. Explicit garbage collection
5. Minimal intermediate dataframes
"""

import polars as pl
import glob
import gc
from pathlib import Path


def haversine_distance_polars(df: pl.DataFrame, lat1_col: str, lon1_col: str, lat2_col: str, lon2_col: str) -> pl.Expr:
    """
    Calculate haversine distance using Polars expressions (no Pandas).

    Returns a Polars expression that can be used in with_columns().
    """
    import math

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


def load_onspd_batched(onspd_dir: str, batch_size: int = 20) -> pl.DataFrame:
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
    print(f"  Combining batches...")
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


def filter_postcode_mismatch_lowmem(
    foursquare: pl.DataFrame,
    onspd_dir: str = "data/input_files/onspd",
    distance_threshold_m: float = 1000.0,
    batch_size: int = 100000,
    save_removed: bool = True,
    output_dir: str = "data/POI_files/postcode_mismatch_removed"
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
        onspd = load_onspd_batched(onspd_dir, batch_size=20)
    except FileNotFoundError:
        print(f"  WARNING: No ONSPD files found, skipping filter")
        return foursquare

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
            haversine_distance_polars(valid, "lat", "lng", "pc_latitude", "pc_longitude").alias("distance_m")
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
    print(f"  Combining results...")

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
        import os
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
