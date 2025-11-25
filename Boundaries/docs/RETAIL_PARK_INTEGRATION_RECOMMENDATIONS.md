# Retail Park Integration: Implementation Recommendations

**Date:** 2025-11-24
**Status:** Experimental - DO NOT integrate into main.py yet

---

## Overview

This document provides recommendations for integrating separately-detected retail parks with the main retail centre workflow. The goal is to distinguish bigbox retail parks from traditional high street/town centre retail while handling edge cases where they overlap.

---

## Scripts Created

### 1. `src/retail/detect_retail_parks.py`
**Purpose:** Detect retail parks based on bigbox brand presence

**Key Features:**
- Filters Foursquare POIs by retail park brand names (B&M, Currys, B&Q, etc.)
- Spatially joins with OSM retail landuse polygons
- Computes ratio of bigbox POIs to total POIs
- Identifies retail parks where ratio ≥ threshold (default: 2%)

**Usage:**
```bash
python src/retail/detect_retail_parks.py \
    --retail_landuse data/input_files/retail_landuse.parquet \
    --foursquare data/input_files/uk_foursquare_cc_aug_retailfilt_geo.parquet \
    --brands data/input_files/bl_retail_parks_brands_deduped.csv \
    --min_ratio 0.02 \
    --output data/output_files/retail_parks_detected.parquet
```

### 2. `src/retail/integrate_retail_parks.py`
**Purpose:** Integrate detected retail parks with existing retail centre networks

**Key Features:**
- Analyzes overlap between parks (polygons) and centres (H3 cells)
- Handles three overlap scenarios:
  1. **No overlap:** Add park as new network
  2. **Single network overlap:** Split or merge based on remainder size
  3. **Multiple network overlap:** Flag for manual review
- Configurable minimum remainder cell threshold

**Usage:**
```bash
python src/retail/integrate_retail_parks.py \
    --centres data/output_files/.../3_afterfill.parquet \
    --parks data/output_files/retail_parks_detected.parquet \
    --output_dir data/output_files/retail_park_integration_test \
    --min_remainder 3
```

---

## Implementation Approaches

### Approach 1: Post-Processing (Recommended for Testing)
**When:** After main workflow completes (after `3_afterfill.parquet` or `4_finalcentres.parquet`)

**Pros:**
- Minimal disruption to existing workflow
- Easy to test and iterate
- Can compare before/after results
- Can be toggled on/off easily

**Cons:**
- Two-pass approach (less efficient)
- Parks don't benefit from network merging/filling logic
- May create discontinuities in network numbering

**Implementation:**
```python
# In main.py or separate script
if ENABLE_RETAIL_PARK_INTEGRATION:
    from retail import detect_retail_parks, integrate_retail_parks

    # Detect parks from OSM landuse
    retail_parks = detect_retail_parks.identify_retail_parks(...)

    # Integrate with existing centres
    integrated_cells, report = integrate_retail_parks.integrate_retail_parks(
        retail_centres_cells_path=f"{save_folder}/3_afterfill.parquet",
        retail_parks_path="data/output_files/retail_parks_detected.parquet",
        output_dir=f"{save_folder}/retail_park_integration",
        min_remainder_cells=3
    )

    # Save as alternative output
    integrated_cells.to_parquet(f"{save_folder}/3_afterfill_with_parks.parquet")
```

### Approach 2: Early Integration (More Complex)
**When:** Before network creation (integrate park POIs into initial cell filtering)

**Pros:**
- Parks benefit from full workflow (merging, filling, Leiden clustering)
- Single-pass processing
- More coherent network numbering

**Cons:**
- Requires modifying core workflow
- Harder to validate/compare
- May interfere with existing parameter tuning

**Implementation:**
```python
# In generate_networks.py or main.py
# After POI filtering but before network creation
if ENABLE_RETAIL_PARK_DETECTION:
    # Tag POIs as retail park brands
    foursquare = tag_retail_park_pois(foursquare)

    # In network creation, apply different rules for park-dominated cells
    # e.g., lower min_retail_in_cell for park cells
```

### Approach 3: Parallel Workflow (Hybrid)
**When:** Run retail park detection in parallel with main workflow, merge at final stage

**Pros:**
- Independent parameter tuning for parks vs centres
- Can use different thresholds/rules
- Flexibility in integration strategy

**Cons:**
- Most complex implementation
- Harder to debug
- Requires careful handling of overlaps

---

## Key Design Decisions

### 1. Minimum Remainder Cell Threshold
**Problem:** When splitting overlapping centres, what's the minimum size for a remainder to be kept separate?

**Options:**
- **Too low (1-2 cells):** Creates tiny fragments attached to parks
- **Too high (5+ cells):** May prevent legitimate splits
- **Recommended: 3 cells** - Balances avoiding fragments vs preserving small centres

**Rationale:**
- 3 H3 cells ≈ 600-800m² area
- Enough to contain 2-3 small shops
- Avoids single-cell artifacts

### 2. Overlap Detection Method
**Current:** Convert park polygons to H3 cells, compare with centre cells

**Alternatives:**
- **Polygon-to-polygon overlap:** More accurate but computationally expensive
- **Centroid containment:** Fast but misses partial overlaps
- **Buffer-based:** Adds complexity without clear benefit

**Recommendation:** Stick with H3 cell comparison for consistency with main workflow

### 3. Handling Multi-Network Overlaps
**Problem:** A retail park polygon may overlap multiple networks (e.g., park spans two adjacent centres)

