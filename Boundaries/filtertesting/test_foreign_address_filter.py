#!/usr/bin/env python3
"""
Foreign address filter - removes POIs with clearly non-UK addresses.

Detection criteria:
- Address contains foreign state/province codes (US, CA, AU)
- OR foreign country names
- OR foreign postal code patterns
- AND no UK postcode present (safeguard)
- EXCEPT Northern Ireland mentions (safe pass)
"""

import polars as pl
import sys
sys.path.insert(0, 'src')

from retail.retailfilter import filter_foursquare_invmethod
from retail.foursquare_qualityfilter import filter_defunct_retailers, filter_by_uk_boundary

# ===== FOREIGN ADDRESS PATTERNS =====

# US states
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

# Canada
CA_PROV_CODES = ["AB","BC","MB","NB","NL","NS","NT","NU","ON","PE","QC","SK","YT"]
CA_PROV_NAMES = [
    "Alberta","British Columbia","Manitoba","New Brunswick","Newfoundland and Labrador","Nova Scotia",
    "Northwest Territories","Nunavut","Ontario","Prince Edward Island","Quebec","Saskatchewan","Yukon"
]

# Australia
AU_STATE_CODES = ["NSW","VIC","QLD","SA","WA","TAS","ACT","NT"]
AU_STATE_NAMES = [
    "New South Wales","Victoria","Queensland","South Australia","Western Australia","Tasmania",
    "Australian Capital Territory","Northern Territory"
]

# Country mentions (explicit foreign countries)
COUNTRY_WORDS = [
    r"United\s+States", r"U\.?S\.?A\.?", r"Canada", r"France", r"Germany", r"Deutschland",
    r"Spain", r"España", r"Italy", r"Italia", r"Australia", r"Ireland",
    r"Republic\s+of\s+Ireland", r"Netherlands", r"Nederland", r"Belgium", r"Belgique",
    r"Luxembourg", r"Switzerland", r"Suisse", r"Sweden", r"Norway", r"Denmark",
    r"Finland", r"Austria", r"Portugal", r"Poland", r"Czech", r"Hungary", r"Greece"
]

# Distinctive postal code formats (end of address)
PAT_US_ZIP_END = r"\d{5}(?:-\d{4})?$"                                        # 12345 or 12345-6789
PAT_CA_PC_END  = r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d$"  # K1A 0B1
PAT_NL_PC_END  = r"\d{4}\s?[A-Z]{2}$"                                        # 1234 AB
PAT_IE_EIR_END = r"[A-Z]\d{2}\s?[A-Z0-9]{4}$"                                # D02 XY45

# Enhanced: 5-digit patterns anywhere (mid-address ZIPs, street numbers)
PAT_FIVE_DIGITS = r'\b\d{5}\b'                                               # 12345 anywhere
PAT_US_ADDRESS_CONTEXT = r'(?i)\b(suite|highway|avenue|boulevard|drive|street|road|lane|court|circle|way|dr|rd|ave|blvd|st|ln|hwy)\b'

# Build regex patterns
PAT_US_STATE_TAIL      = rf"(?:,?\s*)\b({'|'.join(US_STATE_CODES)})\b(?:\s*{PAT_US_ZIP_END})?$"
PAT_US_STATE_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(US_STATE_NAMES)})\b(?:\s*{PAT_US_ZIP_END})?$"
PAT_US_STATE_ABBR      = rf"\b({'|'.join(US_STATE_CODES)})\b"  # State code anywhere

PAT_CA_PROV_TAIL       = rf"(?:,?\s*)\b({'|'.join(CA_PROV_CODES)})\b(?:\s*{PAT_CA_PC_END})?$"
PAT_CA_PROV_NAME_TAIL  = rf"(?i)(?:,?\s*)\b({'|'.join(CA_PROV_NAMES)})\b(?:\s*{PAT_CA_PC_END})?$"

PAT_AU_STATE_TAIL      = rf"(?:,?\s*)\b({'|'.join(AU_STATE_CODES)})\b(?:\s*\d{{4}})?$"
PAT_AU_STATE_NAME_TAIL = rf"(?i)(?:,?\s*)\b({'|'.join(AU_STATE_NAMES)})\b(?:\s*\d{{4}})?$"

