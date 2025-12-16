#!/usr/bin/env python3
"""
Retail Park Integration - Workflow 3: Merge Small Remainders

Implements the "Merge to Parks" approach:
1. Load completed retail centres from main workflow
2. Detect retail parks (or load pre-detected)
3. Subtract retail park cells from centres
4. If remainder is below POI threshold, MERGE it into the retail park (not delete)
5. Output separate files for centres and parks

Key difference from previous: Small remainders are absorbed into parks
instead of being deleted.
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path
from typing import Tuple
import h3
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import utils as ut



def load_retail_centres(centres_path: str) -> gpd.GeoDataFrame:
    """
    Load retail centres from parquet file.

    Handles both cell-level (3_afterfill.parquet) and dissolved polygon-level
    (4_finalcentres.parquet) outputs.

    Args:
        centres_path: Path to retail centres parquet file

    Returns:
        GeoDataFrame with retail centres (must have h3_11 and network_number columns)
    """
    print(f"Loading retail centres from: {centres_path}")
    centres = gpd.read_parquet(centres_path)

    # Check for required columns
    if 'h3_11' not in centres.columns:
        raise ValueError(f"centres file must have 'h3_11' column. Found: {centres.columns.tolist()}")

    if 'network_number' not in centres.columns:
        raise ValueError(f"centres file must have 'network_number' column. Found: {centres.columns.tolist()}")

    print(f"  Loaded {len(centres):,} centre cells")
    print(f"  Unique networks: {centres['network_number'].nunique():,}")

    return centres


def get_retail_park_cells(
    retail_parks_input: gpd.GeoDataFrame,
    include_park_metadata: bool = True
) -> pd.DataFrame:
    """
    Get retail park H3 cells. Handles both:
    - Pre-computed H3 cells (has 'h3_11' column)
    - Retail park polygons (needs conversion to H3)

    Args:
        retail_parks_input: GeoDataFrame of either park cells or park polygons
        include_park_metadata: Whether to include park metadata in output

    Returns:
        DataFrame with h3_11 cells and optional park metadata
    """
    # Check if already H3 cells
    if 'h3_11' in retail_parks_input.columns and 'park_id' in retail_parks_input.columns:
        print("\nUsing pre-computed retail park H3 cells...")
        print(f"  Loaded {len(retail_parks_input):,} park cells")
        print(f"  Unique parks: {retail_parks_input['park_id'].nunique():,}")

        if include_park_metadata:
            return retail_parks_input
        else:
            return retail_parks_input[['h3_11', 'park_id']].copy()

    # Otherwise convert polygons to H3
    print("\nConverting retail parks to H3 cells...")
    from retail.detect_retail_parks import convert_retail_parks_to_h3

    retail_parks_h3, _ = convert_retail_parks_to_h3(
        retail_parks_input,
        output_h3_path=None,
        output_polygons_path=None
    )

    if include_park_metadata:
        return retail_parks_h3
    else:
        return retail_parks_h3[['h3_11', 'park_id']].copy()


def subtract_park_cells_from_centres(
    centres: gpd.GeoDataFrame,
    park_cells: pd.DataFrame,
    min_remainder_pois: int = 10,
    check_connectivity: bool = True
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Subtract retail park cells from retail centres.

    For each centre:
    - Remove cells that overlap with retail parks
    - Check if remainder meets minimum thresholds
    - If below threshold, MERGE remainder cells into adjacent park (Workflow 3 behavior)
    - Classify as: keep_centre, merge_to_park, or needs_review

    Args:
        centres: GeoDataFrame of retail centre cells
        park_cells: DataFrame of retail park H3 cells
        min_remainder_pois: Minimum POIs required to keep centre after subtraction
        check_connectivity: If True, split centres that become disconnected

    Returns:
        Tuple of (centres_kept, centres_merged_to_parks, summary_stats, updated_park_cells)
    """
    print("\n" + "="*80)
    print("SUBTRACTING RETAIL PARK CELLS FROM CENTRES (WORKFLOW 3: MERGE REMAINDERS)")
    print("="*80)

    # Get set of park cells for fast lookup
    park_cells_set = set(park_cells['h3_11'].unique())
    print(f"\nRetail park cells: {len(park_cells_set):,}")

    # Mark which centre cells overlap with parks AND track which park
    centres['is_park_cell'] = centres['h3_11'].isin(park_cells_set)

    # Create mapping of h3_11 -> park_id for cells that overlap
    h3_to_park_id = dict(zip(park_cells['h3_11'], park_cells['park_id']))
    centres['overlapping_park_id'] = centres['h3_11'].map(h3_to_park_id)

    overlap_count = centres['is_park_cell'].sum()
    print(f"Centre cells overlapping with parks: {overlap_count:,} ({overlap_count/len(centres)*100:.1f}%)")

    # Analyze by network
    print("\nAnalyzing centres network by network...")

    results = []
    centres_to_keep = []
    centres_to_merge = []  # Changed from centres_to_delete - these will be merged into parks

    for network_id, network_df in centres.groupby('network_number'):
        total_cells = len(network_df)
        park_cells_in_network = network_df['is_park_cell'].sum()
        non_park_cells = total_cells - park_cells_in_network

        # Get POI counts
        poi_col = 'retail_count' if 'retail_count' in network_df.columns else 'poi_count'
        if poi_col in network_df.columns:
            total_pois = network_df[poi_col].sum()
            park_pois = network_df[network_df['is_park_cell']][poi_col].sum()
            non_park_pois = total_pois - park_pois
        else:
            total_pois = non_park_pois = park_pois = None

        # Decision logic - WORKFLOW 3: Always split first, then check thresholds
        if park_cells_in_network == 0:
            decision = 'no_overlap'
            remainder_cells = network_df.copy()
            remainder_cells['reason'] = 'no_overlap'
            centres_to_keep.append(remainder_cells)

        elif non_park_cells == 0:
            decision = 'fully_park'
            # All cells already in parks - just track for stats
            network_copy = network_df.copy()
            network_copy['merge_reason'] = 'fully_park'
            centres_to_merge.append(network_copy)

        else:
            # ALWAYS split into connected components first (Workflow 3 logic)
            remainder_cells_only = network_df[~network_df['is_park_cell']].copy()

            if len(remainder_cells_only) == 0:
                # No cells remain after removing parks - merge into park
                decision = 'fully_park'
                network_copy = network_df.copy()
                network_copy['merge_reason'] = 'fully_park'
                centres_to_merge.append(network_copy)
            else:
                # Check if remainder is connected
                is_connected = check_network_connectivity(remainder_cells_only)

                if not is_connected:
                    # Split into components - will evaluate each component's POI threshold later
                    decision = 'split_fragmented'
                    remainder_cells_only['reason'] = 'needs_split'
                    centres_to_keep.append(remainder_cells_only)
                else:
                    # Still connected - check POI threshold for the whole remainder
                    if non_park_pois is not None and non_park_pois < min_remainder_pois:
                        decision = 'below_poi_threshold'
                        # Merge entire remainder into adjacent park
                        remainder_cells_only['merge_reason'] = 'below_poi_threshold'
                        centres_to_merge.append(remainder_cells_only)
                    else:
                        # Keep as centre
                        decision = 'keep'
                        remainder_cells_only['reason'] = 'sufficient_remainder'
                        centres_to_keep.append(remainder_cells_only)

        # Record results
        results.append({
            'network_number': network_id,
            'total_cells': total_cells,
            'park_cells': park_cells_in_network,
            'non_park_cells': non_park_cells,
            'total_pois': total_pois,
            'park_pois': park_pois,
            'non_park_pois': non_park_pois,
            'park_ratio': park_cells_in_network / total_cells if total_cells > 0 else 0,
            'decision': decision
        })

    # Combine results
    summary_df = pd.DataFrame(results)

    if centres_to_keep:
        centres_kept = pd.concat(centres_to_keep, ignore_index=True)
    else:
        centres_kept = gpd.GeoDataFrame(columns=centres.columns, crs=centres.crs)

    # Second pass: Split fragmented networks and evaluate components
    if check_connectivity and 'reason' in centres_kept.columns:
        needs_split = centres_kept[centres_kept['reason'] == 'needs_split'].copy()

        if len(needs_split) > 0:
            print(f"\nSplitting {needs_split['network_number'].nunique()} fragmented networks into components...")

            # Get starting ID for subnetworks
            max_network_id = centres['network_number'].max()
            starting_subnetwork_id = max_network_id + 100000

            split_results = []
            component_stats = []

            for network_id in needs_split['network_number'].unique():
                network_cells = needs_split[needs_split['network_number'] == network_id].copy()

                # Split into components
                split_network = split_into_connected_components(
                    network_cells,
                    network_id,
                    starting_subnetwork_id
                )

                # Add all components (threshold check comes later)
                for component_id in split_network['network_number'].unique():
                    component = split_network[split_network['network_number'] == component_id].copy()
                    component_cells = len(component)

                    # Get POI count
                    poi_col = 'retail_count' if 'retail_count' in component.columns else 'foursquare_count'
                    if poi_col in component.columns:
                        component_pois = component[poi_col].sum()
                    else:
                        component_pois = 0

                    # Add component without threshold check
                    component['reason'] = 'split_component'
                    split_results.append(component)

                    component_stats.append({
                        'original_network': network_id,
                        'component_id': component_id,
                        'cells': component_cells,
                        'pois': component_pois
                    })

                    starting_subnetwork_id += 1

            # Remove needs_split networks from centres_kept
            centres_kept = centres_kept[centres_kept['reason'] != 'needs_split'].copy()

            # Add split components that passed
            if split_results:
                centres_kept = pd.concat([centres_kept] + split_results, ignore_index=True)

            # Print component statistics
            comp_df = pd.DataFrame(component_stats)
            print(f"  Total components created: {len(comp_df)}")
            print(f"  Largest component: {comp_df['cells'].max()} cells, {comp_df['pois'].max()} POIs")

    if centres_to_merge:
        centres_merged = pd.concat(centres_to_merge, ignore_index=True)
    else:
        centres_merged = gpd.GeoDataFrame(columns=centres.columns, crs=centres.crs)

    # Final threshold check: Apply to ALL networks after splitting
    print("\n" + "="*80)
    print("FINAL THRESHOLD CHECK")
    print("="*80)

    poi_col = 'retail_count' if 'retail_count' in centres_kept.columns else 'foursquare_count'
    if poi_col not in centres_kept.columns:
        poi_col = 'foursquare_count'

    # Compute network-level statistics
    network_stats_final = centres_kept.groupby('network_number').agg({
        'h3_11': 'count',
        poi_col: 'sum'
    }).rename(columns={'h3_11': 'cell_count', poi_col: 'poi_count'})

    # Apply thresholds (CELL THRESHOLD REMOVED - only POI threshold applies)
    networks_below_poi_threshold = network_stats_final[network_stats_final['poi_count'] < min_remainder_pois].index
    networks_to_remove = set(networks_below_poi_threshold)

    if len(networks_to_remove) > 0:
        print(f"\nMerging {len(networks_to_remove)} networks that don't meet thresholds:")
        print(f"  Below POI threshold ({min_remainder_pois}): {len(networks_below_poi_threshold)}")

        # Move to merged (will be absorbed into parks)
        below_threshold_cells = centres_kept[centres_kept['network_number'].isin(networks_to_remove)].copy()
        below_threshold_cells['merge_reason'] = 'below_poi_threshold_post_split'
        centres_merged = pd.concat([centres_merged, below_threshold_cells], ignore_index=True)

        # Remove from kept
        centres_kept = centres_kept[~centres_kept['network_number'].isin(networks_to_remove)].copy()

        print(f"  Merged {len(below_threshold_cells):,} cells from {len(networks_to_remove)} networks into parks")
    else:
        print("\n✓ All networks meet thresholds")

    print(f"\nFinal network count: {centres_kept['network_number'].nunique():,}")
    print(f"Final cell count: {len(centres_kept):,}")

    # Print summary
    print("\n" + "-"*80)
    print("DECISION SUMMARY:")
    print("-"*80)
    print(summary_df['decision'].value_counts().to_string())
    print()
    print(f"Centres kept: {summary_df[summary_df['decision'] == 'keep'].shape[0]:,}")
    merged_count = summary_df[~summary_df['decision'].isin(['keep', 'no_overlap', 'split_fragmented'])].shape[0]
    print(f"Centres merged to parks: {merged_count:,}")
    print(f"  - Fully park: {summary_df[summary_df['decision'] == 'fully_park'].shape[0]:,}")
    print(f"  - Below POI threshold: {summary_df[summary_df['decision'] == 'below_poi_threshold'].shape[0]:,}")
    if check_connectivity:
        print(f"  - Split & evaluated: {summary_df[summary_df['decision'] == 'split_fragmented'].shape[0]:,}")
    print()

    # Merge remainder cells into parks
    print("\n" + "="*80)
    print("MERGING REMAINDER CELLS INTO PARKS")
    print("="*80)

    updated_park_cells = park_cells.copy()

    if len(centres_merged) > 0:
        # Get non-park cells from merged centres (the remainders to merge)
        remainder_to_merge = centres_merged[~centres_merged['is_park_cell']].copy()

        if len(remainder_to_merge) > 0:
            print(f"\nMerging {len(remainder_to_merge):,} remainder cells into parks")

            # Form networks and assign each network to adjacent park
            # Use ORIGINAL park_cells for adjacency detection
            merged_cells = assign_networks_to_parks(remainder_to_merge, park_cells)

            # Add to park_cells
            updated_park_cells = pd.concat([updated_park_cells, merged_cells], ignore_index=True)

            print(f"Updated park cells: {len(updated_park_cells):,} (added {len(merged_cells):,})")
            print(f"Updated park count: {updated_park_cells['park_id'].nunique():,}")
        else:
            print("\nNo remainder cells to merge (all merged centres were fully within parks)")
    else:
        print("\nNo centres to merge")

    return centres_kept, centres_merged, summary_df, updated_park_cells


