#!/usr/bin/env python3
"""
Quick test version using sampling for faster iteration.
"""

import sys
sys.path.insert(0, '.')
from test_duplicate_filters import *

def main():
    print("="*80)
    print("DUPLICATE POI FILTER TESTING (SAMPLE VERSION)")
    print("="*80)

    # Load data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading: {input_file}")
    df = pl.read_parquet(input_file)

    # Filter to open venues
    df = df.filter(pl.col("date_closed").is_null())
    print(f"Open POIs: {len(df):,}")

    # SAMPLE for faster testing
    sample_size = 100_000
    df_sample = df.sample(n=sample_size, seed=42)
    print(f"Using sample of {len(df_sample):,} POIs for testing\n")

    # ===== TEST TYPE 1 =====

    print("\n" + "="*80)
    print("TYPE 1: Same POI Recorded Twice")
    print("="*80)

    dupes_type1 = find_duplicate_pois_type1(
        df_sample,
        name_threshold=0.7,
        coord_precision=6,
        use_distance=False
    )

    # Show samples
    if len(dupes_type1) > 0:
        print("\nSample duplicate groups (Type 1):")
        sample_groups = dupes_type1.head(20).select([
            "name", "lat", "lng", "date_created", "dup_count",
            "fsq_category_labels"
        ])
        print(sample_groups)

        # Save to CSV for review
        dupes_type1.write_parquet("data/POI_files/duplicate_analysis/type1_sample.parquet")
        dupes_type1.select([
            "fsq_place_id", "name", "lat", "lng", "date_created", "date_refreshed",
            "dup_count"
        ]).head(100).write_csv("data/POI_files/duplicate_analysis/type1_sample_top100.csv")
        print("\nSaved sample to: data/POI_files/duplicate_analysis/type1_sample_top100.csv")

    # ===== TEST TYPE 2 =====

    print("\n" + "="*80)
    print("TYPE 2: Same Venue, Different Business")
    print("="*80)

    dupes_type2 = find_duplicate_pois_type2(
        df_sample,
        name_dissimilarity_max=0.3,
        coord_precision=7,
        same_category=False
    )

    # Show samples
    if len(dupes_type2) > 0:
        print("\nSample venue-reuse groups (Type 2):")
        sample_groups = dupes_type2.head(20).select([
            "name", "lat", "lng", "date_created", "dup_count",
            "fsq_category_labels"
        ])
        print(sample_groups)

        # Save
        dupes_type2.write_parquet("data/POI_files/duplicate_analysis/type2_sample.parquet")
        dupes_type2.select([
            "fsq_place_id", "name", "lat", "lng", "date_created", "date_refreshed",
            "dup_count"
        ]).head(100).write_csv("data/POI_files/duplicate_analysis/type2_sample_top100.csv")
        print("\nSaved sample to: data/POI_files/duplicate_analysis/type2_sample_top100.csv")

    # ===== ANALYZE DATES =====

    print("\n" + "="*80)
    print("DATE ANALYSIS: Are duplicates actually old POIs?")
    print("="*80)

    for dtype, dupes_df in [("Type 1", dupes_type1), ("Type 2", dupes_type2)]:
        if len(dupes_df) == 0:
            continue

        print(f"\n{dtype}:")

        # Parse dates
        dupes_dated = dupes_df.with_columns([
            pl.col("date_created").str.strptime(pl.Datetime, strict=False, exact=False).alias("date_created_ts"),
            pl.col("date_refreshed").str.strptime(pl.Datetime, strict=False, exact=False).alias("date_refreshed_ts"),
        ])

        # Get date statistics
        print(f"\nDate Created stats:")
        created_stats = dupes_dated.select("date_created_ts").describe()
        print(created_stats)

        print(f"\nDate Refreshed stats:")
        refreshed_stats = dupes_dated.select("date_refreshed_ts").describe()
        print(refreshed_stats)

        # Check age distribution
        print(f"\nDistribution by year created:")
        year_dist = (
            dupes_dated
            .with_columns(pl.col("date_created_ts").dt.year().alias("year"))
            .group_by("year")
            .len()
            .sort("year")
        )
        print(year_dist)

    print("\n" + "="*80)
    print("TESTING COMPLETE - Review CSV files to validate")
    print("="*80)


if __name__ == "__main__":
    import os
    os.makedirs("data/POI_files/duplicate_analysis/", exist_ok=True)
    main()
