import pandas as pd
import polars as pl
import h3
import geopandas as gpd
from shapely.geometry import Polygon, MultiPolygon
import networkx as nx


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
    df.to_parquet(f"data/output_files/{file_name}.parquet")


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

    # Create a polars frame of h3 with a column of the network number, number of nodes in network and total retail venues in network
    networks = pl.DataFrame(
        {
            "h3_11": [h3_11 for component in components for h3_11 in component],
            "network_number": [i for i, component in enumerate(components, 1) for _ in component],
            "trackNodes": [len(component) for component in components for _ in component],
        }
    )

    # Join the networks with the input cells to get the retail count
    cells_with_network = networks.join(input_cells, on="h3_11", how="inner")

    cells_with_network = cells_with_network.join(
        cells_with_network.group_by("network_number").agg([
            pl.sum("overture_count").alias("total_overture_count"),
            pl.sum("foursquare_count").alias("total_foursquare_count")
        ]),
        on="network_number",
        how="inner"
    ).sort("network_number")

    return cells_with_network

# Step 6: Fill small holes in the geometries
def fill_holes(geometry, threshold = 2000 * 1e6):
    """Fill holes in polygons smaller than the threshold."""
    if isinstance(geometry, Polygon):
        exterior = geometry.exterior
        interiors = [interior for interior in geometry.interiors if interior.area > threshold]
        return Polygon(exterior, interiors)
    elif isinstance(geometry, MultiPolygon):
        return MultiPolygon([fill_holes(p, threshold) for p in geometry.geoms])
    return geometry