def assign_networks_to_parks(
    remainder_cells: gpd.GeoDataFrame,
    park_cells: pd.DataFrame
) -> pd.DataFrame:
    """
    Form networks from connected remainder cells, then assign each network to adjacent park.

    Args:
        remainder_cells: GeoDataFrame of cells to merge into parks
        park_cells: DataFrame of existing park cells with park_id

    Returns:
        DataFrame of remainder cells with park_id assigned
    """
    import h3
    from collections import Counter

    if len(remainder_cells) == 0:
        return pd.DataFrame(columns=['h3_11', 'park_id'])

    print(f"  Forming networks from {len(remainder_cells):,} remainder cells...")

    # Convert to Polars DataFrame for create_networks
    import polars as pl
    remainder_df = pl.from_pandas(pd.DataFrame(remainder_cells.drop(columns='geometry')))
    remainder_with_networks = ut.create_networks(remainder_df)

    # Convert back to pandas if needed
    if hasattr(remainder_with_networks, 'to_pandas'):
        remainder_with_networks = remainder_with_networks.to_pandas()

    num_networks = remainder_with_networks['network_number'].nunique()
    print(f"  Found {num_networks:,} connected networks")

    # Create mapping of h3_11 -> park_id for fast lookup
    park_cell_to_park_id = dict(zip(park_cells['h3_11'], park_cells['park_id']))

    # For each network, find adjacent park
    assigned_cells = []

    for network_id, network_df in remainder_with_networks.groupby('network_number'):
        cells_in_network = set(network_df['h3_11'])

        # Find all parks adjacent to any cell in this network
        adjacent_parks = []
        for cell in cells_in_network:
            neighbors = h3.grid_ring(cell, 1)
            for neighbor in neighbors:
                if neighbor in park_cell_to_park_id:
                    adjacent_parks.append(park_cell_to_park_id[neighbor])

        if adjacent_parks:
            # Assign to most common adjacent park
            most_common_park = Counter(adjacent_parks).most_common(1)[0][0]
            assigned_park_id = most_common_park
        else:
            print(f"  Warning: Network {network_id} ({len(cells_in_network)} cells) has no adjacent park - using fallback")
            # Sample some cells for debugging
            sample_cells = list(cells_in_network)[:3]
            print(f"    Sample cells: {sample_cells}")
            # Use first park as fallback
            assigned_park_id = park_cells['park_id'].iloc[0] if len(park_cells) > 0 else 0

        # Assign this park_id to all cells in network
        for _, row in network_df.iterrows():
            cell_data = {
                'h3_11': row['h3_11'],
                'park_id': assigned_park_id
            }

            # Copy over POI counts if available
            poi_cols = ['retail_count', 'poi_count', 'foursquare_count', 'centre_poi_total']
            for col in poi_cols:
                if col in network_df.columns:
                    cell_data[col] = row[col]

            assigned_cells.append(cell_data)

    return pd.DataFrame(assigned_cells)


