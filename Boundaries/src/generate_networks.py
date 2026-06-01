import os
from pathlib import Path
from typing import Optional

import pandas as pd
import geopandas as gpd
import polars as pl

from utils import utils as ut
from retail import centre_postprocessing
from retail import find_subcentres
from retail import landuse_filter
from retail import manual_edits
from retail import network_merger
from retail import integrate_retail_parks as retail_park_integration
import config

def generate_networks(
    combined: pl.DataFrame,
    run_name: str,
    source: str = "foursquare",
    min_retail_in_cell: int = 2,
    min_retail_in_network: int = 10,
    min_to_fill: int = 5,
    split_threshold: int = 0,
    merge_adjacent: bool = True,
    enable_landuse_filter: bool = False,
    landuse_overlap_threshold: float = 75.0,
    landuse_poi_threshold: Optional[int] = 20,
    integrate_retail_parks: bool = False,
    retail_parks_path: Optional[str] = None,
    min_remainder_pois: int = 10
) -> None:
    """
    Creates and processes retail centre networks from a combined Polars DataFrame.
    """

    # ----------------------------------------
    # Set up output folder based on parameters
    # ----------------------------------------
    folder_name = config.get_output_folder_name(
        run_name=run_name,
        source=source,
        min_retail_in_cell=min_retail_in_cell,
        min_retail_in_network=min_retail_in_network,
        min_to_fill=min_to_fill,
        split_threshold=split_threshold,
        merge_adjacent=merge_adjacent
    )
    print(f"Processing {folder_name} \n")
    save_folder = config.RUNS_DIR / run_name / folder_name
    save_folder.mkdir(parents=True, exist_ok=True)
    save_folder = str(save_folder)

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

    # ------------------------------------------------------------------
    input_cells = input_cells.filter(~pl.col("manually_removed"))

    input_cells.write_parquet(f"{save_folder}/0_input_cells.parquet")

    # ----------------------------------------
    # Create networks of adjoining cells
    # ----------------------------------------
    # A network is defined as a set of cells connected by at least one shared edge
    cells_with_network = ut.create_networks(input_cells)
    ut.to_parquet(cells_with_network, f"{save_folder}/1_intial_networks.parquet")

    # ------------------------------------------------------------------
    # Filter networks by retail venue count
    # ------------------------------------------------------------------
    filt_cells_with_network = cells_with_network.filter(
        cells_with_network[f"total_{source}_count"] >= min_retail_in_network
    ).sort("network_number")

    n_networks = filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]
    print(
        "Number of networks after intial filter: "
        f"{n_networks}"
    )

    ut.to_parquet(
        filt_cells_with_network,
        f"{save_folder}/2_filtered_networks.parquet",
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

    # ----------------------------------------
    # Retail Park Integration (optional)
    # ----------------------------------------
    park_networks = None
    if integrate_retail_parks:
        centres_gdf = ut.to_geoframe(filt_cells_with_network)
        if retail_parks_path:
            print(f"\nLoading retail parks from: {retail_parks_path}")
            park_cells = gpd.read_parquet(retail_parks_path)
            print(f"  Loaded {park_cells['park_id'].nunique()} retail parks")
        else:
            print("\nWarning: integrate_retail_parks=True but no parks detected or provided")

            #throw error
            raise ValueError("Retail parks path must be provided if integrate_retail_parks is True")

        # Step 2: Integrate parks (workflow 3)
        if integrate_retail_parks and park_cells is not None:
            print("\nIntegrating retail parks (Workflow 3: merge small remainders)...")

            centres_kept, centres_merged, summary_df, updated_park_cells = (
                retail_park_integration.subtract_park_cells_from_centres(
                    centres=centres_gdf,
                    park_cells=park_cells,
                    min_remainder_pois=min_remainder_pois,
                    check_connectivity=True
                )
            )

            # Create park networks
            starting_park_id = centres_gdf['network_number'].max() + 1000 if len(centres_gdf) > 0 else 1000
            park_networks_raw = retail_park_integration.create_retail_park_networks(
                park_cells=updated_park_cells,
                centres_deleted=centres_merged,
                starting_network_id=starting_park_id
            )

            # Join park networks with input_cells to calculate category aggregations
            # (same as done for centres)
            park_networks_df = park_networks_raw.drop(columns='geometry')
            park_networks_pl = pl.from_pandas(park_networks_df.reset_index(drop=True))
            park_networks_pl = ut.join_networks_with_cells(park_networks_pl, input_cells)
            park_networks = ut.to_geoframe(park_networks_pl)

            # Save integration outputs
            centres_kept.to_parquet(f"{save_folder}/centres_no_parks.parquet")
            park_networks.to_parquet(f"{save_folder}/retail_parks_integrated.parquet")
            summary_df.to_csv(f"{save_folder}/retail_park_integration_summary.csv", index=False)

            print(f"\n  Final centres (no parks): {centres_kept['network_number'].nunique()} networks, {len(centres_kept)} cells")
            print(f"  Retail parks: {park_networks['network_number'].nunique()} networks, {len(park_networks)} cells")

            # Create dissolved polygon outputs
            print("\nCreating dissolved polygon outputs...")
            retail_park_integration.create_polygon_outputs(
                centres_kept=centres_kept,
                park_networks=park_networks,
                output_dir=Path(save_folder)
            )

            # Convert centres back to polars for continued processing
            centres_kept_df = centres_kept.drop(columns='geometry')
            filt_cells_with_network = pl.from_pandas(centres_kept_df.reset_index(drop=True))

    pre_landuse_cells = filt_cells_with_network.clone()

    if enable_landuse_filter and filt_cells_with_network.height > 0:
        if not config.COMMERCIAL_LANDUSE_PATH.exists():
            raise FileNotFoundError(f"Commercial landuse file missing: {config.COMMERCIAL_LANDUSE_PATH}")
        if not config.INDUSTRIAL_LANDUSE_PATH.exists():
            raise FileNotFoundError(f"Industrial landuse file missing: {config.INDUSTRIAL_LANDUSE_PATH}")

        centres_gdf = ut.to_geoframe(filt_cells_with_network)
        commercial_gdf = gpd.read_parquet(config.COMMERCIAL_LANDUSE_PATH)
        industrial_gdf = gpd.read_parquet(config.INDUSTRIAL_LANDUSE_PATH)

        filter_result = landuse_filter.run_landuse_filter(
            centres=centres_gdf,
            commercial=commercial_gdf,
            industrial=industrial_gdf,
            overlap_threshold=landuse_overlap_threshold,
            poi_threshold=landuse_poi_threshold,
            source=source
        )

        ut.to_parquet(pre_landuse_cells, f"{save_folder}/3_afterfill_pre_landuse.parquet")
        pre_landuse_cells.write_parquet(f"{save_folder}/3_afterfill_pl_pre_landuse.parquet")
        filter_result.filtered.to_parquet(Path(save_folder) / "3_afterfill_landuse_filtered.parquet")
        filter_result.summary.to_csv(Path(save_folder) / "landuse_filter_summary.csv", index=False)
        if not filter_result.removed_cells.empty:
            filter_result.removed_cells.to_parquet(Path(save_folder) / "landuse_filter_removed_networks.parquet")
        else:
            removed_path = Path(save_folder) / "landuse_filter_removed_networks.parquet"
            if removed_path.exists():
                removed_path.unlink()
        filter_result.overlap_details.to_parquet(Path(save_folder) / "landuse_filter_overlap_details.parquet")

        filtered_df = filter_result.filtered.drop(columns="geometry")
        filt_cells_with_network = pl.from_pandas(filtered_df.reset_index(drop=True))

    # ----------------------------------------
    # Merge networks AFTER retail parks & landuse filter
    # ----------------------------------------
    if merge_adjacent:
        print("\n" + "="*80)
        print("MERGING ADJACENT NETWORKS (AFTER FILTERS)")
        print("="*80)

        n_networks_before = filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]
        print(f"Networks before merge: {n_networks_before}")

        filt_cells_with_network = network_merger.merge_networks_separated_by_one_cell(
            filt_cells_with_network, merge_h3_threshold=10
        )
        filt_cells_with_network = ut.join_networks_with_cells(
            filt_cells_with_network, input_cells
        )

        n_networks_after = filt_cells_with_network.select(pl.col('network_number').n_unique()).to_numpy()[0][0]
        print(f"Networks after merge: {n_networks_after}")
        print(f"Networks merged: {n_networks_before - n_networks_after}")
        print("="*80 + "\n")

    ut.to_parquet(filt_cells_with_network, f"{save_folder}/3_afterfill.parquet")
    filt_cells_with_network.write_parquet(f"{save_folder}/3_afterfill_pl.parquet")

    # ----------------------------------------
    # Run Leiden clustering to find subcentres
    # ----------------------------------------
    print("Running subcentre finder...")
    filt_cells_with_network = find_subcentres.run_leiden_clustering_polars(
        filt_cells_with_network,
        res=config.LEIDEN_RESOLUTION,
        alpha=config.LEIDEN_ALPHA,
        seed=config.LEIDEN_SEED,
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

    # ----------------------------------------
    # Add retail parks to final centres (if integrated)
    # ----------------------------------------
    if park_networks is not None:
        print("\nAdding retail parks to final centres...")

        # Dissolve park networks the same way as centres
        # (park_networks already has all required columns from join_networks_with_cells)
        park_dissolved = ut.dissolve_to_centres(park_networks)
        park_dissolved["geometry"] = park_dissolved["geometry"].apply(lambda geom: ut.fill_holes(geom))
        park_dissolved_gdf = gpd.GeoDataFrame(
            park_dissolved, geometry="geometry", crs="EPSG:27700"
        )
        park_dissolved_gdf = park_dissolved_gdf[
            ["network_number", "geometry", f"total_{source}_count", "trackNodes", 'Retail',
             'Dining and Drinking', 'Leisure & Travel', 'Community & Health', 'category_names']
        ]

        # Add centre_type flag
        dissolved_gdf['centre_type'] = 'centre'
        park_dissolved_gdf['centre_type'] = 'retail_park'

        # Combine centres and parks
        dissolved_combined = pd.concat([dissolved_gdf, park_dissolved_gdf], ignore_index=True)
        print(f"  Combined: {len(dissolved_gdf)} centres + {len(park_dissolved_gdf)} parks = {len(dissolved_combined)} total")
    else:
        dissolved_combined = dissolved_gdf
        dissolved_combined['centre_type'] = 'centre'

    # Rank by POI count (deterministic: tiebreak by centroid easting then northing)
    dissolved_combined["_centroid_x"] = dissolved_combined.geometry.centroid.x
    dissolved_combined["_centroid_y"] = dissolved_combined.geometry.centroid.y
    dissolved_combined = dissolved_combined.sort_values(
        [f"total_{source}_count", "_centroid_x", "_centroid_y"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    dissolved_combined["network_number"] = range(1, len(dissolved_combined) + 1)
    dissolved_combined = dissolved_combined.drop(columns=["_centroid_x", "_centroid_y"])
    dissolved_combined = dissolved_combined.rename(
        columns={
            "network_number": "RC_ID",
            f"total_{source}_count": "Total_POI_count",
            "trackNodes": "# H3 cells",
        }
    )

    # NOTE: post-processing merge of Leiden-split centres (e.g. Camden) is no
    # longer applied here. It is keyed by post-rank generated RC_IDs, which differ
    # between split-threshold sweeps and silently glued unrelated centres in the
    # nosplit run (e.g. Milton Keynes + Bexhill at RC_ID 130). The merge has been
    # moved to scripts/create_workshop_files_v2.py, applied to the split-run
    # centres after RC_ID restore so it can be keyed by stable RC_IDs.

    dissolved_combined.to_crs("EPSG:4326").to_parquet(f"{save_folder}/4_finalcentres.parquet")

    # ----------------------------------------
    # Add local authority names to final centres
    # ----------------------------------------
    dissolved_gdf_las = centre_postprocessing.add_localauthorities_to_centres(
        dissolved_combined
    )
    dissolved_gdf_las.to_crs("EPSG:4326").to_parquet(f"{save_folder}/4_finalcentres_las.parquet")
