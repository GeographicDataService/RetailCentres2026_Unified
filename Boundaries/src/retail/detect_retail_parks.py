#!/usr/bin/env python3
"""
Retail Park Detection Module

Identifies retail parks based on presence of bigbox store brands.
Retail parks are characterized by high ratios of bigbox brands (e.g., B&Q, Currys,
Pets at Home) relative to total POI counts.

This module is designed to run separately from the main retail centre workflow
and can be integrated to create distinct retail park boundaries.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import re
import h3
import networkx as nx
from pathlib import Path
from typing import Tuple, Optional, Dict, Set
from collections import defaultdict
from shapely.geometry import MultiPolygon


def brand_to_pattern(brand: str) -> str:
    """
    Convert a brand name into a whole-word regex pattern.

    Args:
        brand: Brand name string

    Returns:
        Regex pattern for whole-word matching (case-insensitive)
    """
    brand = str(brand).strip().lower()
    tokens = re.split(r"\s+", brand)
    return r"\b" + r"\s+".join(re.escape(t) for t in tokens if t) + r"\b"


def filter_pois_by_brands(
    foursquare_pois: gpd.GeoDataFrame,
    brands_list: pd.DataFrame,
    classic_only: bool = True
) -> gpd.GeoDataFrame:
    """
    Filter Foursquare POIs to only those matching bigbox retail park brands.

    Args:
        foursquare_pois: GeoDataFrame with Foursquare POIs (must have 'name' column)
        brands_list: DataFrame with brand list (columns: 'brand', 'classic')
        classic_only: Whether to filter to only "classic" retail park brands

    Returns:
        Filtered GeoDataFrame with matched POIs and matched_brand_text column
    """
    # Filter to classic brands if requested
    if classic_only and 'classic' in brands_list.columns:
        brands_df = brands_list[brands_list["classic"] == "yes"].copy()
    else:
        brands_df = brands_list.copy()

    # Build regex pattern from all brands
    brands = brands_df["brand"].dropna().astype(str).str.strip().str.lower().unique()
    brand_patterns = [brand_to_pattern(b) for b in brands if b]
    big_pattern = r"(?i)(" + "|".join(brand_patterns) + r")"  # (?i) = case-insensitive

    # Apply to Foursquare names
    name_series = foursquare_pois["name"].astype(str)
    mask = name_series.str.contains(big_pattern, regex=True, na=False)

    # Filtered POIs: only those where a full brand word/phrase occurs
    foursquare_pois_filtered = foursquare_pois[mask].copy()
    foursquare_pois_filtered["matched_brand_text"] = name_series[mask].str.extract(
        big_pattern, expand=False
    )
    foursquare_pois_filtered["matched_brand_norm"] = (
        foursquare_pois_filtered["matched_brand_text"].str.lower().str.strip()
    )

    return foursquare_pois_filtered


def compute_retail_park_metrics(
    retail_landuse: gpd.GeoDataFrame,
    foursquare_pois_filtered: gpd.GeoDataFrame,
    foursquare_pois_all: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Compute retail park metrics for landuse polygons.

    Joins bigbox brand POIs and all POIs with retail landuse polygons,
    computes ratios, counts, and area metrics.

    Args:
        retail_landuse: GeoDataFrame of retail landuse polygons
        foursquare_pois_filtered: GeoDataFrame of bigbox brand POIs
        foursquare_pois_all: GeoDataFrame of ALL Foursquare POIs

    Returns:
        retail_landuse GeoDataFrame with added columns:
        - matched_brand_count: number of UNIQUE bigbox brands (each brand counted once)
        - centre_poi_total: number of all POIs
        - matched_to_centre_ratio: ratio of unique brands to total POIs
        - matched_poi_list: list of matched brands with their POI counts
        - area_sqm, area_sqkm: polygon areas
        - area_per_matched_brand_sqm: area per unique bigbox brand
        - area_per_total_poi_sqm: area per total POI
    """
    # Ensure CRS alignment
    if retail_landuse.crs is None and foursquare_pois_all.crs is not None:
        retail_landuse = retail_landuse.set_crs(foursquare_pois_all.crs, allow_override=True)
    if retail_landuse.crs != foursquare_pois_all.crs:
        retail_landuse = retail_landuse.to_crs(foursquare_pois_all.crs)
    if foursquare_pois_filtered.crs != foursquare_pois_all.crs:
        foursquare_pois_filtered = foursquare_pois_filtered.to_crs(foursquare_pois_all.crs)

    # Spatial join: FILTERED POIs (for brand counts)
    joined_filtered = gpd.sjoin(
        foursquare_pois_filtered,
        retail_landuse,
        how="inner",
        predicate="within"
    )

    # Spatial join: ALL POIs (for centre totals)
    joined_all = gpd.sjoin(
        foursquare_pois_all,
        retail_landuse,
        how="inner",
        predicate="within"
    )

    # Count UNIQUE brands per polygon (not total POI count)
    # This ensures each brand is counted only once per park
    matched_counts = joined_filtered.groupby("index_right")["matched_brand_norm"].nunique()

    # Build ordered list of "brand (poi_count, unique)" per polygon
    # Group by polygon and brand, count POIs per brand
    brand_poi_counts = (
        joined_filtered.groupby(["index_right", "matched_brand_norm"])
        .size()
        .reset_index(name="poi_count")
    )

    # Create display list: "Brand (N POIs)"
    poi_lists = (
        brand_poi_counts
        .sort_values(["index_right", "poi_count", "matched_brand_norm"], ascending=[True, False, True])
        .groupby("index_right", group_keys=False)
        .apply(lambda df: [f"{row['matched_brand_norm']} ({row['poi_count']} POIs)" for _, row in df.iterrows()])
    )

    # Centre totals from FULL set
    centre_totals = joined_all.groupby("index_right").size().astype(int)

    # Add metrics to retail_landuse
    retail_landuse["matched_brand_count"] = (
        retail_landuse.index.to_series().map(matched_counts).fillna(0).astype(int)
    )
    retail_landuse["matched_brand_list"] = (
        retail_landuse.index.to_series().map(poi_lists).apply(
            lambda x: x if isinstance(x, list) else []
        )
    )
    retail_landuse["centre_poi_total"] = (
        retail_landuse.index.to_series().map(centre_totals).fillna(0).astype(int)
    )
    retail_landuse["matched_to_centre_ratio"] = np.where(
        retail_landuse["centre_poi_total"] > 0,
        retail_landuse["matched_brand_count"] / retail_landuse["centre_poi_total"],
        0.0
    )

    # Compute polygon areas
    try:
        area_crs = retail_landuse.estimate_utm_crs()
    except Exception:
        area_crs = "EPSG:3857"  # Fallback to Web Mercator

    retail_landuse_area = retail_landuse.to_crs(area_crs)
    area_sqm = retail_landuse_area.geometry.area

    retail_landuse["area_sqm"] = area_sqm
    retail_landuse["area_sqkm"] = retail_landuse["area_sqm"] / 1_000_000.0

    # Area per matched brand
    retail_landuse["area_per_matched_brand_sqm"] = np.where(
        retail_landuse["matched_brand_count"] > 0,
        retail_landuse["area_sqm"] / retail_landuse["matched_brand_count"],
        np.nan
    )
    retail_landuse["area_per_matched_brand_sqkm"] = (
        retail_landuse["area_per_matched_brand_sqm"] / 1_000_000.0
    )

    # Area per total POI
    retail_landuse["area_per_total_poi_sqm"] = np.where(
        retail_landuse["centre_poi_total"] > 0,
        retail_landuse["area_sqm"] / retail_landuse["centre_poi_total"],
        np.nan
    )
    retail_landuse["area_per_total_poi_sqkm"] = (
        retail_landuse["area_per_total_poi_sqm"] / 1_000_000.0
    )

    # Reorder columns
    cols_front = [
        "matched_brand_count",
        "centre_poi_total",
        "matched_to_centre_ratio",
        "matched_brand_list",
        "area_sqm",
        "area_sqkm",
        "area_per_matched_brand_sqm",
        "area_per_total_poi_sqm",
    ]
    other_cols = [c for c in retail_landuse.columns if c not in cols_front + ["geometry"]]
    retail_landuse = retail_landuse[cols_front + other_cols + ["geometry"]]

    return retail_landuse


