#!/usr/bin/env python3
"""
Compare H3-based duplicate detection vs coordinate rounding approach.
Both use 0.6 name threshold.
"""

import math
import polars as pl
import h3
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

EARTH_R_M = 6_371_000.0

# --- Helper functions ---
def _norm_text(s: str) -> str:
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _norm_site(s: str) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"^https?://(www\.)?", "", s)
    s = s.rstrip("/")
    return s

def _levenshtein(a: str, b: str) -> int:
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    if len(a) > len(b): a, b = b, a
    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, start=1):
        curr = [j]
        for i, ca in enumerate(a, start=1):
            curr.append(min(prev[i] + 1, curr[i - 1] + 1, prev[i - 1] + (ca != cb)))
        prev = curr
    return prev[-1]

def _lev_ratio(a: str, b: str) -> float:
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return 0.0
    return 1.0 - (_levenshtein(a, b) / max(la, lb))

def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))

def h3_approach(df, name_threshold=0.6, dist_thresh=15):
    """H3-based duplicate detection (fixed version)."""

    print("\n--- H3 APPROACH ---")
    print(f"Distance threshold: {dist_thresh}m")
    print(f"Name threshold: {name_threshold}")

    # Add row_id
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Normalized columns
    dfn = (
        df.with_columns(
            pl.col("lat").cast(pl.Float64),
            pl.col("lng").cast(pl.Float64),
            pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
            pl.col("tel").map_elements(_norm_text, return_dtype=str).alias("tel_norm"),
            pl.col("website").map_elements(_norm_site, return_dtype=str).alias("website_norm"),
        )
        .select([
            "row_id", "lat", "lng", "h3_11", "fsq_category_id",
            "name_norm", "tel_norm", "website_norm"
        ])
    )

    # Build H3 neighbors
    unique_cells = dfn.select("h3_11").unique()

    neighbors = (
        unique_cells
        .with_columns(
            pl.col("h3_11")
              .map_elements(lambda h: list(h3.grid_disk(h, 1)), return_dtype=pl.List(pl.Utf8))
              .alias("cand_cells")
        )
        .explode("cand_cells")
        .rename({"h3_11": "src_cell", "cand_cells": "cand_cell"})
    )

    # Expand to neighbors
    dfn_exp = (
        dfn.join(neighbors, left_on="h3_11", right_on="src_cell", how="inner")
           .select([
               "row_id", "lat", "lng", "h3_11", "fsq_category_id",
               "name_norm", "tel_norm", "website_norm",
               "cand_cell"
           ])
    )

    # Self-join
    pairs_raw = (
        dfn_exp.join(
            dfn,
            left_on=["cand_cell", "fsq_category_id"],
            right_on=["h3_11", "fsq_category_id"],
            how="inner",
            suffix="_r",
        )
        .filter(pl.col("row_id") < pl.col("row_id_r"))
    )

    # FIXED: Better pre-filter (0.0002 degrees ≈ 22m)
    pairs_pre = pairs_raw.filter(
        ((pl.col("lat") - pl.col("lat_r")).abs() <= 0.0002) &
        ((pl.col("lng") - pl.col("lng_r")).abs() <= 0.0002)
    )

    # Distance + matching
    pairs = (
        pairs_pre
        .with_columns(
            pl.struct(["lat","lng","lat_r","lng_r"])
              .map_elements(lambda s: _haversine_m(s["lat"], s["lng"], s["lat_r"], s["lng_r"]), return_dtype=pl.Float64)
              .alias("dist_m"),
            (pl.col("tel_norm") == pl.col("tel_norm_r")).alias("m_tel"),
            (pl.col("website_norm") == pl.col("website_norm_r")).alias("m_website"),
            pl.struct(["name_norm","name_norm_r"])
              .map_elements(lambda s: _lev_ratio(s["name_norm"], s["name_norm_r"]), return_dtype=pl.Float64)
              .alias("name_sim"),
        )
        .with_columns((pl.col("name_sim") >= name_threshold).alias("m_name"))
        # FIXED: Remove address matching to match coordinate approach
        .with_columns(
            ((pl.col("dist_m") <= dist_thresh) & (pl.col("m_tel") | pl.col("m_website") | pl.col("m_name")))
            .alias("is_match")
        )
        .filter(pl.col("is_match"))
    )

    # Get implicated IDs
    implicated_ids = pl.concat([
        pairs.select(pl.col("row_id")),
        pairs.select(pl.col("row_id_r").alias("row_id")),
    ]).unique()

    print(f"Pairs found: {len(pairs):,}")
    print(f"POIs involved: {len(implicated_ids):,}")

    return implicated_ids

def coord_rounding_approach(df, name_threshold=0.6, coord_precision=4):
    """Coordinate rounding duplicate detection."""

    print("\n--- COORDINATE ROUNDING APPROACH ---")
    print(f"Coordinate precision: {coord_precision}dp (~25m effective radius)")
    print(f"Name threshold: {name_threshold}")

    # Add row_id
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Add normalized columns
    dfn = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
        pl.col("tel").map_elements(_norm_text, return_dtype=str).alias("tel_norm"),
        pl.col("website").map_elements(_norm_site, return_dtype=str).alias("website_norm"),
    ])

    keys = ["lat_round", "lng_round", "fsq_category_id"]

    # Self-join
    pairs = (
        dfn.join(dfn, on=keys, how="inner", suffix="_r")
           .filter(pl.col("row_id") < pl.col("row_id_r"))
           .with_columns([
               (pl.col("tel_norm") == pl.col("tel_norm_r")).alias("m_tel"),
               (pl.col("website_norm") == pl.col("website_norm_r")).alias("m_website"),
               pl.struct(["name_norm", "name_norm_r"])
                 .map_elements(
                     lambda s: _lev_ratio(s["name_norm"], s["name_norm_r"]),
                     return_dtype=pl.Float64
                 )
                 .alias("name_sim"),
           ])
           .with_columns((pl.col("name_sim") >= name_threshold).alias("m_name"))
           .with_columns(
               (pl.col("m_tel") | pl.col("m_website") | pl.col("m_name")).alias("is_match")
           )
           .filter(pl.col("is_match"))
    )

    # Get implicated IDs
    implicated_ids = pl.concat([
        pairs.select(pl.col("row_id")),
        pairs.select(pl.col("row_id_r").alias("row_id")),
    ]).unique()

    print(f"Pairs found: {len(pairs):,}")
    print(f"POIs involved: {len(implicated_ids):,}")

    return implicated_ids

