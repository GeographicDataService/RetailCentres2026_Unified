#!/usr/bin/env python3
"""
Comprehensive test to identify gaps in defunct brand filtering.

Tests for:
1. Partial matches (e.g., "McColl's Local" vs "McColl's")
2. Suffix variations (Ltd, PLC, Limited, UK)
3. Apostrophe/punctuation variations
4. Ampersand vs "and" variations
5. Spacing variations (hyphens, spaces)
"""

import polars as pl
import pandas as pd
import re
import sys
sys.path.insert(0, 'src')

def normalize_name(name: str) -> str:
    """Normalize a name for matching (current filter logic)."""
    return name.strip().lower()

def normalize_fuzzy(name: str) -> str:
    """
    More aggressive normalization for fuzzy matching.
    Removes punctuation, multiple spaces, common suffixes.
    """
    # Lowercase
    name = name.lower()

    # Remove common company suffixes
    suffixes = [
        r'\s+(ltd|limited|plc|uk|group|stores?|shops?|inc|corp|co\.?)$',
        r'\s+\(uk\)$',
        r'\s+\(.*?\)$'  # Any bracketed text at end
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)

    # Remove all punctuation except spaces
    name = re.sub(r"[^\w\s]", "", name)

    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)

    return name.strip()

def contains_match(poi_name: str, brand_name: str) -> bool:
    """Check if POI name contains the brand name as a substring."""
    poi_normalized = normalize_fuzzy(poi_name)
    brand_normalized = normalize_fuzzy(brand_name)

    # Check if brand is a word/phrase within the POI name
    # Use word boundaries to avoid false matches (e.g., "Costa" matching "Costa Coffee")
    pattern = r'\b' + re.escape(brand_normalized) + r'\b'
    return bool(re.search(pattern, poi_normalized))

def test_partial_matches(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs that contain defunct brand names but didn't get filtered."""
    print("\n" + "="*80)
    print("TEST 1: PARTIAL MATCHES (e.g., 'McColl's Local' contains 'McColl's')")
    print("="*80)

    results = []

    for brand in defunct_list[:20]:  # Test top 20 for performance
        brand_normalized = normalize_fuzzy(brand)

        # Find POIs that contain this brand name
        matches = foursquare.filter(
            pl.col("name").map_elements(
                lambda x: contains_match(str(x), brand),
                return_dtype=pl.Boolean
            )
        )

        if len(matches) > 0:
            sample_names = matches.select("name").head(5).to_series().to_list()
            results.append({
                "defunct_brand": brand,
                "poi_count": len(matches),
                "sample_names": "; ".join(sample_names)
            })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} defunct brands with partial matches")
    if len(df) > 0:
        print(df.to_string(index=False))
    return df

def test_suffix_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with common suffixes added to defunct brand names."""
    print("\n" + "="*80)
    print("TEST 2: SUFFIX VARIATIONS (Ltd, PLC, Limited, UK, Stores, etc.)")
    print("="*80)

    suffixes = ["Ltd", "Limited", "PLC", "UK", "Group", "Stores", "Store", "Shops", "Shop"]
    results = []

    for brand in defunct_list[:20]:
        for suffix in suffixes:
            # Try with space and without
            test_names = [
                f"{brand} {suffix}",
                f"{brand}{suffix}",
                f"{brand} ({suffix})"
            ]

            for test_name in test_names:
                count = foursquare.filter(
                    normalize_name(pl.col("name")) == normalize_name(pl.lit(test_name))
                ).height

                if count > 0:
                    results.append({
                        "defunct_brand": brand,
                        "poi_name_variant": test_name,
                        "poi_count": count
                    })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} suffix variations")
    if len(df) > 0:
        print(df.head(20).to_string(index=False))
    return df

def test_apostrophe_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with apostrophe variations."""
    print("\n" + "="*80)
    print("TEST 3: APOSTROPHE VARIATIONS (McColl's vs McColls)")
    print("="*80)

    results = []

    for brand in defunct_list[:30]:
        if "'" in brand or "'" in brand:  # Curly apostrophe
            # Try without apostrophe
            brand_no_apos = brand.replace("'", "").replace("'", "")

            count = foursquare.filter(
                normalize_name(pl.col("name")) == normalize_name(pl.lit(brand_no_apos))
            ).height

            if count > 0:
                results.append({
                    "defunct_brand": brand,
                    "poi_name_variant": brand_no_apos,
                    "poi_count": count
                })
        else:
            # Try adding apostrophe before 's'
            if brand.endswith("s"):
                brand_with_apos = brand[:-1] + "'s"

                count = foursquare.filter(
                    normalize_name(pl.col("name")) == normalize_name(pl.lit(brand_with_apos))
                ).height

                if count > 0:
                    results.append({
                        "defunct_brand": brand,
                        "poi_name_variant": brand_with_apos,
                        "poi_count": count
                    })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} apostrophe variations")
    if len(df) > 0:
        print(df.to_string(index=False))
    return df