**Current approach:** Flag for manual review

**Better approach options:**
- **Union networks first:** Merge overlapping networks before splitting
- **Assign to majority:** Park goes to network with most overlap
- **Split park:** Divide park cells among networks (complex)

**Recommendation:** Start with flagging, analyze examples, then implement rule-based logic

---

## Edge Cases to Handle

### Case 1: Park Fully Contains Network
**Scenario:** Small traditional centre completely within retail park polygon

**Current:** Mark entire network as retail park

**Concern:** May lose distinction if centre has genuine high street character

**Suggested refinement:** Check bigbox ratio of network cells - if low, keep as traditional centre

### Case 2: Tiny Remainder Cells
**Scenario:** After removing park cells, 1-2 cells remain from original centre

**Current:** Merge remainder back with park (keep_together)

**Concern:** May inflate park boundaries

**Alternative:** Discard remainder cells entirely (mark as noise)

### Case 3: Park Overlaps Town Centre
**Scenario:** Retail park shares cells with established high street

**Current:** Will attempt to split

**Concern:** May inappropriately fragment coherent centres

**Suggested refinement:** Add heuristic to check if park cells are at periphery - if yes, split; if mixed throughout, keep together

### Case 4: Multiple Small Parks in Same Network
**Scenario:** Network contains several small retail park clusters

**Current:** Not explicitly handled

**Suggestion:** Run retail park detection on network subgraphs after Leiden clustering

---

## Recommended Testing Workflow

### Phase 1: Detection Only
1. Run `detect_retail_parks.py` on full UK dataset
2. Validate results manually for known locations:
   - Lakeside Retail Park
   - Thurrock Retail Park
   - Fort Kinnaird (Edinburgh)
   - Cribbs Causeway (Bristol)
3. Test different ratio thresholds (1%, 2%, 5%)
4. Compare with notebook results

### Phase 2: Overlap Analysis
1. Run integration script with `--min_remainder` variations (2, 3, 5, 10)
2. Analyze overlap types:
   - What % have no overlap?
   - What % single network?
   - What % multiple networks?
3. Review flagged multi-network cases
4. Refine splitting logic based on examples

### Phase 3: Full Integration
1. Run on test parameter set from main.py
2. Compare metrics:
   - Network count before/after
   - Total POIs before/after
   - Network size distribution
3. Validate specific locations (visual inspection in QGIS)
4. Check for pathological cases (e.g., 1000+ small parks created)

### Phase 4: Production Integration
1. Add configuration to main.py (similar to landuse filter)
2. Run on full parameter sweep
3. Document in CLAUDE.md
4. Update output file naming convention

---

## Configuration Recommendations

When integrating into main.py:

```python
# ========================================
# RETAIL PARK INTEGRATION CONFIGURATION
# ========================================
# Enable/disable retail park detection and integration
ENABLE_RETAIL_PARK_INTEGRATION = False  # Start disabled

# Detection parameters
RETAIL_PARK_MIN_RATIO = 0.02  # 2% bigbox POI ratio
RETAIL_PARK_MIN_MATCHED_POIS = 1

# Integration parameters
RETAIL_PARK_MIN_REMAINDER_CELLS = 3  # Min cells to keep remainder separate
RETAIL_PARK_PREDICATE = "within"  # or "intersects"

# Paths
RETAIL_LANDUSE_PATH = "data/input_files/retail_landuse.parquet"
RETAIL_PARK_BRANDS_PATH = "data/input_files/bl_retail_parks_brands_deduped.csv"
# ========================================
```

---

## Outstanding Questions

1. **Should retail parks go through Leiden clustering?**
   - Pro: May identify sub-clusters within large parks
   - Con: Parks are inherently single-purpose, clustering may be artificial

2. **How to handle retail parks in final centre classification?**
   - Add `centre_type` field: "traditional", "retail_park", "mixed"?
   - Separate output files?
   - Single file with flag column?

3. **Should parks use different POI thresholds?**
   - Current workflow: min 10 POIs per network
   - Parks may be valid with fewer POIs (e.g., B&Q + Currys = 2 POIs but legit park)

4. **How to update Local Authority assignments?**
   - Parks may cross LA boundaries more than traditional centres
   - Use centroid, majority area, or list all touching LAs?

---

## Next Steps

1. **Immediate:** Test `detect_retail_parks.py` on real data, validate against notebook
2. **Short-term:** Run integration analysis to understand overlap patterns
3. **Medium-term:** Refine splitting logic based on edge cases
4. **Long-term:** Integrate into main.py with full parameter testing

---

## References

- Notebook: `notebooks/retailparkproto.ipynb`
- Landuse filter implementation: `src/retail/landuse_filter.py`
- Network merging logic: `src/retail/network_merger.py`
- Brands list: `data/input_files/bl_retail_parks_brands_deduped.csv` (29 classic brands)

---

## Summary

The retail park integration approach is feasible but requires careful handling of edge cases. The recommended path is:

1. **Start with post-processing approach** (Approach 1) for maximum flexibility
2. **Test thoroughly** with Phase 1-3 workflow above
3. **Refine splitting logic** based on real-world overlap patterns
4. **Consider parallel workflow** (Approach 3) if post-processing proves insufficient
5. **Only integrate into main.py** after validation on full dataset

**Key success metrics:**
- Retail parks correctly identified (visual validation)
- No fragmentation of coherent traditional centres
- Minimal creation of tiny remainder cells
- Clear distinction between park and non-park centres in outputs
