#!/usr/bin/env python3
"""
Detect business changes at the same location without proper refresh.

Tests different category matching levels:
- Level 2 category match
- Level 3 category match
- Exact category match (fsq_category_id)

Location match: ~1m precision (5 decimal places)
"""

import polars as pl
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

def _norm_text(s: str) -> str:
    """Normalize text for comparison."""
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def test_category_level(df, level_name, cat_col, coord_precision=5, name_dissimilarity_threshold=0.3):
    """
    Test business change detection at a specific category level.

    Parameters:
    - df: DataFrame with POI data
    - level_name: Description of category level (e.g., "Level 2")
    - cat_col: Category column to match on (e.g., "level2_category_id")
    - coord_precision: Decimal places for location matching (default: 5 for ~1m)
    - name_dissimilarity_threshold: Maximum name similarity to consider different businesses (default: 0.3)
    """

    print(f"\n{'='*80}")
    print(f"TESTING: {level_name} ({cat_col})")
    print(f"{'='*80}")

    # Add normalized columns
    df_test = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
    ])

    # Group by location + category
    keys = ["lat_round", "lng_round", cat_col]

    location_groups = (
        df_test
        .group_by(keys)
        .agg([
            pl.count("name").alias("poi_count"),
            pl.n_unique("name_norm").alias("unique_names"),
            pl.col("name").head(5).alias("sample_names"),
            pl.col("date_created").head(5).alias("sample_dates"),
        ])
        .filter(pl.col("poi_count") > 1)  # Multiple POIs at same location
        .filter(pl.col("unique_names") > 1)  # Different business names
    )

    print(f"\nResults:")
    print(f"  Locations with multiple POIs: {len(location_groups):,}")
    print(f"  Total POIs involved: {location_groups.select(pl.col('poi_count').sum()).item():,}")

    if len(location_groups) > 0:
        # Show distribution
        print(f"\nDistribution of POIs per location:")
        dist = (
            location_groups
            .group_by("poi_count")
            .agg(pl.len().alias("num_locations"))
            .sort("poi_count", descending=True)
            .head(10)
        )
        print(dist)

        # Show top examples
        print(f"\nTop 10 locations with most business changes:")
        top_examples = (
            location_groups
            .sort("poi_count", descending=True)
            .head(10)
            .select([
                "lat_round", "lng_round", "poi_count", "unique_names",
                "sample_names", "sample_dates"
            ])
        )

        for row in top_examples.iter_rows(named=True):
            names = ", ".join([n[:30] for n in row["sample_names"][:3]])
            print(f"\n  Location ({row['lat_round']}, {row['lng_round']}):")
            print(f"    POIs: {row['poi_count']}, Unique names: {row['unique_names']}")
            print(f"    Sample: {names}")

    return location_groups

def main():
    print("="*80)
    print("BUSINESS CHANGE DETECTION TEST")
    print("="*80)
    print("\nObjective: Find POIs at same location with same category but different names")
    print("(Indicates business changed but location not properly refreshed)")

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    # Apply retail filter
    print("\nApplying retail filter...")
    foursquare_filt = filter_foursquare_invmethod(foursquare)
    print(f"After retail filter: {len(foursquare_filt):,}")

    # Apply quality filters
    print("\nApplying quality filters...")
    foursquare_filt = foursquare_filt.filter(pl.col("date_closed").is_null())
    print(f"After closed filter: {len(foursquare_filt):,}")

    foursquare_filt = filter_defunct_retailers(
        foursquare_filt,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=False
    )

    foursquare_filt = filter_by_uk_boundary(
        foursquare_filt,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False
    )

    print(f"After quality filters: {len(foursquare_filt):,}")

    # Test different category levels
    print(f"\n{'='*80}")
    print("TESTING DIFFERENT CATEGORY MATCHING LEVELS")
    print(f"{'='*80}")
    print(f"Location precision: 5 decimal places (~1m)")

    # Test Level 2 categories
    results_l2 = test_category_level(
        foursquare_filt,
        "Level 2 Category",
        "level2_category_id",
        coord_precision=5
    )

    # Test Level 3 categories
    results_l3 = test_category_level(
        foursquare_filt,
        "Level 3 Category",
        "level3_category_id",
        coord_precision=5
    )

    # Test Exact category match
    results_exact = test_category_level(
        foursquare_filt,
        "Exact Category (fsq_category_id)",
        "fsq_category_id",
        coord_precision=5
    )

    # Summary comparison
    print(f"\n{'='*80}")
    print("SUMMARY COMPARISON")
    print(f"{'='*80}")
    print(f"Level 2:  {len(results_l2):,} locations, {results_l2.select(pl.col('poi_count').sum()).item() if len(results_l2) > 0 else 0:,} POIs")
    print(f"Level 3:  {len(results_l3):,} locations, {results_l3.select(pl.col('poi_count').sum()).item() if len(results_l3) > 0 else 0:,} POIs")
    print(f"Exact:    {len(results_exact):,} locations, {results_exact.select(pl.col('poi_count').sum()).item() if len(results_exact) > 0 else 0:,} POIs")

    print(f"\nRecommendation:")
    print(f"  - Level 2: Broadest, may catch unrelated businesses at same address")
    print(f"  - Level 3: Good balance between specificity and coverage")
    print(f"  - Exact: Most specific, only catches businesses in exact same category")

    # Save results for most promising level (Level 3)
    import os
    output_dir = "data/POI_files/business_change_analysis/"
    os.makedirs(output_dir, exist_ok=True)

    if len(results_l3) > 0:
        output_path = f"{output_dir}level3_business_changes.parquet"
        results_l3.write_parquet(output_path)
        print(f"\n✓ Saved Level 3 results: {output_path}")

        csv_path = f"{output_dir}level3_business_changes_top500.csv"
        results_l3.sort("poi_count", descending=True).head(500).drop("sample_names", "sample_dates").write_csv(csv_path)
        print(f"✓ Saved CSV: {csv_path}")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
