#!/usr/bin/env python
"""
Apply quality and retail filters to Foursquare POI data and save output.
Order: quality filter first, then retail filter (matches main.py logic).
"""

import geopandas as gpd
import polars as pl
from pathlib import Path
import argparse

# Import filter functions
from retail import retailfilter
from retail import foursquare_qualityfilter


def apply_full_filters(input_path: str, output_path: str, save_quality_ids: bool = False):
    """Apply quality filter and retail filter to POI data (in that order)."""

    print(f"Loading base POI file from {input_path}...")
    foursquare_pl = pl.read_parquet(input_path)
    print(f"  Loaded {len(foursquare_pl)} POIs")

    # Stage 1: Quality filter
    print("\n" + "="*80)
    print("STAGE 1: Quality Filter")
    print("="*80)
    foursquare_filtered_pl = foursquare_qualityfilter.filter_foursquare_quality(
        foursquare_pl,
        save_filter_ids=save_quality_ids,
        filter_ids_path="data/POI_files/quality_filter_ids.parquet"
    )
    print(f"  After quality filter: {len(foursquare_filtered_pl)} POIs")
    print(f"  Removed: {len(foursquare_pl) - len(foursquare_filtered_pl)} POIs")


    # Stage 2: Retail filter
    print("\n" + "="*80)
    print("STAGE 2: Retail Filter")
    print("="*80)
    foursquare_final = retailfilter.filter_foursquare(foursquare_filtered_pl)
    print(f"  After retail filter: {len(foursquare_final)} POIs")
    print(f"  Removed: {len(foursquare_filtered_pl) - len(foursquare_final)} POIs")

    # Save output
    print(f"\nSaving fully filtered POI file to {output_path}...")
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    foursquare_final.write_parquet(output_path)

    # Print summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Original POIs: {len(foursquare_pl):,}")
    print(f"After quality filter: {len(foursquare_filtered_pl):,}")
    print(f"After retail filter: {len(foursquare_final):,}")
    print(f"Total removed: {len(foursquare_pl) - len(foursquare_final):,}")
    print(f"Retention rate: {len(foursquare_final)/len(foursquare_pl)*100:.1f}%")
    print("\nSaved to:", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Apply retail and quality filters to Foursquare POI data"
    )
    parser.add_argument(
        "--input",
        default="data/input_files/uk_foursquare_cc_nov_iceberg.parquet",
        help="Path to input POI file (default: uk_foursquare_cc_nov_iceberg.parquet)"
    )
    parser.add_argument(
        "--output",
        default="data/input_files/uk_foursquare_cc_nov_iceberg_fullfiltered_geo.parquet",
        help="Path to output file (default: uk_foursquare_cc_nov_iceberg_fullfiltered_geo.parquet)"
    )
    parser.add_argument(
        "--save-quality-ids",
        action="store_true",
        help="Save quality filter IDs to quality_filter_ids.parquet"
    )

    args = parser.parse_args()

    apply_full_filters(args.input, args.output, args.save_quality_ids)
