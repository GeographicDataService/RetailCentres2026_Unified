#!/usr/bin/env python3
"""
Analyze POIs with 5-digit patterns (potential US ZIPs) that slipped through foreign address filter.

This investigates whether the current end-of-line ZIP pattern is missing legitimate foreign addresses.
"""

import polars as pl
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

# Current patterns from foreign address filter
US_STATE_CODES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","IA","ID","IL","IN","KS","KY","LA",
    "MA","MD","ME","MI","MN","MO","MS","MT","NC","ND","NE","NH","NJ","NM","NV","NY","OH","OK",
    "OR","PA","RI","SC","SD","TN","TX","UT","VA","VT","WA","WI","WV","DC"
]
US_STATE_NAMES = [
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware",
    "Florida","Georgia","Hawaii","Iowa","Idaho","Illinois","Indiana","Kansas","Kentucky",
    "Louisiana","Massachusetts","Maryland","Maine","Michigan","Minnesota","Missouri","Mississippi",
    "Montana","North Carolina","North Dakota","Nebraska","New Hampshire","New Jersey","New Mexico",
    "Nevada","New York","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina",
    "South Dakota","Tennessee","Texas","Utah","Virginia","Vermont","Washington","Wisconsin",
    "West Virginia","District of Columbia"
]

CA_PROV_CODES = ["AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"]
CA_PROV_NAMES = [
    "Alberta","British Columbia","Manitoba","New Brunswick","Newfoundland and Labrador","Nova Scotia",
    "Northwest Territories","Nunavut","Ontario","Prince Edward Island","Quebec","Saskatchewan","Yukon"
]

AU_STATE_CODES = ["NSW","VIC","QLD","SA","WA","TAS","ACT","NT"]
AU_STATE_NAMES = [
    "New South Wales","Victoria","Queensland","South Australia","Western Australia","Tasmania",
    "Australian Capital Territory","Northern Territory"
]

COUNTRY_WORDS = [
    r"United\s+States", r"U\.?S\.?A\.?", r"Canada", r"France", r"Germany", r"Deutschland",
    r"Spain", r"España", r"Italy", r"Italia", r"Australia", r"Ireland",
    r"Republic\s+of\s+Ireland", r"Netherlands", r"Nederland", r"Belgium", r"Belgique",
    r"Luxembourg", r"Switzerland", r"Suisse", r"Sweden", r"Norway", r"Denmark",
    r"Finland", r"Austria", r"Portugal", r"Poland", r"Czech", r"Hungary", r"Greece"
]

SAFE_PASSES = [
    r"(?i)\bNorthern\s+Ireland\b",
    r"(?i)\bDenmark\s+Hill\b",
    r"(?i)\bDenmark\s+St(?:reet)?\b",
    r"(?i)\bCanada\s+Place\b",
    r"(?i)\bCanada\s+Water\b",
    r"(?i)\bNew\s+England\b",
]
SAFE_PASS_PATTERN = "|".join(f"({p})" for p in SAFE_PASSES)

# Build patterns
PAT_US_ZIP_END = r"\d{5}(?:-\d{4})?$"
PAT_CA_PC_END = r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d$"
PAT_NL_PC_END = r"\d{4}\s?[A-Z]{2}$"
PAT_IE_EIR_END = r"[A-Z]\d{2}\s?[A-Z0-9]{4}$"

PAT_US_STATE_TAIL = rf"(?:,?\s*)\b({'|'.join(US_STATE_CODES)})\b(?:\s*{PAT_US_ZIP_END})?$"
PAT_US_STATE_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(US_STATE_NAMES)})\b(?:\s*{PAT_US_ZIP_END})?$"
PAT_CA_PROV_TAIL = rf"(?:,?\s*)\b({'|'.join(CA_PROV_CODES)})\b(?:\s*{PAT_CA_PC_END})?$"
PAT_CA_PROV_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(CA_PROV_NAMES)})\b(?:\s*{PAT_CA_PC_END})?$"
PAT_AU_STATE_TAIL = rf"(?:,?\s*)\b({'|'.join(AU_STATE_CODES)})\b(?:\s*\d{{4}})?$"
PAT_AU_STATE_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(AU_STATE_NAMES)})\b(?:\s*\d{{4}})?$"
PAT_COUNTRY_WORDS = rf"(?i)\b({'|'.join(COUNTRY_WORDS)})\b"

