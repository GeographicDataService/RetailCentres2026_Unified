import polars as pl
import pandas as pd
import geopandas as gpd
import os
from utils import utils as ut
from retail import network_merger
from retail import find_subcentres
from retail import centre_postprocessing
from retail import manual_edits

def generate_networks(
    combined: pl.DataFrame,
    run_name: str,
    source: str = "foursquare",
    min_retail_in_cell: int = 2,
    min_retail_in_island: int = 10,
    min_retail_in_network: int = 10,
    min_to_fill: int = 5,
    split_threshold: int = 0,
    merge_adjacent: bool = True
) -> None:
    """
    Creates and processes retail centre networks from a combined Polars DataFrame.
    """

    # ----------------------------------------
    # Set up output folder based on parameters
    # ----------------------------------------
    merge_flag = "y" if merge_adjacent else "n"
    folder_name = (
        f"{run_name}_{source}_mrc_{min_retail_in_cell}_mri_{min_retail_in_island}_"
        f"mrn_{min_retail_in_network}_mtf_{min_to_fill}_splitthresh_{split_threshold}"
        f"_merge_{merge_flag}"
    )
    print(f"Processing {folder_name} \n")
    os.makedirs(f"data/output_files/{folder_name}", exist_ok=True)
    save_folder = f"data/output_files/{folder_name}"

    # --------------------------------------------------------
    # Manual edits: add and flag manually edited input cells
    # --------------------------------------------------------
    print("Adding manually edited cells...")
    combined = manual_edits.add_cells_manually(combined)  # Adds manually added cells with a flag
    combined = manual_edits.flag_manually_removed_cells(combined)  # Flags cells to be removed

    # --------------------------------------------------------
    # Filter input cells based on source and retail land use, or manually added
    # --------------------------------------------------------
    input_cells_not_manual = combined.filter(
        (pl.col(f"{source}_count") >= min_retail_in_cell)
        | (pl.col("retail_landuse"))
    )
    input_cells = combined.filter(
        (pl.col(f"{source}_count") >= min_retail_in_cell)
        | (pl.col("retail_landuse"))
        | (pl.col("manually_added"))
    )
    print(f"Filtered input cells, to keep only those with POI count > {min_retail_in_cell}, flagged as OSM retail land use, or manually added")
    print("Number of cells kept due to manual flag: ", input_cells.shape[0] - input_cells_not_manual.shape[0] , "\n")

    # ------------------------------------------------------------------
    # NOTE: filter out any manually removed cells and count them
    # Not running this for now. Three cases from before seem fine:
    # - Brighton: exact split by algo
    # - Norwich: already split normally
    # - London: Islington/Highbury splits a bit different but reasonable.
    #   Manual split forces north Hackney not to split (below threshold)
    # ------------------------------------------------------------------
    # input_cells = input_cells.filter(~pl.col("manually_removed"))

    input_cells.write_parquet(f"{save_folder}/0_input_cells.parquet")

    # ----------------------------------------
    # Create networks of adjoining cells
    # ----------------------------------------
    # A network is defined as a set of cells connected by at least one shared edge
    cells_with_network = ut.create_networks(input_cells)
    ut.to_parquet(cells_with_network, f"{save_folder}/1_intial_networks.parquet")

    # ------------------------------------------------------------------
    # Filter networks by retail venue count and track node count
    # ------------------------------------------------------------------
    filt_cells_with_network = cells_with_network.filter(
        (
            (cells_with_network[f"total_{source}_count"] >= min_retail_in_island)
            | (cells_with_network["trackNodes"] >= 2)
        )
        & (cells_with_network[f"total_{source}_count"] >= min_retail_in_network)
    ).sort("network_number")

    n_networks = filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]
    print(
        "Number of networks after intial filter: "
        f"{n_networks}"
    )

    # ----------------------------------------
    # Merge networks separated by one cell (optional) if one of the networks has <10 tracknodes
    # ----------------------------------------
    if merge_adjacent:
        filt_cells_with_network = network_merger.merge_networks_separated_by_one_cell(
            filt_cells_with_network, merge_h3_threshold= 10
        )
        filt_cells_with_network = ut.join_networks_with_cells(
            filt_cells_with_network, input_cells
        )
    
        n_networks = filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]
        print(
            "Number of networks after merging adjacent: "
            f"{n_networks}"
        )

    ut.to_parquet(
        filt_cells_with_network,
        f"{save_folder}/2_merged_filtered_networks.parquet",
    )

    # ----------------------------------------
    # Optional: Add cells with N or more adjacent cells in a network to the network.
    # By default, this is set to 6. which fills cells entirely within a network.
    # ----------------------------------------
    if min_to_fill < 7:
        filt_cells_with_network = network_merger.fill_until_no_new_cells(
            filt_cells_with_network,
            min_neighbours=min_to_fill
        )
        filt_cells_with_network = ut.join_networks_with_cells(
            filt_cells_with_network, input_cells
        )

    ut.to_parquet(filt_cells_with_network, f"{save_folder}/3_afterfill.parquet")
    filt_cells_with_network.write_parquet(f"{save_folder}/3_afterfill_pl.parquet")

    # ----------------------------------------
    # Run Leiden clustering to find subcentres
    # ----------------------------------------
    print("Running subcentre finder...")
    filt_cells_with_network = find_subcentres.run_leiden_clustering_polars(
        filt_cells_with_network, res=0.15, alpha=0, seed=505
    )

    print(
        "Total Number of subcentres: "
        f"{filt_cells_with_network.select(pl.col('subcentre').n_unique()).to_numpy()[0][0]}"
    )

    # ------------------------------------------------------------------
    # Split networks where subcentres are below POI count threshold
    # ------------------------------------------------------------------
    filt_cells_with_network = find_subcentres.split_networks_with_poi_threshold_polars(
        filt_cells_with_network, count_threshold=split_threshold
    )
    print(
        "Number of networks after subnetwork finding with poi threshold: "
        f"{filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]}"
    )

    # ----------------------------------------
    # Recalculate totals for each network
    # ----------------------------------------
    filt_cells_with_network = ut.join_networks_with_cells(
        filt_cells_with_network, input_cells
    )
    filt_cells_with_network = ut.to_geoframe(filt_cells_with_network)

    # ----------------------------------------
    # Dissolve H3 cells into final centres
    # ----------------------------------------
    # This step creates single polygons per network and fills holes
    dissolved = ut.dissolve_to_centres(filt_cells_with_network)
    dissolved["geometry"] = dissolved["geometry"].apply(lambda geom: ut.fill_holes(geom))
    dissolved_gdf = gpd.GeoDataFrame(
        dissolved, geometry="geometry", crs="EPSG:27700"
    )
    dissolved_gdf = dissolved_gdf[
        ["network_number", "geometry", f"total_{source}_count", "trackNodes", 'Retail',
         'Dining and Drinking', 'Leisure & Travel', 'Community & Health', 'category_names']
    ]
    dissolved_gdf["network_number"] = (
        dissolved_gdf[f"total_{source}_count"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    dissolved_gdf = dissolved_gdf.rename(
        columns={
            "network_number": "RC_ID",
            f"total_{source}_count": "Total_POI_count",
            "trackNodes": "# H3 cells",
        }
    )

    dissolved_gdf.to_parquet(f"{save_folder}/4_finalcentres.parquet")

    # ----------------------------------------
    # Add local authority names to final centres
    # ----------------------------------------
    dissolved_gdf_las = centre_postprocessing.add_localauthorities_to_centres(
        dissolved_gdf
    )
    dissolved_gdf_las.to_parquet(f"{save_folder}/4_finalcentres_las.parquet")
