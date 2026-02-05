import geopandas as gpd
import pandas as pd


def build_ldc_retail_counts(
    rc_path: str,
    ldc_csv: str,
    output_csv: str,
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

    unit_counts = joined.groupby("RC_ID").size().reset_index(name="LDC_retailN")
    rc_retailN = retail_centers.merge(unit_counts, on="RC_ID", how="left").fillna(0)
    rc_retailN.to_csv(output_csv, index=False)


    print(f"Saved retail center counts to {output_csv}")


def main() -> None:
    build_ldc_retail_counts(
        rc_path="geo/postworkshopcentres.gpkg",
        ldc_csv="data/LDC_Historical_snapshot_2015-01-01-2025-09-30.csv",
        output_csv="output/retail_centers_with_ldc_retailN1.csv",
    )

if __name__ == "__main__":
    main()
