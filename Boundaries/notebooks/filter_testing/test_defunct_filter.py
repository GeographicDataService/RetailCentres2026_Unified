#!/usr/bin/env python3
"""
Test script to run the defunct retailers filter and analyze removed POIs.
"""

import polars as pl
import sys
sys.path.insert(0, 'src')

from retail.foursquare_qualityfilter import filter_defunct_retailers

def main():
    print("="*80)
    print("DEFUNCT RETAILERS FILTER TEST")
    print("="*80)

    # Load Foursquare data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading Foursquare data from: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs loaded: {len(foursquare):,}")

    # Run the defunct filter with detailed output
    print("\n" + "="*80)
    print("RUNNING DEFUNCT RETAILERS FILTER")
    print("="*80)

    filtered = filter_defunct_retailers(
        foursquare,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=True,
        output_dir="data/POI_files/defunct_removed",
        top_n_brands=20  # Save top 20 brands for analysis
    )

    # Calculate statistics
    total_removed = len(foursquare) - len(filtered)
    removal_rate = 100 * total_removed / len(foursquare)

    print("\n" + "="*80)
    print("SUMMARY STATISTICS")
    print("="*80)
    print(f"Total POIs processed:     {len(foursquare):,}")
    print(f"POIs removed (defunct):   {total_removed:,}")
    print(f"POIs remaining:           {len(filtered):,}")
    print(f"Removal rate:             {removal_rate:.3f}%")

    # Additional analysis: Load and display the summary file
    print("\n" + "="*80)
    print("TOP 20 DEFUNCT BRANDS REMOVED")
    print("="*80)

    try:
        summary = pl.read_csv("data/POI_files/defunct_removed/defunct_removed_summary.csv")
        print(summary)

        # Calculate some stats
        total_in_top20 = summary.select(pl.col("removed_poi_count").sum()).item()
        pct_of_removed = 100 * total_in_top20 / total_removed if total_removed > 0 else 0

        print(f"\nTop 20 brands account for {total_in_top20:,} POIs ({pct_of_removed:.1f}% of all removed)")

        # Show distribution
        print("\n" + "="*80)
        print("REMOVAL DISTRIBUTION")
        print("="*80)

        if len(summary) >= 5:
            top5_total = summary.head(5).select(pl.col("removed_poi_count").sum()).item()
            print(f"Top 5 brands:  {top5_total:,} POIs ({100*top5_total/total_removed:.1f}% of removed)")

        if len(summary) >= 10:
            top10_total = summary.head(10).select(pl.col("removed_poi_count").sum()).item()
            print(f"Top 10 brands: {top10_total:,} POIs ({100*top10_total/total_removed:.1f}% of removed)")

        if len(summary) >= 20:
            top20_total = summary.head(20).select(pl.col("removed_poi_count").sum()).item()
            print(f"Top 20 brands: {top20_total:,} POIs ({100*top20_total/total_removed:.1f}% of removed)")

    except Exception as e:
        print(f"Could not load summary file: {e}")

    print("\n" + "="*80)
    print("OUTPUT FILES")
    print("="*80)
    print("Files saved to: data/POI_files/defunct_removed/")
    print("  - defunct_removed_summary.csv (brand statistics)")
    print("  - [Brand_Name].geo.parquet (individual brand GeoParquet files)")
    print("="*80)

if __name__ == "__main__":
    main()
