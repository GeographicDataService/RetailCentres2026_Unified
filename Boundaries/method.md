# Retail Centre Boundary Creation
Owen Goodwin - Geographic Data Service
Date: December 2025
---

## Overview

This document describes the algorithmic methodology for generating retail centre boundaries for the UK from open source point-of-interest (POI) and land use data. The pipeline implements a series of data cleaning, filtering, spatial aggregation, network construction, community detection, and post-processing steps to identify contiguous retail agglomerations and delineate their boundaries.


---
## Based On
This methodology extends and refines the core approach detailed in:
https://www.nature.com/articles/s41597-022-01556-3
https://github.com/GeographicDataService/Retail-Centre-Boundaries

## Data Sources

### Core Input Data
- **POI Data**: Foursquare Places API POI
- **Land Use**: OpenStreetMap land use polygons (retail, commercial, industrial)

---

---

## Pipeline Structure

```
POI Data Preparation (Stages 1-2)
├─ Stage 1: POI Quality Filtering
└─ Stage 2: Retail Category Filtering
         │
         ├─────────────────────────────────────┬──────────────────────────────────────┐
         │                                     │                                      │
         ▼                                     ▼                                      │
Traditional Retail Centre Pipeline    Retail Park Pipeline                           │
(Stages 3-9)                          (Stages 10-11)                                 │
                                                                                      │
├─ Stage 3: H3 Spatial Aggregation       ├─ Stage 10: Retail Park Identification       │
├─ Stage 4: Network Construction      └─ Stage 11: H3 Conversion and Aggregation    │
├─ Stage 5: Network Thresholding                                                     │
├─ Stage 6: Gap Filling                                                              │
├─ Stage 7: Subcentre Detection                                                      │
├─ Stage 8: Land Use Filtering                                                       │
└─ Stage 9: Adjacent Centre Merging                                                  │
         │                                     │                                      │
         └─────────────────────────────────────┴──────────────────────────────────────┘
                                               │
                                               ▼
                      Integration and Post-Processing (Stages 12-14)
                      ├─ Stage 12: Integration of Traditional Centres and Retail Parks
                      ├─ Stage 13: Boundary Finalization
                      └─ Stage 14: Attribute Calculation and Assignment
```



## Methodological Pipeline

### POI Data Preparation (Stages 1-2)
*Applied to all POI data before branching into separate pipelines*

---

### Stage 1: POI Quality Filtering

**Objective:** Remove erroneous and low-quality POI records

**Implementation:** `src/retail/foursquare_qualityfilter.py::filter_foursquare_quality()`

**Seven Sub-Filters Applied Sequentially:**

1. **Closed Venues**: Removes POIs with non-null `date_closed` field

2. **Defunct UK Retailers**: Pattern matching against ~180 historical UK retail chains (e.g., Woolworths, BHS, Blockbuster, Comet). Normalized name matching handles variations.

3. **UK Boundary Filter**: Spatial join with UK boundary polygon (50m buffer). Removes POIs outside UK extent.

4. **Foreign Addresses**: Detects non-UK addresses via pattern matching (US/CA/AU state codes, postal patterns, foreign country names). Safe passes for UK place names (e.g., "Canada Water").

5. **Postcode Mismatches**: Cross-references coordinates with ONSPD (Office for National Statistics Postcode Directory). Removes POIs >1000m from postcode centroid (likely geocoding errors). Batched processing (100k POIs per batch).

6. **Duplicate POIs**: Identifies duplicates based on distance <15m + same category + address match + (name similarity ≥60% OR telephone match OR website match). Uses H3 spatial index for efficient neighbor queries. Keeps most recently refreshed POI. Uses connected components for transitive duplicates.

7. **Business Changes**: Detects same location (~1m precision) and same cat, with different business names. Keeps most recently created POI. Safeguard: bulk imports with same creation date kept entirely (e.g., outlet centers).


**Output:** Quality-filtered POI dataset with validated coordinates, operational status, and deduplicated records

---

### Stage 2: Retail Category Filtering

**Objective:** Filter to retail-relevant POI categories using Foursquare hierarchical taxonomy

**Implementation:** `src/retail/retailfilter.py::filter_foursquare()`

**Filter Logic Flow:**

