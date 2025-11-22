#!/usr/bin/env python3
"""
Detailed comparison of business change detection at different category levels.

Shows what each level catches that the others don't, with specific examples.
"""

import polars as pl
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

def _norm_text(s: str) -> str:
    """Normalize text for comparison."""
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def find_locations_at_level(df, cat_col, coord_precision=5):
    """
    Find locations with business changes at specific category level.
    Returns set of (lat_round, lng_round, category) tuples.
    """
    df_test = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
    ])

    keys = ["lat_round", "lng_round", cat_col]

    location_groups = (
        df_test
        .group_by(keys)
        .agg([
            pl.count("name").alias("poi_count"),
            pl.n_unique("name_norm").alias("unique_names"),
            pl.col("name").alias("all_names"),
            pl.col("fsq_place_id").alias("all_ids"),
            pl.col(cat_col).first().alias("category"),
        ])
        .filter(pl.col("poi_count") > 1)
        .filter(pl.col("unique_names") > 1)
    )

    # Create location identifiers
    locations = set()
    for row in location_groups.iter_rows(named=True):
        loc_key = (row["lat_round"], row["lng_round"], str(row["category"]))
        locations.add(loc_key)

    return location_groups, locations

def main():
    print("="*80)
    print("DETAILED COMPARISON: BUSINESS CHANGE DETECTION LEVELS")
    print("="*80)

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/4] Loading and filtering: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    print("\nApplying retail filter...")
    foursquare_filt = filter_foursquare(foursquare)
    print(f"After retail filter: {len(foursquare_filt):,}")

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

    # Run all three levels
    print(f"\n[2/4] Finding business changes at each level...")

    print("\nLevel 2...")
    results_l2, locs_l2 = find_locations_at_level(
        foursquare_filt, "level2_category_id", coord_precision=5
    )

    print("Level 3...")
    results_l3, locs_l3 = find_locations_at_level(
        foursquare_filt, "level3_category_id", coord_precision=5
    )

    print("Exact...")
    results_exact, locs_exact = find_locations_at_level(
        foursquare_filt, "fsq_category_id", coord_precision=5
    )

    # Summary stats
    print(f"\n[3/4] Summary Statistics")
    print("="*80)
    print(f"Level 2:  {len(results_l2):,} locations, {results_l2.select(pl.col('poi_count').sum()).item():,} POIs")
    print(f"Level 3:  {len(results_l3):,} locations, {results_l3.select(pl.col('poi_count').sum()).item():,} POIs")
    print(f"Exact:    {len(results_exact):,} locations, {results_exact.select(pl.col('poi_count').sum()).item():,} POIs")

    # Set operations to find unique catches
    only_l2 = locs_l2 - locs_l3
    only_l3 = locs_l3 - locs_exact
    only_exact = locs_exact - locs_l3
    l2_and_l3 = locs_l2 & locs_l3
    all_three = locs_l2 & locs_l3 & locs_exact

    print(f"\n[4/4] Set Analysis")
    print("="*80)
    print(f"\nLocations caught by:")
    print(f"  All three levels:           {len(all_three):,}")
    print(f"  Level 2 AND Level 3:        {len(l2_and_l3):,}")
    print(f"  Level 3 AND Exact:          {len(locs_l3 & locs_exact):,}")
    print(f"\nUnique to each level:")
    print(f"  Only Level 2:               {len(only_l2):,}")
    print(f"  Only Level 3:               {len(only_l3):,}")
    print(f"  Only Exact:                 {len(only_exact):,}")

    print(f"\nLevel 3 as superset:")
    print(f"  Level 3 contains all Exact: {locs_exact.issubset(locs_l3)}")
    print(f"  Level 2 contains all Level 3: {locs_l3.issubset(locs_l2)}")

    # Show examples of differences
    print(f"\n{'='*80}")
    print("EXAMPLES: What Level 2 catches that Level 3 doesn't")
    print(f"{'='*80}")

    if len(only_l2) > 0:
        # Get examples from only_l2
        sample_l2_only = list(only_l2)[:10]
        for lat, lng, cat in sample_l2_only:
            # Find this location in results_l2
            match = results_l2.filter(
                (pl.col("lat_round") == lat) &
                (pl.col("lng_round") == lng)
            )
            if len(match) > 0:
                row = match.row(0, named=True)
                names = ", ".join([n[:25] for n in row["all_names"][:3]])
                print(f"\n  Location ({lat}, {lng}): {row['poi_count']} POIs")
                print(f"    Names: {names}")
                print(f"    Level 2 Category: {cat}")
    else:
        print("  (None - Level 3 is superset of Level 2)")

    print(f"\n{'='*80}")
    print("EXAMPLES: What Level 3 catches that Exact doesn't")
    print(f"{'='*80}")

    if len(only_l3) > 0:
        sample_l3_only = list(only_l3)[:15]
        for lat, lng, cat in sample_l3_only:
            match = results_l3.filter(
                (pl.col("lat_round") == lat) &
                (pl.col("lng_round") == lng)
            )
            if len(match) > 0:
                row = match.row(0, named=True)
                names = ", ".join([n[:25] for n in row["all_names"][:3]])
                print(f"\n  Location ({lat}, {lng}): {row['poi_count']} POIs")
                print(f"    Names: {names}")
                print(f"    Level 3 Category: {cat}")

    print(f"\n{'='*80}")
    print("EXAMPLES: Locations caught by all three levels (consensus)")
    print(f"{'='*80}")

    if len(all_three) > 0:
        sample_all = list(all_three)[:10]
        for lat, lng, cat in sample_all:
            match = results_exact.filter(
                (pl.col("lat_round") == lat) &
                (pl.col("lng_round") == lng)
            )
            if len(match) > 0:
                row = match.row(0, named=True)
                names = ", ".join([n[:25] for n in row["all_names"][:3]])
                print(f"\n  Location ({lat}, {lng}): {row['poi_count']} POIs")
                print(f"    Names: {names}")
                print(f"    Exact Category: {cat}")

    # Detailed breakdown by POI count ranges
    print(f"\n{'='*80}")
    print("POI COUNT DISTRIBUTION (how many POIs per location)")
    print(f"{'='*80}")

    for level_name, results_df in [
        ("Level 2", results_l2),
        ("Level 3", results_l3),
        ("Exact", results_exact)
    ]:
        print(f"\n{level_name}:")

        # Count ranges
        ranges = [
            ("2 POIs", 2, 2),
            ("3-5 POIs", 3, 5),
            ("6-10 POIs", 6, 10),
            ("11-20 POIs", 11, 20),
            ("21-50 POIs", 21, 50),
            ("51+ POIs", 51, 10000),
        ]

        for label, min_val, max_val in ranges:
            count = len(results_df.filter(
                (pl.col("poi_count") >= min_val) &
                (pl.col("poi_count") <= max_val)
            ))
            pois = results_df.filter(
                (pl.col("poi_count") >= min_val) &
                (pl.col("poi_count") <= max_val)
            ).select(pl.col("poi_count").sum()).item() if count > 0 else 0

            print(f"  {label:15s}: {count:6,} locations, {pois:7,} total POIs")

    # Save detailed comparison
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")
    print("""
Level 2 (Broadest):
  - Catches unrelated businesses at same address more often
  - Groups by broad category (e.g., all "Retail" together)
  - Risk: False positives from different business types at same building
  - Use case: Maximum spam detection

Level 3 (Balanced) ⭐ RECOMMENDED:
  - Good specificity while maintaining coverage
  - Groups by specific retail type (e.g., "Clothing Store", "Bookstore")
  - Most comprehensive without excessive false positives
  - Use case: Standard business change detection

Exact (Most Specific):
  - Only catches identical category IDs
  - Misses legitimate cases where category slightly changed
  - Lowest false positive rate
  - Use case: Conservative filtering, high-confidence spam removal
    """)

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