PAT_COUNTRY_WORDS      = rf"(?i)\b({'|'.join(COUNTRY_WORDS)})\b"

# Safe passes for UK place names that match foreign patterns
SAFE_PASSES = [
    r"(?i)\bNorthern\s+Ireland\b",      # Northern Ireland (country mention)
    r"(?i)\bDenmark\s+Hill\b",          # South London street
    r"(?i)\bDenmark\s+St(?:reet)?\b",   # Soho street
    r"(?i)\bCanada\s+Place\b",          # Canary Wharf
    r"(?i)\bCanada\s+Water\b",          # South London area
    r"(?i)\bNew\s+England\b",           # Peterborough area
]
SAFE_PASS_PATTERN = "|".join(f"({p})" for p in SAFE_PASSES)


def main():
    print("="*80)
    print("FOREIGN ADDRESS FILTER TEST (ENHANCED)")
    print("="*80)
    print("\nDetection criteria:")
    print("  - Foreign state/province codes (US, CA, AU)")
    print("  - OR foreign country names")
    print("  - OR foreign postal code patterns")
    print("  - OR 5-digit patterns + US address keywords (Suite, Highway, Road, etc.)")
    print("  - AND no UK postcode")
    print("  - EXCEPT Northern Ireland and UK place names (safe pass)")

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

    # Check address and postcode availability
    print(f"\n[2/4] Data completeness:")
    has_address = foursquare_filt.filter(pl.col("address").is_not_null())
    has_postcode = foursquare_filt.filter(pl.col("postcode").is_not_null())
    print(f"  POIs with address:  {len(has_address):,} ({100*len(has_address)/len(foursquare_filt):.1f}%)")
    print(f"  POIs with postcode: {len(has_postcode):,} ({100*len(has_postcode)/len(foursquare_filt):.1f}%)")

    # Apply foreign address detection
    print(f"\n[3/4] Detecting foreign addresses...")

    # Build foreign indicator expression (only for POIs with addresses)
    has_address = pl.col("address").is_not_null()
    has_uk_postcode = pl.col("postcode").is_not_null()

    foreign_indicator = has_address & (
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
        # Enhanced: 5-digit patterns with US address context
        | (
            pl.col("address").str.contains(PAT_FIVE_DIGITS, literal=False) &
            (
                pl.col("address").str.contains(PAT_US_ADDRESS_CONTEXT, literal=False) |
                pl.col("address").str.contains(PAT_US_STATE_ABBR, literal=False) |
                pl.col("address").str.contains(r'(?i)(USA|United States|America)', literal=False)
            )
        )
    ) & (~pl.col("address").str.contains(SAFE_PASS_PATTERN, literal=False))

    # Final filter: foreign indicator AND no UK postcode
    to_remove = foursquare_filt.filter(foreign_indicator & ~has_uk_postcode)

    print(f"  Foreign addresses detected: {len(to_remove):,}")
    print(f"  Percentage: {100 * len(to_remove) / len(foursquare_filt):.3f}%")

    # Create filtered dataset
    filtered = foursquare_filt.filter(~(foreign_indicator & ~has_uk_postcode))
    print(f"  POIs remaining: {len(filtered):,}")

    # Analyze what was caught
    print(f"\n[4/4] Analysis of removed POIs:")

    # Breakdown by detection type
    breakdown = to_remove.with_columns([
        pl.col("address").str.contains(PAT_COUNTRY_WORDS, literal=False).alias("country_name"),
        pl.col("address").str.contains(PAT_US_STATE_TAIL, literal=False).alias("us_state_code"),
        pl.col("address").str.contains(PAT_US_STATE_NAME_TAIL, literal=False).alias("us_state_name"),
        pl.col("address").str.contains(PAT_CA_PROV_TAIL, literal=False).alias("ca_prov_code"),
        pl.col("address").str.contains(PAT_CA_PROV_NAME_TAIL, literal=False).alias("ca_prov_name"),
        pl.col("address").str.contains(PAT_AU_STATE_TAIL, literal=False).alias("au_state_code"),
        pl.col("address").str.contains(PAT_AU_STATE_NAME_TAIL, literal=False).alias("au_state_name"),
        pl.col("address").str.contains(PAT_CA_PC_END, literal=False).alias("ca_postal"),
        pl.col("address").str.contains(PAT_NL_PC_END, literal=False).alias("nl_postal"),
        pl.col("address").str.contains(PAT_IE_EIR_END, literal=False).alias("ie_postal"),
        (
            pl.col("address").str.contains(PAT_FIVE_DIGITS, literal=False) &
            (
                pl.col("address").str.contains(PAT_US_ADDRESS_CONTEXT, literal=False) |
                pl.col("address").str.contains(PAT_US_STATE_ABBR, literal=False) |
                pl.col("address").str.contains(r'(?i)(USA|United States|America)', literal=False)
            )
        ).alias("us_5digit_enhanced"),
    ])

    print("\nDetection breakdown:")
    print(f"  Country name mention:     {breakdown.filter(pl.col('country_name')).height:,}")
    print(f"  US state code:            {breakdown.filter(pl.col('us_state_code')).height:,}")
    print(f"  US state name:            {breakdown.filter(pl.col('us_state_name')).height:,}")
    print(f"  Canadian province code:   {breakdown.filter(pl.col('ca_prov_code')).height:,}")
    print(f"  Canadian province name:   {breakdown.filter(pl.col('ca_prov_name')).height:,}")
    print(f"  Australian state code:    {breakdown.filter(pl.col('au_state_code')).height:,}")
    print(f"  Australian state name:    {breakdown.filter(pl.col('au_state_name')).height:,}")
    print(f"  Canadian postal pattern:  {breakdown.filter(pl.col('ca_postal')).height:,}")
    print(f"  Dutch postal pattern:     {breakdown.filter(pl.col('nl_postal')).height:,}")
    print(f"  Irish postal pattern:     {breakdown.filter(pl.col('ie_postal')).height:,}")
    print(f"  5-digit + US context:     {breakdown.filter(pl.col('us_5digit_enhanced')).height:,}")

    # Category breakdown
    print("\nTop 15 categories:")
    cat_breakdown = (
        to_remove
        .group_by("fsq_category_labels")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
        .head(15)
    )
    for row in cat_breakdown.iter_rows(named=True):
        label = str(row["fsq_category_labels"])[:60] if row["fsq_category_labels"] else "Unknown"
        print(f"  {row['count']:4d} - {label}")

    # Show examples
    print(f"\n{'='*80}")
    print("EXAMPLES OF FOREIGN ADDRESSES (sample of 40)")
    print(f"{'='*80}")

    sample = to_remove.select(["name", "address", "fsq_category_labels"]).head(40)
    for i, row in enumerate(sample.iter_rows(named=True), 1):
        addr = row["address"] or "(no address)"
        cat = str(row["fsq_category_labels"])[:40] if row["fsq_category_labels"] else "Unknown"
        print(f"\n{i:2d}. {row['name']}")
        print(f"    Address: {addr}")
        print(f"    Category: {cat}")

    # Save results
    print(f"\n{'='*80}")
    print("SAVING RESULTS")
    print(f"{'='*80}")

    import os
    output_dir = "data/POI_files/foreign_address_removal/"
    os.makedirs(output_dir, exist_ok=True)

    # Save removed
    remove_path = f"{output_dir}foreign_addresses_removed.parquet"
    to_remove.write_parquet(remove_path)
    print(f"\n✓ Foreign addresses: {remove_path}")

    # Save CSV sample
    csv_path = f"{output_dir}foreign_addresses_removed_top500.csv"
    to_remove.head(500).select(["fsq_place_id", "name", "address", "postcode"]).write_csv(csv_path)
    print(f"✓ CSV (top 500): {csv_path}")

    # Save filtered dataset
    filtered_path = f"{output_dir}foursquare_foreign_filtered.parquet"
    filtered.write_parquet(filtered_path)
    print(f"✓ Filtered dataset: {filtered_path}")

    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Original POIs:          {len(foursquare_filt):,}")
    print(f"Foreign addresses:      {len(to_remove):,}")
    print(f"Final POIs:             {len(filtered):,}")
    print(f"Removal rate:           {100 * len(to_remove) / len(foursquare_filt):.3f}%")

    print(f"\n{'='*80}")
    print("COMPLETE!")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
