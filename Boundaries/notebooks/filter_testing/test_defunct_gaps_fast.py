#!/usr/bin/env python3
"""
Fast version: Comprehensive test to identify gaps in defunct brand filtering.
Uses Polars-native operations for better performance.
"""

import polars as pl
import pandas as pd
import re
import sys
sys.path.insert(0, 'src')

def test_suffix_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with common suffixes added to defunct brand names."""
    print("\n" + "="*80)
    print("TEST 1: SUFFIX VARIATIONS (Ltd, PLC, Limited, UK, Stores, etc.)")
    print("="*80)

    suffixes = ["Ltd", "Limited", "PLC", "UK", "Group", "Stores", "Store", "Shops", "Shop", "Supermarket"]
    results = []

    # Normalize names once
    fs_normalized = foursquare.with_columns(
        name_norm=pl.col("name").str.strip_chars().str.to_lowercase()
    )

    for brand in defunct_list:
        brand_norm = brand.strip().lower()

        for suffix in suffixes:
            # Try with space and without
            test_patterns = [
                f"{brand_norm} {suffix.lower()}",
                f"{brand_norm}{suffix.lower()}",
                f"{brand_norm} ({suffix.lower()})"
            ]

            for test_pattern in test_patterns:
                count = fs_normalized.filter(
                    pl.col("name_norm") == test_pattern
                ).height

                if count > 0:
                    results.append({
                        "defunct_brand": brand,
                        "poi_name_variant": test_pattern,
                        "poi_count": count
                    })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} suffix variations with {df['poi_count'].sum() if len(df) > 0 else 0:,} total POIs")
    if len(df) > 0:
        print(df.head(30).to_string(index=False))
    return df

def test_apostrophe_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with apostrophe variations."""
    print("\n" + "="*80)
    print("TEST 2: APOSTROPHE VARIATIONS (McColl's vs McColls)")
    print("="*80)

    results = []

    # Normalize names once
    fs_normalized = foursquare.with_columns(
        name_norm=pl.col("name").str.strip_chars().str.to_lowercase()
    )

    for brand in defunct_list:
        brand_norm = brand.strip().lower()

        test_variants = []

        if "'" in brand_norm or "'" in brand_norm:  # Curly apostrophe
            # Try without apostrophe
            test_variants.append(brand_norm.replace("'", "").replace("'", ""))
        else:
            # Try adding apostrophe before 's'
            if brand_norm.endswith("s"):
                test_variants.append(brand_norm[:-1] + "'s")
            # Also try adding possessive to non-s ending
            test_variants.append(brand_norm + "'s")

        for variant in test_variants:
            count = fs_normalized.filter(
                pl.col("name_norm") == variant
            ).height

            if count > 0:
                results.append({
                    "defunct_brand": brand,
                    "poi_name_variant": variant,
                    "poi_count": count
                })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} apostrophe variations with {df['poi_count'].sum() if len(df) > 0 else 0:,} total POIs")
    if len(df) > 0:
        print(df.head(20).to_string(index=False))
    return df

def test_ampersand_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with ampersand vs 'and' variations."""
    print("\n" + "="*80)
    print("TEST 3: AMPERSAND VARIATIONS (& vs 'and')")
    print("="*80)

    results = []

    # Normalize names once
    fs_normalized = foursquare.with_columns(
        name_norm=pl.col("name").str.strip_chars().str.to_lowercase()
    )

    for brand in defunct_list:
        brand_norm = brand.strip().lower()
        test_variants = []

        if "&" in brand_norm:
            # Try replacing with "and"
            test_variants.append(re.sub(r'\s*&\s*', ' and ', brand_norm))
            test_variants.append(brand_norm.replace("&", "and"))
        elif " and " in brand_norm:
            # Try replacing with "&"
            test_variants.append(re.sub(r'\s+and\s+', ' & ', brand_norm))
            test_variants.append(re.sub(r'\s+and\s+', '&', brand_norm))

        for variant in test_variants:
            variant = variant.strip()
            count = fs_normalized.filter(
                pl.col("name_norm") == variant
            ).height

            if count > 0:
                results.append({
                    "defunct_brand": brand,
                    "poi_name_variant": variant,
                    "poi_count": count
                })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} ampersand variations with {df['poi_count'].sum() if len(df) > 0 else 0:,} total POIs")
    if len(df) > 0:
        print(df.to_string(index=False))
    return df

def test_spacing_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with spacing/hyphen variations."""
    print("\n" + "="*80)
    print("TEST 4: SPACING/HYPHEN VARIATIONS (Co-op vs Coop vs Co op)")
    print("="*80)

    results = []

    # Normalize names once
    fs_normalized = foursquare.with_columns(
        name_norm=pl.col("name").str.strip_chars().str.to_lowercase()
    )

    for brand in defunct_list:
        brand_norm = brand.strip().lower()
        test_variants = []

        if "-" in brand_norm:
            # Try without hyphen
            test_variants.append(brand_norm.replace("-", ""))
            # Try with space instead
            test_variants.append(brand_norm.replace("-", " "))
        elif " " in brand_norm:
            # Try with hyphens
            test_variants.append(brand_norm.replace(" ", "-"))
            # Try without spaces
            test_variants.append(brand_norm.replace(" ", ""))

        for variant in test_variants:
            count = fs_normalized.filter(
                pl.col("name_norm") == variant
            ).height

            if count > 0:
                results.append({
                    "defunct_brand": brand,
                    "poi_name_variant": variant,
                    "poi_count": count
                })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} spacing variations with {df['poi_count'].sum() if len(df) > 0 else 0:,} total POIs")
    if len(df) > 0:
        print(df.to_string(index=False))
    return df

