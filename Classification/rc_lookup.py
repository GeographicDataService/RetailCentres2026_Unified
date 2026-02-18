import geopandas as gpd
import pandas as pd


def build_rc_lookups(
    rc_path: str,
    lad_path: str,
    counties_path: str,
    regions_path: str,
    buildup_path: str,
    output_csv: str,
    lad_name_col: str = "LAD24NM",
    lad_code_col: str = "LAD24CD",
    county_name_col: str = "Name",
    region_name_col: str = "Name",
    buildup_code_col: str = "BUA11CD",
    buildup_name_col: str = "BUA11NM",
    buildup_id_col: str = "GlobalID",
) -> None:
    # ---------- Load retail centers ----------
    retail_centers = gpd.read_file(rc_path)[["RC_ID", "geometry"]]

    # ---------- LAD join ----------
    lad = gpd.read_file(lad_path).to_crs(retail_centers.crs)
    rc_lad = gpd.sjoin(retail_centers, lad, how="left", predicate="within")

    # centroid join for missing LAD
    unmerged = rc_lad[rc_lad[lad_name_col].isna()].copy()
    if not unmerged.empty:
        unmerged["geometry"] = unmerged.geometry.centroid
        centroid_join = gpd.sjoin(
            unmerged[["RC_ID", "geometry"]],
            lad[[lad_name_col, lad_code_col, "geometry"]],
            how="left",
            predicate="within",
        ).set_index("RC_ID")

        rc_lad = rc_lad.set_index("RC_ID")
        rc_lad[lad_name_col] = rc_lad[lad_name_col].where(
            rc_lad[lad_name_col].notna(), centroid_join[lad_name_col]
        )
        rc_lad[lad_code_col] = rc_lad[lad_code_col].where(
            rc_lad[lad_code_col].notna(), centroid_join[lad_code_col]
        )
        rc_lad = rc_lad.reset_index()

    # manual fix for RC_ID = 7183 (only if column exists)
    if "LocalAuthorityNM_1" in rc_lad.columns:
        rc_lad.loc[
            rc_lad["RC_ID"] == 7183,
            lad_name_col,
        ] = rc_lad.loc[
            rc_lad["RC_ID"] == 7183,
            "LocalAuthorityNM_1",
        ].values[0]

    # ---------- Counties ----------
    counties = gpd.read_file(counties_path).to_crs(retail_centers.crs)
    counties = counties[["geometry", county_name_col]].rename(columns={county_name_col: "CountyName"})
    counties["CountyName"] = counties["CountyName"].str.capitalize()

    rc_counties = gpd.sjoin(
        rc_lad[["RC_ID", "geometry", lad_name_col]],
        counties,
        how="left",
        predicate="within",
    )

    C_unmerged = rc_counties[rc_counties["CountyName"].isna()].copy()
    if not C_unmerged.empty:
        C_unmerged["geometry"] = C_unmerged.geometry.centroid
        C_centroid_join = gpd.sjoin(
            C_unmerged[["RC_ID", "geometry"]],
            counties,
            how="left",
            predicate="within",
        ).set_index("RC_ID")

        rc_counties = rc_counties.set_index("RC_ID")
        rc_counties["CountyName"] = rc_counties["CountyName"].where(
            rc_counties["CountyName"].notna(), C_centroid_join["CountyName"]
        )
        rc_counties = rc_counties.reset_index()

    rc_counties = rc_counties[["RC_ID", "geometry", lad_name_col, "CountyName"]]

    # ---------- Regions ----------
    regions = gpd.read_file(regions_path).to_crs(retail_centers.crs)
    regions = regions[["geometry", region_name_col]].rename(columns={region_name_col: "RegionName"})
    regions = regions[regions["RegionName"] != "England"]

    rc_regions = gpd.sjoin(rc_counties, regions, how="left", predicate="within")

    unmerged_r = rc_regions[rc_regions["RegionName"].isna()].copy()
    if not unmerged_r.empty:
        unmerged_r["geometry"] = unmerged_r.geometry.centroid
        r_centroid_join = gpd.sjoin(
            unmerged_r[["RC_ID", "geometry"]],
            regions,
            how="left",
            predicate="within",
        ).set_index("RC_ID")

        rc_regions = rc_regions.set_index("RC_ID")
        rc_regions["RegionName"] = rc_regions["RegionName"].where(
            rc_regions["RegionName"].notna(), r_centroid_join["RegionName"]
        )
        rc_regions = rc_regions.reset_index()

    rc_regions = rc_regions.drop(columns=["index_right"], errors="ignore")

    ni_counties = {"TYRONE", "ANTRIM", "ARMAGH", "FERMANAGH", "LONDONDERRY", "DOWN"}
    mask_ni = rc_regions["CountyName"].str.upper().isin(ni_counties)
    rc_regions.loc[mask_ni, "RegionName"] = "NI"

    # ---------- Buildup ----------
    buildup = gpd.read_file(buildup_path).to_crs(retail_centers.crs)
    buildup["gsscode"] = buildup[buildup_code_col]
    buildup["name1_text"] = buildup[buildup_name_col]
    buildup["fid"] = buildup[buildup_id_col]
    buildup = buildup[["gsscode", "geometry", "name1_text", "fid"]]

    rc_buildup = gpd.sjoin(retail_centers, buildup, how="left", predicate="within")

    B_unmerged = rc_buildup[rc_buildup["gsscode"].isna()].copy()
    if not B_unmerged.empty:
        B_unmerged["geometry"] = B_unmerged.geometry.centroid
        B_centroid_join = gpd.sjoin(
            B_unmerged[["RC_ID", "geometry"]],
            buildup,
            how="left",
            predicate="within",
        )
        centroid_lookup = (
            B_centroid_join.dropna(subset=["gsscode"])
            .set_index("RC_ID")["gsscode"]
        )
        rc_buildup.loc[rc_buildup["gsscode"].isna(), "gsscode"] = (
            rc_buildup.loc[rc_buildup["gsscode"].isna(), "RC_ID"].map(centroid_lookup)
        )

    B_still = rc_buildup[rc_buildup["gsscode"].isna()].copy()
    if not B_still.empty:
        B_intersect = gpd.sjoin(
            B_still[["RC_ID", "geometry"]],
            buildup[["gsscode", "geometry"]],
            how="left",
            predicate="intersects",
        )
        lookup = (
            B_intersect.dropna(subset=["gsscode"])
            .groupby("RC_ID")["gsscode"]
            .first()
        )
        rc_buildup.loc[rc_buildup["gsscode"].isna(), "gsscode"] = (
            rc_buildup.loc[rc_buildup["gsscode"].isna(), "RC_ID"].map(lookup)
        )

    # ---------- Final merge ----------
    rc_final = rc_regions.merge(rc_buildup[["RC_ID", "gsscode"]], on="RC_ID", how="left")
    rc_final.loc[rc_final["RegionName"] == "NI", "gsscode"] = "NI"

    rc_final.to_csv(output_csv, index=False)
    print(f"RC lookups between 2021paper RC_ID and new RC_IDsaved to {output_csv}")


def main() -> None:
    build_rc_lookups(
        rc_path="geo/postworkshopcentres.gpkg", 
        lad_path="geo/LA/Local_Authority_Districts_May_2024_Boundaries_UK_BFE_-5758551109064458912/LAD_MAY_2024_UK_BFE.shp",
        counties_path="geo/Counties/uk_27700.shp",
        regions_path="geo/Regions/GB_regions.shp",
        buildup_path="geo/buildup/Built_up_Areas_Dec_2011_Boundaries_V2_2022_-9186664123850227917.gpkg",
        output_csv="output/rc_lookups_2011BUA.csv",
    )


if __name__ == "__main__":
    main()
