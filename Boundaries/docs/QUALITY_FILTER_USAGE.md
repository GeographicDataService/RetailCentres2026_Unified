# Quality Filter Save/Load Feature

This document explains how to use the presaved quality filter functionality to speed up repeated pipeline runs.

## Overview

Quality filtering (removing defunct retailers, duplicates, foreign addresses, etc.) is expensive. This feature allows you to:
1. Run filters once and save which POI IDs should be removed
2. Reuse those saved results in subsequent runs (much faster)

## Usage

### First Run: Save Filter Results

Run the pipeline with `--save_filter_ids` to save which POIs are filtered out:

```bash
python src/main.py --run_name "my_run" --save_filter_ids
```

This will:
- Run all quality filters normally
- Save removed POI IDs to `data/POI_files/quality_filter_ids.parquet`
- Output shows breakdown by filter type (closed, defunct, duplicates, etc.)

### Subsequent Runs: Use Presaved Filters

Use `--use_presaved_filters` to skip expensive filtering and apply saved results:

```bash
python src/main.py --run_name "my_run" --use_presaved_filters
```

This will:
- Load saved filter IDs from `data/POI_files/quality_filter_ids.parquet`
- Apply them via fast anti-join (removes matching POI IDs)
- Skip all expensive filter operations (boundary checks, duplicate detection, etc.)

### Custom Filter Path

Use `--filter_ids_path` to specify a custom location:

```bash
# Save to custom path
python src/main.py --run_name "my_run" --save_filter_ids --filter_ids_path "my_filters.parquet"

# Load from custom path
python src/main.py --run_name "my_run" --use_presaved_filters --filter_ids_path "my_filters.parquet"
```

## Saved File Format

The saved file (`quality_filter_ids.parquet`) contains:
- `fsq_place_id`: Foursquare place ID to remove
- `filter_type`: Which filter removed this POI (e.g., "closed", "defunct", "duplicates", "business_changes", "foreign_addresses", "postcode_mismatch", "outside_uk")

## When to Regenerate

Regenerate filter results when:
- Input POI data changes
- You modify filter parameters (thresholds, boundaries, etc.)
- Defunct retailer list is updated
- ONSPD postcode data is updated

## Programmatic Usage

You can also use the functions directly in Python:

```python
from retail import foursquare_qualityfilter

# Run filters and save IDs
filtered = foursquare_qualityfilter.filter_foursquare_quality(
    foursquare,
    save_filter_ids=True,
    filter_ids_path="my_filters.parquet"
)

# Load and apply presaved filters
filtered = foursquare_qualityfilter.load_and_apply_presaved_filters(
    foursquare,
    filter_ids_path="my_filters.parquet"
)
```

## Performance Benefit

Approximate speedup (depends on data size):
- Normal filtering: 5-15 minutes (includes UK boundary spatial join, duplicate detection, etc.)
- Presaved filtering: 5-30 seconds (simple anti-join on POI IDs)

**Speedup: ~10-100x faster**