def identify_retail_parks(
    retail_landuse_path: str,
    foursquare_pois_path: str,
    brands_csv_path: str,
    min_ratio: float = 0.05,
    min_matched_pois: int = 1,
    output_path: Optional[str] = None
) -> gpd.GeoDataFrame:
    """
    Identify retail parks from retail landuse polygons based on bigbox brand presence.

    Args:
        retail_landuse_path: Path to retail landuse parquet (OSM retail polygons)
        foursquare_pois_path: Path to Foursquare POIs parquet
        brands_csv_path: Path to retail park brands CSV
        min_ratio: Minimum ratio of bigbox POIs to total POIs (default: 0.05 = 5%)
        min_matched_pois: Minimum number of bigbox brand POIs (default: 1)
        output_path: Optional path to save results as parquet

    Returns:
        GeoDataFrame of identified retail parks with metrics
    """
    print("="*80)
    print("RETAIL PARK DETECTION")
    print("="*80)
    print()

    # Load data
    print("Loading data...")
    retail_landuse = gpd.read_parquet(retail_landuse_path)

    # Load Foursquare POIs - handle both GeoParquet and regular parquet
    try:
        foursquare_pois = gpd.read_parquet(foursquare_pois_path)
    except ValueError:
        # Not a GeoParquet - load as regular parquet and create geometry
        foursquare_pois_df = pd.read_parquet(foursquare_pois_path)
        from shapely.geometry import Point

        # Use lat/lng columns (lowercase preferred)
        lat_col = 'lat' if 'lat' in foursquare_pois_df.columns else 'LAT'
        lng_col = 'lng' if 'lng' in foursquare_pois_df.columns else 'LONG'

        geometry = [Point(lng, lat) for lng, lat in
                   zip(foursquare_pois_df[lng_col], foursquare_pois_df[lat_col])]
        foursquare_pois = gpd.GeoDataFrame(
            foursquare_pois_df,
            geometry=geometry,
            crs="EPSG:4326"
        )

    brands_list = pd.read_csv(brands_csv_path)

    print(f"  Retail landuse polygons: {len(retail_landuse):,}")
    print(f"  Foursquare POIs: {len(foursquare_pois):,}")
    print(f"  Brands in list: {len(brands_list):,}")
    print()

    # Filter POIs by brands
    print("Filtering POIs by bigbox brands...")
    foursquare_pois_filtered = filter_pois_by_brands(
        foursquare_pois, brands_list, classic_only=True
    )
    print(f"  Matched POIs: {len(foursquare_pois_filtered):,}")
    print()

    # Compute metrics
    print("Computing retail park metrics...")
    retail_landuse = compute_retail_park_metrics(
        retail_landuse,
        foursquare_pois_filtered,
        foursquare_pois
    )
    print()

    # Filter to retail parks
    print(f"Filtering to retail parks (ratio >= {min_ratio}, matched brands >= {min_matched_pois})...")
    retail_parks = retail_landuse[
        (retail_landuse["matched_to_centre_ratio"] >= min_ratio) &
        (retail_landuse["matched_brand_count"] >= min_matched_pois)
    ].copy()

    # Sort by ratio descending
    retail_parks = retail_parks.sort_values("matched_to_centre_ratio", ascending=False)
    retail_parks = retail_parks.reset_index(drop=True)

    print(f"  Identified retail parks: {len(retail_parks):,}")
    print(f"  Total unique brands in parks: {retail_parks['matched_brand_count'].sum():,}")
    print(f"  Total POIs in parks: {retail_parks['centre_poi_total'].sum():,}")
    print(f"  Average ratio: {retail_parks['matched_to_centre_ratio'].mean():.2%}")
    print()

    # Save if requested
    if output_path:
        retail_parks.to_parquet(output_path)
        print(f"Saved retail parks to: {output_path}")
        print()

    print("="*80)
    print()

    return retail_parks


