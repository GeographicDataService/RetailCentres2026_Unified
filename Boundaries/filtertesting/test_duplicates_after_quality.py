#!/usr/bin/env python3
"""
Test duplicate filters on FULL dataset AFTER applying quality filters.

Pipeline:
1. Load raw Foursquare data
2. Apply quality filters (defunct, UK boundary, closed venues)
3. Run duplicate detection (Type 1 and Type 2)
4. Analyze results and save
"""

import polars as pl
import sys
import os
sys.path.insert(0, 'src')
sys.path.insert(0, '.')

from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary
from test_duplicate_filters import find_duplicate_pois_type1, find_duplicate_pois_type2, keep_newest_pois

def main():
    print("="*80)
    print("DUPLICATE DETECTION ON QUALITY-FILTERED DATA (FULL DATASET)")
    print("="*80)

    # ===== STEP 1: LOAD DATA =====

    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/5] Loading: {input_file}")
    df = pl.read_parquet(input_file)
    print(f"Total POIs loaded: {len(df):,}")

    # ===== STEP 2: APPLY QUALITY FILTERS =====

    print(f"\n{'='*80}")
    print("[2/5] APPLYING QUALITY FILTERS")
    print(f"{'='*80}")

    # Filter closed venues
    print("\nRemoving closed venues...")
    initial_count = len(df)
    df_quality = df.filter(pl.col("date_closed").is_null())
    closed_removed = initial_count - len(df_quality)
    print(f"  Removed: {closed_removed:,} closed venues")
    print(f"  Remaining: {len(df_quality):,}")

    # Filter defunct retailers
    print("\nFiltering defunct retailers...")
    df_quality = filter_defunct_retailers(
        df_quality,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=False  # Already saved from earlier tests
    )

    # Filter by UK boundary
    print("\nFiltering by UK boundary...")
    df_quality = filter_by_uk_boundary(
        df_quality,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False
    )

    total_removed = initial_count - len(df_quality)
    print(f"\n{'='*80}")
    print(f"QUALITY FILTERING SUMMARY")
    print(f"{'='*80}")
    print(f"Original POIs:     {initial_count:,}")
    print(f"After filtering:   {len(df_quality):,}")
    print(f"Total removed:     {total_removed:,} ({100*total_removed/initial_count:.2f}%)")

    # ===== STEP 3: TEST DUPLICATE FILTERS =====

    print(f"\n{'='*80}")
    print("[3/5] TESTING DUPLICATE FILTERS ON CLEANED DATA")
    print(f"{'='*80}")

    # Type 1: Same POI recorded twice
    print("\nRunning Type 1 filter (Same POI recorded twice)...")
    print("This will take several minutes on the full dataset...")

    dupes_type1 = find_duplicate_pois_type1(
        df_quality,
        name_threshold=0.7,
        coord_precision=6,
        use_distance=False
    )

    # Type 2: Same venue, different business
    print("\nRunning Type 2 filter (Same venue, different business)...")

    dupes_type2 = find_duplicate_pois_type2(
        df_quality,
        name_dissimilarity_max=0.3,
        coord_precision=7,
        same_category=False
    )

    # ===== STEP 4: ANALYZE RESULTS =====

    print(f"\n{'='*80}")
    print("[4/5] ANALYZING DUPLICATE DETECTION RESULTS")
    print(f"{'='*80}")

    # Type 1 analysis
    if len(dupes_type1) > 0:
        print(f"\nType 1 (Same POI recorded twice):")
        print(f"  Total POIs in duplicate groups: {len(dupes_type1):,}")

        keys_t1 = ["lat_round", "lng_round", "fsq_category_id"]
        n_groups_t1 = dupes_type1.select(keys_t1).n_unique()
        print(f"  Number of duplicate groups: {n_groups_t1:,}")
        print(f"  Average POIs per group: {len(dupes_type1) / n_groups_t1:.1f}")

        # Sample the top groups
        print(f"\n  Top 10 largest duplicate groups:")
        top_groups_t1 = (
            dupes_type1
            .group_by(keys_t1)
            .agg([
                pl.count("row_id").alias("group_size"),
                pl.col("name").first().alias("sample_name")
            ])
            .sort("group_size", descending=True)
            .head(10)
        )
        print(top_groups_t1.select(["sample_name", "group_size"]))

    # Type 2 analysis
    if len(dupes_type2) > 0:
        print(f"\nType 2 (Same venue, different business):")
        print(f"  Total POIs in venue groups: {len(dupes_type2):,}")

        keys_t2 = ["lat_round", "lng_round"]
        n_groups_t2 = dupes_type2.select(keys_t2).n_unique()
        print(f"  Number of venue groups: {n_groups_t2:,}")
        print(f"  Average POIs per venue: {len(dupes_type2) / n_groups_t2:.1f}")

        # Sample the top groups
        print(f"\n  Top 10 venues with most businesses:")
        top_groups_t2 = (
            dupes_type2
            .group_by(keys_t2)
            .agg([
                pl.count("row_id").alias("group_size"),
                pl.col("name").head(3).alias("sample_names")
            ])
            .sort("group_size", descending=True)
            .head(10)
        )
        print(top_groups_t2.select(["group_size", "sample_names"]))

    # ===== STEP 5: SAVE RESULTS =====

    print(f"\n{'='*80}")
    print("[5/5] SAVING RESULTS")
    print(f"{'='*80}")

    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    # Save Type 1 duplicates
    if len(dupes_type1) > 0:
        output_path_t1 = f"{output_dir}type1_same_poi_full.parquet"
        dupes_type1.write_parquet(output_path_t1)
        print(f"✓ Type 1: {output_path_t1} ({len(dupes_type1):,} POIs)")

        # Save top 500 to CSV for manual review
        csv_path_t1 = f"{output_dir}type1_same_poi_top500.csv"
        dupes_type1.select([
            "fsq_place_id", "name", "lat", "lng", "address",
            "date_created", "date_refreshed", "tel", "website",
            "dup_count"
        ]).head(500).write_csv(csv_path_t1)
        print(f"✓ Type 1 CSV: {csv_path_t1} (top 500 for review)")

    # Save Type 2 duplicates
    if len(dupes_type2) > 0:
        output_path_t2 = f"{output_dir}type2_same_venue_full.parquet"
        dupes_type2.write_parquet(output_path_t2)
        print(f"✓ Type 2: {output_path_t2} ({len(dupes_type2):,} POIs)")

        # Save top 500 to CSV for manual review
        csv_path_t2 = f"{output_dir}type2_same_venue_top500.csv"
        dupes_type2.select([
            "fsq_place_id", "name", "lat", "lng", "address",
            "date_created", "date_refreshed",
            "dup_count"
        ]).head(500).write_csv(csv_path_t2)
        print(f"✓ Type 2 CSV: {csv_path_t2} (top 500 for review)")

    # ===== SUMMARY =====

    print(f"\n{'='*80}")
    print("COMPLETE - SUMMARY")
    print(f"{'='*80}")
    print(f"\nQuality-filtered dataset: {len(df_quality):,} POIs")
    print(f"\nDuplicate Detection Results:")
    print(f"  Type 1 (Same POI twice):        {len(dupes_type1):,} POIs in {dupes_type1.select(keys_t1).n_unique() if len(dupes_type1) > 0 else 0:,} groups")
    print(f"  Type 2 (Venue reuse):           {len(dupes_type2):,} POIs in {dupes_type2.select(keys_t2).n_unique() if len(dupes_type2) > 0 else 0:,} groups")
    print(f"\nPotential POIs to remove (if keeping newest only):")

    # Estimate removals (keeping newest from each group)
    if len(dupes_type1) > 0:
        est_remove_t1 = len(dupes_type1) - dupes_type1.select(keys_t1).n_unique()
        print(f"  Type 1: ~{est_remove_t1:,} older POIs")

    if len(dupes_type2) > 0:
        est_remove_t2 = len(dupes_type2) - dupes_type2.select(keys_t2).n_unique()
        print(f"  Type 2: ~{est_remove_t2:,} older POIs")

    print(f"\n{'='*80}")
    print("Next steps:")
    print("  1. Review CSV files to validate duplicates are real")
    print("  2. If satisfied, use keep_newest_pois() to apply removal")
    print("  3. Integrate chosen filter into main pipeline")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
