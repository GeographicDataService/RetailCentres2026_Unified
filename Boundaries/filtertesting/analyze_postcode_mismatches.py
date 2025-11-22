#!/usr/bin/env python3
"""
Analyze postcode mismatches to identify potential false positives and typos.

Analysis includes:
1. Distance distribution near threshold (potential false positives)
2. Postcode typo detection (similar postcodes in ONSPD)
3. Business type patterns (online businesses, franchises)
4. Postcode area analysis
"""

import polars as pl
import sys
import numpy as np
import glob
from collections import Counter
import re

sys.path.insert(0, 'src')


def levenshtein_distance(s1, s2):
    """Calculate Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def find_similar_postcodes(postcode, onspd, max_distance=2):
    """
    Find postcodes in ONSPD that are similar (edit distance <= max_distance).

    Returns list of (similar_postcode, distance, lat, lng, distance_m)
    """
    # Normalize postcode
    postcode_clean = postcode.upper().replace(" ", "")

    # Get all postcodes that have similar prefix (for performance)
    prefix = postcode_clean[:3]

    similar = []
    candidates = onspd.filter(
        pl.col("postcode").str.starts_with(prefix)
    )

    for row in candidates.iter_rows(named=True):
        candidate = row["postcode"].replace(" ", "")
        edit_dist = levenshtein_distance(postcode_clean, candidate)

        if edit_dist > 0 and edit_dist <= max_distance:
            similar.append({
                "similar_postcode": row["postcode"],
                "edit_distance": edit_dist,
                "pc_lat": row["latitude"],
                "pc_lng": row["longitude"]
            })

    return similar


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate haversine distance in meters."""
    R = 6371000
    lat1_rad = np.radians(lat1)
    lat2_rad = np.radians(lat2)
    delta_lat = np.radians(lat2 - lat1)
    delta_lon = np.radians(lon2 - lon1)

    a = np.sin(delta_lat / 2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(delta_lon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c


def load_onspd(onspd_dir="data/input_files/onspd"):
    """Load ONS Postcode Directory."""
    print(f"Loading ONSPD from {onspd_dir}...")
    csv_files = glob.glob(f"{onspd_dir}/*.csv")

    dfs = []
    for i, csv_file in enumerate(csv_files, 1):
        df = pl.read_csv(
            csv_file,
            columns=["pcds", "lat", "long"],
            schema_overrides={"pcds": pl.Utf8, "lat": pl.Float64, "long": pl.Float64}
        )
        dfs.append(df)
        if i % 20 == 0:
            print(f"  Loaded {i}/{len(csv_files)} files...")

    onspd = pl.concat(dfs)
    onspd = onspd.rename({"pcds": "postcode", "lat": "latitude", "long": "longitude"})
    onspd = onspd.filter(
        pl.col("postcode").is_not_null() &
        pl.col("latitude").is_not_null() &
        pl.col("longitude").is_not_null()
    )
    onspd = onspd.with_columns(
        pl.col("postcode").str.to_uppercase().str.replace_all(r'\s+', ' ').alias("postcode")
    )

    print(f"  Loaded {len(onspd):,} postcodes")
    return onspd


def main():
    print("="*80)
    print("POSTCODE MISMATCH FALSE POSITIVE ANALYSIS")
    print("="*80)

    # Load results
    print("\n[1/5] Loading mismatch results...")
    mismatches = pl.read_parquet("data/POI_files/postcode_mismatch_filtered/postcode_mismatch_gt1000m.parquet")
    all_results = pl.read_parquet("data/POI_files/postcode_mismatch_filtered/postcode_distances_all.parquet")
    print(f"  Mismatches: {len(mismatches):,}")
    print(f"  All tested: {len(all_results):,}")

    # Analysis 1: Near-threshold mismatches (potential false positives)
    print(f"\n{'='*80}")
    print("[2/5] NEAR-THRESHOLD ANALYSIS (1000-2000m)")
    print(f"{'='*80}")

    near_threshold = mismatches.filter(
        (pl.col("distance_m") > 1000) & (pl.col("distance_m") <= 2000)
    )
    print(f"\nPOIs with distance 1000-2000m: {len(near_threshold):,}")
    print(f"Percentage of all mismatches: {100 * len(near_threshold) / len(mismatches):.1f}%")

    # Show distribution in 100m buckets
    print("\nDistribution in 100m buckets:")
    for i in range(1000, 2100, 100):
        count = len(mismatches.filter(
            (pl.col("distance_m") > i) & (pl.col("distance_m") <= i + 100)
        ))
        pct = 100 * count / len(mismatches)
        print(f"  {i+1:4d}-{i+100:4d}m: {count:5,} ({pct:5.2f}%)")

    # Analysis 2: Business type patterns
    print(f"\n{'='*80}")
    print("[3/5] BUSINESS TYPE ANALYSIS")
    print(f"{'='*80}")

    # Check for online/remote businesses (often have registered office postcodes)
    online_keywords = ['online', 'web', 'internet', 'digital', 'virtual', 'e-commerce', 'ecommerce']
    franchise_keywords = ['ltd', 'limited', 'plc', 'group', 'uk', 'franchise']

    online_pattern = '|'.join([f'(?i){kw}' for kw in online_keywords])
    franchise_pattern = '|'.join([f'(?i){kw}' for kw in franchise_keywords])

    online_mismatches = mismatches.filter(
        pl.col("name").str.contains(online_pattern, literal=False)
    )
    franchise_mismatches = mismatches.filter(
        pl.col("name").str.contains(franchise_pattern, literal=False)
    )

    print(f"\nPotential online/remote businesses: {len(online_mismatches):,} ({100*len(online_mismatches)/len(mismatches):.2f}%)")
    if len(online_mismatches) > 0:
        print("\nTop 10 online business mismatches:")
        for i, row in enumerate(online_mismatches.sort("distance_m", descending=True).head(10).iter_rows(named=True), 1):
            print(f"  {i:2d}. {row['name'][:50]} - {row['distance_m']:.0f}m")

    print(f"\nPotential franchises/chains: {len(franchise_mismatches):,} ({100*len(franchise_mismatches)/len(mismatches):.2f}%)")

    # Analysis 3: Postcode typo detection
    print(f"\n{'='*80}")
    print("[4/5] POSTCODE TYPO DETECTION")
    print(f"{'='*80}")

    print("\nLoading ONSPD for typo detection...")
    onspd = load_onspd()

    print("\nChecking for potential typos (edit distance <= 2)...")
    print("Analyzing sample of 100 mismatches with distance 1000-5000m...\n")

    # Sample mismatches in the "suspicious" range (1-5km)
    sample = mismatches.filter(
        (pl.col("distance_m") > 1000) & (pl.col("distance_m") <= 5000)
    ).head(100)

    potential_typos = []

    for i, row in enumerate(sample.iter_rows(named=True), 1):
        if i % 20 == 0:
            print(f"  Checked {i}/100...")

        similar = find_similar_postcodes(row['postcode'], onspd, max_distance=2)

        if len(similar) > 0:
            # Check if any similar postcode would bring distance under threshold
            for sim in similar:
                dist_to_similar = haversine_distance(
                    row['lat'], row['lng'],
                    sim['pc_lat'], sim['pc_lng']
                )

                if dist_to_similar < 1000:  # Would pass with corrected postcode
                    potential_typos.append({
                        'name': row['name'],
                        'orig_postcode': row['postcode'],
                        'similar_postcode': sim['similar_postcode'],
                        'edit_distance': sim['edit_distance'],
                        'orig_distance_m': row['distance_m'],
                        'corrected_distance_m': dist_to_similar,
                        'lat': row['lat'],
                        'lng': row['lng']
                    })
                    break  # Only record first match

    print(f"\nPotential typos found: {len(potential_typos)}")

    if len(potential_typos) > 0:
        print(f"\nTop 20 likely postcode typos:")
        print(f"{'Name':<40} {'Original':<10} {'Corrected':<10} {'Edit':>4} {'Orig Dist':>9} {'New Dist':>9}")
        print("-" * 95)

        for i, typo in enumerate(sorted(potential_typos, key=lambda x: x['edit_distance'])[:20], 1):
            print(f"{typo['name'][:38]:<40} {typo['orig_postcode']:<10} {typo['similar_postcode']:<10} "
                  f"{typo['edit_distance']:>4} {typo['orig_distance_m']:>9.0f}m {typo['corrected_distance_m']:>9.0f}m")

    # Analysis 4: Postcode area patterns
    print(f"\n{'='*80}")
    print("[5/5] POSTCODE AREA ANALYSIS")
    print(f"{'='*80}")

    # Extract postcode area (first 1-2 letters)
    mismatches_with_area = mismatches.with_columns(
        pl.col("postcode").str.extract(r'^([A-Z]{1,2})', 1).alias("postcode_area")
    )

    area_counts = (
        mismatches_with_area
        .group_by("postcode_area")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
    )

    print("\nTop 20 postcode areas with most mismatches:")
    print(f"{'Area':>6} | {'Count':>8} | {'Description'}")
    print("-" * 40)

    for row in area_counts.head(20).iter_rows(named=True):
        area = row["postcode_area"] if row["postcode_area"] else "Unknown"
        print(f"{area:>6} | {row['count']:>8,}")

    # Save potential typos
    if len(potential_typos) > 0:
        print(f"\n{'='*80}")
        print("SAVING RESULTS")
        print(f"{'='*80}")

        typos_df = pl.DataFrame(potential_typos)
        output_path = "data/POI_files/postcode_mismatch_filtered/potential_typos.csv"
        typos_df.write_csv(output_path)
        print(f"\n✓ Potential typos saved: {output_path}")

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")

    print(f"\nTotal mismatches: {len(mismatches):,}")
    print(f"Near threshold (1000-2000m): {len(near_threshold):,} ({100*len(near_threshold)/len(mismatches):.1f}%)")
    print(f"Potential online businesses: {len(online_mismatches):,} ({100*len(online_mismatches)/len(mismatches):.1f}%)")
    print(f"Potential typos (in sample): {len(potential_typos)}")

    # Estimate total typos
    if len(sample) > 0:
        typo_rate = len(potential_typos) / len(sample)
        estimated_total_typos = int(typo_rate * len(mismatches))
        print(f"Estimated total typos: ~{estimated_total_typos:,} ({100*typo_rate:.1f}% of mismatches)")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
