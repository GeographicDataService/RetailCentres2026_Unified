#!/usr/bin/env python3
"""
Compare duplicate detection at 0.5 vs 0.7 name threshold.
Output NEW duplicate PAIRS with matching reasons.
"""

import polars as pl
import re
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
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

def find_duplicate_pairs_at_threshold(df, name_threshold, coord_precision=4):
    """Find duplicate pairs with given name threshold."""

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
               ]).list.drop_nulls().list.join(", ").alias("match_reason")
           )
           .select("row_id", "row_id_r", *keys, "match_reason", "name_sim", "m_tel", "m_website", "m_name")
    )

    return pairs

def main():
    print("="*80)
    print("COMPARING 0.5 vs 0.7 NAME THRESHOLD (PAIRS WITH REASONS)")
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

    # Add row_id to original data
    if "row_id" not in foursquare_filt.columns:
        foursquare_filt = foursquare_filt.with_row_index("row_id")

    # Find duplicate pairs at 0.7 threshold
    print("\n" + "="*80)
    print("Finding duplicate pairs at 0.7 threshold...")
    print("="*80)
    pairs_07 = find_duplicate_pairs_at_threshold(foursquare_filt, name_threshold=0.7)
    print(f"Pairs matched at 0.7: {len(pairs_07):,}")

    # Find duplicate pairs at 0.5 threshold
    print("\n" + "="*80)
    print("Finding duplicate pairs at 0.5 threshold...")
    print("="*80)
    pairs_05 = find_duplicate_pairs_at_threshold(foursquare_filt, name_threshold=0.5)
    print(f"Pairs matched at 0.5: {len(pairs_05):,}")

    # Find NEW pairs (in 0.5 but not in 0.7)
    print("\n" + "="*80)
    print("Finding NEW pairs (0.5 only)...")
    print("="*80)

    # Create unique pair identifiers
    pairs_07_ids = pairs_07.with_columns(
        pl.concat_str([pl.col("row_id").cast(str), pl.lit("_"), pl.col("row_id_r").cast(str)]).alias("pair_id")
    )
    pairs_05_ids = pairs_05.with_columns(
        pl.concat_str([pl.col("row_id").cast(str), pl.lit("_"), pl.col("row_id_r").cast(str)]).alias("pair_id")
    )

    new_pairs = pairs_05_ids.join(
        pairs_07_ids.select("pair_id").with_columns(pl.lit(True).alias("in_07")),
        on="pair_id",
        how="left"
    ).filter(pl.col("in_07").is_null()).drop("in_07", "pair_id")

    print(f"NEW pairs captured by lowering to 0.5: {len(new_pairs):,}")
    print(f"Improvement: {100 * len(new_pairs) / len(pairs_07):,.2f}% more pairs")

    # Join with POI data for both sides
    if len(new_pairs) > 0:
        print("\nJoining with POI data for both sides of pairs...")

        # Select relevant columns from POI data
        poi_cols = ["row_id", "fsq_place_id", "name", "lat", "lng", "address", "tel", "website",
                    "date_created", "date_refreshed"]

        pairs_with_data = (
            new_pairs
            .join(foursquare_filt.select(poi_cols), on="row_id", how="left")
            .rename({
                "fsq_place_id": "poi1_id",
                "name": "poi1_name",
                "lat": "poi1_lat",
                "lng": "poi1_lng",
                "address": "poi1_address",
                "tel": "poi1_tel",
                "website": "poi1_website",
                "date_created": "poi1_date_created",
                "date_refreshed": "poi1_date_refreshed",
            })
            .join(
                foursquare_filt.select(poi_cols).rename({"row_id": "row_id_r"}),
                on="row_id_r",
                how="left"
            )
            .rename({
                "fsq_place_id": "poi2_id",
                "name": "poi2_name",
                "lat": "poi2_lat",
                "lng": "poi2_lng",
                "address": "poi2_address",
                "tel": "poi2_tel",
                "website": "poi2_website",
                "date_created": "poi2_date_created",
                "date_refreshed": "poi2_date_refreshed",
            })
            .select([
                "poi1_id", "poi1_name", "poi1_address", "poi1_lat", "poi1_lng",
                "poi1_tel", "poi1_website", "poi1_date_created", "poi1_date_refreshed",
                "poi2_id", "poi2_name", "poi2_address", "poi2_lat", "poi2_lng",
                "poi2_tel", "poi2_website", "poi2_date_created", "poi2_date_refreshed",
                "match_reason", "name_sim", "m_tel", "m_website", "m_name"
            ])
            .sort("name_sim")  # Sort by name similarity (lowest first = most interesting)
        )

        # Save results
        import os
        output_dir = "data/POI_files/duplicate_analysis_full/"
        os.makedirs(output_dir, exist_ok=True)

        output_path = f"{output_dir}new_pairs_05_threshold.parquet"
        pairs_with_data.write_parquet(output_path)
        print(f"\n✓ Saved NEW pairs: {output_path}")

        # Save to CSV (all pairs)
        csv_path = f"{output_dir}new_pairs_05_threshold.csv"
        pairs_with_data.write_csv(csv_path)
        print(f"✓ Saved CSV: {csv_path}")

        # Show some examples
        print(f"\n{'='*80}")
        print("SAMPLE OF NEW PAIRS (sorted by name similarity, lowest first)")
        print(f"{'='*80}")
        sample = pairs_with_data.head(10).select([
            "poi1_name", "poi2_name", "poi1_address", "poi2_address",
            "match_reason", "name_sim"
        ])
        print(sample)

        # Stats by match reason
        print(f"\n{'='*80}")
        print("BREAKDOWN BY MATCH REASON")
        print(f"{'='*80}")
        match_stats = (
            pairs_with_data
            .group_by("match_reason")
            .agg(pl.count().alias("count"))
            .sort("count", descending=True)
        )
        print(match_stats)
    else:
        print("\nNo new pairs - 0.5 threshold caught the same pairs as 0.7")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
