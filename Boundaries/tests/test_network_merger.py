import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import polars as pl
from retail.network_merger import merge_networks_separated_by_one_cell
from retail.network_merger import _find_overlapping_networks_and_overlap
from polars.testing import assert_frame_equal


#8b2b996b26f2fff, 8b2b996b26f0fff, 8b2b996b26f3fff, 8b2b996b26e6fff, 8b2b996b2653fff


def test_merge_networks_separated_by_one_cell():
    # Sample data
    data = pl.DataFrame({
        "h3_11": ["8b2b996b26f2fff", "8b2b996b26f0fff", "8b2b996b26f3fff", "8b2b996b26e6fff", "8b2b996b2653fff"],

        "network_number": [1, 1, 1, 2, 3]
    })

    # Expected result
    expected_data = pl.DataFrame({
        "h3_11": ["8b2b996b26f2fff", "8b2b996b26f0fff", "8b2b996b26f3fff", "8b2b996b26e6fff", "8b2b996b2653fff","8b2b996b26f5fff"], #cell added in between
        "network_number": [1, 1, 1, 1, 3, 1]
    })

    # Call the functiont
    result = merge_networks_separated_by_one_cell(data)
    print(result)
    print(expected_data)
    # Assert the result
    assert_frame_equal(result, expected_data), f"Expected {expected_data}, but got {result}"


def test_find_overlapping_networks_and_overlap_no_overlap():
    combined_neighbors = {
        1: {"8b2b996b26f2fff", "8b2b996b26f0fff"},
        2: {"8b2b996b26e6fff"},
        3: {"8b2b996b2653fff"}
    }
    expected_overlapping_pairs = []
    expected_new_rows = []

    overlapping_pairs, new_rows = _find_overlapping_networks_and_overlap(combined_neighbors)

    assert overlapping_pairs == expected_overlapping_pairs, f"Expected {expected_overlapping_pairs}, but got {overlapping_pairs}"
    assert new_rows == expected_new_rows, f"Expected {expected_new_rows}, but got {new_rows}"

def test_find_overlapping_networks_and_overlap_with_overlap():
    combined_neighbors = {
        1: {"8b2b996b26f2fff", "8b2b996b26f0fff"},
        2: {"8b2b996b26f0fff", "8b2b996b26e6fff"},
        3: {"8b2b996b2653fff"}
    }
    expected_overlapping_pairs = [(1, 2)]
    expected_new_rows = [{"h3_11": "8b2b996b26f0fff", "network_number": 1}]

    overlapping_pairs, new_rows = _find_overlapping_networks_and_overlap(combined_neighbors)

    assert overlapping_pairs == expected_overlapping_pairs, f"Expected {expected_overlapping_pairs}, but got {overlapping_pairs}"
    assert new_rows == expected_new_rows, f"Expected {expected_new_rows}, but got {new_rows}"

def test_find_overlapping_networks_and_overlap_multiple_overlaps():
    combined_neighbors = {
        1: {"8b2b996b26f2fff", "8b2b996b26f0fff"},
        2: {"8b2b996b26f0fff", "8b2b996b26e6fff"},
        3: {"8b2b996b26f0fff", "8b2b996b2653fff"}
    }
    expected_overlapping_pairs = [(1, 2), (1, 3), (2, 3)]
    expected_new_rows = [
        {"h3_11": "8b2b996b26f0fff", "network_number": 1}
    ]

    overlapping_pairs, new_rows = _find_overlapping_networks_and_overlap(combined_neighbors)
    print(expected_new_rows)
    print(new_rows)
    assert overlapping_pairs == expected_overlapping_pairs, f"Expected {expected_overlapping_pairs}, but got {overlapping_pairs}"
    assert new_rows == expected_new_rows, f"Expected {expected_new_rows}, but got {new_rows}"
