#!/usr/bin/env python3
"""
Landuse filtering module for retail centre networks.

Changes in this version:
- Commercial and industrial overlaps are computed SEPARATELY.
- Networks are removed based on (commercial_overlap + industrial_overlap).
- A SINGLE shared POI threshold is used.
"""

import geopandas as gpd
import pandas as pd
from multiprocessing import Pool, cpu_count
from dataclasses import dataclass
from typing import Tuple, Dict, Optional, List


@dataclass
class LanduseFilterResult:
    """Container for landuse filtering artefacts."""

    filtered: gpd.GeoDataFrame
    summary: pd.DataFrame
    removed_cells: gpd.GeoDataFrame
    overlap_details: pd.DataFrame
    removed_network_ids: List[int]
    exempt_network_ids: List[int]


# -----------------------------------------------------------------------------
# Helper: Compute overlap for *one* landuse type
# -----------------------------------------------------------------------------

def compute_single_overlap(args: Tuple) -> Dict:
    """
    Compute overlap for a single network for one landuse type.

    Args:
        args: (network_id, network_geom, landuse_gdf)

    Returns:
        { network_number, overlap_pct }
    """
    network_id, network_geom, landuse_gdf = args
    network_area = network_geom.area
    bounds = network_geom.bounds

    # Spatial index filter
    idx = list(landuse_gdf.sindex.intersection(bounds))
    if not idx:
        return {"network_number": network_id, "overlap_pct": 0.0}

    nearby = landuse_gdf.iloc[idx]
    landuse_union = nearby.union_all()

    intersection_area = network_geom.intersection(landuse_union).area
    pct = (intersection_area / network_area * 100.0) if network_area > 0 else 0.0

    return {"network_number": network_id, "overlap_pct": pct}


# -----------------------------------------------------------------------------
# Compute both overlaps in parallel
# -----------------------------------------------------------------------------

def compute_both_overlaps(
    centres_gdf: gpd.GeoDataFrame,
    commercial_gdf: gpd.GeoDataFrame,
    industrial_gdf: gpd.GeoDataFrame,
    num_workers: int = None
) -> pd.DataFrame:
    """
    Computes overlap for commercial and industrial separately.
    """

    if num_workers is None:
        num_workers = max(1, cpu_count() - 1)

    # Dissolve networks
    print("Dissolving networks...")
    networks = centres_gdf.dissolve(by="network_number", as_index=False)

    # Prepare args
    commercial_args = [
        (row.network_number, row.geometry, commercial_gdf)
        for _, row in networks.iterrows()
    ]
    industrial_args = [
        (row.network_number, row.geometry, industrial_gdf)
        for _, row in networks.iterrows()
    ]

    print(f"Computing overlaps using {num_workers} workers...")

    with Pool(num_workers) as pool:
        comm_results = pool.map(compute_single_overlap, commercial_args)
        ind_results = pool.map(compute_single_overlap, industrial_args)

    comm_df = pd.DataFrame(comm_results).rename(columns={"overlap_pct": "commercial_overlap"})
    ind_df = pd.DataFrame(ind_results).rename(columns={"overlap_pct": "industrial_overlap"})

    df = comm_df.merge(ind_df, on="network_number")
    df["total_overlap"] = df["commercial_overlap"] + df["industrial_overlap"]
    return df


# -----------------------------------------------------------------------------
# Main filtering function
# -----------------------------------------------------------------------------

def run_landuse_filter(
    centres: gpd.GeoDataFrame,
    commercial: gpd.GeoDataFrame,
    industrial: gpd.GeoDataFrame,
    overlap_threshold: float = 75.0,
    poi_threshold: Optional[int] = 20,
    source: str = "foursquare",
    num_workers: int = None
) -> LanduseFilterResult:
    """
    Filter networks based on TOTAL overlap = commercial + industrial.

    Rules:
    - If total_overlap ≥ threshold AND POIs < poi_threshold → REMOVE
    - If poi_threshold is None → REMOVE ALL networks with total_overlap ≥ threshold
    """

    print("\n" + "="*80)
    if poi_threshold is None:
        print(f"LANDUSE FILTER: total_overlap >= {overlap_threshold}%, NO POI EXEMPTION")
    else:
        print(f"LANDUSE FILTER: total_overlap >= {overlap_threshold}%, POI threshold = {poi_threshold}")
    print("="*80 + "\n")

    centres = centres.copy()
    commercial = commercial.copy()
    industrial = industrial.copy()

    # Ensure CRS match
    if commercial.crs != centres.crs:
        commercial = commercial.to_crs(centres.crs)
    if industrial.crs != centres.crs:
        industrial = industrial.to_crs(centres.crs)

    count_col = f"{source}_count"
    if count_col not in centres.columns:
        count_col = f"total_{source}_count"

    poi_df = centres.groupby("network_number")[count_col].sum().reset_index()
    poi_df.columns = ["network_number", "total_pois"]

    total_networks = centres.network_number.nunique()
    print(f"Total networks: {total_networks}")

    # 1) Compute overlaps
    overlap_df = compute_both_overlaps(centres, commercial, industrial, num_workers)
    overlap_df = overlap_df.merge(poi_df, on="network_number")

    # 2) Flag high-overlap networks
    high = overlap_df[overlap_df["total_overlap"] >= overlap_threshold]

    if poi_threshold is None:
        removed_ids = high.network_number.tolist()
        exempt_ids = []
    else:
        removed_ids = high[high["total_pois"] < poi_threshold].network_number.tolist()
        exempt_ids = high[high["total_pois"] >= poi_threshold].network_number.tolist()

    removed_cells = centres[centres.network_number.isin(removed_ids)]

    # 3) Filter centres
    filtered = centres[~centres.network_number.isin(removed_ids)]
    
    print("\n" + "="*80)
    print(f"TOTAL NETWORKS REMOVED: {len(removed_ids)}")
    print(f"TOTAL CELLS REMOVED: {len(centres) - len(filtered)}")
    print(f"REMAINING NETWORKS: {filtered.network_number.nunique()}")
    print("="*80 + "\n")

    # Summary
    summary = pd.DataFrame([{
        "overlap_threshold": overlap_threshold,
        "poi_threshold": poi_threshold,
        "total_networks": total_networks,
        "high_overlap_networks": len(high),
        "removed_networks": len(removed_ids),
        "exempt_networks": len(exempt_ids),
        "cells_removed": len(removed_cells)
    }])

    return LanduseFilterResult(
        filtered=filtered,
        summary=summary,
        removed_cells=removed_cells,
        overlap_details=overlap_df,
        removed_network_ids=removed_ids,
        exempt_network_ids=exempt_ids
    )


