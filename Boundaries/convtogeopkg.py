import geopandas as gpd

#load the data
data = gpd.read_parquet("data/output_files/retailcen_foursquare_mrc_3_mri_10_mrn_10_mtf_4_dissolved_filteraftermerge.parquet")
#save ti to geopackage
data.to_file("data/output_files/retailcen_foursquare_mrc_3_mri_10_mrn_10_mtf_4_dissolved_filteraftermerge.gpkg", driver="GPKG")
