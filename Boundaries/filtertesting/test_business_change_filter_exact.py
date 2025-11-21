#!/usr/bin/env python3
"""
Business change detection filter - EXACT category match.

Detects locations where businesses changed but POI wasn't properly refreshed.

Criteria:
- Coordinates match within ~1m (5 decimal places)
- fsq_category_id matches exactly
- Different business names (multiple unique names)
- Action: Keep POI with most RECENT date_created
"""

import polars as pl
import re
import sys
import networkx as nx
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

def _norm_text(s: str) -> str:
    """Normalize text for comparison."""
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def apply_same_date_safeguard(business_changes_df: pl.DataFrame, enable: bool = True) -> pl.DataFrame:
    """
    Safeguard: Keep ALL POIs in groups where all have same creation date.

    Rationale: Same date suggests bulk import of current state (e.g., outlet centers),
    not historical business turnover. These POIs are all current and should be kept.

    Parameters:
    - business_changes_df: DataFrame with 'group_key', 'created_date', 'row_id' columns
    - enable: Set to False to disable this safeguard

    Returns:
    - DataFrame with 'keep' column updated for same-date groups
    """
    if not enable:
        print("  Same-date safeguard: DISABLED")
        return business_changes_df

    # Identify groups where all POIs have same creation date
    same_date_groups = (
        business_changes_df
        .group_by("group_key")
        .agg([
            pl.col("created_date").n_unique().alias("unique_dates"),
            pl.first("poi_count").alias("count")
        ])
        .filter(pl.col("unique_dates") == 1)  # All POIs same date
    )

    print(f"  Same-date safeguard: ENABLED")
    print(f"    Groups with same date: {len(same_date_groups):,}")
    print(f"    POIs in these groups: {same_date_groups.select(pl.col('count').sum()).item():,}")
    print(f"    → Keeping ALL POIs in these groups (likely bulk imports)")

    # Mark these groups for exclusion from filtering
    result = business_changes_df.join(
        same_date_groups.select("group_key").with_columns(pl.lit(True).alias("is_same_date_group")),
        on="group_key",
        how="left"
    )

    return result