def main():
    print("="*80)
    print("COMPARING H3 vs COORDINATE ROUNDING DUPLICATE DETECTION")
    print("="*80)

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading and filtering: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    print("\nApplying retail filter...")
    foursquare_filt = filter_foursquare_invmethod(foursquare)
    print(f"After retail filter: {len(foursquare_filt):,}")

    print("\nApplying quality filters...")
    foursquare_filt = foursquare_filt.filter(pl.col("date_closed").is_null())
    print(f"After closed filter: {len(foursquare_filt):,}")

    foursquare_filt = filter_defunct_retailers(
        foursquare_filt,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=False
    )

    foursquare_filt = filter_by_uk_boundary(
        foursquare_filt,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False
    )

    print(f"After all filters: {len(foursquare_filt):,}")

    # Add row_id to main dataframe for later joins
    if "row_id" not in foursquare_filt.columns:
        foursquare_filt = foursquare_filt.with_row_index("row_id")

    # Run both approaches
    print("\n" + "="*80)
    print("RUNNING BOTH APPROACHES")
    print("="*80)

    # H3 approach
    h3_ids = h3_approach(foursquare_filt, name_threshold=0.6, dist_thresh=15)

    # Coordinate rounding approach
    coord_ids = coord_rounding_approach(foursquare_filt, name_threshold=0.6, coord_precision=4)

    # Compare results
    print("\n" + "="*80)
    print("COMPARISON RESULTS")
    print("="*80)

    # Find differences
    h3_only = h3_ids.join(
        coord_ids.with_columns(pl.lit(True).alias("in_coord")),
        on="row_id",
        how="left"
    ).filter(pl.col("in_coord").is_null()).drop("in_coord")

    coord_only = coord_ids.join(
        h3_ids.with_columns(pl.lit(True).alias("in_h3")),
        on="row_id",
        how="left"
    ).filter(pl.col("in_h3").is_null()).drop("in_h3")

    both = h3_ids.join(coord_ids, on="row_id", how="inner")

    print(f"\nH3 approach:              {len(h3_ids):,} POIs")
    print(f"Coordinate approach:      {len(coord_ids):,} POIs")
    print(f"Found by BOTH:            {len(both):,} POIs")
    print(f"H3 ONLY:                  {len(h3_only):,} POIs")
    print(f"Coordinate rounding ONLY: {len(coord_only):,} POIs")

    # Percentages
    print(f"\nOverlap: {100 * len(both) / len(h3_ids):.1f}% of H3 results")
    print(f"Overlap: {100 * len(both) / len(coord_ids):.1f}% of coordinate results")

    # Save results with duplicate groups
    import os
    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    if len(h3_only) > 0:
        # Get full POI data
        h3_only_full = foursquare_filt.join(h3_only, on="row_id", how="inner")

        # Add H3 cell and count duplicates per H3 cell + category
        h3_only_grouped = (
            h3_only_full
            .join(
                h3_only_full
                    .group_by(["h3_11", "fsq_category_id"])
                    .agg(pl.len().alias("dup_count")),
                on=["h3_11", "fsq_category_id"],
                how="left"
            )
            # Keep only essential fields
            .select([
                "h3_11", "fsq_category_id", "dup_count",
                "fsq_place_id", "name", "lat", "lng", "address",
                "date_created", "date_refreshed"
            ])
            # Sort by dup count and h3 cell so duplicates are grouped together
            .sort(["dup_count", "h3_11", "fsq_category_id"], descending=[True, False, False])
        )

        output_path = f"{output_dir}h3_only_duplicates.parquet"
        h3_only_grouped.write_parquet(output_path)
        print(f"\n✓ Saved H3-only duplicates: {output_path}")

        csv_path = f"{output_dir}h3_only_duplicates_grouped.csv"
        h3_only_grouped.head(1000).write_csv(csv_path)
        print(f"✓ Saved CSV (top 1000): {csv_path}")

        # Show sample of largest groups
        print(f"\nSample of largest duplicate groups (H3 only):")
        sample = h3_only_grouped.head(20).select([
            "dup_count", "name", "address", "lat", "lng"
        ])
        print(sample)

    if len(coord_only) > 0:
        coord_only_full = foursquare_filt.join(coord_only, on="row_id", how="inner")
        output_path = f"{output_dir}coord_only_duplicates.parquet"
        coord_only_full.write_parquet(output_path)
        print(f"\n✓ Saved coordinate-only duplicates: {output_path}")

        csv_path = f"{output_dir}coord_only_duplicates_sample.csv"
        coord_only_full.select([
            "fsq_place_id", "name", "lat", "lng", "address"
        ]).head(500).write_csv(csv_path)
        print(f"✓ Saved CSV: {csv_path}")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
