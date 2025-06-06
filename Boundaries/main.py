import polars as pl
import pandas as pd
import numpy as np
import geopandas as gpd
import utils as ut
import itertools
import network_merger
import find_subcentres
import retailfilter
import centre_postprocessing
import os
import random

#set random seed for reproducibility (of the subnetwork finding algorithm)
seed = 505
random.seed(seed)        # or any integer
np.random.seed(seed)

def generate_networks_mergefirst(
    combined,
    source="foursquare",
    min_retail_in_cell=2,
    min_retail_in_island=10,
    min_retail_in_network=15,
    min_to_fill=5,
    merge_adjacent=True
):
    merge_flag = "y" if merge_adjacent else "n"
    folder_name = f"retailcen_{source}_mrc_{min_retail_in_cell}_mri_{min_retail_in_island}_mrn_{min_retail_in_network}_mtf_{min_to_fill}_merge_{merge_flag}"
    print(f"Processing {folder_name}")
    #create folder if it doesn't exist
    os.makedirs(f"data/output_files/{folder_name}", exist_ok=True)
    save_folder = f"data/output_files/{folder_name}"
    input_cells = combined.filter(
        (pl.col(f"{source}_count") >= min_retail_in_cell)
        | (pl.col("retail_landuse") == True)
    )


    #only keep first 10000 cells for testing
    input_cells = input_cells.head(10000)
    
    input_cells.write_parquet(
        save_folder+"/0_input_cells.parquet"
    )
    # Example usage
    cells_with_network = ut.create_networks(input_cells)

    ut.to_parquet(
        cells_with_network,
        save_folder+"/1_intial_networks.parquet"
    )

    if merge_adjacent:
        cells_with_network = network_merger.merge_networks_separated_by_one_cell(cells_with_network)
        cells_with_network = ut.join_networks_with_cells(cells_with_network, input_cells) #add the retail count to the network

        # island rmeoval
    # keep only the networks with more than 10 retail venues or more than 1 track node
    # We prune the exhaustive set of retail cen-
    # tres to include only those with at least two hexagon units and at least ten overall retail unit points contained
    # within them, a threshold used by Pavlis et al. (2018) and based on UK retail planning policy 18 .

    # "In England and Wales, agglomerations with less than
    # fifteen VOA retail points and ten OSM retail points are removed from the set, while for Scotland and Northern
    # Ireland the condition is based on ten OSM points."""
    # from https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates/articles/highstreetsingreatbritain/march2020
    # Spatial clustering has been implemented using the data clustering algorithm DBSCAN (Density-based spatial clustering of applications with noise). Candidate retail clusters required a minimum of 15 retail address point geometries within 15 buildings and a maximum of 150 metres between the address geometries in the cluster.

    filt_cells_with_network = cells_with_network.filter(
        (
            (cells_with_network[f"total_{source}_count"] >= min_retail_in_island)
            | (cells_with_network["trackNodes"] >= 2)
        )
        & (cells_with_network[f"total_{source}_count"] >= min_retail_in_network)
    ).sort("network_number")


    ut.to_parquet(
        filt_cells_with_network,
        save_folder+"/2_merged_filtered_networks.parquet",
    )

    #if min_to_fill is 7, we don't fill any cells
    if min_to_fill < 7:
        filt_cells_with_network = network_merger.fill_until_no_new_cells(filt_cells_with_network, min_neighbours=min_to_fill)
        filt_cells_with_network = ut.join_networks_with_cells(filt_cells_with_network, input_cells) #add the retail count to the network

    ut.to_parquet(
        filt_cells_with_network,
        save_folder+"/3_afterfill.parquet",
    )



    ##run the subnetwork finding algorithm
    # We use the find_subcentres function to find subcentres in the network
    filt_cells_with_network= find_subcentres.run_leiden_clustering_polars(
        filt_cells_with_network,
        res=0.15,
        alpha=0,
        seed=505)
    
    filt_cells_with_network = find_subcentres.split_networks_with_poi_threshold_polars(
        filt_cells_with_network, count_threshold=1000
    )
    #recalculate the total_foursquare_count and trackNodes for each network
    filt_cells_with_network = ut.join_networks_with_cells(
        filt_cells_with_network, input_cells
    )  # add the retail count to the network


    filt_cells_with_network = ut.to_geoframe(filt_cells_with_network)

    dissolved = filt_cells_with_network.dissolve(
        by="network_number", as_index=False
    ).reset_index(drop=True)

    dissolved["geometry"] = dissolved["geometry"].apply(
        lambda geom: ut.fill_holes(geom)
    )


    # Final GeoDataFrame with dissolved unique polygons
    dissolved_gdf = gpd.GeoDataFrame(
        dissolved, geometry="geometry", crs="EPSG:27700"
    )

    #drop cell related columns
    dissolved_gdf = dissolved_gdf[["network_number", "geometry","total_foursquare_count","trackNodes"]]

    #replace network number with rank based on total_foursquare_count
    dissolved_gdf["network_number"] = (
        dissolved_gdf["total_foursquare_count"]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    dissolved_gdf = dissolved_gdf.rename(
        columns={
            "network_number": "RC_ID",
            "total_foursquare_count": "POI_count",
            "trackNodes": "trackNodes"
        }
    )
    ##post processing
    dissolved_gdf = centre_postprocessing.add_localauthorities_to_centres(
        dissolved_gdf
    )
    dissolved_gdf.to_parquet(
        save_folder+"/4_finalcentres.parquet",
    )



# # Define parameter values
# sources = ["foursquare"]
# min_retail_in_cell_values = [1, 2, 3]
# min_retail_in_island_values = [ 10, 15]
# min_retail_in_network_values = [10, 15, 20, 25]

sources = ["foursquare"]
min_retail_in_cell_values = [2]
min_retail_in_island_values = [10]
min_retail_in_network_values = [10]
min_to_fill = [6]
merge_adjacent = [False]


# Generate all parameter combinations
param_combinations = itertools.product(
    sources,
    min_retail_in_cell_values,
    min_retail_in_island_values,
    min_retail_in_network_values,
    min_to_fill,
    merge_adjacent
)

# Convert to a list once for both counting and iteration
param_combinations_list = list(param_combinations)

# Get the total combinations count
total_combos = len(param_combinations_list)

print(f"Total combinations: {total_combos}")
# Load data only once
foursquare = pl.read_parquet(
    "data/input_files/uk_foursquare_datefields_admin_categories.parquet"
)
overture = pl.read_parquet("data/input_files/poi_uk_overture_proc.parquet")


foursquare = retailfilter.filter_foursquare(foursquare)

overture = overture.filter(
    (overture["level1_category_name"] == "retail")
    | (overture["level1_category_name"] == "eat_and_drink")
    | (overture["level1_category_name"] == "beauty_and_spa")
    | (overture["level1_category_name"] == "arts_and_entertainment")
    | (overture["level2_category_name"] == "activate_life")
    | (overture["level1_category_name"] == "automotive")
    | (overture["level2_category_name"] == "art_gallery")
    | (overture["level2_category_name"] == "museum")
)

foursquare = ut.add_h3_11_column(foursquare)
overture = ut.add_h3_11_column(overture)

foursquare_cells = ut.agg_to_cells_foursquare(foursquare)
overture_cells = ut.agg_to_cells(overture)

# Load land use data
land_use_cells = pd.read_parquet("data/input_files/retail_landuse_h3_geo.parquet")
#
land_use_cells = pl.DataFrame(land_use_cells)
combined = ut.create_combined_table(foursquare_cells, overture_cells, land_use_cells)


for idx, (
    source,
    min_retail_in_cell,
    min_retail_in_island,
    min_retail_in_network,
    min_to_fill,
    merge_adjacent
) in enumerate(param_combinations_list, start=1):
    print(f"Processing combination {idx} of {total_combos}")
    print(
        f"Parameters: source={source}, min_cell={min_retail_in_cell}, min_island={min_retail_in_island}, min_network={min_retail_in_network}, min_to_fill={min_to_fill}"
    )

    generate_networks_mergefirst(
        combined,
        source=source,
        min_retail_in_cell=min_retail_in_cell,
        min_retail_in_island=min_retail_in_island,
        min_retail_in_network=min_retail_in_network,
        min_to_fill=min_to_fill,
        merge_adjacent=merge_adjacent
    )