# Existing foreign indicator
def get_existing_foreign_indicator():
    return (
        pl.col("address").str.contains(PAT_COUNTRY_WORDS, literal=False)
        | pl.col("address").str.contains(PAT_US_STATE_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_US_STATE_NAME_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_CA_PROV_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_CA_PROV_NAME_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_AU_STATE_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_AU_STATE_NAME_TAIL, literal=False)
        | pl.col("address").str.contains(PAT_CA_PC_END, literal=False)
        | pl.col("address").str.contains(PAT_NL_PC_END, literal=False)
        | pl.col("address").str.contains(PAT_IE_EIR_END, literal=False)
    ) & (~pl.col("address").str.contains(SAFE_PASS_PATTERN, literal=False))


def main():
    print("="*80)
    print("ANALYZING MISSED FOREIGN ADDRESSES (5-DIGIT ZIP PATTERNS)")
    print("="*80)

    # Load and filter data
    input_file = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"
    print(f"\nLoading and filtering: {input_file}")
    foursquare = pl.read_parquet(input_file)

    foursquare_filt = filter_foursquare_invmethod(foursquare)
    foursquare_filt = foursquare_filt.filter(pl.col("date_closed").is_null())
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

    # Find POIs NOT caught by existing filter
    existing_foreign = get_existing_foreign_indicator()
    has_uk_postcode = pl.col("postcode").is_not_null()

    # POIs already flagged as foreign
    already_caught = foursquare_filt.filter(existing_foreign & ~has_uk_postcode)
    print(f"\nAlready caught by current filter: {len(already_caught):,}")

    # POIs NOT caught but have 5-digit patterns
    not_caught = foursquare_filt.filter(~(existing_foreign & ~has_uk_postcode))

    # Look for 5-digit patterns (potential ZIPs) anywhere in address
    # Pattern: word boundary + 5 digits + word boundary
    PAT_FIVE_DIGITS = r'\b\d{5}\b'

    potential_missed = (
        not_caught
        .filter(pl.col("address").is_not_null())
        .filter(pl.col("postcode").is_null())  # No UK postcode
        .filter(pl.col("address").str.contains(PAT_FIVE_DIGITS, literal=False))
    )

    print(f"\nPOIs with 5-digit patterns (not caught): {len(potential_missed):,}")

    # Analyze what these look like
    print(f"\n{'='*80}")
    print("ANALYSIS OF MISSED POIs")
    print(f"{'='*80}")

    # Check how many also have other foreign indicators (just not matching current patterns)
    with_us_keywords = potential_missed.filter(
        pl.col("address").str.contains(r'(?i)\b(suite|highway|avenue|boulevard|street|road|dr|rd|ave|blvd|st|tx|ca|fl|ny)\b', literal=False)
    )
    print(f"\nWith US address keywords: {len(with_us_keywords):,}")

    with_country_like = potential_missed.filter(
        pl.col("address").str.contains(r'(?i)(united states|usa|america|milan|milano|roma|paris)', literal=False)
    )
    print(f"With country mentions: {len(with_country_like):,}")

    # Category breakdown
    print("\nTop 20 categories:")
    cat_breakdown = (
        potential_missed
        .group_by("fsq_category_labels")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
        .head(20)
    )
    for row in cat_breakdown.iter_rows(named=True):
        label = str(row["fsq_category_labels"])[:60] if row["fsq_category_labels"] else "Unknown"
        print(f"  {row['count']:4d} - {label}")

    # Manual review sample
    print(f"\n{'='*80}")
    print("SAMPLE: 50 POIs with 5-digit patterns")
    print(f"{'='*80}")

    sample = potential_missed.select([
        "fsq_place_id", "name", "address", "fsq_category_labels"
    ]).head(50)

    for i, row in enumerate(sample.iter_rows(named=True), 1):
        addr = row["address"] or "(no address)"
        cat = str(row["fsq_category_labels"])[:40] if row["fsq_category_labels"] else "Unknown"
        print(f"\n{i:2d}. {row['name']}")
        print(f"    Address: {addr}")
        print(f"    Category: {cat}")

    # Test enhanced pattern
    print(f"\n{'='*80}")
    print("TESTING ENHANCED PATTERN")
    print(f"{'='*80}")

    # Enhanced pattern: catch 5-digit anywhere if accompanied by US keywords
    PAT_US_ADDRESS_CONTEXT = r'(?i)\b(suite|highway|avenue|boulevard|drive|street|road|lane|court|circle|way|dr|rd|ave|blvd|st|ln|hwy)\b'
    PAT_US_STATE_ABBR = rf"\b({'|'.join(US_STATE_CODES)})\b"

    enhanced_foreign = (
        get_existing_foreign_indicator() |
        (
            # Has 5-digit pattern AND US address context AND no UK postcode
            pl.col("address").str.contains(PAT_FIVE_DIGITS, literal=False) &
            (
                pl.col("address").str.contains(PAT_US_ADDRESS_CONTEXT, literal=False) |
                pl.col("address").str.contains(PAT_US_STATE_ABBR, literal=False) |
                pl.col("address").str.contains(r'(?i)(USA|United States|America)', literal=False)
            )
        )
    ) & (~pl.col("address").str.contains(SAFE_PASS_PATTERN, literal=False))

    enhanced_caught = foursquare_filt.filter(enhanced_foreign & ~has_uk_postcode)
    newly_caught = len(enhanced_caught) - len(already_caught)

    print(f"\nCurrent filter catches:    {len(already_caught):,}")
    print(f"Enhanced filter catches:   {len(enhanced_caught):,}")
    print(f"Newly caught:              {newly_caught:,}")
    print(f"Percentage of dataset:     {100 * len(enhanced_caught) / len(foursquare_filt):.3f}%")

    # Check for false positives in newly caught
    print(f"\n{'='*80}")
    print("CHECKING FOR FALSE POSITIVES IN NEWLY CAUGHT")
    print(f"{'='*80}")

    # Get newly caught POIs
    newly_caught_pois = (
        foursquare_filt
        .with_columns([
            (existing_foreign & ~has_uk_postcode).alias("old_foreign"),
            (enhanced_foreign & ~has_uk_postcode).alias("new_foreign")
        ])
        .filter(~pl.col("old_foreign") & pl.col("new_foreign"))
    )

    print(f"\nNewly caught POIs: {len(newly_caught_pois):,}")

    # Look for UK indicators in newly caught (potential false positives)
    uk_city_pattern = r'(?i)\b(london|manchester|birmingham|liverpool|leeds|glasgow|edinburgh|cardiff|belfast|bristol)\b'
    uk_postcode_fragments = r'\b[A-Z]{1,2}\d{1,2}\s?\d?[A-Z]{0,2}\b'

    potential_fp_uk_city = newly_caught_pois.filter(
        pl.col("address").str.contains(uk_city_pattern, literal=False)
    )
    print(f"\nPotential false positives (UK city names): {len(potential_fp_uk_city):,}")

    if len(potential_fp_uk_city) > 0:
        print("\nSample of potential false positives:")
        for row in potential_fp_uk_city.head(10).select(["name", "address"]).iter_rows(named=True):
            print(f"  {row['name']}: {row['address']}")

    # Show sample of newly caught
    print(f"\n{'='*80}")
    print("SAMPLE: 30 newly caught foreign addresses")
    print(f"{'='*80}")

    newly_sample = newly_caught_pois.select([
        "name", "address", "fsq_category_labels"
    ]).head(30)

    for i, row in enumerate(newly_sample.iter_rows(named=True), 1):
        addr = row["address"] or "(no address)"
        cat = str(row["fsq_category_labels"])[:40] if row["fsq_category_labels"] else "Unknown"
        print(f"\n{i:2d}. {row['name']}")
        print(f"    Address: {addr}")
        print(f"    Category: {cat}")

    # Save results
    import os
    output_dir = "data/POI_files/foreign_address_analysis/"
    os.makedirs(output_dir, exist_ok=True)

    missed_path = f"{output_dir}potential_missed_foreign.parquet"
    potential_missed.write_parquet(missed_path)
    print(f"\n✓ Potential missed: {missed_path}")

    newly_path = f"{output_dir}newly_caught_enhanced.parquet"
    newly_caught_pois.write_parquet(newly_path)
    print(f"✓ Newly caught: {newly_path}")

    csv_path = f"{output_dir}newly_caught_enhanced_top500.csv"
    newly_caught_pois.head(500).select(["fsq_place_id", "name", "address", "postcode"]).write_csv(csv_path)
    print(f"✓ CSV (top 500): {csv_path}")

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Current filter:       {len(already_caught):,} foreign addresses")
    print(f"Enhanced filter:      {len(enhanced_caught):,} foreign addresses")
    print(f"Additional caught:    {newly_caught:,} POIs")
    print(f"False positive risk:  {len(potential_fp_uk_city):,} with UK city names")
    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