def check_network_connectivity(network_cells: pd.DataFrame) -> bool:
    """
    Check if network cells form a connected component.

    Args:
        network_cells: DataFrame with h3_11 column

    Returns:
        True if cells are connected, False if fragmented
    """
    if len(network_cells) <= 1:
        return True

    # Build adjacency graph
    import networkx as nx
    G = nx.Graph()

    cells = network_cells['h3_11'].unique()
    for cell in cells:
        G.add_node(cell)
        # Get neighbors
        neighbors = h3.grid_ring(cell, 1)
        for neighbor in neighbors:
            if neighbor in cells:
                G.add_edge(cell, neighbor)

    # Check if connected
    return nx.is_connected(G)


def split_into_connected_components(
    network_cells: pd.DataFrame,
    original_network_id: int,
    starting_subnetwork_id: int
) -> pd.DataFrame:
    """
    Split network cells into connected components and assign new network IDs.

    Args:
        network_cells: DataFrame with h3_11 column and network_number
        original_network_id: Original network ID
        starting_subnetwork_id: Starting ID for new subnetworks

    Returns:
        DataFrame with updated network_number for each component
    """
    import networkx as nx

    if len(network_cells) <= 1:
        return network_cells

    # Build adjacency graph
    G = nx.Graph()
    cells = network_cells['h3_11'].unique()

    for cell in cells:
        G.add_node(cell)
        neighbors = h3.grid_ring(cell, 1)
        for neighbor in neighbors:
            if neighbor in cells:
                G.add_edge(cell, neighbor)

    # Find connected components
    components = list(nx.connected_components(G))

    if len(components) == 1:
        return network_cells

    # Assign new network IDs to each component
    result = network_cells.copy()
    component_id = starting_subnetwork_id

    for component in sorted(components, key=len, reverse=True):
        mask = result['h3_11'].isin(component)
        result.loc[mask, 'network_number'] = component_id
        component_id += 1

    return result