def main():
    # TOGGLE: Set to False to disable same-date safeguard
    ENABLE_SAME_DATE_SAFEGUARD = True

    print("="*80)
    print("BUSINESS CHANGE DETECTION - EXACT CATEGORY MATCH")
    print("="*80)
    print("\nCriteria:")
    print("  - Coordinates match within ~1m (5 decimal places)")
    print("  - fsq_category_id matches exactly")
    print("  - Different business names")
    print("  - Keep: Most recent date_created")
    print(f"\nSafeguards:")
    print(f"  - Same-date group protection: {'ENABLED' if ENABLE_SAME_DATE_SAFEGUARD else 'DISABLED'}")

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\n[1/4] Loading and filtering: {input_file}")
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

    print(f"After quality filters: {len(foursquare_filt):,}")

    # Find business changes
    print(f"\n[2/4] Finding business changes...")

    df = foursquare_filt

    # Add row_id if not present
    if "row_id" not in df.columns:
        df = df.with_row_index("row_id")

    # Round coordinates to 5 decimal places (~1m precision)
    # Add normalized names
    df_with_location = df.with_columns([
        pl.col("lat").cast(pl.Float64).round(5).alias("lat_round"),
        pl.col("lng").cast(pl.Float64).round(5).alias("lng_round"),
        pl.col("name").map_elements(_norm_text, return_dtype=str).alias("name_norm"),
    ])

    # Group by location + exact category
    keys = ["lat_round", "lng_round", "fsq_category_id"]

    location_groups = (
        df_with_location
        .group_by(keys)
        .agg([
            pl.count("name").alias("poi_count"),
            pl.n_unique("name_norm").alias("unique_names"),
            pl.col("row_id").alias("all_row_ids"),
        ])
        .filter(pl.col("poi_count") > 1)  # Multiple POIs at same location
        .filter(pl.col("unique_names") > 1)  # Different business names
    )

    print(f"  Locations with business changes: {len(location_groups):,}")
    print(f"  Total POIs involved: {location_groups.select(pl.col('poi_count').sum()).item():,}")

    if len(location_groups) == 0:
        print("\nNo business changes detected. Exiting.")
        return

    # Flatten to get all POIs in business change groups
    business_change_pois = (
        location_groups
        .explode("all_row_ids")
        .select([
            "lat_round", "lng_round", "fsq_category_id",
            "poi_count", "unique_names", "all_row_ids"
        ])
        .rename({"all_row_ids": "row_id"})
    )

    # Join with original data to get full details
    business_changes_full = (
        business_change_pois
        .join(df, on="row_id", how="inner")
        .with_columns([
            # Parse date_created
            pl.col("date_created")
              .str.strptime(pl.Datetime, format="%Y-%m-%d", strict=False)
              .alias("created_date"),
        ])
    )

    print(f"\n[3/4] Determining which POIs to keep (most recent date_created)...")

    # Add group key to all rows
    business_changes_full = business_changes_full.with_columns(
        pl.concat_str([
            pl.col("lat_round").cast(pl.Utf8),
            pl.lit("_"),
            pl.col("lng_round").cast(pl.Utf8),
            pl.lit("_"),
            pl.col("fsq_category_id").cast(pl.Utf8)
        ]).alias("group_key")
    )

    # Apply same-date safeguard
    business_changes_full = apply_same_date_safeguard(
        business_changes_full,
        enable=ENABLE_SAME_DATE_SAFEGUARD
    )

    # For groups NOT in same-date exclusion, find the row with most recent date_created
    if ENABLE_SAME_DATE_SAFEGUARD:
        # Only process groups without same dates
        groups_to_filter = business_changes_full.filter(
            pl.col("is_same_date_group").is_null()
        )
    else:
        groups_to_filter = business_changes_full

    keep_ids = (
        groups_to_filter
        .sort(["group_key", "created_date"], descending=[False, True])
        .group_by("group_key")
        .agg(pl.first("row_id").alias("keep_row_id"))
    )

    # Mark which to keep/remove
    business_changes_final = (
        business_changes_full
        .join(keep_ids, on="group_key", how="left")
        .with_columns(
            # Keep if: (1) in same-date group OR (2) is the keep_row_id
            (
                (pl.col("is_same_date_group").fill_null(False)) |
                (pl.col("row_id") == pl.col("keep_row_id"))
            ).alias("keep")
        )
        .select([
            "group_key", "poi_count", "unique_names", "keep",
            "row_id", "fsq_place_id", "name", "lat", "lng",
            "fsq_category_id", "fsq_category_labels",
            "address", "tel", "website",
            "date_created", "date_refreshed"
        ])
        .sort(["poi_count", "group_key", "keep"], descending=[True, False, True])
    )

    to_remove = business_changes_final.filter(pl.col("keep") == False)
    to_keep = business_changes_final.filter(pl.col("keep") == True)

    print(f"  POIs to keep (most recent): {len(to_keep):,}")
    print(f"  POIs to remove: {len(to_remove):,}")

    # Save results
    print(f"\n[4/4] Saving results...")

    import os
    output_dir = "data/POI_files/business_change_removal/"
    os.makedirs(output_dir, exist_ok=True)

    # Save all with keep/remove flag
    all_path = f"{output_dir}business_changes_all.parquet"
    business_changes_final.write_parquet(all_path)
    print(f"\n✓ All business changes: {all_path}")

    # Save removed POIs
    remove_path = f"{output_dir}business_changes_to_remove.parquet"
    to_remove.write_parquet(remove_path)
    print(f"✓ POIs to remove: {remove_path}")

    # Save CSV for review (top 500 groups)
    csv_path = f"{output_dir}business_changes_to_remove_top500.csv"
    to_remove.head(500).drop("fsq_category_labels").write_csv(csv_path)
    print(f"✓ CSV (top 500): {csv_path}")

    # Create filtered dataset
    filtered_dataset = df.join(
        to_remove.select("row_id").with_columns(pl.lit(True).alias("remove")),
        on="row_id",
        how="left"
    ).filter(pl.col("remove").is_null()).drop("remove")

    filtered_path = f"{output_dir}foursquare_business_change_filtered.parquet"
    filtered_dataset.write_parquet(filtered_path)
    print(f"✓ Filtered dataset: {filtered_path}")

    # Generate report
    print(f"\n{'='*80}")
    print("REPORT: BUSINESS CHANGE REMOVAL")
    print(f"{'='*80}")

    print(f"\nDataset Summary:")
    print(f"  Original POIs:                {len(df):,}")
    print(f"  POIs with business changes:   {len(business_changes_final):,}")
    print(f"  POIs to remove:               {len(to_remove):,}")
    print(f"  Final dataset size:           {len(filtered_dataset):,}")
    print(f"  Reduction:                    {100 * len(to_remove) / len(df):.3f}%")

    print(f"\nLocation Groups:")
    print(f"  Number of groups:             {len(location_groups):,}")
    print(f"  Average POIs per group:       {len(business_changes_final) / len(location_groups):.2f}")

    # Group size distribution
    print(f"\nGroup Size Distribution:")
    size_dist = (
        business_changes_final
        .group_by("poi_count")
        .agg((pl.len() / pl.first("poi_count")).cast(pl.Int32).alias("num_locations"))
        .sort("poi_count", descending=True)
        .head(15)
    )
    print(size_dist)

    # Category analysis
    print(f"\nTop 20 Categories with Business Changes:")
    cat_dist = (
        business_changes_final
        .group_by("fsq_category_labels")
        .agg([
            pl.len().alias("pois"),
            (pl.len() / pl.first("poi_count")).cast(pl.Int32).alias("locations")
        ])
        .sort("pois", descending=True)
        .head(20)
    )
    for row in cat_dist.iter_rows(named=True):
        labels = str(row["fsq_category_labels"])[:60] if row["fsq_category_labels"] else "Unknown"
        print(f"  {row['pois']:4d} POIs, {row['locations']:4d} locations: {labels}")

    # Show examples
    print(f"\n{'='*80}")
    print("SAMPLE: Top 30 locations with most business changes")
    print(f"{'='*80}")

    sample_groups = (
        business_changes_final
        .group_by("group_key")
        .agg([
            pl.first("poi_count").alias("count"),
            pl.first("fsq_category_labels").alias("category"),
            pl.col("name").alias("names"),
            pl.col("date_created").alias("dates"),
            pl.col("keep").alias("keep_flags"),
        ])
        .sort("count", descending=True)
        .head(30)
    )

    for i, row in enumerate(sample_groups.iter_rows(named=True), 1):
        names_with_flags = []
        for name, date, keep in zip(row["names"], row["dates"], row["keep_flags"]):
            flag = "✓ KEEP" if keep else "✗ REMOVE"
            names_with_flags.append(f"{name[:40]:40s} [{date}] {flag}")

        cat = str(row["category"])[:60] if row["category"] else "Unknown"
        print(f"\n{i}. Group with {row['count']} POIs:")
        print(f"   Category: {cat}")
        for nf in names_with_flags[:5]:  # Show max 5
            print(f"   - {nf}")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")
    print(f"\nOutput files:")
    print(f"  - All business changes: {all_path}")
    print(f"  - POIs to remove:       {remove_path}")
    print(f"  - Filtered dataset:     {filtered_path}")

if __name__ == "__main__":
    main()
