# Naming Logic

This document describes how retail centre names are generated, and how the Python implementation differs from the original R pipeline.

## Overview

The naming pipeline runs in two stages:

1. **Lookup generation** (`naming.py`) — builds seven lookup tables from spatial data
2. **Name assembly** (`generate_names.py`) — combines lookups into final `RC_Name` values

The output name format is:

```
Street; Neighbourhood; Local Authority (Region; Country)
```

Components are omitted when empty, so a Regional Centre might just be `Manchester; Manchester (North West; England)`.

---

## Stage 1: Lookup Generation (`naming.py`)

### 1a. ONS Naming

LA, County, Region, and Country come **pre-joined** in the input gpkg (`LocalAuthorityNM_1/2/3`, `CountyName`, `RegionName`) — no spatial work in `naming.py`. The only spatial intersection performed at this stage is the neighbourhood lookup.

- **Local Authority / County / Region / Country** — pre-joined columns, copied through. Country is derived from `RegionName` (English regions → England; Wales/Scotland/NI → matching country, with `RegionNM` rewritten to equal the country).
- **Neighbourhood** — spatial intersection with MSOA (England/Wales), Intermediate Zones (Scotland), and **Super Data Zones** (Northern Ireland, `NbhdTY = SDZ2021CD`). Top 3 by area proportion, >10% threshold.

Output: `RC_Naming_ONS.csv`.

### 1b. OS Open Names — Nearest

Loads OS Open Names (populated places + transport network) from a GeoPackage, supplemented with OSM place nodes (`city/town/village/suburb/hamlet`) for Northern Ireland from `osm_ni_places.parquet` — OS Open Names doesn't cover NI, so OSM fills the gap and NI then flows through the same lookup as GB.

For each centre's centroid, finds the nearest OS Open Names place of each type (City, Town, Village, Suburban Area, Other Settlement, Hamlet) using a KDTree. The 10 km buffer is preserved from the R version, though the fallback (nearest overall if nothing within 10 km) means all centres get a match.

Where OS Open Names has a Gaelic or Welsh primary name with an English alternative, the English name is used by default (`PREFER_ENGLISH_NAMES = True`).

Output: `RC_Naming_OS.csv`.

### 1c. OS Open Names — Internal

Finds OS Open Names places that fall within a 100 m buffer of each centre polygon. When multiple places of the same type fall inside a centre, the one nearest to the centroid is kept.

Priority order for selecting the neighbourhood name from internal places: City > Village > Town > Suburban > Settlement > Hamlet. Internal names override nearest names at the assembly stage.

Output: `RC_Naming_OS_Internal.csv`.

### 1d. Street Naming (Foursquare)

Spatial join of Foursquare POIs to centre polygons, then:

1. **Extract street name** from the `address` field — splits on commas (taking the first part), strips leading house/unit numbers, then validates the result.
2. **Validation, two-stage**:
   - First, check the candidate (length ≥ 5 chars) against the OS Open Names `Named Road` set, loaded lazily from `os_open_names/Data/opname_gb.gpkg`.
   - Otherwise, fall back to UK street-suffix matching against a curated list (Road, Street, Lane, etc.), including two-word suffixes like "high street".
3. **Expand abbreviations** in the **last two words** of the street (so `Rd` → `Road`, and `Rd South` → `Road South`). A guard prevents `St` followed by a proper noun from being rewritten — so `St Albans` is preserved, but `St N` (i.e. `Street North`) is still expanded.
4. **Frequency analysis** — counts POIs per street per centre, computes proportions.
5. **Top 2 streets** kept per centre (`Str_1`, `Str_1_P`, `Str_2`, `Str_2_P`).
6. **Retail park extras** — for centres flagged `centre_type == retail_park`, also extracts:
   - `RetailParkBranded` — the most common branded park name extracted from POI addresses via regex (matches "Retail Park", "Shopping Park", "Leisure Park", "Trading Estate", "Shopping Centre", "Retail Centre", "Retail & Leisure Park").
   - `RetailParkLocality` — the most common Foursquare `locality` value, used as a fallback.

