# network_merger.py

from collections import defaultdict
from itertools import combinations
import polars as pl
import h3
from typing import Dict, Set, Tuple, List
import networkx as nx
import utils as ut
import time

def merge_networks_separated_by_one_cell(data: pl.DataFrame) -> pl.DataFrame:
    """
    Merges networks in the data that are separated by a single H3 cell.

    Args:
        data (pl.DataFrame): A DataFrame with columns 'h3_11' (H3 addresses) 
                             and 'network_number' (network identifiers).
    
    Returns:
        pl.DataFrame: A DataFrame with merged network numbers.
    """
    print("Merging networks separated by one cell.")
    print("Getting the perimeter of the networks.")
    combined_neighbors = _get_perimeter_networks(data)
    print("Finding overlapping networks and overlap.")
    overlapping_pairs, new_rows = _find_overlapping_networks_and_overlap(combined_neighbors)

    new_df = pl.DataFrame(new_rows)
    # Select relevant columns and append new rows
    data = data.select(["h3_11", "network_number"])
    data = data.vstack(new_df)
    # Merge overlapping networks
    print("Merging overlapping networks.")
    data = _merge_networks(data, overlapping_pairs)
    return data


def fill_until_no_new_cells(merged_data, min_neighbours=5):
    """
    Fill the merged_data with cells until no new cells can be added.
    """

    #drop the cells that aren't h3_11 or network_number
    merged_data = merged_data.select(["h3_11", "network_number"])
    print(f"Iteratively adding cells, with {min_neighbours} or more neighbours to the network.")
    previous_height = 0
    current_height = merged_data.height
    #run number
    run = 0
    while current_height > previous_height:
        run += 1
        print("Run ", run)
        merged_data = add_if_n_adjacent_cells(merged_data, min_neighbours)
        previous_height = current_height
        current_height = merged_data.height

    return merged_data


def add_if_n_adjacent_cells(merged_data: pl.DataFrame, min_neighbours: int = 5) -> pl.DataFrame:
    """
    Add cells to the merged_data if they have at least `min_neighbours` adjacent cells 
    in the original network.
    
    Args:
        merged_data (pl.DataFrame): Input Polars DataFrame with existing cells.
        min_neighbours (int): Minimum number of adjacent cells required to add a new cell.

    Returns:
        pl.DataFrame: Updated DataFrame with new cells added.
    """
    # Get the original and perimeter networks
    original_networks = _get_original_networks(merged_data)
    perimeter_networks = _get_perimeter_networks(merged_data)

    cells_to_add = []

    # Process each network
    for network_key, perimeter_cells in perimeter_networks.items():

        #get the original cells
        original_cells = set(original_networks[network_key])  # Convert to set for O(1) lookups
        #loop through the perimeter cells
        for cell_address in perimeter_cells:
            # Generate the neighbors of the current cell
            neighbors = h3.grid_ring(cell_address, 1)
            count = sum(1 for neighbor in neighbors if neighbor in original_cells)

            if count >= min_neighbours:
                cells_to_add.append({"h3_11": cell_address, "network_number": network_key})

    # Add the new cells to the merged data if any exist
    if cells_to_add:
        new_data = pl.DataFrame(cells_to_add)
        print(f"Adding {new_data.height} cells.")
        merged_data = merged_data.vstack(new_data)
    else:
        print("No new cells added.")

    return merged_data


def _get_expanded_networks(data: pl.DataFrame) -> Dict[int, Set[str]]:
    """
    Builds a dictionary mapping network numbers to the set of expanded H3 cells (the oringinal cell and the 1+ ring).

    Args:
        data (pl.DataFrame): Input data with H3 addresses and network numbers.

    Returns:
        Dict[int, Set[str]]: A dictionary mapping network numbers to their H3 neighbors.
    """
    expanded_network_dict = defaultdict(set)

    for h3_address, network in zip(data["h3_11"].to_list(), data["network_number"].to_list()):
        expanded_network_dict[network].update(h3.grid_ring(h3_address, 1))
    return expanded_network_dict