**Step 1: Positive Inclusion** (Level 1-4 category matching)
- **Level 1 (all)**: Retail, Dining & Drinking, Arts & Entertainment
- **Level 2-4 (selected)**:
  - Business services: Health & Beauty, Pet Service, Photography Service, Locksmith, Funeral Home, Laundry
  - Financial: Bank (L4), Credit Union, Real Estate Agency, Loans Agency
  - Transport: Fuel Station, Travel Agency, Tourist Information
  - Medical: Doctor's Office, Dentist, Veterinarian, Physical Therapy
  - Community: Post Office, Library, Community Center, Social Club
  - Sports: Gym & Studio, Indoor Play Area, Martial Arts Dojo, Swimming Pool (L4)

**Step 2: Category-Level Exclusions** (removes matching category only, POI kept if other categories present)

Organized by Level 1 parent category:
- **Arts & Entertainment**: Amusement Park, Stadium, Zoo, Aquarium, Museum, Fair, Carnival, Circus, Exhibit, Disc Golf, Disc Golf Course, Go Kart Track
- **Business & Professional Services**: Psychic & Astrologer, Photography service categories (Photographer, Photography Studio, Photography Lab)
- **Retail**: Auction House, Vineyard, Construction Supplies Store, Outlet Mall, Shopping Mall, Shopping Plaza

**Step 3: POI-Level Exclusions** (removes ENTIRE POI via anti-join on fsq_place_id)

These POIs often have legitimate retail/business categories as secondary categories, but their primary function is non-retail. We remove the entire POI to prevent false positives (e.g., car dealerships with "Retail" or "Print Shop" categories, hospitals with "Doctor's Office" categories).

