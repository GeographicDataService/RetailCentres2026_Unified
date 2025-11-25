#!/usr/bin/env python
"""
Script to create postworkshopcentres GPKG files and filtered POI geopackage.
Creates 4 variants:
1. postworkshopcentres.gpkg - with splits, with category_names
2. postworkshopcentres_nocatnames.gpkg - with splits, without category_names
3. postworkshopcentres_nosplits.gpkg - without splits (from 99999), with category_names
4. postworkshopcentres_nosplits_nocatnames.gpkg - without splits, without category_names

Also creates:
5. filtered_pois.gpkg - POI data with just name and full category
"""

import geopandas as gpd
import argparse
from pathlib import Path


def create_workshop_centres(
    split_centres_path: str,
    nosplit_centres_path: str,
    output_dir: str = "data/forarcgis"
):
    """Create 4 variants of postworkshopcentres GPKG files."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading centre files...")
    # Load centres with splits (splitthresh_1500)
    centres_split = gpd.read_parquet(split_centres_path)
    print(f"  Loaded {len(centres_split)} centres with splits")

    # Load centres without splits (splitthresh_99999)
    centres_nosplit = gpd.read_parquet(nosplit_centres_path)
    print(f"  Loaded {len(centres_nosplit)} centres without splits")

    # 1. postworkshopcentres.gpkg - with splits, with category_names
    print("\n1. Creating postworkshopcentres.gpkg (with splits, with category_names)...")
    centres_split.to_file(
        output_dir / "postworkshopcentres.gpkg",
        driver="GPKG",
        layer="postworkshopcentres"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres.gpkg'}")

    # 2. postworkshopcentres_nocatnames.gpkg - with splits, without category_names
    print("\n2. Creating postworkshopcentres_nocatnames.gpkg (with splits, no category_names)...")
    centres_split_nocat = centres_split.copy()
    if 'category_names' in centres_split_nocat.columns:
        centres_split_nocat = centres_split_nocat.drop(columns=['category_names'])
    centres_split_nocat.to_file(
        output_dir / "postworkshopcentres_nocatnames.gpkg",
        driver="GPKG",
        layer="postworkshopcentres_nocatnames"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres_nocatnames.gpkg'}")

    # 3. postworkshopcentres_nosplits.gpkg - without splits, with category_names
    print("\n3. Creating postworkshopcentres_nosplits.gpkg (no splits, with category_names)...")
    centres_nosplit.to_file(
        output_dir / "postworkshopcentres_nosplits.gpkg",
        driver="GPKG",
        layer="postworkshopcentres_nosplits"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres_nosplits.gpkg'}")

    # 4. postworkshopcentres_nosplits_nocatnames.gpkg - without splits, without category_names
    print("\n4. Creating postworkshopcentres_nosplits_nocatnames.gpkg (no splits, no category_names)...")
    centres_nosplit_nocat = centres_nosplit.copy()
    if 'category_names' in centres_nosplit_nocat.columns:
        centres_nosplit_nocat = centres_nosplit_nocat.drop(columns=['category_names'])
    centres_nosplit_nocat.to_file(
        output_dir / "postworkshopcentres_nosplits_nocatnames.gpkg",
        driver="GPKG",
        layer="postworkshopcentres_nosplits_nocatnames"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres_nosplits_nocatnames.gpkg'}")

    print("\nAll postworkshopcentres GPKG files created successfully!")


def create_filtered_pois(poi_path: str, output_dir: str = "data/forarcgis"):
    """Create filtered POI geopackage with just name and full category."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating filtered POI geopackage...")
    print(f"Loading POIs from {poi_path}...")
    pois = gpd.read_parquet(poi_path)
    print(f"  Loaded {len(pois)} POIs")

    # Keep only name and category columns
    columns_to_keep = ['name', 'geometry']

    # Determine which category column exists
    if 'fsq_category_labels' in pois.columns:
        columns_to_keep.append('fsq_category_labels')
        category_col = 'fsq_category_labels'
    elif 'fsq_category_ids' in pois.columns:
        columns_to_keep.append('fsq_category_ids')
        category_col = 'fsq_category_ids'
    elif 'fsq_category_id' in pois.columns:
        columns_to_keep.append('fsq_category_id')
        category_col = 'fsq_category_id'
    else:
        print("  Warning: No category column found, saving with name only")
        category_col = None

    # Select columns
    filtered_pois = pois[[col for col in columns_to_keep if col in pois.columns]].copy()

    # Rename category column to 'category'
    if category_col:
        filtered_pois = filtered_pois.rename(columns={category_col: 'category'})

    print(f"  Filtered to {len(filtered_pois)} POIs with columns: {list(filtered_pois.columns)}")

    # Save to GPKG
    output_path = output_dir / "filtered_pois.gpkg"
    filtered_pois.to_file(output_path, driver="GPKG", layer="filtered_pois")
    print(f"  Saved to {output_path}")

    print("\nFiltered POI geopackage created successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create postworkshopcentres GPKG files and filtered POI geopackage"
    )
    parser.add_argument(
        "--split-centres",
        required=True,
        help="Path to 4_finalcentres_las.parquet with splits (splitthresh_1500)"
    )
    parser.add_argument(
        "--nosplit-centres",
        required=True,
        help="Path to 4_finalcentres_las.parquet without splits (splitthresh_99999)"
    )
    parser.add_argument(
        "--pois",
        required=True,
        help="Path to filtered POI geoparquet file"
    )
    parser.add_argument(
        "--output-dir",
        default="data/forarcgis",
        help="Output directory (default: data/forarcgis)"
    )

    args = parser.parse_args()

    # Create workshopcentres files
    create_workshop_centres(
        args.split_centres,
        args.nosplit_centres,
        args.output_dir
    )

    # Create filtered POI file
    create_filtered_pois(args.pois, args.output_dir)

    print("\n" + "="*80)
    print("ALL FILES CREATED SUCCESSFULLY!")
    print("="*80)
