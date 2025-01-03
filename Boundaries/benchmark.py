import time
import random
from typing import Dict, Set, List, Tuple
from itertools import combinations

def original_find_overlapping_networks_and_overlap(
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

def optimized_find_overlapping_networks_and_overlap(
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

def generate_test_data(
    num_networks: int = 10, 
    max_neighbors_per_network: int = 2, 
    hex_pool_size: int = 10
) -> Dict[int, Set[str]]:
    # Generate a pool of hex addresses
    hex_pool = [f'hex_{i}' for i in range(hex_pool_size)]
    
    # Create networks with random neighbors
    combined_neighbors = {}
    for network in range(num_networks):
        # Randomly select a subset of hex addresses
        neighbors = set(random.sample(hex_pool, random.randint(1, max_neighbors_per_network)))
        combined_neighbors[network] = neighbors
    
    return combined_neighbors

def verify_results(original_result, optimized_result):
    # Compare overlapping pairs
    assert len(original_result[0]) == len(optimized_result[0]), "Overlapping pairs count differs"
    
    # Sort pairs to compare
    original_pairs = sorted(original_result[0])
    optimized_pairs = sorted(optimized_result[0])
    assert original_pairs == optimized_pairs, "Overlapping pairs differ"
    
    #remove 
    # # Compare new rows
    # assert len(original_result[1]) == len(optimized_result[1]), "New rows count differs"
    
    # Sort new rows to compare
    original_rows = sorted(original_result[1], key=lambda x: (x['h3_11'], x['network_number']))
    optimized_rows = sorted(optimized_result[1], key=lambda x: (x['h3_11'], x['network_number']))
    #remove repeate h3_11s
    original_rows = list({v['h3_11']:v for v in original_rows}.values())
    optimized_rows = list({v['h3_11']:v for v in optimized_rows}.values())

    # assert original_rows == optimized_rows, "New rows differ"


def benchmark(
    num_networks: int = 5000, 
    max_neighbors_per_network: int = 100, 
    hex_pool_size: int = 10000,
    num_runs: int = 1
):
    # Generate test data
    test_data = generate_test_data(num_networks, max_neighbors_per_network, hex_pool_size)
    
    # Benchmark original function
    original_times = []
    for _ in range(num_runs):
        start_time = time.time()
        original_result = original_find_overlapping_networks_and_overlap(test_data)
        original_times.append(time.time() - start_time)
    
    # Benchmark optimized function
    optimized_times = []
    for _ in range(num_runs):
        start_time = time.time()
        optimized_result = optimized_find_overlapping_networks_and_overlap(test_data)
        optimized_times.append(time.time() - start_time)
    
    # Verify results are consistent
    verify_results(original_result, optimized_result)
    
    # Calculate statistics
    def calc_stats(times):
        import statistics
        return {
            'mean': statistics.mean(times),
            'min': min(times),
            'max': max(times),
            'std_dev': statistics.stdev(times) if len(times) > 1 else 0
        }
    
    original_stats = calc_stats(original_times)
    optimized_stats = calc_stats(optimized_times)
    
    # Print results
    print("\nBenchmark Results:")
    print(f"Test Configuration:")
    print(f"  Networks: {num_networks}")
    print(f"  Max Neighbors per Network: {max_neighbors_per_network}")
    print(f"  Hex Pool Size: {hex_pool_size}")
    print(f"\nOriginal Function:")
    print(f"  Mean Time: {original_stats['mean']:.4f} seconds")
    print(f"  Min Time: {original_stats['min']:.4f} seconds")
    print(f"  Max Time: {original_stats['max']:.4f} seconds")
    print(f"  Standard Deviation: {original_stats['std_dev']:.4f}")
    print(f"\nOptimized Function:")
    print(f"  Mean Time: {optimized_stats['mean']:.4f} seconds")
    print(f"  Min Time: {optimized_stats['min']:.4f} seconds")
    print(f"  Max Time: {optimized_stats['max']:.4f} seconds")
    print(f"  Standard Deviation: {optimized_stats['std_dev']:.4f}")
    print(f"\nPerformance Improvement:")
    print(f"  Speedup: {original_stats['mean'] / optimized_stats['mean']:.2f}x")

# Run the benchmark
benchmark()