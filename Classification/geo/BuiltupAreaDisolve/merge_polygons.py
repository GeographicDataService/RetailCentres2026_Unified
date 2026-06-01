#!/usr/bin/env python3
"""
Load polygons from BUA_data and merge touching or near-touching polygons.
Outputs a GeoPackage with the merged result.
"""

import geopandas as gpd
from shapely.ops import unary_union
from tqdm import tqdm

# Configuration
INPUT_GPKG = "data/os_open_built_up_areas.gpkg"
OUTPUT_GPKG = "output/merged_bua.gpkg"
BUFFER_DISTANCE = 100  # meters - closes gaps < 200m

def main():
    print(f"Loading GeoPackage: {INPUT_GPKG}")
    gdf = gpd.read_file(INPUT_GPKG)

    print(f"Loaded {len(gdf)} polygons")
    print(f"CRS: {gdf.crs}")

    # Method 1: Simple dissolve (merges only truly touching/overlapping polygons)
    print("\nDissolving touching polygons...")
    dissolved = gdf.dissolve()

    # Method 2: Buffer-dissolve-negative buffer (merges near-touching polygons)
    # This expands polygons, merges them, then shrinks back
    print(f"\nMerging near-touching polygons (buffer distance: {BUFFER_DISTANCE}m)...")

    # Buffer all geometries outward
    tqdm.pandas(desc="Buffering polygons")
    buffered = gdf.geometry.progress_apply(lambda g: g.buffer(BUFFER_DISTANCE))

    # Union all buffered geometries in batches for progress tracking
    print("Performing union...")
    batch_size = 1000
    geoms = list(buffered)
    batches = [geoms[i:i+batch_size] for i in range(0, len(geoms), batch_size)]

    merged_batches = []
    for batch in tqdm(batches, desc="Unioning batches"):
        merged_batches.append(unary_union(batch))
    merged = unary_union(merged_batches)

    # Buffer back inward to restore approximate original size
    print("Applying negative buffer...")
    merged = merged.buffer(-BUFFER_DISTANCE)

    # Convert back to GeoDataFrame
    result_gdf = gpd.GeoDataFrame(geometry=[merged], crs=gdf.crs)

    # Explode multipolygons into individual polygons
    result_gdf = result_gdf.explode(index_parts=False).reset_index(drop=True)

    print(f"Result: {len(result_gdf)} polygons after merging")

    # Save to GeoPackage
    print(f"\nSaving to: {OUTPUT_GPKG}")
    result_gdf.to_file(OUTPUT_GPKG, driver="GPKG")

    print("Done!")

if __name__ == "__main__":
    main()
