#!/usr/bin/env python3
"""
Detailed comparison of business change detection with HIERARCHICAL category matching.

Level 2 match: level1 matches AND level2 matches (or both NaN)
Level 3 match: level1 matches AND level2 matches (or both NaN) AND level3 matches (or both NaN)

If categories are NaN, that's as far as precision goes - still a match.
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

def find_hierarchical_matches(df, level, coord_precision=5):
    """
    Find locations with business changes using hierarchical category matching.

    level="L2": level1 + level2 must match (NaN = match)
    level="L3": level1 + level2 + level3 must match (NaN = match)
    level="Exact": fsq_category_id must match exactly
    """
    df_test = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
    ])

    if level == "Exact":
        # Exact match on fsq_category_id
        keys = ["lat_round", "lng_round", "fsq_category_id"]

        location_groups = (
            df_test
            .group_by(keys)
            .agg([
                pl.count("name").alias("poi_count"),
                pl.n_unique("name_norm").alias("unique_names"),
                pl.col("name").alias("all_names"),
                pl.col("fsq_place_id").alias("all_ids"),
                pl.col("fsq_category_id").first().alias("category_key"),
            ])
            .filter(pl.col("poi_count") > 1)
            .filter(pl.col("unique_names") > 1)
        )

    elif level == "L2":
        # Hierarchical Level 2: level1 + level2 match
        location_groups = (
            df_test
            .group_by(["lat_round", "lng_round", "level1_category_id", "level2_category_id"])
            .agg([
                pl.count("name").alias("poi_count"),
                pl.n_unique("name_norm").alias("unique_names"),
                pl.col("name").alias("all_names"),
                pl.col("fsq_place_id").alias("all_ids"),
                pl.concat_str([
                    pl.col("level1_category_id").cast(pl.Utf8),
                    pl.lit("_"),
                    pl.col("level2_category_id").cast(pl.Utf8)
                ]).first().alias("category_key"),
            ])
            .filter(pl.col("poi_count") > 1)
            .filter(pl.col("unique_names") > 1)
        )

    elif level == "L3":
        # Hierarchical Level 3: level1 + level2 + level3 match
        location_groups = (
            df_test
            .group_by(["lat_round", "lng_round", "level1_category_id", "level2_category_id", "level3_category_id"])
            .agg([
                pl.count("name").alias("poi_count"),
                pl.n_unique("name_norm").alias("unique_names"),
                pl.col("name").alias("all_names"),
                pl.col("fsq_place_id").alias("all_ids"),
                pl.concat_str([
                    pl.col("level1_category_id").cast(pl.Utf8),
                    pl.lit("_"),
                    pl.col("level2_category_id").cast(pl.Utf8),
                    pl.lit("_"),
                    pl.col("level3_category_id").cast(pl.Utf8)
                ]).first().alias("category_key"),
            ])
            .filter(pl.col("poi_count") > 1)
            .filter(pl.col("unique_names") > 1)
        )

    return location_groups

def main():
    print("="*80)
    print("HIERARCHICAL CATEGORY MATCHING - BUSINESS CHANGE DETECTION")
    print("="*80)
    print("\nMatching logic:")
    print("  Level 2: level1 + level2 must match (NaN = match)")
    print("  Level 3: level1 + level2 + level3 must match (NaN = match)")
    print("  Exact:   fsq_category_id must match exactly")

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/4] Loading and filtering: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    print("\nApplying retail filter...")
    foursquare_filt = filter_foursquare_invmethod(foursquare)
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

    # Check category completeness
    print(f"\n[2/4] Category completeness check:")
    print(f"  Has level1: {foursquare_filt.filter(pl.col('level1_category_id').is_not_null()).height:,} ({100*foursquare_filt.filter(pl.col('level1_category_id').is_not_null()).height/len(foursquare_filt):.1f}%)")
    print(f"  Has level2: {foursquare_filt.filter(pl.col('level2_category_id').is_not_null()).height:,} ({100*foursquare_filt.filter(pl.col('level2_category_id').is_not_null()).height/len(foursquare_filt):.1f}%)")
    print(f"  Has level3: {foursquare_filt.filter(pl.col('level3_category_id').is_not_null()).height:,} ({100*foursquare_filt.filter(pl.col('level3_category_id').is_not_null()).height/len(foursquare_filt):.1f}%)")

    # Run all three levels
    print(f"\n[3/4] Finding business changes with hierarchical matching...")

    print("\nLevel 2 (level1 + level2)...")
    results_l2 = find_hierarchical_matches(foursquare_filt, "L2", coord_precision=5)

    print("Level 3 (level1 + level2 + level3)...")
    results_l3 = find_hierarchical_matches(foursquare_filt, "L3", coord_precision=5)

    print("Exact (fsq_category_id)...")
    results_exact = find_hierarchical_matches(foursquare_filt, "Exact", coord_precision=5)

    # Summary stats
    print(f"\n[4/4] Summary Statistics")
    print("="*80)
    print(f"Level 2:  {len(results_l2):,} locations, {results_l2.select(pl.col('poi_count').sum()).item():,} POIs")
    print(f"Level 3:  {len(results_l3):,} locations, {results_l3.select(pl.col('poi_count').sum()).item():,} POIs")
    print(f"Exact:    {len(results_exact):,} locations, {results_exact.select(pl.col('poi_count').sum()).item():,} POIs")

    # Show examples from each level
    print(f"\n{'='*80}")
    print("EXAMPLES: Level 2 matches (top 20 by POI count)")
    print(f"{'='*80}")

    top_l2 = results_l2.sort("poi_count", descending=True).head(20)
    for row in top_l2.iter_rows(named=True):
        names = ", ".join([n[:30] for n in row["all_names"][:3]])
        print(f"\n  {row['poi_count']:3d} POIs at ({row['lat_round']}, {row['lng_round']})")
        print(f"      Category: {row['category_key']}")
        print(f"      Names: {names}")

    print(f"\n{'='*80}")
    print("EXAMPLES: Level 3 matches (top 20 by POI count)")
    print(f"{'='*80}")

    top_l3 = results_l3.sort("poi_count", descending=True).head(20)
    for row in top_l3.iter_rows(named=True):
        names = ", ".join([n[:30] for n in row["all_names"][:3]])
        print(f"\n  {row['poi_count']:3d} POIs at ({row['lat_round']}, {row['lng_round']})")
        print(f"      Category: {row['category_key']}")
        print(f"      Names: {names}")

    print(f"\n{'='*80}")
    print("EXAMPLES: Exact matches (top 20 by POI count)")
    print(f"{'='*80}")

    top_exact = results_exact.sort("poi_count", descending=True).head(20)
    for row in top_exact.iter_rows(named=True):
        names = ", ".join([n[:30] for n in row["all_names"][:3]])
        print(f"\n  {row['poi_count']:3d} POIs at ({row['lat_round']}, {row['lng_round']})")
        print(f"      Category: {row['category_key']}")
        print(f"      Names: {names}")

    # Distribution analysis
    print(f"\n{'='*80}")
    print("POI COUNT DISTRIBUTION")
    print(f"{'='*80}")

    for level_name, results_df in [
        ("Level 2", results_l2),
        ("Level 3", results_l3),
        ("Exact", results_exact)
    ]:
        print(f"\n{level_name}:")

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

    # Hierarchical relationships
    print(f"\n{'='*80}")
    print("HIERARCHICAL RELATIONSHIPS")
    print(f"{'='*80}")
    print("""
