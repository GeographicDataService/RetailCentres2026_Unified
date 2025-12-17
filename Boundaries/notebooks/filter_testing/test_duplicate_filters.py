#!/usr/bin/env python3
"""
Test script for duplicate POI filtering.

Two types of duplicates:
1. Same POI recorded twice - similar name, close location, similar attributes
2. Same venue, different business - different names, exact location, similar category
   (e.g., old business vs new business at same address)
"""

import polars as pl
import re
import math
import sys
sys.path.insert(0, 'src')

# ===== HELPER FUNCTIONS =====

def _norm_text(s: str) -> str:
    """Normalize text for comparison."""
    if s is None or not isinstance(s, str):
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _norm_site(s: str) -> str:
    """Normalize website URLs."""
    if not s or not isinstance(s, str):
        return ""
    s = s.lower().strip()
    s = re.sub(r"^https?://(www\.)?", "", s)
    s = s.rstrip("/")
    return s

def _levenshtein(a: str, b: str) -> int:
    """Calculate Levenshtein distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a

    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, start=1):
        curr = [j]
        for i, ca in enumerate(a, start=1):
            curr.append(min(prev[i] + 1, curr[i - 1] + 1, prev[i - 1] + (ca != cb)))
        prev = curr
    return prev[-1]

def _lev_ratio(a: str, b: str) -> float:
    """Calculate normalized Levenshtein similarity (0-1 scale)."""
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return 1.0
    return 1.0 - (_levenshtein(a, b) / max(la, lb))

def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two lat/lng points."""
    EARTH_R_M = 6_371_000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


# ===== TYPE 1: SAME POI RECORDED TWICE =====

def find_duplicate_pois_type1(
    df: pl.DataFrame,
    name_threshold: float = 0.7,
    coord_precision: int = 6,
    distance_threshold_m: float = 15.0,
    use_distance: bool = False
) -> pl.DataFrame:
    """
    Find Type 1 duplicates: Same POI recorded twice.

    Matches on:
    - Similar/exact location (rounded coords or distance threshold)
    - Same or very similar category
    - At least one of: similar name, same tel, same website

    Parameters:
    - df: Input dataframe with POIs
    - name_threshold: Levenshtein similarity threshold for names (0-1)
    - coord_precision: Decimal places for coordinate rounding
    - distance_threshold_m: Distance threshold in meters (if use_distance=True)
    - use_distance: Use haversine distance instead of rounded coords

    Returns:
    - DataFrame of duplicate groups with metadata
    """

    print(f"\n{'='*80}")
    print("TYPE 1 DUPLICATE FILTER: Same POI Recorded Twice")
    print(f"{'='*80}")
    print(f"Parameters:")
    print(f"  - Name similarity threshold: {name_threshold}")
    print(f"  - Coordinate precision: {coord_precision} decimal places")
    if use_distance:
        print(f"  - Distance threshold: {distance_threshold_m}m")
    print()

    # Add row_id for tracking
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Normalize fields
    dfn = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=pl.String).alias("name_norm"),
        pl.col("tel").map_elements(_norm_text, return_dtype=pl.String).alias("tel_norm"),
        pl.col("website").map_elements(_norm_site, return_dtype=pl.String).alias("website_norm"),
    ])

    # Join keys: location + category
    if use_distance:
        # For distance-based, just use category for initial join
        keys = ["fsq_category_id"]
    else:
        keys = ["lat_round", "lng_round", "fsq_category_id"]

    print(f"Finding pairs matching on: {', '.join(keys)}")

    # Self-join to find potential pairs
    pairs = (
        dfn.join(dfn, on=keys, how="inner", suffix="_r")
           .filter(pl.col("row_id") < pl.col("row_id_r"))  # Avoid duplicates
    )

    print(f"Initial pairs found: {len(pairs):,}")

    # Add distance filter if requested
    if use_distance:
        pairs = pairs.with_columns(
            pl.struct(["lat", "lng", "lat_r", "lng_r"])
              .map_elements(
                  lambda s: _haversine_m(s["lat"], s["lng"], s["lat_r"], s["lng_r"]),
                  return_dtype=pl.Float64
              )
              .alias("distance_m")
        )
        pairs = pairs.filter(pl.col("distance_m") <= distance_threshold_m)
        print(f"After distance filter ({distance_threshold_m}m): {len(pairs):,} pairs")

    # Check matching fields
    pairs = pairs.with_columns([
        (pl.col("tel_norm") == pl.col("tel_norm_r")).alias("m_tel"),
        (pl.col("website_norm") == pl.col("website_norm_r")).alias("m_website"),
        pl.struct(["name_norm", "name_norm_r"])
          .map_elements(
              lambda s: _lev_ratio(s["name_norm"], s["name_norm_r"]),
              return_dtype=pl.Float64
          )
          .alias("name_sim"),
    ])

    pairs = pairs.with_columns([
        (pl.col("name_sim") >= name_threshold).alias("m_name")
    ])

    # Must match on at least one field
    pairs = pairs.with_columns([
        (pl.col("m_tel") | pl.col("m_website") | pl.col("m_name")).alias("is_match")
    ])

    pairs = pairs.filter(pl.col("is_match"))

    print(f"Pairs matching on name/tel/website: {len(pairs):,}")

    # Track which fields matched
    pairs = pairs.with_columns(
        pl.concat_list([
            pl.when(pl.col("m_tel")).then(pl.lit("tel")).otherwise(None),
            pl.when(pl.col("m_website")).then(pl.lit("website")).otherwise(None),
            pl.when(pl.col("m_name")).then(pl.lit("name")).otherwise(None),
        ]).list.drop_nulls().alias("match_fields")
    )

    # Get all implicated row_ids
    implicated_ids = pl.concat([
        pairs.select(pl.col("row_id")),
        pairs.select(pl.col("row_id_r").alias("row_id")),
    ]).unique()

    # Build duplicate groups
    dupes = (
        dfn.join(implicated_ids, on="row_id", how="inner")
           .join(
               implicated_ids.join(dfn.select("row_id", *keys), on="row_id", how="inner")
                            .group_by(keys).agg(pl.len().alias("dup_count")),
               on=keys, how="left"
           )
           .sort(["dup_count"] + keys, descending=[True, False, False, False])
    )

    print(f"\nTotal POIs in duplicate groups: {len(dupes):,}")
    print(f"Duplicate groups: {dupes.select(keys).n_unique():,}")

    return dupes