def _get_original_networks(data: pl.DataFrame) -> Dict[int, Set[str]]:
    """
    Builds a dictionary mapping network numbers to the set of expanded H3 cells (the oringinal cell and the 1+ ring).

    Args:
        data (pl.DataFrame): Input data with H3 addresses and network numbers.

    Returns:
        Dict[int, Set[str]]: A dictionary mapping network numbers to their H3 neighbors.
    """
    network_dict = defaultdict(set)

    for h3_address, network in zip(data["h3_11"].to_list(), data["network_number"].to_list()):
        network_dict[network].add(h3_address)
    return network_dict

def _get_perimeter_networks(data: pl.DataFrame) -> Dict[int, Set[str]]:
    """ get the perimeter of the networks by removing the inner cells, ie remove the oringal cells from the expanded cells"""
    perimeter_network_dict = defaultdict(set)
    network_dict = _get_original_networks(data)
    expanded_network_dict = _get_expanded_networks(data)
    for network, expanded_cells in expanded_network_dict.items():
        original_cells = network_dict[network]
        perimeter_network_dict[network] = expanded_cells - original_cells
    return perimeter_network_dict


def _find_overlapping_networks_and_overlap( #O(n*log(n))
    combined_neighbors: Dict[int, Set[str]]
) -> Tuple[List[Tuple[int, int]], List[Dict[str, int]]]:
    # Create a reverse index: hex to networks
    hex_to_networks = {}
    for network, neighbors in combined_neighbors.items():
        for hex_val in neighbors:
            hex_to_networks.setdefault(hex_val, set()).add(network)
    
    # Track overlaps
    overlapping_pairs = []
    unique_overlapping_pairs = set()
    new_rows = []
    
    # Find overlaps using the reverse index
    for hex_val, networks in hex_to_networks.items():
        # If a hex appears in multiple networks
        if len(networks) > 1:
            # Generate all unique network pairs
            network_pairs = list(combinations(sorted(networks), 2))
            
            # Maintain order and avoid duplicates
            for pair in network_pairs:
                if pair not in unique_overlapping_pairs:
                    unique_overlapping_pairs.add(pair)
                    overlapping_pairs.append(pair)
            
            # Add only one new row per hex (using the first network)
            first_network = min(networks)
            new_rows.append({"h3_11": hex_val, "network_number": int(first_network)})
    
    return overlapping_pairs, new_rows


def original_find_overlapping_networks_and_overlap( #O(n^2)
    combined_neighbors: Dict[int, Set[str]]
) -> Tuple[List[Tuple[int, int]], List[Dict[str, int]]]:
    overlapping_pairs = []
    new_rows = []
    for (network1, neighbors1), (network2, neighbors2) in combinations(combined_neighbors.items(), 2):
        overlap = neighbors1 & neighbors2
        if overlap:
            overlapping_pairs.append((network1, network2))
            new_rows.extend({"h3_11": hex, "network_number": int(network1)} for hex in overlap)
    return overlapping_pairs, new_rows


def _merge_networks(data: pl.DataFrame, overlapping_pairs: List[Tuple[int, int]]) -> pl.DataFrame:
    """
    Merges overlapping networks by mapping them to a common network number.

    Args:
        data (pl.DataFrame): Input data with columns 'h3_11' and 'network_number'.
        overlapping_pairs (List[Tuple[int, int]]): Pairs of overlapping networks.

    Returns:
        pl.DataFrame: Updated DataFrame with merged network numbers.
    """
    # Create a graph and add edges for overlapping pairs
    G = nx.Graph(overlapping_pairs)

    # Create a mapping of network numbers to their representative (smallest in the component)
    network_mapping = {
        node: min(component)
        for component in nx.connected_components(G)
        for node in component
    }
    #get the type of data["network_number"] column
    print(data["network_number"].dtype)
    
    # # Apply the mapping to the network_number column
    # data = data.to_pandas()
    data_merged = data.with_columns(pl.col("network_number").replace(network_mapping).alias("network_number"))
    # data["network_number"] = data["network_number"].map(network_mapping).fillna(data["network_number"])
    # print(data["network_number"].dtype)
    # return pl.from_pandas(data)
    return data_merged
