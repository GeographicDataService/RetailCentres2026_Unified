import pandas as pd
import geopandas as gpd
import numpy as np
from itertools import chain
from pathlib import Path
from shapely.ops import unary_union

from utils.utils import fill_holes


def merge_centres(
    centres: gpd.GeoDataFrame,
    merge_groups: list[list[int]],
) -> gpd.GeoDataFrame:
    """
    Merge specified retail centres together in post-processing.

    For each merge group, unions geometries, sums numeric columns, merges list
    columns, and keeps the lowest RC_ID. Other centres are left unchanged (no
    re-ranking), so RC_IDs remain stable with gaps where merged centres were removed.

    Args:
        centres: GeoDataFrame with RC_ID, geometry, and standard centre columns.
        merge_groups: Lists of RC_IDs to merge, e.g. [[5, 42], [100, 101, 103]].

    Returns:
        New GeoDataFrame with merged centres. LA columns are re-derived for
        merged centres only.
    """
    result = centres.copy()

    sum_cols = [
        'Total_POI_count', 'foursquare_count', 'Retail', 'Dining and Drinking',
        'Leisure & Travel', 'Community & Health', '# H3 cells',
    ]
    list_cols = ['level2_categories', 'category_names']

    la_cols = ['LocalAuthorityNM_1', 'LocalAuthorityNM_2', 'LocalAuthorityNM_3']
    has_la_cols = all(col in result.columns for col in la_cols)

    for group in merge_groups:
        if len(group) < 2:
            continue

        mask = result['RC_ID'].isin(group)
        group_rows = result[mask]

        if len(group_rows) == 0:
            print(f"Warning: no centres found for merge group {group}, skipping")
            continue

        missing = set(group) - set(group_rows['RC_ID'].values)
        if missing:
            print(f"Warning: RC_IDs {missing} not found, merging remaining {list(group_rows['RC_ID'].values)}")

        if len(group_rows) < 2:
            continue

        # Build merged row from the row with the lowest RC_ID
        keep_id = group_rows['RC_ID'].min()
        merged_row = group_rows[group_rows['RC_ID'] == keep_id].iloc[0].copy()

        # Union geometry and fill holes
        merged_geom = unary_union(group_rows.geometry.values)
        merged_row['geometry'] = fill_holes(merged_geom)

        # Sum numeric columns
        for col in sum_cols:
            if col in group_rows.columns:
                merged_row[col] = group_rows[col].sum()

        # Merge list columns (deduplicated union)
        for col in list_cols:
            if col in group_rows.columns:
                all_vals = [v for v in group_rows[col] if v is not None]
                merged_row[col] = list(set(chain.from_iterable(all_vals)))

        # Drop all group rows, insert merged row
        result = result[~mask]
        merged_df = gpd.GeoDataFrame([merged_row], geometry='geometry', crs=result.crs)
        result = gpd.GeoDataFrame(
            pd.concat([result, merged_df], ignore_index=True),
            geometry='geometry', crs=result.crs,
        )

    # Re-derive LA columns for merged centres only
    if has_la_cols:
        merged_ids = {min(g) for g in merge_groups if len(g) >= 2}
        existing_ids = set(result['RC_ID'].values)
        merged_ids = merged_ids & existing_ids

        if merged_ids:
            # Drop old LA cols from merged rows
            non_merged = result[~result['RC_ID'].isin(merged_ids)]
            merged_only = result[result['RC_ID'].isin(merged_ids)].drop(
                columns=[c for c in la_cols if c in result.columns]
            )
            # Re-run LA assignment on just the merged centres
            merged_with_la = add_localauthorities_to_centres(merged_only)
            result = gpd.GeoDataFrame(
                pd.concat([non_merged, merged_with_la], ignore_index=True),
                geometry='geometry', crs=centres.crs,
            )

    result = result.sort_values('RC_ID').reset_index(drop=True)
    return result


