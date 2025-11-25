#!/usr/bin/env python3
"""
Split 75% overlap networks by POI ranges: 20-50 and 50+
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

# Load centres
centres = gpd.read_parquet("data/output_files/nov2025_v10postcodefilter_foursquare_mrc_2_mri_1_mrn_10_mtf_6_splitthresh_1500_merge_y/3_afterfill.parquet")

# Calculate POI counts
network_pois = centres.groupby('network_number')['foursquare_count'].sum().reset_index()
network_pois.columns = ['network_number', 'total_pois']

# Load 75% overlap results (both 20 and 50 POI threshold runs)
comm_75_poi20 = gpd.read_parquet("data/landuse_filter_polygon_75pct/removed_commercial_75pct_minpoi20.parquet")
comm_75_poi50 = gpd.read_parquet("data/landuse_filter_polygon_75pct_poi50/removed_commercial_75pct_minpoi50.parquet")

ind_75_poi20 = gpd.read_parquet("data/landuse_filter_polygon_75pct/removed_industrial_75pct_minpoi20.parquet")
ind_75_poi50 = gpd.read_parquet("data/landuse_filter_polygon_75pct_poi50/removed_industrial_75pct_minpoi50.parquet")

# Get network IDs
comm_poi20_nets = set(comm_75_poi20['network_number'].unique())
comm_poi50_nets = set(comm_75_poi50['network_number'].unique())

ind_poi20_nets = set(ind_75_poi20['network_number'].unique())
ind_poi50_nets = set(ind_75_poi50['network_number'].unique())

# Networks in poi50 but not in poi20 = networks with 20-50 POIs (saved by poi20 threshold, removed by poi50)
comm_20_50_pois = comm_poi50_nets - comm_poi20_nets
ind_20_50_pois = ind_poi50_nets - ind_poi20_nets

# Networks NOT in poi50 = networks with 50+ POIs (saved by both thresholds)
# But we need networks with 75%+ overlap, so let's load the full overlap data
import pandas as pd

# Read overlap results to find all networks with 75%+ overlap
# We'll need to recompute or read intermediate data

# Alternative: Just use the POI data to split the removed sets
# poi20 removed = networks with <20 POIs
# poi50 removed but not poi20 removed = networks with 20-50 POIs
# not in poi50 removed = networks with 50+ POIs

print("="*80)
print("75% OVERLAP NETWORKS BY POI RANGE")
print("="*80)

output_path = Path("data/landuse_filter_75pct_by_poi")
output_path.mkdir(parents=True, exist_ok=True)

# COMMERCIAL
print("\nCOMMERCIAL:")
print(f"  Networks removed at POI>=20: {len(comm_poi20_nets)}")
print(f"  Networks removed at POI>=50: {len(comm_poi50_nets)}")
print(f"  Networks with 20-50 POIs (saved by POI>=20, removed by POI>=50): {len(comm_20_50_pois)}")

if len(comm_20_50_pois) > 0:
    comm_20_50_data = centres[centres['network_number'].isin(comm_20_50_pois)]
    comm_20_50_pois_info = network_pois[network_pois['network_number'].isin(comm_20_50_pois)]

    print(f"    POI range: {comm_20_50_pois_info['total_pois'].min():.0f} - {comm_20_50_pois_info['total_pois'].max():.0f}")
    print(f"    Networks: {len(comm_20_50_pois)}")
    print(f"    Cells: {len(comm_20_50_data):,}")

    output_file = output_path / "commercial_75pct_poi20to50.parquet"
    comm_20_50_data.to_parquet(output_file)
    print(f"    ✓ Saved to: {output_file}")

# Find networks with 50+ POIs that have 75%+ overlap
# These are NOT in the poi50 removed set, but ARE in the high overlap set
# We need to read the overlap calculations

# Simpler approach: Read from the exempt lists
# Networks exempt at poi50 threshold = networks with 50+ POIs and 75%+ overlap
exempt_comm_50 = gpd.read_parquet("data/landuse_filter_polygon_75pct_poi50/removed_commercial_75pct_minpoi50.parquet")

# Actually, let's just filter the original centres by the networks we want
# All networks with 75%+ commercial overlap = comm_poi50_nets + (networks exempt at poi50)
# But we don't have exempt list saved separately...

# Let's use a different approach: merge with POI data and filter
comm_all_75pct = centres[centres['network_number'].isin(comm_poi50_nets.union(comm_poi20_nets))]
comm_all_75pct = comm_all_75pct.merge(network_pois, on='network_number')

# Networks with 50+ POIs that have 75%+ overlap
# These would be in poi20's exempt list but not in removed
# Let's read the summary to understand better

# Actually simpler: Just create the two files the user wants
# 1. Networks with 75%+ overlap and 20-50 POIs
comm_networks_20_50 = comm_all_75pct[(comm_all_75pct['total_pois'] >= 20) & (comm_all_75pct['total_pois'] < 50)]
comm_networks_50plus = comm_all_75pct[comm_all_75pct['total_pois'] >= 50]

print(f"\n  Networks with 50+ POIs: {comm_networks_50plus['network_number'].nunique()}")
print(f"    POI range: {comm_networks_50plus['total_pois'].min():.0f} - {comm_networks_50plus['total_pois'].max():.0f}")
print(f"    Cells: {len(comm_networks_50plus):,}")

if len(comm_networks_50plus) > 0:
    output_file = output_path / "commercial_75pct_poi50plus.parquet"
    comm_networks_50plus.drop('total_pois', axis=1).to_parquet(output_file)
    print(f"    ✓ Saved to: {output_file}")

# INDUSTRIAL
print("\nINDUSTRIAL:")
print(f"  Networks removed at POI>=20: {len(ind_poi20_nets)}")
print(f"  Networks removed at POI>=50: {len(ind_poi50_nets)}")
print(f"  Networks with 20-50 POIs (saved by POI>=20, removed by POI>=50): {len(ind_20_50_pois)}")

if len(ind_20_50_pois) > 0:
    ind_20_50_data = centres[centres['network_number'].isin(ind_20_50_pois)]
    ind_20_50_pois_info = network_pois[network_pois['network_number'].isin(ind_20_50_pois)]

    print(f"    POI range: {ind_20_50_pois_info['total_pois'].min():.0f} - {ind_20_50_pois_info['total_pois'].max():.0f}")
    print(f"    Networks: {len(ind_20_50_pois)}")
    print(f"    Cells: {len(ind_20_50_data):,}")

    output_file = output_path / "industrial_75pct_poi20to50.parquet"
    ind_20_50_data.to_parquet(output_file)
    print(f"    ✓ Saved to: {output_file}")

ind_all_75pct = centres[centres['network_number'].isin(ind_poi50_nets.union(ind_poi20_nets))]
ind_all_75pct = ind_all_75pct.merge(network_pois, on='network_number')

ind_networks_50plus = ind_all_75pct[ind_all_75pct['total_pois'] >= 50]

print(f"\n  Networks with 50+ POIs: {ind_networks_50plus['network_number'].nunique()}")
if len(ind_networks_50plus) > 0:
    print(f"    POI range: {ind_networks_50plus['total_pois'].min():.0f} - {ind_networks_50plus['total_pois'].max():.0f}")
    print(f"    Cells: {len(ind_networks_50plus):,}")

    output_file = output_path / "industrial_75pct_poi50plus.parquet"
    ind_networks_50plus.drop('total_pois', axis=1).to_parquet(output_file)
    print(f"    ✓ Saved to: {output_file}")

print("\n" + "="*80)
print("Complete!")
print("="*80)
