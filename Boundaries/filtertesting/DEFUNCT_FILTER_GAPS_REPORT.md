# Defunct Brand Filter - Gap Analysis Report

## Executive Summary

The current defunct brand filter successfully removes **2,159 POIs** from 134 matched brands. However, gap analysis reveals an additional **~623 POIs** (28.9% increase) are being missed due to name normalization issues.

### Current Filter Performance
- **POIs removed**: 2,159
- **Brands matched**: 134 out of 328 (40.9%)
- **Removal rate**: 0.052% of total dataset

### Identified Gaps
- **POIs potentially missed**: ~623
- **Additional removal potential**: +28.9%
- **New total with improvements**: ~2,782 POIs

## Gap Analysis Results

### 1. Spacing/Hyphen Variations ⚠️ **HIGHEST PRIORITY**

**Impact**: 420 POIs missed (67.4% of total gaps)

The filter fails when:
- Hyphens are removed: `"Bon Marché"` → `"bonmarché"` (**344 POIs**)
- Hyphens replaced with spaces: `"Floors-2-Go"` → `"floors 2 go"` (55 POIs)
- Spaces removed entirely: `"Kwik Save"` → `"kwiksave"` (5 POIs)
- Compound words collapsed: `"Past Times"` → `"pasttimes"` (3 POIs)

**Critical Issue**: Bon Marché alone represents 55% of all missed POIs.

| Defunct Brand | POI Name Variant | POIs Missed |
|--------------|------------------|-------------|
| Bon Marché | bonmarché | 344 |
| Floors-2-Go | floors 2 go | 55 |
| Floors-2-Go | floors2go | 3 |
| Kwik Save | kwiksave | 5 |
| Past Times | pasttimes | 3 |
| MK One | mkone | 3 |
| My Local | mylocal | 2 |
| Others | Various | 5 |

### 2. Apostrophe Variations

**Impact**: 78 POIs missed (12.5% of total gaps)

The filter fails when:
- Possessive apostrophes are dropped: `"Jack's"` → `"jacks"` (28 POIs)
- Apostrophes added incorrectly: `"Jacksons"` → `"jackson's"` (9 POIs)
- Possessive forms vary: `"Hawkin's Bazaar"` → `"hawkins bazaar"` (7 POIs)

Top issues:
| Defunct Brand | POI Name Variant | POIs Missed |
|--------------|------------------|-------------|
| Jack's | jacks | 28 |
| Jacksons | jackson's | 9 |
| Hawkin's Bazaar | hawkins bazaar | 7 |
| Fulton's Foods | fultons foods | 6 |
| Gardiner's | gardiners | 6 |
| Others | Various | 22 |

### 3. Suffix Variations

**Impact**: 77 POIs missed (12.4% of total gaps)

The filter fails when common company suffixes are added:
- `"Alldays"` → `"Alldays Stores"` (31 POIs)
- `"Safeway Stores"` → `"Safeway Stores Limited"` (11 POIs)
- `"Focus DIY"` → `"Focus DIY Limited"` (4 POIs)

Common problematic suffixes:
- "Stores" / "Store"
- "Limited" / "Ltd"
- "Group"
- "UK"
- "Supermarket"
- "PLC"

### 4. Partial Matches

**Impact**: 45 POIs missed (7.2% of total gaps)

POIs that contain defunct brand names but have additional text:
- "Past Times Tattoo Parlour" (contains "Past Times")
- "Hintons Country & Garden" (contains "Hintons")
- "Our Price Norfolk Discounts" (contains "Our Price")

**Note**: Partial matching requires careful implementation to avoid false positives (e.g., "Costa Express" should NOT match "Costa Coffee" if Costa is active).

### 5. Ampersand Variations

**Impact**: 3 POIs missed (0.5% of total gaps)

Minor issue with `&` vs `"and"`:
- `"C&A"` → `"c and a"` (1 POI)
- Long Co-operative Society names (2 POIs)

## Recommendations

### Priority 1: Fix Spacing/Hyphen Normalization (420 POIs)

**Recommended approach**: Aggressive whitespace and punctuation normalization

