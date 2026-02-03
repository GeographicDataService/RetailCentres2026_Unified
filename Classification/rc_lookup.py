import geopandas as gpd
import pandas as pd

# ---------- Load retail centers ----------
retail_centers = gpd.read_file("geo/postworkshopcentres.gpkg")
retail_centers = retail_centers[["RC_ID", "geometry"]]

# ---------- LAD join ----------
lad = gpd.read_file(
    "geo/LA/Local_Authority_Districts_May_2024_Boundaries_UK_BFE_-5758551109064458912/LAD_MAY_2024_UK_BFE.shp"
)
lad = lad.to_crs(retail_centers.crs)

rc_lad = gpd.sjoin(
    retail_centers,
    lad,
    how="left",
    predicate="within"
)

# dealing with unmerged
unmerged_mask = rc_lad["LAD24NM"].isna()
unmerged = rc_lad[unmerged_mask].copy()

# centroid join for missing
unmerged_centroids = unmerged.loc[:, :"geometry"].copy()
unmerged_centroids["geometry"] = unmerged_centroids.geometry.centroid

centroid_join = gpd.sjoin(
    unmerged_centroids[["RC_ID", "geometry"]],
    lad[["LAD24NM", "LAD24CD", "geometry"]],
    how="left",
    predicate="within"
)

rc_lad = rc_lad.set_index("RC_ID")
centroid_join = centroid_join.set_index("RC_ID")

# fill missing LAD values from centroid join without chained inplace updates
rc_lad["LAD24NM"] = rc_lad["LAD24NM"].where(
    rc_lad["LAD24NM"].notna(), centroid_join["LAD24NM"]
)
rc_lad["LAD24CD"] = rc_lad["LAD24CD"].where(
    rc_lad["LAD24CD"].notna(), centroid_join["LAD24CD"]
)

rc_lad = rc_lad.reset_index()

# manual fix for RC_ID = 7183 (only if the column exists)
if "LocalAuthorityNM_1" in rc_lad.columns:
    rc_lad.loc[
        rc_lad["RC_ID"] == 7183,
        "LAD24NM"
    ] = rc_lad.loc[
        rc_lad["RC_ID"] == 7183,
        "LocalAuthorityNM_1"
    ].values[0]

# ---------- Counties ----------
counties = gpd.read_file("geo/Counties/uk_27700.shp")
counties = counties.to_crs(retail_centers.crs)
counties = counties[["geometry", "Name"]]
counties["Name"] = counties["Name"].str.capitalize()
counties.rename(columns={"Name": "CountyName"}, inplace=True)

rc_counties = gpd.sjoin(
    rc_lad[["RC_ID", "geometry", "LAD24NM"]],
    counties,
    how="left",
    predicate="within"
)

C_unmerged = rc_counties[rc_counties["CountyName"].isna()].copy()
C_unmerged_centroids = C_unmerged.copy()
C_unmerged_centroids["geometry"] = C_unmerged_centroids.geometry.centroid

C_centroid_join = gpd.sjoin(
    C_unmerged_centroids[["RC_ID", "geometry"]],
    counties,
    how="left",
    predicate="within"
)


rc_counties = rc_counties.set_index("RC_ID")
C_centroid_join = C_centroid_join.set_index("RC_ID")

rc_counties["CountyName"] = rc_counties["CountyName"].where(
    rc_counties["CountyName"].notna(), C_centroid_join["CountyName"]
)

rc_counties = rc_counties.reset_index()

rc_counties = rc_counties[["RC_ID", "geometry", "LAD24NM", "CountyName"]]

# ---------- Regions ----------
GB_regions = gpd.read_file("geo/Regions/GB_regions.shp")
GB_regions = GB_regions.to_crs(retail_centers.crs)
GB_regions = GB_regions[["geometry", "Name"]]
GB_regions.rename(columns={"Name": "RegionName"}, inplace=True)
GB_regions = GB_regions[GB_regions["RegionName"] != "England"]

