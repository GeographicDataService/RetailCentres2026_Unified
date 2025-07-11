
import polars as pl
import h3
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
import networkx as nx
from collections import defaultdict
from itertools import combinations, chain


def to_geoframe(df):
    if isinstance(df, pl.DataFrame):
        df = df.to_pandas()
    df["geometry"] = df.apply(lambda x: h3.cell_to_boundary(x["h3_11"]), axis=1)
    # swap the lat lon to lon lat
    df["geometry"] = df["geometry"].apply(lambda x: [(i[1], i[0]) for i in x])
    df["geometry"] = df["geometry"].apply(lambda x: Polygon(x))
    # make valid geometry
    df = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    # convert to british national grid
    df = df.to_crs("EPSG:27700")
    return df


def to_parquet(df, file_name):
    df = to_geoframe(df)
    df.to_parquet(file_name)


def add_h3_11_column(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(
        h3_11=pl.struct(["lat", "lng"]).map_elements(
            lambda row: h3.latlng_to_cell(row["lat"], row["lng"], 11), return_dtype=str
        )
    )


# group on h3_11 and count the number of rows in each group
def agg_to_cells(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by("h3_11")
        .agg(pl.len().alias("retail_count"))
        .with_columns(pl.col("h3_11"))
    )

def agg_to_cells_foursquare(df: pl.DataFrame, threshold: float = 0.5) -> pl.DataFrame:
    # Map original categories to aggregated super-groups, except keep Dining and Drinking unchanged
    category_map = {
        "Retail": "Retail",
        "Business and Professional Services": "Retail",
        "Dining and Drinking": "Dining and Drinking",
        "Sports and Recreation": "Leisure & Travel",
        "Arts and Entertainment": "Leisure & Travel",
        "Travel and Transportation": "Leisure & Travel",
        "Community and Government": "Community & Health",
        "Health and Medicine": "Community & Health"
    }

    # category_map = {}

    # Map level1 categories to aggregated categories
    agg_category_pd = df["level1_category_name"].to_pandas().map(category_map).fillna(df["level1_category_name"].to_pandas())
    agg_category_pl = pl.Series("agg_category", agg_category_pd)
    df = df.with_columns([agg_category_pl])

    # Count total rows per h3_11
    base = df.group_by("h3_11").agg(pl.len().alias("retail_count"))

    # Count POIs per aggregated category per h3_11
    category_counts_long = (
        df.group_by(["h3_11", "agg_category"])
        .agg(pl.len().alias("count"))
    )

    # Pivot for wide format
    category_counts = (
        category_counts_long
        .pivot(values="count", index="h3_11", columns="agg_category")
        .fill_null(0)
    )

    # Top aggregated category (mode)
    top_category = (
        df.group_by("h3_11")
        .agg(pl.col("agg_category").mode().alias("top_category"))
    )

    # Calculate proportions and determine dominant_type based on threshold
    dominant_type = (
        category_counts_long.join(base, on="h3_11")
        .with_columns((pl.col("count") / pl.col("retail_count")).alias("proportion"))
        .filter(pl.col("proportion") >= threshold)
        .sort(["h3_11", "proportion"], descending=True)
        .group_by("h3_11")
        .agg(pl.col("agg_category").first().alias("dominant_type"))
    )

    # Fill 'mixed' where no dominant category
    dominant_type = (
        base.select("h3_11")
        .join(dominant_type, on="h3_11", how="left")
        .with_columns(pl.col("dominant_type").fill_null("mixed"))
    )

    # NEW: Add list of unique level 2 (or fallback to level 1) categories per h3_11
    unique_level2 = (
        df.with_columns(
            pl.when(pl.col("level2_category_name").is_not_null())
            .then(pl.col("level2_category_name"))
            .otherwise(pl.col("level1_category_name"))
            .alias("effective_level2")
        )
        .group_by("h3_11")
        .agg(pl.col("effective_level2").unique().alias("level2_categories"))
    )
    # NEW: Add list of unique category_name values per h3_11
    unique_category = (
        df.group_by("h3_11")
        .agg(pl.col("category_name").unique().alias("category_names"))
    )

    # Join everything together
    return (
        base
        .join(category_counts, on="h3_11", how="left")
        .join(top_category, on="h3_11", how="left")
        .join(dominant_type, on="h3_11", how="left")
        .join(unique_level2, on="h3_11", how="left")
        .join(unique_category, on="h3_11", how="left")
    )



def create_combined_table(
    foursquare_cells: pl.DataFrame,
    overture_cells: pl.DataFrame,
    land_use_cells: pl.DataFrame,
) -> pl.DataFrame:

    combined = foursquare_cells.join(
        land_use_cells, on="h3_11", how="full", coalesce=True
    )
    # Fill in missing values
    combined = combined.with_columns(
        [
            (pl.col("landuse") == "retail")
            .fill_null(False)
            .alias("retail_landuse")  # Create boolean retail_landuse column
        ]
    ).drop(
        "landuse"
    )  # Drop the original landuse column if needed

    # Add overture data
    combined = combined.join(overture_cells, on="h3_11", how="full", coalesce=True)
    # Rename columns
    combined = combined.rename(
        {"retail_count": "foursquare_count", "retail_count_right": "overture_count"}
    )

    # Fill in missing values
    combined = combined.with_columns(
        [
            pl.col("overture_count").fill_null(0),  # Replace null retail_count with 0
            pl.col("foursquare_count").fill_null(0),  # Replace null retail_count with 0
            pl.col("retail_landuse").fill_null(
                False
            ),  # Replace null retail_landuse with False
        ]
    )
    return combined


def create_networks(input_cells):
    # Create a set of H3 cells for fast lookup
    h3_cells_set = set(input_cells["h3_11"].to_list())

    # Generate edge pairs for all cells in the input DataFrame
    edges = [
        (cell, neighbor)
        for cell in h3_cells_set
        for neighbor in h3.grid_ring(cell, 1)
        if neighbor in h3_cells_set
    ]

    # Construct the graph and find connected components
    graph = nx.Graph()
    graph.add_nodes_from(h3_cells_set)  # Ensure all cells are included even if they have no edges
    graph.add_edges_from(edges)
    components = list(nx.connected_components(graph))
    
    # Sort components by the smallest H3 index in each to ensure deterministic ordering
    components = sorted(components, key=lambda comp: min(comp))
    # Create a polars frame of h3 with a column of the network number, number of nodes in network and total retail venues in network
    networks = pl.DataFrame(
        {
            "h3_11": [h3_11 for component in components for h3_11 in component],
            "network_number": [i for i, component in enumerate(components, 1) for _ in component],
            "trackNodes": [len(component) for component in components for _ in component],
        }
    )

    cells_with_network = join_networks_with_cells(networks, input_cells)

    return cells_with_network




def join_networks_with_cells(networks, input_cells):
    # Select relevant columns and join networks with input cells
    cells_with_network = (
        networks
        .select(["h3_11", "network_number"])  # Keep only relevant columns
        .join(input_cells, on="h3_11", how="left")  # Left join with input_cells
    )
    
    # Aggregate data by network_number and join the results back
    aggregated = (
        cells_with_network
        .group_by("network_number")
        .agg([
            pl.sum("overture_count").alias("total_overture_count"),
            pl.sum("foursquare_count").alias("total_foursquare_count"),
            pl.len().alias("trackNodes").cast(pl.Int64),
        ])
    )
    
    cells_with_network = (
        cells_with_network
        .join(aggregated, on="network_number", how="inner")
        .sort("network_number")
    )
    
    # Fill missing values
    cells_with_network = cells_with_network.with_columns([
        pl.col("overture_count").fill_null(0),
        pl.col("foursquare_count").fill_null(0),
        pl.col("retail_landuse").fill_null(False),
    ])
    
    return cells_with_network

    
def fill_holes(geometry, threshold = 2000 * 1e6):
    """Fill holes in polygons smaller than the threshold."""
    if isinstance(geometry, Polygon):
        exterior = geometry.exterior
        interiors = [interior for interior in geometry.interiors if interior.area > threshold]
        return Polygon(exterior, interiors)
    elif isinstance(geometry, MultiPolygon):
        return MultiPolygon([fill_holes(p, threshold) for p in geometry.geoms])
    return geometry

def dissolve_to_centres(df):
    
    # Your custom aggregation for list of strings
    def merge_unique_lists(series):
        clean_series = [x for x in series if x is not None] #celss added by manual edits, landuse, etc
        return list(set(chain.from_iterable(clean_series)))

    # Columns to aggregate
    sum_cols = [
        'foursquare_count', 'Retail', 'Dining and Drinking',
        'Leisure & Travel', 'Community & Health', 'overture_count'
    ]
    first_cols = ['total_overture_count', 'total_foursquare_count', 'trackNodes']
    list_cols = ['level2_categories', 'category_names']

    # Define aggregation dictionary
    aggfunc = {col: 'sum' for col in sum_cols}
    aggfunc.update({col: 'first' for col in first_cols})
    aggfunc.update({col: merge_unique_lists for col in list_cols})
    # Drop unwanted columns first
    cols_to_drop = [
        'h3_11', 'top_category', 'dominant_type', 'retail_landuse',
        'manually_added', 'manually_removed'
    ]
    df_cleaned = df.drop(columns=cols_to_drop)

    # Dissolve
    dissolved = df_cleaned.dissolve(
        by='network_number',
        aggfunc=aggfunc,
        as_index=False
    )

    return dissolved