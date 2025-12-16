#!/usr/bin/env python3
"""
Retail Landuse POI Filter

Filters retail landuse polygons based on POI counts before network generation.
This helps remove low-quality or sparse retail landuse areas that don't have
sufficient retail activity.
"""

import geopandas as gpd
import polars as pl
import pandas as pd
from pathlib import Path
from typing import Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def filter_retail_landuse_by_pois(
    foursquare: pl.DataFrame,
    min_pois_per_polygon: int = 1,
    retail_landuse_path: str = "data/input_files/retail_landuse.parquet",
    output_h3_path: Optional[str] = "data/input_files/retail_landuse_h3_geo.parquet",
    save_intermediates: bool = True
) -> pl.DataFrame:
    """
    Filter retail landuse polygons based on POI counts.

    Performs a spatial join between retail landuse polygons and Foursquare POIs,
    counts POIs per polygon, filters polygons with sufficient POIs, and converts
    to H3 cells.

    Args:
        foursquare: Polars DataFrame of Foursquare POIs with lat/lng columns
        min_pois_per_polygon: Minimum POIs required to keep a polygon (default: 1)
        retail_landuse_path: Path to retail landuse parquet file
        output_h3_path: Path to save filtered H3 cells (None to skip saving)
        save_intermediates: Whether to save intermediate filtered polygons

    Returns:
        Polars DataFrame of H3 cells from filtered retail landuse polygons
    """
    print("\n" + "="*80)
    print("FILTERING RETAIL LANDUSE BY POI COUNT")
    print("="*80)
    print(f"Minimum POIs per polygon: {min_pois_per_polygon}")
    print()

    # Load retail landuse polygons
    print(f"Loading retail landuse from: {retail_landuse_path}")
    retail_landuse = gpd.read_parquet(retail_landuse_path)
    print(f"  Loaded {len(retail_landuse):,} polygons")

    # Convert Foursquare to GeoDataFrame
    print("\nConverting Foursquare POIs to GeoDataFrame...")
    foursquare_pd = foursquare.to_pandas()
    foursquare_gdf = gpd.GeoDataFrame(
        foursquare_pd,
        geometry=gpd.points_from_xy(foursquare_pd['lng'], foursquare_pd['lat']),
        crs="EPSG:4326"
    )
    print(f"  {len(foursquare_gdf):,} POIs")

    # Ensure CRS match
    if retail_landuse.crs != foursquare_gdf.crs:
        retail_landuse = retail_landuse.to_crs(foursquare_gdf.crs)

    # Spatial join: POIs within polygons
    print("\nPerforming spatial join...")
    joined = gpd.sjoin(
        foursquare_gdf[['geometry']],
        retail_landuse,
        how='inner',
        predicate='within'
    )

    # Count POIs per polygon
    poi_counts = joined.groupby('index_right').size().rename('poi_count')
    print(f"  {len(poi_counts):,} polygons have POIs")

    # Filter polygons by POI count
    print(f"\nFiltering polygons with >= {min_pois_per_polygon} POIs...")
    polygons_to_keep = poi_counts[poi_counts >= min_pois_per_polygon].index
    filtered_landuse = retail_landuse.loc[polygons_to_keep].copy()
    filtered_landuse['poi_count'] = poi_counts.loc[polygons_to_keep]

    print(f"  Kept {len(filtered_landuse):,} / {len(retail_landuse):,} polygons")
    print(f"  Total POIs in kept polygons: {filtered_landuse['poi_count'].sum():,}")

    # Save intermediate filtered polygons if requested
    if save_intermediates:
        filtered_polygons_path = Path(retail_landuse_path).parent / "retail_landuse_filtered.parquet"
        filtered_landuse.to_parquet(filtered_polygons_path)
        print(f"\n  Saved filtered polygons: {filtered_polygons_path}")

    # Convert to H3 cells (returns DataFrame with h3_11 and landuse columns)
    print("\nConverting filtered polygons to H3 cells...")
    h3_cells_df = convert_polygons_to_h3(filtered_landuse)

    # Convert to Polars DataFrame
    h3_cells_pl = pl.from_pandas(h3_cells_df)

    print(f"  Generated {len(h3_cells_pl):,} H3 cells")

    # Save H3 cells if path provided
    if output_h3_path:
        output_path = Path(output_h3_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save as regular parquet (no geometry)
        h3_cells_df.to_parquet(output_path)
        print(f"\n  Saved H3 cells: {output_path}")

    print("\n" + "="*80)
    print("RETAIL LANDUSE FILTERING COMPLETE")
    print("="*80)

    return h3_cells_pl


def convert_polygons_to_h3(polygons: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Convert polygons to H3 cells at resolution 11 (via res13 parents).

    Matches the logic from grab_osm_landuse.py:
    - Uses resolution 13 for detailed coverage
    - Derives parent resolution 11 cells
    - Returns DataFrame (not GeoDataFrame)

    Args:
        polygons: GeoDataFrame of polygons to convert

    Returns:
        DataFrame with h3_11 and landuse columns (NO geometry)
    """
    import h3
    from tqdm import tqdm

    def get_h3_indices(geometry, resolution=13):
        """Get H3 cell indices covering a polygon."""
        if pd.isna(geometry) or geometry.is_empty:
            return set()

        if geometry.geom_type == 'Polygon':
            coords = [(lat, lng) for lng, lat in geometry.exterior.coords]
        elif geometry.geom_type == 'MultiPolygon':
            coords = []
            for poly in geometry.geoms:
                coords.extend([(lat, lng) for lng, lat in poly.exterior.coords])
        else:
            return set()

        try:
            poly = h3.LatLngPoly(coords)
            return h3.h3shape_to_cells(poly, res=resolution)
        except Exception:
            return set()

    # Get H3 indices at resolution 13 (detailed)
    print("  Computing H3 res13 cells...")
    tqdm.pandas(desc="H3 res13")
    polygons['h3_indices_res13'] = polygons['geometry'].progress_apply(
        lambda g: get_h3_indices(g, resolution=13)
    )

    # Drop polygons with no H3 coverage
    polygons = polygons[polygons['h3_indices_res13'].apply(len) > 0]

    # Derive parent resolution 11 cells
    print("  Deriving parent H3 res11 cells...")
    polygons['h3_indices_res11_parents'] = polygons['h3_indices_res13'].apply(
        lambda h3_cells: [h3.cell_to_parent(cell, 11) for cell in h3_cells]
    )

    # Explode to one row per H3 cell
    landuse_h3 = (
        polygons
        .explode('h3_indices_res11_parents')
        .rename(columns={'h3_indices_res11_parents': 'h3_11'})
        [['h3_11']]  # Keep only h3_11 column
        .drop_duplicates()
    )

    # Add landuse column
    landuse_h3['landuse'] = 'retail'

    print(f"    Final H3 cells: {len(landuse_h3):,}")

    return landuse_h3
