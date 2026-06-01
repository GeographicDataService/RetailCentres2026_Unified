#!/usr/bin/env python3
"""
Landuse filter using polygon overlap instead of H3 cell coverage.

Networks with >= 90% area overlap with commercial/industrial AND < min_pois are removed.

Usage:
    python src/test_landuse_filter_polygon_overlap.py \
        --centres data/output_files/nov2025_v10.../3_afterfill.parquet \
        --commercial data/input_files/commercial_landuse.parquet \
        --industrial data/input_files/industrial_landuse.parquet \
        --min_pois 20 \
        --overlap_threshold 90
"""

import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
from utils import utils as ut
from tqdm import tqdm


def compute_polygon_overlap(centres_gdf, landuse_gdf, landuse_type):
    """
    Compute polygon-based overlap for each network.

    Parameters:
    - centres_gdf: GeoDataFrame with retail centres (with geometry)
    - landuse_gdf: GeoDataFrame with landuse polygons
    - landuse_type: Type of landuse ("commercial" or "industrial")

    Returns:
    - DataFrame with network_number, network_area, overlap_area, overlap_pct
    """
    print(f"\nComputing {landuse_type} polygon overlap...")

    if landuse_gdf is None or len(landuse_gdf) == 0:
        print(f"  WARNING: No {landuse_type} landuse data. Skipping.")
        return None

    print(f"  Loaded {len(landuse_gdf):,} {landuse_type} polygons")

    # Ensure CRS match
    if centres_gdf.crs != landuse_gdf.crs:
        print(f"  Converting landuse CRS from {landuse_gdf.crs} to {centres_gdf.crs}...")
        landuse_gdf = landuse_gdf.to_crs(centres_gdf.crs)

    # Dissolve landuse polygons into single multipolygon for faster intersection
    print(f"  Dissolving {landuse_type} polygons...")
    landuse_union = landuse_gdf.union_all()

    # Dissolve each network's cells into a single polygon
    print(f"  Dissolving networks...")
    network_polygons = centres_gdf.groupby('network_number').agg({
        'geometry': lambda x: x.union_all()
    }).reset_index()
    network_polygons.columns = ['network_number', 'geometry']
    network_polygons = gpd.GeoDataFrame(network_polygons, geometry='geometry', crs=centres_gdf.crs)

    # Calculate overlap for each network
    print(f"  Calculating overlaps for {len(network_polygons):,} networks...")
    overlap_rows = []

    for idx, row in tqdm(network_polygons.iterrows(), total=len(network_polygons), desc=f"  {landuse_type}"):
        network_id = row['network_number']
        network_geom = row['geometry']
        network_area = network_geom.area

        # Calculate intersection with landuse
        try:
            intersection = network_geom.intersection(landuse_union)
            overlap_area = intersection.area
            overlap_pct = (overlap_area / network_area * 100.0) if network_area > 0 else 0.0
        except Exception as e:
            print(f"    Warning: Error calculating overlap for network {network_id}: {e}")
            overlap_area = 0.0
            overlap_pct = 0.0

        overlap_rows.append({
            'network_number': network_id,
            'network_area': network_area,
            'overlap_area': overlap_area,
            'overlap_pct': overlap_pct
        })

    overlap_df = pd.DataFrame(overlap_rows)
    print(f"  Computed overlap for {len(overlap_df):,} networks")

    # Print distribution stats
    print(f"  Overlap distribution:")
    print(f"    Mean: {overlap_df['overlap_pct'].mean():.1f}%")
    print(f"    Median: {overlap_df['overlap_pct'].median():.1f}%")
    print(f"    Max: {overlap_df['overlap_pct'].max():.1f}%")
    print(f"    >= 50%: {(overlap_df['overlap_pct'] >= 50).sum():,} networks")
    print(f"    >= 70%: {(overlap_df['overlap_pct'] >= 70).sum():,} networks")
    print(f"    >= 80%: {(overlap_df['overlap_pct'] >= 80).sum():,} networks")
    print(f"    >= 90%: {(overlap_df['overlap_pct'] >= 90).sum():,} networks")

    return overlap_df


