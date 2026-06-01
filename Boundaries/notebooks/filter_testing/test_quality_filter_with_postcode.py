#!/usr/bin/env python3
"""
Test the quality filter with postcode mismatch filter integrated.
"""

import polars as pl
import sys

sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare
from retail.foursquare_qualityfilter import filter_foursquare_quality


def main():
    print("="*80)
    print("TESTING QUALITY FILTER WITH POSTCODE MISMATCH")
    print("="*80)

    # Load raw POI data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/3] Loading raw POI data: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total raw POIs: {len(foursquare):,}")

    # Apply retail filter
    print(f"\n[2/3] Applying retail category filter...")
    print("="*80)
    foursquare = filter_foursquare(foursquare)
    print(f"After retail filter: {len(foursquare):,}")

    # Apply quality filters WITH postcode mismatch
    print(f"\n[3/3] Applying quality filters (including postcode mismatch)...")
    print("="*80)
    foursquare = filter_foursquare_quality(
        foursquare,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False,
        filter_defunct=True,
        save_defunct_removed=True,
        filter_duplicates=True,
        save_duplicates_removed=True,
        filter_business_changes=True,
        save_business_changes_removed=True,
        filter_foreign_addresses=True,
        save_foreign_addresses_removed=True,
        filter_postcode_mismatch=True,
        postcode_mismatch_threshold_m=1000.0,
        onspd_dir="data/input_files/onspd",
        save_postcode_mismatch_removed=True
    )

    print(f"\n{'='*80}")
    print("FINAL RESULTS")
    print(f"{'='*80}")
    print(f"Final POIs: {len(foursquare):,}")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