def create_retail_park_networks(
    park_cells: pd.DataFrame,
    centres_deleted: gpd.GeoDataFrame,
    starting_network_id: int
) -> gpd.GeoDataFrame:
    """
    Create retail park networks from park cells.

    Combines:
    1. Pure park cells (no overlap with centres)
    2. Cells from deleted centres (that were classified as parks)

    Args:
        park_cells: DataFrame of retail park H3 cells
        centres_deleted: GeoDataFrame of centre cells that were deleted
        starting_network_id: Starting ID for park networks (to avoid collision)

    Returns:
        GeoDataFrame of retail park networks with network_number assignments
    """
    print("\n" + "="*80)
    print("CREATING RETAIL PARK NETWORKS")
    print("="*80)

    # Combine park cells with geometry
    park_cells_geo = ut.to_geoframe(park_cells).copy()

    # Assign network numbers to parks based on park_id
    if 'park_id' in park_cells_geo.columns:
        park_cells_geo['network_number'] = park_cells_geo['park_id'] + starting_network_id
        park_cells_geo['centre_type'] = 'retail_park'
    else:
        raise ValueError("park_cells must have 'park_id' column")

    print(f"Park networks created: {park_cells_geo['network_number'].nunique():,}")
    print(f"Park cells: {len(park_cells_geo):,}")

    return park_cells_geo


