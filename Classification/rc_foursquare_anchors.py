from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd


FoursquareBrandConfig = dict[str, list[str]]

FSQ_ANCHOR_BRANDS: FoursquareBrandConfig = {
    "high_street_fashion": [
        "next", "h&m", "zara", "tk maxx", "river island",
        "primark", "jack wills", "white stuff", "fat face",
        "crew clothing", "seasalt", "joules", "lacoste",
        "diesel", "hugo boss", "tommy hilfiger",
    ],
    "department_stores": [
        "john lewis", "harvey nichols", "marks & spencer", "m&s", "ikea", "house of fraser",
    ],
    "jewellery_accessories": [
        "h.samuel", "swarovski",
    ],
    "sports": [
        "jd sports", "sports direct",
    ],
    "health_beauty": [
        "boots",
    ],
    "home_diy": [
        "b&q", "the range",
    ],
    "leisure_cinema": [
        "odeon", "vue", "cineworld",
    ],
    "electronics_gaming": [
        "apple store", "bose", "currys",
    ],
    "fragrance": [
        "the perfume shop",
    ],
}

ALIASES = {
    "boots the chemist": "boots",
    "alliance boots": "boots",
    "boots opticians": "boots",
    "boots pharmacy": "boots",
    "m&s opticians": "marks & spencer",
    "m & s": "marks & spencer",
    "marks and spencer": "marks & spencer",
    "marks & spencers": "marks & spencer",
    "h & m": "h&m",
    "h and m": "h&m",
    "tkmaxx": "tk maxx",
    "tk-maxx": "tk maxx",
    "jd": "jd sports",
    "h samuel": "h.samuel",
    "h. samuel": "h.samuel",
    "john lewis & partners": "john lewis",
    "john lewis and partners": "john lewis",
    "odeon cinema": "odeon",
    "odeon cinemas": "odeon",
    "vue cinema": "vue",
    "vue cinemas": "vue",
    "cineworld cinema": "cineworld",
    "apple": "apple store",
    "hugo boss": "hugo boss",
}

COUNT_EXEMPT = {
    "Harvey Nichols",
    "Hugo Boss",
    "Zara Home",
    "H&M Kids",
}

EXCLUDED_ANCHOR_TERMS = {
    "m&s simply food",
    "m and s simply food",
    "marks & spencer simply food",
    "marks and spencer simply food",
}


