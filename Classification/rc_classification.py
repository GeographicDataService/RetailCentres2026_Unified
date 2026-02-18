import pandas as pd
import geopandas as gpd
from pathlib import Path
from shapely import wkt

#####-----1. Hierarchical Classification Functions -----#####
def apply_hierarchical_classification(
    df: pd.DataFrame,
    retail_park_rc_ids=None,
    id_col: str = "RC_ID",
) -> pd.DataFrame:
    df = df.copy()
    retail_park_rc_ids = set() if retail_park_rc_ids is None else set(retail_park_rc_ids)

    rank_specs = {
        "RGN_rank": "RegionName",
        "CTY_rank": "CountyName",
        "LAD_rank": "LAD24NM",
        "BUA_rank": "gsscode",
    }

    for rank_col, group_col in rank_specs.items():
        if rank_col in df.columns:
            continue
        mask = df[group_col].notna()
        df.loc[mask, rank_col] = df[mask].groupby(group_col)["LDC_retailN"].rank(
            method="first", ascending=False
        )
        df[rank_col] = df[rank_col].fillna(999999)

    df["tr_retailN"] = df.get("tr_retailN", df["LDC_retailN"])
    df["Classification"] = pd.Series(pd.NA, index=df.index)

    def assign(label: str, mask: pd.Series) -> None:
        df.loc[df["Classification"].isna() & mask, "Classification"] = label

    assign("Regional Centre", (df["RGN_rank"] == 1))
    # assign(
    #     "Major Town Centre",
    #     (df["CTY_rank"] == 1) & (df["RGN_rank"] != 1) & (df["LDC_retailN"] >= 350),
    # )
    assign(
        "Major Town Centre",
        ((df["CTY_rank"] == 1) & (df["RGN_rank"] != 1)) # change this to OR condition
        | (df["LDC_retailN"] >= 500) # change the treshold to 500
        | (
            (df["LAD_rank"] == 1) & (df["RGN_rank"] != 1 ) & (df["CTY_rank"] != 1) & (df["LDC_retailN"] >= 600) # change to 600
        ),
    )
    assign(
        "Town Centre",
        (
            (df["CTY_rank"] == 1)
            & (df["RGN_rank"] != 1)
            & (df["LDC_retailN"] >= 250)
            & (df["LDC_retailN"] < 500) #change to 500 rather 350
        )
        | (
            (df["LAD_rank"] == 1)
            & (df["CTY_rank"] != 1)
            & (df["RGN_rank"] != 1)
        ),
    )

    assign(
        "Market Town",
        (df["BUA_rank"] == 1)
        & (df["LAD_rank"] != 1)
        & (df["RGN_rank"] != 1)
        & (df["CTY_rank"] != 1)
        & (df["tr_retailN"] >= 150)
        & (df["tr_retailN"] < 250),
    )
    assign(
        "District Centre",
        (df["BUA_rank"] != 1)
        & (df["LAD_rank"] != 1)
        & (df["RGN_rank"] != 1)
        & (df["CTY_rank"] != 1)
        & (df["tr_retailN"] >= 150),
    )
    assign("Local Centre", df["tr_retailN"] < 150)

    df.loc[(df["Classification"] == "Local Centre") & (df["tr_retailN"] < 100), "Classification"] = (
        "Small Local Centre"
    )

    df.loc[df["Classification"].isna() & df["LDC_retailN"].notna(), "Classification"] = "Market Town"
    df["Classification"] = df["Classification"].fillna("Small Local Centre")

    retail_park_mask = (df["centre_type"] == "retail_park") & (
        df["Classification"].isin(["Small Local Centre"])
    )

    df.loc[retail_park_mask, "Classification"] = "Retail Park"
    df.loc[(df["Classification"] == "Retail Park") & (df["tr_retailN"] < 25), "Classification"] = (
        "Small Retail Park"
    )
    df.loc[(df["Classification"] == "Retail Park") & (df["tr_retailN"] >= 25), "Classification"] = (
        "Large Retail Park" # change this threshold to 25 from 50
    )

    return df.sort_values(["RegionName", id_col]).reset_index(drop=True)

