#!/usr/bin/env python3
"""
Compare landuse filter results across different thresholds.
"""

import pandas as pd
import geopandas as gpd
from pathlib import Path

# Read all summaries
summaries = []

configs = [
    ("75% overlap, 20 POI", "data/landuse_filter_polygon_75pct"),
    ("90% overlap, 20 POI", "data/landuse_filter_polygon_fast"),
    ("90% overlap, 10 POI", "data/landuse_filter_polygon_90pct_poi10"),
    ("90% overlap, 30 POI", "data/landuse_filter_polygon_90pct_poi30"),
]

for config_name, path in configs:
    summary_path = Path(path) / "filter_summary.csv"
    if summary_path.exists():
        df = pd.read_csv(summary_path)
        df['config'] = config_name
        summaries.append(df)

combined = pd.concat(summaries, ignore_index=True)

# Pivot to make comparison easier
comparison = combined.pivot_table(
    index=['config', 'landuse_type'],
    values=['networks_high_overlap', 'networks_removed', 'networks_exempt', 'cells_removed'],
    aggfunc='first'
).reset_index()

print("="*80)
print("LANDUSE FILTER COMPARISON")
print("="*80)
print()
print(comparison.to_string(index=False))
print()

# Calculate differences between 75% and 90%
print("="*80)
print("IMPACT OF LOWERING THRESHOLD FROM 90% TO 75%")
print("="*80)
print()

def get_config_data(config_name, landuse):
    return combined[(combined['config'] == config_name) & (combined['landuse_type'] == landuse)].iloc[0]

for landuse in ['commercial', 'industrial']:
    data_90 = get_config_data("90% overlap, 20 POI", landuse)
    data_75 = get_config_data("75% overlap, 20 POI", landuse)

    print(f"{landuse.upper()}:")
    print(f"  High overlap networks: {data_90['networks_high_overlap']:.0f} → {data_75['networks_high_overlap']:.0f} (+{data_75['networks_high_overlap'] - data_90['networks_high_overlap']:.0f})")
    print(f"  Would be removed: {data_90['networks_removed']:.0f} → {data_75['networks_removed']:.0f} (+{data_75['networks_removed'] - data_90['networks_removed']:.0f})")
    print(f"  Exempt: {data_90['networks_exempt']:.0f} → {data_75['networks_exempt']:.0f} (+{data_75['networks_exempt'] - data_90['networks_exempt']:.0f})")
    print(f"  Cells removed: {data_90['cells_removed']:.0f} → {data_75['cells_removed']:.0f} (+{data_75['cells_removed'] - data_90['cells_removed']:.0f})")
    print()

# Calculate differences for POI threshold
print("="*80)
print("IMPACT OF POI THRESHOLD (at 90% overlap)")
print("="*80)
print()

for landuse in ['commercial', 'industrial']:
    data_10 = get_config_data("90% overlap, 10 POI", landuse)
    data_20 = get_config_data("90% overlap, 20 POI", landuse)
    data_30 = get_config_data("90% overlap, 30 POI", landuse)

    print(f"{landuse.upper()}:")
    print(f"  Networks removed: {data_10['networks_removed']:.0f} (POI≥10) → {data_20['networks_removed']:.0f} (POI≥20) → {data_30['networks_removed']:.0f} (POI≥30)")
    print(f"  Networks exempt: {data_10['networks_exempt']:.0f} (POI≥10) → {data_20['networks_exempt']:.0f} (POI≥20) → {data_30['networks_exempt']:.0f} (POI≥30)")
    print(f"  Difference (10→20): -{data_10['networks_removed'] - data_20['networks_removed']:.0f} removed, +{data_20['networks_exempt'] - data_10['networks_exempt']:.0f} exempt")
    print(f"  Difference (20→30): -{data_20['networks_removed'] - data_30['networks_removed']:.0f} removed, +{data_30['networks_exempt'] - data_20['networks_exempt']:.0f} exempt")
    print()

