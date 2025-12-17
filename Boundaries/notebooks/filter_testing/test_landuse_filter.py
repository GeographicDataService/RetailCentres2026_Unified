#!/usr/bin/env python3
"""
Test filter for retail centres surrounded by commercial/industrial landuse.

This script:
1. Computes landuse coverage for each retail centre (network)
2. Identifies centres 100% surrounded by commercial landuse
3. Identifies centres 100% surrounded by industrial landuse
4. Saves filtered centres to geoparquet for inspection

Usage:
    python src/test_landuse_filter.py \
        --centres data/output_files/run_name/3_afterfill.parquet \
        --commercial_h3 data/input_files/commercial_landuse_h3.parquet \
        --industrial_h3 data/input_files/industrial_landuse_h3.parquet \
        --output_dir data/landuse_filter_test
"""

import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
from utils import utils as ut


def compute_landuse_coverage(centres_gdf, landuse_h3_path, landuse_type):
    """
    Compute what percentage of each centre's H3 cells are covered by a landuse type.

    Parameters:
    - centres_gdf: GeoDataFrame with retail centres (must have h3_11, network_number columns)
    - landuse_h3_path: Path to landuse H3 parquet file
    - landuse_type: Type of landuse ("commercial" or "industrial")

    Returns:
    - DataFrame with network_number, total_cells, covered_cells, coverage_pct
    """
    print(f"\nComputing {landuse_type} landuse coverage...")

    # Load landuse H3 cells
    if not Path(landuse_h3_path).exists():
        print(f"  WARNING: {landuse_h3_path} not found. Skipping {landuse_type}.")
        return None

    landuse_h3 = pd.read_parquet(landuse_h3_path)
    print(f"  Loaded {len(landuse_h3):,} {landuse_type} landuse H3 cells")

    # Set of all landuse H3 cells
    landuse_h3_set = set(landuse_h3['h3_11'])

    # Group centre H3 cells by network_number
    network_h3s = centres_gdf.groupby('network_number')['h3_11'].apply(set)

    # Compute coverage for each network
    coverage_rows = []
    for network_number, cells in network_h3s.items():
        if not cells:
            continue
        covered = len(cells & landuse_h3_set)
        total = len(cells)
        coverage_pct = (covered / total) * 100.0
        coverage_rows.append((network_number, total, covered, coverage_pct))

    coverage_df = pd.DataFrame(
        coverage_rows,
        columns=['network_number', 'total_cells', 'covered_cells', 'coverage_pct']
    )

    print(f"  Computed coverage for {len(coverage_df):,} networks")
    print(f"  Coverage stats:")
    print(coverage_df['coverage_pct'].describe())

    return coverage_df


def filter_and_save_surrounded_centres(centres_gdf, coverage_df, landuse_type, threshold_pct, output_path):
    """
    Filter centres with coverage >= threshold and save to geoparquet.

    Parameters:
    - centres_gdf: GeoDataFrame with retail centres
    - coverage_df: DataFrame with coverage statistics
    - landuse_type: Type of landuse ("commercial" or "industrial")
    - threshold_pct: Coverage threshold (e.g., 100 for "entirely surrounded")
    - output_path: Path to save filtered centres
    """
    print(f"\nFiltering centres surrounded by {landuse_type} (>= {threshold_pct}% coverage)...")

    # Add coverage to centres
    centres_with_coverage = centres_gdf.merge(
        coverage_df[['network_number', 'coverage_pct']],
        on='network_number',
        how='left'
    )

    # Filter surrounded centres
    surrounded = centres_with_coverage[
        centres_with_coverage['coverage_pct'] >= threshold_pct
    ]

    # Count unique networks
    num_networks_surrounded = surrounded['network_number'].nunique()
    num_networks_total = centres_gdf['network_number'].nunique()

    print(f"  Networks surrounded: {num_networks_surrounded:,} / {num_networks_total:,} "
          f"({100 * num_networks_surrounded / num_networks_total:.2f}%)")
    print(f"  Total cells in surrounded networks: {len(surrounded):,}")

    # Save to geoparquet
    if len(surrounded) > 0:
        # Ensure geometry column exists
        if 'geometry' not in surrounded.columns:
            print(f"  Converting H3 cells to geometries...")
            surrounded_geo = ut.to_geopandas(surrounded)
        else:
            surrounded_geo = surrounded

        output_path.parent.mkdir(parents=True, exist_ok=True)
        surrounded_geo.to_parquet(output_path)
        print(f"  ✓ Saved to: {output_path}")

        # Print some examples
        print(f"\n  Top 5 networks by cell count:")
        top_networks = (
            surrounded.groupby('network_number')
            .size()
            .sort_values(ascending=False)
            .head(5)
        )
        for network_id, cell_count in top_networks.items():
            coverage = coverage_df[coverage_df['network_number'] == network_id]['coverage_pct'].values[0]
            print(f"    Network {network_id}: {cell_count:,} cells, {coverage:.1f}% coverage")
    else:
        print(f"  No centres found with >= {threshold_pct}% {landuse_type} coverage")

    return surrounded


