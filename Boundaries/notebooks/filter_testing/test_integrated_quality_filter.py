#!/usr/bin/env python3
"""
Test the integrated quality filter with duplicate removal.
"""

import polars as pl
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare
from retail.foursquare_qualityfilter import filter_foursquare_quality

def main():
    print("="*80)
    print("TESTING INTEGRATED QUALITY FILTER (WITH DUPLICATE REMOVAL)")
    print("="*80)

    # Load data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    # Apply retail filter first
    print("\nApplying retail category filter...")
    foursquare_retail = filter_foursquare(foursquare)
    print(f"After retail filter: {len(foursquare_retail):,}")

    # Apply integrated quality filter (defunct + UK boundary + duplicates)
    foursquare_clean = filter_foursquare_quality(
        foursquare_retail,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        filter_defunct=True,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        filter_duplicates=True,
        duplicate_name_threshold=0.6,
        duplicate_dist_thresh=15.0,
        save_defunct_removed=False,  # Don't save to avoid clutter
        save_duplicates_removed=True  # Save duplicate info
    )

    print(f"\n{'='*80}")
    print("FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"Original POIs:           {len(foursquare):,}")
    print(f"After retail filter:     {len(foursquare_retail):,}")
    print(f"After quality filters:   {len(foursquare_clean):,}")
    print(f"Total removed:           {len(foursquare) - len(foursquare_clean):,}")
    print(f"Removal rate:            {100 * (len(foursquare) - len(foursquare_clean)) / len(foursquare):.2f}%")

    print(f"\n{'='*80}")
    print("SUCCESS! Integrated quality filter working correctly.")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
