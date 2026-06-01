#!/usr/bin/env python3
"""
Unified script to grab land use data from OpenStreetMap for the UK.

Supports:
- Retail land use (landuse=retail)
- Commercial land use (landuse=commercial)
- Industrial land use (landuse=industrial)
- All types simultaneously

Outputs for each land use type:
- <type>_landuse.parquet - Original OSM polygons
- <type>_landuse_h3.parquet - H3 cell IDs only (resolution 11)
- <type>_landuse_h3_geo.parquet - H3 cells with hexagon geometries (for main.py)

Usage:
    python src/grab_osm_landuse.py --landuse retail
    python src/grab_osm_landuse.py --landuse commercial
    python src/grab_osm_landuse.py --landuse industrial
    python src/grab_osm_landuse.py --landuse all
"""

import argparse
import pandas as pd
import geopandas as gpd
import h3
import osmnx as ox
from shapely.geometry import box
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def split_area(geometry, num_splits=4):
    """
    Split a geometry into a grid of smaller bounding boxes.

    Parameters:
    - geometry: Shapely geometry to split
    - num_splits: Number of splits per dimension (creates num_splits^2 pieces)

    Returns:
    - List of box geometries
    """
    minx, miny, maxx, maxy = geometry.bounds
    dx = (maxx - minx) / num_splits
    dy = (maxy - miny) / num_splits
    pieces = []
    for i in range(num_splits):
        for j in range(num_splits):
            pieces.append(box(
                minx + i * dx,
                miny + j * dy,
                minx + (i + 1) * dx,
                miny + (j + 1) * dy
            ))
    return pieces


def query_landuse(geom, landuse_type):
    """
    Query OSM for land use features within a geometry.

    Parameters:
    - geom: Shapely geometry to query within
    - landuse_type: Type of land use ("retail" or "commercial")

    Returns:
    - GeoDataFrame with polygon/multipolygon features, or None if error
    """
    tags = {"landuse": landuse_type}
    try:
        gdf = ox.features_from_polygon(geom, tags)
        # Keep only polygon/multipolygon features
        return gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])]
    except Exception as e:
        # Silently skip errors (often empty results)
        return None


def query_with_progress_concurrent(boundary_geometry, landuse_type, num_splits=10, max_workers=16):
    """
    Query OSM land use data in parallel with progress tracking.

    Parameters:
    - boundary_geometry: Shapely geometry defining the query area
    - landuse_type: Type of land use ("retail" or "commercial")
    - num_splits: Number of grid splits per dimension
    - max_workers: Number of parallel worker threads

    Returns:
    - GeoDataFrame with combined results
    """
    # Split the area into pieces
    pieces = split_area(boundary_geometry, num_splits=num_splits)

    # Query in parallel with progress tracking
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(query_landuse, piece, landuse_type) for piece in pieces]
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Querying {landuse_type} land use"):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as e:
                print(f"Error processing result: {e}")

    # Combine results
    if not results:
        raise ValueError(f"No {landuse_type} land use data found")

    combined_gdf = gpd.GeoDataFrame(pd.concat(results, ignore_index=True))
    return combined_gdf


def get_h3_indices(geometry, resolution=13):
    """
    Convert a polygon or multipolygon to H3 cell indices.

    Parameters:
    - geometry: Shapely Polygon or MultiPolygon
    - resolution: H3 resolution level

    Returns:
    - Set of H3 cell indices
    """
    if geometry.geom_type == 'Polygon':
        coords = [(lat, lng) for lng, lat in geometry.exterior.coords]
    elif geometry.geom_type == 'MultiPolygon':
        coords = []
        for poly in geometry.geoms:
            coords.extend([(lat, lng) for lng, lat in poly.exterior.coords])
    else:
        raise ValueError(f"Geometry type {geometry.geom_type} not supported")

    # Create H3 polygon and convert to cells
    poly = h3.LatLngPoly(coords)
    return h3.h3shape_to_cells(poly, res=resolution)


def convert_to_h3(landuse_gdf, landuse_type):
    """
    Convert land use polygons to H3 cells at resolution 11.

    Uses resolution 13 for detailed coverage, then derives parent resolution 11 cells.

    Parameters:
    - landuse_gdf: GeoDataFrame with land use polygons
    - landuse_type: Type of land use (for progress messages)

    Returns:
    - DataFrame with h3_11 and landuse columns
    """
    print(f"Converting {landuse_type} polygons to H3 cells...")

    # Get H3 indices at resolution 13 (detailed)
    tqdm.pandas(desc=f"Computing H3 res13 for {landuse_type}")
    landuse_gdf['h3_indices_res13'] = landuse_gdf['geometry'].progress_apply(
        get_h3_indices, resolution=13
    )

    # Drop very small polygons with no H3 coverage
    landuse_gdf = landuse_gdf[landuse_gdf['h3_indices_res13'].apply(len) > 0]

    # Derive parent resolution 11 cells from res13 cells
    print(f"Deriving parent H3 res11 cells for {landuse_type}...")
    landuse_gdf['h3_indices_res11_parents'] = landuse_gdf['h3_indices_res13'].apply(
        lambda h3_cells: [h3.cell_to_parent(cell, 11) for cell in h3_cells]
    )

    # Explode to one row per H3 cell
    landuse_h3 = (
        landuse_gdf
        .explode('h3_indices_res11_parents')
        .rename(columns={'h3_indices_res11_parents': 'h3_11'})
        .drop(columns=['h3_indices_res13', 'name', 'geometry'], errors='ignore')
        [['h3_11', 'landuse']]  # Keep only essential columns
        .drop_duplicates()
    )

    return landuse_h3