def main():
    parser = argparse.ArgumentParser(
        description="Test filter for centres surrounded by commercial/industrial landuse"
    )
    parser.add_argument(
        "--centres",
        type=str,
        required=True,
        help="Path to centres parquet file (e.g., 3_afterfill.parquet)"
    )
    parser.add_argument(
        "--commercial_h3",
        type=str,
        default="data/input_files/commercial_landuse_h3.parquet",
        help="Path to commercial landuse H3 parquet"
    )
    parser.add_argument(
        "--industrial_h3",
        type=str,
        default="data/input_files/industrial_landuse_h3.parquet",
        help="Path to industrial landuse H3 parquet"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="data/landuse_filter_test",
        help="Output directory for filtered centres"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=100.0,
        help="Coverage threshold percentage (default: 100 = entirely surrounded)"
    )

    args = parser.parse_args()

    print("="*60)
    print("Landuse Filter Test")
    print("="*60)
    print(f"Centres file: {args.centres}")
    print(f"Coverage threshold: {args.threshold}%")
    print(f"Output directory: {args.output_dir}")
    print("="*60)

    # Load centres
    print(f"\nLoading centres from {args.centres}...")
    centres = gpd.read_parquet(args.centres)
    print(f"  Loaded {len(centres):,} centre cells")
    print(f"  Unique networks: {centres['network_number'].nunique():,}")

    # Check required columns
    if 'h3_11' not in centres.columns or 'network_number' not in centres.columns:
        raise ValueError("Centres file must have 'h3_11' and 'network_number' columns")

    output_path = Path(args.output_dir)

    # Process commercial landuse
    commercial_coverage = compute_landuse_coverage(
        centres,
        args.commercial_h3,
        "commercial"
    )

    if commercial_coverage is not None:
        commercial_output = output_path / f"centres_surrounded_commercial_{int(args.threshold)}pct.parquet"
        commercial_surrounded = filter_and_save_surrounded_centres(
            centres,
            commercial_coverage,
            "commercial",
            args.threshold,
            commercial_output
        )

        # Save coverage stats
        commercial_coverage.to_parquet(output_path / "commercial_coverage_stats.parquet")
        print(f"\n  Coverage stats saved to: {output_path / 'commercial_coverage_stats.parquet'}")

    # Process industrial landuse
    industrial_coverage = compute_landuse_coverage(
        centres,
        args.industrial_h3,
        "industrial"
    )

    if industrial_coverage is not None:
        industrial_output = output_path / f"centres_surrounded_industrial_{int(args.threshold)}pct.parquet"
        industrial_surrounded = filter_and_save_surrounded_centres(
            centres,
            industrial_coverage,
            "industrial",
            args.threshold,
            industrial_output
        )

        # Save coverage stats
        industrial_coverage.to_parquet(output_path / "industrial_coverage_stats.parquet")
        print(f"\n  Coverage stats saved to: {output_path / 'industrial_coverage_stats.parquet'}")

    print("\n" + "="*60)
    print("Filtering complete!")
    print("="*60)
    print(f"\nOutputs saved to: {output_path}")
    print("\nNext steps:")
    print("  1. Open geoparquet files in QGIS to inspect surrounded centres")
    print("  2. Review coverage_stats.parquet to see distribution")
    print("  3. Adjust threshold if needed and re-run")


if __name__ == "__main__":
    main()
