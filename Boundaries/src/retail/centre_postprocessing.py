import geopandas as gpd
import numpy as np

def add_localauthorities_to_centres(retail_centres: gpd.GeoDataFrame):
    """
    Adds local authority information to retail centres.
    Handles cases where a retail centre intersects with multiple LAs.
    """

    # Load Local Authority boundaries and set CRS
    UK_LAD = gpd.read_file("data/Boundaries_lookups/Local_Authority_Districts_December_2022_UK_BGC_V2_5759908710055972638.gpkg")[['LAD22CD', 'LAD22NM', 'geometry']]
    UK_LAD['LocalAuthorityTY'] = UK_LAD['LAD22CD'].map(lambda x: {
        'E0': 'LAD22CD',
        'W06': 'LAD22CD',
        'S12': 'CouncilArea20CD',
        'N09': 'LGD14CD'
    }.get(x[:3], None))
    UK_LAD = UK_LAD.to_crs(retail_centres.crs)

    # Spatial intersection and area computation
    RC_int = gpd.overlay(retail_centres, UK_LAD, how='intersection')[['RC_ID', 'LAD22CD', 'LAD22NM', 'geometry']]
    RC_int = RC_int.assign(area_km2=RC_int.geometry.area * 1e-6)

    # Count number of LA overlaps per centre
    area_stats = RC_int.groupby('RC_ID')['area_km2'].agg(['count', 'sum']).rename(columns={'count': 'N', 'sum': 'Tarea'}).reset_index()
    RC_int = RC_int.merge(area_stats, on='RC_ID')
    RC_int['Prop'] = RC_int['area_km2'] / RC_int['Tarea']

    # Keep only significant overlaps (>10%)
    RC_filtered = RC_int[RC_int['Prop'] > 0.1].copy()

    # Sort and keep top 3 overlaps per centre
    RC_filtered = RC_filtered.sort_values(['RC_ID', 'Prop'], ascending=[True, False])
    RC_filtered['Number'] = RC_filtered.groupby('RC_ID').cumcount() + 1
    RC_filtered = RC_filtered[RC_filtered['Number'] <= 3]

    # Pivot to wide format
    pivoted = RC_filtered.pivot(index='RC_ID', columns='Number', values=['LAD22CD', 'LAD22NM', 'Prop'])
    pivoted.columns = [f'{a}_{b}' for a, b in pivoted.columns]
    pivoted = pivoted.reset_index()

    rename_cols = {}
    for i in range(1, 4):
        rename_cols[f'LAD22CD_{i}'] = f'LocalAuthorityCD_{i}'
        rename_cols[f'LAD22NM_{i}'] = f'LocalAuthorityNM_{i}'
        rename_cols[f'Prop_{i}'] = f'LocalAuthority_{i}_Prop'

    pivoted = pivoted.rename(columns=rename_cols)

    # Merge authority type
    auth_type = UK_LAD[['LAD22CD', 'LocalAuthorityTY']].drop_duplicates()
    pivoted = pivoted.merge(auth_type, left_on='LocalAuthorityCD_1', right_on='LAD22CD', how='left').drop(columns='LAD22CD')

    # Reorder final columns
    final_cols = ['RC_ID', 'LocalAuthorityNM_1','LocalAuthorityNM_2', 'LocalAuthorityNM_3']
    for col in final_cols:
        if col not in pivoted.columns:
            pivoted[col] = np.nan
    pivoted = pivoted[final_cols]

    # Merge back into retail_centres
    return retail_centres.merge(pivoted, on='RC_ID', how='left')