- **Vehicle sales**: Car Dealership, Motorcycle Dealership, Motor Scooter Dealership
- **Real estate development**: Real Estate Development & Title Company, Commercial Real Estate Developer (distinct from Real Estate Agency, which is retail)
- **Healthcare facilities**: Hospital (removes confusion with Doctor's Office POIs)
- **Marketing**: Advertising Agency (removes confusion with Print Shop retail category)
- **Public infrastructure**: Public Art

**Step 4: Name-Based Filters**
- **Warehouses**: Removes "Warehouse or Wholesale Store" EXCEPT POIs named "Argos" (Argos has retail format)
- **Costa Express**: Removes POIs with name containing both "Costa" AND "Express" (automated machines, not retail destinations)
- **Post boxes**: Removes exact name matches: "Post Box", "Postbox", "Post box"
- **Misclassified fuel stations**: Removes Fuel Station category POIs with car brand names + dealership keywords in name

**Step 5: Deduplication**
- Removes POIs with duplicate name + lat + lng (keeps one instance, removes multi-category duplicates)

**Output:** Retail-relevant POI subset (~60-70% of quality-filtered dataset)

---

### Traditional Retail Centre Pipeline (Stages 3-7)
*Hex-based POI aggregation and network detection*

---

### Stage 3: Spatial Aggregation to H3 Hexagons

**Objective:** Transform point data to areal units for network analysis

**Implementation:** `src/utils/utils.py::agg_to_cells_foursquare()`

**Tessellation Scheme:**
- **Grid system**: Uber H3 hexagonal hierarchical geospatial indexing
- **Resolution**: Level 11 (edge length ~150m, area ~0.024 km²)

**Aggregation Process:**
1. Convert lat/lng coordinates to H3 cell IDs using `h3.latlng_to_cell()`
2. Group POIs by H3 cell
3. Calculate per-cell statistics:
   - Total POI count
   - Category distribution (4 super-categories)
   - Density metrics

**Output:** H3-aggregated retail density surface with category attributes

---

### Stage 4: Network Construction

**Objective:** Identify connected cluster of h3 cells with retail activity/.

**Implementation:** `src/utils/utils.py::create_networks()`

Criteria for H3 Cell Inclusion:
- Minimum POI count per cell: `min_retail_in_cell = 2` (configurable)
- Cell is included inside one of our filtered retail land use polygons.
- Manual additions from `src/retail/manual_edits.py` These are a handful of cells indified in the previous consultation which were missed by the algorithm.
- We were previouslty removed cells from a list from the previous consulation but these are not needed with the new algorithm. We could add a new set of removals if requested
**Graph Construction:**
1. **Nodes**: H3 cells meeting `min_retail_in_cell` threshold
2. **Edges**: K-ring adjacency (k=1, immediate neighbors only)
   - H3 cells have exactly 6 neighbors (hexagonal topology)
3. **Connected components**: Identified using NetworkX `connected_components()`

**Network ID Assignment:**
- Network ID = smallest H3 cell ID (as integer) in connected component
- Ensures deterministic, reproducible network labeling

**Output:** Initial retail networks (connected components of H3 cells)

---

### Stage 5: Network Thresholding

**Objective:** Remove networks which do not contain more than the minimum POI count

**Parameter:** `min_retail_in_network = 10` (configurable)
**Action:** Remove networks below POI threshold

**Output:** Networks meeting minimum size requirement

---

### Stage 6: Gap Filling

**Objective:** Fill small holes within retail networks

**Implementation:** `src/retail/network_merger.py::fill_until_no_new_cells()`

**Parameter:** `min_to_fill = 6` (configurable - at 6, fills cells completely surrounded by network)

**Output:** Networks with interior gaps filled

---

### Stage 7: Subcentre Detection (Community Detection)

**Objective:** Split large retail networks into subcentres based on POI density. Large retail areas (e.g., major city centres) often contain multiple distinct retail hubs. This stage identifies and delineates these subcentres within large networks.

**Implementation:** `src/retail/find_subcentres.py::find_subcentres()`

**Algorithm:** Leiden community detection (Traag et al., 2019)

**Graph Construction:**
1. **Nodes**: H3 cells within network
2. **Edge weights**: Composite of spatial proximity and category similarity
   - Spatial: K-ring adjacency (binary)
   - Category similarity: Cosine similarity of 4-category POI distributions
   - Weight formula: `w = alpha * category_sim + (1-alpha) * density`
   - By default, `alpha = 0` (pure density-based clustering)

**Parameters:**
- `alpha = 0`: Pure density-based clustering (spatial proximity only)
- `resolution = 0.15`: Controls cluster granularity (lower = fewer, larger clusters) - Determined via empirical testing and consultation
- `seed = 505`: Fixed random seed for reproducibility
- `split_threshold = 1500`: POI count threshold for network splitting, prevents over-segmentation of small networks
  - Networks ≥ 1500 POIs: Apply Leiden, split if multiple communities detected
  - Networks < 1500 POIs: No splitting (retain as single centre)


**Output:** Refined retail centres with subcentre delineation

---

### Stage 8: Land Use Filtering

**Objective:** Remove false positives in commercial/industrial areas (industrial estates with trade counters, business parks with retail related POIs)

**Implementation:** `src/retail/retail_landuse_poi_filter.py`

**Exclusion Logic:**

#### 8a: Commercial/Industrial Overlap
**Data Source:** OSM `landuse=commercial` and `landuse=industrial` polygons

**Overlap Calculation:**
1. Spatial intersection of centre boundary with commercial/industrial polygons
2. Compute `overlap_fraction = intersection_area / centre_area`

**Threshold Rules:**
- `overlap_fraction > 0.75` AND `total_pois < 20`: Remove (likely industrial estate)

**Examples Filtered:**
- Industrial estates with trade counters


#### 8b: Quality Assurance Checks
- Manual review of centres near airports, stadiums, universities
- Hardcoded exceptions in `src/retail/manual_edits.py` (~180 H3 cells)

**Output:** Refined centre list with commercial/industrial false positives removed

---

### Stage 9: Adjacent Centre Merging

**Objective:** Reunite artificially fragmented continuous retail areas

**Implementation:** `src/retail/network_merger.py` (post-processing phase)

**Merge Criteria:**
1. **Spatial proximity**: Centres separated by ≤1 empty cell
2. **Size threshold**: At least one centre has POI count < `merge_h3_threshold` (default: 10)
   - Smaller centre is merged into adjacent larger centre

**Typical Cases:**
- High streets split by pedestrian crossings
- Town centres divided by market squares or small parks
- Shopping parades separated by residential blocks

**Algorithm:**
```
FOR each centre pair:
    IF separation == 1 cell AND one_centre_pois < merge_h3_threshold:
        MERGE smaller centre into larger centre
        UPDATE statistics
```

**Output:** Merged centres with reduced artificial fragmentation

---

### Retail Park Pipeline (Stages 10-11)
*Big-box POI-based detection - runs in parallel to traditional centre pipeline*

This is an entirely separate method which works in parallel to the traditional centre detection pipeline, designed to identify large car-oriented retail parks which may not be well-captured due to their dispersed layout and lower overall POI density.

**Implementation:** `src/retail/detect_retail_parks.py`

---

### Stage 10: Retail Park Identification via OSM Land Use

**Objective:** Identify car-oriented big-box retail parks using OSM land use polygons

**Data Source:** OpenStreetMap `landuse=retail` polygons

**Brand List:** List of large-format retailers
- Eg DIY (B&Q, Homebase), electronics (Currys), furniture (IKEA, DFS), discount (B&M, Home Bargains)
- NLP Pattern matching on POI names

**Retail Park Criteria:**
1. Fraction of POIs within polygon which match big-box brands > 0.05 (5%) - this is low but there are very few false positives at this level. Raising any higher starts to remove genuine retail parks.
2. Size greater than 0.07 km² (7000 m²) - ensures minimum spatial extent - this removes a small number of false positives in dense urban areas (mainly London), where big box stores often exist in unusual formats (B&Q on high street etc)

Passing this criteria marks the polygon as a retail park.

**Output:** Retail park polygons meeting criteria

---

### Stage 11: H3 Conversion and Aggregation

**Objective:** Convert retail park polygons to H3 cells and aggregate statistics

**Process:**
We convert the retail park polygons to H3 cells at resolution 11, and aggregate POI counts and other statistics in the same way as for traditional centres.

If this aggregation results in parks with overlapping cells, we merge them into a single retail park. This handles cases where what is functionally a single retail park is mapped as multiple adjacent polygons in OSM. There are cases where two separate retail parks exist adjacent to each other (eg in out of town shopping areas) but these are rare and merging them is preferable as it creates a consistent dataset. The implementation of OSM retail land use mapping is quite inconsistent.

**Output:** Retail park boundaries (distinct from traditional high streets) in H3 cells with aggregated POI statistics

---

### Integration and Post-Processing (Stages 12-14)
*Merging traditional centres and retail parks into unified dataset and finalization*

---

### Stage 12: Integration of Traditional Centres and Retail Parks

**Objective:** Merge centre and retail park datasets into unified retail centre dataset

**Implementation:** `src/retail/integrate_retail_parks.py`

The centre and retail park datasets are integrated into a single unified retail centre dataset. This is done by adding the retail parks to the traditional centre dataset, in cases where they do not overlap with existing traditional centres. Where they do overlap, we "cut" the retail park out of the traditional centre to create separate entities. If the remaining traditional centre is just a stub and too small to be its own centre (below minimum POI threshold) it is merged into the retail park. OR if it does not pass the land use filtering stage, it is removed entirely (ie on commercial land surrounded by the retail park).

**Output:** Unified retail centre dataset with parks integrated

---

### Stage 13: Boundary Finalization

**Objective:** Convert H3 cells to publication-ready polygon boundaries

**Implementation:** `src/retail/centre_postprocessing.py`

**Geometric Processing:**

#### 13a: Polygon Dissolution
**Function:** `dissolve_h3_to_polygons()`

**Process:**
1. Convert H3 cell IDs to polygon geometries using `h3.cells_to_h3shape()`
2. Dissolve adjacent cells into single multipolygon per centre
3. Simplify geometry (Douglas-Peucker algorithm, tolerance = 1m)

#### 13b: Hole Filling
**Criteria:** Fill interior holes (voids) in polygons
- Removes small interior gaps (car parks, small parks)
- Preserves exterior boundaries

**Output:** Clean polygon geometries

---

### Stage 14: Attribute Calculation and Assignment

**Implementation:** `src/retail/centre_postprocessing.py::add_localauthorities_to_centres()`

**Computed Attributes:**

#### 14a: Retail Statistics
- `total_pois`: Total POI count
- `retail_count`, `dining_count`, `entertainment_count`, `community_count`: Category breakdowns
- `category_diversity`: Shannon entropy of category distribution
- `area_m2`: Polygon area in square meters
- `poi_density`: POIs per hectare

#### 14b: Local Authority Assignment
**Method:** Spatial intersection with ONS Local Authority boundaries

**Assignment Logic:**
1. Intersect centre boundary with all LA polygons
2. Calculate overlap area for each LA
3. Assign LA with maximum overlap (plurality rule)
4. Add fields: `lad22cd` (LA code), `lad22nm` (LA name)

#### 14c: Centre Ranking
**Ranking:** Descending by `total_pois`
- `centre_rank`: National rank (1 = largest centre)
- Enables size-based filtering and analysis

**Output:** Feature-complete retail centre dataset

---

## Quality Assurance

### Manual Corrections
**Implementation:** `src/retail/manual_edits.py`

**Purpose:** Override algorithmic edge cases
- ~180 hardcoded H3 cells for additions/removals
- Corrections for scattered retail parks, peripheral clusters
- Functions: `add_cells_manually()`, `flag_manually_removed_cells()`

### Validation Steps
1. **Geometric validation**: Check for invalid polygons, self-intersections
2. **Attribute validation**: Verify POI counts, category sums
3. **Spatial validation**: Check for unexpected overlaps
4. **Visual QA**: Manual review of sample centres in QGIS

---

## Parameter Sweep Framework

**Implementation:** `src/main.py`

**Purpose:** Systematic evaluation of parameter combinations

**Current Parameter Values:**
```python
min_retail_in_cell: [2]                 # Cell inclusion threshold
min_retail_in_network: [10]             # Network size threshold
min_to_fill: [6]                        # Gap-filling (6 = fill holes only)
split_threshold: [1500, 9999999]        # Subcentre detection threshold
merge_adjacent: [True]                  # Enable/disable merging
```

**Output Naming Convention:**
```
{run_name}/{source}_mrc_{min_cell}_mrn_{min_network}_mtf_{min_fill}_splitthresh_{threshold}_merge_{y/n}
```

**Intermediate Outputs (per parameter combination):**
- `0_input_cells.parquet`: Filtered H3 cells
- `1_intial_networks.parquet`: Connected components
- `2_filtered_networks.parquet`: After network thresholding
- `3_afterfill.parquet`: After gap filling
- `4_finalcentres.parquet`: Dissolved polygons
- `4_finalcentres_las.parquet`: Final boundaries with LA assignments

---

## Computational Environment

**Libraries:**
- **Spatial indexing**: `h3-py` (Uber H3 hexagonal grid)
- **Graph analysis**: `NetworkX` (network construction, connected components)
- **Community detection**: `leidenalg`, `igraph` (Leiden algorithm)
- **Data processing**: `polars` (primary aggregation), `pandas` (category mapping)
- **Geospatial**: `geopandas`, `shapely` (geometric operations)
- **Coordinate transformation**: `pyproj` (EPSG transformations)

**Performance:**
- Runtime: ~5-15 minutes per parameter combination (100k+ POIs)
- Bottlenecks: H3 neighbor queries, Leiden clustering on large networks
- Optimization: Polars vectorization for aggregation, parallel parameter sweep

**Reproducibility:**
- Fixed random seeds (Leiden: 505)
- Versioned dependencies (see `setup.py`)
- All intermediate stages saved for audit trail

---

## Output Data Products

### Final Datasets

#### Traditional Retail Centres
**File:** `{run_name}_finalcentres_las.parquet`

**Schema:**
- `centre_id` (int): Unique identifier
- `centre_rank` (int): Size-based national rank
- `geometry` (polygon): Boundary in EPSG:27700
- `total_pois` (int): Total POI count
- `retail_count`, `dining_count`, `entertainment_count`, `community_count` (int): Category counts
- `area_m2` (float): Area in square meters
- `poi_density` (float): POIs per hectare
- `lad22cd`, `lad22nm` (str): Local Authority code and name
- `centre_type` (str): "traditional" | "retail_park" | "mixed"

#### Retail Parks
**File:** `{run_name}_retail_parks.parquet`

**Additional Fields:**
- `big_box_proportion` (float): Fraction of POIs matching big-box brands
- `osm_retail_overlap` (float): Overlap fraction with OSM retail land use

### Format Conversions
**Tool:** `src/utils/convtoshp.py`

**Supported Formats:**
```bash
python src/utils/convtoshp.py output.parquet -f shapefile  # ESRI Shapefile
python src/utils/convtoshp.py output.parquet -f geojson    # GeoJSON
```

