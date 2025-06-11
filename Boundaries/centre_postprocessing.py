import geopandas as gpd
from matplotlib import pyplot as plt
import pandas as pd
import networkx as nx
import h3
from networkx.algorithms.community import louvain_communities
import igraph as ig
import leidenalg
import networkx as nx
import igraph as ig
import leidenalg
import geopandas as gpd
import pandas as pd
import h3
from tqdm import tqdm
from pathlib import Path
import numpy as np
import random
seed = 505
random.seed(seed)        # or any integer
np.random.seed(seed)

def create_RC_IDs(retail_centres: gpd.GeoDataFrame):
    """
    Creates unique RC_IDs for each retail centre, following the pattern:
    'RC_CC_XXXXXX', where CC is the County cide EW, NI or SC for England, Wales, Northern Ireland or Scotland respectively, and XXXX is the size ranking of the RC by POI number
    """


def add_localauthorities_to_centres(retail_centres: gpd.GeoDataFrame):
    """
    Adds local authority information to retail centres.
    """

    # ONS NAMING - LOCAL AUTHORITY LEVEL BREAKDOWN
    UK_LAD = gpd.read_file(f"data/Boundaries_lookups/Local_Authority_Districts_December_2022_UK_BGC_V2_5759908710055972638.gpkg")[['LAD22CD', 'LAD22NM', 'geometry']]

    # Add LocalAuthorityTY column based on LAD22CD patterns
    conditions = [
        UK_LAD['LAD22CD'].str.startswith('E0'),
        UK_LAD['LAD22CD'].str.startswith('W06'),
        UK_LAD['LAD22CD'].str.startswith('S12'),
        UK_LAD['LAD22CD'].str.startswith('N09')
    ]
    choices = ['LAD22CD', 'LAD22CD', 'CouncilArea20CD', 'LGD14CD']
    UK_LAD['LocalAuthorityTY'] = np.select(conditions, choices, default=None)

    UK_LAD = UK_LAD.to_crs(retail_centres.crs)

    # Spatial intersection
    RC_int = gpd.overlay(retail_centres, UK_LAD, how='intersection')[['RC_ID', 'LAD22CD', 'LAD22NM', 'geometry']]
    RC_int['area_km2'] = RC_int.geometry.area * 1e-6

    # Count intersections per RC_ID
    intersection_counts = RC_int.groupby('RC_ID').agg({'area_km2': ['count', 'sum']}).reset_index()
    intersection_counts.columns = ['RC_ID', 'N', 'Size']

    # Handle single intersections
    single_intersections = intersection_counts[intersection_counts['N'] == 1]['RC_ID']
    RC_int1 = RC_int[RC_int['RC_ID'].isin(single_intersections)].copy()
    RC_int1 = RC_int1[['RC_ID', 'LAD22CD', 'LAD22NM']].copy()
    RC_int1.columns = ['RC_ID', 'LocalAuthorityCD', 'LocalAuthorityNM']
    RC_int1['Prop'] = 1.0

    # Handle multiple intersections
    multiple_intersections = intersection_counts[intersection_counts['N'] > 1]['RC_ID']
    RC_int2 = RC_int[RC_int['RC_ID'].isin(multiple_intersections)].copy()
    RC_int2 = RC_int2[['RC_ID', 'LAD22CD', 'LAD22NM', 'area_km2']].copy()

    # Calculate proportions
    total_areas = RC_int2.groupby('RC_ID')['area_km2'].sum().reset_index()
    total_areas.columns = ['RC_ID', 'Tarea']
    RC_int2 = RC_int2.merge(total_areas, on='RC_ID')
    RC_int2['Prop'] = RC_int2['area_km2'] / RC_int2['Tarea']
    RC_int2 = RC_int2[RC_int2['Prop'] > 0.1]  # Filter significant overlaps

    # Handle non-duplicated entries
    non_duplicated = RC_int2.drop_duplicates('RC_ID', keep=False)
    t = non_duplicated[['RC_ID', 'LAD22CD', 'LAD22NM', 'Prop']].copy()
    t.columns = ['RC_ID', 'LocalAuthorityCD', 'LocalAuthorityNM', 'Prop']
    RC_LADs = pd.concat([RC_int1, t], ignore_index=True)

    # Handle duplicated entries (multiple authorities per retail center)
    duplicated_mask = RC_int2.duplicated('RC_ID', keep=False)
    duplicated_entries = RC_int2[duplicated_mask].copy()
    duplicated_entries = duplicated_entries[['RC_ID', 'LAD22CD', 'LAD22NM', 'Prop']]
    duplicated_entries.columns = ['RC_ID', 'LocalAuthorityCD', 'LocalAuthorityNM', 'Prop']
    duplicated_entries = duplicated_entries.sort_values(['RC_ID', 'Prop'], ascending=[True, False])

    # Add ranking numbers
    duplicated_entries['Number'] = duplicated_entries.groupby('RC_ID').cumcount() + 1

    # Pivot to separate columns for each authority
    authority_pivot = duplicated_entries.pivot_table(
        index='RC_ID', 
        columns='Number', 
        values=['LocalAuthorityCD', 'LocalAuthorityNM', 'Prop'], 
        aggfunc='first'
    ).reset_index()

    # Flatten column names
    authority_pivot.columns = [f'{col[0]}_{col[1]}' if col[1] != '' else col[0] 
                            for col in authority_pivot.columns]

    # Rename columns to match expected format
    rename_dict = {}
    for i in range(1, 4):  # Up to 3 authorities
        if f'LocalAuthorityCD_{i}' in authority_pivot.columns:
            rename_dict.update({
                f'LocalAuthorityCD_{i}': f'LocalAuthorityCD_{i}',
                f'LocalAuthorityNM_{i}': f'LocalAuthorityNM_{i}',
                f'Prop_{i}': f'LocalAuthority_{i}_Prop'
            })

    authority_pivot = authority_pivot.rename(columns=rename_dict)

    # Ensure RC_LADs has the same structure
    RC_LADs = RC_LADs.rename(columns={
        'LocalAuthorityCD': 'LocalAuthorityCD_1',
        'LocalAuthorityNM': 'LocalAuthorityNM_1',
        'Prop': 'LocalAuthority_1_Prop'
    })

    # Combine all authority data
    RC_LADs = pd.concat([RC_LADs, authority_pivot], ignore_index=True, sort=False)

    # Add LocalAuthorityTY from UK_LAD
    authority_types = UK_LAD[['LAD22CD', 'LocalAuthorityTY']].drop_duplicates()
    RC_LADs = RC_LADs.merge(authority_types, left_on='LocalAuthorityCD_1', right_on='LAD22CD', how='left')
    RC_LADs = RC_LADs.drop('LAD22CD', axis=1)

    # Reorder columns
    expected_cols = ['RC_ID', 'LocalAuthorityTY', 'LocalAuthorityCD_1', 'LocalAuthorityNM_1', 
                    'LocalAuthority_1_Prop', 'LocalAuthorityCD_2', 'LocalAuthorityNM_2', 
                    'LocalAuthority_2_Prop', 'LocalAuthorityCD_3', 'LocalAuthorityNM_3', 
                    'LocalAuthority_3_Prop']
    RC_LADs = RC_LADs.reindex(columns=expected_cols)

    print("Local Authority processing complete.")
    # add the LocalAuthorityNMs columns to the retail centres df
    for col in RC_LADs.columns:
        if col.startswith('LocalAuthorityNM'):
            retail_centres[col] = RC_LADs[col]
    return retail_centres