#####-----2. Manual Edits -----#####
def apply_manual_edits(
    df: pd.DataFrame,
    rcid_lookup_csv: str = "output/rcid_lookup_old_to_new.csv",
    manual_hierarchy_csv: str | None = None,
    group_col: str = "group_id",
) -> pd.DataFrame:
    df = df.copy()

    lookup = pd.read_csv(rcid_lookup_csv)
    old_to_new = {}
    for old_id, new_id in zip(lookup["RC_ID"], lookup["new_rcid"]):
        old_to_new.setdefault(old_id, []).append(new_id)

    def map_old_to_new_list(old_id: str):
        return old_to_new.get(old_id, [old_id])

    has_group = group_col in df.columns

    manual_classification_old = {
        "RC_EW_2920": "Market Town",
        "RC_SC_332": "Major Town Centre",
        "RC_EW_876": "Major Town Centre",
        "RC_EW_5564": "Major Town Centre",
        "RC_EW_61": "Major Town Centre",
        "RC_EW_3096": "Major Town Centre",
        "RC_EW_3254": "Major Town Centre",
        "RC_EW_3301": "Major Town Centre",
        "RC_EW_3476": "Major Town Centre",
        "RC_EW_3522": "Regional Centre",
        "RC_EW_2751": "Regional Centre",
        "RC_SC_280": "Regional Centre",
    }

    for old_id, cls in manual_classification_old.items():
        new_ids = map_old_to_new_list(old_id)
        if has_group:
            target_groups = df.loc[df["RC_ID"].isin(new_ids), group_col].unique()
            df.loc[df[group_col].isin(target_groups), "Classification"] = cls
        else:
            df.loc[df["RC_ID"].isin(new_ids), "Classification"] = cls

    if manual_hierarchy_csv:
        manual_path = Path(manual_hierarchy_csv)
        if manual_path.exists():
            rc_manual = pd.read_csv(manual_path)
            rc_manual = rc_manual.loc[
                rc_manual["H_Classification"] == "Major Town Centre", "RC_ID"
            ].dropna()

            new_ids = []
            for old_id in rc_manual.astype(str).unique():
                new_ids.extend(map_old_to_new_list(old_id))

            if has_group:
                target_groups = df.loc[df["RC_ID"].isin(new_ids), group_col].unique()
                mask = df[group_col].isin(target_groups) & (df["Classification"] == "Town Centre")
            else:
                mask = df["RC_ID"].isin(new_ids) & (df["Classification"] == "Town Centre")

            df.loc[mask, "Classification"] = "Major Town Centre"

    # --- Manual classification edits (NEW RC_IDs) ---
    manual_classification_new = {
        "29": "Regional Centre", #glasgow
    }

    for rcid, cls in manual_classification_new.items():
        if has_group:
            target_groups = df.loc[df["RC_ID"].astype(str) == str(rcid), group_col].unique()
            df.loc[df[group_col].isin(target_groups), "Classification"] = cls
        else:
            df.loc[df["RC_ID"].astype(str) == str(rcid), "Classification"] = cls

    return df

