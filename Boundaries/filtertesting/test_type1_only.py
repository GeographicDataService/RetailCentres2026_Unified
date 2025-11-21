#!/usr/bin/env python3
"""
Fast Type 1 duplicate detection only (same POI recorded twice).
Should run in under a minute on full dataset.
"""

import polars as pl
import sys
import os
sys.path.insert(0, 'src')
sys.path.insert(0, '.')

from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary
from test_duplicate_filters import find_duplicate_pois_type1, keep_newest_pois

def main():
    print("="*80)
    print("TYPE 1 DUPLICATE DETECTION (SAME POI RECORDED TWICE)")
    print("="*80)

    # ===== LOAD AND FILTER =====

    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading and applying quality filters...")
    df = pl.read_parquet(input_file)
    print(f"Total POIs: {len(df):,}")

    # Apply quality filters
    df_quality = df.filter(pl.col("date_closed").is_null())
    print(f"After removing closed: {len(df_quality):,}")

    df_quality = filter_defunct_retailers(
        df_quality,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=False
    )

    df_quality = filter_by_uk_boundary(
        df_quality,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False
    )

    print(f"After quality filters: {len(df_quality):,}\n")

    # ===== RUN TYPE 1 DUPLICATE DETECTION =====

    print("="*80)
    print("RUNNING TYPE 1 DUPLICATE DETECTION")
    print("="*80)
    print("This should take less than a minute...\n")

    dupes_type1 = find_duplicate_pois_type1(
        df_quality,
        name_threshold=0.7,
        coord_precision=4,  # 4dp ≈ 11m precision, ~25m effective radius
        use_distance=False
    )

    # ===== ANALYZE RESULTS =====

    print(f"\n{'='*80}")
    print("RESULTS ANALYSIS")
    print(f"{'='*80}")

    if len(dupes_type1) > 0:
        keys = ["lat_round", "lng_round", "fsq_category_id"]
        n_groups = dupes_type1.select(keys).n_unique()

        print(f"\nTotal POIs in duplicate groups: {len(dupes_type1):,}")
        print(f"Number of duplicate groups: {n_groups:,}")
        print(f"Average POIs per group: {len(dupes_type1) / n_groups:.2f}")

        # Show top groups
        print(f"\nTop 20 largest duplicate groups:")
        top_groups = (
            dupes_type1
            .group_by(keys)
            .agg([
                pl.count("row_id").alias("group_size"),
                pl.col("name").first().alias("sample_name_1"),
                pl.col("name").head(2).list.get(1).alias("sample_name_2"),
                pl.col("date_created").first().alias("date_1"),
                pl.col("date_created").head(2).list.get(1).alias("date_2"),
            ])
            .sort("group_size", descending=True)
            .head(20)
        )
        print(top_groups.select(["sample_name_1", "sample_name_2", "date_1", "date_2", "group_size"]))

        # Date analysis
        print(f"\n{'='*80}")
        print("DATE ANALYSIS")
        print(f"{'='*80}")

        # Parse dates and analyze
        dupes_dated = dupes_type1.with_columns([
            pl.col("date_created").str.strptime(pl.Datetime, format="%Y-%m-%d", strict=False).alias("date_created_ts"),
        ])

        # Check if we have dates
        dates_available = dupes_dated.filter(pl.col("date_created_ts").is_not_null()).height
        print(f"\nPOIs with valid dates: {dates_available:,} / {len(dupes_type1):,}")

        if dates_available > 0:
            # Year distribution
            year_dist = (
                dupes_dated
                .filter(pl.col("date_created_ts").is_not_null())
                .with_columns(pl.col("date_created_ts").dt.year().alias("year"))
                .group_by("year")
                .len()
                .sort("year")
            )
            print(f"\nDistribution by creation year:")
            print(year_dist)

    else:
        print("\nNo duplicates found!")

    # ===== SAVE RESULTS =====

    print(f"\n{'='*80}")
    print("SAVING RESULTS")
    print(f"{'='*80}")

    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    if len(dupes_type1) > 0:
        # Save full results
        output_path = f"{output_dir}type1_same_poi_full.parquet"
        dupes_type1.write_parquet(output_path)
        print(f"\n✓ Full results: {output_path}")

        # Save top 1000 to CSV for review
        csv_path = f"{output_dir}type1_same_poi_top1000.csv"
        dupes_type1.select([
            "fsq_place_id", "name", "lat", "lng", "address", "tel", "website",
            "date_created", "date_refreshed", "dup_count"
        ]).head(1000).write_csv(csv_path)
        print(f"✓ Top 1000 CSV: {csv_path}")

        # Estimate removals
        keys = ["lat_round", "lng_round", "fsq_category_id"]
        n_groups = dupes_type1.select(keys).n_unique()
        est_remove = len(dupes_type1) - n_groups

        print(f"\n{'='*80}")
        print("REMOVAL ESTIMATE")
        print(f"{'='*80}")
        print(f"If keeping newest POI from each group:")
        print(f"  POIs to remove: ~{est_remove:,}")
        print(f"  POIs to keep: ~{n_groups:,}")
        print(f"  Percentage of dataset: {100 * est_remove / len(df_quality):.3f}%")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
