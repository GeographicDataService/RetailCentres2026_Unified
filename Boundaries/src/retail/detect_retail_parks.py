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
import matplotlib.pyplot as plt
import re
from pathlib import Path
from typing import Tuple, Optional


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
    foursquare_pois_all: gpd.GeoDataFrame,
    predicate: str = "within"
) -> gpd.GeoDataFrame:
    """
    Compute retail park metrics for landuse polygons.

    Joins bigbox brand POIs and all POIs with retail landuse polygons,
    computes ratios, counts, and area metrics.

    Args:
        retail_landuse: GeoDataFrame of retail landuse polygons
        foursquare_pois_filtered: GeoDataFrame of bigbox brand POIs
        foursquare_pois_all: GeoDataFrame of ALL Foursquare POIs
        predicate: Spatial predicate for join ("within" or "intersects")

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
        predicate=predicate
    )

    # Spatial join: ALL POIs (for centre totals)
    joined_all = gpd.sjoin(
        foursquare_pois_all,
        retail_landuse,
        how="inner",
        predicate=predicate
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


def save_area_histogram(
    retail_parks: gpd.GeoDataFrame,
    hist_path: Path,
    bins: int = 30
) -> Optional[Path]:
    """Persist a histogram of park areas in square kilometres."""

    if retail_parks.empty or "area_sqkm" not in retail_parks.columns:
        return None

    area_values = retail_parks["area_sqkm"].replace([np.inf, -np.inf], np.nan).dropna()
    if area_values.empty:
        return None

    hist_path = Path(hist_path)
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    ax_full, ax_zoom = axes

    ax_full.hist(area_values, bins=bins, color="#2a9d8f", edgecolor="white")
    ax_full.set_title("Retail park area distribution (sqkm)")
    ax_full.set_xlabel("Area (sqkm)")
    ax_full.set_ylabel("Number of parks")
    ax_full.grid(axis="y", linestyle="--", alpha=0.4)

    small_values = area_values[area_values <= 0.05]
    if not small_values.empty:
        ax_zoom.hist(small_values, bins=max(5, min(bins, 20)), color="#e76f51", edgecolor="white")
        ax_zoom.set_xlim(0, 0.05)
        ax_zoom.grid(axis="y", linestyle="--", alpha=0.4)
    else:
        ax_zoom.text(0.5, 0.5, "No parks ≤ 0.05 sqkm", ha="center", va="center", fontsize=10)
        ax_zoom.set_xlim(0, 0.05)
        ax_zoom.set_ylim(0, 1)

    ax_zoom.set_title("Zoom: areas ≤ 0.05 sqkm")
    ax_zoom.set_xlabel("Area (sqkm)")

    for spine in ax_zoom.spines.values():
        spine.set_alpha(0.6)

    fig.tight_layout()
    fig.savefig(hist_path, dpi=150)
    plt.close(fig)

    return hist_path


def identify_retail_parks(
    retail_landuse_path: str,
    foursquare_pois_path: str,
    brands_csv_path: str,
    min_ratio: float = 0.05,
    min_matched_pois: int = 1,
    predicate: str = "within",
    output_path: Optional[str] = None,
    area_hist_path: Optional[str] = None
) -> gpd.GeoDataFrame:
    """
    Identify retail parks from retail landuse polygons based on bigbox brand presence.

    Args:
        retail_landuse_path: Path to retail landuse parquet (OSM retail polygons)
        foursquare_pois_path: Path to Foursquare POIs parquet
        brands_csv_path: Path to retail park brands CSV
        min_ratio: Minimum ratio of bigbox POIs to total POIs (default: 0.05 = 5%)
        min_matched_pois: Minimum number of bigbox brand POIs (default: 1)
        predicate: Spatial predicate ("within" or "intersects")
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
        foursquare_pois,
        predicate=predicate
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

    hist_path = area_hist_path
    if hist_path is None:
        if output_path:
            output_path_obj = Path(output_path)
            hist_path = output_path_obj.with_name(f"{output_path_obj.stem}_area_sqkm_hist.png")
        else:
            hist_path = Path("data/output_files/retail_parks_area_sqkm_hist.png")

    saved_hist = save_area_histogram(retail_parks, Path(hist_path))
    if saved_hist:
        print(f"Saved area histogram to: {saved_hist}")
        print()

    print("="*80)
    print()

    return retail_parks