def _normalise(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = html.unescape(text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s&.'-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_lookup(brand_dict: dict[str, list[str]]) -> tuple[dict[str, str], dict[str, str]]:
    norm_to_cat: dict[str, str] = {}
    for category, brands in brand_dict.items():
        for brand in brands:
            norm_to_cat[_normalise(brand)] = category

    alias_to_norm: dict[str, str] = {}
    for raw_alias, canonical in ALIASES.items():
        norm_alias = _normalise(raw_alias)
        norm_canonical = _normalise(canonical)
        if norm_canonical in norm_to_cat:
            alias_to_norm[norm_alias] = norm_canonical

    return norm_to_cat, alias_to_norm


def _whole_word_match(brand: str, text: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(brand) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


FSQ_NORM_TO_CAT, FSQ_ALIAS_TO_NORM = _build_lookup(FSQ_ANCHOR_BRANDS)


def _get_foursquare_anchor_brand(raw_name: str) -> str | None:
    norm = _normalise(raw_name)
    if not norm:
        return None
    if norm in EXCLUDED_ANCHOR_TERMS:
        return None
    if "simply food" in norm and (
        "m&s" in norm or "marks & spencer" in norm or "marks and spencer" in norm
    ):
        return None
    if norm in FSQ_NORM_TO_CAT:
        return norm
    if norm in FSQ_ALIAS_TO_NORM:
        return FSQ_ALIAS_TO_NORM[norm]
    for brand in FSQ_NORM_TO_CAT:
        if _whole_word_match(brand, norm):
            return brand
    return None


def _is_exact_known_foursquare_brand(raw_name: str) -> bool:
    norm = _normalise(raw_name)
    return norm in FSQ_NORM_TO_CAT or norm in FSQ_ALIAS_TO_NORM


def _read_foursquare_points(path: str, layer: str | None = None) -> gpd.GeoDataFrame:
    suffix = Path(path).suffix.lower()
    if suffix in {".gpkg", ".shp", ".geojson", ".json"}:
        return gpd.read_file(path, layer=layer)
    if suffix == ".parquet":
        return gpd.read_parquet(path)
    raise ValueError(f"Foursquare input must be spatial; unsupported suffix: {suffix}")


def _points_from_table(
    df: gpd.GeoDataFrame,
    *,
    name_col: str,
) -> gpd.GeoDataFrame:
    if name_col not in df.columns:
        raise KeyError(f"name_col '{name_col}' not found in Foursquare data")
    if not isinstance(df, gpd.GeoDataFrame) or "geometry" not in df.columns:
        raise TypeError("Foursquare input must be a GeoDataFrame with a geometry column")
    if df.crs is None:
        raise ValueError("Foursquare geometry must have a CRS")
    gdf = df.copy()
    return gdf.rename(columns={name_col: "fsq_anchor_source_name"})


def build_foursquare_anchor_counts(
    rc_path: str,
    foursquare_path: str,
    output_csv: str,
    *,
    rc_layer: str | None = None,
    foursquare_layer: str | None = None,
    name_col: str = "name",
    low_frequency_threshold: int = 10,
) -> None:
    retail_centers = gpd.read_file(rc_path, layer=rc_layer)
    raw_points = _read_foursquare_points(foursquare_path, layer=foursquare_layer)
    points = _points_from_table(
        raw_points,
        name_col=name_col,
    )

    points["anchor_brand"] = points["fsq_anchor_source_name"].apply(_get_foursquare_anchor_brand)
    points["anchor_category"] = points["anchor_brand"].map(FSQ_NORM_TO_CAT)
    points["is_anchor"] = points["anchor_brand"].notna()

    if low_frequency_threshold > 0:
        name_counts = points["fsq_anchor_source_name"].map(
            points["fsq_anchor_source_name"].value_counts()
        )
        exact_known_brand = points["fsq_anchor_source_name"].map(_is_exact_known_foursquare_brand)
        low_count_mask = (
            (name_counts <= low_frequency_threshold)
            & (~points["fsq_anchor_source_name"].isin(COUNT_EXEMPT))
            & (~exact_known_brand)
        )
        points.loc[low_count_mask, "is_anchor"] = False
        points.loc[low_count_mask, "anchor_brand"] = None
        points.loc[low_count_mask, "anchor_category"] = None

    joined = gpd.sjoin(
        points.to_crs(retail_centers.crs),
        retail_centers[["RC_ID", "geometry"]],
        predicate="within",
    )

    anchor_rows = joined[joined["is_anchor"]].dropna(subset=["anchor_brand"])
    anchor_counts = (
        anchor_rows.drop_duplicates(subset=["RC_ID", "anchor_brand"])
        .groupby("RC_ID")
        .size()
        .reset_index(name="anchor_counts")
    )
    anchor_shops = (
        anchor_rows.groupby("RC_ID")["fsq_anchor_source_name"]
        .apply(lambda s: "; ".join(pd.unique(s.dropna().astype(str))))
        .reset_index(name="anchor_shops")
    )

    out = retail_centers.merge(anchor_counts, on="RC_ID", how="left")
    out = out.merge(anchor_shops, on="RC_ID", how="left")
    out["anchor_counts"] = out["anchor_counts"].fillna(0).astype(int)
    out["anchor_shops"] = out["anchor_shops"].fillna("")

    cols = out.columns.tolist()
    if "anchor_counts" in cols and "anchor_shops" in cols:
        cols.remove("anchor_shops")
        cols.insert(cols.index("anchor_counts") + 1, "anchor_shops")
        out = out[cols]

    out.to_csv(output_csv, index=False)

    print(f"---3f. Saved Foursquare anchor counts to {output_csv}")


def main() -> None:
    build_foursquare_anchor_counts(
        rc_path="geo/postworkshopcentres_camdenmerge.gpkg",
        foursquare_path="geo/foursquare_quality_retail_filtered.parquet",
        output_csv="output/retail_centers_with_foursquare_anchorN.csv",
    )


if __name__ == "__main__":
    main()
