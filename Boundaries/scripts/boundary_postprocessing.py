#!/usr/bin/env python
"""
Boundary post-processing: turn a pipeline run into the final bounds outputs,
ready for classification.

Reads a network-generation run (split + nosplit final centres, POIs, and an
optional retail-parks polygon layer) and writes the deliverable GPKGs into a
timestamped folder under ``data/outputs/boundary_postprocessing/``.

All centres use split IDs; split centres get Parent_ID starting at 1.

Creates 4 variants:
1. postworkshopcentres.gpkg - with splits, with category_names
2. postworkshopcentres_nocatnames.gpkg - with splits, without category_names
3. postworkshopcentres_nosplits.gpkg - without splits (from 99999), with category_names
4. postworkshopcentres_nosplits_nocatnames.gpkg - without splits, without category_names

Also creates:
5. filtered_pois.gpkg - POI data with just name and full category
6. retail_parks.gpkg - Retail park polygons with all attributes (optional)
7. centres_clean.gpkg - Clean centres with only RC_ID and category totals
8. retail_parks_clean.gpkg - Clean retail parks with name, ID, total POIs, matched brands, and match % (optional)
"""

import geopandas as gpd
import pandas as pd
import argparse
from pathlib import Path
from datetime import datetime
import re


# --- Configuration (inlined; this script has no intra-project imports) ------
REPO_ROOT = Path(__file__).resolve().parents[1]
LEGACY_RC_BOUNDS_PATH = REPO_ROOT / "data" / "inputs" / "legacy_rc_bounds.parquet"
RC_ID_RESTORE_BBOX_TOLERANCE_M = 2.0

# Final bounds outputs (ready for classification) live under data/outputs/, next
# to the pipeline's other outputs (runs/, arcgis_exports/, id_lookups/). Anchored
# to REPO_ROOT so the script works regardless of the current working directory.
DEFAULT_OUTPUT_BASE = REPO_ROOT / "data" / "outputs" / "boundary_postprocessing"

# Camden's two pieces are Leiden-split into adjacent centres. In the un-merged
# generate_networks output, they sit at generated RC_IDs 130 (north, 631 POIs)
# and 218 (south, 487 POIs). Merging them here (before RC_ID restore) re-fuses
# Camden into a single centre, matching what the published rc_id_restore_lookup
# expects (9,623 rows, with Camden as one row at stable RC_ID 130).
CAMDEN_MERGE_IDS: tuple[int, int] | None = (130, 218)

# BNG bounding box (EPSG:27700) the merge must lie inside, so a future POI-count
# reshuffle that puts unrelated centres at IDs 130/218 silently no-ops instead
# of fusing two random centres into a Frankenstein polygon. Camden is centred
# around (529000, 184000); a 5 km box gives ample slack for any future drift.
CAMDEN_EXPECTED_BBOX_27700 = (524000, 179000, 534000, 189000)  # (minx, miny, maxx, maxy)


