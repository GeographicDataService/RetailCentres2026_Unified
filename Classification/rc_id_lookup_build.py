import geopandas as gpd
import pandas as pd


def build_rcid_lookup(
    new_rc_path: str = "geo/postworkshopcentres.gpkg",
    old_rc_path: str = "geo/old_retail_mapmaker/retail_boundaries_uk.gpkg",
    output_csv: str = "output/rcid_lookup_old_to_new.csv",
    metric_crs: str = "EPSG:27700",
) -> None:
    new_rcid = gpd.read_file(new_rc_path)
    old_rcid = gpd.read_file(old_rc_path)

    new_rcid = new_rcid.rename(columns={"RC_ID": "new_rcid"})

    # Ensure same CRS before reprojecting
    if new_rcid.crs != old_rcid.crs:
        old_rcid = old_rcid.to_crs(new_rcid.crs)

    new_rcid_metric = new_rcid.to_crs(metric_crs)
    old_rcid_metric = old_rcid.to_crs(metric_crs)

    intersections = gpd.overlay(
        old_rcid_metric[["RC_ID", "geometry"]],
        new_rcid_metric[["new_rcid", "geometry"]],
        how="intersection",
    )

    intersections["overlap_area_m2"] = intersections.geometry.area

    best_matches = (
        intersections
        .sort_values(["RC_ID", "overlap_area_m2"], ascending=[True, False])
        .drop_duplicates(subset=["RC_ID"])
        [["RC_ID", "new_rcid", "overlap_area_m2"]]
    )

    lookup = best_matches[["RC_ID", "new_rcid"]].copy()
    lookup.to_csv(output_csv, index=False)


def main() -> None:
    build_rcid_lookup()


if __name__ == "__main__":
    main()
