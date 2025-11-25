#!/usr/bin/env python3
"""
Landuse filtering module for retail centre networks.

Filters networks based on overlap with commercial/industrial landuse polygons.
Networks with high overlap (>= threshold %) AND low POI counts (< min_pois) are removed.
If min_pois_exempt is None, ALL networks with high overlap are removed regardless of POI count.
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from multiprocessing import Pool, cpu_count
from typing import Tuple, Dict, List, Optional


def compute_network_overlap(args: Tuple) -> Dict:
    """
    Compute overlap for a single network (for parallel processing).

    Args:
        args: Tuple of (network_id, network_geom, landuse_gdf)

    Returns:
        Dict with network_number and overlap_pct
    """
    network_id, network_geom, landuse_gdf = args
    network_area = network_geom.area
    network_bounds = network_geom.bounds

    # Use spatial index to filter landuse polygons near this network
    possible_matches_idx = list(landuse_gdf.sindex.intersection(network_bounds))

    if not possible_matches_idx:
        return {'network_number': network_id, 'overlap_pct': 0.0}

    # Get nearby landuse polygons and compute union
    nearby_landuse = landuse_gdf.iloc[possible_matches_idx]
    landuse_union = nearby_landuse.union_all()

    # Compute intersection area
    intersection = network_geom.intersection(landuse_union)
    overlap_pct = (intersection.area / network_area * 100.0) if network_area > 0 else 0.0

    return {'network_number': network_id, 'overlap_pct': overlap_pct}


def compute_polygon_overlap_parallel(
    centres_gdf: gpd.GeoDataFrame,
    landuse_gdf: gpd.GeoDataFrame,
    num_workers: int = None
) -> pd.DataFrame:
    """
    Compute overlap percentage for each network using parallel processing.

    Args:
        centres_gdf: GeoDataFrame with retail centre cells (must have 'network_number' column)
        landuse_gdf: GeoDataFrame with landuse polygons
        num_workers: Number of parallel workers (default: cpu_count - 1)

    Returns:
        DataFrame with columns: network_number, overlap_pct
    """
    if num_workers is None:
        num_workers = max(1, cpu_count() - 1)

    # Ensure CRS match
    if centres_gdf.crs != landuse_gdf.crs:
        print(f"  Converting landuse CRS from {landuse_gdf.crs} to {centres_gdf.crs}...")
        landuse_gdf = landuse_gdf.to_crs(centres_gdf.crs)

    # Dissolve networks into single polygons
    print("  Dissolving networks into polygons...")
    network_geoms = centres_gdf.dissolve(by='network_number', as_index=False)[['network_number', 'geometry']]

    # Prepare arguments for parallel processing
    args_list = [
        (row['network_number'], row['geometry'], landuse_gdf)
        for _, row in network_geoms.iterrows()
    ]

    # Process in parallel
    print(f"  Computing overlap for {len(args_list)} networks using {num_workers} workers...")
    with Pool(num_workers) as pool:
        results = pool.map(compute_network_overlap, args_list)

    return pd.DataFrame(results)


def filter_centres_by_landuse(
    centres_path: str,
    commercial_path: str,
    industrial_path: str,
    overlap_threshold: float = 75.0,
    min_pois_exempt: Optional[int] = 20,
    source: str = "foursquare",
    num_workers: int = None
) -> Tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Filter retail centres by landuse overlap.

    Networks with >= overlap_threshold% overlap with commercial OR industrial landuse
    are removed. If min_pois_exempt is specified, networks with >= that many POIs are exempt.
    If min_pois_exempt is None, ALL high-overlap networks are removed regardless of POI count.

    Args:
        centres_path: Path to centres parquet file (e.g., 3_afterfill.parquet)
        commercial_path: Path to commercial landuse parquet
        industrial_path: Path to industrial landuse parquet
        overlap_threshold: Minimum overlap percentage to flag (default: 75.0)
        min_pois_exempt: Minimum POIs to exempt from removal, or None for no exemption (default: 20)
        source: POI source name for count column (default: "foursquare")
        num_workers: Number of parallel workers (default: cpu_count - 1)

    Returns:
        Tuple of (filtered_centres_gdf, summary_df)
    """
    print(f"\n{'='*80}")
    if min_pois_exempt is None:
        print(f"LANDUSE FILTER: overlap_threshold={overlap_threshold}%, NO POI EXEMPTION")
    else:
        print(f"LANDUSE FILTER: overlap_threshold={overlap_threshold}%, min_pois_exempt={min_pois_exempt}")
    print(f"{'='*80}\n")

    # Load data
    print("Loading centres...")
    centres_gdf = gpd.read_parquet(centres_path)

    print("Loading landuse data...")
    commercial_gdf = gpd.read_parquet(commercial_path)
    industrial_gdf = gpd.read_parquet(industrial_path)

    # Calculate POI counts per network
    count_col = f"{source}_count"
    if count_col not in centres_gdf.columns:
        count_col = f"total_{source}_count"

    network_pois = centres_gdf.groupby('network_number')[count_col].sum().reset_index()
    network_pois.columns = ['network_number', 'total_pois']

    total_networks = centres_gdf['network_number'].nunique()
    print(f"Total networks: {total_networks}")

    # Compute overlaps
    results = []

    for landuse_type, landuse_gdf in [('commercial', commercial_gdf), ('industrial', industrial_gdf)]:
        print(f"\nProcessing {landuse_type} landuse...")
        overlap_df = compute_polygon_overlap_parallel(centres_gdf, landuse_gdf, num_workers)
        overlap_df = overlap_df.merge(network_pois, on='network_number')

        # Find networks with high overlap
        high_overlap = overlap_df[overlap_df['overlap_pct'] >= overlap_threshold]

        # Split into removed and exempt based on POI threshold
        if min_pois_exempt is None:
            # No exemption - remove ALL high-overlap networks
            networks_removed = high_overlap['network_number'].tolist()
            networks_exempt = []
        else:
            # Exempt high-POI networks
            networks_removed = high_overlap[high_overlap['total_pois'] < min_pois_exempt]['network_number'].tolist()
            networks_exempt = high_overlap[high_overlap['total_pois'] >= min_pois_exempt]['network_number'].tolist()

        # Get cells for removed networks
        cells_removed = centres_gdf[centres_gdf['network_number'].isin(networks_removed)]

        print(f"  Networks with {overlap_threshold}%+ overlap: {len(high_overlap)}")
        if min_pois_exempt is None:
            print(f"    - Removed (all): {len(networks_removed)} networks, {len(cells_removed)} cells")
        else:
            print(f"    - Removed (POI < {min_pois_exempt}): {len(networks_removed)} networks, {len(cells_removed)} cells")
            print(f"    - Exempt (POI >= {min_pois_exempt}): {len(networks_exempt)} networks")

        results.append({
            'landuse_type': landuse_type,
            'overlap_threshold_pct': overlap_threshold,
            'min_pois_exempt': min_pois_exempt if min_pois_exempt is not None else 'None',
            'networks_total': total_networks,
            'networks_high_overlap': len(high_overlap),
            'networks_removed': len(networks_removed),
            'networks_exempt': len(networks_exempt),
            'cells_removed': len(cells_removed),
            'removed_network_ids': networks_removed
        })

    # Combine removal lists
    all_removed_networks = set()
    for result in results:
        all_removed_networks.update(result['removed_network_ids'])

    # Filter centres
    filtered_centres = centres_gdf[~centres_gdf['network_number'].isin(all_removed_networks)]

    print(f"\n{'='*80}")
    print(f"TOTAL NETWORKS REMOVED: {len(all_removed_networks)} ({len(all_removed_networks)/total_networks*100:.1f}%)")
    print(f"TOTAL CELLS REMOVED: {len(centres_gdf) - len(filtered_centres)}")
    print(f"REMAINING NETWORKS: {filtered_centres['network_number'].nunique()}")
    print(f"{'='*80}\n")

    # Create summary DataFrame
    summary_df = pd.DataFrame([{k: v for k, v in r.items() if k != 'removed_network_ids'} for r in results])

    return filtered_centres, summary_df