# Load network data to show which networks are different
print("="*80)
print("NETWORKS AFFECTED BY THRESHOLD CHANGES")
print("="*80)
print()

centres = gpd.read_parquet("data/output_files/nov2025_v10postcodefilter_foursquare_mrc_2_mri_1_mrn_10_mtf_6_splitthresh_1500_merge_y/3_afterfill.parquet")
network_pois = centres.groupby('network_number')['foursquare_count'].sum().reset_index()
network_pois.columns = ['network_number', 'total_pois']

# Compare 90% vs 75% for commercial
commercial_90 = gpd.read_parquet("data/landuse_filter_polygon_fast/removed_commercial_90pct_minpoi20.parquet")
commercial_75 = gpd.read_parquet("data/landuse_filter_polygon_75pct/removed_commercial_75pct_minpoi20.parquet")

networks_90 = set(commercial_90['network_number'].unique())
networks_75 = set(commercial_75['network_number'].unique())
new_in_75 = networks_75 - networks_90

print(f"COMMERCIAL: {len(new_in_75)} additional networks removed at 75% vs 90%")
if len(new_in_75) > 0:
    new_networks_info = network_pois[network_pois['network_number'].isin(new_in_75)].sort_values('total_pois', ascending=False)
    print(f"  POI range: {new_networks_info['total_pois'].min():.0f}-{new_networks_info['total_pois'].max():.0f}")
    print(f"  Networks with POIs in [10-14]: {((new_networks_info['total_pois'] >= 10) & (new_networks_info['total_pois'] < 15)).sum()}")
    print(f"  Networks with POIs in [15-19]: {((new_networks_info['total_pois'] >= 15) & (new_networks_info['total_pois'] < 20)).sum()}")
    print()

# Compare 90% vs 75% for industrial
industrial_90 = gpd.read_parquet("data/landuse_filter_polygon_fast/removed_industrial_90pct_minpoi20.parquet")
industrial_75 = gpd.read_parquet("data/landuse_filter_polygon_75pct/removed_industrial_75pct_minpoi20.parquet")

networks_90_ind = set(industrial_90['network_number'].unique())
networks_75_ind = set(industrial_75['network_number'].unique())
new_in_75_ind = networks_75_ind - networks_90_ind

print(f"INDUSTRIAL: {len(new_in_75_ind)} additional networks removed at 75% vs 90%")
if len(new_in_75_ind) > 0:
    new_networks_info_ind = network_pois[network_pois['network_number'].isin(new_in_75_ind)].sort_values('total_pois', ascending=False)
    print(f"  POI range: {new_networks_info_ind['total_pois'].min():.0f}-{new_networks_info_ind['total_pois'].max():.0f}")
    print(f"  Networks with POIs in [10-14]: {((new_networks_info_ind['total_pois'] >= 10) & (new_networks_info_ind['total_pois'] < 15)).sum()}")
    print(f"  Networks with POIs in [15-19]: {((new_networks_info_ind['total_pois'] >= 15) & (new_networks_info_ind['total_pois'] < 20)).sum()}")
    print()

# Save comparison
output_path = Path("data/landuse_filter_comparison")
output_path.mkdir(parents=True, exist_ok=True)

comparison.to_csv(output_path / "threshold_comparison.csv", index=False)
print(f"✓ Saved comparison to: {output_path / 'threshold_comparison.csv'}")

# Save detailed network differences
if len(new_in_75) > 0:
    new_networks_75_comm = centres[centres['network_number'].isin(new_in_75)]
    new_networks_75_comm.to_parquet(output_path / "additional_removed_75pct_commercial.parquet")
    print(f"✓ Saved additional commercial networks to: {output_path / 'additional_removed_75pct_commercial.parquet'}")

if len(new_in_75_ind) > 0:
    new_networks_75_ind = centres[centres['network_number'].isin(new_in_75_ind)]
    new_networks_75_ind.to_parquet(output_path / "additional_removed_75pct_industrial.parquet")
    print(f"✓ Saved additional industrial networks to: {output_path / 'additional_removed_75pct_industrial.parquet'}")
