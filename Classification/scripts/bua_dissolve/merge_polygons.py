#!/usr/bin/env python3
"""Dissolve near-touching OS Open Built Up Area polygons."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
from shapely.ops import unary_union
from tqdm import tqdm


DEFAULT_INPUT = Path("geo/BuiltupAreaDisolve/data/os_open_built_up_areas.gpkg")
DEFAULT_OUTPUT = Path("geo/buildup/merged_BUA_dissolved2025.gpkg")
DEFAULT_BUFFER_DISTANCE = 100


def merge_nearby_polygons(
    input_gpkg: Path,
    output_gpkg: Path,
    buffer_distance: float = DEFAULT_BUFFER_DISTANCE,
    batch_size: int = 1000,
) -> None:
    print(f"Loading GeoPackage: {input_gpkg}")
    gdf = gpd.read_file(input_gpkg)

    print(f"Loaded {len(gdf):,} polygons")
    print(f"CRS: {gdf.crs}")

    print(f"\nMerging near-touching polygons (buffer distance: {buffer_distance:g}m)...")
    tqdm.pandas(desc="Buffering polygons")
    buffered = gdf.geometry.progress_apply(lambda geom: geom.buffer(buffer_distance))

    print("Performing union...")
    geoms = list(buffered)
    batches = [geoms[i : i + batch_size] for i in range(0, len(geoms), batch_size)]

    merged_batches = []
    for batch in tqdm(batches, desc="Unioning batches"):
        merged_batches.append(unary_union(batch))
    merged = unary_union(merged_batches)

    print("Applying negative buffer...")
    merged = merged.buffer(-buffer_distance)

    result_gdf = gpd.GeoDataFrame(geometry=[merged], crs=gdf.crs)
    result_gdf = result_gdf.explode(index_parts=False).reset_index(drop=True)

    print(f"Result: {len(result_gdf):,} polygons after merging")

    output_gpkg.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving to: {output_gpkg}")
    result_gdf.to_file(output_gpkg, driver="GPKG")
    print("Done.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dissolve OS Open Built Up Area polygons that are separated by small gaps."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input OS Open BUA GeoPackage.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output dissolved BUA GeoPackage.")
    parser.add_argument(
        "--buffer-distance",
        type=float,
        default=DEFAULT_BUFFER_DISTANCE,
        help="Positive/negative buffer distance in metres. Gaps up to roughly 2x this value are closed.",
    )
    parser.add_argument("--batch-size", type=int, default=1000, help="Geometry batch size for unary union.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    merge_nearby_polygons(
        input_gpkg=args.input,
        output_gpkg=args.output,
        buffer_distance=args.buffer_distance,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