def merge_camden(centres: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Union Camden's two Leiden-split pieces into a single row.

    Keeps the lower RC_ID, unions geometries, sums numeric columns and concats
    category_names. Deliberately minimal: no hole-filling, no LA recalculation.
    """
    if CAMDEN_MERGE_IDS is None:
        return centres
    a, b = CAMDEN_MERGE_IDS
    rows = centres[centres['RC_ID'].isin([a, b])]
    if len(rows) != 2:
        print(f"  Camden merge skipped: expected 2 rows for IDs {CAMDEN_MERGE_IDS}, found {len(rows)}")
        return centres

    # Sanity-check that both candidates actually lie inside Camden's expected
    # BNG bounding box. Without this, a future POI-rank reshuffle could put
    # unrelated centres at IDs 130/218 and we'd silently fuse them (exactly the
    # Milton-Keynes/Bexhill bug that motivated moving the merge here).
    rows_27700 = rows if rows.crs and rows.crs.to_string() == 'EPSG:27700' else rows.to_crs(27700)
    minx, miny, maxx, maxy = CAMDEN_EXPECTED_BBOX_27700
    for _, r in rows_27700.iterrows():
        b_minx, b_miny, b_maxx, b_maxy = r.geometry.bounds
        if not (minx <= b_minx and miny <= b_miny and b_maxx <= maxx and b_maxy <= maxy):
            print(
                f"  Camden merge skipped: RC_ID {int(r['RC_ID'])} bounds "
                f"({b_minx:.0f},{b_miny:.0f},{b_maxx:.0f},{b_maxy:.0f}) fall "
                f"outside CAMDEN_EXPECTED_BBOX_27700 {CAMDEN_EXPECTED_BBOX_27700}. "
                "IDs 130/218 likely no longer refer to Camden — re-confirm before re-enabling."
            )
            return centres

    keep_id = min(a, b)
    kept = rows[rows['RC_ID'] == keep_id].iloc[0].copy()
    kept['geometry'] = rows.geometry.unary_union
    for col in ['Total_POI_count', 'Retail', 'Dining and Drinking',
                'Leisure & Travel', 'Community & Health', '# H3 cells']:
        if col in rows.columns:
            kept[col] = rows[col].sum()
    if 'category_names' in rows.columns:
        kept['category_names'] = list({c for lst in rows['category_names'] if lst is not None for c in lst})

    other = centres[~centres['RC_ID'].isin([a, b])]
    merged = gpd.GeoDataFrame([kept], geometry='geometry', crs=centres.crs)
    return gpd.GeoDataFrame(pd.concat([other, merged], ignore_index=True), crs=centres.crs)\
        .sort_values('RC_ID').reset_index(drop=True)


def remap_to_legacy_ids(
    centres: gpd.GeoDataFrame,
    legacy_path: str | Path,
    bbox_tolerance_m: float = 2.0,
) -> gpd.GeoDataFrame:
    """Overwrite generated RC_IDs with legacy IDs by pairing polygons on bbox.

    Loads the legacy spolygons file (the ``_email`` file moved into data/inputs/),
    requires a 1:1 row match with ``centres``, and pairs each workshop centre to
    the legacy polygon whose bounding box matches within ``bbox_tolerance_m`` on
    every coordinate. Raises loudly on any size mismatch, unpaired centre, or
    duplicate legacy ID.
    """
    legacy_path = Path(legacy_path)
    if not legacy_path.exists():
        raise FileNotFoundError(f"Legacy RC bounds file not found: {legacy_path}")

    legacy = gpd.read_parquet(legacy_path)
    if 'RC_ID' not in legacy.columns:
        raise ValueError(f"Legacy file {legacy_path} is missing required 'RC_ID' column")

    result = centres.copy()
    if len(result) != len(legacy):
        raise ValueError(
            f"Legacy remap aborted: row count mismatch. "
            f"Workshop centres: {len(result):,}; legacy ({legacy_path.name}): {len(legacy):,}. "
            "Most likely cause: Camden not merged before remap, or a split-threshold mismatch."
        )

    # Project legacy into the workshop CRS so bbox tolerances share metres.
    if result.crs is None:
        raise ValueError("Workshop centres have no CRS; cannot compare bboxes to legacy.")
    if legacy.crs is None:
        raise ValueError(f"Legacy file {legacy_path} has no CRS; cannot compare bboxes.")
    if legacy.crs.to_string() != result.crs.to_string():
        legacy = legacy.to_crs(result.crs)

    work_bounds = result.geometry.bounds.copy()
    work_bounds['generated_RC_ID'] = result['RC_ID'].values
    legacy_bounds = legacy.geometry.bounds.copy()
    legacy_bounds['legacy_RC_ID'] = legacy['RC_ID'].values

    # Sort both by (minx, miny) and pair positionally — the bbox tolerance check
    # below catches any mispairing.
    work_sorted = work_bounds.sort_values(['minx', 'miny']).reset_index(drop=True)
    legacy_sorted = legacy_bounds.sort_values(['minx', 'miny']).reset_index(drop=True)

    diffs = (work_sorted[['minx', 'miny', 'maxx', 'maxy']].values
             - legacy_sorted[['minx', 'miny', 'maxx', 'maxy']].values)
    max_diff = abs(diffs).max(axis=1)
    failed_mask = max_diff > bbox_tolerance_m
    if failed_mask.any():
        n_failed = int(failed_mask.sum())
        sample = pd.concat(
            [
                work_sorted.loc[failed_mask, ['generated_RC_ID', 'minx', 'miny', 'maxx', 'maxy']].head(10).add_prefix('work_'),
                legacy_sorted.loc[failed_mask, ['legacy_RC_ID', 'minx', 'miny', 'maxx', 'maxy']].head(10).add_prefix('legacy_').reset_index(drop=True),
            ],
            axis=1,
        )
        raise ValueError(
            f"Legacy remap aborted: {n_failed:,} workshop centres do not pair to a "
            f"legacy polygon within {bbox_tolerance_m}m bbox tolerance.\n{sample.to_string(index=False)}"
        )

    id_map = dict(zip(work_sorted['generated_RC_ID'], legacy_sorted['legacy_RC_ID']))
    if len(set(id_map.values())) != len(id_map):
        raise ValueError("Legacy remap produced duplicate legacy IDs (pairing is not bijective).")

    print(
        f"Remapping {len(id_map):,} RC_IDs to legacy IDs from {legacy_path} "
        f"(bbox tolerance {bbox_tolerance_m}m)."
    )

    remapped = result['RC_ID'].map(id_map)
    if remapped.isna().any():
        raise ValueError("Legacy remap produced null IDs; pairing is incomplete.")
    remapped_str = remapped.astype(str)
    if remapped_str.str.fullmatch(r"\d+").all():
        result['RC_ID'] = remapped_str.astype(int)
    else:
        result['RC_ID'] = remapped_str
    if result['RC_ID'].duplicated().any():
        dups = result.loc[result['RC_ID'].duplicated(keep=False), 'RC_ID'].tolist()
        raise ValueError(f"Legacy remap produced duplicate IDs: {dups[:20]}")

    return result.sort_values('RC_ID').reset_index(drop=True)


def sanitize_column_names(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Sanitize column names for ArcGIS Online compatibility.

    Rules:
    - Must start with a letter
    - Only letters, numbers, and underscores
    - Replace all special characters and spaces with underscores
    - Max 64 characters
    """
    gdf = gdf.copy()

    rename_map = {}
    for col in gdf.columns:
        if col == 'geometry':
            continue

        # Replace special characters and spaces with underscores
        new_col = re.sub(r'[^a-zA-Z0-9_]', '_', col)

        # Remove leading/trailing spaces and underscores
        new_col = new_col.strip('_ ')

        # Ensure starts with letter
        if new_col and not new_col[0].isalpha():
            new_col = 'col_' + new_col

        # Remove consecutive underscores and clean up spaces around underscores
        new_col = re.sub(r'_+', '_', new_col)
        new_col = re.sub(r'\s+', ' ', new_col)  # Remove consecutive spaces

        # Truncate to 64 characters
        new_col = new_col[:64]

        if new_col != col:
            rename_map[col] = new_col
            print(f"  Renamed: '{col}' -> '{new_col}'")

    if rename_map:
        gdf = gdf.rename(columns=rename_map)

    return gdf


def add_split_tracking_columns(centres_split: gpd.GeoDataFrame, centres_nosplit: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Add was_split, Original_POI_count, Parent_ID columns. Keep original split RC_IDs.

    V2 ID Scheme:
    - All centres keep their original RC_ID from the split version (unique per subcentre)
    - Non-split centres (was_split == False):
      - Parent_ID = null (no parent)

    - Split centres (was_split == True):
      - Parent_ID = sequential integer starting at 1, one per unique parent centre
        (all subcentres from the same original parent share the same Parent_ID)

    Example:
      Original centre (1800 POIs) splits into 3 subcentres with RC_IDs 5, 12, 23:
        - RC_ID: 5,  Parent_ID: 1, POIs: 700
        - RC_ID: 12, Parent_ID: 1, POIs: 650
        - RC_ID: 23, Parent_ID: 1, POIs: 450

      Another original centre splits into 2 subcentres with RC_IDs 8, 15:
        - RC_ID: 8,  Parent_ID: 2, POIs: 500
        - RC_ID: 15, Parent_ID: 2, POIs: 400

      Non-split centre with RC_ID 789 stays as:
        - RC_ID: 789, Parent_ID: null
    """
    print("\nCalculating split tracking columns (V2 - keeping split IDs)...")

    # Get the POI count column name (may vary)
    poi_col = 'Total_POI_count' if 'Total_POI_count' in centres_split.columns else 'Total_Units'

    # Store original RC_ID for reference
    centres_split['original_split_RC_ID'] = centres_split['RC_ID']

    # Create representative points for split centres (guaranteed to be inside the polygon,
    # unlike centroid which can fall outside for highly concave shapes)
    split_centroids = centres_split.copy()
    split_centroids['rep_point'] = split_centroids.geometry.representative_point()
    split_centroids = split_centroids.set_geometry('rep_point')

    # Spatial join: find which nosplit centre contains each split centre's representative point
    joined = gpd.sjoin(
        split_centroids[['original_split_RC_ID', 'rep_point', poi_col]],
        centres_nosplit[['RC_ID', 'geometry', poi_col]],
        how='left',
        predicate='within'
    )

    # Rename columns for clarity
    joined = joined.rename(columns={
        'RC_ID': 'nosplit_RC_ID',
        f'{poi_col}_left': 'split_poi_count',
        f'{poi_col}_right': 'nosplit_poi_count'
    })

    # Handle cases where a split centre might match multiple nosplit centres (take first)
    joined = joined.drop_duplicates(subset=['original_split_RC_ID'], keep='first')

    # Determine was_split: True if nosplit POI count > split POI count
    joined['was_split'] = joined['nosplit_poi_count'] > joined['split_poi_count']

    # Original_POI_count: from nosplit version (or same as split if no match)
    joined['Original_POI_count'] = joined['nosplit_poi_count'].fillna(joined['split_poi_count'])

    # Merge back to original split centres
    centres_split = centres_split.merge(
        joined[['original_split_RC_ID', 'was_split', 'Original_POI_count', 'nosplit_RC_ID']],
        on='original_split_RC_ID',
        how='left'
    )

    # Fill any missing values (centres that didn't match)
    centres_split['was_split'] = centres_split['was_split'].fillna(False)
    centres_split['Original_POI_count'] = centres_split['Original_POI_count'].fillna(
        centres_split[poi_col]
    )

    # Convert to appropriate types
    centres_split['was_split'] = centres_split['was_split'].astype(bool)
    centres_split['Original_POI_count'] = centres_split['Original_POI_count'].astype(int)

    # Now assign Parent_ID for split centres only
    # Get unique nosplit_RC_IDs that have splits, and assign sequential Parent_IDs starting at 1
    split_mask = centres_split['was_split']

    # Initialize Parent_ID as None for all
    centres_split['Parent_ID'] = None

    if split_mask.any():
        # Get unique parent (nosplit) RC_IDs for split centres, sorted for consistency
        unique_parents = sorted(centres_split.loc[split_mask, 'nosplit_RC_ID'].dropna().unique())

        # Create mapping from nosplit_RC_ID to Parent_ID (starting at 1)
        parent_id_map = {nosplit_id: idx + 1 for idx, nosplit_id in enumerate(unique_parents)}

        # Assign Parent_ID to split centres
        centres_split.loc[split_mask, 'Parent_ID'] = centres_split.loc[split_mask, 'nosplit_RC_ID'].map(parent_id_map)

        # Convert to nullable integer type
        centres_split['Parent_ID'] = centres_split['Parent_ID'].astype('Int64')

    # Keep the original RC_ID from split version (don't modify it)
    centres_split['RC_ID'] = centres_split['original_split_RC_ID']

    # Clean up temporary columns
    centres_split = centres_split.drop(columns=['original_split_RC_ID', 'nosplit_RC_ID'], errors='ignore')

    # Print summary
    n_split = centres_split['was_split'].sum()
    print(f"  Centres that were split: {n_split}")
    print(f"  Centres not split: {len(centres_split) - n_split}")

    # Count how many unique parents have multiple children (actual splits)
    split_centres_only = centres_split[centres_split['was_split']]
    if len(split_centres_only) > 0:
        parent_counts = split_centres_only.groupby('Parent_ID').size()
        n_parents = len(parent_counts)
        print(f"  Original centres that were split: {n_parents}")
        print(f"  Parent_ID range: 1 to {n_parents}")

        # Show example of ID scheme
        example_parent = parent_counts.idxmax()
        examples = centres_split[centres_split['Parent_ID'] == example_parent][['RC_ID', 'Parent_ID', poi_col]].head(3)
        print(f"  Example (Parent_ID {example_parent}):")
        for _, row in examples.iterrows():
            print(f"    RC_ID: {row['RC_ID']}, Parent_ID: {row['Parent_ID']}, POIs: {row[poi_col]}")

    return centres_split


def apply_legacy_ids(centres: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Merge Camden + remap workshop split-centre RC_IDs onto legacy IDs."""
    print("\nApplying legacy RC_IDs to split workshop centres...")

    original_crs = centres.crs
    centres_for_check = centres
    if original_crs is not None and original_crs.to_string() != "EPSG:27700":
        centres_for_check = centres.to_crs("EPSG:27700")

    # Merge Camden's two Leiden-split pieces BEFORE the remap so the row count
    # matches the legacy file (which has Camden as a single row). merge_camden
    # is guarded by a bbox check so it no-ops if 130/218 ever stop being Camden.
    centres_for_check = merge_camden(centres_for_check)

    remapped = remap_to_legacy_ids(
        centres_for_check,
        LEGACY_RC_BOUNDS_PATH,
        bbox_tolerance_m=RC_ID_RESTORE_BBOX_TOLERANCE_M,
    )

    if original_crs is not None and remapped.crs != original_crs:
        remapped = remapped.to_crs(original_crs)

    return remapped


def create_workshop_centres(
    split_centres_path: str,
    nosplit_centres_path: str,
    output_dir: str | Path = DEFAULT_OUTPUT_BASE,
    legacy_ids: bool = False,
):
    """Create 4 variants of postworkshopcentres GPKG files."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading centre files...")
    # Load centres with splits (splitthresh_1500)
    centres_split = gpd.read_parquet(split_centres_path)
    print(f"  Loaded {len(centres_split)} centres with splits")
    if legacy_ids:
        centres_split = apply_legacy_ids(centres_split)

    # Load centres without splits (splitthresh_99999)
    centres_nosplit = gpd.read_parquet(nosplit_centres_path)
    print(f"  Loaded {len(centres_nosplit)} centres without splits")

    # Add split tracking columns (was_split, Original_POI_count, Parent_ID)
    centres_split = add_split_tracking_columns(centres_split, centres_nosplit)

    # Sanitize column names for ArcGIS compatibility
    print("\nSanitizing column names for ArcGIS Online...")
    centres_split = sanitize_column_names(centres_split)
    centres_nosplit = sanitize_column_names(centres_nosplit)

    # Reproject to WGS84 for ArcGIS Online compatibility (no client-side datum
    # transformation needed; sidesteps OSGB36/OSTN15 issues for NI features).
    centres_split = centres_split.to_crs("EPSG:4326")
    centres_nosplit = centres_nosplit.to_crs("EPSG:4326")

    # 1. postworkshopcentres.gpkg - with splits, with category_names
    print("\n1. Creating postworkshopcentres.gpkg (with splits, with category_names)...")
    centres_split.to_file(
        output_dir / "postworkshopcentres.gpkg",
        driver="GPKG",
        layer="postworkshopcentres"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres.gpkg'}")

    # 2. postworkshopcentres_nocatnames.gpkg - with splits, without category_names
    print("\n2. Creating postworkshopcentres_nocatnames.gpkg (with splits, no category_names)...")
    centres_split_nocat = centres_split.copy()
    if 'category_names' in centres_split_nocat.columns:
        centres_split_nocat = centres_split_nocat.drop(columns=['category_names'])
    centres_split_nocat.to_file(
        output_dir / "postworkshopcentres_nocatnames.gpkg",
        driver="GPKG",
        layer="postworkshopcentres_nocatnames"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres_nocatnames.gpkg'}")

    # 3. postworkshopcentres_nosplits.gpkg - without splits, with category_names
    print("\n3. Creating postworkshopcentres_nosplits.gpkg (no splits, with category_names)...")
    centres_nosplit.to_file(
        output_dir / "postworkshopcentres_nosplits.gpkg",
        driver="GPKG",
        layer="postworkshopcentres_nosplits"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres_nosplits.gpkg'}")

    # 4. postworkshopcentres_nosplits_nocatnames.gpkg - without splits, without category_names
    print("\n4. Creating postworkshopcentres_nosplits_nocatnames.gpkg (no splits, no category_names)...")
    centres_nosplit_nocat = centres_nosplit.copy()
    if 'category_names' in centres_nosplit_nocat.columns:
        centres_nosplit_nocat = centres_nosplit_nocat.drop(columns=['category_names'])
    centres_nosplit_nocat.to_file(
        output_dir / "postworkshopcentres_nosplits_nocatnames.gpkg",
        driver="GPKG",
        layer="postworkshopcentres_nosplits_nocatnames"
    )
    print(f"   Saved to {output_dir / 'postworkshopcentres_nosplits_nocatnames.gpkg'}")

    print("\nAll postworkshopcentres GPKG files created successfully!")


def create_filtered_pois(poi_path: str, output_dir: str | Path = DEFAULT_OUTPUT_BASE):
    """Create filtered POI geopackage with just name and full category."""
    import pandas as pd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating filtered POI geopackage...")
    print(f"Loading POIs from {poi_path}...")

    # Try geopandas first, fall back to pandas if no geo metadata
    try:
        pois = gpd.read_parquet(poi_path)
    except ValueError:
        # Not a geoparquet, read with pandas and convert
        from shapely.geometry import Point
        pois_df = pd.read_parquet(poi_path)

        if 'geometry' in pois_df.columns:
            # Convert WKB to shapely geometry if needed
            from shapely import wkb
            pois_df['geometry'] = pois_df['geometry'].apply(lambda x: wkb.loads(bytes(x)) if x is not None else None)
            pois = gpd.GeoDataFrame(pois_df, geometry='geometry', crs='EPSG:4326')
        elif 'lat' in pois_df.columns and 'lng' in pois_df.columns:
            # Create geometry from lat/lng columns
            print("  Creating geometry from lat/lng columns...")
            geometry = [Point(lng, lat) for lng, lat in zip(pois_df['lng'], pois_df['lat'])]
            pois = gpd.GeoDataFrame(pois_df, geometry=geometry, crs='EPSG:4326')
        else:
            raise ValueError("POI file must have either a 'geometry' column or 'lat' and 'lng' columns")

    print(f"  Loaded {len(pois):,} POIs")

    # Keep only name and category columns
    columns_to_keep = ['name', 'geometry']

    # Determine which category column exists
    if 'fsq_category_labels' in pois.columns:
        columns_to_keep.append('fsq_category_labels')
        category_col = 'fsq_category_labels'
    elif 'fsq_category_ids' in pois.columns:
        columns_to_keep.append('fsq_category_ids')
        category_col = 'fsq_category_ids'
    elif 'fsq_category_id' in pois.columns:
        columns_to_keep.append('fsq_category_id')
        category_col = 'fsq_category_id'
    else:
        print("  Warning: No category column found, saving with name only")
        category_col = None

    # Select columns
    filtered_pois = pois[[col for col in columns_to_keep if col in pois.columns]].copy()

    # Rename category column to 'category'
    if category_col:
        filtered_pois = filtered_pois.rename(columns={category_col: 'category'})

    # Sanitize column names
    filtered_pois = sanitize_column_names(filtered_pois)

    print(f"  Filtered to {len(filtered_pois)} POIs with columns: {list(filtered_pois.columns)}")

    # Save to GPKG (WGS84 for AGOL compatibility)
    output_path = output_dir / "filtered_pois.gpkg"
    filtered_pois.to_crs("EPSG:4326").to_file(output_path, driver="GPKG", layer="filtered_pois")
    print(f"  Saved to {output_path}")

    print("\nFiltered POI geopackage created successfully!")


def create_retail_parks_gpkg(retail_parks_path: str, output_dir: str | Path = DEFAULT_OUTPUT_BASE):
    """Create retail parks geopackage with all attributes."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating retail parks geopackage...")
    print(f"Loading retail parks from {retail_parks_path}...")
    retail_parks = gpd.read_parquet(retail_parks_path)
    print(f"  Loaded {len(retail_parks)} retail parks")

    # Sanitize column names for ArcGIS compatibility
    print("  Sanitizing column names for ArcGIS Online...")
    retail_parks = sanitize_column_names(retail_parks)

    # Save to GPKG (WGS84 for AGOL compatibility)
    output_path = output_dir / "retail_parks.gpkg"
    retail_parks.to_crs("EPSG:4326").to_file(output_path, driver="GPKG", layer="retail_parks")
    print(f"  Saved to {output_path}")
    print(f"  Columns: {list(retail_parks.columns)}")

    print("\nRetail parks geopackage created successfully!")


def create_centres_clean(
    split_centres_path: str,
    nosplit_centres_path: str,
    output_dir: str | Path = DEFAULT_OUTPUT_BASE,
    legacy_ids: bool = False,
):
    """Create clean centres GPKG with only RC_ID and category totals."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating centres_clean.gpkg...")
    print(f"Loading centres from {split_centres_path}...")
    centres = gpd.read_parquet(split_centres_path)
    print(f"  Loaded {len(centres)} centres")
    if legacy_ids:
        centres = apply_legacy_ids(centres)

    # Load nosplit centres for split tracking calculation
    centres_nosplit = gpd.read_parquet(nosplit_centres_path)

    # Add split tracking columns
    centres = add_split_tracking_columns(centres, centres_nosplit)

    # Map potential column name variations to desired output names
    column_mapping = {
        'Total Units': 'Total Units',
        'total_units': 'Total Units',
        'poi_count': 'Total Units',
        'Total_POI_count': 'Total Units',
        'Retail (total)': 'Retail (total)',
        'retail_total': 'Retail (total)',
        'Retail': 'Retail (total)',
        'Dining and Drinking (total)': 'Dining and Drinking (total)',
        'dining_drinking_total': 'Dining and Drinking (total)',
        'Dining and Drinking': 'Dining and Drinking (total)',
        'Leisure and Travel (total)': 'Leisure and Travel (total)',
        'leisure_travel_total': 'Leisure and Travel (total)',
        'Leisure & Travel': 'Leisure and Travel (total)',
        'Community and Health (total)': 'Community and Health (total)',
        'community_health_total': 'Community and Health (total)',
        'Community & Health': 'Community and Health (total)',
        'centre_type': 'Is Retail Park',
        'was_split': 'Was Split',
        'Original_POI_count': 'Original POI Count',
        'Parent_ID': 'Parent ID',
    }

    # Find which columns exist and build the clean dataframe
    cols_to_keep = ['RC_ID', 'geometry']
    rename_dict = {}

    for possible_col, standard_col in column_mapping.items():
        if possible_col in centres.columns:
            cols_to_keep.append(possible_col)
            if possible_col != standard_col:
                rename_dict[possible_col] = standard_col

    # Filter to just these columns
    centres_clean = centres[cols_to_keep].copy()

    # Rename to standard names
    if rename_dict:
        centres_clean = centres_clean.rename(columns=rename_dict)

    # Convert Is Retail Park to boolean: retail_park -> True, centre -> False
    if 'Is Retail Park' in centres_clean.columns:
        centres_clean['Is Retail Park'] = centres_clean['Is Retail Park'].map({
            'retail_park': True,
            'centre': False
        }).fillna(False)

    # Sanitize column names for ArcGIS
    centres_clean = sanitize_column_names(centres_clean)

    # Save to GPKG (WGS84 for AGOL compatibility)
    output_path = output_dir / "centres_clean.gpkg"
    centres_clean.to_crs("EPSG:4326").to_file(output_path, driver="GPKG", layer="centres_clean")
    print(f"  Saved to {output_path}")
    print(f"  Columns: {list(centres_clean.columns)}")

    print("\nCentres clean geopackage created successfully!")


def create_retail_parks_clean(
    retail_parks_path: str,
    output_dir: str | Path = DEFAULT_OUTPUT_BASE
):
    """Create clean retail parks GPKG with name, ID, total POIs, matched brands, and match percentage."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nCreating retail_parks_clean.gpkg...")
    print(f"Loading retail parks from {retail_parks_path}...")
    retail_parks = gpd.read_parquet(retail_parks_path)
    print(f"  Loaded {len(retail_parks)} retail parks")

    # Map potential column name variations to desired output names
    column_mapping = {
        'name': 'Name',
        'Name': 'Name',
        'park_name': 'Name',
        'RC_ID': 'RC_ID',
        'id': 'RC_ID',
        'park_id': 'RC_ID',
        'centre_poi_total': 'Total POIs',
        'total_pois': 'Total POIs',
        'poi_count': 'Total POIs',
        'Total_POI_count': 'Total POIs',
        'matched_brand_list': 'Matched Brands',
        'matched_brands': 'Matched Brands',
        'Matched Brands': 'Matched Brands',
        'matched_pois': 'Matched Brands'
    }

    # Find which columns exist
    cols_to_keep = ['geometry']
    rename_dict = {}

    for possible_col, standard_col in column_mapping.items():
        if possible_col in retail_parks.columns:
            if possible_col not in cols_to_keep:
                cols_to_keep.append(possible_col)
            if possible_col != standard_col:
                rename_dict[possible_col] = standard_col

    # Also keep matched_to_centre_ratio for calculation
    if 'matched_to_centre_ratio' in retail_parks.columns:
        cols_to_keep.append('matched_to_centre_ratio')

    # Filter to just these columns
    retail_parks_clean = retail_parks[cols_to_keep].copy()

    # Calculate percentage column (ratio * 100, rounded to 1 decimal place)
    if 'matched_to_centre_ratio' in retail_parks_clean.columns:
        retail_parks_clean['Match Percentage'] = (retail_parks_clean['matched_to_centre_ratio'] * 100).round(1)
        retail_parks_clean = retail_parks_clean.drop(columns=['matched_to_centre_ratio'])

    # Rename to standard names
    if rename_dict:
        retail_parks_clean = retail_parks_clean.rename(columns=rename_dict)

    # Clean up Matched Brands column - remove "(X POIs)" text
    if 'Matched Brands' in retail_parks_clean.columns:
        import numpy as np

        def clean_brands(x):
            if x is None:
                return None
            # If it's a list or numpy array, clean each element
            if isinstance(x, (list, np.ndarray)):
                cleaned = [re.sub(r'\s*\(\d+\s+POIs?\)', '', str(brand)).strip() for brand in x]
                return ', '.join(cleaned)
            # If it's a string, clean it
            return re.sub(r'\s*\(\d+\s+POIs?\)', '', str(x)).strip()

        retail_parks_clean['Matched Brands'] = retail_parks_clean['Matched Brands'].apply(clean_brands)

    # Sanitize column names for ArcGIS
    retail_parks_clean = sanitize_column_names(retail_parks_clean)

    # Save to GPKG (WGS84 for AGOL compatibility)
    output_path = output_dir / "retail_parks_clean.gpkg"
    retail_parks_clean.to_crs("EPSG:4326").to_file(output_path, driver="GPKG", layer="retail_parks_clean")
    print(f"  Saved to {output_path}")
    print(f"  Columns: {list(retail_parks_clean.columns)}")

    print("\nRetail parks clean geopackage created successfully!")


