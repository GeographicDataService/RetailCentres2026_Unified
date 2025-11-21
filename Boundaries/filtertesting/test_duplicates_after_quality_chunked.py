#!/usr/bin/env python3
"""
Memory-efficient version: Process duplicates in chunks by geographic region (H3 cells).

Strategy:
1. Apply quality filters
2. Divide UK into H3 level-5 regions (~25km hexagons)
3. Process each region independently to find duplicates
4. Combine results
"""

import polars as pl
import h3
import sys
import os
sys.path.insert(0, 'src')
sys.path.insert(0, '.')

from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary
from test_duplicate_filters import find_duplicate_pois_type1, find_duplicate_pois_type2

def main():
    print("="*80)
    print("DUPLICATE DETECTION (CHUNKED BY REGION)")
    print("="*80)

    # ===== STEP 1: LOAD AND APPLY QUALITY FILTERS =====

    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/4] Loading and applying quality filters...")
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

    print(f"After quality filters: {len(df_quality):,}")

    # ===== STEP 2: ADD H3 LEVEL-5 REGIONS =====

    print(f"\n[2/4] Dividing into geographic regions (H3 level-5)...")

    # Add H3 level-5 cell (large regions, ~25km across)
    df_quality = df_quality.with_columns(
        pl.struct(["lat", "lng"]).map_elements(
            lambda row: h3.latlng_to_cell(row["lat"], row["lng"], 5),
            return_dtype=pl.String
        ).alias("h3_region")
    )

    regions = df_quality.select("h3_region").unique().to_series().to_list()
    print(f"Number of regions: {len(regions)}")
    print(f"Average POIs per region: {len(df_quality) / len(regions):.0f}")

    # ===== STEP 3: PROCESS EACH REGION =====

    print(f"\n[3/4] Processing duplicates by region...")

    all_dupes_type1 = []
    all_dupes_type2 = []

    for i, region in enumerate(regions, 1):
        region_df = df_quality.filter(pl.col("h3_region") == region)

        # Skip small regions
        if len(region_df) < 10:
            continue

        if i % 50 == 0:
            print(f"  Progress: {i}/{len(regions)} regions ({100*i/len(regions):.1f}%) - Current region: {len(region_df):,} POIs")

        # Type 1: Same POI recorded twice
        try:
            dupes_t1 = find_duplicate_pois_type1(
                region_df,
                name_threshold=0.7,
                coord_precision=6,
                use_distance=False
            )
            if len(dupes_t1) > 0:
                dupes_t1 = dupes_t1.with_columns(pl.lit(region).alias("h3_region"))
                all_dupes_type1.append(dupes_t1)
        except Exception as e:
            print(f"    Warning: Type 1 failed for region {region}: {e}")

        # Type 2: Same venue, different business
        try:
            dupes_t2 = find_duplicate_pois_type2(
                region_df,
                name_dissimilarity_max=0.3,
                coord_precision=7,
                same_category=False
            )
            if len(dupes_t2) > 0:
                dupes_t2 = dupes_t2.with_columns(pl.lit(region).alias("h3_region"))
                all_dupes_type2.append(dupes_t2)
        except Exception as e:
            print(f"    Warning: Type 2 failed for region {region}: {e}")

    # ===== STEP 4: COMBINE AND SAVE =====

    print(f"\n[4/4] Combining results and saving...")

    # Combine all regions
    if all_dupes_type1:
        dupes_type1_combined = pl.concat(all_dupes_type1)
        print(f"\nType 1 (Same POI twice): {len(dupes_type1_combined):,} duplicate POIs")
    else:
        dupes_type1_combined = pl.DataFrame()
        print(f"\nType 1: No duplicates found")

    if all_dupes_type2:
        dupes_type2_combined = pl.concat(all_dupes_type2)
        print(f"Type 2 (Venue reuse): {len(dupes_type2_combined):,} duplicate POIs")
    else:
        dupes_type2_combined = pl.DataFrame()
        print(f"Type 2: No duplicates found")

    # Save results
    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    if len(dupes_type1_combined) > 0:
        output_path = f"{output_dir}type1_same_poi_chunked.parquet"
        dupes_type1_combined.write_parquet(output_path)
        print(f"\n✓ Saved Type 1: {output_path}")

        # Top 500 for review
        csv_path = f"{output_dir}type1_same_poi_chunked_top500.csv"
        dupes_type1_combined.select([
            "fsq_place_id", "name", "lat", "lng", "address",
            "date_created", "date_refreshed", "dup_count"
        ]).head(500).write_csv(csv_path)
        print(f"✓ Saved Type 1 CSV: {csv_path}")

    if len(dupes_type2_combined) > 0:
        output_path = f"{output_dir}type2_same_venue_chunked.parquet"
        dupes_type2_combined.write_parquet(output_path)
        print(f"\n✓ Saved Type 2: {output_path}")

        # Top 500 for review
        csv_path = f"{output_dir}type2_same_venue_chunked_top500.csv"
        dupes_type2_combined.select([
            "fsq_place_id", "name", "lat", "lng", "address",
            "date_created", "date_refreshed", "dup_count"
        ]).head(500).write_csv(csv_path)
        print(f"✓ Saved Type 2 CSV: {csv_path}")

    # ===== SUMMARY =====

    print(f"\n{'='*80}")
    print("COMPLETE - SUMMARY")
    print(f"{'='*80}")
    print(f"Quality-filtered dataset: {len(df_quality):,} POIs")
    print(f"Processed in {len(regions)} geographic regions")
    print(f"\nDuplicate Detection Results:")
    print(f"  Type 1 (Same POI twice):   {len(dupes_type1_combined):,} POIs")
    print(f"  Type 2 (Venue reuse):      {len(dupes_type2_combined):,} POIs")

    if len(dupes_type1_combined) > 0:
        keys_t1 = ["lat_round", "lng_round", "fsq_category_id"]
        n_groups_t1 = dupes_type1_combined.select(keys_t1).n_unique()
        est_remove_t1 = len(dupes_type1_combined) - n_groups_t1
        print(f"\nEstimated removals (keeping newest):")
        print(f"  Type 1: ~{est_remove_t1:,} older POIs from {n_groups_t1:,} groups")

    if len(dupes_type2_combined) > 0:
        keys_t2 = ["lat_round", "lng_round"]
        n_groups_t2 = dupes_type2_combined.select(keys_t2).n_unique()
        est_remove_t2 = len(dupes_type2_combined) - n_groups_t2
        print(f"  Type 2: ~{est_remove_t2:,} older POIs from {n_groups_t2:,} groups")

    print(f"\n{'='*80}")

if __name__ == "__main__":
    main()
