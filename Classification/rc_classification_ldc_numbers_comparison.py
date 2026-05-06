import geopandas as gpd
import pandas as pd

from rc_classification import run_classification


def has_ldc_source(ldc_csv: str | None) -> bool:
    return bool(ldc_csv and str(ldc_csv).strip())


def _build_ldc_retail_counts(
    *,
    rc_path: str,
    ldc_csv: str,
    ldc_counts_csv: str,
) -> None:
    retail_centers = gpd.read_file(rc_path)
    ldc = pd.read_csv(ldc_csv)
    ldc_live = ldc[ldc["Status"] == "Live"].copy()

    poi_gdf = gpd.GeoDataFrame(
        ldc_live,
        geometry=gpd.points_from_xy(ldc_live.Longitude, ldc_live.Latitude),
        crs="EPSG:4326",
    ).to_crs(retail_centers.crs)

    joined = gpd.sjoin(
        poi_gdf,
        retail_centers[["RC_ID", "geometry"]],
        predicate="within",
    )

    unit_counts = joined.groupby("RC_ID").size().reset_index(name="unit_counts")
    rc_retailN = retail_centers.merge(unit_counts, on="RC_ID", how="left")
    rc_retailN["unit_counts"] = rc_retailN["unit_counts"].fillna(0).astype(int)
    rc_retailN["LDC_retailN"] = rc_retailN["unit_counts"]
    rc_retailN.to_csv(ldc_counts_csv, index=False)
    print(f"---3. Saved retail center counts to {ldc_counts_csv}")


def _merge_ldc_retail_counts(*, anchor_csv: str, ldc_counts_csv: str) -> None:
    anchors = pd.read_csv(anchor_csv)
    ldc = pd.read_csv(ldc_counts_csv)
    if "LDC_retailN" not in ldc.columns:
        raise KeyError(f"{ldc_counts_csv} does not contain LDC_retailN")

    anchors = anchors.drop(columns=["LDC_retailN"], errors="ignore")
    anchors = anchors.merge(
        ldc[["RC_ID", "LDC_retailN"]].drop_duplicates("RC_ID"),
        on="RC_ID",
        how="left",
    )
    anchors["LDC_retailN"] = anchors["LDC_retailN"].fillna(0).astype(int)
    anchors.to_csv(anchor_csv, index=False)


def run_ldc_numbers_comparison(
    *,
    rc_path: str,
    ldc_csv: str | None,
    ldc_counts_csv: str,
    anchor_csv: str,
    rc_lookups_csv: str,
    rc_counts_csv: str,
    split_path: str,
    split_parent_col: str,
    split_flag_col: str,
    output_gpkg: str,
    crs: str,
    retailN_col: str,
    rcid_lookup_csv: str,
    rc_uk_path: str,
    manual_hierarchy_csv: str | None = None,
    anchor_district_to_town_threshold: int,
    london_split_override_enabled: bool = True,
    london_region_name: str = "London",
    london_town_centres_path: str | None = None,
    london_town_centres_layer: str | None = None,
    london_town_centres_sitename_col: str = "sitename",
    london_town_centres_min_overlap_ratio: float = 0.05,
    rc_ldc_csv: str | None = None,
) -> bool:
    if not has_ldc_source(ldc_csv):
        print("---3. LDC numbers comparison skipped: ldc_csv is blank.")
        return False

    _build_ldc_retail_counts(
        rc_path=rc_path,
        ldc_csv=ldc_csv,
        ldc_counts_csv=ldc_counts_csv,
    )
    _merge_ldc_retail_counts(anchor_csv=anchor_csv, ldc_counts_csv=ldc_counts_csv)
    run_classification(
        rc_lookups_csv=rc_lookups_csv,
        rc_counts_csv=rc_counts_csv,
        split_path=split_path,
        split_parent_col=split_parent_col,
        split_flag_col=split_flag_col,
        output_gpkg=output_gpkg,
        crs=crs,
        retailN_col=retailN_col,
        rcid_lookup_csv=rcid_lookup_csv,
        rc_uk_path=rc_uk_path,
        manual_hierarchy_csv=manual_hierarchy_csv,
        anchor_district_to_town_threshold=anchor_district_to_town_threshold,
        london_split_override_enabled=london_split_override_enabled,
        london_region_name=london_region_name,
        london_town_centres_path=london_town_centres_path,
        london_town_centres_layer=london_town_centres_layer,
        london_town_centres_sitename_col=london_town_centres_sitename_col,
        london_town_centres_min_overlap_ratio=london_town_centres_min_overlap_ratio,
        rc_ldc_csv=rc_ldc_csv,
    )
    return True


def main() -> None:
    run_ldc_numbers_comparison(
        rc_path="geo/postworkshopcentres.gpkg",
        ldc_csv="data/LDC_Historical_snapshot_2015-01-01-2025-09-30.csv",
        ldc_counts_csv="output/retail_centers_with_ldc_retailN.csv",
        anchor_csv="output/retail_centers_with_foursquare_anchorN.csv",
        rc_lookups_csv="output/rc_lookups_2011BUA.csv",
        split_path="geo/postworkshopcentres_withsplit.gpkg",
        split_parent_col="Parent_ID",
        split_flag_col="was_split",
        output_gpkg="output/rc2025_foursquareAnchors_LDCNumbers.gpkg",
        crs="EPSG:27700",
        retailN_col="LDC_retailN",
        rcid_lookup_csv="output/rcid_lookup_old_to_new.csv",
        rc_uk_path="geo/postworkshopcentres.gpkg",
        anchor_district_to_town_threshold=3,
    )


if __name__ == "__main__":
    main()
