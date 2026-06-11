# Built-Up Area Dissolve

This folder contains the code used to derive the Built-Up Area (BUA) input read
by the Classification stage:

```text
Classification/geo/buildup/merged_BUA_dissolved2025.gpkg
```

The source geodata is intentionally not tracked in git. It is either restored
from `classification_inputs.zip` for normal Classification runs, or downloaded
manually when regenerating the derived BUA file.

## Why We Merge BUAs

The Classification stage needs a BUA-like geography for ranking centres within
larger urban areas. The current runtime input is derived from **OS Open Built Up
Areas**, which is more current than the older ONS 2011 BUA reference. However,
the newer OS method produces smaller and more separated built-up polygons than
the 2011 BUA geography.

For retail-centre classification, those extra splits can make rankings less
meaningful: centres that should be compared within the same wider urban area can
end up in separate BUA containers. We therefore dissolve near-touching OS BUA
polygons to produce a more 2011-like geography before classification. The
default process applies a 100m positive buffer, dissolves the polygons, then
applies a 100m negative buffer. In practical terms this joins BUA polygons
separated by gaps of roughly 200m or less, producing a more stable urban-area
container for centre ranking.

## Source Data

Download these files under `Classification/geo/BuiltupAreaDisolve/data/`:

1. **OS Open Built Up Areas** — current BUA source
   - Source: https://osdatahub.os.uk/downloads/open/BuiltUpAreas
   - Format: GeoPackage
   - Expected path: `geo/BuiltupAreaDisolve/data/os_open_built_up_areas.gpkg`
   - Version date: April 2026. Use the latest OS Open Built Up Areas download
     available when intentionally regenerating this derived input.

2. **Built Up Areas Dec 2011 Boundaries V2** — optional comparison reference
   - Source: ONS Open Geography Portal
   - Search: `Built Up Areas Dec 2011 Boundaries V2`
   - Expected path: `geo/BuiltupAreaDisolve/data/Built_up_Areas_Dec_2011_Boundaries_V2_2022.gpkg`
   - Vintage: this is the ONS 2011 BUA geography, published as the 2022 V2
     boundary product. It is not the Classification runtime input; it is used as
     a reference for reasonableness checks.

## Generate The Derived Input

Run from `Classification/`:

```bash
python scripts/bua_dissolve/merge_polygons.py
```

By default this reads:

```text
geo/BuiltupAreaDisolve/data/os_open_built_up_areas.gpkg
```

and writes:

```text
geo/buildup/merged_BUA_dissolved2025.gpkg
```

The method applies a 100m positive buffer, dissolves/merges the buffered
polygons, then applies a 100m negative buffer. This merges BUA polygons within
roughly 200m of each other.

## Compare Against ONS Reference

Run from `Classification/`:

```bash
python scripts/bua_dissolve/compare_datasets.py
```

This reports area overlap statistics between the derived dissolved BUA file and
the ONS 2011 reference, and writes optional lightweight viewing outputs under:

```text
geo/BuiltupAreaDisolve/output/
```

## Notes

- The working CRS is expected to be EPSG:27700.
- Large inputs, outputs, and comparison artifacts remain under `geo/` and are
  ignored by git.
- `classification_inputs.zip` includes only the final derived
  `geo/buildup/merged_BUA_dissolved2025.gpkg` needed to run Classification.
