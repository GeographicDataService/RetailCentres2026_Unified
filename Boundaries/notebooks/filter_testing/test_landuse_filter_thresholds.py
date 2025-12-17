#!/usr/bin/env python3
"""
Multi-threshold landuse filter comparison.

Tests multiple coverage thresholds and shows incremental removals at each level.

Usage:
    python src/test_landuse_filter_thresholds.py \
        --centres data/output_files/nov2025_v10postcodefilter.../3_afterfill.parquet \
        --commercial_h3 data/input_files/commercial_landuse_h3.parquet \
        --output_dir data/landuse_filter_comparison
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

    return coverage_df


def analyze_thresholds(centres_gdf, coverage_df, landuse_type, thresholds, output_dir):
    """
    Analyze multiple thresholds and save incremental removals.

    Parameters:
    - centres_gdf: GeoDataFrame with retail centres
    - coverage_df: DataFrame with coverage statistics
    - landuse_type: Type of landuse ("commercial" or "industrial")
    - thresholds: List of thresholds to test (descending order, e.g., [100, 90, 80, ...])
    - output_dir: Directory to save outputs
    """
    print(f"\n{'='*60}")
    print(f"Threshold Analysis: {landuse_type.upper()}")
    print(f"{'='*60}")

    # Add coverage to centres
    centres_with_coverage = centres_gdf.merge(
        coverage_df[['network_number', 'coverage_pct']],
        on='network_number',
        how='left'
    )

    # Summary table
    summary_rows = []

    # Track cumulative removals
    prev_threshold = 101  # Start above 100

    for threshold in sorted(thresholds, reverse=True):  # Process from highest to lowest
        # Networks at this threshold or higher
        removed_at_threshold = centres_with_coverage[
            centres_with_coverage['coverage_pct'] >= threshold
        ]

        # NEW removals: between this threshold and previous threshold
        new_removals = centres_with_coverage[
            (centres_with_coverage['coverage_pct'] >= threshold) &
            (centres_with_coverage['coverage_pct'] < prev_threshold)
        ]

        num_networks_removed = removed_at_threshold['network_number'].nunique()
        num_networks_new = new_removals['network_number'].nunique()
        num_cells_removed = len(removed_at_threshold)
        num_cells_new = len(new_removals)
        total_networks = centres_gdf['network_number'].nunique()

        pct_removed = 100 * num_networks_removed / total_networks
        pct_new = 100 * num_networks_new / total_networks

        summary_rows.append({
            'threshold_pct': threshold,
            'coverage_range': f'{threshold}-{prev_threshold-1}%' if prev_threshold <= 100 else f'{threshold}-100%',
            'networks_new_at_threshold': num_networks_new,
            'networks_cumulative': num_networks_removed,
            'pct_new': pct_new,
            'pct_cumulative': pct_removed,
            'cells_new': num_cells_new,
            'cells_cumulative': num_cells_removed
        })

        # Save NEW removals geoparquet
        if len(new_removals) > 0:
            # Convert to geopandas if needed
            if 'geometry' not in new_removals.columns:
                new_removals_geo = ut.to_geopandas(new_removals)
            else:
                new_removals_geo = new_removals

            output_path = output_dir / f"new_removals_{landuse_type}_{threshold}pct.parquet"
            new_removals_geo.to_parquet(output_path)
            print(f"  ✓ {threshold}%: {num_networks_new:,} new networks ({num_cells_new:,} cells) → {output_path.name}")
        else:
            print(f"  - {threshold}%: 0 new networks")

        prev_threshold = threshold

    summary_df = pd.DataFrame(summary_rows)

    # Print summary table
    print(f"\n{landuse_type.upper()} Coverage Threshold Summary:")
    print("="*100)
    print(summary_df.to_string(index=False))
    print("="*100)

    # Save summary
    summary_path = output_dir / f"threshold_summary_{landuse_type}.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"\n✓ Summary saved to: {summary_path}")

    return summary_df


def main():
    parser = argparse.ArgumentParser(
        description="Multi-threshold landuse filter comparison"
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
        default="data/landuse_filter_comparison",
        help="Output directory for filtered centres"
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default="100,90,80,70,60,50",
        help="Comma-separated coverage thresholds (default: 100,90,80,70,60,50)"
    )

    args = parser.parse_args()

    # Parse thresholds
    thresholds = [int(t.strip()) for t in args.thresholds.split(',')]
    thresholds = sorted(thresholds, reverse=True)  # Ensure descending order

    print("="*60)
    print("Multi-Threshold Landuse Filter Analysis")
    print("="*60)
    print(f"Centres file: {args.centres}")
    print(f"Thresholds: {thresholds}")
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
    output_path.mkdir(parents=True, exist_ok=True)

    # Process commercial landuse
    commercial_coverage = compute_landuse_coverage(
        centres,
        args.commercial_h3,
        "commercial"
    )

    if commercial_coverage is not None:
        commercial_summary = analyze_thresholds(
            centres,
            commercial_coverage,
            "commercial",
            thresholds,
            output_path
        )

        # Save full coverage stats
        commercial_coverage.to_parquet(output_path / "commercial_coverage_all_networks.parquet")

    # Process industrial landuse
    industrial_coverage = compute_landuse_coverage(
        centres,
        args.industrial_h3,
        "industrial"
    )

    if industrial_coverage is not None:
        industrial_summary = analyze_thresholds(
            centres,
            industrial_coverage,
            "industrial",
            thresholds,
            output_path
        )

        # Save full coverage stats
        industrial_coverage.to_parquet(output_path / "industrial_coverage_all_networks.parquet")

    print("\n" + "="*60)
    print("Analysis Complete!")
    print("="*60)
    print(f"\nOutputs saved to: {output_path}")
    print("\nGenerated files:")
    print("  - threshold_summary_*.csv - Summary statistics for each threshold")
    print("  - new_removals_*_XXpct.parquet - GeoParquet of NEW removals at each threshold")
    print("  - *_coverage_all_networks.parquet - Full coverage stats for all networks")
    print("\nNext steps:")
    print("  1. Review threshold summary CSVs to see distribution")
    print("  2. Open new_removals geoparquet files in QGIS to inspect each threshold level")
    print("  3. Choose optimal threshold based on visual inspection")


if __name__ == "__main__":
    main()
