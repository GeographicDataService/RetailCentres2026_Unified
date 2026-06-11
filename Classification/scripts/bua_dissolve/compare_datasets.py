#!/usr/bin/env python3
"""Compare the dissolved BUA output with an ONS reference BUA dataset."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
from tqdm import tqdm


DEFAULT_MERGED = Path("geo/buildup/merged_BUA_dissolved2025.gpkg")
DEFAULT_REFERENCE = Path("geo/BuiltupAreaDisolve/data/Built_up_Areas_Dec_2011_Boundaries_V2_2022.gpkg")
DEFAULT_OUTPUT_DIR = Path("geo/BuiltupAreaDisolve/output")
DEFAULT_SIMPLIFY_TOLERANCE = 50


def compare_datasets(
    merged_gpkg: Path,
    reference_gpkg: Path,
    output_dir: Path,
    simplify_tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE,
) -> None:
    print("Loading datasets...")

    print(f"\nLoading merged data: {merged_gpkg}")
    merged_gdf = gpd.read_file(merged_gpkg)
    print(f"  Polygons: {len(merged_gdf):,}")
    print(f"  CRS: {merged_gdf.crs}")
    print(f"  Total area: {merged_gdf.geometry.area.sum():,.2f} sq metres")

    print(f"\nLoading reference data: {reference_gpkg}")
    ref_gdf = gpd.read_file(reference_gpkg)
    print(f"  Polygons: {len(ref_gdf):,}")
    print(f"  CRS: {ref_gdf.crs}")
    print(f"  Total area: {ref_gdf.geometry.area.sum():,.2f} sq metres")

    if merged_gdf.crs != ref_gdf.crs:
        print("\nReprojecting merged data to match reference CRS...")
        merged_gdf = merged_gdf.to_crs(ref_gdf.crs)

    print("\n--- Comparison Statistics ---")
    merged_total_area = merged_gdf.geometry.area.sum()
    ref_total_area = ref_gdf.geometry.area.sum()

    print(f"Merged total area:    {merged_total_area:,.2f} sq metres")
    print(f"Reference total area: {ref_total_area:,.2f} sq metres")
    print(f"Area difference:      {merged_total_area - ref_total_area:,.2f} sq metres")
    print(f"Area ratio:           {merged_total_area / ref_total_area:.4f}")

    print("\nCalculating spatial overlap...")
    merged_union = merged_gdf.union_all()
    ref_union = ref_gdf.union_all()

    intersection_area = merged_union.intersection(ref_union).area
    union_area = merged_union.union(ref_union).area
    iou = intersection_area / union_area if union_area > 0 else 0

    print(f"Intersection area:    {intersection_area:,.2f} sq metres")
    print(f"Union area:           {union_area:,.2f} sq metres")
    print(f"IoU (Jaccard index):  {iou:.4f}")

    merged_covered = intersection_area / merged_total_area if merged_total_area > 0 else 0
    ref_covered = intersection_area / ref_total_area if ref_total_area > 0 else 0

    print(f"\n% of merged covered by reference: {merged_covered * 100:.2f}%")
    print(f"% of reference covered by merged: {ref_covered * 100:.2f}%")

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n--- Creating simplified GeoParquet files (tolerance: {simplify_tolerance:g}m) ---")

    print("Simplifying merged data...")
    tqdm.pandas(desc="Simplifying merged")
    merged_simplified = merged_gdf.copy()
    merged_simplified.geometry = merged_gdf.geometry.progress_apply(
        lambda geom: geom.simplify(simplify_tolerance, preserve_topology=True)
    )
    merged_path = output_dir / "merged_bua_simplified.parquet"
    merged_simplified.to_parquet(merged_path)
    print(f"  Saved: {merged_path}")

    print("Simplifying reference data...")
    tqdm.pandas(desc="Simplifying reference")
    ref_simplified = ref_gdf.copy()
    ref_simplified.geometry = ref_gdf.geometry.progress_apply(
        lambda geom: geom.simplify(simplify_tolerance, preserve_topology=True)
    )
    ref_path = output_dir / "reference_bua_simplified.parquet"
    ref_simplified.to_parquet(ref_path)
    print(f"  Saved: {ref_path}")

    print("\nDone.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare dissolved BUA output with an ONS reference dataset.")
    parser.add_argument("--merged", type=Path, default=DEFAULT_MERGED, help="Dissolved BUA GeoPackage.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE, help="Reference ONS BUA GeoPackage.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for comparison outputs.")
    parser.add_argument(
        "--simplify-tolerance",
        type=float,
        default=DEFAULT_SIMPLIFY_TOLERANCE,
        help="Simplification tolerance in metres for lightweight comparison outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    compare_datasets(
        merged_gpkg=args.merged,
        reference_gpkg=args.reference,
        output_dir=args.output_dir,
        simplify_tolerance=args.simplify_tolerance,
    )


if __name__ == "__main__":
    main()
