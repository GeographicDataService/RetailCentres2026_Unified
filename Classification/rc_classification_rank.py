import pandas as pd
import geopandas as gpd
from pathlib import Path
from shapely import wkt

from rc_classification_rerank import (
    apply_hierarchical_classification,
    apply_manual_edits,
    apply_out_of_town_sizing,
    apply_shopping_outlet_overrides,
    classify_with_grouping,
)


def _maybe_parse_wkt(series: pd.Series) -> pd.Series:
    return series.apply(lambda geom: wkt.loads(geom) if isinstance(geom, str) else geom)


def _load_rc_geo(lookups_csv: str, ldc_csv: str, crs: str) -> pd.DataFrame:
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

    return rc


def build_rank_table(
    rc_lookups_csv: str = "output/old_rc/rc_lookups_2011BUA.csv",
    rc_ldc_csv: str = "output/old_rc/retail_centers_with_ldc_retailN.csv",
    split_path: str = "geo/postworkshopcentres_withsplit.gpkg",
    split_parent_col: str = "Parent_ID",
    split_flag_col: str = "was_split",
    output_csv: str = "output/rc_rank_table.csv",
    crs: str = "EPSG:27700",
) -> pd.DataFrame:
    df = _load_rc_geo(rc_lookups_csv, rc_ldc_csv, crs)

    if "tr_retailN" not in df.columns and "LDC_retailN" in df.columns:
        df["tr_retailN"] = df["LDC_retailN"]

    def add_ranks(frame: pd.DataFrame) -> pd.DataFrame:
        ranked = frame.copy()
        rank_specs = {
            "RGN_rank": "RegionName",
            "CTY_rank": "CountyName",
            "LAD_rank": "LAD24NM",
            "BUA_rank": "gsscode",
        }

        for rank_col, group_col in rank_specs.items():
            if rank_col in ranked.columns:
                continue
            mask = ranked[group_col].notna()
            ranked.loc[mask, rank_col] = ranked[mask].groupby(group_col)["LDC_retailN"].rank(
                method="first", ascending=False
            )
            ranked[rank_col] = ranked[rank_col].fillna(999999)

        return ranked

    if Path(split_path).exists():
        split_df = gpd.read_file(split_path)
        df_out = classify_with_grouping(
            rc_geo=df,
            rc_split=split_df,
            parent_col=split_parent_col,
            split_col=split_flag_col,
        )
    else:
        df_out = apply_hierarchical_classification(df)
        df_out = apply_manual_edits(df_out)
        df_out = apply_shopping_outlet_overrides(df_out)
        df_out = apply_out_of_town_sizing(df_out)

    ranked_df = add_ranks(df_out)

    out_cols = [
        "RC_ID",
        "RegionName",
        "CountyName",
        "LAD24NM",
        "gsscode",
        "RGN_rank",
        "CTY_rank",
        "LAD_rank",
        "BUA_rank",
        "LDC_retailN",
        "group_retailN",
        "Classification",
    ]
    out_cols = [c for c in out_cols if c in ranked_df.columns]

    out_df = ranked_df[out_cols].copy()
    out_df.to_csv(output_csv, index=False)
    return out_df


def main() -> None:
    build_rank_table()


if __name__ == "__main__":
    main()
