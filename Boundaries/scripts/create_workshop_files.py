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
6. retail_parks.gpkg - Retail park polygons with all attributes (optional)
7. centres_clean.gpkg - Clean centres with only RC_ID and category totals
8. retail_parks_clean.gpkg - Clean retail parks with name, ID, total POIs, matched brands, and match % (optional)
"""

import geopandas as gpd
import argparse
from pathlib import Path
from datetime import datetime
import re


def sanitize_column_names(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Sanitize column names for ArcGIS Online compatibility.

    Rules:
    - Must start with a letter
    - Only letters, numbers, and underscores
    - Replace all special characters and spaces with underscores
    - Max 64 characters
    """
    gdf = gdf.copy()

    rename_map = {}
    for col in gdf.columns:
        if col == 'geometry':
            continue

        # Replace special characters and spaces with underscores
        new_col = re.sub(r'[^a-zA-Z0-9_]', '_', col)

        # Remove leading/trailing spaces and underscores
        new_col = new_col.strip('_ ')

        # Ensure starts with letter
        if new_col and not new_col[0].isalpha():
            new_col = 'col_' + new_col

        # Remove consecutive underscores and clean up spaces around underscores
        new_col = re.sub(r'_+', '_', new_col)
        new_col = re.sub(r'\s+', ' ', new_col)  # Remove consecutive spaces

        # Truncate to 64 characters
        new_col = new_col[:64]

        if new_col != col:
            rename_map[col] = new_col
            print(f"  Renamed: '{col}' -> '{new_col}'")

    if rename_map:
        gdf = gdf.rename(columns=rename_map)

    return gdf


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

    # Sanitize column names for ArcGIS compatibility
    print("\nSanitizing column names for ArcGIS Online...")
    centres_split = sanitize_column_names(centres_split)
    centres_nosplit = sanitize_column_names(centres_nosplit)

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
    import pandas as pd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating filtered POI geopackage...")
    print(f"Loading POIs from {poi_path}...")

    # Try geopandas first, fall back to pandas if no geo metadata
    try:
        pois = gpd.read_parquet(poi_path)
    except ValueError:
        # Not a geoparquet, read with pandas and convert
        from shapely.geometry import Point
        pois_df = pd.read_parquet(poi_path)

        if 'geometry' in pois_df.columns:
            # Convert WKB to shapely geometry if needed
            from shapely import wkb
            pois_df['geometry'] = pois_df['geometry'].apply(lambda x: wkb.loads(bytes(x)) if x is not None else None)
            pois = gpd.GeoDataFrame(pois_df, geometry='geometry', crs='EPSG:4326')
        elif 'lat' in pois_df.columns and 'lng' in pois_df.columns:
            # Create geometry from lat/lng columns
            print("  Creating geometry from lat/lng columns...")
            geometry = [Point(lng, lat) for lng, lat in zip(pois_df['lng'], pois_df['lat'])]
            pois = gpd.GeoDataFrame(pois_df, geometry=geometry, crs='EPSG:4326')
        else:
            raise ValueError("POI file must have either a 'geometry' column or 'lat' and 'lng' columns")

    print(f"  Loaded {len(pois):,} POIs")

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

    # Sanitize column names
    filtered_pois = sanitize_column_names(filtered_pois)

    print(f"  Filtered to {len(filtered_pois)} POIs with columns: {list(filtered_pois.columns)}")

    # Save to GPKG
    output_path = output_dir / "filtered_pois.gpkg"
    filtered_pois.to_file(output_path, driver="GPKG", layer="filtered_pois")
    print(f"  Saved to {output_path}")

    print("\nFiltered POI geopackage created successfully!")