def merge_adjacent_parks(
    retail_parks_h3: pd.DataFrame,
    retail_parks_polygons: gpd.GeoDataFrame
) -> Tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Merge adjacent or overlapping retail parks.

    Updates both the H3 cells dataframe and the polygons dataframe to reflect merged parks.
    Polygons are grouped into MultiPolygons with the same park_id.

    Args:
        retail_parks_h3: DataFrame with H3 cells (must have 'park_id' and 'h3_11' columns)
        retail_parks_polygons: GeoDataFrame with original park polygons (must have 'park_id' column)

    Returns:
        Tuple of (merged_h3_df, merged_polygons_gdf)
    """
    from tqdm import tqdm

    print("Merging adjacent/overlapping retail parks...")

    # Build reverse lookup: h3_cell -> set of park_ids containing it
    cell_to_parks: Dict[str, Set[int]] = defaultdict(set)
    for _, row in retail_parks_h3.iterrows():
        cell_to_parks[row['h3_11']].add(row['park_id'])

    # Build park_cells for later use
    park_cells: Dict[int, Set[str]] = defaultdict(set)
    for _, row in retail_parks_h3.iterrows():
        park_cells[row['park_id']].add(row['h3_11'])

    park_ids = list(park_cells.keys())
    n_parks_before = len(park_ids)

    # Find pairs of parks that are adjacent or overlapping (more efficient)
    adjacent_pairs_set = set()

    for park_id in tqdm(park_ids, desc="Finding adjacent parks"):
        cells = park_cells[park_id]

        # Check for overlapping parks (parks sharing cells)
        for cell in cells:
            other_parks = cell_to_parks[cell]
            for other_park in other_parks:
                if other_park != park_id:
                    # Add as sorted tuple to avoid duplicates
                    pair = tuple(sorted([park_id, other_park]))
                    adjacent_pairs_set.add(pair)

        # Check for adjacent parks (parks with neighboring cells)
        for cell in cells:
            neighbors = h3.grid_ring(cell, 1)
            for neighbor in neighbors:
                if neighbor in cell_to_parks:
                    for other_park in cell_to_parks[neighbor]:
                        if other_park != park_id:
                            pair = tuple(sorted([park_id, other_park]))
                            adjacent_pairs_set.add(pair)

    adjacent_pairs = list(adjacent_pairs_set)

    if not adjacent_pairs:
        print("  No adjacent/overlapping parks found")
        return retail_parks_h3.copy(), retail_parks_polygons.copy()

    print(f"  Found {len(adjacent_pairs)} adjacent/overlapping pairs")

    # Create a graph and find connected components
    G = nx.Graph(adjacent_pairs)

    # Create mapping: old park_id -> new park_id (smallest in component)
    park_id_mapping = {}
    for component in nx.connected_components(G):
        new_id = min(component)
        for park_id in component:
            park_id_mapping[park_id] = new_id

    # Add unmapped parks (those that weren't in any pair)
    for park_id in park_ids:
        if park_id not in park_id_mapping:
            park_id_mapping[park_id] = park_id

    # Update H3 cells dataframe
    retail_parks_h3_merged = retail_parks_h3.copy()
    retail_parks_h3_merged['park_id'] = retail_parks_h3_merged['park_id'].map(park_id_mapping)

    # Update polygons: group by new park_id and create MultiPolygons
    retail_parks_polygons_merged = retail_parks_polygons.copy()
    retail_parks_polygons_merged['park_id'] = retail_parks_polygons_merged['park_id'].map(park_id_mapping)

    # Group polygons by park_id and combine into MultiPolygons
    merged_polys = []
    park_groups = list(retail_parks_polygons_merged.groupby('park_id'))

    for park_id, group in tqdm(park_groups, desc="Merging polygons"):
        # Flatten geometries (extract Polygons from MultiPolygons)
        all_polygons = []
        for geom in group.geometry:
            if geom.geom_type == 'Polygon':
                all_polygons.append(geom)
            elif geom.geom_type == 'MultiPolygon':
                all_polygons.extend(list(geom.geoms))

        # Create merged geometry
        if len(all_polygons) == 1:
            merged_geom = all_polygons[0]
        else:
            merged_geom = MultiPolygon(all_polygons)

        # Aggregate other columns (take first value or sum as appropriate)
        merged_row = group.iloc[0].copy()
        merged_row['geometry'] = merged_geom
        merged_row['park_id'] = park_id

        # Combine names from all merged parks
        if 'name' in group.columns:
            names = group['name'].dropna().unique()
            if len(names) > 0:
                merged_row['name'] = ', '.join(names)
            else:
                merged_row['name'] = None

        # Sum numeric columns
        if 'matched_brand_count' in group.columns:
            merged_row['matched_brand_count'] = group['matched_brand_count'].sum()
        if 'centre_poi_total' in group.columns:
            merged_row['centre_poi_total'] = group['centre_poi_total'].sum()
        if 'area_sqm' in group.columns:
            merged_row['area_sqm'] = group['area_sqm'].sum()
        if 'area_sqkm' in group.columns:
            merged_row['area_sqkm'] = group['area_sqkm'].sum()

        # Recalculate ratio
        if 'matched_to_centre_ratio' in merged_row.index:
            if merged_row['centre_poi_total'] > 0:
                merged_row['matched_to_centre_ratio'] = merged_row['matched_brand_count'] / merged_row['centre_poi_total']

        # Combine brand lists
        if 'matched_brand_list' in group.columns:
            all_brands = []
            for brand_list in group['matched_brand_list']:
                if isinstance(brand_list, list):
                    all_brands.extend(brand_list)
            merged_row['matched_brand_list'] = all_brands

        merged_polys.append(merged_row)

    retail_parks_polygons_merged = gpd.GeoDataFrame(merged_polys, crs=retail_parks_polygons.crs)

    # Map aggregated attributes from polygons to H3 cells
    print("  Mapping aggregated attributes to H3 cells...")

    # Create mapping from park_id to aggregated attributes
    attr_cols = ['name', 'matched_brand_count', 'centre_poi_total', 'matched_to_centre_ratio',
                 'matched_brand_list', 'area_sqm', 'area_sqkm']

    for col in attr_cols:
        if col in retail_parks_polygons_merged.columns and col in retail_parks_h3_merged.columns:
            park_attr_map = retail_parks_polygons_merged.set_index('park_id')[col].to_dict()
            retail_parks_h3_merged[col] = retail_parks_h3_merged['park_id'].map(park_attr_map)

    n_parks_after = retail_parks_polygons_merged['park_id'].nunique()
    print(f"  Parks before merge: {n_parks_before}")
    print(f"  Parks after merge: {n_parks_after}")
    print(f"  Parks merged: {n_parks_before - n_parks_after}")

    return retail_parks_h3_merged, retail_parks_polygons_merged


def convert_retail_parks_to_h3(
    retail_parks_polygons: gpd.GeoDataFrame,
    output_h3_path: Optional[str] = None,
    output_polygons_path: Optional[str] = None,
    merge_adjacent: bool = True,
    min_area_sqkm: float = 0.007
) -> Tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Convert retail park polygons to H3 cells at resolution 11.

    Uses resolution 13 for detailed coverage, then derives parent resolution 11 cells.
    Optionally merges adjacent/overlapping parks and filters by minimum area.
    Returns both H3 cell DataFrame and dissolved polygon GeoDataFrame.

    Args:
        retail_parks_polygons: GeoDataFrame of retail park polygons
        output_h3_path: Optional path to save H3 cells parquet (unmerged version)
        output_polygons_path: Optional path to save dissolved polygons parquet (unmerged version)
        merge_adjacent: If True, also creates and saves merged versions (default: True)
        min_area_sqkm: Minimum area in sqkm to keep parks after merging (default: 0.007)

    Returns:
        Tuple of (h3_cells_df, dissolved_polygons_gdf) - returns merged and filtered version if merge_adjacent=True
    """
    from tqdm import tqdm
    import h3

    def get_h3_indices(geometry, resolution=13):
        """Convert a polygon or multipolygon to H3 cell indices."""
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

    print("="*80)
    print("CONVERTING RETAIL PARKS TO H3 CELLS")
    print("="*80)
    print()

    # Add park_id
    retail_parks = retail_parks_polygons.copy()
    retail_parks['park_id'] = range(len(retail_parks))

    # Get H3 indices at resolution 13
    print("Computing H3 res13 cells...")
    tqdm.pandas(desc="H3 res13")
    retail_parks['h3_indices_res13'] = retail_parks['geometry'].progress_apply(
        get_h3_indices, resolution=13
    )

    # Drop parks with no H3 coverage
    parks_before = len(retail_parks)
    retail_parks = retail_parks[retail_parks['h3_indices_res13'].apply(len) > 0]
    print(f"  Parks with coverage: {len(retail_parks):,} (dropped {parks_before - len(retail_parks)} empty)")

    # Derive parent resolution 11 cells
    print("Deriving parent H3 res11 cells...")
    retail_parks['h3_indices_res11_parents'] = retail_parks['h3_indices_res13'].apply(
        lambda h3_cells: [h3.cell_to_parent(cell, 11) for cell in h3_cells]
    )

    # Explode to one row per H3 cell
    print("Exploding to cell-level data...")
    retail_parks_h3 = (
        retail_parks
        .explode('h3_indices_res11_parents')
        .rename(columns={'h3_indices_res11_parents': 'h3_11'})
        .drop(columns=['h3_indices_res13', 'geometry'], errors='ignore')
    )

    # Keep essential columns
    essential_cols = [
        'park_id', 'h3_11', 'matched_brand_count', 'centre_poi_total',
        'matched_to_centre_ratio', 'matched_brand_list', 'area_sqkm'
    ]
    retail_parks_h3 = retail_parks_h3[[col for col in essential_cols if col in retail_parks_h3.columns]]

    # Deduplicate
    before_dedup = len(retail_parks_h3)
    retail_parks_h3 = retail_parks_h3.drop_duplicates(subset=['park_id', 'h3_11'])
    print(f"  Before dedup: {before_dedup:,}")
    print(f"  After dedup: {len(retail_parks_h3):,}")

    # Add H3 hexagon geometries using utils function
    print("\nAdding H3 hexagon geometries...")
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils import utils as ut
    retail_parks_h3_geo = ut.to_geoframe(retail_parks_h3)

    # Statistics
    print("\nCell count statistics per park:")
    cells_per_park = retail_parks_h3_geo.groupby('park_id').size()
    print(f"  Total unique parks: {len(cells_per_park):,}")
    print(f"  Total H3 cells: {len(retail_parks_h3_geo):,}")
    print(f"  Min cells per park: {cells_per_park.min()}")
    print(f"  Max cells per park: {cells_per_park.max()}")
    print(f"  Mean cells per park: {cells_per_park.mean():.1f}")
    print(f"  Median cells per park: {cells_per_park.median():.1f}")
    single_cell = (cells_per_park == 1).sum()
    print(f"  Single-cell parks: {single_cell} ({single_cell/len(cells_per_park)*100:.1f}%)")
    print()

    # Prepare polygons with park_ids
    retail_parks_dissolved = retail_parks_polygons.copy()
    retail_parks_dissolved['park_id'] = range(len(retail_parks_dissolved))

    # Save unmerged versions (baseline)
    if output_h3_path:
        retail_parks_h3_geo.to_parquet(output_h3_path, index=False)
        print(f"Saved unmerged H3 cells to: {output_h3_path}")

    if output_polygons_path:
        retail_parks_dissolved.to_parquet(output_polygons_path)
        print(f"Saved unmerged polygons to: {output_polygons_path}")

    # Initialize final output with unmerged versions
    final_h3 = retail_parks_h3_geo
    final_polygons = retail_parks_dissolved

    # Apply merge if requested
    if merge_adjacent:
        print()
        retail_parks_h3_merged, retail_parks_polygons_merged = merge_adjacent_parks(
            retail_parks_h3_geo,
            retail_parks_dissolved
        )

        # Save merged versions
        if output_h3_path:
            merged_h3_path = output_h3_path.replace('.parquet', '_merged.parquet')
            retail_parks_h3_merged.to_parquet(merged_h3_path, index=False)
            print(f"Saved merged H3 cells to: {merged_h3_path}")

        if output_polygons_path:
            merged_polygons_path = output_polygons_path.replace('.parquet', '_merged.parquet')
            retail_parks_polygons_merged.to_parquet(merged_polygons_path)
            print(f"Saved merged polygons to: {merged_polygons_path}")

        # Update final output to merged versions
        final_h3 = retail_parks_h3_merged
        final_polygons = retail_parks_polygons_merged

    # Apply size filter if requested
    if min_area_sqkm > 0:
        print(f"\nApplying size filter ({min_area_sqkm} sqkm)...")

        # Filter current final output
        filter_mask = final_polygons['area_sqkm'] >= min_area_sqkm
        final_h3_filtered = final_h3[
            final_h3['park_id'].isin(final_polygons[filter_mask]['park_id'])
        ]
        final_polygons_filtered = final_polygons[filter_mask]

        # Save filtered versions
        suffix = '_merged_filtered' if merge_adjacent else '_filtered'

        if output_h3_path:
            filtered_h3_path = output_h3_path.replace('.parquet', f'{suffix}.parquet')
            final_h3_filtered.to_parquet(filtered_h3_path, index=False)
            print(f"  Saved filtered H3: {filtered_h3_path}")

        if output_polygons_path:
            filtered_polygons_path = output_polygons_path.replace('.parquet', f'{suffix}.parquet')
            final_polygons_filtered.to_parquet(filtered_polygons_path)
            print(f"  Saved filtered polygons: {filtered_polygons_path}")

        print(f"  Parks before filter: {len(final_polygons)}")
        print(f"  Parks after filter: {len(final_polygons_filtered)}")
        print(f"  Parks removed: {len(final_polygons) - len(final_polygons_filtered)}")

        # Update final output to filtered versions
        final_h3 = final_h3_filtered
        final_polygons = final_polygons_filtered

    # Single return with final processed output
    print("\n" + "="*80)
    print(f"Final output: {'merged' if merge_adjacent else 'unmerged'}, {'filtered' if min_area_sqkm > 0 else 'unfiltered'}")
    print(f"  Parks: {final_polygons['park_id'].nunique():,}")
    print(f"  H3 cells: {len(final_h3):,}")
    print("="*80)
    print()
    return final_h3, final_polygons