def restore_stable_rc_ids(
    centres: gpd.GeoDataFrame,
    lookup_path: str | Path,
    bbox_tolerance_m: float = 2.0,
) -> gpd.GeoDataFrame:
    """
    Restore stable published RC_IDs from a generated-ID lookup.

    The lookup maps the freshly generated deterministic RC_ID to the stable RC_ID
    from the email boundary file. Before overwriting IDs, this checks that the
    generated geometry bounds still match the bounds captured in the lookup.
    If they do not, the run fails because downstream manual ID references may no
    longer be valid.
    """
    lookup_path = Path(lookup_path)
    if not lookup_path.exists():
        raise FileNotFoundError(f"RC_ID restore lookup not found: {lookup_path}")

    lookup = pd.read_parquet(lookup_path)
    required_cols = {
        'generated_RC_ID',
        'stable_RC_ID',
        'expected_generated_minx',
        'expected_generated_miny',
        'expected_generated_maxx',
        'expected_generated_maxy',
    }
    missing_cols = required_cols - set(lookup.columns)
    if missing_cols:
        raise ValueError(
            f"RC_ID restore lookup is missing required columns: {sorted(missing_cols)}"
        )

    result = centres.copy()
    generated_ids = set(result['RC_ID'].astype(int))
    lookup_ids = set(lookup['generated_RC_ID'].astype(int))
    missing = sorted(generated_ids - lookup_ids)
    extra = sorted(lookup_ids - generated_ids)
    if missing or extra:
        raise ValueError(
            "RC_ID restore lookup does not match generated centres. "
            f"Missing generated IDs in lookup: {missing[:20]}; "
            f"extra lookup IDs: {extra[:20]}."
        )

    bounds = result.geometry.bounds.rename(
        columns={
            'minx': 'actual_minx',
            'miny': 'actual_miny',
            'maxx': 'actual_maxx',
            'maxy': 'actual_maxy',
        }
    )
    check = pd.concat(
        [result[['RC_ID']].astype({'RC_ID': int}).reset_index(drop=True), bounds.reset_index(drop=True)],
        axis=1,
    ).merge(
        lookup[
            [
                'generated_RC_ID',
                'stable_RC_ID',
                'expected_generated_minx',
                'expected_generated_miny',
                'expected_generated_maxx',
                'expected_generated_maxy',
            ]
        ],
        left_on='RC_ID',
        right_on='generated_RC_ID',
        how='left',
    )

    for actual, expected in [
        ('actual_minx', 'expected_generated_minx'),
        ('actual_miny', 'expected_generated_miny'),
        ('actual_maxx', 'expected_generated_maxx'),
        ('actual_maxy', 'expected_generated_maxy'),
    ]:
        check[f'{actual}_diff'] = (check[actual] - check[expected]).abs()

    diff_cols = [c for c in check.columns if c.endswith('_diff')]
    failed = check[check[diff_cols].max(axis=1) > bbox_tolerance_m].copy()
    if not failed.empty:
        sample_cols = [
            'generated_RC_ID',
            'stable_RC_ID',
            'actual_minx',
            'actual_miny',
            'actual_maxx',
            'actual_maxy',
            'expected_generated_minx',
            'expected_generated_miny',
            'expected_generated_maxx',
            'expected_generated_maxy',
        ] + diff_cols
        raise ValueError(
            "RC_ID restore aborted: generated centre bounding boxes differ from "
            f"the lookup by more than {bbox_tolerance_m}m. This means IDs may no "
            "longer refer to the same geometries; downstream manual references "
            "could be affected.\n"
            + failed[sample_cols].head(20).to_string(index=False)
        )

    id_map = dict(
        zip(lookup['generated_RC_ID'].astype(int), lookup['stable_RC_ID'].astype(str))
    )
    changed = sum(str(k) != v for k, v in id_map.items())
    print(
        "WARNING: Restoring stable RC_IDs from "
        f"{lookup_path}. Overwriting {changed:,} generated IDs. "
        "If the restore lookup is stale, downstream manual ID references may be wrong."
    )

    restored_ids = result['RC_ID'].astype(int).map(id_map)
    if restored_ids.isna().any():
        raise ValueError("RC_ID restore produced null IDs; lookup is incomplete.")

    if restored_ids.str.fullmatch(r"\d+").all():
        result['RC_ID'] = restored_ids.astype(int)
    else:
        result['RC_ID'] = restored_ids

    if result['RC_ID'].duplicated().any():
        duplicates = result.loc[result['RC_ID'].duplicated(keep=False), 'RC_ID'].tolist()
        raise ValueError(f"RC_ID restore produced duplicate IDs: {duplicates[:20]}")

    return result.sort_values('RC_ID').reset_index(drop=True)


