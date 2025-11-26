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

## Implementation Approaches - Testing Plan

### **WORKFLOW 1: Pre-Exclusion (Parks First)**
**When:** Before Stage 1 (POI filtering) - exclude retail park cells from retail centre detection

**Implementation:**
1. Run `detect_retail_parks.py` to identify retail park polygons (OSM landuse + bigbox brands)
2. Convert retail park polygons to H3 cells (resolution 11)
3. Mark these cells as "retail_park" type
4. In main workflow Stage 1, filter OUT any POIs that fall in retail park cells
5. Run stages 1-6 of retail centre pipeline on remaining POIs
6. At Stage 6 finalization, add retail parks back as separate networks with `type='retail_park'`

**Pros:**
- Clean separation: retail parks and retail centres are mutually exclusive
- Prevents parks from fragmenting traditional centres during network creation
- Retail parks are "protected" - won't be merged/split by algorithm
- Simple to reason about: "if it's a park, it's not a centre"

**Cons:**
- Parks miss out on filling logic (may have gaps where single cells could connect clusters)
- Doesn't handle hybrid areas well (e.g., retail park adjacent to high street)
- May create artificial boundaries where park edges blend into centres
- Removes POIs from centre detection entirely - reduces POI counts in nearby centres

**Key Parameters:**
- `min_ratio`: 0.02 (2% bigbox POIs) - determines what qualifies as park
- `retail_park_cells_exclusion`: boolean flag in main.py

