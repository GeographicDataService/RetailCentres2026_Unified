#!/usr/bin/env python3
"""
Duplicate POI detection and removal.

Filter criteria:
- Distance < 15m
- Address same OR one has no address
- At least one of: name match (0.6), tel match, website match

Action: Keep only most recently refreshed POI from each duplicate group.
"""

import math
import polars as pl
import h3
import re
import sys
import networkx as nx
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

def main():
    print("="*80)
    print("DUPLICATE POI DETECTION AND REMOVAL")
    print("="*80)
    print("\nFilter criteria:")
    print("  - Distance < 15m")
    print("  - Address same OR one has no address")
    print("  - At least one of: name match (0.6), tel match, website match")
    print("\nAction: Keep only most recently refreshed POI from each duplicate group")

    # ===== LOAD AND FILTER DATA =====
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/5] Loading and filtering: {input_file}")
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

    # ===== FIND DUPLICATE PAIRS =====
    print(f"\n[2/5] Finding duplicate pairs...")

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

    # Use H3 for efficient spatial lookup
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
    print("Finding nearby POI pairs...")
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

    # Apply all filter criteria
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
        .select(["row_id", "row_id_r"])
    )

    print(f"Duplicate pairs found: {len(pairs):,}")

    # ===== BUILD CONNECTED COMPONENTS (DUPLICATE GROUPS) =====
    print(f"\n[3/5] Building duplicate groups (connected components)...")

    # Build graph from pairs
    G = nx.Graph()
    for row in pairs.iter_rows():
        G.add_edge(row[0], row[1])

    # Find connected components
    components = list(nx.connected_components(G))
    print(f"Duplicate groups found: {len(components):,}")

    # Create group_id mapping
    group_mapping = []
    for group_id, component in enumerate(components):
        for row_id in component:
            group_mapping.append({"row_id": row_id, "group_id": group_id, "group_size": len(component)})

    group_df = pl.DataFrame(group_mapping)
    print(f"Total POIs in duplicate groups: {len(group_df):,}")

    # ===== DETERMINE WHICH POIs TO KEEP/REMOVE =====
    print(f"\n[4/5] Determining which POIs to keep (most recently refreshed)...")

    # Join with original data to get dates
    duplicates_with_groups = (
        df.join(group_df, on="row_id", how="inner")
        .with_columns(
            # Parse date_refreshed (handle nulls)
            pl.when(pl.col("date_refreshed").is_null())
              .then(pl.col("date_created"))
              .otherwise(pl.col("date_refreshed"))
              .str.strptime(pl.Datetime, format="%Y-%m-%d", strict=False)
              .alias("refresh_date")
        )
    )

    # For each group, find the row with most recent refresh_date
    keep_ids = (
        duplicates_with_groups
        .sort(["group_id", "refresh_date"], descending=[False, True])
        .group_by("group_id")
        .agg(pl.first("row_id").alias("keep_row_id"))
    )

    # Mark which to keep/remove
    duplicates_final = (
        duplicates_with_groups
        .join(keep_ids, on="group_id", how="left")
        .with_columns(
            (pl.col("row_id") == pl.col("keep_row_id")).alias("keep")
        )
        .select([
            "group_id", "group_size", "keep",
            "row_id", "fsq_place_id", "name", "lat", "lng", "address",
            "tel", "website", "date_created", "date_refreshed"
        ])
        .sort(["group_size", "group_id", "keep"], descending=[True, False, True])
    )

    to_remove = duplicates_final.filter(pl.col("keep") == False)
    to_keep_from_groups = duplicates_final.filter(pl.col("keep") == True)

    print(f"POIs to keep (most recent): {len(to_keep_from_groups):,}")
    print(f"POIs to remove: {len(to_remove):,}")

    # ===== SAVE RESULTS =====
    print(f"\n[5/5] Saving results...")

    import os
    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    # Save all duplicates with group info
    output_path = f"{output_dir}duplicates_all_with_groups.parquet"
    duplicates_final.write_parquet(output_path)
    print(f"\n✓ All duplicates: {output_path}")

    # Save removed POIs
    remove_path = f"{output_dir}duplicates_to_remove.parquet"
    to_remove.write_parquet(remove_path)
    print(f"✓ POIs to remove: {remove_path}")

    # Save CSV of removed (top 2000)
    csv_path = f"{output_dir}duplicates_to_remove_top2000.csv"
    to_remove.head(2000).write_csv(csv_path)
    print(f"✓ CSV (top 2000): {csv_path}")

    # Create filtered dataset (original - removed)
    filtered_dataset = df.join(
        to_remove.select("row_id").with_columns(pl.lit(True).alias("remove")),
        on="row_id",
        how="left"
    ).filter(pl.col("remove").is_null()).drop("remove")

    filtered_path = f"{output_dir}foursquare_deduped.parquet"
    filtered_dataset.write_parquet(filtered_path)
    print(f"✓ Filtered dataset: {filtered_path}")

    # ===== GENERATE REPORT =====
    print(f"\n{'='*80}")
    print("REPORT: DUPLICATE REMOVAL")
    print(f"{'='*80}")

    print(f"\nDataset Summary:")
    print(f"  Original POIs:                {len(df):,}")
    print(f"  Duplicate POIs identified:    {len(duplicates_final):,}")
    print(f"  POIs to remove:               {len(to_remove):,}")
    print(f"  Final dataset size:           {len(filtered_dataset):,}")
    print(f"  Reduction:                    {100 * len(to_remove) / len(df):.3f}%")

    print(f"\nDuplicate Groups:")
    print(f"  Number of groups:             {len(components):,}")
    print(f"  Average POIs per group:       {len(duplicates_final) / len(components):.2f}")

    # Group size distribution
    print(f"\nGroup Size Distribution:")
    size_dist = (
        duplicates_final
        .group_by("group_size")
        .agg((pl.len() / pl.first("group_size")).cast(pl.Int32).alias("num_groups"))
        .sort("group_size", descending=True)
        .head(15)
    )
    print(size_dist)

    # Top 20 largest groups
    print(f"\nTop 20 Largest Duplicate Groups:")
    top_groups = (
        duplicates_final
        .group_by("group_id")
        .agg([
            pl.first("group_size").alias("size"),
            pl.col("name").head(3).alias("sample_names"),
        ])
        .sort("size", descending=True)
        .head(20)
    )
    for row in top_groups.iter_rows(named=True):
        names = ", ".join(row["sample_names"])
        print(f"  Size {row['size']:2d}: {names[:70]}")

    # Sample of removed POIs
    print(f"\n{'='*80}")
    print("SAMPLE OF REMOVED POIs (grouped by duplicate group)")
    print(f"{'='*80}")
    sample = to_remove.head(30).select([
        "group_id", "group_size", "name", "address", "date_refreshed"
    ])
    print(sample)

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")
    print(f"\nOutput files:")
    print(f"  - All duplicates (with groups): {output_path}")
    print(f"  - POIs to remove:                {remove_path}")
    print(f"  - Filtered dataset:              {filtered_path}")

if __name__ == "__main__":
    main()
