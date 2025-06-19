import polars as pl
import pandas as pd
import geopandas as gpd
import os
from utils import utils as ut
from retail import network_merger
from retail import find_subcentres
from retail import centre_postprocessing

def generate_networks(
    combined: pl.DataFrame,
    source: str = "foursquare",
    min_retail_in_cell: int = 2,
    min_retail_in_island: int = 10,
    min_retail_in_network: int = 15,
    min_to_fill: int = 5,
    split_threshold: int = 0,
    merge_adjacent: bool = True
) -> None:
    """
    Creates and processes retail centre networks from a combined Polars DataFrame.
    """
    merge_flag = "y" if merge_adjacent else "n"
    folder_name = (
        f"retailcen_{source}_mrc_{min_retail_in_cell}_mri_{min_retail_in_island}_"
        f"mrn_{min_retail_in_network}_mtf_{min_to_fill}_splitthresh_{split_threshold}"
        f"_merge_{merge_flag}"
    )
    print(f"Processing {folder_name}")
    os.makedirs(f"data/output_files/{folder_name}", exist_ok=True)
    save_folder = f"data/output_files/{folder_name}"

    input_cells = combined.filter(
        (pl.col(f"{source}_count") >= min_retail_in_cell)
        | (pl.col("retail_landuse") == True)
    )

    input_cells.write_parquet(f"{save_folder}/0_input_cells.parquet")
    cells_with_network = ut.create_networks(input_cells)
    ut.to_parquet(cells_with_network, f"{save_folder}/1_intial_networks.parquet")

    if merge_adjacent:
        cells_with_network = network_merger.merge_networks_separated_by_one_cell(
            cells_with_network
        )
        cells_with_network = ut.join_networks_with_cells(
            cells_with_network, input_cells
        )

    filt_cells_with_network = cells_with_network.filter(
        (
            (cells_with_network[f"total_{source}_count"] >= min_retail_in_island)
            | (cells_with_network["trackNodes"] >= 2)
        )
        & (cells_with_network[f"total_{source}_count"] >= min_retail_in_network)
    ).sort("network_number")

    ut.to_parquet(
        filt_cells_with_network,
        f"{save_folder}/2_merged_filtered_networks.parquet",
    )

    if min_to_fill < 7:
        filt_cells_with_network = network_merger.fill_until_no_new_cells(
            filt_cells_with_network,
            min_neighbours=min_to_fill
        )
        filt_cells_with_network = ut.join_networks_with_cells(
            filt_cells_with_network, input_cells
        )

    ut.to_parquet(filt_cells_with_network, f"{save_folder}/3_afterfill.parquet")
    print(
        "Number of networks after filtering: "
        f"{filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]}"
    )

    filt_cells_with_network.write_parquet(f"{save_folder}/3_afterfill_pl.parquet")

    filt_cells_with_network = find_subcentres.run_leiden_clustering_polars(
        filt_cells_with_network, res=0.15, alpha=0, seed=505
    )
    print(
        "Number of networks after subnetwork finding: "
        f"{filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]}"
    )
    print(
        "Number of subcentres: "
        f"{filt_cells_with_network.select(pl.col('subcentre').n_unique()).to_numpy()[0][0]}"
    )

    filt_cells_with_network = find_subcentres.split_networks_with_poi_threshold_polars(
        filt_cells_with_network, count_threshold=split_threshold
    )
    print(
        "Number of networks after subnetwork finding with poi threshold: "
        f"{filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]}"
    )

    filt_cells_with_network = ut.join_networks_with_cells(
        filt_cells_with_network, input_cells
    )
    print(
        "Number of networks after recalculating total_foursquare_count and trackNodes: "
        f"{filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]}"
    )

    filt_cells_with_network = ut.to_geoframe(filt_cells_with_network)
    dissolved = filt_cells_with_network.dissolve(by="network_number", as_index=False)
    dissolved["geometry"] = dissolved["geometry"].apply(lambda geom: ut.fill_holes(geom))

    dissolved_gdf = gpd.GeoDataFrame(
        dissolved, geometry="geometry", crs="EPSG:27700"
    )
    dissolved_gdf = dissolved_gdf[
        ["network_number", "geometry", f"total_{source}_count", "trackNodes"]
    ]
    dissolved_gdf["network_number"] = (
        dissolved_gdf[f"total_{source}_count"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    dissolved_gdf = dissolved_gdf.rename(
        columns={
            "network_number": "RC_ID",
            f"total_{source}_count": "POI_count",
            "trackNodes": "# H3 cells",
        }
    )

    dissolved_gdf.to_parquet(f"{save_folder}/4_finalcentres.parquet")
    dissolved_gdf_las = centre_postprocessing.add_localauthorities_to_centres(
        dissolved_gdf
    )
    dissolved_gdf_las.to_parquet(f"{save_folder}/4_finalcentres_las.parquet")