def test_partial_contains(foursquare: pl.DataFrame, defunct_list: list, top_n: int = 10) -> pd.DataFrame:
    """
    Find POIs where name CONTAINS defunct brand (e.g., 'McColl's Local' contains 'McColl's').
    Only test top N brands for performance.
    """
    print("\n" + "="*80)
    print(f"TEST 5: PARTIAL MATCHES (testing top {top_n} defunct brands)")
    print("="*80)

    results = []

    # Normalize names once
    fs_normalized = foursquare.with_columns(
        name_norm=pl.col("name").str.strip_chars().str.to_lowercase()
    )

    for brand in defunct_list[:top_n]:
        brand_norm = brand.strip().lower()

        # Use Polars' contains for efficient string matching
        matches = fs_normalized.filter(
            pl.col("name_norm").str.contains(re.escape(brand_norm))
        )

        if len(matches) > 0:
            # Get some sample names
            sample_names = matches.select("name").head(5).to_series().to_list()

            results.append({
                "defunct_brand": brand,
                "poi_count": len(matches),
                "sample_names": "; ".join(str(n) for n in sample_names)
            })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} brands with partial matches, {df['poi_count'].sum() if len(df) > 0 else 0:,} total POIs")
    if len(df) > 0:
        print(df.to_string(index=False, max_colwidth=80))
    return df

def analyze_unmatched_brands(defunct_list: list, all_variants: list) -> pd.DataFrame:
    """Check which defunct brands had NO matches across all tests."""
    print("\n" + "="*80)
    print("TEST 6: DEFUNCT BRANDS WITH NO VARIATIONS FOUND")
    print("="*80)

    matched_brands = set(all_variants)
    unmatched = [b for b in defunct_list if b not in matched_brands]

    print(f"\n{len(unmatched)} defunct brands had no variations found in any test")
    print("(These are truly not in the dataset, or have very different naming)")
    print("\nSample of unmatched brands:")
    for brand in unmatched[:20]:
        print(f"  - {brand}")

    return pd.DataFrame({"unmatched_brand": unmatched})

def main():
    print("="*80)
    print("DEFUNCT BRAND FILTER GAP ANALYSIS (FAST VERSION)")
    print("="*80)

    # Load data
    print("\nLoading data...")
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    foursquare = pl.read_parquet(input_file)
    print(f"Loaded {len(foursquare):,} POIs")

    # Load defunct brands
    defunct_csv = "data/input_files/defunct_uk_retailers_wikipedia_full.csv"
    defunct_df = pl.read_csv(defunct_csv)

    # Clean defunct list (same as filter does)
    defunct_df = (
        defunct_df
        .unique(subset=["Brand"])
        .with_columns(
            pl.col("Brand").str.replace(r"\s*\(.*?\)", "", literal=False)
        )
    )

    defunct_list = defunct_df.get_column("Brand").to_list()
    print(f"Loaded {len(defunct_list)} defunct brands")

    # Filter to only open venues (same as quality filter does)
    foursquare = foursquare.filter(pl.col("date_closed").is_null())
    print(f"Filtered to {len(foursquare):,} open venues")

    # Apply current defunct filter to get what remains
    print("\nApplying current defunct filter...")
    from retail.foursquare_qualityfilter import filter_defunct_retailers

    filtered = filter_defunct_retailers(
        foursquare,
        defunct_csv_path=defunct_csv,
        save_removed=False  # Don't save during testing
    )

    print(f"\nRemaining POIs after current filter: {len(filtered):,}")
    print(f"POIs removed by current filter: {len(foursquare) - len(filtered):,}")
    print("\nNow testing for variations that were MISSED by the filter...\n")

    # Run all tests on the FILTERED data (to find what was missed)
    all_results = {}

    all_results['suffix_variations'] = test_suffix_variations(filtered, defunct_list)
    all_results['apostrophe_variations'] = test_apostrophe_variations(filtered, defunct_list)
    all_results['ampersand_variations'] = test_ampersand_variations(filtered, defunct_list)
    all_results['spacing_variations'] = test_spacing_variations(filtered, defunct_list)
    all_results['partial_matches'] = test_partial_contains(filtered, defunct_list, top_n=30)

    # Track which brands had any variations found
    all_variant_brands = set()
    for df in all_results.values():
        if len(df) > 0 and 'defunct_brand' in df.columns:
            all_variant_brands.update(df['defunct_brand'].unique())

    all_results['unmatched_brands'] = analyze_unmatched_brands(defunct_list, list(all_variant_brands))

    # Summary
    print("\n" + "="*80)
    print("SUMMARY OF POTENTIAL GAPS")
    print("="*80)

    total_potential_pois = 0
    for test_name, df in all_results.items():
        if len(df) > 0 and 'poi_count' in df.columns:
            total_pois = df['poi_count'].sum()
            total_potential_pois += total_pois
            print(f"\n{test_name}:")
            print(f"  - {len(df)} unique variations found")
            print(f"  - ~{total_pois:,} POIs potentially missed")

    print(f"\n{'='*80}")
    print(f"TOTAL ESTIMATED MISSING POIs: ~{total_potential_pois:,}")
    print(f"(Note: This is an estimate; there may be overlaps between tests)")
    print(f"{'='*80}")

    # Save results
    print("\n" + "="*80)
    print("SAVING RESULTS")
    print("="*80)

    output_dir = "data/POI_files/defunct_gaps_analysis/"
    import os
    os.makedirs(output_dir, exist_ok=True)

    for test_name, df in all_results.items():
        if len(df) > 0:
            output_path = f"{output_dir}{test_name}.csv"
            df.to_csv(output_path, index=False)
            print(f"Saved: {output_path}")

    print("\n" + "="*80)
    print("Analysis complete! Check output directory for detailed CSVs.")
    print("="*80)

if __name__ == "__main__":
    main()
