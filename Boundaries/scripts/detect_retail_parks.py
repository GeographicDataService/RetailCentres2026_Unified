#!/usr/bin/env python
"""
Standalone script to detect retail parks based on bigbox store brands.

This script identifies retail parks from retail landuse polygons by analyzing
the presence of bigbox retail brands in POI data. It outputs:
1. Detected retail park polygons with metrics
2. H3 cell representation of retail parks
3. Merged and filtered retail park networks

For use in the main pipeline, retail park detection is integrated into main.py.
This script is for standalone analysis or custom parameter testing.
"""

import argparse
from datetime import datetime
from pathlib import Path

from retail.detect_retail_parks import identify_retail_parks, convert_retail_parks_to_h3
import config


def main():
    """
    Main function for standalone retail park detection.
    """
    # Create timestamped output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(f"data/output_files/retail_parks_{timestamp}")
    output_dir.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(
        description="Detect retail parks based on bigbox store brands"
    )
    parser.add_argument(
        "--retail_landuse",
        type=str,
        default=str(config.RETAIL_LANDUSE_POLYGONS_PATH),
        help="Path to retail landuse parquet"
    )
    parser.add_argument(
        "--foursquare",
        type=str,
        default=str(config.FOURSQUARE_PATH),
        help="Path to Foursquare POIs parquet"
    )
    parser.add_argument(
        "--brands",
        type=str,
        default=str(config.RETAIL_PARK_BRANDS_PATH),
        help="Path to retail park brands CSV"
    )
    parser.add_argument(
        "--min_ratio",
        type=float,
        default=config.RETAIL_PARK_MIN_RATIO,
        help=f"Minimum ratio of bigbox to total POIs (default: {config.RETAIL_PARK_MIN_RATIO})"
    )
    parser.add_argument(
        "--min_matched",
        type=int,
        default=config.RETAIL_PARK_MIN_MATCHED_POIS,
        help=f"Minimum number of bigbox POIs (default: {config.RETAIL_PARK_MIN_MATCHED_POIS})"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=None,
        help="Output directory (default: timestamped folder)"
    )

    args = parser.parse_args()

    # Use custom output dir if provided
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nOutput directory: {output_dir}\n")

    # Build output paths
    output_path = str(output_dir / "detected_retail_parks.parquet")
    output_hist = str(output_dir / "retail_parks_area_hist.png")
    output_h3 = str(output_dir / "retail_park_cells.parquet")
    output_polygons = str(output_dir / "retail_parks_polygons.parquet")

    retail_parks = identify_retail_parks(
        retail_landuse_path=args.retail_landuse,
        foursquare_pois_path=args.foursquare,
        brands_csv_path=args.brands,
        min_ratio=args.min_ratio,
        min_matched_pois=args.min_matched,
        output_path=output_path,
        area_hist_path=output_hist
    )

    # Print summary statistics
    print("TOP 20 RETAIL PARKS BY BIGBOX RATIO:")
    print("-" * 80)
    display_cols = ["matched_brand_count", "centre_poi_total", "matched_to_centre_ratio", "area_sqkm"]
    if "name" in retail_parks.columns:
        display_cols = ["name"] + display_cols

    print(retail_parks[display_cols].head(20).to_string(index=False))

    print("\n")
    convert_retail_parks_to_h3(
        retail_parks,
        output_h3_path=output_h3,
        output_polygons_path=output_polygons
    )

    print(f"\n✓ Retail park detection complete!")
    print(f"  Output directory: {output_dir}")


if __name__ == "__main__":
    main()