def create_retail_parks_gpkg(retail_parks_path: str, output_dir: str = "data/forarcgis"):
    """Create retail parks geopackage with all attributes."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating retail parks geopackage...")
    print(f"Loading retail parks from {retail_parks_path}...")
    retail_parks = gpd.read_parquet(retail_parks_path)
    print(f"  Loaded {len(retail_parks)} retail parks")

    # Sanitize column names for ArcGIS compatibility
    print("  Sanitizing column names for ArcGIS Online...")
    retail_parks = sanitize_column_names(retail_parks)

    # Save to GPKG
    output_path = output_dir / "retail_parks.gpkg"
    retail_parks.to_file(output_path, driver="GPKG", layer="retail_parks")
    print(f"  Saved to {output_path}")
    print(f"  Columns: {list(retail_parks.columns)}")

    print("\nRetail parks geopackage created successfully!")


def create_centres_clean(
    split_centres_path: str,
    output_dir: str = "data/forarcgis"
):
    """Create clean centres GPKG with only RC_ID and category totals."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating centres_clean.gpkg...")
    print(f"Loading centres from {split_centres_path}...")
    centres = gpd.read_parquet(split_centres_path)
    print(f"  Loaded {len(centres)} centres")

    # Map potential column name variations to desired output names
    column_mapping = {
        'Total Units': 'Total Units',
        'total_units': 'Total Units',
        'poi_count': 'Total Units',
        'Total_POI_count': 'Total Units',
        'Retail (total)': 'Retail (total)',
        'retail_total': 'Retail (total)',
        'Retail': 'Retail (total)',
        'Dining and Drinking (total)': 'Dining and Drinking (total)',
        'dining_drinking_total': 'Dining and Drinking (total)',
        'Dining and Drinking': 'Dining and Drinking (total)',
        'Leisure and Travel (total)': 'Leisure and Travel (total)',
        'leisure_travel_total': 'Leisure and Travel (total)',
        'Leisure & Travel': 'Leisure and Travel (total)',
        'Community and Health (total)': 'Community and Health (total)',
        'community_health_total': 'Community and Health (total)',
        'Community & Health': 'Community and Health (total)',
        'centre_type': 'Is Retail Park'
    }

    # Find which columns exist and build the clean dataframe
    cols_to_keep = ['RC_ID', 'geometry']
    rename_dict = {}

    for possible_col, standard_col in column_mapping.items():
        if possible_col in centres.columns:
            cols_to_keep.append(possible_col)
            if possible_col != standard_col:
                rename_dict[possible_col] = standard_col

    # Filter to just these columns
    centres_clean = centres[cols_to_keep].copy()

    # Rename to standard names
    if rename_dict:
        centres_clean = centres_clean.rename(columns=rename_dict)

    # Convert Is Retail Park to boolean: retail_park -> True, centre -> False
    if 'Is Retail Park' in centres_clean.columns:
        centres_clean['Is Retail Park'] = centres_clean['Is Retail Park'].map({
            'retail_park': True,
            'centre': False
        }).fillna(False)

    # Sanitize column names for ArcGIS
    centres_clean = sanitize_column_names(centres_clean)

    # Save to GPKG
    output_path = output_dir / "centres_clean.gpkg"
    centres_clean.to_file(output_path, driver="GPKG", layer="centres_clean")
    print(f"  Saved to {output_path}")
    print(f"  Columns: {list(centres_clean.columns)}")

    print("\nCentres clean geopackage created successfully!")