def dissolve_to_polygons_with_metadata(park_networks: gpd.GeoDataFrame, name: str) -> gpd.GeoDataFrame:
    """
    Dissolve retail park cells to polygons, preserving brand matching metadata.

    Aggregates:
    - matched_brand_count (max across cells)
    - matched_brand_list (combined list from all cells)
    - matched_to_centre_ratio (average)
    - poi_count (sum)
    - cell_count (count)
    """
    from shapely.geometry import Polygon, MultiPolygon

    print(f"\n{name}...")

    # Get unique park identifiers (park_id or network_number)
    if 'park_id' in park_networks.columns:
        group_col = 'park_id'
    else:
        group_col = 'network_number'

    # Standardize POI count column
    if 'poi_count' not in park_networks.columns:
        if 'centre_poi_total' in park_networks.columns:
            park_networks['poi_count'] = park_networks['centre_poi_total']
        else:
            park_networks['poi_count'] = 0

    # Build aggregation dict
    agg_dict = {
        'h3_11': 'count',
        'poi_count': 'sum',
    }

    # Add optional brand metadata columns if they exist
    if 'matched_brand_count' in park_networks.columns:
        agg_dict['matched_brand_count'] = 'max'  # Max brands seen in any cell
    if 'matched_to_centre_ratio' in park_networks.columns:
        agg_dict['matched_to_centre_ratio'] = 'mean'  # Average ratio

    # Compute stats before dissolving
    network_stats = park_networks.groupby(group_col).agg(agg_dict).rename(
        columns={'h3_11': 'cell_count'}
    )

    # Aggregate brand lists - take first non-empty list per park
    # (all cells from same park should have same brand list from original detection)
    if 'matched_brand_list' in park_networks.columns:
        def get_first_nonempty_list(lists):
            """Get first non-empty brand list."""
            for brand_list in lists:
                if isinstance(brand_list, list) and len(brand_list) > 0:
                    return brand_list
            return []

        brand_lists_agg = park_networks.groupby(group_col)['matched_brand_list'].apply(get_first_nonempty_list)
        network_stats['matched_brand_list'] = brand_lists_agg

    # Dissolve geometries
    dissolved = park_networks.dissolve(by=group_col)

    # Add stats
    dissolved = dissolved.join(network_stats, rsuffix='_stats')

    # Clean up columns
    columns_to_keep = ['cell_count', 'poi_count', 'geometry']
    if 'matched_brand_count_stats' in dissolved.columns:
        dissolved['matched_brand_count'] = dissolved['matched_brand_count_stats']
        columns_to_keep.append('matched_brand_count')
    if 'matched_to_centre_ratio_stats' in dissolved.columns:
        dissolved['matched_to_centre_ratio'] = dissolved['matched_to_centre_ratio_stats']
        columns_to_keep.append('matched_to_centre_ratio')
    if 'matched_brand_list' in dissolved.columns:
        columns_to_keep.append('matched_brand_list')

    dissolved['centre_type'] = 'retail_park'
    columns_to_keep.insert(0, 'centre_type')

    dissolved = dissolved[[col for col in columns_to_keep if col in dissolved.columns]]

    # Fill holes
    def fill_holes(geom):
        if geom.geom_type == 'Polygon':
            return Polygon(geom.exterior)
        elif geom.geom_type == 'MultiPolygon':
            return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
        return geom

    dissolved['geometry'] = dissolved['geometry'].apply(fill_holes)

    # Add area
    dissolved_27700 = dissolved.to_crs('EPSG:27700')
    dissolved['area_sqm'] = dissolved_27700.geometry.area
    dissolved['area_sqkm'] = dissolved['area_sqm'] / 1_000_000

    dissolved = dissolved.reset_index()
    dissolved = dissolved.sort_values('poi_count', ascending=False)

    return dissolved


