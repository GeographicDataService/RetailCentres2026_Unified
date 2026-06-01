import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import polars as pl
import pytest
from utils.utils import join_networks_with_cells
from polars.testing import assert_frame_equal

def test_join_networks_with_cells():
    # Create sample data for networks
    networks = pl.DataFrame(
        {
            "h3_11": ["8928308280fffff", "8928308280bffff", "89283082807ffff", "8928308281fffff"],
            "network_number": [1, 1, 2,5],
            "trackNodes": [2, 2, 1,1],
        }
    )

    # Create sample data for input_cells
    input_cells = pl.DataFrame(
        {
            "h3_11": ["8928308280fffff", "8928308280bffff", "89283082807ffff"],
            "foursquare_count": [10, 8, 6],
            "retail_landuse": [True, False, True],
        }
    )

    # Expected output
    expected_output = pl.DataFrame(
        {
            "h3_11": ["8928308280fffff", "8928308280bffff", "89283082807ffff", "8928308281fffff"],
            "network_number": [1, 1, 2,5],
            "foursquare_count": [10, 8, 6, 0],
            "retail_landuse": [True, False, True, False],
            "total_foursquare_count": [18, 18, 6,0 ],
            "trackNodes": [2, 2, 1,1]
        }
    )

    # Run the function
    result = join_networks_with_cells(networks, input_cells)

    # Assert the result matches the expected output
    assert_frame_equal(result, expected_output), f"Expected {expected_output}, but got {result}"

if __name__ == "__main__":
    pytest.main()