#!/usr/bin/env python3
"""
Duplicate POI detection with retail filters applied first.

Pipeline:
1. Apply retail category filter
2. Apply quality filters (closed, defunct, UK boundary)
3. Find duplicate POIs (4dp coordinates, same category, similar name/tel/website)
"""

import polars as pl
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

# --- Helper functions (from notebook) ---
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

def main():
    print("="*80)
    print("DUPLICATE POI DETECTION (WITH RETAIL FILTERS)")
    print("="*80)

    # ===== STEP 1: LOAD AND APPLY RETAIL CATEGORY FILTER =====
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/4] Loading: {input_file}")
    foursquare = pl.read_parquet(input_file)
    print(f"Total POIs: {len(foursquare):,}")

    print("\n[2/4] Applying retail category filter...")
    foursquare_filt = filter_foursquare_invmethod(foursquare)
    print(f"After retail filter: {len(foursquare_filt):,}")

    # ===== STEP 2: APPLY QUALITY FILTERS =====
    print("\n[3/4] Applying quality filters...")

    # Remove closed venues (already done in retail filter, but make sure)
    foursquare_filt = foursquare_filt.filter(pl.col("date_closed").is_null())
    print(f"After closed filter: {len(foursquare_filt):,}")

    # Remove defunct retailers
    foursquare_filt = filter_defunct_retailers(
        foursquare_filt,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=False
    )

    # Remove out-of-bounds POIs
    foursquare_filt = filter_by_uk_boundary(
        foursquare_filt,
        boundary_path="data/input_files/Countries_December_2022_UK_BGC_1943732719298389253.gpkg",
        buffer_m=50,
        save_outside=False
    )

    print(f"After all filters: {len(foursquare_filt):,}")

    # ===== STEP 3: FIND DUPLICATES =====
    print(f"\n[4/4] Finding duplicate POIs...")
    print("Parameters:")
    print("  - Coordinate precision: 4dp (~11m, ~25m effective radius)")
    print("  - Name similarity threshold: 0.6")
    print("  - Matches: same location + same category + (similar name OR same tel OR same website)")

    name_threshold = 0.6
    coord_precision = 4

    # Add row_id
    df = foursquare_filt
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

    # Join keys: rounded location + category
    keys = ["lat_round", "lng_round", "fsq_category_id"]

    print("\nRunning self-join (this is fast in Polars)...")

    # Self-join to find pairs at same location with same category
    pairs = (
        dfn.join(dfn, on=keys, how="inner", suffix="_r")
           .filter(pl.col("row_id") < pl.col("row_id_r"))  # Avoid duplicate pairs
           .with_columns([
               # Check matching fields
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
               # Match if any field matches
               (pl.col("m_tel") | pl.col("m_website") | pl.col("m_name")).alias("is_match")
           )
           .filter(pl.col("is_match"))  # Keep only matching pairs
           .with_columns(
               # Track which fields matched
               pl.concat_list([
                   pl.when(pl.col("m_tel")).then(pl.lit("tel")).otherwise(None),
                   pl.when(pl.col("m_website")).then(pl.lit("website")).otherwise(None),
                   pl.when(pl.col("m_name")).then(pl.lit("name")).otherwise(None),
               ]).alias("match_list_raw")
           )
           .with_columns(pl.col("match_list_raw").list.drop_nulls().alias("match_list"))
           .select("row_id", "row_id_r", *keys, "match_list")
    )

    print(f"Found {len(pairs):,} duplicate pairs")

    if len(pairs) == 0:
        print("\nNo duplicates found!")
        return

    # Get all POIs involved in duplicates
    implicated_ids = (
        pl.concat([
            pairs.select(pl.col("row_id")),
            pairs.select(pl.col("row_id_r").alias("row_id")),
        ])
        .unique()
    )

    print(f"Total POIs involved: {len(implicated_ids):,}")

    # Aggregate matched fields per POI
    row_match_fields = (
        pl.concat([
            pairs.select("row_id", "match_list").rename({"row_id": "rid"}),
            pairs.select(pl.col("row_id_r").alias("rid"), "match_list"),
        ])
        .group_by("rid")
        .agg(pl.col("match_list").flatten().alias("match_fields_list"))
        .with_columns(
            pl.col("match_fields_list").list.unique().list.sort().list.join(", ").alias("match_fields")
        )
        .select(pl.col("rid").alias("row_id"), "match_fields")
    )

    # Build final duplicate table
    dupes = (
        dfn.join(implicated_ids, on="row_id", how="inner")
           .join(
               # Add dup_count: number of POIs in each group
               implicated_ids
                   .join(dfn.select("row_id", *keys), on="row_id", how="inner")
                   .group_by(keys)
                   .agg(pl.len().alias("dup_count")),
               on=keys,
               how="left"
           )
           .join(row_match_fields, on="row_id", how="left")
           .sort(["dup_count"] + keys, descending=[True, False, False, False])
    )

    # ===== RESULTS =====
    print(f"\n{'='*80}")
    print("RESULTS")
    print(f"{'='*80}")

    n_groups = dupes.select(keys).n_unique()
    print(f"\nDuplicate POIs found: {len(dupes):,}")
    print(f"Duplicate groups: {n_groups:,}")
    print(f"Average POIs per group: {len(dupes) / n_groups:.2f}")

    # Top 20 groups
    print(f"\nTop 20 largest duplicate groups:")
    top_groups = (
        dupes.group_by(keys)
             .agg([
                 pl.count("row_id").alias("size"),
                 pl.col("name").head(3).alias("sample_names"),  # Get up to 3 names as a list
                 pl.col("match_fields").first().alias("matched_on"),
             ])
             .sort("size", descending=True)
             .head(20)
    )
    print(top_groups.select(["sample_names", "matched_on", "size"]))

    # ===== SAVE =====
    print(f"\n{'='*80}")
    print("SAVING RESULTS")
    print(f"{'='*80}")

    import os
    output_dir = "data/POI_files/duplicate_analysis_full/"
    os.makedirs(output_dir, exist_ok=True)

    # Save full results
    output_path = f"{output_dir}duplicates_retail_filtered_4dp_06thresh.parquet"
    dupes.write_parquet(output_path)
    print(f"\n✓ Saved: {output_path}")

    # Save top 1000 to CSV for review
    csv_path = f"{output_dir}duplicates_retail_filtered_4dp_06thresh_top1000.csv"
    dupes.select([
        "fsq_place_id", "name", "lat", "lng", "address", "tel", "website",
        "date_created", "date_refreshed", "dup_count", "match_fields"
    ]).head(1000).write_csv(csv_path)
    print(f"✓ Saved CSV: {csv_path}")

    # Estimate removals if keeping newest from each group
    est_remove = len(dupes) - n_groups
    print(f"\n{'='*80}")
    print("REMOVAL ESTIMATE (if keeping newest from each group)")
    print(f"{'='*80}")
    print(f"POIs to remove: ~{est_remove:,}")
    print(f"POIs to keep: ~{n_groups:,}")
    print(f"% of filtered dataset: {100 * est_remove / len(df):.3f}%")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
