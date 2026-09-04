#!/usr/bin/env python
"""
Build an H3 res-11 cell -> retail centre lookup CSV from the final bounds.

The boundaries are dissolved from H3 res-11 cells, but the cell membership is
never published: the cell-level intermediates are keyed by the pre-split
network number, not the final ID. This script recovers the cell list from the
finished bounds and (by default) verifies it by rebuilding the boundaries from
the cells and comparing them to the input.

Output columns: Retail_ID,H3_11

Usage:
    python scripts/build_h3_lookup.py --bounds Naming/exports/retailcentre_bounds_uk.gpkg
    python scripts/build_h3_lookup.py --bounds <path> --output rc_h3.csv --diff-out diffs.gpkg
    python scripts/build_h3_lookup.py --bounds <path> --no-verify
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon

# H3 resolution the boundaries are built from (see Boundaries/src/utils/utils.py).
H3_RES = 11
# Metric CRS the pipeline dissolves cells in; comparisons happen here.
METRIC_CRS = "EPSG:27700"
# CRS H3 cell boundaries are constructed in before reprojection.
GEO_CRS = "EPSG:4326"
# Matches utils.fill_holes: effectively fills every hole.
FILL_HOLES_THRESHOLD = 2000 * 1e6


def read_bounds(path: Path) -> gpd.GeoDataFrame:
    """Read a bounds file, dispatching on suffix."""
    if path.suffix.lower() == ".parquet":
        return gpd.read_parquet(path)
    return gpd.read_file(path)


def polygon_to_cells(geom, resolution: int = H3_RES) -> set:
    """H3 cells covering a (Multi)Polygon, by cell-centre containment.

    Direct res-11 fill rather than the res-13 -> cell_to_parent idiom used
    elsewhere in the repo: the input here *is* a union of res-11 hexes, so
    centre containment returns exactly the original cells, whereas going via
    res-13 parents would pull in cells along the edge.
    """
    if isinstance(geom, Polygon):
        parts = [geom]
    elif isinstance(geom, MultiPolygon):
        parts = list(geom.geoms)
    else:
        return set()

    cells = set()
    for part in parts:
        # h3 wants (lat, lng); shapely coords are (lng, lat).
        exterior = [(lat, lng) for lng, lat in part.exterior.coords]
        holes = [[(lat, lng) for lng, lat in ring.coords] for ring in part.interiors]
        cells.update(h3.h3shape_to_cells(h3.LatLngPoly(exterior, *holes), res=resolution))
    return cells


def cells_to_geoframe(df: pd.DataFrame, cell_col: str = "H3_11") -> gpd.GeoDataFrame:
    """Cell IDs -> hexagon polygons in the metric CRS (mirrors utils.to_geoframe)."""
    df = df.copy()
    boundaries = df[cell_col].apply(h3.cell_to_boundary)
    # swap the lat lon to lon lat
    df["geometry"] = boundaries.apply(lambda ring: Polygon([(lng, lat) for lat, lng in ring]))
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=GEO_CRS)
    return gdf.to_crs(METRIC_CRS)


def fill_holes(geometry, threshold: float = FILL_HOLES_THRESHOLD):
    """Fill holes in polygons smaller than the threshold (copy of utils.fill_holes)."""
    if isinstance(geometry, Polygon):
        interiors = [ring for ring in geometry.interiors if ring.area > threshold]
        return Polygon(geometry.exterior, interiors)
    elif isinstance(geometry, MultiPolygon):
        return MultiPolygon([fill_holes(p, threshold) for p in geometry.geoms])
    return geometry


def build_lookup(bounds: gpd.GeoDataFrame, id_column: str) -> pd.DataFrame:
    """Build the Retail_ID / H3_11 table from centre polygons."""
    bounds = bounds.to_crs(GEO_CRS)

    rows = []
    for centre_id, geom in zip(bounds[id_column], bounds.geometry):
        for cell in polygon_to_cells(geom):
            rows.append((centre_id, cell))

    lookup = pd.DataFrame(rows, columns=["Retail_ID", "H3_11"])
    return lookup.sort_values(["Retail_ID", "H3_11"], kind="stable").reset_index(drop=True)


def normalise_ids(ids: pd.Series) -> pd.Series:
    """Coerce centre IDs to integers where possible.

    GeoPackage stores RC_ID as a string while the parquet bounds store int64;
    without this the IDs sort as text (1, 10, 100, 1000) instead of numerically.
    Left untouched if any value is non-numeric.
    """
    numeric = pd.to_numeric(ids, errors="coerce")
    if numeric.isna().any():
        return ids
    return numeric.astype("int64")


def check_disjoint(lookup: pd.DataFrame) -> int:
    """Report cells claimed by more than one centre. Returns the offending count."""
    counts = lookup.groupby("H3_11")["Retail_ID"].nunique()
    shared = counts[counts > 1]
    if len(shared) == 0:
        print("  ✓ No cell is claimed by more than one centre")
        return 0

    print(f"  ✗ {len(shared):,} cells are claimed by more than one centre:")
    for cell in shared.index[:10]:
        ids = sorted(lookup.loc[lookup["H3_11"] == cell, "Retail_ID"].unique())
        print(f"      {cell}: {ids}")
    if len(shared) > 10:
        print(f"      ... and {len(shared) - 10:,} more")
    return len(shared)


def report_h3_count_column(bounds: gpd.GeoDataFrame, lookup: pd.DataFrame, id_column: str) -> None:
    """Informational comparison against the H3 count carried in the bounds.

    That column comes from `trackNodes` aggregated with 'first' on pre-split
    networks, so disagreement for split centres is expected. Diagnostic only.
    """
    col = next((c for c in ("H3_cells", "H3_count", "# H3 cells") if c in bounds.columns), None)
    if col is None:
        return

    derived = lookup.groupby("Retail_ID").size().rename("derived")
    stated = bounds.set_index(id_column)[col].rename("stated")
    joined = pd.concat([derived, stated], axis=1).dropna()
    agree = int((joined["derived"] == joined["stated"]).sum())
    print(
        f"  Cells per centre vs '{col}' column: {agree:,}/{len(joined):,} agree "
        f"(informational — '{col}' is a pre-split network count)"
    )


def count_vertices(geom) -> int:
    """Total vertices across all rings of a (Multi)Polygon."""
    if isinstance(geom, Polygon):
        return len(geom.exterior.coords) + sum(len(r.coords) for r in geom.interiors)
    elif isinstance(geom, MultiPolygon):
        return sum(count_vertices(p) for p in geom.geoms)
    return 0


def verify(
    bounds: gpd.GeoDataFrame,
    lookup: pd.DataFrame,
    id_column: str,
    diff_out: Path | None,
    tolerance: float,
) -> bool:
    """Rebuild the boundaries from the cell list and compare to the input."""
    print("\nRebuilding boundaries from the cell list...")
    cells = cells_to_geoframe(lookup)
    rebuilt = cells.dissolve(by="Retail_ID", as_index=False)[["Retail_ID", "geometry"]]
    rebuilt["geometry"] = rebuilt["geometry"].apply(fill_holes)
    print(f"  Rebuilt {len(rebuilt):,} centres from {len(cells):,} cells")

    original = bounds.to_crs(METRIC_CRS)[[id_column, "geometry"]].rename(columns={id_column: "Retail_ID"})

    original_ids = set(original["Retail_ID"])
    rebuilt_ids = set(rebuilt["Retail_ID"])
    missing = original_ids - rebuilt_ids
    invented = rebuilt_ids - original_ids
    if missing or invented:
        print(f"  ✗ ID sets differ: {len(missing):,} missing, {len(invented):,} invented")
        for centre_id in sorted(missing)[:10]:
            print(f"      missing: {centre_id}")
        for centre_id in sorted(invented)[:10]:
            print(f"      invented: {centre_id}")
    else:
        print(f"  ✓ ID sets identical ({len(original_ids):,} centres)")

    merged = original.merge(rebuilt, on="Retail_ID", suffixes=("_orig", "_rebuilt"))
    orig_geom = gpd.GeoSeries(merged["geometry_orig"], crs=METRIC_CRS).normalize()
    rebuilt_geom = gpd.GeoSeries(merged["geometry_rebuilt"], crs=METRIC_CRS).normalize()

    # Vertex-for-vertex identity, allowing only sub-centimetre drift. The published
    # bounds were dissolved in EPSG:27700 and stored reprojected to EPSG:4326, so a
    # rebuild from cells goes through one more WGS84<->OSGB36 datum transform than
    # they did; that round trip is not the identity and leaves ~3 mm of noise. The
    # tolerance absorbs exactly that and nothing larger — a genuinely different cell
    # set moves a boundary by tens of metres, not millimetres.
    same_vertices = pd.Series(
        [count_vertices(a) == count_vertices(b) for a, b in zip(orig_geom, rebuilt_geom)],
        index=merged.index,
    )
    matches = orig_geom.geom_equals_exact(rebuilt_geom, tolerance) & same_vertices

    n_match = int(matches.sum())
    print(f"  Vertex counts identical: {int(same_vertices.sum()):,}/{len(merged):,} centres")
    print(f"  Geometry equal within {tolerance} m: {n_match:,}/{len(merged):,} centres")
    print(f"  Max vertex displacement: {orig_geom.hausdorff_distance(rebuilt_geom).max() * 1000:.3f} mm")

    # Re-fill the rebuilt polygons and check the cells come back. Geometry equality
    # alone cannot see a missing *interior* cell: the gap it leaves is closed again
    # by fill_holes, so the polygon is unchanged. Re-deriving the cells from the
    # rebuild catches that, because the filled polygon yields the cell back.
    refilled = (
        gpd.GeoSeries(merged["geometry_rebuilt"], crs=METRIC_CRS)
        .to_crs(GEO_CRS)
        .apply(polygon_to_cells)
    )
    stated_cells = lookup.groupby("Retail_ID")["H3_11"].apply(set)
    cell_matches = pd.Series(
        [
            refilled.iloc[i] == stated_cells.get(merged["Retail_ID"].iloc[i], set())
            for i in range(len(merged))
        ],
        index=merged.index,
    )
    n_cell_match = int(cell_matches.sum())
    print(f"  Cell sets round-trip: {n_cell_match:,}/{len(merged):,} centres")
    if n_cell_match < len(merged):
        for _, row in merged[~cell_matches.values].head(10).iterrows():
            i = merged.index.get_loc(row.name)
            derived = refilled.iloc[i]
            stated = stated_cells.get(row["Retail_ID"], set())
            print(
                f"      Retail_ID {row['Retail_ID']}: "
                f"{len(stated - derived):,} cells in CSV but not in the rebuild, "
                f"{len(derived - stated):,} in the rebuild but not the CSV"
            )
    matches = matches & cell_matches

    failed = merged[~matches.values].copy()
    if len(failed) > 0:
        failed_orig = gpd.GeoSeries(failed["geometry_orig"], crs=METRIC_CRS)
        failed_rebuilt = gpd.GeoSeries(failed["geometry_rebuilt"], crs=METRIC_CRS)
        failed["sym_diff_m2"] = failed_orig.symmetric_difference(failed_rebuilt).area
        failed["orig_area_m2"] = failed_orig.area
        failed["sym_diff_frac"] = failed["sym_diff_m2"] / failed["orig_area_m2"]
        failed = failed.sort_values("sym_diff_frac", ascending=False)

        print(f"  ✗ {len(failed):,} centres do not match. Worst offenders:")
        for _, row in failed.head(10).iterrows():
            print(
                f"      Retail_ID {row['Retail_ID']}: "
                f"sym diff {row['sym_diff_m2']:,.1f} m² "
                f"({row['sym_diff_frac'] * 100:.4f}% of centre)"
            )

        if diff_out is not None:
            out = gpd.GeoDataFrame(
                failed[["Retail_ID", "sym_diff_m2", "orig_area_m2", "sym_diff_frac"]],
                geometry=failed_orig.symmetric_difference(failed_rebuilt).values,
                crs=METRIC_CRS,
            )
            out.to_file(diff_out, driver="GPKG")
            print(f"  Wrote differences to {diff_out}")
    else:
        print("  ✓ Every centre rebuilt to the same geometry")

    return not (missing or invented) and len(failed) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bounds", required=True, type=Path, help="Final bounds file (.gpkg/.parquet/.geojson)")
    parser.add_argument("--output", type=Path, help="Output CSV (default: retailcentre_h3_lookup.csv beside --bounds)")
    parser.add_argument("--id-column", default="RC_ID", help="Centre ID column in the bounds (default: RC_ID)")
    parser.add_argument("--no-verify", action="store_true", help="Skip the rebuild-and-compare verification")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing output file")
    parser.add_argument("--diff-out", type=Path, help="Write mismatching centres to this GeoPackage")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.01,
        help="Max per-vertex displacement in metres allowed when comparing (default: 0.01)",
    )
    args = parser.parse_args()

    output = args.output or args.bounds.parent / "retailcentre_h3_lookup.csv"
    if output.exists() and not args.overwrite:
        print(f"ERROR: {output} already exists. Pass --overwrite to replace it.")
        return 1

    print("=" * 80)
    print("BUILDING H3 CELL -> RETAIL CENTRE LOOKUP")
    print("=" * 80)
    print(f"Bounds:     {args.bounds}")
    print(f"Output:     {output}")
    print(f"ID column:  {args.id_column} -> Retail_ID")
    print(f"h3 version: {h3.versions()['python']}")

    bounds = read_bounds(args.bounds)
    if args.id_column not in bounds.columns:
        print(f"ERROR: column '{args.id_column}' not in bounds. Available: {list(bounds.columns)}")
        return 1
    bounds[args.id_column] = normalise_ids(bounds[args.id_column])
    crs_name = bounds.crs.srs if bounds.crs else "no CRS"
    print(f"\nRead {len(bounds):,} centres ({crs_name}, {args.id_column} as {bounds[args.id_column].dtype})")

    print(f"\nFilling centres with res-{H3_RES} cells...")
    lookup = build_lookup(bounds, args.id_column)
    print(f"  {len(lookup):,} cells across {lookup['Retail_ID'].nunique():,} centres")

    n_shared = check_disjoint(lookup)
    report_h3_count_column(bounds, lookup, args.id_column)

    empty = set(bounds[args.id_column]) - set(lookup["Retail_ID"])
    if empty:
        print(f"  ✗ {len(empty):,} centres produced no cells: {sorted(empty)[:10]}")

    output.parent.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(output, index=False)
    print(f"\nWrote {output}")

    ok = n_shared == 0 and not empty
    if not args.no_verify:
        print("\n" + "=" * 80)
        print("VERIFICATION")
        print("=" * 80)
        ok = verify(bounds, lookup, args.id_column, args.diff_out, args.tolerance) and ok

    print("\n" + "=" * 80)
    print("PASS: lookup round-trips to the input boundaries" if ok else "FAIL: see errors above")
    print("=" * 80)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