def apply_landuse_filter_to_output(
    save_folder: str,
    commercial_path: str,
    industrial_path: str,
    overlap_threshold: float = 75.0,
    min_pois_exempt: Optional[int] = 20,
    source: str = "foursquare",
    num_workers: int = None
) -> None:
    """
    Apply landuse filter to an existing generate_networks() output folder.

    Reads 3_afterfill.parquet, applies filter, and saves:
    - 3_afterfill_landuse_filtered.parquet (filtered cells)
    - landuse_filter_summary.csv (summary statistics)
    - removed_{commercial,industrial}_networks.parquet (removed network cells for inspection)

    Args:
        save_folder: Path to output folder (e.g., "data/output_files/run_name_...")
        commercial_path: Path to commercial landuse parquet
        industrial_path: Path to industrial landuse parquet
        overlap_threshold: Minimum overlap percentage to flag (default: 75.0)
        min_pois_exempt: Minimum POIs to exempt from removal, or None for no exemption (default: 20)
        source: POI source name (default: "foursquare")
        num_workers: Number of parallel workers (default: cpu_count - 1)
    """
    save_folder = Path(save_folder)
    input_file = save_folder / "3_afterfill.parquet"

    if not input_file.exists():
        print(f"ERROR: Input file not found: {input_file}")
        return

    # Apply filter
    filtered_centres, summary_df = filter_centres_by_landuse(
        centres_path=str(input_file),
        commercial_path=commercial_path,
        industrial_path=industrial_path,
        overlap_threshold=overlap_threshold,
        min_pois_exempt=min_pois_exempt,
        source=source,
        num_workers=num_workers
    )

    # Save filtered centres
    output_file = save_folder / "3_afterfill_landuse_filtered.parquet"
    filtered_centres.to_parquet(output_file)
    print(f"✓ Saved filtered centres to: {output_file}")

    # Save summary
    summary_file = save_folder / "landuse_filter_summary.csv"
    summary_df.to_csv(summary_file, index=False)
    print(f"✓ Saved summary to: {summary_file}")

    # Optionally save removed networks for inspection
    centres_gdf = gpd.read_parquet(input_file)
    removed_networks = set(centres_gdf['network_number'].unique()) - set(filtered_centres['network_number'].unique())

    if len(removed_networks) > 0:
        removed_cells = centres_gdf[centres_gdf['network_number'].isin(removed_networks)]
        removed_file = save_folder / "landuse_filter_removed_networks.parquet"
        removed_cells.to_parquet(removed_file)
        print(f"✓ Saved removed networks to: {removed_file}")