```python
def normalize_aggressive(name: str) -> str:
    """
    Remove all non-alphanumeric characters except spaces,
    then collapse multiple spaces to single space.
    """
    # Remove accents (é → e)
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))

    # Lowercase
    name = name.lower()

    # Remove all punctuation and special chars (keep spaces and alphanumeric)
    name = re.sub(r'[^a-z0-9\s]', '', name)

    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)

    return name.strip()
```

**Expected impact**: +420 POIs removed (+19.5% improvement)

### Priority 2: Fix Apostrophe Handling (78 POIs)

**Recommended approach**: Test both with and without apostrophes

```python
def generate_apostrophe_variants(brand: str) -> list[str]:
    """Generate variations with/without apostrophes."""
    variants = [brand]

    # Remove apostrophes
    if "'" in brand or "'" in brand:
        variants.append(brand.replace("'", "").replace("'", ""))

    # Add possessive 's if ends with 's' or appropriate
    if not "'" in brand:
        if brand.endswith('s'):
            variants.append(brand[:-1] + "'s")
        else:
            variants.append(brand + "'s")

    return variants
```

**Expected impact**: +78 POIs removed (+3.6% improvement)

### Priority 3: Handle Common Suffixes (77 POIs)

**Recommended approach**: Strip common company suffixes before matching

```python
COMPANY_SUFFIXES = [
    r'\s+(ltd|limited|plc|group|stores?|shops?|uk|inc|corp|co\.?)',
    r'\s+\(uk\)',
    r'\s+\(.*?\)',  # Any bracketed text
    r'\s+supermarket'
]

def remove_suffixes(name: str) -> str:
    """Remove common company suffixes."""
    name_clean = name.lower()
    for suffix_pattern in COMPANY_SUFFIXES:
        name_clean = re.sub(suffix_pattern + r'$', '', name_clean)
    return name_clean.strip()
```

**Expected impact**: +77 POIs removed (+3.6% improvement)

### Priority 4: Partial Matching (Optional - 45 POIs)

**Recommended approach**: Word-boundary matching with caution

```python
def contains_brand_as_word(poi_name: str, brand: str) -> bool:
    """Check if POI name contains brand as complete word(s)."""
    poi_norm = normalize_aggressive(poi_name)
    brand_norm = normalize_aggressive(brand)

    # Use word boundaries to avoid "Costa" matching "Costa Coffee"
    pattern = r'\b' + re.escape(brand_norm) + r'\b'
    return bool(re.search(pattern, poi_norm))
```

**Caution**: Only apply to high-confidence defunct brands to avoid false positives.

**Expected impact**: +45 POIs removed (+2.1% improvement)

### Priority 5: Ampersand Normalization (Low Priority - 3 POIs)

**Recommended approach**: Normalize ampersands to "and"

```python
name = re.sub(r'\s*&\s*', ' and ', name)
```

**Expected impact**: +3 POIs removed (+0.1% improvement)

## Implementation Strategy

### Option A: Enhanced Exact Matching (Recommended)

**Pros**:
- Maintains conservative approach (low false positive risk)
- Easy to implement incrementally
- Clear audit trail

**Approach**:
1. Apply aggressive normalization to both defunct list and POI names
2. Handle apostrophes, spacing, hyphens, accents
3. Strip common suffixes
4. Keep exact matching logic

**Expected improvement**: +575 POIs (~26.6% increase)

### Option B: Hybrid Exact + Partial Matching

**Pros**:
- Maximum coverage (+623 POIs)
- Can be tuned for precision

**Cons**:
- Higher false positive risk
- Requires more careful validation

**Approach**:
- Use Option A for all brands
- Add partial matching only for top 20-30 defunct brands (manually curated)
- Validate partial matches with category filters (e.g., "Past Times Tattoo Parlour" is NOT retail)

**Expected improvement**: +623 POIs (~28.9% increase)

## Proposed Updated Filter Function

