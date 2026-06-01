import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from retail.centre_postprocessing import merge_centres


def _make_centres():
    """Create a simple test GeoDataFrame with 4 centres."""
    return gpd.GeoDataFrame(
        {
            'RC_ID': [1, 2, 3, 4],
            'Total_POI_count': [100, 50, 30, 20],
            'foursquare_count': [80, 40, 25, 15],
            'Retail': [50, 20, 10, 8],
            'Dining and Drinking': [20, 15, 10, 5],
            'Leisure & Travel': [5, 3, 3, 1],
            'Community & Health': [5, 2, 2, 1],
            '# H3 cells': [10, 5, 3, 2],
            'category_names': [['shop', 'cafe'], ['pub', 'shop'], ['bakery'], ['gym']],
            'level2_categories': [['cat_a'], ['cat_b'], ['cat_a', 'cat_c'], ['cat_d']],
            'centre_type': ['centre', 'centre', 'centre', 'centre'],
        },
        geometry=[
            box(0, 0, 1, 1),
            box(1, 0, 2, 1),
            box(5, 5, 6, 6),
            box(10, 10, 11, 11),
        ],
        crs='EPSG:27700',
    )


def test_merge_sums_numeric_columns():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2]])

    assert len(merged) == 3  # 4 centres - 2 merged + 1 new = 3

    row = merged[merged['RC_ID'] == 1].iloc[0]
    assert row['Total_POI_count'] == 150
    assert row['foursquare_count'] == 120
    assert row['Retail'] == 70
    assert row['Dining and Drinking'] == 35
    assert row['# H3 cells'] == 15


def test_merge_unions_geometry():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2]])

    row = merged[merged['RC_ID'] == 1].iloc[0]
    expected_area = box(0, 0, 2, 1).area
    assert abs(row.geometry.area - expected_area) < 1e-6


def test_merge_deduplicates_list_columns():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2]])

    row = merged[merged['RC_ID'] == 1].iloc[0]
    assert set(row['category_names']) == {'shop', 'cafe', 'pub'}
    assert set(row['level2_categories']) == {'cat_a', 'cat_b'}


def test_merge_keeps_lowest_rc_id():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[2, 3]])

    assert 2 in merged['RC_ID'].values
    assert 3 not in merged['RC_ID'].values


def test_other_centres_unchanged():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2]])

    # Centre 3 and 4 should be completely unchanged
    for rc_id in [3, 4]:
        orig = centres[centres['RC_ID'] == rc_id].iloc[0]
        new = merged[merged['RC_ID'] == rc_id].iloc[0]
        assert orig['Total_POI_count'] == new['Total_POI_count']
        assert orig['Retail'] == new['Retail']
        assert orig.geometry.equals(new.geometry)


def test_merge_multiple_groups():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2], [3, 4]])

    assert len(merged) == 2
    assert set(merged['RC_ID'].values) == {1, 3}

    row1 = merged[merged['RC_ID'] == 1].iloc[0]
    assert row1['Total_POI_count'] == 150

    row3 = merged[merged['RC_ID'] == 3].iloc[0]
    assert row3['Total_POI_count'] == 50


def test_merge_three_centres():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2, 3]])

    assert len(merged) == 2
    row = merged[merged['RC_ID'] == 1].iloc[0]
    assert row['Total_POI_count'] == 180
    assert row['# H3 cells'] == 18


def test_merge_missing_rc_id_warns(capsys):
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 999]])

    captured = capsys.readouterr()
    assert 'Warning' in captured.out
    # Should not merge since only 1 valid ID found
    assert len(merged) == 4


def test_merge_sorted_by_rc_id():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 4]])

    assert list(merged['RC_ID'].values) == sorted(merged['RC_ID'].values)


def test_merge_empty_group_skipped():
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1]])

    assert len(merged) == 4  # Nothing changed


def test_merge_no_la_cols():
    """Works fine when LA columns are not present (4_finalcentres.parquet case)."""
    centres = _make_centres()
    merged = merge_centres(centres, merge_groups=[[1, 2]])

    assert len(merged) == 3
    assert 'LocalAuthorityNM_1' not in merged.columns