# ===== TYPE 2: SAME VENUE, DIFFERENT BUSINESS =====

def find_duplicate_pois_type2(
    df: pl.DataFrame,
    name_dissimilarity_max: float = 0.3,
    coord_precision: int = 7,
    same_category: bool = False
) -> pl.DataFrame:
    """
    Find Type 2 duplicates: Same venue with old and new business.

    Matches on:
    - Exact same location (high precision coords)
    - DIFFERENT names (dissimilar)
    - Same or similar category (optional)
    - Optionally: same address

    This catches cases like:
    - "Woolworths" and "Poundland" at exact same location
    - Old shop and new shop at same address

    Parameters:
    - df: Input dataframe
    - name_dissimilarity_max: Maximum name similarity (to ensure different businesses)
    - coord_precision: Decimal places for coordinate matching
    - same_category: Require same fsq_category_id (stricter)

    Returns:
    - DataFrame of duplicate groups
    """

    print(f"\n{'='*80}")
    print("TYPE 2 DUPLICATE FILTER: Same Venue, Different Business")
    print(f"{'='*80}")
    print(f"Parameters:")
    print(f"  - Name dissimilarity threshold: {name_dissimilarity_max} (lower = more different)")
    print(f"  - Coordinate precision: {coord_precision} decimal places")
    print(f"  - Require same category: {same_category}")
    print()

    # Add row_id
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Normalize
    dfn = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(coord_precision).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(coord_precision).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=pl.String).alias("name_norm"),
        pl.col("address").map_elements(_norm_text, return_dtype=pl.String).alias("address_norm"),
    ])

    # Join keys: exact location
    if same_category:
        keys = ["lat_round", "lng_round", "fsq_category_id"]
    else:
        keys = ["lat_round", "lng_round"]

    print(f"Finding pairs matching on: {', '.join(keys)}")

    # Self-join
    pairs = (
        dfn.join(dfn, on=keys, how="inner", suffix="_r")
           .filter(pl.col("row_id") < pl.col("row_id_r"))
    )

    print(f"Initial pairs at same location: {len(pairs):,}")

    # Check name dissimilarity (we WANT different names)
    pairs = pairs.with_columns(
        pl.struct(["name_norm", "name_norm_r"])
          .map_elements(
              lambda s: _lev_ratio(s["name_norm"], s["name_norm_r"]),
              return_dtype=pl.Float64
          )
          .alias("name_sim")
    )

    # Filter: names must be DIFFERENT (low similarity)
    pairs = pairs.filter(pl.col("name_sim") <= name_dissimilarity_max)

    print(f"Pairs with different names: {len(pairs):,}")

    # Check if addresses match (optional signal)
    pairs = pairs.with_columns(
        (pl.col("address_norm") == pl.col("address_norm_r")).alias("same_address")
    )

    # Get implicated IDs
    implicated_ids = pl.concat([
        pairs.select(pl.col("row_id")),
        pairs.select(pl.col("row_id_r").alias("row_id")),
    ]).unique()

    # Build groups
    dupes = (
        dfn.join(implicated_ids, on="row_id", how="inner")
           .join(
               implicated_ids.join(dfn.select("row_id", *keys), on="row_id", how="inner")
                            .group_by(keys).agg(pl.len().alias("dup_count")),
               on=keys, how="left"
           )
           .sort(["dup_count"] + keys, descending=[True] + [False] * len(keys))
    )

    print(f"\nTotal POIs in venue-reuse groups: {len(dupes):,}")
    print(f"Venue groups: {dupes.select(keys).n_unique():,}")

    return dupes


# ===== RESOLUTION: KEEP NEWEST =====

