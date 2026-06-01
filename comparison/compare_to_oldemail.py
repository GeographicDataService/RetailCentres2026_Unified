"""
Compare current naming output to the snapshot in retailcentre_bounds_uk_oldemail.parquet.

Checks: RC_ID set, RC_Name, Classification, Country, Region_NM, Retail_N, H3_count,
Area_km2, and geometry (extent + shape).
"""
import os
import sys
import geopandas as gpd
import pandas as pd
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OLD_PATH = os.path.join(DATA_DIR, "retailcentre_bounds_uk_oldemail.parquet")
NEW_PATH = os.path.join(DATA_DIR, "retailcentre_bounds_uk.parquet")

WORKING_CRS = 27700  # compare geometry in BNG metres


def load(path):
    gdf = gpd.read_parquet(path).to_crs(WORKING_CRS)
    gdf["RC_ID"] = gdf["RC_ID"].astype(str)
    return gdf


def compare_column(old, new, col):
    merged = old[["RC_ID", col]].merge(
        new[["RC_ID", col]], on="RC_ID", how="outer", suffixes=("_old", "_new")
    )
    a, b = merged[f"{col}_old"], merged[f"{col}_new"]
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
        diff = ~np.isclose(a.fillna(-9e9), b.fillna(-9e9), rtol=1e-4, atol=1e-6)
    else:
        diff = a.fillna("").astype(str) != b.fillna("").astype(str)
    n_diff = int(diff.sum())
    print(f"  {col}: {n_diff} differ ({n_diff / len(merged):.2%})")
    return merged[diff].head(20)


def compare_geometry(old, new):
    merged = old[["RC_ID", "geometry"]].merge(
        new[["RC_ID", "geometry"]], on="RC_ID", how="inner", suffixes=("_old", "_new")
    )
    g_old = gpd.GeoSeries(merged["geometry_old"], crs=WORKING_CRS)
    g_new = gpd.GeoSeries(merged["geometry_new"], crs=WORKING_CRS)

    # Bounds (extent) per centre
    b_old = g_old.bounds
    b_new = g_new.bounds
    bounds_diff = ~np.isclose(b_old.values, b_new.values, atol=1.0).all(axis=1)
    print(f"  bounds (extent): {int(bounds_diff.sum())} differ by >1m")

    # Area
    a_old = g_old.area
    a_new = g_new.area
    area_rel_diff = (a_new - a_old).abs() / a_old.replace(0, np.nan)
    big_area = (area_rel_diff > 0.001).fillna(False)
    print(f"  area: {int(big_area.sum())} differ by >0.1%")

    # Shape equivalence (symmetric difference area / total area)
    sym = g_old.symmetric_difference(g_new, align=False).area
    union = g_old.union(g_new, align=False).area.replace(0, np.nan)
    iou_miss = (sym / union).fillna(0)
    shape_diff = iou_miss > 0.001
    print(f"  shape (sym-diff / union > 0.1%): {int(shape_diff.sum())}")

    return merged.assign(area_rel_diff=area_rel_diff, sym_over_union=iou_miss)


def main():
    if not os.path.exists(OLD_PATH):
        sys.exit(f"Missing: {OLD_PATH}")
    if not os.path.exists(NEW_PATH):
        sys.exit(f"Missing: {NEW_PATH}")

    print(f"OLD: {OLD_PATH}")
    print(f"NEW: {NEW_PATH}\n")

    old = load(OLD_PATH)
    new = load(NEW_PATH)

    print(f"Row counts: old={len(old)}  new={len(new)}")

    old_ids, new_ids = set(old["RC_ID"]), set(new["RC_ID"])
    only_old = old_ids - new_ids
    only_new = new_ids - old_ids
    print(f"RC_IDs only in OLD: {len(only_old)}")
    print(f"RC_IDs only in NEW: {len(only_new)}")
    if only_old:
        print(f"  sample old-only: {list(only_old)[:10]}")
    if only_new:
        print(f"  sample new-only: {list(only_new)[:10]}")

    print("\n=== Attribute differences (matched RC_IDs) ===")
    attr_cols = ["RC_Name", "Classification", "Country", "Region_NM", "Retail_N", "H3_count", "Area_km2"]
    sample_changes = {}
    for col in attr_cols:
        if col in old.columns and col in new.columns:
            sample_changes[col] = compare_column(old, new, col)
        else:
            print(f"  {col}: missing in one side (old={col in old.columns}, new={col in new.columns})")

    print("\n=== Geometry differences ===")
    geom_diffs = compare_geometry(old, new)

    out_dir = os.path.dirname(__file__)
    os.makedirs(out_dir, exist_ok=True)
    report_path = os.path.join(out_dir, "comparison_report.csv")

    # Merged per-RC report
    report = old[["RC_ID", "RC_Name", "Classification"]].rename(
        columns={"RC_Name": "RC_Name_old", "Classification": "Classification_old"}
    ).merge(
        new[["RC_ID", "RC_Name", "Classification"]].rename(
            columns={"RC_Name": "RC_Name_new", "Classification": "Classification_new"}
        ),
        on="RC_ID", how="outer",
    ).merge(
        geom_diffs[["RC_ID", "area_rel_diff", "sym_over_union"]],
        on="RC_ID", how="left",
    )
    report["name_changed"] = report["RC_Name_old"].fillna("") != report["RC_Name_new"].fillna("")
    report["class_changed"] = report["Classification_old"].fillna("") != report["Classification_new"].fillna("")
    changed = report[
        report["name_changed"] | report["class_changed"]
        | (report["area_rel_diff"].fillna(0) > 0.001)
        | (report["sym_over_union"].fillna(0) > 0.001)
    ]
    changed.to_csv(report_path, index=False)
    print(f"\nWrote {len(changed)} changed rows to {report_path}")

    # Print a few examples
    print("\nName change examples:")
    print(report[report["name_changed"]].head(10)[["RC_ID", "RC_Name_old", "RC_Name_new"]].to_string(index=False))
    print("\nClassification change examples:")
    print(report[report["class_changed"]].head(10)[["RC_ID", "Classification_old", "Classification_new"]].to_string(index=False))


if __name__ == "__main__":
    main()