def add_localauthorities_to_centres(retail_centres: gpd.GeoDataFrame):
    """
    Adds local authority information to retail centres.
    Handles cases where a retail centre intersects with multiple LAs.
    """

    # Load Local Authority boundaries and set CRS
    UK_LAD = gpd.read_file("data/inputs/boundaries/Local_Authority_Districts_December_2022_UK_BGC_V2_5759908710055972638.gpkg")[['LAD22CD', 'LAD22NM', 'geometry']]
    UK_LAD['LocalAuthorityTY'] = UK_LAD['LAD22CD'].map(lambda x: {
        'E0': 'LAD22CD',
        'W06': 'LAD22CD',
        'S12': 'CouncilArea20CD',
        'N09': 'LGD14CD'
    }.get(x[:3], None))
    UK_LAD = UK_LAD.to_crs(retail_centres.crs)

    # Spatial intersection and area computation
    RC_int = gpd.overlay(retail_centres, UK_LAD, how='intersection')[['RC_ID', 'LAD22CD', 'LAD22NM', 'geometry']]
    RC_int = RC_int.assign(area_km2=RC_int.geometry.area * 1e-6)

    # Count number of LA overlaps per centre
    area_stats = RC_int.groupby('RC_ID')['area_km2'].agg(['count', 'sum']).rename(columns={'count': 'N', 'sum': 'Tarea'}).reset_index()
    RC_int = RC_int.merge(area_stats, on='RC_ID')
    RC_int['Prop'] = RC_int['area_km2'] / RC_int['Tarea']

    # Keep only significant overlaps (>10%)
    RC_filtered = RC_int[RC_int['Prop'] > 0.1].copy()

    # Sort and keep top 3 overlaps per centre
    RC_filtered = RC_filtered.sort_values(['RC_ID', 'Prop'], ascending=[True, False])
    RC_filtered['Number'] = RC_filtered.groupby('RC_ID').cumcount() + 1
    RC_filtered = RC_filtered[RC_filtered['Number'] <= 3]

    # Pivot to wide format
    pivoted = RC_filtered.pivot(index='RC_ID', columns='Number', values=['LAD22CD', 'LAD22NM', 'Prop'])
    pivoted.columns = [f'{a}_{b}' for a, b in pivoted.columns]
    pivoted = pivoted.reset_index()

    rename_cols = {}
    for i in range(1, 4):
        rename_cols[f'LAD22CD_{i}'] = f'LocalAuthorityCD_{i}'
        rename_cols[f'LAD22NM_{i}'] = f'LocalAuthorityNM_{i}'
        rename_cols[f'Prop_{i}'] = f'LocalAuthority_{i}_Prop'

    pivoted = pivoted.rename(columns=rename_cols)

    # Merge authority type
    auth_type = UK_LAD[['LAD22CD', 'LocalAuthorityTY']].drop_duplicates()
    pivoted = pivoted.merge(auth_type, left_on='LocalAuthorityCD_1', right_on='LAD22CD', how='left').drop(columns='LAD22CD')

    # Reorder final columns
    final_cols = ['RC_ID', 'LocalAuthorityNM_1','LocalAuthorityNM_2', 'LocalAuthorityNM_3']
    for col in final_cols:
        if col not in pivoted.columns:
            pivoted[col] = np.nan
    pivoted = pivoted[final_cols]

    # Merge back into retail_centres
    return retail_centres.merge(pivoted, on='RC_ID', how='left')