def grab_landuse_data(landuse_type, output_dir="data/input_files", num_splits=10, max_workers=16):
    """
    Grab land use data from OSM and save polygon and H3 versions.

    Parameters:
    - landuse_type: "retail", "commercial", or "both"
    - output_dir: Directory to save output files
    - num_splits: Number of grid splits for parallel querying
    - max_workers: Number of parallel workers
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Get UK boundary
    print("Loading UK boundary...")
    uk_boundary = ox.geocode_to_gdf("United Kingdom").geometry[0]

    # Determine which land use types to process
    if landuse_type == "all":
        landuse_types = ["retail", "commercial", "industrial"]
    else:
        landuse_types = [landuse_type]

    for lu_type in landuse_types:
        print(f"\n{'='*60}")
        print(f"Processing {lu_type.upper()} land use")
        print(f"{'='*60}")

        # Query OSM data
        print(f"Querying OSM for {lu_type} land use...")
        landuse_gdf = query_with_progress_concurrent(
            uk_boundary,
            lu_type,
            num_splits=num_splits,
            max_workers=max_workers
        )

        # Clip to UK boundary and clean
        print(f"Clipping {lu_type} data to UK boundary...")
        landuse_gdf = (
            gpd.clip(landuse_gdf, uk_boundary)
            [['geometry', 'landuse', 'name']]
            .drop_duplicates()
        )

        print(f"Found {len(landuse_gdf):,} {lu_type} land use polygons")

        # Save polygon version
        polygon_path = output_path / f"{lu_type}_landuse.parquet"
        print(f"Saving polygon data to {polygon_path}...")
        landuse_gdf.to_parquet(polygon_path)

        # Convert to H3 cells
        landuse_h3 = convert_to_h3(landuse_gdf, lu_type)

        print(f"Generated {len(landuse_h3):,} unique H3 cells (res 11)")

        # Save H3 version (without geometry)
        h3_path = output_path / f"{lu_type}_landuse_h3.parquet"
        print(f"Saving H3 data to {h3_path}...")
        landuse_h3.to_parquet(h3_path)

        # Save H3 version with hexagon geometries (for main.py)
        h3_geo_path = output_path / f"{lu_type}_landuse_h3_geo.parquet"
        print(f"Saving H3 with hexagon geometries to {h3_geo_path}...")

        # Import utils to use to_geoframe function
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from utils import utils as ut

        # Convert H3 cells to hexagon geometries
        landuse_h3_geo = ut.to_geoframe(landuse_h3)
        landuse_h3_geo.to_parquet(h3_geo_path)

        print(f"\n✓ {lu_type.upper()} land use processing complete")
        print(f"  Polygons: {polygon_path}")
        print(f"  H3 cells: {h3_path}")
        print(f"  H3 with geometry: {h3_geo_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Grab OSM land use data for the UK and convert to H3 cells"
    )
    parser.add_argument(
        "--landuse",
        type=str,
        choices=["retail", "commercial", "industrial", "all"],
        default="all",
        help="Land use type to grab: retail, commercial, industrial, or all (default: all)"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="data/input_files",
        help="Output directory for parquet files (default: data/input_files)"
    )
    parser.add_argument(
        "--num_splits",
        type=int,
        default=10,
        help="Number of grid splits per dimension (default: 10, creates 100 sub-areas)"
    )
    parser.add_argument(
        "--max_workers",
        type=int,
        default=16,
        help="Number of parallel worker threads (default: 16)"
    )

    args = parser.parse_args()

    print("="*60)
    print("OSM Land Use Data Grabber")
    print("="*60)
    print(f"Land use type: {args.landuse}")
    print(f"Output directory: {args.output_dir}")
    print(f"Grid splits: {args.num_splits}x{args.num_splits} = {args.num_splits**2} sub-areas")
    print(f"Max workers: {args.max_workers}")
    print("="*60)

    grab_landuse_data(
        landuse_type=args.landuse,
        output_dir=args.output_dir,
        num_splits=args.num_splits,
        max_workers=args.max_workers
    )

    print("\n" + "="*60)
    print("All processing complete!")
    print("="*60)


if __name__ == "__main__":
    main()
