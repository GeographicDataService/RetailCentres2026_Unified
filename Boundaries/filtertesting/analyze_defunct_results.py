#!/usr/bin/env python3
"""
Detailed analysis of defunct retailers removal results.
"""

import polars as pl
import pandas as pd

def main():
    print("="*80)
    print("DETAILED ANALYSIS OF DEFUNCT RETAILERS REMOVAL")
    print("="*80)

    # Load the summary
    summary = pl.read_csv("data/POI_files/defunct_removed/defunct_removed_summary.csv")

    total_removed = summary.select(pl.col("removed_poi_count").sum()).item()
    num_brands = len(summary)

    print(f"\nTotal defunct brands matched: {num_brands}")
    print(f"Total POIs removed: {total_removed:,}\n")

    # Show full list
    print("="*80)
    print("COMPLETE LIST OF ALL REMOVED DEFUNCT BRANDS")
    print("="*80)
    print(summary)

    # Calculate percentiles
    print("\n" + "="*80)
    print("DISTRIBUTION STATISTICS")
    print("="*80)

    counts = summary.get_column("removed_poi_count")

    print(f"Mean POIs per brand:     {counts.mean():.1f}")
    print(f"Median POIs per brand:   {counts.median():.0f}")
    print(f"Max POIs (single brand): {counts.max():,}")
    print(f"Min POIs (single brand): {counts.min()}")

    # Cumulative analysis
    summary_sorted = summary.sort("removed_poi_count", descending=True)
    summary_sorted = summary_sorted.with_columns(
        cumulative_pois = pl.col("removed_poi_count").cum_sum(),
        cumulative_pct = (100 * pl.col("removed_poi_count").cum_sum() / total_removed).round(2)
    )

    print("\n" + "="*80)
    print("CUMULATIVE REMOVAL BREAKDOWN")
    print("="*80)

    # Show key thresholds
    for threshold in [1, 5, 10, 20, 50]:
        if threshold <= len(summary_sorted):
            row = summary_sorted.row(threshold - 1, named=True)
            pct = row['cumulative_pct']
            cumulative_pois = row['cumulative_pois']
            print(f"Top {threshold:3d} brands: {cumulative_pois:6,} POIs ({pct:5.1f}% of total removed)")

    # Category breakdown by size
    print("\n" + "="*80)
    print("BRANDS BY REMOVAL SIZE")
    print("="*80)

    # Categorize brands
    summary_categorized = summary.with_columns(
        pl.when(pl.col("removed_poi_count") >= 500)
        .then(pl.lit("Large (500+)"))
        .when(pl.col("removed_poi_count") >= 100)
        .then(pl.lit("Medium (100-499)"))
        .when(pl.col("removed_poi_count") >= 50)
        .then(pl.lit("Small (50-99)"))
        .otherwise(pl.lit("Very Small (<50)"))
        .alias("size_category")
    )

    category_stats = (
        summary_categorized
        .group_by("size_category")
        .agg([
            pl.count("Brand").alias("num_brands"),
            pl.sum("removed_poi_count").alias("total_pois")
        ])
        .sort("total_pois", descending=True)
        .with_columns(
            pct_of_total = (100 * pl.col("total_pois") / total_removed).round(2)
        )
    )

    print(category_stats)

    # Show brands in each category
    print("\n" + "="*80)
    print("LARGE BRANDS (500+ POIs removed)")
    print("="*80)
    large_brands = summary.filter(pl.col("removed_poi_count") >= 500)
    print(large_brands)

    print("\n" + "="*80)
    print("MEDIUM BRANDS (100-499 POIs removed)")
    print("="*80)
    medium_brands = summary.filter(
        (pl.col("removed_poi_count") >= 100) &
        (pl.col("removed_poi_count") < 500)
    )
    print(medium_brands)

    # Interesting findings
    print("\n" + "="*80)
    print("KEY FINDINGS")
    print("="*80)

    # McColl's dominance
    mccolls = summary.filter(pl.col("Brand") == "McColl's")
    if len(mccolls) > 0:
        mccolls_count = mccolls.get_column("removed_poi_count").item()
        mccolls_pct = 100 * mccolls_count / total_removed
        print(f"• McColl's alone accounts for {mccolls_count:,} POIs ({mccolls_pct:.1f}% of all removed)")

    # Top 3 contribution
    top3_total = summary_sorted.head(3).select(pl.col("removed_poi_count").sum()).item()
    top3_pct = 100 * top3_total / total_removed
    print(f"• Top 3 brands account for {top3_total:,} POIs ({top3_pct:.1f}% of all removed)")

    # Long tail
    small_brands = summary.filter(pl.col("removed_poi_count") < 10)
    if len(small_brands) > 0:
        small_total = small_brands.select(pl.col("removed_poi_count").sum()).item()
        print(f"• {len(small_brands)} brands have <10 POIs each (total: {small_total:,} POIs)")

    print("\n" + "="*80)
    print("All detailed results saved to: data/POI_files/defunct_removed/")
    print("="*80)

if __name__ == "__main__":
    main()