#####-----3. Shopping Outlet Overrides -----#####
def apply_shopping_outlet_overrides(
    df: pd.DataFrame,
    rc_uk_path: str = "geo/postworkshopcentres.gpkg",
    rcid_lookup_csv: str = "output/rcid_lookup_old_to_new.csv",
) -> pd.DataFrame:
    """
    Manual outlet locations (spatial intersection + explicit ID overrides).
    rc_uk_path: path to postworkshopcentres.gpkg
    rcid_lookup_csv: path to rcid_lookup_old_to_new.csv
    """
    df = df.copy()

    # --- RC_ID mapping (old -> new) ---
    lookup = pd.read_csv(rcid_lookup_csv)
    old_to_new = dict(zip(lookup["RC_ID"], lookup["new_rcid"]))

    def map_rcid(old_id: str) -> str:
        return old_to_new.get(old_id, old_id)

    # --- Manual outlet locations ---
    outlets = pd.DataFrame(
        [
            ("Regional Shopping Centre", "Westfield London", 51.50768597440922, -0.22088352838801395),
            ("Regional Shopping Centre", "Metrocentre", 54.957214904105754, -1.6674536751658506),
            ("Regional Shopping Centre", "Trafford Centre", 53.465100417291744, -2.347637851106119),
            ("Regional Shopping Centre", "Westfield Stratford City", 51.54425552636472, -0.004332458383472109),
            ("Regional Shopping Centre", "Bluewater", 51.43912203176112, 0.27160383738290644),
            ("Regional Shopping Centre", "intu Merry Hill", 52.48138718476229, -2.110658395511001),
            ("Regional Shopping Centre", "Lakeside Shopping Centre", 51.489406902239956, 0.2853764470235825),
            ("Regional Shopping Centre", "Meadowhall", 53.41411230589209, -1.4111151687565566),
            ("Regional Shopping Centre", "East Kilbride Shopping Centre", 55.76021412051323, -4.17708950101207),
            ("Regional Shopping Centre", "Silverburn Centre", 55.82112954772368, -4.341253330960348),
            ("Regional Shopping Centre", "intu Braehead", 55.87600450967236, -4.364642953985305),
            ("Regional Shopping Centre", "White Rose Centre", 53.75868081616114, -1.5734907774777223),
            ("Large Outlet Shopping Centre", "Ashford Designer Outlet", 51.137387301260496, 0.8801687441992894),
            ("Large Outlet Shopping Centre", "Astle Park West Bromwich", 52.520103339621166, -1.9960259925402608),
            ("Large Outlet Shopping Centre", "Bicester Outlet Village", 51.89237714202758, -1.1560770883204268),
            ("Large Outlet Shopping Centre", "Bideford Atlantic Village", 51.00755545946937, -4.237327761297502),
            #("Large Outlet Shopping Centre", "Burberry Factory Outlet London", 51.54651001026377, -0.05093197052890261),
            ("Large Outlet Shopping Centre", "Castleford Junction 32 Outlet", 53.712463797168354, -1.3388364244282458),
            ("Large Outlet Shopping Centre", "Chatham Dockside Outlet Centre", 51.40160304040388, 0.5377104489852201),
            ("Large Outlet Shopping Centre", "Cheshire Oaks Designer Outlet", 53.26539272808919, -2.8809029974792315),
            ("Large Outlet Shopping Centre", "Clacton Factory Outlet", 51.81858769266023, 1.168209463308007),
            ("Large Outlet Shopping Centre", "Clarks Village Outlet Somerset", 51.12833201493458, -2.741588552823589),
            ("Large Outlet Shopping Centre", "Dalton Park Outlet", 54.81537131857434, -1.3739226162513756),
            ("Large Outlet Shopping Centre", "Doncaster Lakeside Village", 53.50769203205623, -1.1135984485990036),
            ("Large Outlet Shopping Centre", "Dover De Bradelei Wharf Outlet", 51.12211019226935, 1.3141697547138849),
            ("Large Outlet Shopping Centre", "East Midlands Outlet Junction 28", 53.108083884731556, -1.3126583496100666),
            ("Large Outlet Shopping Centre", "Freeport Braintree", 51.870070700810075, 0.5714801267433955),
            ("Large Outlet Shopping Centre", "Freeport Fleetwood Outlet", 53.91786152727727, -3.0118505404061744),
            ("Large Outlet Shopping Centre", "Freeport Talke Stoke-on-Trent", 53.070597467076176, -2.263078253210015),
            ("Large Outlet Shopping Centre", "Gloucester Quays Outlet", 51.85953205593224, -2.2516156614946916),
            ("Large Outlet Shopping Centre", "Hertfordshire Galleria Outlet Shopping", 51.76141229905345, -0.24021860677316503),
            ("Large Outlet Shopping Centre", "Hornsea Freeport Outlet", 53.898485374967684, -0.1724229262407349),
            ("Large Outlet Shopping Centre", "Kilver Court Designer Village", 51.19063584650441, -2.5353243560244905),
            ("Large Outlet Shopping Centre", "London Designer Outlet Wembley", 51.55646778421662, -0.28320440479433673),
            ("Large Outlet Shopping Centre", "Lowry Outlet Salford Quays", 53.47092253822526, -2.292514874626797),
            ("Large Outlet Shopping Centre", "Newcastle Royal Quays Outlet", 54.99532901611218, -1.4642812945442476),
            ("Large Outlet Shopping Centre", "Portsmouth Gunwharf Quays", 50.79546395254288, -1.103824062300293),
            ("Large Outlet Shopping Centre", "Springfields Spalding Outlet", 52.799438891276665, -0.126329033767297),
            ("Large Outlet Shopping Centre", "Swindon Designer Outlet", 51.56272470333755, -1.7971899666540831),
            ("Large Outlet Shopping Centre", "The Mill Outlet Batley", 53.7129199988173, -1.6251337290018772),
            ("Large Outlet Shopping Centre", "York Designer Outlet", 53.92233415376806, -1.0768705880781113),
            ("Large Outlet Shopping Centre", "Banbridge Village Outlet", 54.33172185692118, -6.276147653115943),
            ("Large Outlet Shopping Centre", "Cribbs Causeway", 51.524552488774034, -2.5955220725284307),
            ("Large Outlet Shopping Centre", "Bridgend Designer Outlets Wales", 51.532410963682594, -3.576839020076668),
            ("Large Outlet Shopping Centre", "Gretna Gateway Outlet Village", 54.99688074646182, -3.056523264134829),
            ("Large Outlet Shopping Centre", "Livingston Designer Outlet", 55.88310933797727, -3.520137944032474),
            ("Large Outlet Shopping Centre", "Sterling Mills Outlet", 56.14927287877639, -3.740053433726151),
        ],
        columns=["SubType", "Name", "Lat", "Lon"],
    )
    outlets["Type"] = "Out of Town Shopping Centres"

    outlets_gdf = gpd.GeoDataFrame(
        outlets,
        geometry=gpd.points_from_xy(outlets["Lon"], outlets["Lat"]),
        crs="EPSG:4326",
    )

    rc_uk = gpd.read_file(rc_uk_path)
    outlets_gdf = outlets_gdf.to_crs(rc_uk.crs)

    outlets_joined = gpd.sjoin(
        outlets_gdf,
        rc_uk[["RC_ID", "geometry"]],
        how="left",
        predicate="intersects",
    )
    outlets_tag = outlets_joined[["Type", "RC_ID"]].dropna(subset=["RC_ID"])

    manual_outlet_rcids_old = {
        "Ashford Designer Outlet": "RC_EW_1312",
        "Chatham Dockside Outlet Centre": "RC_EW_1529",
        "Doncaster Lakeside Village": "RC_EW_762",
        "Swindon Designer Outlet": "RC_EW_3751",
        "Springfields Spalding Outlet": "RC_EW_955",
    }

    manual_override = outlets_gdf[outlets_gdf["Name"].isin(manual_outlet_rcids_old)].copy()
    manual_override["RC_ID"] = manual_override["Name"].map(manual_outlet_rcids_old).map(map_rcid)
    manual_override = manual_override[["Type", "RC_ID"]].dropna(subset=["RC_ID"])

    outlets_tag = pd.concat([outlets_tag, manual_override], ignore_index=True)
    outlets_tag = outlets_tag.drop_duplicates(subset=["RC_ID"])

    df.loc[df["RC_ID"].isin(outlets_tag["RC_ID"]), "Classification"] = "Out of Town Shopping Centres"

    return df


