#!/usr/bin/env python3
"""
Create comparison files showing additional networks removed at different thresholds.
"""

import geopandas as gpd
from pathlib import Path

# Load network data
centres = gpd.read_parquet("data/output_files/nov2025_v10postcodefilter_foursquare_mrc_2_mri_1_mrn_10_mtf_6_splitthresh_1500_merge_y/3_afterfill.parquet")
network_pois = centres.groupby('network_number')['foursquare_count'].sum().reset_index()
network_pois.columns = ['network_number', 'total_pois']

output_path = Path("data/landuse_filter_comparison")
output_path.mkdir(parents=True, exist_ok=True)

# Load removed networks for each threshold
commercial_90 = gpd.read_parquet("data/landuse_filter_polygon_fast/removed_commercial_90pct_minpoi20.parquet")
commercial_75 = gpd.read_parquet("data/landuse_filter_polygon_75pct/removed_commercial_75pct_minpoi20.parquet")
commercial_50 = gpd.read_parquet("data/landuse_filter_polygon_50pct/removed_commercial_50pct_minpoi20.parquet")

industrial_90 = gpd.read_parquet("data/landuse_filter_polygon_fast/removed_industrial_90pct_minpoi20.parquet")
industrial_75 = gpd.read_parquet("data/landuse_filter_polygon_75pct/removed_industrial_75pct_minpoi20.parquet")
industrial_50 = gpd.read_parquet("data/landuse_filter_polygon_50pct/removed_industrial_50pct_minpoi20.parquet")

# Get network IDs
comm_90_nets = set(commercial_90['network_number'].unique())
comm_75_nets = set(commercial_75['network_number'].unique())
comm_50_nets = set(commercial_50['network_number'].unique())

ind_90_nets = set(industrial_90['network_number'].unique())
ind_75_nets = set(industrial_75['network_number'].unique())
ind_50_nets = set(industrial_50['network_number'].unique())

# Find additional networks at each threshold
print("="*80)
print("ADDITIONAL NETWORKS REMOVED AT LOWER THRESHOLDS")
print("="*80)

# 75% vs 90%
comm_75_additional = comm_75_nets - comm_90_nets
ind_75_additional = ind_75_nets - ind_90_nets

print(f"\nCOMMERCIAL (75% vs 90%): {len(comm_75_additional)} additional networks")
if len(comm_75_additional) > 0:
    comm_75_add_data = centres[centres['network_number'].isin(comm_75_additional)]
    comm_75_add_pois = network_pois[network_pois['network_number'].isin(comm_75_additional)]
    print(f"  POI range: {comm_75_add_pois['total_pois'].min():.0f} - {comm_75_add_pois['total_pois'].max():.0f}")
    print(f"  Cells: {len(comm_75_add_data):,}")

    output_file = output_path / "additional_commercial_75pct_vs_90pct.parquet"
    comm_75_add_data.to_parquet(output_file)
    print(f"  Saved to: {output_file}")

print(f"\nINDUSTRIAL (75% vs 90%): {len(ind_75_additional)} additional networks")
if len(ind_75_additional) > 0:
    ind_75_add_data = centres[centres['network_number'].isin(ind_75_additional)]
    ind_75_add_pois = network_pois[network_pois['network_number'].isin(ind_75_additional)]
    print(f"  POI range: {ind_75_add_pois['total_pois'].min():.0f} - {ind_75_add_pois['total_pois'].max():.0f}")
    print(f"  Cells: {len(ind_75_add_data):,}")

    output_file = output_path / "additional_industrial_75pct_vs_90pct.parquet"
    ind_75_add_data.to_parquet(output_file)
    print(f"  Saved to: {output_file}")

# 50% vs 90%
comm_50_additional = comm_50_nets - comm_90_nets
ind_50_additional = ind_50_nets - ind_90_nets

print(f"\nCOMMERCIAL (50% vs 90%): {len(comm_50_additional)} additional networks")
if len(comm_50_additional) > 0:
    comm_50_add_data = centres[centres['network_number'].isin(comm_50_additional)]
    comm_50_add_pois = network_pois[network_pois['network_number'].isin(comm_50_additional)]
    print(f"  POI range: {comm_50_add_pois['total_pois'].min():.0f} - {comm_50_add_pois['total_pois'].max():.0f}")
    print(f"  Cells: {len(comm_50_add_data):,}")

    output_file = output_path / "additional_commercial_50pct_vs_90pct.parquet"
    comm_50_add_data.to_parquet(output_file)
    print(f"  Saved to: {output_file}")

print(f"\nINDUSTRIAL (50% vs 90%): {len(ind_50_additional)} additional networks")
if len(ind_50_additional) > 0:
    ind_50_add_data = centres[centres['network_number'].isin(ind_50_additional)]
    ind_50_add_pois = network_pois[network_pois['network_number'].isin(ind_50_additional)]
    print(f"  POI range: {ind_50_add_pois['total_pois'].min():.0f} - {ind_50_add_pois['total_pois'].max():.0f}")
    print(f"  Cells: {len(ind_50_add_data):,}")

    output_file = output_path / "additional_industrial_50pct_vs_90pct.parquet"
    ind_50_add_data.to_parquet(output_file)
    print(f"  Saved to: {output_file}")

# 50% vs 75%
comm_50_vs_75 = comm_50_nets - comm_75_nets
ind_50_vs_75 = ind_50_nets - ind_75_nets

print(f"\nCOMMERCIAL (50% vs 75%): {len(comm_50_vs_75)} additional networks")
if len(comm_50_vs_75) > 0:
    comm_50_vs_75_data = centres[centres['network_number'].isin(comm_50_vs_75)]
    comm_50_vs_75_pois = network_pois[network_pois['network_number'].isin(comm_50_vs_75)]
    print(f"  POI range: {comm_50_vs_75_pois['total_pois'].min():.0f} - {comm_50_vs_75_pois['total_pois'].max():.0f}")
    print(f"  Cells: {len(comm_50_vs_75_data):,}")

    output_file = output_path / "additional_commercial_50pct_vs_75pct.parquet"
    comm_50_vs_75_data.to_parquet(output_file)
    print(f"  Saved to: {output_file}")

print(f"\nINDUSTRIAL (50% vs 75%): {len(ind_50_vs_75)} additional networks")
if len(ind_50_vs_75) > 0:
    ind_50_vs_75_data = centres[centres['network_number'].isin(ind_50_vs_75)]
    ind_50_vs_75_pois = network_pois[network_pois['network_number'].isin(ind_50_vs_75)]
    print(f"  POI range: {ind_50_vs_75_pois['total_pois'].min():.0f} - {ind_50_vs_75_pois['total_pois'].max():.0f}")
    print(f"  Cells: {len(ind_50_vs_75_data):,}")

    output_file = output_path / "additional_industrial_50pct_vs_75pct.parquet"
    ind_50_vs_75_data.to_parquet(output_file)
    print(f"  Saved to: {output_file}")

print("\n" + "="*80)
print("Complete!")
print("="*80)
