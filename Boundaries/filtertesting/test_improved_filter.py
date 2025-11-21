#!/usr/bin/env python3
"""
Test the improved defunct filter to validate improvements.

Compares before/after to show:
- How many additional POIs are now caught
- Which brands benefit from improved normalization
"""

import polars as pl
import sys
sys.path.insert(0, 'src')

def test_normalization():
    """Test the normalization function directly."""
    from retail.foursquare_qualityfilter import _make_key

    test_cases = [
        ("Jack's", "jacks"),
        ("Alldays Stores", "alldays"),
        ("Safeway Stores Limited", "safeway"),
        ("Kwik-Save", "kwiksave"),
        ("Floors-2-Go", "floors2go"),
        ("Past Times", "past times"),
        ("McColl's Ltd", "mccolls"),
        ("Focus DIY Limited", "focus diy"),
        ("Hawkin's Bazaar", "hawkins bazaar"),
        ("MK One", "mk one"),
        ("C&A UK", "c&a"),
    ]

    print("="*80)
    print("TESTING NORMALIZATION FUNCTION")
    print("="*80)

    # Create a small dataframe to test
    test_df = pl.DataFrame({"name": [case[0] for case in test_cases]})
    test_df = test_df.with_columns(normalized=_make_key(pl.col("name")))

    print("\nNormalization results:")
    for i, (original, expected) in enumerate(test_cases):
        actual = test_df.row(i)[1]
        status = "✓" if actual == expected else "✗"
        print(f"{status} '{original}' → '{actual}' (expected: '{expected}')")

def compare_before_after():
    """Run the improved filter and show results."""
    from retail.foursquare_qualityfilter import filter_defunct_retailers

    print("\n" + "="*80)
    print("TESTING IMPROVED FILTER ON FULL DATASET")
    print("="*80)

    # Load data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading: {input_file}")
    foursquare = pl.read_parquet(input_file)

    # Filter to open venues
    foursquare = foursquare.filter(pl.col("date_closed").is_null())
    print(f"Open POIs: {len(foursquare):,}")

    # Run improved filter
    print("\nRunning improved defunct filter...")
    filtered = filter_defunct_retailers(
        foursquare,
        defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv",
        save_removed=True,
        output_dir="data/POI_files/defunct_removed_improved",
        top_n_brands=20
    )

    removed_count = len(foursquare) - len(filtered)

    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    print(f"Total open POIs:        {len(foursquare):,}")
    print(f"POIs removed (defunct): {removed_count:,}")
    print(f"POIs remaining:         {len(filtered):,}")
    print(f"Removal rate:           {100 * removed_count / len(foursquare):.3f}%")

    # Compare with expected improvements
    print("\n" + "="*80)
    print("COMPARISON WITH PREVIOUS ANALYSIS")
    print("="*80)
    print("Previous filter removed:  2,159 POIs")
    print(f"Improved filter removed:  {removed_count:,} POIs")
    print(f"Additional POIs caught:   {removed_count - 2159:,}")
    print(f"Improvement:              +{100 * (removed_count - 2159) / 2159:.1f}%")

    expected_improvements = {
        "Suffix variations": 77,
        "Apostrophe variations": 78,
        "Spacing variations": 76 - 344,  # Minus Bon Marché
    }
    expected_total = sum(expected_improvements.values())

    print(f"\nExpected additional POIs: ~{expected_total}")
    print(f"Actual additional POIs:   {removed_count - 2159:,}")

    if abs(removed_count - 2159 - expected_total) < 50:
        print("✓ Results match expectations!")
    else:
        print("⚠ Results differ from expectations - review manually")

    print("\n" + "="*80)
    print("OUTPUT FILES")
    print("="*80)
    print("Saved to: data/POI_files/defunct_removed_improved/")
    print("  - defunct_removed_summary.csv (top 20 brands)")
    print("  - complete_defunct_summary.csv (all matched brands)")
    print("  - all_removed_pois.geo.parquet (all removed POIs)")
    print("  - [Brand].geo.parquet (individual brand files)")
    print("="*80)

def main():
    print("="*80)
    print("IMPROVED DEFUNCT FILTER TEST")
    print("="*80)
    print("\nImprovements:")
    print("  1. Suffix stripping (Ltd, Limited, Stores, etc.)")
    print("  2. Apostrophe handling (Jack's ↔ jacks)")
    print("  3. Hyphen removal (Kwik-Save → kwiksave)")
    print("  4. Removed Bon Marché false positive")
    print("\n")

    # Test normalization
    test_normalization()

    # Test on full dataset
    compare_before_after()

if __name__ == "__main__":
    main()