def main():
    parser = argparse.ArgumentParser(
        description="Landuse filter using polygon overlap"
    )
    parser.add_argument("--centres", type=str, required=True)
    parser.add_argument("--commercial", type=str, default="data/input_files/commercial_landuse.parquet")
    parser.add_argument("--industrial", type=str, default="data/input_files/industrial_landuse.parquet")
    parser.add_argument("--output_dir", type=str, default="data/landuse_filter_polygon")
    parser.add_argument("--overlap_threshold", type=float, default=90.0, help="Overlap threshold %")
    parser.add_argument("--min_pois", type=int, default=20, help="Networks with >= this many POIs are exempt")

    args = parser.parse_args()

    print("="*60)
    print("Landuse Filter - Polygon Overlap Method")
    print("="*60)
    print(f"Overlap threshold: {args.overlap_threshold}%")
    print(f"POI exemption: Networks with >= {args.min_pois} POIs are exempt")
    print("="*60)

    # Load centres
    print(f"\nLoading centres...")
    centres = gpd.read_parquet(args.centres)

    # Ensure geometry exists
    if 'geometry' not in centres.columns:
        print("  Converting H3 to geometries...")
        centres = ut.to_geopandas(centres)

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
    if Path(args.commercial).exists():
        commercial_landuse = gpd.read_parquet(args.commercial)
        commercial_overlap = compute_polygon_overlap(centres, commercial_landuse, "commercial")

        if commercial_overlap is not None:
            # Merge overlap with POI counts
            analysis = commercial_overlap.merge(network_pois, on='network_number')

            # Identify networks to remove (high overlap AND below POI threshold)
            to_remove = analysis[
                (analysis['overlap_pct'] >= args.overlap_threshold) &
                (analysis['total_pois'] < args.min_pois)
            ]

            # Identify networks that would be removed but are exempt
            exempt = analysis[
                (analysis['overlap_pct'] >= args.overlap_threshold) &
                (analysis['total_pois'] >= args.min_pois)
            ]

            print(f"\n{'='*60}")
            print("COMMERCIAL Landuse Filter Results")
            print(f"{'='*60}")
            print(f"Networks with >= {args.overlap_threshold}% overlap: {len(analysis[analysis['overlap_pct'] >= args.overlap_threshold]):,}")
            print(f"  - Would be REMOVED (< {args.min_pois} POIs): {len(to_remove):,}")
            print(f"  - EXEMPT (>= {args.min_pois} POIs): {len(exempt):,}")

            if len(exempt) > 0:
                print(f"\nExempt networks POI range: {exempt['total_pois'].min():.0f} - {exempt['total_pois'].max():.0f}")
            if len(to_remove) > 0:
                print(f"Removed networks POI range: {to_remove['total_pois'].min():.0f} - {to_remove['total_pois'].max():.0f}")

            # Show top exempt networks
            if len(exempt) > 0:
                print(f"\nTop 10 EXEMPT networks (saved from removal):")
                exempt_sorted = exempt.sort_values('total_pois', ascending=False).head(10)
                print(exempt_sorted[['network_number', 'overlap_pct', 'total_pois']].to_string(index=False))

            # Filter centres
            removed_centres = centres_with_pois[
                centres_with_pois['network_number'].isin(to_remove['network_number'])
            ]

            if len(removed_centres) > 0:
                output_file = output_path / f"removed_commercial_{int(args.overlap_threshold)}pct_minpoi{args.min_pois}.parquet"
                removed_centres.to_parquet(output_file)
                print(f"\n✓ Saved removed centres to: {output_file}")

            # Save summary
            summary = pd.DataFrame([{
                'landuse_type': 'commercial',
                'overlap_threshold_pct': args.overlap_threshold,
                'min_pois_exempt': args.min_pois,
                'networks_total': centres['network_number'].nunique(),
                'networks_high_overlap': len(analysis[analysis['overlap_pct'] >= args.overlap_threshold]),
                'networks_removed': len(to_remove),
                'networks_exempt': len(exempt),
                'cells_removed': len(removed_centres)
            }])
            summary.to_csv(output_path / "filter_summary.csv", index=False)
            print(f"✓ Saved summary to: {output_path / 'filter_summary.csv'}")
    else:
        print(f"\nWARNING: Commercial landuse file not found: {args.commercial}")

    # Process industrial
    if Path(args.industrial).exists():
        industrial_landuse = gpd.read_parquet(args.industrial)
        industrial_overlap = compute_polygon_overlap(centres, industrial_landuse, "industrial")

        if industrial_overlap is not None:
            # Merge overlap with POI counts
            analysis = industrial_overlap.merge(network_pois, on='network_number')

            # Identify networks to remove (high overlap AND below POI threshold)
            to_remove = analysis[
                (analysis['overlap_pct'] >= args.overlap_threshold) &
                (analysis['total_pois'] < args.min_pois)
            ]

            # Identify networks that would be removed but are exempt
            exempt = analysis[
                (analysis['overlap_pct'] >= args.overlap_threshold) &
                (analysis['total_pois'] >= args.min_pois)
            ]

            print(f"\n{'='*60}")
            print("INDUSTRIAL Landuse Filter Results")
            print(f"{'='*60}")
            print(f"Networks with >= {args.overlap_threshold}% overlap: {len(analysis[analysis['overlap_pct'] >= args.overlap_threshold]):,}")
            print(f"  - Would be REMOVED (< {args.min_pois} POIs): {len(to_remove):,}")
            print(f"  - EXEMPT (>= {args.min_pois} POIs): {len(exempt):,}")

            if len(exempt) > 0:
                print(f"\nExempt networks POI range: {exempt['total_pois'].min():.0f} - {exempt['total_pois'].max():.0f}")
            if len(to_remove) > 0:
                print(f"Removed networks POI range: {to_remove['total_pois'].min():.0f} - {to_remove['total_pois'].max():.0f}")

            # Show top exempt networks
            if len(exempt) > 0:
                print(f"\nTop 10 EXEMPT networks (saved from removal):")
                exempt_sorted = exempt.sort_values('total_pois', ascending=False).head(10)
                print(exempt_sorted[['network_number', 'overlap_pct', 'total_pois']].to_string(index=False))

            # Filter centres
            removed_centres = centres_with_pois[
                centres_with_pois['network_number'].isin(to_remove['network_number'])
            ]

            if len(removed_centres) > 0:
                output_file = output_path / f"removed_industrial_{int(args.overlap_threshold)}pct_minpoi{args.min_pois}.parquet"
                removed_centres.to_parquet(output_file)
                print(f"\n✓ Saved removed centres to: {output_file}")

            # Append to summary
            industrial_summary = pd.DataFrame([{
                'landuse_type': 'industrial',
                'overlap_threshold_pct': args.overlap_threshold,
                'min_pois_exempt': args.min_pois,
                'networks_total': centres['network_number'].nunique(),
                'networks_high_overlap': len(analysis[analysis['overlap_pct'] >= args.overlap_threshold]),
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
    else:
        print(f"\nWARNING: Industrial landuse file not found: {args.industrial}")

    print("\n" + "="*60)
    print("Complete!")
    print("="*60)


if __name__ == "__main__":
    main()
