import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import polars as pl
from retail.network_merger import merge_networks_separated_by_one_cell
from retail.network_merger import get_overlap_hexes_by_pair
from polars.testing import assert_frame_equal


#8b2b996b26f2fff, 8b2b996b26f0fff, 8b2b996b26f3fff, 8b2b996b26e6fff, 8b2b996b2653fff


def test_merge_networks_separated_by_one_cell():
    # Sample data
    data = pl.DataFrame({
        "h3_11": ["8b2b996b26f2fff", "8b2b996b26f0fff", "8b2b996b26f3fff", "8b2b996b26e6fff", "8b2b996b2653fff"],
        "network_number": [1, 1, 1, 2, 3],
        "trackNodes": [3, 3, 3, 1, 1],
    })

    # Expected result
    expected_data = pl.DataFrame({
        "h3_11": ["8b2b996b26f2fff", "8b2b996b26f0fff", "8b2b996b26f3fff", "8b2b996b26e6fff", "8b2b996b2653fff","8b2b996b26f5fff"], #cell added in between
        "network_number": [1, 1, 1, 1, 3, 1]
    })

    # Call the functiont
    result = merge_networks_separated_by_one_cell(data, merge_h3_threshold=10)
    print(result)
    print(expected_data)
    # Assert the result
    assert_frame_equal(result, expected_data), f"Expected {expected_data}, but got {result}"


def test_get_overlap_hexes_by_pair_no_overlap():
    combined_neighbors = {
        1: {"8b2b996b26f2fff", "8b2b996b26f0fff"},
        2: {"8b2b996b26e6fff"},
        3: {"8b2b996b2653fff"}
    }
    expected_overlaps = {}

    overlaps = get_overlap_hexes_by_pair(combined_neighbors)

    assert overlaps == expected_overlaps, f"Expected {expected_overlaps}, but got {overlaps}"

def test_get_overlap_hexes_by_pair_with_overlap():
    combined_neighbors = {
        1: {"8b2b996b26f2fff", "8b2b996b26f0fff"},
        2: {"8b2b996b26f0fff", "8b2b996b26e6fff"},
        3: {"8b2b996b2653fff"}
    }
    expected_overlaps = {(1, 2): {"8b2b996b26f0fff"}}

    overlaps = get_overlap_hexes_by_pair(combined_neighbors)

    assert overlaps == expected_overlaps, f"Expected {expected_overlaps}, but got {overlaps}"

def test_get_overlap_hexes_by_pair_multiple_overlaps():
    combined_neighbors = {
        1: {"8b2b996b26f2fff", "8b2b996b26f0fff"},
        2: {"8b2b996b26f0fff", "8b2b996b26e6fff"},
        3: {"8b2b996b26f0fff", "8b2b996b2653fff"}
    }
    expected_overlaps = {
        (1, 2): {"8b2b996b26f0fff"},
        (1, 3): {"8b2b996b26f0fff"},
        (2, 3): {"8b2b996b26f0fff"},
    }

    overlaps = get_overlap_hexes_by_pair(combined_neighbors)

    assert overlaps == expected_overlaps, f"Expected {expected_overlaps}, but got {overlaps}"
