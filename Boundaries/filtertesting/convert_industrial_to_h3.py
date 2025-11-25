#!/usr/bin/env python3
"""
Quick script to convert existing industrial landuse polygons to H3 cells.
"""
import pandas as pd
import geopandas as gpd
import h3
from tqdm import tqdm

print("Loading industrial landuse polygons...")
industrial_gdf = gpd.read_parquet("data/input_files/industrial_landuse.parquet")
print(f"Loaded {len(industrial_gdf):,} industrial polygons")

def get_h3_indices(geometry, resolution=13):
    """Convert geometry to H3 cells."""
    if geometry.geom_type == 'Polygon':
        coords = [(lat, lng) for lng, lat in geometry.exterior.coords]
    elif geometry.geom_type == 'MultiPolygon':
        coords = []
        for poly in geometry.geoms:
            coords.extend([(lat, lng) for lng, lat in poly.exterior.coords])
    else:
        return set()

    try:
        poly = h3.LatLngPoly(coords)
        return h3.h3shape_to_cells(poly, res=resolution)
    except Exception:
        return set()

print("\nConverting to H3 cells (resolution 13)...")
all_h3_cells = set()

for idx, row in tqdm(industrial_gdf.iterrows(), total=len(industrial_gdf), desc="Processing polygons"):
    h3_cells = get_h3_indices(row.geometry, resolution=13)
    all_h3_cells.update(h3_cells)

print(f"\nGenerated {len(all_h3_cells):,} unique H3 cells (resolution 13)")

# Derive parent resolution 11 cells
print("Deriving parent H3 cells (resolution 11)...")
h3_res11 = set(h3.cell_to_parent(cell, 11) for cell in all_h3_cells)
print(f"Generated {len(h3_res11):,} unique H3 cells (resolution 11)")

# Create DataFrame
h3_df = pd.DataFrame({
    'h3_11': list(h3_res11),
    'landuse': 'industrial'
})

# Save
output_path = "data/input_files/industrial_landuse_h3.parquet"
h3_df.to_parquet(output_path)
print(f"\n✓ Saved H3 data to {output_path}")
print(f"  {len(h3_df):,} H3 cells (resolution 11)")