rc_counties_region = gpd.sjoin(
    rc_counties,
    GB_regions,
    predicate="within",
    how="left"
)

# centroid join for missing regions
rc_centroids = rc_counties_region.copy()
rc_centroids["geometry"] = rc_centroids.geometry.centroid

rc_counties_region_join = gpd.sjoin(
    rc_centroids[["RC_ID", "geometry"]],
    GB_regions,
    how="left",
    predicate="within"
)

region_lookup = (
    rc_counties_region_join
    .dropna(subset=["RegionName"])
    .set_index("RC_ID")["RegionName"]
)

rc_counties_region["RegionName"] = rc_counties_region["RC_ID"].map(region_lookup)

# manual check for NI counties
ni_counties = [
    "TYRONE",
    "ANTRIM",
    "ARMAGH",
    "FERMANAGH",
    "LONDONDERRY",
    "DOWN"
]
mask_ni = rc_counties_region["CountyName"].str.upper().isin(ni_counties)
rc_counties_region.loc[mask_ni, "RegionName"] = "NI"

rc_counties_region = rc_counties_region.drop(columns=["index_right"])

# ---------- Output LA/County/Region lookups ----------
#rc_counties_region.to_csv("output/rc_la_county_region_lookups.csv", index=False)

# ---------- Buildup ----------
#buildup = gpd.read_file("geo/buildup/buildup.shp")
# 2011 version-----
buildup = gpd.read_file(
    "geo/buildup/Built_up_Areas_Dec_2011_Boundaries_V2_2022_-9186664123850227917.gpkg"
)
buildup["gsscode"] = buildup["BUA11CD"]
buildup["name1_text"] = buildup["BUA11NM"]
buildup["fid"] = buildup["GlobalID"]
#----------------
buildup = buildup.to_crs(retail_centers.crs)
buildup = buildup[["gsscode", "geometry", "name1_text", "fid"]]

rc_buildup = gpd.sjoin(
    retail_centers,
    buildup,
    how="left",
    predicate="within"
)

# centroid join for missing gsscode
B_unmerged = rc_buildup[rc_buildup["gsscode"].isna()].copy()
B_unmerged_centroids = B_unmerged.copy()
B_unmerged_centroids["geometry"] = B_unmerged_centroids.geometry.centroid

B_centroid_join = gpd.sjoin(
    B_unmerged_centroids[["RC_ID", "geometry"]],
    buildup,
    how="left",
    predicate="within"
)

centroid_lookup = (
    B_centroid_join
    .dropna(subset=["gsscode"])
    .set_index("RC_ID")["gsscode"]
)

rc_buildup.loc[
    rc_buildup["gsscode"].isna(),
    "gsscode"
] = rc_buildup.loc[
    rc_buildup["gsscode"].isna(),
    "RC_ID"
].map(centroid_lookup)

# intersects join for still missing
B_still_unmerged = rc_buildup[rc_buildup["gsscode"].isna()].copy()
B_intersect_join = gpd.sjoin(
    B_still_unmerged[["RC_ID", "geometry"]],
    buildup[["gsscode", "geometry"]],
    how="left",
    predicate="intersects"
)

lookup = (
    B_intersect_join
    .dropna(subset=["gsscode"])
    .groupby("RC_ID")["gsscode"]
    .first()
)

rc_buildup.loc[
    rc_buildup["gsscode"].isna(),
    "gsscode"
] = rc_buildup.loc[
    rc_buildup["gsscode"].isna(),
    "RC_ID"
].map(lookup)

# ---------- Final merge ----------
rc_final = rc_counties_region.merge(
    rc_buildup[["RC_ID", "gsscode"]],
    on="RC_ID",
    how="left"
)

# manual NI gsscode
rc_final.loc[rc_final["RegionName"] == "NI", "gsscode"] = "NI"

rc_final.to_csv("output/rc_lookups_2011BUA.csv", index=False)
print("RC lookups with 2011 BUA saved to output/rc_lookups_2011BUA.csv")