def test_ampersand_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with ampersand vs 'and' variations."""
    print("\n" + "="*80)
    print("TEST 4: AMPERSAND VARIATIONS (& vs 'and')")
    print("="*80)

    results = []

    for brand in defunct_list[:30]:
        test_variants = []

        if "&" in brand:
            # Try replacing with "and"
            test_variants.append(brand.replace("&", "and"))
            test_variants.append(brand.replace("&", " and "))
        elif " and " in brand.lower():
            # Try replacing with "&"
            test_variants.append(re.sub(r'\s+and\s+', '&', brand, flags=re.IGNORECASE))
            test_variants.append(re.sub(r'\s+and\s+', ' & ', brand, flags=re.IGNORECASE))

        for variant in test_variants:
            count = foursquare.filter(
                normalize_name(pl.col("name")) == normalize_name(pl.lit(variant))
            ).height

            if count > 0:
                results.append({
                    "defunct_brand": brand,
                    "poi_name_variant": variant,
                    "poi_count": count
                })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} ampersand variations")
    if len(df) > 0:
        print(df.to_string(index=False))
    return df

def test_spacing_variations(foursquare: pl.DataFrame, defunct_list: list) -> pd.DataFrame:
    """Find POIs with spacing/hyphen variations."""
    print("\n" + "="*80)
    print("TEST 5: SPACING/HYPHEN VARIATIONS (Co-op vs Coop vs Co op)")
    print("="*80)

    results = []

    for brand in defunct_list[:30]:
        test_variants = []

        if "-" in brand:
            # Try without hyphen
            test_variants.append(brand.replace("-", ""))
            # Try with space instead
            test_variants.append(brand.replace("-", " "))
        elif " " in brand:
            # Try with hyphens
            test_variants.append(brand.replace(" ", "-"))
            # Try without spaces
            test_variants.append(brand.replace(" ", ""))

        for variant in test_variants:
            count = foursquare.filter(
                normalize_name(pl.col("name")) == normalize_name(pl.lit(variant))
            ).height

            if count > 0:
                results.append({
                    "defunct_brand": brand,
                    "poi_name_variant": variant,
                    "poi_count": count
                })

    df = pd.DataFrame(results).sort_values("poi_count", ascending=False)
    print(f"\nFound {len(df)} spacing variations")
    if len(df) > 0:
        print(df.to_string(index=False))
    return df

def sample_actual_poi_names(foursquare: pl.DataFrame, defunct_list: list, n_samples: int = 100):
    """Sample actual POI names to manually inspect for patterns."""
    print("\n" + "="*80)
    print(f"TEST 6: SAMPLE ACTUAL POI NAMES (looking for patterns)")
    print("="*80)

    # Get random sample of POI names
    sample = foursquare.select("name").sample(n=min(n_samples, len(foursquare))).to_series().to_list()

    print(f"\nRandom sample of {len(sample)} POI names:")
    for i, name in enumerate(sample[:50], 1):  # Show first 50
        print(f"  {i:3d}. {name}")

    return sample

def main():
    print("="*80)
    print("DEFUNCT BRAND FILTER GAP ANALYSIS")
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
    from retail.foursquare_qualityfilter import filter_defunct_retailers

    filtered = filter_defunct_retailers(
        foursquare,
        defunct_csv_path=defunct_csv,
        save_removed=False  # Don't save during testing
    )

    print(f"\nRemaining POIs after current filter: {len(filtered):,}")
    print(f"This is what we'll test for missed matches")

    # Run all tests on the FILTERED data (to find what was missed)
    all_results = {}

    all_results['partial_matches'] = test_partial_matches(filtered, defunct_list)
    all_results['suffix_variations'] = test_suffix_variations(filtered, defunct_list)
    all_results['apostrophe_variations'] = test_apostrophe_variations(filtered, defunct_list)
    all_results['ampersand_variations'] = test_ampersand_variations(filtered, defunct_list)
    all_results['spacing_variations'] = test_spacing_variations(filtered, defunct_list)

    # Summary
    print("\n" + "="*80)
    print("SUMMARY OF POTENTIAL GAPS")
    print("="*80)

    total_potential = sum(len(df) for df in all_results.values() if len(df) > 0)
    print(f"\nTotal pattern types with potential missing matches: {total_potential}")

    for test_name, df in all_results.items():
        if len(df) > 0:
            total_pois = df['poi_count'].sum() if 'poi_count' in df.columns else 0
            print(f"  {test_name}: {len(df)} patterns, ~{total_pois:,} POIs")

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
    print("Analysis complete!")
    print("="*80)

if __name__ == "__main__":
    main()
