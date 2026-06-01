#!/usr/bin/env python3
"""
Compare merged BUA output with the reference Built_up_Areas GeoPackage.
"""

import geopandas as gpd
from tqdm import tqdm

# Configuration
MERGED_GPKG = "output/merged_bua.gpkg"
REFERENCE_GPKG = "data/Built_up_Areas_Dec_2011_Boundaries_V2_2022.gpkg"
SIMPLIFY_TOLERANCE = 50  # meters - for reduced resolution output

def main():
    print("Loading datasets...")

    # Load merged result
    print(f"\nLoading merged data: {MERGED_GPKG}")
    merged_gdf = gpd.read_file(MERGED_GPKG)
    print(f"  Polygons: {len(merged_gdf)}")
    print(f"  CRS: {merged_gdf.crs}")
    print(f"  Total area: {merged_gdf.geometry.area.sum():,.2f} sq meters")

    # Load reference
    print(f"\nLoading reference data: {REFERENCE_GPKG}")
    ref_gdf = gpd.read_file(REFERENCE_GPKG)
    print(f"  Polygons: {len(ref_gdf)}")
    print(f"  CRS: {ref_gdf.crs}")
    print(f"  Total area: {ref_gdf.geometry.area.sum():,.2f} sq meters")

    # Ensure same CRS for comparison
    if merged_gdf.crs != ref_gdf.crs:
        print(f"\nReprojecting merged data to match reference CRS...")
        merged_gdf = merged_gdf.to_crs(ref_gdf.crs)

    # Calculate overlap statistics
    print("\n--- Comparison Statistics ---")

    merged_total_area = merged_gdf.geometry.area.sum()
    ref_total_area = ref_gdf.geometry.area.sum()

    print(f"Merged total area:    {merged_total_area:,.2f} sq meters")
    print(f"Reference total area: {ref_total_area:,.2f} sq meters")
    print(f"Area difference:      {merged_total_area - ref_total_area:,.2f} sq meters")
    print(f"Area ratio:           {merged_total_area / ref_total_area:.4f}")

    # Calculate intersection (overlap) area
    print("\nCalculating spatial overlap...")
    merged_union = merged_gdf.union_all()
    ref_union = ref_gdf.union_all()

    intersection = merged_union.intersection(ref_union)
    intersection_area = intersection.area

    union = merged_union.union(ref_union)
    union_area = union.area

    # IoU (Intersection over Union) - common similarity metric
    iou = intersection_area / union_area if union_area > 0 else 0

    print(f"Intersection area:    {intersection_area:,.2f} sq meters")
    print(f"Union area:           {union_area:,.2f} sq meters")
    print(f"IoU (Jaccard index):  {iou:.4f}")

    # Coverage percentages
    merged_covered = intersection_area / merged_total_area if merged_total_area > 0 else 0
    ref_covered = intersection_area / ref_total_area if ref_total_area > 0 else 0

    print(f"\n% of merged covered by reference: {merged_covered * 100:.2f}%")
    print(f"% of reference covered by merged: {ref_covered * 100:.2f}%")

    # Create simplified versions for faster viewing
    print(f"\n--- Creating simplified geoparquet files (tolerance: {SIMPLIFY_TOLERANCE}m) ---")

    print("Simplifying merged data...")
    tqdm.pandas(desc="Simplifying merged")
    merged_simplified = merged_gdf.copy()
    merged_simplified.geometry = merged_gdf.geometry.progress_apply(
        lambda g: g.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    )
    merged_simplified.to_parquet("output/merged_bua_simplified.parquet")
    print(f"  Saved: merged_bua_simplified.parquet")

    print("Simplifying reference data...")
    tqdm.pandas(desc="Simplifying reference")
    ref_simplified = ref_gdf.copy()
    ref_simplified.geometry = ref_gdf.geometry.progress_apply(
        lambda g: g.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
    )
    ref_simplified.to_parquet("output/reference_bua_simplified.parquet")
    print(f"  Saved: reference_bua_simplified.parquet")

    print("\nDone!")

if __name__ == "__main__":
    main()