Output: `RC_Naming_Streets.csv`.

### 1e. OSM Retail Park Names

Independent retail-park naming pathway using OSM `landuse=retail` polygons.

- Spatial join of named OSM retail polygons to RCs flagged as retail parks.
- Containment filter: only OSM polygons **>95% contained** within the RC are kept.
- 31% area rule: per RC, keep every name whose polygon covers more than 31% of the total contained-OSM area; if none clear 31%, fall back to the largest polygon.
- Deduplicate near-matches by substring containment in either direction.
- Multiple surviving names are joined with ` & `.

Output column: `OSM_RetailParkName`. CSV: `RC_Naming_OSM_RetailParks.csv`.

### 1f. Address Component Naming

Captures place names like "Liverpool One", "The Moor", or "Arndale Centre" that are real centre identifiers but don't end in a recognised street suffix.

- Splits each Foursquare address on commas; strips house/unit numbers and discards postcodes.
- Title-cases and abbreviation-expands every component (`_normalise_address_component`) for case-insensitive grouping.
- Per RC, excludes the most common `locality` value (the city name itself) so it doesn't drown out useful tokens.
- Top 2 by frequency: `Addr_1`/`Addr_1_Norm`/`Addr_1_P`, `Addr_2`/`Addr_2_Norm`/`Addr_2_P`.

Output: `RC_Naming_AddressComponents.csv`.

> **Note**: this CSV is generated but **not currently consumed** by `generate_names.py` — the `load_data` function reads only six of the seven lookups. It is available for future integration but does not affect current `RC_Name` output.

### 1g. OSM Neighbourhood Names

Provides a neighbourhood-name fallback for centres where OS Open Names has no internal match.

- Spatial join of `osm_neighbourhoods.parquet` (OSM nodes tagged `place=neighbourhood/quarter`) to RC polygons buffered by 100 m.
- Where multiple nodes match a centre, keep the one nearest to the centroid.

Output columns: `OSM_NbhdName`, `OSM_NbhdType`, `OSM_NbhdDist`. CSV: `RC_Naming_OSM_Neighbourhoods.csv`.

---

## Stage 2: Name Assembly (`generate_names.py`)

### 2a. Classification

Classifications are taken directly from the input gpkg. A hardcoded list of ~45 shopping outlets/centres (with coordinates) is spatially matched to centres and overrides their classification (e.g. to `Regional Shopping Centre` or `Large Outlet Shopping Centre`).

A temporary in-script override sets `RC_ID 1661` (Brighton Marina) to `Large Retail Park`; the inline comment notes this is intended to migrate to the classification module.

### 2b. Name Assembly

**Level 1 — Street name selection:**

- If the top street's proportion > 31%: use that street alone
- Else if the second street's proportion > 31%: combine as `Street1 & Street2`
- Otherwise: no street name assigned

**Level 2 — Neighbourhood name** (in priority order):

1. Start with the nearest OS place (minimum distance across all types from the 1b output).
2. Override with the internal OS place if available (1c), under the priority chain City > Village > Town > Suburban > Settlement > Hamlet.
3. If neither nearest nor internal OS produced a name, fall back to the OSM `place=neighbourhood/quarter` name from 1g.
4. Apply manual neighbourhood overrides for a small set of RCs where OS placement is wrong: `2126` (Paternoster Row, Sheffield), `666` (Kingswood), `1699` (Bromborough). See `NEIGHBOURHOOD_OVERRIDES` in code.

NI no longer needs special handling at the assembly stage because OSM NI place nodes were merged into the OS dataset in 1b.

**Final assembly by classification:**

| Classification | Format |
|---|---|
| Regional Centre, Major Town Centre, Town Centre (and **not** a sub-area) | `Neighbourhood; LA (Region; Country)` |
| Sub-areas of any class, plus District / Local / Small Local / Market Town | `Street; Neighbourhood; LA (Region; Country)` |
| Retail Parks | See retail-park priority below |
| Shopping Centres / Outlets | `OutletName; LA (Region; Country)` |

