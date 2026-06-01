#!/usr/bin/env python3
"""
Complete analysis of ALL defunct retailers (not just top 20).
"""

import polars as pl
import sys
sys.path.insert(0, 'src')

def _make_key(col: pl.Expr) -> pl.Expr:
    """Helper to normalize strings for matching (lowercase, stripped)."""
    return col.str.strip_chars().str.to_lowercase()

def main():
    print("="*80)
    print("COMPLETE DEFUNCT RETAILERS ANALYSIS (ALL BRANDS)")
    print("="*80)

    # Load data
    foursquare = pl.read_parquet("data/input_files/uk_foursquare_cc_nov_iceberg.parquet")
    defunct_retailers = pl.read_csv("data/input_files/defunct_uk_retailers_wikipedia_full.csv")

    print(f"\nTotal Foursquare POIs: {len(foursquare):,}")
    print(f"Defunct retailers in list: {len(defunct_retailers):,}")

    # Clean defunct retailers list
    defunct_retailers = (
        defunct_retailers
        .unique(subset=["Brand"])
        .with_columns(
            pl.col("Brand").str.replace(r"\s*\(.*?\)", "", literal=False)
        )
    )

    print(f"Unique defunct retailers (after cleaning): {len(defunct_retailers):,}")

    # Build normalized keys
    defunct = defunct_retailers.with_columns(brand_key=_make_key(pl.col("Brand")))
    fs = foursquare.with_columns(brand_key=_make_key(pl.col("name")))

    # Find all removed POIs
    removed = fs.join(defunct.select("brand_key").unique(), on="brand_key", how="inner")

    # Get complete counts for ALL brands
    removed_counts = (
        removed
        .group_by("brand_key")
        .len()
        .rename({"len": "removed_poi_count"})
        .sort("removed_poi_count", descending=True)
    )

    # Add human-readable brand names
    defunct_lookup = defunct.select(["brand_key", "Brand"]).unique()
    complete_summary = (
        removed_counts
        .join(defunct_lookup, on="brand_key", how="left")
        .select(["Brand", "removed_poi_count"])
        .sort("removed_poi_count", descending=True)
    )

    total_removed = complete_summary.select(pl.col("removed_poi_count").sum()).item()
    num_brands = len(complete_summary)

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total defunct brands matched: {num_brands}")
    print(f"Total POIs removed: {total_removed:,}")
    print(f"Average POIs per brand: {total_removed/num_brands:.1f}")

    # Save complete list
    output_file = "data/POI_files/defunct_removed/complete_defunct_summary.csv"
    complete_summary.write_csv(output_file)
    print(f"\nComplete summary saved to: {output_file}")

    # Display full table
    print(f"\n{'='*80}")
    print("ALL DEFUNCT BRANDS REMOVED (sorted by POI count)")
    print(f"{'='*80}")
    print(complete_summary)

    # Statistics
    print(f"\n{'='*80}")
    print("DISTRIBUTION STATISTICS")
    print(f"{'='*80}")

    counts = complete_summary.get_column("removed_poi_count")
    print(f"Mean POIs per brand:     {counts.mean():.1f}")
    print(f"Median POIs per brand:   {counts.median():.0f}")
    print(f"Max POIs (single brand): {counts.max():,}")
    print(f"Min POIs (single brand): {counts.min()}")

    # Percentiles
    print(f"\nPercentiles:")
    for p in [10, 25, 50, 75, 90, 95, 99]:
        val = counts.quantile(p/100)
        print(f"  {p}th percentile: {val:.0f} POIs")

    # Size categories
    print(f"\n{'='*80}")
    print("BRANDS BY REMOVAL SIZE")
    print(f"{'='*80}")

    summary_categorized = complete_summary.with_columns(
        pl.when(pl.col("removed_poi_count") >= 500)
        .then(pl.lit("Very Large (500+)"))
        .when(pl.col("removed_poi_count") >= 200)
        .then(pl.lit("Large (200-499)"))
        .when(pl.col("removed_poi_count") >= 100)
        .then(pl.lit("Medium (100-199)"))
        .when(pl.col("removed_poi_count") >= 50)
        .then(pl.lit("Small (50-99)"))
        .when(pl.col("removed_poi_count") >= 10)
        .then(pl.lit("Very Small (10-49)"))
        .otherwise(pl.lit("Minimal (<10)"))
        .alias("size_category")
    )

    category_stats = (
        summary_categorized
        .group_by("size_category")
        .agg([
            pl.count("Brand").alias("num_brands"),
            pl.sum("removed_poi_count").alias("total_pois"),
            pl.min("removed_poi_count").alias("min_pois"),
            pl.max("removed_poi_count").alias("max_pois")
        ])
        .sort("total_pois", descending=True)
        .with_columns(
            pct_of_total = (100 * pl.col("total_pois") / total_removed).round(2)
        )
    )

    print(category_stats)

    # Cumulative analysis
    print(f"\n{'='*80}")
    print("CUMULATIVE CONTRIBUTION")
    print(f"{'='*80}")

    complete_summary_cum = complete_summary.with_columns(
        cumulative_pois = pl.col("removed_poi_count").cum_sum(),
        cumulative_pct = (100 * pl.col("removed_poi_count").cum_sum() / total_removed).round(2)
    )

    for threshold in [1, 3, 5, 10, 20, 30, 50, 100]:
        if threshold <= len(complete_summary_cum):
            row = complete_summary_cum.row(threshold - 1, named=True)
            pct = row['cumulative_pct']
            cumulative_pois = row['cumulative_pois']
            print(f"Top {threshold:3d} brands: {cumulative_pois:6,} POIs ({pct:5.1f}% of total removed)")

    # Show specific categories
    print(f"\n{'='*80}")
    print("VERY LARGE BRANDS (500+ POIs)")
    print(f"{'='*80}")
    very_large = complete_summary.filter(pl.col("removed_poi_count") >= 500)
    print(very_large)

    print(f"\n{'='*80}")
    print("LARGE BRANDS (200-499 POIs)")
    print(f"{'='*80}")
    large = complete_summary.filter(
        (pl.col("removed_poi_count") >= 200) &
        (pl.col("removed_poi_count") < 500)
    )
    print(large)

    print(f"\n{'='*80}")
    print("BRANDS WITH ONLY 1 POI REMOVED")
    print(f"{'='*80}")
    single_poi = complete_summary.filter(pl.col("removed_poi_count") == 1)
    print(f"Number of brands: {len(single_poi)}")
    print(single_poi)

    # Key insights
    print(f"\n{'='*80}")
    print("KEY INSIGHTS")
    print(f"{'='*80}")

    # Concentration
    top10_total = complete_summary.head(10).select(pl.col("removed_poi_count").sum()).item()
    top10_pct = 100 * top10_total / total_removed

    # Long tail
    brands_with_lt10 = complete_summary.filter(pl.col("removed_poi_count") < 10)
    lt10_total = brands_with_lt10.select(pl.col("removed_poi_count").sum()).item()
    lt10_pct = 100 * lt10_total / total_removed

    print(f"• Top 10 brands account for {top10_pct:.1f}% of all removed POIs")
    print(f"• {len(brands_with_lt10)} brands have <10 POIs each ({lt10_pct:.1f}% of removed)")
    print(f"• McColl's dominates with {complete_summary.row(0, named=True)['removed_poi_count']:,} POIs")
    print(f"• Median brand has only {counts.median():.0f} POIs removed")

    print(f"\n{'='*80}")

if __name__ == "__main__":
    main()
