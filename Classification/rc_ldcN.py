import geopandas as gpd
import pandas as pd
import html
import re
import unicodedata


ANCHOR_BRANDS = {
    "high_street_fashion": [
        "next", "h&m", "zara", "tk maxx", "river island",
        "primark", "jack wills", "white stuff", "fat face",
        "crew clothing", "seasalt", "joules", "lacoste",
        "diesel", "hugo boss", "tommy hilfiger", "ted baker",
        "laura ashley",
    ],
    "department_stores": [
        "john lewis", "harvey nichols", "marks & spencer", "m&s", "ikea", "house of fraser",
    ],
    "jewellery_accessories": [
        "h.samuel", "swarovski", "claire's",
    ],
    "sports": [
        "jd sports", "sports direct",
    ],
    "health_beauty": [
        "boots",
    ],
    "home_diy": [
        "b&q", "homebase",
    ],
    "leisure_cinema": [
        "odeon", "vue", "cineworld",
    ],
    "electronics_gaming": [
        "apple store", "bose", "game", "currys",
    ],
    "fragrance": [
        "the perfume shop",
    ],
}

ALIASES = {
    "boots the chemist": "boots",
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
    "claire's accessories": "claire's",
    "claires": "claire's",
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
    "Laura Ashley Home",
    "Zara Home",
    "H&M Kids",
    "Laura Ashley",
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
    text = re.sub(r"[^\w\s&.\'-]", " ", text)
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


NORM_TO_CAT, ALIAS_TO_NORM = _build_lookup(ANCHOR_BRANDS)


def _whole_word_match(brand: str, text: str) -> bool:
    pattern = r"(?<![a-z0-9])" + re.escape(brand) + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def _get_anchor_category(raw_name: str) -> str | None:
    brand = _get_anchor_brand(raw_name)
    if brand is None:
        return None
    return NORM_TO_CAT[brand]


def _get_anchor_brand(raw_name: str) -> str | None:
    norm = _normalise(raw_name)
    if not norm:
        return None
    if norm in EXCLUDED_ANCHOR_TERMS:
        return None
    if "simply food" in norm and ("m&s" in norm or "marks & spencer" in norm or "marks and spencer" in norm):
        return None
    if norm in NORM_TO_CAT:
        return norm
    if norm in ALIAS_TO_NORM:
        return ALIAS_TO_NORM[norm]
    for brand, cat in NORM_TO_CAT.items():
        if _whole_word_match(brand, norm):
            return brand
    return None


def build_ldc_retail_counts(
    rc_path: str,
    ldc_csv: str,
    output_csv: str,
) -> None:
    retail_centers = gpd.read_file(rc_path)

    ldc = pd.read_csv(ldc_csv)
    ldc_live = ldc[ldc["Status"] == "Live"].copy()
    ldc_live["anchor_brand"] = ldc_live["Name"].apply(_get_anchor_brand)
    ldc_live["anchor_category"] = ldc_live["anchor_brand"].map(NORM_TO_CAT)
    ldc_live["is_anchor"] = ldc_live["anchor_brand"].notna()

    # Remove low-frequency brand names except explicit exceptions.
    name_counts = ldc_live["Name"].map(ldc_live["Name"].value_counts())
    low_count_mask = (name_counts <= 10) & (~ldc_live["Name"].isin(COUNT_EXEMPT))
    ldc_live.loc[low_count_mask, "is_anchor"] = False
    ldc_live.loc[low_count_mask, "anchor_brand"] = None
    ldc_live.loc[low_count_mask, "anchor_category"] = None

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
    anchor_counts = (
        joined[joined["is_anchor"]]
        .dropna(subset=["anchor_brand"])
        .drop_duplicates(subset=["RC_ID", "anchor_brand"])
        .groupby("RC_ID")
        .size()
        .reset_index(name="anchor_counts")
    )
    anchor_shops = (
        joined[joined["is_anchor"]]
        .groupby("RC_ID")["Name"]
        .apply(lambda s: "; ".join(pd.unique(s.dropna().astype(str))))
        .reset_index(name="anchor_shops")
    )

    rc_retailN = retail_centers.merge(unit_counts, on="RC_ID", how="left")
    rc_retailN = rc_retailN.merge(anchor_counts, on="RC_ID", how="left")
    rc_retailN = rc_retailN.merge(anchor_shops, on="RC_ID", how="left")
    rc_retailN[["unit_counts", "anchor_counts"]] = (
        rc_retailN[["unit_counts", "anchor_counts"]].fillna(0).astype(int)
    )
    rc_retailN["anchor_shops"] = rc_retailN["anchor_shops"].fillna("")

    # Keep anchor_shops directly after anchor_counts for downstream readability.
    cols = rc_retailN.columns.tolist()
    if "anchor_counts" in cols and "anchor_shops" in cols:
        cols.remove("anchor_shops")
        cols.insert(cols.index("anchor_counts") + 1, "anchor_shops")
        rc_retailN = rc_retailN[cols]

    # Backward compatibility for downstream scripts expecting LDC_retailN.
    rc_retailN["LDC_retailN"] = rc_retailN["unit_counts"]
    rc_retailN.to_csv(output_csv, index=False)


    print(f"---3. Saved retail center counts to {output_csv}")


def main() -> None:
    build_ldc_retail_counts(
        rc_path="geo/postworkshopcentres.gpkg",
        ldc_csv="data/LDC_Historical_snapshot_2015-01-01-2025-09-30.csv",
        output_csv="output/retail_centers_with_ldc_retailN.csv",
    )

if __name__ == "__main__":
    main()
