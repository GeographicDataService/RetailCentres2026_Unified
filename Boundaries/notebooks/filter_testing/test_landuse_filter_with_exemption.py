#!/usr/bin/env python3
"""
Landuse filter with minimum POI exemption.

Networks with >= min_pois are exempt from filtering.

Usage:
    python src/test_landuse_filter_with_exemption.py \
        --centres data/output_files/nov2025_v10.../3_afterfill.parquet \
        --commercial_h3 data/input_files/commercial_landuse_h3.parquet \
        --min_pois 20 \
        --threshold 100
"""

import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
from utils import utils as ut


def compute_landuse_coverage(centres_gdf, landuse_h3_path, landuse_type):
    """Compute landuse coverage for each network."""
    print(f"\nComputing {landuse_type} landuse coverage...")

    if not Path(landuse_h3_path).exists():
        print(f"  WARNING: {landuse_h3_path} not found. Skipping {landuse_type}.")
        return None

    landuse_h3 = pd.read_parquet(landuse_h3_path)
    print(f"  Loaded {len(landuse_h3):,} {landuse_type} landuse H3 cells")

    landuse_h3_set = set(landuse_h3['h3_11'])
    network_h3s = centres_gdf.groupby('network_number')['h3_11'].apply(set)

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


def main():
    parser = argparse.ArgumentParser(
        description="Landuse filter with minimum POI exemption"
    )
    parser.add_argument("--centres", type=str, required=True)
    parser.add_argument("--commercial_h3", type=str, default="data/input_files/commercial_landuse_h3.parquet")
    parser.add_argument("--industrial_h3", type=str, default="data/input_files/industrial_landuse_h3.parquet")
    parser.add_argument("--output_dir", type=str, default="data/landuse_filter_with_exemption")
    parser.add_argument("--threshold", type=float, default=100.0, help="Coverage threshold %")
    parser.add_argument("--min_pois", type=int, default=20, help="Networks with >= this many POIs are exempt")

    args = parser.parse_args()

    print("="*60)
    print("Landuse Filter with POI Exemption")
    print("="*60)
    print(f"Coverage threshold: {args.threshold}%")
    print(f"POI exemption: Networks with >= {args.min_pois} POIs are exempt")
    print("="*60)

    # Load centres
    print(f"\nLoading centres...")
    centres = gpd.read_parquet(args.centres)
    print(f"  {len(centres):,} cells, {centres['network_number'].nunique():,} networks")

    # Calculate POI counts per network
    print(f"\nCalculating POI counts per network...")
    network_pois = centres.groupby('network_number')['foursquare_count'].sum().reset_index()
    network_pois.columns = ['network_number', 'total_pois']

    # Add to centres
    centres_with_pois = centres.merge(network_pois, on='network_number')

    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Process commercial
    commercial_coverage = compute_landuse_coverage(centres, args.commercial_h3, "commercial")

    if commercial_coverage is not None:
        # Merge coverage with POI counts
        analysis = commercial_coverage.merge(network_pois, on='network_number')

        # Identify networks to remove (high coverage AND below POI threshold)
        to_remove = analysis[
            (analysis['coverage_pct'] >= args.threshold) &
            (analysis['total_pois'] < args.min_pois)
        ]

        # Identify networks that would be removed but are exempt
        exempt = analysis[
            (analysis['coverage_pct'] >= args.threshold) &
            (analysis['total_pois'] >= args.min_pois)
        ]

        print(f"\n{'='*60}")
        print("COMMERCIAL Landuse Filter Results")
        print(f"{'='*60}")
        print(f"Networks with >= {args.threshold}% coverage: {len(analysis[analysis['coverage_pct'] >= args.threshold]):,}")
        print(f"  - Would be REMOVED (< {args.min_pois} POIs): {len(to_remove):,}")
        print(f"  - EXEMPT (>= {args.min_pois} POIs): {len(exempt):,}")
        print(f"\nExempt networks POI range: {exempt['total_pois'].min():.0f} - {exempt['total_pois'].max():.0f}")
        print(f"Removed networks POI range: {to_remove['total_pois'].min():.0f} - {to_remove['total_pois'].max():.0f}")

        # Show top exempt networks
        if len(exempt) > 0:
            print(f"\nTop 10 EXEMPT networks (saved from removal):")
            exempt_sorted = exempt.sort_values('total_pois', ascending=False).head(10)
            print(exempt_sorted[['network_number', 'total_cells', 'coverage_pct', 'total_pois']].to_string(index=False))

        # Filter centres
        removed_centres = centres_with_pois[
            centres_with_pois['network_number'].isin(to_remove['network_number'])
        ]

        if len(removed_centres) > 0:
            # Convert to geopandas if needed
            if 'geometry' not in removed_centres.columns:
                removed_geo = ut.to_geopandas(removed_centres)
            else:
                removed_geo = removed_centres

            output_file = output_path / f"removed_commercial_{int(args.threshold)}pct_minpoi{args.min_pois}.parquet"
            removed_geo.to_parquet(output_file)
            print(f"\n✓ Saved removed centres to: {output_file}")

        # Save summary
        summary = pd.DataFrame([{
            'landuse_type': 'commercial',
            'threshold_pct': args.threshold,
            'min_pois_exempt': args.min_pois,
            'networks_total': centres['network_number'].nunique(),
            'networks_high_coverage': len(analysis[analysis['coverage_pct'] >= args.threshold]),
            'networks_removed': len(to_remove),
            'networks_exempt': len(exempt),
            'cells_removed': len(removed_centres)
        }])
        summary.to_csv(output_path / "filter_summary.csv", index=False)
        print(f"✓ Saved summary to: {output_path / 'filter_summary.csv'}")

    # Process industrial
    industrial_coverage = compute_landuse_coverage(centres, args.industrial_h3, "industrial")

    if industrial_coverage is not None:
        # Merge coverage with POI counts
        analysis = industrial_coverage.merge(network_pois, on='network_number')

        # Identify networks to remove (high coverage AND below POI threshold)
        to_remove = analysis[
            (analysis['coverage_pct'] >= args.threshold) &
            (analysis['total_pois'] < args.min_pois)
        ]

        # Identify networks that would be removed but are exempt
        exempt = analysis[
            (analysis['coverage_pct'] >= args.threshold) &
            (analysis['total_pois'] >= args.min_pois)
        ]

        print(f"\n{'='*60}")
        print("INDUSTRIAL Landuse Filter Results")
        print(f"{'='*60}")
        print(f"Networks with >= {args.threshold}% coverage: {len(analysis[analysis['coverage_pct'] >= args.threshold]):,}")
        print(f"  - Would be REMOVED (< {args.min_pois} POIs): {len(to_remove):,}")
        print(f"  - EXEMPT (>= {args.min_pois} POIs): {len(exempt):,}")
        print(f"\nExempt networks POI range: {exempt['total_pois'].min():.0f} - {exempt['total_pois'].max():.0f}")
        print(f"Removed networks POI range: {to_remove['total_pois'].min():.0f} - {to_remove['total_pois'].max():.0f}")

        # Show top exempt networks
        if len(exempt) > 0:
            print(f"\nTop 10 EXEMPT networks (saved from removal):")
            exempt_sorted = exempt.sort_values('total_pois', ascending=False).head(10)
            print(exempt_sorted[['network_number', 'total_cells', 'coverage_pct', 'total_pois']].to_string(index=False))

        # Filter centres
        removed_centres = centres_with_pois[
            centres_with_pois['network_number'].isin(to_remove['network_number'])
        ]

        if len(removed_centres) > 0:
            # Convert to geopandas if needed
            if 'geometry' not in removed_centres.columns:
                removed_geo = ut.to_geopandas(removed_centres)
            else:
                removed_geo = removed_centres

            output_file = output_path / f"removed_industrial_{int(args.threshold)}pct_minpoi{args.min_pois}.parquet"
            removed_geo.to_parquet(output_file)
            print(f"\n✓ Saved removed centres to: {output_file}")

        # Append to summary
        industrial_summary = pd.DataFrame([{
            'landuse_type': 'industrial',
            'threshold_pct': args.threshold,
            'min_pois_exempt': args.min_pois,
            'networks_total': centres['network_number'].nunique(),
            'networks_high_coverage': len(analysis[analysis['coverage_pct'] >= args.threshold]),
            'networks_removed': len(to_remove),
            'networks_exempt': len(exempt),
            'cells_removed': len(removed_centres)
        }])

        # Read existing summary and append
        summary_path = output_path / "filter_summary.csv"
        if summary_path.exists():
            existing = pd.read_csv(summary_path)
            combined = pd.concat([existing, industrial_summary], ignore_index=True)
            combined.to_csv(summary_path, index=False)
        else:
            industrial_summary.to_csv(summary_path, index=False)

        print(f"✓ Updated summary at: {summary_path}")

    print("\n" + "="*60)
    print("Complete!")
    print("="*60)


if __name__ == "__main__":
    main()