def convert_retail_parks_to_h3(
    retail_parks_polygons: gpd.GeoDataFrame,
    output_h3_path: Optional[str] = None,
    output_polygons_path: Optional[str] = None
) -> Tuple[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Convert retail park polygons to H3 cells at resolution 11.

    Uses resolution 13 for detailed coverage, then derives parent resolution 11 cells.
    Returns both H3 cell DataFrame and dissolved polygon GeoDataFrame.

    Args:
        retail_parks_polygons: GeoDataFrame of retail park polygons
        output_h3_path: Optional path to save H3 cells parquet
        output_polygons_path: Optional path to save dissolved polygons parquet

    Returns:
        Tuple of (h3_cells_df, dissolved_polygons_gdf)
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

    # Save H3 cells if requested
    if output_h3_path:
        retail_parks_h3_geo.to_parquet(output_h3_path, index=False)
        print(f"Saved H3 cells to: {output_h3_path}")

    # Create dissolved polygons from H3 cells (for visualization)
    # Note: This requires loading retail centre cells to get H3 geometries
    # For now, just return the H3 cells and original polygons
    retail_parks_dissolved = retail_parks_polygons.copy()
    retail_parks_dissolved['park_id'] = range(len(retail_parks_dissolved))

    if output_polygons_path:
        retail_parks_dissolved.to_parquet(output_polygons_path)
        print(f"Saved polygons to: {output_polygons_path}")

    print("="*80)
    print()

    return retail_parks_h3_geo, retail_parks_dissolved


def main():
    """
    Main function for standalone testing.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect retail parks based on bigbox store brands"
    )
    parser.add_argument(
        "--retail_landuse",
        type=str,
        default="data/input_files/retail_landuse.parquet",
        help="Path to retail landuse parquet"
    )
    parser.add_argument(
        "--foursquare",
        type=str,
        default="data/input_files/uk_foursquare_cc_nov_iceberg_fullfiltered_geo.parquet",
        help="Path to Foursquare POIs parquet"
    )
    parser.add_argument(
        "--brands",
        type=str,
        default="data/input_files/bl_retail_parks_brands_deduped.csv",
        help="Path to retail park brands CSV"
    )
    parser.add_argument(
        "--min_ratio",
        type=float,
        default=0.05,
        help="Minimum ratio of bigbox to total POIs (default: 0.05 = 5%%)"
    )
    parser.add_argument(
        "--min_matched",
        type=int,
        default=1,
        help="Minimum number of bigbox POIs (default: 1)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/output_files/retail_parks_detected.parquet",
        help="Output path for detected retail parks (polygons)"
    )
    parser.add_argument(
        "--output_h3",
        type=str,
        default="data/output_files/retail_parks_h3_cells.parquet",
        help="Output path for retail parks H3 cells"
    )
    parser.add_argument(
        "--output_polygons",
        type=str,
        default="data/output_files/retail_parks_polygons.parquet",
        help="Output path for retail parks dissolved polygons"
    )
    parser.add_argument(
        "--output_hist",
        type=str,
        default="data/output_files/retail_parks_area_sqkm_hist.png",
        help="Output path for histogram of retail park areas (sqkm)"
    )
    parser.add_argument(
        "--predicate",
        type=str,
        default="within",
        choices=["within", "intersects"],
        help="Spatial predicate for POI-polygon join"
    )

    args = parser.parse_args()

    retail_parks = identify_retail_parks(
        retail_landuse_path=args.retail_landuse,
        foursquare_pois_path=args.foursquare,
        brands_csv_path=args.brands,
        min_ratio=args.min_ratio,
        min_matched_pois=args.min_matched,
        predicate=args.predicate,
        output_path=args.output,
        area_hist_path=args.output_hist
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
        output_h3_path=args.output_h3,
        output_polygons_path=args.output_polygons
    )


if __name__ == "__main__":
    main()