def create_polygon_outputs(
    centres_kept: gpd.GeoDataFrame,
    park_networks: gpd.GeoDataFrame,
    output_dir: Path
):
    """
    Create dissolved polygon outputs for visualization and analysis.

    Creates three files:
    1. retail_parks_polygons.parquet - Retail parks only (with brand metadata)
    2. split_centres_polygons.parquet - Split retail centres only
    3. final_centres_and_parks_polygons.parquet - Combined
    """
    from shapely.geometry import Polygon, MultiPolygon

    print("\n" + "="*80)
    print("CREATING POLYGON OUTPUTS")
    print("="*80)

    # Make copies to avoid modifying originals
    centres_kept = centres_kept.copy()
    park_networks = park_networks.copy()

    # Standardize POI count columns
    if 'poi_count' not in centres_kept.columns:
        if 'foursquare_count' in centres_kept.columns:
            centres_kept['poi_count'] = centres_kept['foursquare_count']
        else:
            centres_kept['poi_count'] = 0

    if 'poi_count' not in park_networks.columns:
        if 'centre_poi_total' in park_networks.columns:
            park_networks['poi_count'] = park_networks['centre_poi_total']
        else:
            park_networks['poi_count'] = 0

    # Add type labels
    if 'centre_type' not in centres_kept.columns:
        centres_kept['centre_type'] = 'retail_centre'
    if 'centre_type' not in park_networks.columns:
        park_networks['centre_type'] = 'retail_park'

    def dissolve_to_polygons(gdf, name):
        """Dissolve cells to polygons by network."""
        print(f"\n{name}...")

        # Compute stats before dissolving
        network_stats = gdf.groupby('network_number').agg({
            'h3_11': 'count',
            'poi_count': 'sum',
            'centre_type': 'first'
        }).rename(columns={'h3_11': 'cell_count'})

        # Dissolve geometries
        dissolved = gdf.dissolve(by='network_number')

        # Add stats
        dissolved = dissolved.join(network_stats, rsuffix='_stats')
        dissolved['centre_type'] = dissolved['centre_type_stats']
        dissolved['cell_count'] = dissolved['cell_count']
        dissolved['poi_count'] = dissolved['poi_count_stats']
        dissolved = dissolved[['centre_type', 'cell_count', 'poi_count', 'geometry']]

        # Fill holes
        def fill_holes(geom):
            if geom.geom_type == 'Polygon':
                return Polygon(geom.exterior)
            elif geom.geom_type == 'MultiPolygon':
                return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
            return geom

        dissolved['geometry'] = dissolved['geometry'].apply(fill_holes)

        # Add area
        dissolved_27700 = dissolved.to_crs('EPSG:27700')
        dissolved['area_sqm'] = dissolved_27700.geometry.area
        dissolved['area_sqkm'] = dissolved['area_sqm'] / 1_000_000

        dissolved = dissolved.reset_index()
        dissolved = dissolved.sort_values(['centre_type', 'poi_count'], ascending=[True, False])

        return dissolved

    # 1. Retail parks polygons (with brand matching metadata)
    parks_polygons = dissolve_to_polygons_with_metadata(park_networks, "Retail Parks")
    parks_output = output_dir / 'retail_parks_polygons.parquet'
    parks_polygons.to_parquet(parks_output)
    print(f"  Saved: {parks_output}")
    print(f"  Networks: {len(parks_polygons):,}, POIs: {parks_polygons['poi_count'].sum():,}, Area: {parks_polygons['area_sqkm'].sum():.1f} km²")

    # 2. Split centres polygons (if any exist)
    split_centres = centres_kept[centres_kept['network_number'] > 100000].copy()  # Split networks have high IDs

    if len(split_centres) > 0:
        split_polygons = dissolve_to_polygons(split_centres, "Split Centres")
        split_output = output_dir / 'split_centres_polygons.parquet'
        split_polygons.to_parquet(split_output)
        print(f"  Saved: {split_output}")
        print(f"  Networks: {len(split_polygons):,}, POIs: {split_polygons['poi_count'].sum():,}, Area: {split_polygons['area_sqkm'].sum():.1f} km²")

    # 3. Combined polygons
    combined = pd.concat([centres_kept, park_networks], ignore_index=True)
    combined_polygons = dissolve_to_polygons(combined, "Combined (Centres + Parks)")
    combined_output = output_dir / 'final_centres_and_parks_polygons.parquet'
    combined_polygons.to_parquet(combined_output)
    print(f"  Saved: {combined_output}")
    print(f"  Total: {len(combined_polygons):,} networks")
    print(f"  Centres: {(combined_polygons['centre_type'] == 'retail_centre').sum():,}")
    print(f"  Parks: {(combined_polygons['centre_type'] == 'retail_park').sum():,}")
    print(f"  POIs: {combined_polygons['poi_count'].sum():,}, Area: {combined_polygons['area_sqkm'].sum():.1f} km²")

    print("\n✓ All polygon outputs created")


