# Naming Logic

This document describes how retail centre names are generated, and how the Python implementation differs from the original R pipeline.

## Overview

The naming pipeline runs in two stages:

1. **Lookup generation** (`naming.py`) — builds four lookup tables from spatial data
2. **Name assembly** (`generate_names.py`) — combines lookups into final `RC_Name` values

The output name format is:

```
Street; Neighbourhood; Local Authority (Region; Country)
```

Components are omitted when empty, so a Regional Centre might just be `Manchester; Manchester (North West; England)`.

---

## Stage 1: Lookup Generation (`naming.py`)

### 1a. ONS Naming

Spatial intersection of centre polygons with administrative boundaries:

- **Local Authority** (LAD) — pre-joined in the input gpkg (`LocalAuthorityNM_1/2/3`)
- **County** — pre-joined (`CountyName`)
- **City / Built-Up Area** — spatial intersection with BUA (England/Wales), Scottish Localities, and NI Settlements. Top 2 by area proportion, >10% threshold.
- **Neighbourhood** — spatial intersection with MSOA (England/Wales), Intermediate Zones (Scotland), and SOA (Northern Ireland). Top 3 by area proportion, >10% threshold.
- **Country / Region** — derived from `RegionName` in the gpkg. For Scotland, Wales, and NI the region equals the country.

### 1b. OS Open Names — Nearest

For each centre's centroid, finds the nearest OS Open Names place of each type (City, Town, Village, Suburban Area, Other Settlement, Hamlet) using a KDTree. The 10km buffer from the R version is preserved, though the fallback (nearest overall if nothing within 10km) means all centres get a match.

Where OS Open Names has a Gaelic or Welsh primary name with an English alternative, the English name is used by default (`PREFER_ENGLISH_NAMES = True`).

### 1c. OS Open Names — Internal

Finds OS Open Names places that fall within a 100m buffer of each centre polygon. When multiple places of the same type fall inside a centre, the one nearest to the centroid is kept.

Priority order for selecting the neighbourhood name from internal places: City > Village > Town > Suburban > Settlement > Hamlet. Internal names override nearest names.

### 1d. Street Naming (Foursquare)

Spatial join of Foursquare POIs to centre polygons, then:

1. **Extract street name** from the `address` field — strips leading house/unit numbers, validates that at least one word matches a known UK street suffix (Road, Street, Lane, etc.)
2. **Expand abbreviations** — only the final word is expanded (e.g. `Rd` → `Road`), so `St Albans` is not changed to `Street Albans`
3. **Frequency analysis** — counts POIs per street per centre, computes proportions
4. **Top 2 streets** kept per centre (`Str_1`, `Str_1_P`, `Str_2`, `Str_2_P`)
5. **Retail park extras** — for retail park centres, also extracts branded park names from addresses (regex for "Retail Park", "Shopping Park", etc.) and the most common `locality` value

---

## Stage 2: Name Assembly (`generate_names.py`)

### 2a. Classification

Classifications are taken directly from the input gpkg. A hardcoded list of ~45 shopping outlets/centres (with coordinates) is spatially matched to centres and overrides their classification (e.g. to "Regional Shopping Centre" or "Large Outlet Shopping Centre").

### 2b. Name Assembly

**Level 1 — Street name selection:**

- If the top street's proportion > 31%: use that street alone
- Else if the second street's proportion > 31%: combine as `Street1 & Street2`
- Otherwise: no street name assigned

**Level 2 — Neighbourhood name:**

- Start with the nearest OS place (minimum distance across all types)
- Override with internal OS place if available (priority: City > Village > Town > Suburban > Settlement > Hamlet)
- **Northern Ireland exception**: OS Open Names doesn't cover NI, so any OS-derived name is cleared and replaced with the SOA neighbourhood name from the ONS lookup (digits stripped from the name)

**Final assembly by classification:**

| Classification | Format |
|---|---|
| Regional Centre, Major Town Centre, Town Centre | `Neighbourhood; LA (Region; Country)` |
| All others (District, Local, Small Local, Market Town) | `Street; Neighbourhood; LA (Region; Country)` |
| Retail Parks | `BrandedName; LA (Region; Country)` or `Locality Retail Park; LA (Region; Country)` |
| Shopping Centres / Outlets | `OutletName; LA (Region; Country)` |

### 2c. Sub-area Naming

Centres with `was_split = True` are grouped by `Parent_ID`. Each group gets a shared parent name built from the nearest City/Town OS name across all members. The primary sub-area (highest `tr_retailN`) provides the LA/Region/Country. All sub-areas in the group receive the same name (differentiated later by deduplication).

### 2d. Cleanup and Deduplication

**Cleanup rules:**
- Collapse repeated `; ; ` separators
- Fix country duplication (`Scotland; Scotland` → `Scotland`)
- Fix LA name inversions (`Bristol, City of` → `City of Bristol`)
- Fix `; (` → ` (`

**Deduplication:**
- When multiple centres share the same name, suffixes ` - 2`, ` - 3`, etc. are appended
- Centres are sorted by classification hierarchy before deduplication, so higher-ranked centres keep the clean name (e.g. a Town Centre keeps `Diss; South Norfolk (East of England; England)` while a Small Local Centre gets ` - 2`)

Classification priority order: Regional Centre > Major Town Centre > Town Centre > Market Town > District Centre > Local Centre > Small Local Centre > Large Retail Park > Small Retail Park > Large Shopping Centre > Small Shopping Centre.

---

## Differences from the Original R Pipeline

### Data source changes

| Aspect | R version | Python version |
|---|---|---|
| **Retail points** | VOA rating list addresses | Foursquare POI data |
| **Retail park names** | LDC proprietary data | Extracted from Foursquare POI addresses (regex for branded park names) + locality field |
| **Street names** | VOA address data (street field) | Extracted from Foursquare address field (house number stripping + street suffix validation) |
| **OS Open Names format** | CSV files | GeoPackage preferred, CSV fallback |

### Logic changes

| Change | Detail |
|---|---|
| **Gaelic/Welsh name handling** | New: swaps to English `name2` where `name1_lang` is `gla` or `cym`. The R version used whatever `NAME1` contained. |
| **Retail park naming** | New: uses Foursquare address data to find branded retail park names and locality names. The R version relied entirely on LDC data. |
| **Sub-area naming** | New capability: centres with `was_split = True` and a `Parent_ID` share a parent name derived from the nearest City/Town. Not present in the R version. |
| **Dedup priority** | New: deduplication now sorts by classification hierarchy so higher-ranked centres keep the unsuffixed name. The R version used arbitrary row order. |
| **Street extraction** | New: validates extracted streets against a list of UK street suffixes to avoid non-street addresses. The R version used the VOA street field directly. |
| **Street abbreviation expansion** | New: only expands the final word to avoid `St Albans` → `Street Albans`. |
| **Shopping outlet matching** | Uses spatial join of hardcoded coordinates to centre polygons. Same list as R but matched spatially rather than by RC_ID (since IDs have changed). |

### Known limitations

- **Street name sparsity**: Small centres with few Foursquare POIs often fail to meet the 31% street frequency threshold, resulting in no street name. This means some Small Local Centres get the same name pattern as their nearby Town Centre, differentiated only by a dedup suffix.
- **NI neighbourhood names**: Depend on SOA boundary data being available; without it NI centres get no neighbourhood.
- **Sub-area differentiation**: All sub-areas in a group currently receive the same parent name. Individual sub-area names (e.g. prepending the local neighbourhood) are not yet implemented.
