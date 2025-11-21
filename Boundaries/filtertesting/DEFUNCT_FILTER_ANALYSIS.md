# Defunct Retailers Filter Analysis

## Summary

**Dataset**: `data/input_files/uk_foursquare_cc_nov_iceberg.parquet`
**Total Foursquare POIs**: 4,695,350
**Defunct retailers list**: 328 unique brands (after cleaning)

## Key Findings

### Overall Impact
- **POIs Removed**: 10,052 (0.214% of total dataset)
- **Brands Matched**: 155 out of 328 defunct retailers found in dataset
- **Average POIs per brand**: 64.9
- **Median POIs per brand**: 5

### Concentration

The removal is highly concentrated in a few major brands:

| Top N | POIs Removed | % of Total Removed |
|-------|--------------|-------------------|
| Top 1 | 3,349 | 33.3% |
| Top 3 | 5,082 | 50.6% |
| Top 5 | 6,134 | 61.0% |
| Top 10 | 7,351 | 73.1% |
| Top 20 | 8,596 | 85.5% |
| Top 50 | 9,666 | 96.2% |

### Distribution by Size

| Category | # Brands | Total POIs | % of Removed |
|----------|----------|------------|--------------|
| Very Large (500+) | 5 | 6,134 | 61.0% |
| Large (200-499) | 4 | 1,020 | 10.2% |
| Medium (100-199) | 8 | 1,163 | 11.6% |
| Small (50-99) | 11 | 802 | 8.0% |
| Very Small (10-49) | 29 | 622 | 6.2% |
| Minimal (<10) | 98 | 311 | 3.1% |
| **Total** | **155** | **10,052** | **100%** |

### Top 5 Defunct Brands (by POIs removed)

1. **McColl's** - 3,349 POIs (33.3% of all removed)
   - Convenience store chain
   - Dominates the removals by a massive margin

2. **Homebase** - 933 POIs (9.3%)
   - DIY and home improvement retailer

3. **Carphone Warehouse** - 800 POIs (8.0%)
   - Mobile phone retailer

4. **Somerfield** - 533 POIs (5.3%)
   - Supermarket chain

5. **BrightHouse** - 519 POIs (5.2%)
   - Rent-to-own retailer

### Long Tail

- **98 brands** have fewer than 10 POIs each
- **33 brands** have exactly 1 POI removed
- These small brands collectively represent only 3.1% of removals

### Distribution Statistics

| Metric | Value |
|--------|-------|
| Mean | 64.9 POIs |
| Median | 5 POIs |
| 25th percentile | 2 POIs |
| 75th percentile | 23 POIs |
| 90th percentile | 121 POIs |
| 95th percentile | 209 POIs |
| Maximum | 3,349 POIs (McColl's) |

## Notable Brands Removed

### Very Large (500+ POIs)
- McColl's (3,349)
- Homebase (933)
- Carphone Warehouse (800)
- Somerfield (533)
- BrightHouse (519)

### Large (200-499 POIs)
- Comet (303)
- JJB Sports (269)
- Ethel Austin (239)
- 99p Stores (209)

### Medium (100-199 POIs)
- Rosebys (197)
- Debenhams (179)
- Gamestation (164)
- Republic (133)
- Focus DIY (131)
- Woolworths (122)
- Safeway Stores (121)
- Past Times (116)

### Historic Brands with Only 1 POI
- Woolworths (actually 122 total, not in this list)
- C&A
- GUS
- Richard Shops
- Blacklers
- Bon Marché

## Output Files

All outputs saved to: `data/POI_files/defunct_removed/`

### Summary Files
- `complete_defunct_summary.csv` - All 155 matched brands with counts
- `defunct_removed_summary.csv` - Top 20 brands (from initial run)

### GeoParquet Files (Top 20 brands)
Individual spatial files for mapping and analysis:
- McColl_s.geo.parquet (294 KB)
- Homebase.geo.parquet (116 KB)
- Carphone_Warehouse.geo.parquet (153 KB)
- Somerfield.geo.parquet (133 KB)
- BrightHouse.geo.parquet (97 KB)
- Comet.geo.parquet (87 KB)
- JJB_Sports.geo.parquet (84 KB)
- Ethel_Austin.geo.parquet (78 KB)
- 99p_Stores.geo.parquet (69 KB)
- Rosebys.geo.parquet (71 KB)
- Debenhams.geo.parquet (68 KB)
- Gamestation.geo.parquet (64 KB)
- Republic.geo.parquet (59 KB)
- Focus_DIY.geo.parquet (61 KB)
- Woolworths.geo.parquet (60 KB)
- Safeway_Stores.geo.parquet (60 KB)
- Past_Times.geo.parquet (57 KB)
- Unwins.geo.parquet (51 KB)
- MK_One.geo.parquet (52 KB)
- PC_World.geo.parquet (52 KB)

Total size: ~1.8 MB

## Recommendations

1. **Filter is effective**: Removes 10,052 defunct POIs (0.214% of dataset)

2. **McColl's dominance**: The single brand accounts for 1/3 of all removals - verify this is correct as McColl's closed in 2022

3. **Long tail is minimal**: 98 brands with <10 POIs each only account for 3% of removals - could consider excluding brands with very few matches

4. **Quality check**: Review the GeoParquet files spatially to ensure matched POIs are actually defunct locations vs. potential false positives

5. **Integration**: Filter is now integrated into `main.py` and will run automatically on all Foursquare data before retail centre generation

## Filter Configuration

Current settings in `filter_foursquare_quality()`:
```python
filter_defunct=True  # Enable defunct filter
defunct_csv_path="data/input_files/defunct_uk_retailers_wikipedia_full.csv"
save_defunct_removed=True  # Save removed POIs
top_n_brands=10  # Number of brands to save as GeoParquet
```

## Notes

- Matching is case-insensitive and whitespace-normalized
- Bracketed text removed from brand names (e.g., "Woolworths (UK)" → "Woolworths")
- Exact name matching only (no fuzzy matching)
- No date filtering applied - all defunct brands matched regardless of closure date
