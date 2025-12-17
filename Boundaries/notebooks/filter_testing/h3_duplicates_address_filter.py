#!/usr/bin/env python3
"""
H3-based duplicate detection with address filtering.

Filter criteria:
- Distance < 15m
- Address same OR one has no address
- At least one of: name match (0.6), tel match, website match
"""

import math
import polars as pl
import h3
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare
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

def main():
    print("="*80)
    print("H3 DUPLICATE DETECTION WITH ADDRESS FILTERING")
    print("="*80)
    print("\nFilter criteria:")
    print("  - Distance < 15m")
    print("  - Address same OR one has no address")
    print("  - At least one of: name match (0.6), tel match, website match")

    # ===== LOAD AND FILTER DATA =====
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/4] Loading and filtering: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    print("\nApplying retail filter...")
    foursquare_filt = filter_foursquare(foursquare)
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

    # ===== RUN H3 DUPLICATE DETECTION =====
    print(f"\n[2/4] Running H3 duplicate detection...")

    name_threshold = 0.6
    dist_thresh = 15

    # Add row_id
    df = foursquare_filt
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Normalized columns
    dfn = (
        df.with_columns(
            pl.col("lat").cast(pl.Float64),
            pl.col("lng").cast(pl.Float64),
            pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
            pl.col("address").map_elements(_norm_text, return_dtype=str).alias("address_norm"),
            pl.col("tel").map_elements(_norm_text, return_dtype=str).alias("tel_norm"),
            pl.col("website").map_elements(_norm_site, return_dtype=str).alias("website_norm"),
        )
        .select([
            "row_id", "lat", "lng", "h3_11", "fsq_category_id",
            "name_norm", "address_norm", "tel_norm", "website_norm"
        ])
    )

    # Build H3 neighbors
    print("Building H3 neighbor mapping...")
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
               "name_norm", "address_norm", "tel_norm", "website_norm",
               "cand_cell"
           ])
    )

    # Self-join
    print("Running self-join on H3 cells...")
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

    # Pre-filter by bbox
    pairs_pre = pairs_raw.filter(
        ((pl.col("lat") - pl.col("lat_r")).abs() <= 0.0002) &
        ((pl.col("lng") - pl.col("lng_r")).abs() <= 0.0002)
    )

    # NEW: Apply address + distance + matching criteria
    print("Applying distance, address, and matching criteria...")
    pairs = (
        pairs_pre
        .with_columns([
            # Distance
            pl.struct(["lat","lng","lat_r","lng_r"])
              .map_elements(lambda s: _haversine_m(s["lat"], s["lng"], s["lat_r"], s["lng_r"]), return_dtype=pl.Float64)
              .alias("dist_m"),

            # Address checks
            (pl.col("address_norm") == "").alias("addr1_empty"),
            (pl.col("address_norm_r") == "").alias("addr2_empty"),
            (pl.col("address_norm") == pl.col("address_norm_r")).alias("addr_same"),

            # Matching fields
            (pl.col("tel_norm") == pl.col("tel_norm_r")).alias("m_tel"),
            (pl.col("website_norm") == pl.col("website_norm_r")).alias("m_website"),
            pl.struct(["name_norm","name_norm_r"])
              .map_elements(lambda s: _lev_ratio(s["name_norm"], s["name_norm_r"]), return_dtype=pl.Float64)
              .alias("name_sim"),
        ])
        .with_columns([
            (pl.col("name_sim") >= name_threshold).alias("m_name"),
            # Address condition: same OR one is empty
            (pl.col("addr_same") | pl.col("addr1_empty") | pl.col("addr2_empty")).alias("addr_ok"),
        ])
        .with_columns(
            # Final match: distance < 15m AND address_ok AND (name OR tel OR website)
            (
                (pl.col("dist_m") <= dist_thresh) &
                pl.col("addr_ok") &
                (pl.col("m_tel") | pl.col("m_website") | pl.col("m_name"))
            ).alias("is_match")
        )
        .filter(pl.col("is_match"))
        .with_columns(
            pl.concat_list([
                pl.when(pl.col("m_tel")).then(pl.lit("tel")).otherwise(None),
                pl.when(pl.col("m_website")).then(pl.lit("website")).otherwise(None),
                pl.when(pl.col("m_name")).then(pl.lit("name")).otherwise(None),
            ]).list.drop_nulls().list.join(", ").alias("match_fields")
        )
    )

    print(f"Pairs found: {len(pairs):,}")

    # Get implicated IDs
    implicated_ids = pl.concat([
        pairs.select(pl.col("row_id")),
        pairs.select(pl.col("row_id_r").alias("row_id")),
    ]).unique()

    print(f"POIs involved: {len(implicated_ids):,}")

    # ===== BUILD DUPLICATE GROUPS =====
    print(f"\n[3/4] Building duplicate groups...")

    # Get full POI data for duplicates
    duplicates_full = df.join(implicated_ids, on="row_id", how="inner")

    # Count duplicates per H3 cell + category
    duplicates_grouped = (
        duplicates_full
        .join(
            duplicates_full
                .group_by(["h3_11", "fsq_category_id"])
                .agg(pl.len().alias("dup_count")),
            on=["h3_11", "fsq_category_id"],
            how="left"
        )
        # Keep essential fields
        .select([
            "h3_11", "fsq_category_id", "dup_count",
            "fsq_place_id", "name", "lat", "lng", "address",
            "tel", "website",
            "date_created", "date_refreshed"
        ])
        # Sort by dup count and h3 cell so duplicates are grouped together
        .sort(["dup_count", "h3_11", "fsq_category_id"], descending=[True, False, False])
    )

    # ===== SAVE RESULTS =====
    print(f"\n[4/4] Saving results...")

    import os
    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    # Save full results
    output_path = f"{output_dir}h3_duplicates_address_filter.parquet"
    duplicates_grouped.write_parquet(output_path)
    print(f"\n✓ Saved full results: {output_path}")

    # Save top 2000 to CSV for review
    csv_path = f"{output_dir}h3_duplicates_address_filter_top2000.csv"
    duplicates_grouped.head(2000).write_csv(csv_path)
    print(f"✓ Saved CSV (top 2000): {csv_path}")

    # ===== GENERATE REPORT =====
    print(f"\n{'='*80}")
    print("REPORT: DUPLICATE DETECTION WITH ADDRESS FILTERING")
    print(f"{'='*80}")

    print(f"\nDataset Summary:")
    print(f"  Total POIs after filters:     {len(df):,}")
    print(f"  Duplicate POIs identified:    {len(duplicates_grouped):,}")
    print(f"  Percentage of dataset:        {100 * len(duplicates_grouped) / len(df):.2f}%")

    # Group statistics
    n_groups = duplicates_grouped.select(["h3_11", "fsq_category_id"]).n_unique()
    print(f"\nDuplicate Groups:")
    print(f"  Number of groups:             {n_groups:,}")
    print(f"  Average POIs per group:       {len(duplicates_grouped) / n_groups:.2f}")

    # Removal estimate
    est_remove = len(duplicates_grouped) - n_groups
    print(f"\nRemoval Estimate (keeping newest from each group):")
    print(f"  POIs to remove:               {est_remove:,}")
    print(f"  POIs to keep:                 {n_groups:,}")
    print(f"  % reduction of dataset:       {100 * est_remove / len(df):.3f}%")

    # Group size distribution
    print(f"\nGroup Size Distribution:")
    size_dist = (
        duplicates_grouped
        .group_by("dup_count")
        .agg(pl.len().alias("num_groups"))
        .sort("dup_count", descending=True)
        .head(10)
        .with_columns((pl.col("num_groups") / pl.col("dup_count")).alias("pois_in_these_groups"))
    )
    print(size_dist)

    # Top 20 largest groups
    print(f"\nTop 20 Largest Duplicate Groups:")
    top_groups = (
        duplicates_grouped
        .group_by(["h3_11", "fsq_category_id"])
        .agg([
            pl.first("dup_count").alias("size"),
            pl.col("name").head(3).alias("sample_names"),
        ])
        .sort("size", descending=True)
        .head(20)
    )
    for row in top_groups.iter_rows(named=True):
        names = ", ".join(row["sample_names"])
        print(f"  Size {row['size']:2d}: {names[:70]}")

    # Sample of duplicates
    print(f"\n{'='*80}")
    print("SAMPLE OF DUPLICATE GROUPS (with duplicates sorted together)")
    print(f"{'='*80}")
    sample = duplicates_grouped.head(30).select([
        "dup_count", "name", "address", "lat", "lng"
    ])
    print(sample)

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")
    print(f"\nOutput files:")
    print(f"  - {output_path}")
    print(f"  - {csv_path}")

if __name__ == "__main__":
    main()