def create_retail_parks_clean(
    retail_parks_path: str,
    output_dir: str = "data/forarcgis"
):
    """Create clean retail parks GPKG with name, ID, total POIs, matched brands, and match percentage."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating retail_parks_clean.gpkg...")
    print(f"Loading retail parks from {retail_parks_path}...")
    retail_parks = gpd.read_parquet(retail_parks_path)
    print(f"  Loaded {len(retail_parks)} retail parks")

    # Map potential column name variations to desired output names
    column_mapping = {
        'name': 'Name',
        'Name': 'Name',
        'park_name': 'Name',
        'RC_ID': 'RC_ID',
        'id': 'RC_ID',
        'park_id': 'RC_ID',
        'centre_poi_total': 'Total POIs',
        'total_pois': 'Total POIs',
        'poi_count': 'Total POIs',
        'Total_POI_count': 'Total POIs',
        'matched_brand_list': 'Matched Brands',
        'matched_brands': 'Matched Brands',
        'Matched Brands': 'Matched Brands',
        'matched_pois': 'Matched Brands'
    }

    # Find which columns exist
    cols_to_keep = ['geometry']
    rename_dict = {}

    for possible_col, standard_col in column_mapping.items():
        if possible_col in retail_parks.columns:
            if possible_col not in cols_to_keep:
                cols_to_keep.append(possible_col)
            if possible_col != standard_col:
                rename_dict[possible_col] = standard_col

    # Also keep matched_to_centre_ratio for calculation
    if 'matched_to_centre_ratio' in retail_parks.columns:
        cols_to_keep.append('matched_to_centre_ratio')

    # Filter to just these columns
    retail_parks_clean = retail_parks[cols_to_keep].copy()

    # Calculate percentage column (ratio * 100, rounded to 1 decimal place)
    if 'matched_to_centre_ratio' in retail_parks_clean.columns:
        retail_parks_clean['Match Percentage'] = (retail_parks_clean['matched_to_centre_ratio'] * 100).round(1)
        retail_parks_clean = retail_parks_clean.drop(columns=['matched_to_centre_ratio'])

    # Rename to standard names
    if rename_dict:
        retail_parks_clean = retail_parks_clean.rename(columns=rename_dict)

    # Clean up Matched Brands column - remove "(X POIs)" text
    if 'Matched Brands' in retail_parks_clean.columns:
        import numpy as np

        def clean_brands(x):
            if x is None:
                return None
            # If it's a list or numpy array, clean each element
            if isinstance(x, (list, np.ndarray)):
                cleaned = [re.sub(r'\s*\(\d+\s+POIs?\)', '', str(brand)).strip() for brand in x]
                return ', '.join(cleaned)
            # If it's a string, clean it
            return re.sub(r'\s*\(\d+\s+POIs?\)', '', str(x)).strip()

        retail_parks_clean['Matched Brands'] = retail_parks_clean['Matched Brands'].apply(clean_brands)

    # Sanitize column names for ArcGIS
    retail_parks_clean = sanitize_column_names(retail_parks_clean)

    # Save to GPKG
    output_path = output_dir / "retail_parks_clean.gpkg"
    retail_parks_clean.to_file(output_path, driver="GPKG", layer="retail_parks_clean")
    print(f"  Saved to {output_path}")
    print(f"  Columns: {list(retail_parks_clean.columns)}")

    print("\nRetail parks clean geopackage created successfully!")


def auto_find_files(run_dir: Path):
    """
    Automatically find all necessary files from a run directory.

    Args:
        run_dir: Path to the run directory

    Returns:
        Dictionary with paths to: split_centres, nosplit_centres, pois, retail_parks
    """
    run_dir = Path(run_dir)

    if not run_dir.exists():
        raise ValueError(f"Run directory does not exist: {run_dir}")

    print(f"\nAuto-detecting files in: {run_dir}")
    print("=" * 80)

    # Find POI file (foursquare_filtered.parquet or similar)
    poi_candidates = list(run_dir.glob("*filtered*.parquet"))
    if not poi_candidates:
        raise ValueError(f"No filtered POI file found in {run_dir}")
    pois_path = poi_candidates[0]
    print(f"✓ POIs: {pois_path.name}")

    # Find split centres directory (splitthresh_1500)
    split_dirs = list(run_dir.glob("*splitthresh_1500*"))
    if not split_dirs:
        raise ValueError(f"No split centres directory (splitthresh_1500) found in {run_dir}")
    split_centres_path = split_dirs[0] / "4_finalcentres_las.parquet"
    if not split_centres_path.exists():
        raise ValueError(f"4_finalcentres_las.parquet not found in {split_dirs[0]}")
    print(f"✓ Split centres: {split_dirs[0].name}/4_finalcentres_las.parquet")

    # Find nosplit centres directory (splitthresh_99999 or splitthresh_9999999)
    nosplit_dirs = list(run_dir.glob("*splitthresh_9999*"))
    if not nosplit_dirs:
        raise ValueError(f"No nosplit centres directory (splitthresh_9999*) found in {run_dir}")
    nosplit_centres_path = nosplit_dirs[0] / "4_finalcentres_las.parquet"
    if not nosplit_centres_path.exists():
        raise ValueError(f"4_finalcentres_las.parquet not found in {nosplit_dirs[0]}")
    print(f"✓ Nosplit centres: {nosplit_dirs[0].name}/4_finalcentres_las.parquet")

    # Find retail parks (optional)
    retail_parks_path = None
    retail_parks_dir = run_dir / "retail_parks"
    if retail_parks_dir.exists():
        # Look for the merged_filtered version first, then merged, then regular
        retail_park_candidates = [
            retail_parks_dir / "retail_parks_polygons_merged_filtered.parquet",
            retail_parks_dir / "retail_parks_polygons_merged.parquet",
            retail_parks_dir / "retail_parks_polygons.parquet"
        ]
        for candidate in retail_park_candidates:
            if candidate.exists():
                retail_parks_path = candidate
                print(f"✓ Retail parks: retail_parks/{candidate.name}")
                break

    if not retail_parks_path:
        print("  (No retail parks found)")

    print("=" * 80 + "\n")

    return {
        "split_centres": str(split_centres_path),
        "nosplit_centres": str(nosplit_centres_path),
        "pois": str(pois_path),
        "retail_parks": str(retail_parks_path) if retail_parks_path else None
    }


if __name__ == "__main__":
    # Create timestamped output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output_dir = Path(f"data/forarcgis/workshop_{timestamp}")

    parser = argparse.ArgumentParser(
        description="Create postworkshopcentres GPKG files and filtered POI geopackage"
    )

    # New simplified interface - just provide run directory
    parser.add_argument(
        "--run-dir",
        help="Path to run directory (e.g., data/outputs/runs/final). Auto-detects all files."
    )

    # Original interface - provide individual files (backward compatible)
    parser.add_argument(
        "--split-centres",
        help="Path to 4_finalcentres_las.parquet with splits (splitthresh_1500)"
    )
    parser.add_argument(
        "--nosplit-centres",
        help="Path to 4_finalcentres_las.parquet without splits (splitthresh_99999)"
    )
    parser.add_argument(
        "--pois",
        help="Path to filtered POI geoparquet file"
    )
    parser.add_argument(
        "--retail-parks",
        required=False,
        help="Path to retail_parks_polygons.parquet (optional)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: timestamped folder in data/forarcgis)"
    )

    args = parser.parse_args()

    # Determine which mode to use
    if args.run_dir:
        # Auto-detect mode
        files = auto_find_files(args.run_dir)
        split_centres = files["split_centres"]
        nosplit_centres = files["nosplit_centres"]
        pois = files["pois"]
        retail_parks = files["retail_parks"]
    elif args.split_centres and args.nosplit_centres and args.pois:
        # Manual mode
        split_centres = args.split_centres
        nosplit_centres = args.nosplit_centres
        pois = args.pois
        retail_parks = args.retail_parks
    else:
        parser.error("Either --run-dir OR (--split-centres AND --nosplit-centres AND --pois) must be provided")

    # Use custom output dir if provided, otherwise use timestamped folder
    output_dir = args.output_dir if args.output_dir else str(default_output_dir)

    print("\n" + "="*80)
    print(f"Output directory: {output_dir}")
    print("="*80 + "\n")

    # Create workshopcentres files
    create_workshop_centres(
        split_centres,
        nosplit_centres,
        output_dir
    )

    # Create filtered POI file
    create_filtered_pois(pois, output_dir)

    # Create retail parks file (if provided)
    if retail_parks:
        create_retail_parks_gpkg(retail_parks, output_dir)

    # Create clean centres file (with only RC_ID and category totals)
    create_centres_clean(split_centres, output_dir)

    # Create clean retail parks file (if provided)
    if retail_parks:
        create_retail_parks_clean(retail_parks, output_dir)

    print("\n" + "="*80)
    print("ALL FILES CREATED SUCCESSFULLY!")
    print(f"Output directory: {output_dir}")
    print("="*80)