def main():
    """Main function for Workflow 3 implementation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Retail Park Integration - Workflow 3: Merge Small Remainders"
    )
    parser.add_argument(
        "--centres",
        type=str,
        required=True,
        help="Path to retail centres parquet (e.g., 3_afterfill.parquet or 4_finalcentres.parquet)"
    )
    parser.add_argument(
        "--parks",
        type=str,
        default=None,
        help="Optional: Path to pre-detected retail parks parquet (skip detection)"
    )
    parser.add_argument(
        "--min_remainder_pois",
        type=int,
        default=10,
        help="Minimum POIs required to keep centre after subtraction (default: 10)"
    )
    parser.add_argument(
        "--check_connectivity",
        action="store_true",
        help="Delete centres that become disconnected after subtraction"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        required=True,
        help="Output directory for results"
    )

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("="*80)
    print("RETAIL PARK INTEGRATION - WORKFLOW 3: MERGE SMALL REMAINDERS")
    print("="*80)
    print()

    # Step 1: Load retail centres
    centres = load_retail_centres(args.centres)
    original_centre_count = centres['network_number'].nunique()
    original_cell_count = len(centres)

    # Step 2: Detect or load retail parks

    print(f"\nLoading pre-detected retail parks from: {args.parks}")
    retail_parks = gpd.read_parquet(args.parks)

    # Step 3: Convert parks to H3 cells
    park_cells = get_retail_park_cells(retail_parks, include_park_metadata=True)

    # Step 4: Subtract park cells from centres (and merge remainders into parks)
    centres_kept, centres_merged, summary_df, updated_park_cells = subtract_park_cells_from_centres(
        centres=centres,
        park_cells=park_cells,
        min_remainder_pois=args.min_remainder_pois,
        check_connectivity=args.check_connectivity
    )

    # Step 5: Create retail park networks (using updated park cells with merged remainders)
    starting_park_id = centres['network_number'].max() + 1000 if len(centres) > 0 else 1000
    park_networks = create_retail_park_networks(
        park_cells=updated_park_cells,
        centres_deleted=centres_merged,  # Pass merged centres for tracking
        starting_network_id=starting_park_id
    )

    # Step 6: Save outputs
    print("\n" + "="*80)
    print("SAVING OUTPUTS")
    print("="*80)

    centres_output = output_dir / "centres_no_parks.parquet"
    parks_output = output_dir / "retail_parks.parquet"
    summary_output = output_dir / "integration_summary.csv"

    centres_kept.to_parquet(centres_output)
    print(f"Saved centres (no parks): {centres_output}")
    print(f"  Networks: {centres_kept['network_number'].nunique():,}")
    print(f"  Cells: {len(centres_kept):,}")

    park_networks.to_parquet(parks_output)
    print(f"\nSaved retail parks: {parks_output}")
    print(f"  Networks: {park_networks['network_number'].nunique():,}")
    print(f"  Cells: {len(park_networks):,}")

    summary_df.to_csv(summary_output, index=False)
    print(f"\nSaved summary: {summary_output}")

    # Create polygon outputs
    create_polygon_outputs(centres_kept, park_networks, output_dir)

    # Apply landuse filter (remove networks with high commercial/industrial overlap)
    print("\n" + "="*80)
    print("APPLYING LANDUSE FILTER")
    print("="*80)

    from retail.landuse_filter import run_landuse_filter

    # Default paths for commercial and industrial landuse
    commercial_path = "data/input_files/commercial_landuse.parquet"
    industrial_path = "data/input_files/industrial_landuse.parquet"  # Or same as commercial if not available

    # Check if files exist
    from pathlib import Path as PathLib
    if PathLib(commercial_path).exists():
        print("\nFiltering centres by commercial/industrial overlap...")
        commercial = gpd.read_parquet(commercial_path)
        industrial = commercial  # Use same for both if industrial not available

        if PathLib(industrial_path).exists():
            industrial = gpd.read_parquet(industrial_path)

        landuse_result = run_landuse_filter(
            centres=centres_kept,
            commercial=commercial,
            industrial=industrial,
            overlap_threshold=75.0,
            poi_threshold=20,
            source='foursquare',
            num_workers=None
        )

        # Save landuse-filtered centres
        filtered_output = output_dir / 'centres_no_parks_landuse_filtered.parquet'
        landuse_result.filtered.to_parquet(filtered_output)
        print(f"\n✓ Saved landuse-filtered centres: {filtered_output}")

        # Save landuse filter summary
        landuse_result.summary.to_csv(output_dir / 'landuse_filter_summary.csv', index=False)
        landuse_result.overlap_details.to_parquet(output_dir / 'landuse_filter_overlap_details.parquet')
        if not landuse_result.removed_cells.empty:
            landuse_result.removed_cells.to_parquet(output_dir / 'landuse_filter_removed_networks.parquet')

        # Create polygon version of landuse-filtered centres
        print("\nCreating polygon version of landuse-filtered centres...")
        create_polygon_outputs(
            landuse_result.filtered,
            park_networks,
            output_dir
        )

        # Rename to distinguish from non-filtered version
        (output_dir / 'final_centres_and_parks_polygons.parquet').rename(
            output_dir / 'final_centres_and_parks_polygons_landuse_filtered.parquet'
        )

        centres_kept = landuse_result.filtered
    else:
        print(f"\n⚠ Commercial landuse file not found: {commercial_path}")
        print("Skipping landuse filter")

    # Final summary
    print("\n" + "="*80)
    print("WORKFLOW 3 COMPLETE")
    print("="*80)
    print(f"Original centres: {original_centre_count:,} networks, {original_cell_count:,} cells")
    print(f"Final centres: {centres_kept['network_number'].nunique():,} networks, {len(centres_kept):,} cells")
    print(f"Retail parks: {park_networks['network_number'].nunique():,} networks, {len(park_networks):,} cells")
    print(f"Centres merged into parks: {centres_merged['network_number'].nunique():,} networks, {len(centres_merged):,} cells")
    print("="*80)


if __name__ == "__main__":
    main()