def keep_newest_pois(df: pl.DataFrame, dupes: pl.DataFrame, date_col: str = "date_created") -> tuple:
    """
    From duplicate groups, keep only the newest POI (by date_created/date_refreshed).

    Returns:
    - (df_cleaned, removed_pois): Tuple of cleaned dataframe and removed POIs
    """

    print(f"\n{'='*80}")
    print("RESOLVING DUPLICATES: Keep Newest POI")
    print(f"{'='*80}")

    # Determine join keys from dupes
    if "lat_round" in dupes.columns and "lng_round" in dupes.columns:
        if "fsq_category_id" in dupes.columns:
            keys = ["lat_round", "lng_round", "fsq_category_id"]
        else:
            keys = ["lat_round", "lng_round"]
    else:
        raise ValueError("Cannot determine keys from dupes dataframe")

    # Parse date
    dupes_with_date = dupes.with_columns(
        pl.col(date_col).str.strptime(pl.Datetime, strict=False, exact=False).alias("date_ts")
    )

    # Keep newest per group
    keep_ids = (
        dupes_with_date
        .sort(["date_ts", "row_id"], descending=[True, False], nulls_last=True)
        .group_by(keys)
        .agg(pl.first("row_id").alias("keep_row_id"))
        .select(pl.col("keep_row_id").alias("row_id"))
    )

    # Find rows to remove
    rows_to_remove = dupes.join(keep_ids, on="row_id", how="anti")

    # Apply to full dataset
    df_cleaned = df.join(rows_to_remove.select("row_id"), on="row_id", how="anti")

    print(f"POIs to remove (older): {len(rows_to_remove):,}")
    print(f"POIs remaining: {len(df_cleaned):,}")

    return df_cleaned, rows_to_remove


# ===== MAIN TEST FUNCTION =====

def main():
    print("="*80)
    print("DUPLICATE POI FILTER TESTING")
    print("="*80)

    # Load data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading: {input_file}")
    df = pl.read_parquet(input_file)

    # Filter to open venues
    df = df.filter(pl.col("date_closed").is_null())
    print(f"Open POIs: {len(df):,}\n")

    # ===== TEST TYPE 1: Same POI Recorded Twice =====

    print("\n" + "="*80)
    print("TESTING TYPE 1 VARIANTS")
    print("="*80)

    # Variant 1a: Rounded coordinates (6 dp ~= 11cm precision)
    dupes_type1_rounded = find_duplicate_pois_type1(
        df,
        name_threshold=0.7,
        coord_precision=6,
        use_distance=False
    )

    # Variant 1b: Haversine distance (15m threshold)
    dupes_type1_distance = find_duplicate_pois_type1(
        df,
        name_threshold=0.7,
        distance_threshold_m=15.0,
        use_distance=True
    )

    # ===== TEST TYPE 2: Same Venue, Different Business =====

    print("\n" + "="*80)
    print("TESTING TYPE 2 VARIANTS")
    print("="*80)

    # Variant 2a: Exact location, any category
    dupes_type2_anycategory = find_duplicate_pois_type2(
        df,
        name_dissimilarity_max=0.3,
        coord_precision=7,
        same_category=False
    )

    # Variant 2b: Exact location, same category
    dupes_type2_samecategory = find_duplicate_pois_type2(
        df,
        name_dissimilarity_max=0.3,
        coord_precision=7,
        same_category=True
    )

    # ===== SAVE RESULTS =====

    print("\n" + "="*80)
    print("SAVING RESULTS")
    print("="*80)

    output_dir = "data/POI_files/duplicate_analysis/"
    import os
    os.makedirs(output_dir, exist_ok=True)

    results = {
        "type1_rounded_6dp": dupes_type1_rounded,
        "type1_distance_15m": dupes_type1_distance,
        "type2_anycategory_7dp": dupes_type2_anycategory,
        "type2_samecategory_7dp": dupes_type2_samecategory,
    }

    for name, dupes_df in results.items():
        output_path = f"{output_dir}{name}.parquet"
        dupes_df.write_parquet(output_path)
        print(f"Saved: {output_path} ({len(dupes_df):,} POIs)")

    # ===== SUMMARY =====

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    print("\nType 1 (Same POI recorded twice):")
    print(f"  - Rounded coords (6dp): {len(dupes_type1_rounded):,} POIs in {dupes_type1_rounded.select(['lat_round', 'lng_round', 'fsq_category_id']).n_unique():,} groups")
    print(f"  - Distance-based (15m): {len(dupes_type1_distance):,} POIs in {dupes_type1_distance.select(['fsq_category_id']).n_unique():,} groups")

    print("\nType 2 (Same venue, different business):")
    print(f"  - Any category (7dp):  {len(dupes_type2_anycategory):,} POIs in {dupes_type2_anycategory.select(['lat_round', 'lng_round']).n_unique():,} groups")
    print(f"  - Same category (7dp): {len(dupes_type2_samecategory):,} POIs in {dupes_type2_samecategory.select(['lat_round', 'lng_round', 'fsq_category_id']).n_unique():,} groups")

    print("\n" + "="*80)
    print("Next steps:")
    print("  1. Review sample POIs from each variant")
    print("  2. Check if removed POIs have older dates")
    print("  3. Choose best variant and apply keep_newest_pois()")
    print("="*80)


if __name__ == "__main__":
    main()