def auto_find_files(run_dir: Path):
    """
    Automatically find all necessary files from a run directory.

    Args:
        run_dir: Path to the run directory

    Returns:
        Dictionary with paths to: split_centres, nosplit_centres, pois, retail_parks
    """
    run_dir = Path(run_dir)

    if not run_dir.exists():
        raise ValueError(f"Run directory does not exist: {run_dir}")

    print(f"\nAuto-detecting files in: {run_dir}")
    print("=" * 80)

    # Find POI file (foursquare_filtered.parquet or similar)
    poi_candidates = list(run_dir.glob("*filtered*.parquet"))
    if not poi_candidates:
        raise ValueError(f"No filtered POI file found in {run_dir}")
    pois_path = poi_candidates[0]
    print(f"✓ POIs: {pois_path.name}")

    # Find split centres directory (splitthresh_1500)
    split_dirs = list(run_dir.glob("*splitthresh_1500*"))
    if not split_dirs:
        raise ValueError(f"No split centres directory (splitthresh_1500) found in {run_dir}")
    split_centres_path = split_dirs[0] / "4_finalcentres_las.parquet"
    if not split_centres_path.exists():
        raise ValueError(f"4_finalcentres_las.parquet not found in {split_dirs[0]}")
    print(f"✓ Split centres: {split_dirs[0].name}/4_finalcentres_las.parquet")

    # Find nosplit centres directory (splitthresh_99999 or splitthresh_9999999)
    nosplit_dirs = list(run_dir.glob("*splitthresh_9999*"))
    if not nosplit_dirs:
        raise ValueError(f"No nosplit centres directory (splitthresh_9999*) found in {run_dir}")
    nosplit_centres_path = nosplit_dirs[0] / "4_finalcentres_las.parquet"
    if not nosplit_centres_path.exists():
        raise ValueError(f"4_finalcentres_las.parquet not found in {nosplit_dirs[0]}")
    print(f"✓ Nosplit centres: {nosplit_dirs[0].name}/4_finalcentres_las.parquet")

    # Find retail parks (optional)
    retail_parks_path = None
    retail_parks_dir = run_dir / "retail_parks"
    if retail_parks_dir.exists():
        # Look for the merged_filtered version first, then merged, then regular
        retail_park_candidates = [
            retail_parks_dir / "retail_parks_polygons_merged_filtered.parquet",
            retail_parks_dir / "retail_parks_polygons_merged.parquet",
            retail_parks_dir / "retail_parks_polygons.parquet"
        ]
        for candidate in retail_park_candidates:
            if candidate.exists():
                retail_parks_path = candidate
                print(f"✓ Retail parks: retail_parks/{candidate.name}")
                break

    if not retail_parks_path:
        print("  (No retail parks found)")

    print("=" * 80 + "\n")

    return {
        "split_centres": str(split_centres_path),
        "nosplit_centres": str(nosplit_centres_path),
        "pois": str(pois_path),
        "retail_parks": str(retail_parks_path) if retail_parks_path else None
    }


