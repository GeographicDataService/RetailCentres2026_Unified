import numpy as np
import networkx as nx
import igraph as ig
import leidenalg
import h3
from tqdm import tqdm
from sklearn.preprocessing import normalize
import polars as pl

def run_leiden_clustering_polars(retail_centres: pl.DataFrame, alpha: float, res: float, seed: int = 42) -> pl.DataFrame:
    poi_cols = ['Dining and Drinking', 'Leisure & Travel', 'Community & Health', 'Retail']
    df = retail_centres.with_columns([
        pl.col(poi_cols).fill_null(0)
    ])

    poi_matrix = normalize(df.select(poi_cols).to_numpy(), norm='l2', axis=1)
    df = df.with_columns([
        pl.Series(name='poi_vec', values=poi_matrix.tolist())
    ])

    # Rank networks by size
    network_counts = (
        df.select('network_number')
        .to_series()
        .value_counts()
        .sort('count', descending=True)
        .with_columns([
            pl.col('count').rank(method='ordinal').cast(pl.Int32).alias('rank'),
        ])
        .rename({'network_number': 'original_network_number', 'rank': 'network_number'})
    )
    df = df.join(network_counts, on='network_number', how='left')

    all_clustered = []
    for network_number in tqdm(df.select('network_number').unique()['network_number'].to_list(), desc=f"Alpha={alpha}, Res={res}"):
        rc = df.filter(pl.col('network_number') == network_number)

        if rc.height < 2:
            rc = rc.with_columns([
                pl.lit(f"{network_number}_0").alias('subcentre')
            ])
            all_clustered.append(rc)
            continue

        h3_list = rc['h3_11'].to_list()
        poi_lookup = dict(zip(h3_list, rc['poi_vec'].to_list()))
        density_lookup = dict(zip(h3_list, rc['foursquare_count'].to_list()))
        h3_set = set(h3_list)

        G = nx.Graph()
        for h in sorted(h3_set):
            G.add_node(h, density=density_lookup[h])
            for n in sorted(h3.grid_ring(h, 1)):
                if n in h3_set and not G.has_edge(h, n):
                    sim = np.dot(poi_lookup[h], poi_lookup[n])
                    if sim == 0: 
                        sim = 0.025 # small value to avoid zero similarity
                    d1, d2 = density_lookup[h], density_lookup[n]
                    density_weight = d1 + d2 + 1
                    weight = alpha * sim + (1 - alpha) * density_weight
                    if weight > 0:
                        G.add_edge(h, n, weight=weight)

        h3_nodes = list(G.nodes)
        h3_id_map = {h: i for i, h in enumerate(h3_nodes)}
        edges = [(h3_id_map[u], h3_id_map[v]) for u, v in G.edges()]
        weights = [G[u][v]['weight'] for u, v in G.edges()]

        if edges:
            G_ig = ig.Graph(n=len(h3_nodes), edges=edges, directed=False)
            G_ig.es['weight'] = weights
            partition = leidenalg.find_partition(
                G_ig,
                leidenalg.RBConfigurationVertexPartition,
                weights=G_ig.es['weight'],
                resolution_parameter=res,
                seed=seed,
                n_iterations=-1
            )
            membership = partition.membership
            h3_to_cluster = {h3_nodes[i]: f"{network_number}_{membership[i]}" for i in range(len(h3_nodes))}
            rc = rc.with_columns([
                pl.col('h3_11').replace_strict(h3_to_cluster).alias('subcentre')
            ])
        else:
            rc = rc.with_columns([
                pl.lit(f"{network_number}_0").alias('subcentre')
            ])

        all_clustered.append(rc)

    result = pl.concat(all_clustered, how='vertical')
    return result


def split_networks_with_poi_threshold_polars(df: pl.DataFrame, count_threshold: int) -> pl.DataFrame:
    df = df.with_columns([
        pl.col('network_number').cast(pl.Utf8).alias('original_network_number')
    ])

    over_threshold = (
        df.select(['network_number', 'total_foursquare_count'])
        .unique()
        .filter(pl.col('total_foursquare_count') >= count_threshold)
        .select(pl.col('network_number').cast(pl.Utf8))
        .to_series()
        .to_list()
    )


    df = df.with_columns([
        pl.when(pl.col('original_network_number').is_in(over_threshold))
        .then(pl.col('subcentre'))
        .otherwise(pl.col('original_network_number'))
        .alias('network_number')
    ])

    return df