```python
import unicodedata
import re

def normalize_for_matching(name: str) -> str:
    """
    Aggressive normalization for defunct brand matching.
    Handles: accents, apostrophes, hyphens, spaces, case, suffixes.
    """
    # Handle None/NaN
    if not isinstance(name, str) or not name:
        return ""

    # Remove accents (Bon Marché → Bon Marche)
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))

    # Lowercase
    name = name.lower()

    # Strip company suffixes BEFORE removing punctuation
    suffixes = [
        r'\s+(ltd|limited|plc|group|stores?|shops?|uk|inc|corp|co\.?)',
        r'\s+\(uk\)',
        r'\s+\(.*?\)',
        r'\s+supermarket'
    ]
    for suffix in suffixes:
        name = re.sub(suffix + r'$', '', name)

    # Remove ALL punctuation (apostrophes, hyphens, etc.)
    name = re.sub(r'[^a-z0-9\s]', '', name)

    # Collapse spaces
    name = re.sub(r'\s+', ' ', name)

    return name.strip()


def filter_defunct_retailers_enhanced(
    foursquare: pl.DataFrame,
    defunct_csv_path: str,
    save_removed: bool = True,
    output_dir: str = "data/POI_files/defunct_removed",
    top_n_brands: int = 10
) -> pl.DataFrame:
    """
    Enhanced defunct filter with better name normalization.
    Expected to catch ~28% more defunct POIs than current version.
    """

    # Load defunct brands
    defunct_df = pl.read_csv(defunct_csv_path)
    defunct_df = defunct_df.unique(subset=["Brand"])

    # Normalize defunct brand names
    defunct_normalized = defunct_df.with_columns(
        brand_key=pl.col("Brand").map_elements(
            normalize_for_matching,
            return_dtype=pl.String
        )
    )

    # Normalize POI names
    fs_normalized = foursquare.with_columns(
        brand_key=pl.col("name").map_elements(
            normalize_for_matching,
            return_dtype=pl.String
        )
    )

    # Match on normalized keys
    removed = fs_normalized.join(
        defunct_normalized.select("brand_key").unique(),
        on="brand_key",
        how="inner"
    )

    # Keep non-matches
    filtered = fs_normalized.join(
        defunct_normalized.select("brand_key").unique(),
        on="brand_key",
        how="anti"
    )

    # Drop temporary key
    filtered = filtered.drop("brand_key")

    # ... rest of save logic ...

    return filtered
```

## Validation Plan

1. **Before/After Comparison**
   - Run current filter → save removed POIs
   - Run enhanced filter → save removed POIs
   - Compare the delta to validate new removals are legitimate

2. **Manual Spot Checks**
   - Review samples from each gap category
   - Verify they are truly defunct (cross-check with closure dates)
   - Check for false positives

3. **Geographic Distribution**
   - Plot removed POIs on map
   - Check if spatial distribution makes sense (e.g., Bon Marché was UK-wide)

4. **Category Validation**
   - Ensure removed POIs are in retail-relevant categories
   - Flag any removals from unexpected categories

## Risk Assessment

### Low Risk (Implement immediately)
- Spacing/hyphen normalization
- Apostrophe handling
- Suffix stripping
- Ampersand normalization

**Risk**: Very low false positive rate, as exact matching still applies after normalization.

### Medium Risk (Implement with validation)
- Partial matching for top N brands

**Risk**: Moderate false positive rate if brand name is common word.

**Mitigation**:
- Curate list of brands safe for partial matching
- Exclude common words ("Jacksons" → don't partial match)
- Add category filters (tattoo parlor ≠ retail)

## Conclusion

The current defunct filter is effective but misses **~623 POIs (~28.9% additional coverage)** due to name normalization issues. The primary issue is **spacing/hyphen handling** (420 POIs, especially Bon Marché with 344 POIs).

**Recommended immediate action**:
1. Implement enhanced normalization (Priority 1-3)
2. Expected improvement: +575 to +623 POIs removed
3. Run validation tests on sample data
4. Deploy updated filter

**File locations**:
- Current filter: `src/retail/foursquare_qualityfilter.py:23`
- Gap analysis results: `data/POI_files/defunct_gaps_analysis/*.csv`
- Test script: `test_defunct_gaps_fast.py`
