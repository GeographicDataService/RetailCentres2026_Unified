#!/usr/bin/env python3
"""
Compare duplicate detection at 0.5 vs 0.7 name threshold.
Output only the NEW duplicates captured by lowering threshold to 0.5.
"""

import polars as pl
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

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

def find_duplicates_at_threshold(df, name_threshold, coord_precision=4):
    """Find duplicates with given name threshold."""

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

    # Self-join to find pairs
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
           .with_columns(
               pl.concat_list([
                   pl.when(pl.col("m_tel")).then(pl.lit("tel")).otherwise(None),
                   pl.when(pl.col("m_website")).then(pl.lit("website")).otherwise(None),
                   pl.when(pl.col("m_name")).then(pl.lit("name")).otherwise(None),
               ]).alias("match_list_raw")
           )
           .with_columns(pl.col("match_list_raw").list.drop_nulls().alias("match_list"))
           .select("row_id", "row_id_r", *keys, "match_list", "name_sim")
    )

    # Get all implicated row_ids
    implicated_ids = (
        pl.concat([
            pairs.select(pl.col("row_id")),
            pairs.select(pl.col("row_id_r").alias("row_id")),
        ])
        .unique()
    )

    return implicated_ids

def main():
    print("="*80)
    print("COMPARING 0.5 vs 0.7 NAME THRESHOLD")
    print("="*80)

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading and filtering: {input_file}")
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

    # Find duplicates at 0.7 threshold
    print("\n" + "="*80)
    print("Finding duplicates at 0.7 threshold...")
    print("="*80)
    dupes_07_ids = find_duplicates_at_threshold(foursquare_filt, name_threshold=0.7)
    print(f"POIs matched at 0.7: {len(dupes_07_ids):,}")

    # Find duplicates at 0.5 threshold
    print("\n" + "="*80)
    print("Finding duplicates at 0.5 threshold...")
    print("="*80)
    dupes_05_ids = find_duplicates_at_threshold(foursquare_filt, name_threshold=0.5)
    print(f"POIs matched at 0.5: {len(dupes_05_ids):,}")

    # Find NEW captures (in 0.5 but not in 0.7)
    print("\n" + "="*80)
    print("Finding NEW captures (0.5 only)...")
    print("="*80)

    new_captures = dupes_05_ids.join(
        dupes_07_ids.with_columns(pl.lit(True).alias("in_07")),
        on="row_id",
        how="left"
    ).filter(pl.col("in_07").is_null())

    print(f"NEW POIs captured by lowering to 0.5: {len(new_captures):,}")
    print(f"Improvement: {100 * len(new_captures) / len(dupes_07_ids):.2f}% more POIs")

    # Get full POI data for new captures
    if len(new_captures) > 0:
        # Add row_id if not present
        if "row_id" not in foursquare_filt.columns:
            foursquare_filt = foursquare_filt.with_row_index("row_id")

        new_captures_full = foursquare_filt.join(new_captures, on="row_id", how="inner")

        # Save results
        import os
        output_dir = "data/POI_files/duplicate_analysis_full/"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}new_captures_05_threshold.parquet"
        new_captures_full.write_parquet(output_path)
        print(f"\n✓ Saved NEW captures: {output_path}")

        # Save sample to CSV
        csv_path = f"{output_dir}new_captures_05_threshold_sample500.csv"
        new_captures_full.select([
            "fsq_place_id", "name", "lat", "lng", "address", "tel", "website",
            "date_created", "date_refreshed"
        ]).head(500).write_csv(csv_path)
        print(f"✓ Saved CSV sample: {csv_path}")

        # Show some examples
        print(f"\n{'='*80}")
        print("SAMPLE OF NEW CAPTURES")
        print(f"{'='*80}")
        print(new_captures_full.select(["name", "address", "lat", "lng"]).head(20))
    else:
        print("\nNo new captures - 0.5 threshold caught the same POIs as 0.7")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