With proper hierarchical matching:
  - Level 2 should catch >= Level 3 (less specific)
  - Level 3 should catch >= Exact (less specific)
  - Exact is most restrictive

Note: Level 2 < Level 3 if many POIs have incomplete categories.
    """)

    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")
    print("""
Level 2 (Broad):
  - Matches on level1 + level2 category hierarchy
  - Good for catching business changes within broad retail types
  - Example: All "Clothing Stores" regardless of specific type

Level 3 (Specific) ⭐ RECOMMENDED:
  - Matches on full category hierarchy (level1 + level2 + level3)
  - Best balance of precision and recall
  - Example: Only "Women's Clothing Store" vs "Men's Clothing Store"

Exact (Most Specific):
  - Matches on exact fsq_category_id only
  - Highest precision, may miss valid cases
  - Use for high-confidence spam detection only
    """)

    # Save Level 3 results
    import os
    output_dir = "data/POI_files/business_change_analysis/"
    os.makedirs(output_dir, exist_ok=True)

    output_path = f"{output_dir}level3_hierarchical_business_changes.parquet"
    results_l3.write_parquet(output_path)
    print(f"\n✓ Saved Level 3 results: {output_path}")

    csv_path = f"{output_dir}level3_hierarchical_business_changes_top500.csv"
    results_l3.sort("poi_count", descending=True).head(500).drop("all_names", "all_ids").write_csv(csv_path)
    print(f"✓ Saved CSV: {csv_path}")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