if __name__ == "__main__":
    # Create timestamped output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output_dir = DEFAULT_OUTPUT_BASE / timestamp

    parser = argparse.ArgumentParser(
        description="Boundary post-processing: build final bounds GPKGs (split IDs with Parent_ID), ready for classification"
    )

    # New simplified interface - just provide run directory
    parser.add_argument(
        "--run-dir",
        help="Path to run directory (e.g., data/outputs/runs/final). Auto-detects all files."
    )

    # Original interface - provide individual files (backward compatible)
    parser.add_argument(
        "--split-centres",
        help="Path to 4_finalcentres_las.parquet with splits (splitthresh_1500)"
    )
    parser.add_argument(
        "--nosplit-centres",
        help="Path to 4_finalcentres_las.parquet without splits (splitthresh_99999)"
    )
    parser.add_argument(
        "--pois",
        help="Path to filtered POI geoparquet file"
    )
    parser.add_argument(
        "--retail-parks",
        required=False,
        help="Path to retail_parks_polygons.parquet (optional)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: timestamped folder in data/outputs/boundary_postprocessing)"
    )
    parser.add_argument(
        "--legacy-ids",
        action="store_true",
        help=(
            "Remap workshop split-centre RC_IDs to the legacy IDs in "
            "data/inputs/legacy_rc_bounds.parquet. Requires the workshop polygons "
            "to match the legacy polygons within a 2 m bbox tolerance "
            "(Camden's two Leiden-split pieces are auto-merged first)."
        ),
    )

    args = parser.parse_args()

    # Determine which mode to use
    if args.run_dir:
        # Auto-detect mode
        files = auto_find_files(args.run_dir)
        split_centres = files["split_centres"]
        nosplit_centres = files["nosplit_centres"]
        pois = files["pois"]
        retail_parks = files["retail_parks"]
    elif args.split_centres and args.nosplit_centres and args.pois:
        # Manual mode
        split_centres = args.split_centres
        nosplit_centres = args.nosplit_centres
        pois = args.pois
        retail_parks = args.retail_parks
    else:
        parser.error("Either --run-dir OR (--split-centres AND --nosplit-centres AND --pois) must be provided")

    # Use custom output dir if provided, otherwise use timestamped folder
    output_dir = args.output_dir if args.output_dir else str(default_output_dir)

    print("\n" + "="*80)
    print(f"Output directory: {output_dir}")
    print("="*80 + "\n")

    # Create workshopcentres files
    create_workshop_centres(
        split_centres,
        nosplit_centres,
        output_dir,
        legacy_ids=args.legacy_ids,
    )

    # Create filtered POI file
    create_filtered_pois(pois, output_dir)

    # Create retail parks file (if provided)
    if retail_parks:
        create_retail_parks_gpkg(retail_parks, output_dir)

    # Create clean centres file (with only RC_ID and category totals)
    create_centres_clean(split_centres, nosplit_centres, output_dir, legacy_ids=args.legacy_ids)

    # Create clean retail parks file (if provided)
    if retail_parks:
        create_retail_parks_clean(retail_parks, output_dir)

    print("\n" + "="*80)
    print("ALL FILES CREATED SUCCESSFULLY!")
    print(f"Output directory: {output_dir}")
    print("="*80)
