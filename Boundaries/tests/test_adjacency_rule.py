"""Clean-state check of the H3 adjacency rule (reviewer R1.6).

Rule: qualifying res-11 cells are nodes; two cells are joined when they share an edge
(h3.grid_ring(cell, 1), the 6 immediate neighbours); connected components are candidate
centres. Gap fill then adds a non-network cell when >= min_to_fill of its 6 neighbours
are in the same network.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import h3
import polars as pl
from utils.utils import create_networks
from retail.network_merger import fill_until_no_new_cells

# Liverpool city centre, res 11 (not a pentagon, so exactly 6 neighbours)
CENTRE = h3.latlng_to_cell(53.4055, -2.9800, 11)


def _cells(cells):
    return pl.DataFrame({
        "h3_11": list(cells),
        "foursquare_count": [2] * len(cells),
        "retail_landuse": [False] * len(cells),
    })


def _networks(cells):
    out = create_networks(_cells(cells))
    return {h: n for h, n in zip(out["h3_11"], out["network_number"])}


def test_neighbours_are_the_six_edge_sharing_cells():
    ring = h3.grid_ring(CENTRE, 1)
    assert len(ring) == 6
    assert all(h3.are_neighbor_cells(CENTRE, n) for n in ring)
    # no corner-only neighbours on a hex grid: ring-2 cells are not adjacent
    assert not any(h3.are_neighbor_cells(CENTRE, n) for n in h3.grid_ring(CENTRE, 2))


def test_edge_sharing_cells_form_one_network():
    a, b = CENTRE, h3.grid_ring(CENTRE, 1)[0]
    nets = _networks([a, b])
    assert nets[a] == nets[b]


def test_one_cell_gap_splits_networks():
    far = h3.grid_ring(CENTRE, 2)[0]
    nets = _networks([CENTRE, far])
    assert nets[CENTRE] != nets[far]


def test_chain_is_transitive():
    # line of 4 cells: each touches only the next, all end up in one component
    end = h3.grid_ring(CENTRE, 3)[0]
    line = h3.grid_path_cells(CENTRE, end)
    nets = _networks(line)
    assert len(set(nets.values())) == 1


def test_gap_fill_needs_all_six_neighbours():
    ring = h3.grid_ring(CENTRE, 1)

    full = pl.DataFrame({"h3_11": ring, "network_number": [1] * 6})
    filled = fill_until_no_new_cells(full, min_neighbours=6)
    assert CENTRE in filled["h3_11"].to_list()

    five = pl.DataFrame({"h3_11": ring[:5], "network_number": [1] * 5})
    filled = fill_until_no_new_cells(five, min_neighbours=6)
    assert CENTRE not in filled["h3_11"].to_list()