def apply_out_of_town_sizing(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    out_of_town_mask = df["Classification"].isin(["Out of Town Shopping Centres"])

    df.loc[out_of_town_mask & (df["tr_retailN"] < 50), "Classification"] = "Small Shopping Centre"
    df.loc[out_of_town_mask & (df["tr_retailN"] >= 50), "Classification"] = "Large Shopping Centre"

    return df


#####-----4. Classification with Grouping -----#####
def classify_with_grouping(
    rc_geo: pd.DataFrame,
    rc_split: pd.DataFrame,
    parent_col: str = "Parent_ID",
    split_col: str = "was_split",
) -> pd.DataFrame:
    df = rc_geo.merge(
        rc_split[["RC_ID", split_col, parent_col]],
        on="RC_ID",
        how="left"
    )

    # if split file brings its own geometry, keep the rc_geo geometry
    if "geometry" not in df.columns and "geometry_x" in df.columns:
        df = df.rename(columns={"geometry_x": "geometry"})
        df = df.drop(columns=["geometry_y"], errors="ignore")

    # 1) build group_id
    is_split = df[split_col].astype(str).str.lower().isin(["true", "1", "yes"])
    df["group_id"] = df["RC_ID"].astype(str)
    df.loc[is_split, "group_id"] = "P_" + df.loc[is_split, parent_col].astype(str)

    # 2) build group-level table
    group_df = (
        df.groupby("group_id", dropna=False)
          .agg(
              LDC_retailN=("tr_retailN", "sum"),
              RegionName=("RegionName", "first"),
              CountyName=("CountyName", "first"),
              LAD24NM=("LAD24NM", "first"),
              gsscode=("gsscode", "first"),
              centre_type=("centre_type", "first"),
          )
          .reset_index()
    )

    # 3) classify at GROUP level
    group_df = apply_hierarchical_classification(group_df, id_col="group_id")
    group_df.rename(columns={"LDC_retailN": "group_LDC_retailN"}, inplace=True)

    # 4) merge group results back
    df = df.merge(
        group_df[["group_id", "group_LDC_retailN", "Classification"]],
        on="group_id",
        how="left"
    )

    # 5) apply overrides on row level
    df = apply_manual_edits(df)
    df = apply_shopping_outlet_overrides(df)
    df = apply_out_of_town_sizing(df)

    return df


def _maybe_parse_wkt(series: pd.Series) -> pd.Series:
    return series.apply(lambda geom: wkt.loads(geom) if isinstance(geom, str) else geom)


def _load_rc_geo(lookups_csv: str, ldc_csv: str, crs: str) -> gpd.GeoDataFrame:
    rc_lookups = pd.read_csv(lookups_csv)
    rc_ldc = pd.read_csv(ldc_csv)

    rc = rc_ldc.merge(
        rc_lookups.drop(columns=["geometry"], errors="ignore"),
        on="RC_ID",
        how="left",
    )

    # only pull geometry from lookups if rc_ldc doesn't already provide it
    if "geometry" not in rc.columns and "geometry" in rc_lookups.columns:
        rc = rc.merge(rc_lookups[["RC_ID", "geometry"]], on="RC_ID", how="left")

    if "geometry" in rc.columns:
        rc["geometry"] = _maybe_parse_wkt(rc["geometry"])
        return gpd.GeoDataFrame(rc, geometry="geometry", crs=crs)

    # no geometry available; return plain DataFrame
    return rc


#####----- Main Execution -----#####
def main() -> None:
    rc_lookups_csv = "output/rc_lookups_2011BUA.csv"
    rc_ldc_csv = "output/retail_centers_with_ldc_retailN.csv"
    split_path = "geo/postworkshopcentres_withsplit.gpkg"
    split_parent_col = "Parent_ID"
    split_flag_col = "was_split"

    output_gpkg = "output/rc2025_classified_10Feb.gpkg"
    crs = "EPSG:27700"

    rc_geo = _load_rc_geo(rc_lookups_csv, rc_ldc_csv, crs)

    if "tr_retailN" not in rc_geo.columns and "LDC_retailN" in rc_geo.columns:
        rc_geo["tr_retailN"] = rc_geo["LDC_retailN"]

    if "tr_retailN" not in rc_geo.columns and "LDC_retailN" in rc_geo.columns:
        rc_geo["tr_retailN"] = rc_geo["LDC_retailN"]


    if Path(split_path).exists():
        split_df = gpd.read_file(split_path)
        df_out = classify_with_grouping(
            rc_geo=rc_geo,
            rc_split=split_df,
            parent_col=split_parent_col,
            split_col=split_flag_col,
        )
    else:
        df_out = apply_hierarchical_classification(rc_geo)
        df_out = apply_manual_edits(df_out)
        df_out = apply_shopping_outlet_overrides(df_out)
        df_out = apply_out_of_town_sizing(df_out)

    if "geometry" not in df_out.columns and "geometry" in rc_geo.columns:
        df_out = df_out.merge(rc_geo[["RC_ID", "geometry"]], on="RC_ID", how="left")

    if "geometry" in df_out.columns:
        df_out["geometry"] = _maybe_parse_wkt(df_out["geometry"])
        out_gdf = gpd.GeoDataFrame(df_out, geometry="geometry", crs=crs)
        out_gdf.to_file(output_gpkg, driver="GPKG")
    else:
        # no geometry available; write a CSV instead
        output_csv = output_gpkg.replace(".gpkg", ".csv")
        df_out.to_csv(output_csv, index=False)

def run_classification(
    rc_lookups_csv="output/rc_lookups_2011BUA.csv",
    rc_ldc_csv="output/retail_centers_with_ldc_retailN.csv",
    split_path="geo/postworkshopcentres_withsplit.gpkg",
    split_parent_col="Parent_ID",
    split_flag_col="was_split",
    output_gpkg="output/rc2025_classified_10Feb.gpkg",
    crs="EPSG:27700",
):
    rc_geo = _load_rc_geo(rc_lookups_csv, rc_ldc_csv, crs)

    if "tr_retailN" not in rc_geo.columns and "LDC_retailN" in rc_geo.columns:
        rc_geo["tr_retailN"] = rc_geo["LDC_retailN"]

    if Path(split_path).exists():
        split_df = gpd.read_file(split_path)
        df_out = classify_with_grouping(
            rc_geo=rc_geo,
            rc_split=split_df,
            parent_col=split_parent_col,
            split_col=split_flag_col,
        )
    else:
        df_out = apply_hierarchical_classification(rc_geo)
        df_out = apply_manual_edits(df_out)
        df_out = apply_shopping_outlet_overrides(df_out)
        df_out = apply_out_of_town_sizing(df_out)

    if "geometry" not in df_out.columns and "geometry" in rc_geo.columns:
        df_out = df_out.merge(rc_geo[["RC_ID", "geometry"]], on="RC_ID", how="left")

    if "geometry" in df_out.columns:
        df_out["geometry"] = _maybe_parse_wkt(df_out["geometry"])
        out_gdf = gpd.GeoDataFrame(df_out, geometry="geometry", crs=crs)
        out_gdf.to_file(output_gpkg, driver="GPKG")
    else:
        output_csv = output_gpkg.replace(".gpkg", ".csv")
        df_out.to_csv(output_csv, index=False)

def main() -> None:
    run_classification()


if __name__ == "__main__":
    main()