**Testing Questions:**
- How many POIs are excluded from retail centre detection?
- Do we create "donut holes" where parks sit inside what should be larger centres?
- How many parks have <10 POIs (wouldn't qualify as centres anyway)?

---

### **WORKFLOW 2: Post-Subtraction (Centres First, Parks Carved Out)**
**When:** After Stage 6 (final centres) - subtract retail park cells and validate remainders

**Implementation:**
1. Run main workflow Stages 1-6 normally (ignore retail parks)
2. Generate `4_finalcentres.parquet` as usual
3. Run `detect_retail_parks.py` to identify retail park polygons
4. Convert parks to H3 cells (resolution 11)
5. For each retail centre:
   - Identify cells that overlap with retail park cells
   - Remove overlapping cells from the centre
   - Count remaining cells and POIs
   - **If remainder >= threshold**: Keep centre (now smaller) + create separate retail park
   - **If remainder < threshold**: Delete entire centre, convert to retail park
6. Output two files: `4_finalcentres_no_parks.parquet` and `retail_parks_carved.parquet`

**Pros:**
- Retail centres benefit from full workflow (merging, filling, Leiden)
- Handles overlap gracefully - only removes what needs removing
- Preserves traditional centres that happen to be near parks
- More flexible: can tune thresholds for "minimum viable centre after subtraction"

**Cons:**
- Two-pass processing (less efficient)
- May create fragmented centres if parks punch holes in the middle
- Threshold choice is critical - too high removes many centres, too low keeps tiny fragments
- More complex logic to handle edge cases (e.g., park spans multiple centres)

**Key Parameters:**
- `min_remainder_cells`: 3-10 cells (minimum cells for remainder to survive)
- `min_remainder_pois`: 10 POIs (minimum POIs for remainder to survive)
- `allow_park_holes`: boolean - if False, discard centres that become disconnected

**Testing Questions:**
- How many centres are deleted entirely vs. just shrunk?
- What % of centres have partial overlap with parks?
- Are there centres that become fragmented (disconnected components after subtraction)?

---

### **WORKFLOW 3: Hybrid Classification (Dual Labels)**
**When:** After Stage 6 - classify centres/parks based on cell composition

**Implementation:**
1. Run main workflow Stages 1-6 normally
2. Run `detect_retail_parks.py` to identify retail park cells
3. For each retail centre:
   - Count cells: `total_cells`, `park_cells`, `non_park_cells`
   - Calculate `park_ratio = park_cells / total_cells`
   - Classify:
     - `park_ratio >= 0.8`: Label as "retail_park"
     - `park_ratio <= 0.2`: Label as "traditional_centre"
     - `0.2 < park_ratio < 0.8`: Label as "mixed"
4. Output single file with `centre_type` column

**Pros:**
- No geometric splitting - preserves network integrity
- Acknowledges reality: many centres are mixed-use
- Simple to implement and explain
- Allows filtering by type in downstream analysis

**Cons:**
- Doesn't create separate park boundaries
- "Mixed" category may be too broad
- Doesn't reduce overlap - parks and centres still share cells

**Use Case:** Best for analysis/classification rather than generating distinct boundaries

---

### **WORKFLOW 4: Staged Exclusion (Exclude from Filling Only)**
**When:** After Stage 3 (initial networks) - prevent parks from benefiting from filling

**Implementation:**
1. Run Stages 1-3 normally (POI filtering, aggregation, initial networks)
2. Identify retail park cells (same as Workflow 1)
3. Run Stage 4 (network merging) normally
4. In Stage 4 filling step: Mark park cells as "ineligible for fill"
   - This prevents non-park cells from being added to networks if they're adjacent to park cells
5. Continue Stages 5-6 normally

**Pros:**
- Prevents parks from "spreading" via filling algorithm
- Parks still benefit from initial network creation and merging
- Less drastic than full exclusion

**Cons:**
- Complex to implement (requires modifying filling logic)
- May create odd boundaries where parks abruptly stop expanding
- Doesn't handle overlap - parks and centres can still share cells

**Use Case:** If testing shows parks are "stealing" cells during filling

---

### **WORKFLOW 5: Separate Pipelines + Conflict Resolution**
**When:** Run two independent pipelines, resolve conflicts at end

**Implementation:**
1. **Pipeline A**: Run main workflow Stages 1-6 normally → retail centres
2. **Pipeline B**: Run retail park detection + H3 conversion → retail parks
3. **Conflict resolution**:
   - Identify cells that appear in both outputs
   - For each conflict cell, apply rules:
     - **Priority to parks**: If cell has bigbox POI, assign to park
     - **Priority to density**: If cell has >X total POIs, assign to centre
     - **Priority to network size**: Assign to larger network
     - **Majority rule**: Assign based on surrounding cells
4. Output: `retail_centres_resolved.parquet` and `retail_parks_resolved.parquet`

**Pros:**
- Maximum flexibility - each pipeline optimized independently
- Can test different conflict resolution strategies
- Preserves original outputs for comparison

**Cons:**
- Most complex implementation
- Requires careful conflict resolution logic
- May still leave ambiguous cases

**Use Case:** If you want to experiment with multiple conflict resolution strategies

---

## Recommendation: Start with Workflows 1 & 2

**Suggested Testing Order:**
1. **Workflow 2 (Post-Subtraction)** - Test first because:
   - Easiest to implement (no changes to main workflow)
   - Can compare before/after visually
   - Reveals how much overlap actually exists

2. **Workflow 1 (Pre-Exclusion)** - Test second because:
   - Shows impact of excluding parks upfront
   - Quantifies POI loss from exclusion
   - Provides clean alternative if overlap is problematic

3. **Compare results** side-by-side:
   - How many retail centres survive in each approach?
   - How different are the boundaries?
   - Which better matches manual validation?

4. **Consider Workflow 3 (Hybrid)** if:
   - Both 1 & 2 produce unsatisfying results
   - Overlap is extensive and splitting seems arbitrary
   - Stakeholders prefer classification over hard boundaries





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
# Detection parameters
RETAIL_PARK_MIN_RATIO = 0.05  # 2% bigbox POI ratio
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

## Key Files
- `detect_retail_parks.py`
- Network merging logic: `src/retail/network_merger.py`
- Brands list: `data/input_files/bl_retail_parks_brands_deduped.csv` (29 classic brands)

---