Sub-areas (`was_split == True`) always get the street format here, then are overwritten by the sub-area block in 2c.

**Retail park naming priority:**

1. **OSM landuse name** from 1e (`OSM_RetailParkName`) — first choice when present.
2. **Foursquare branded name** from 1d (`RetailParkBranded`) — fallback.
3. For parks still unnamed, append the literal ` Retail Park` to the first name component (typically a street).

A manual override rewrites `RC_ID 3379`'s `Europa Boulevard Retail Park` to `Gemini Retail Park`.

### 2c. Sub-area Naming

Centres with `was_split == True` are grouped by `Parent_ID`. Each group is named through the following process:

1. **Parent city name**: the closest City-type OS name across all members (falling back to Town) provides the parent city. `City of London` is rewritten to `London`.
2. **Local name** for each sub-area: taken from a manual sub-area dictionary if present (see below); otherwise falls back to the first component of the sub-area's existing pipeline name.
3. **Format** depends on the city:
   - **Non-London**: `Local (City City Centre); LA (Region; Country)` — e.g. `Northern Quarter (Manchester City Centre); Manchester (North West; England)`.
   - **London with settlement context** (the group does **not** contain a Regional Centre, i.e. it's an outer London centre): `Local (Settlement); London (London; England)` — e.g. `Upper Street (Islington); London (London; England)`.
   - **London without settlement context** (the group **does** contain a Regional Centre, i.e. the central London core): `Local; London (London; England)`.

The primary sub-area (highest `tr_retailN`) provides the LA / Region / Country attribution that's shared across the group.

**Manual sub-area dictionary**: `MANUAL_SUBAREA_NAMES_V1` … `V4` provide curated local names for ~150 sub-areas across Liverpool, Manchester, Sheffield, Edinburgh, Glasgow, Leeds, Birmingham, Bristol, Newcastle, Norwich, Nottingham, Aberdeen, Leicester, York, Bath, and Brighton. The active version is selected by the `MANUAL_SUBAREA_VERSION` constant at the top of `generate_names.py` (currently `"v4"`):

- `v1` — street-focused, single names where dominant
- `v2` — neighbourhood/landmark-focused, more two-part names
- `v3` — web-verified geography + POI data, proper quarter/area names
- `v4` — current default

### 2d. Cleanup and Deduplication

**Cleanup rules:**

- Collapse repeated `; ; ` separators
- Strip leading/trailing separator characters
- Fix country duplication: `Scotland; Scotland` → `Scotland`, plus `Wales; Wales` and `Northern Ireland; Northern Ireland`
- Fix `; (` → ` (`
- Fix LA name inversions: `Bristol, City of` → `City of Bristol`; `Kingston upon Hull, City of` → `City of Kingston upon Hull`; `Herefordshire, County of` → `County of Herefordshire`

**Empty names**: any centre that ends up with an empty `RC_Name` falls back to `LocalAuthorityNM_1`.

**Deduplication:**

- When multiple centres share the same name, suffixes ` - 2`, ` - 3`, etc. are appended to all but the highest-priority centre.
- Centres are sorted by classification hierarchy before deduplication, so higher-ranked centres keep the clean name (e.g. a Town Centre keeps `Diss; South Norfolk (East of England; England)` while a Small Local Centre gets ` - 2`).

Classification priority order: Regional Centre > Major Town Centre > Town Centre > Market Town > District Centre > Local Centre > Small Local Centre > Large Retail Park > Small Retail Park > Large Shopping Centre > Small Shopping Centre.

### Outputs

`generate_names.py` writes three files to `exports/`:

- `rc2025_named.gpkg` — final named retail centres
- `rc2025_named.parquet` — same, in GeoParquet format
- `rc2025_naming_lookup.csv` — combined lookup table (`RC_ID`, `RC_Name`, `Classification`, `Street`, `Neighbourhood`, LA, Region, Country)

The seven Stage 1 lookup CSVs (`RC_Naming_ONS.csv`, `RC_Naming_OS.csv`, `RC_Naming_OS_Internal.csv`, `RC_Naming_Streets.csv`, `RC_Naming_OSM_RetailParks.csv`, `RC_Naming_AddressComponents.csv`, `RC_Naming_OSM_Neighbourhoods.csv`) also remain in `exports/` after Stage 1.

---

## Differences from the Original R Pipeline

### Data source changes

| Aspect | R version | Python version |
|---|---|---|
| **Retail points** | VOA rating list addresses | Foursquare POI data |
| **Retail park names** | LDC proprietary data | OSM `landuse=retail` polygon names (1e), with Foursquare-address regex (`RetailParkBranded`) and locality fallback (1d) |
| **Street names** | VOA address data (street field) | Foursquare address field (house-number stripping + OS road validation + suffix fallback) |
| **OS Open Names format** | CSV files | GeoPackage preferred, CSV fallback |
| **NI place names** | (not handled / SOA fallback) | OSM `place=*` nodes (`city/town/village/suburb/hamlet`) merged into the OS Open Names dataset before the nearest/internal lookups |

### Logic changes

| Change | Detail |
|---|---|
| **Gaelic/Welsh name handling** | Swaps to English `name2` where `name1_lang` is `gla` or `cym`. The R version used whatever `NAME1` contained. |
| **Retail park naming** | Three-tier priority: OSM landuse name → Foursquare branded → suffix `" Retail Park"` to first name component. The R version relied entirely on LDC data. |
| **OSM neighbourhood fallback** | New stage 1g: where OS internal/nearest produces no neighbourhood, OSM `place=neighbourhood/quarter` nodes within 100 m provide a fallback. |
| **Sub-area naming** | New: per-sub-area names are built from a manual dictionary (`MANUAL_SUBAREA_NAMES_V1`–`V4`), wrapped with the parent city name, with separate formats for London inner/outer and non-London. Not present in the R version. |
| **Address components stage** | New (1f): unfiltered top address components (no street-suffix requirement). Currently generated but not consumed by Stage 2. |
| **Street validation** | First validates against the OS Open Names `Named Road` set; falls back to a UK street-suffix list. The R version used the VOA street field directly. |
| **Street abbreviation expansion** | Expands the last two words (so `Rd South` → `Road South`); the `St`-before-proper-noun guard preserves `St Albans`. |
| **Dedup priority** | Sorts by classification hierarchy so higher-ranked centres keep the unsuffixed name. The R version used arbitrary row order. |
| **Shopping outlet matching** | Spatial join of hardcoded coordinates to centre polygons (same list as R, but matched spatially since RC_IDs have changed). |
| **Manual neighbourhood overrides** | `NEIGHBOURHOOD_OVERRIDES` dict for a handful of RCs (`2126`, `666`, `1699`) where OS placement is wrong. |

### Known limitations

- **Street name sparsity**: small centres with few Foursquare POIs often fail to meet the 31% street-frequency threshold, resulting in no street name. Some Small Local Centres therefore get the same name pattern as a nearby Town Centre, differentiated only by a dedup suffix.
- **Address components unused**: the stage 1f output is generated but not currently read by `generate_names.py`. Either the pipeline should be wired to consume it (it is the most plausible source for "Liverpool One" / "The Moor" / "Arndale Centre" style names) or the stage should be removed.
- **Sub-area dictionary coverage**: the manual `MANUAL_SUBAREA_NAMES_V*` dictionaries cover ~150 sub-areas in 16 cities. Sub-areas in cities outside that list (or sub-areas in covered cities not in the dictionary) fall back to the first component of their pipeline name, which may not be locally meaningful.
- **OSM NI places coverage**: NI now uses OSM `place=*` nodes in lieu of OS Open Names; coverage and consistency depend on OSM contributor activity in NI and may differ from GB.
