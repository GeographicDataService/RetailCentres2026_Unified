"""
Generate a comparison parquet with two name columns for each centre:
  - Name_OwnCentre: each sub-area named as its own independent centre (full pipeline)
  - Name_WholeArea: sub-areas get the parent group name (city; LA (region; country))

Non-sub-area centres get the same value in both columns.
"""

import os
import re
import sys
import warnings
import numpy as np
import pandas as pd

# This script lives in scripts/; the pipeline modules live in the parent dir.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from generate_names import (
    load_data,
    match_outlets_to_centres,
    assemble_name_components,
    clean_name,
)

warnings.filterwarnings("ignore")

EXPORTS_DIR = os.path.join(PROJECT_DIR, "exports")


def run():
    rc, lookups = load_data()
    ons = lookups["RC_Naming_ONS"]
    os_nearest = lookups["RC_Naming_OS"]
    os_internal = lookups["RC_Naming_OS_Internal"]
    streets = lookups["RC_Naming_Streets"]
    osm_rp = lookups["RC_Naming_OSM_RetailParks"]

    # === Classification ===
    classification = rc[["RC_ID", "Classification"]].copy()
    outlets = match_outlets_to_centres(rc)
    for _, row in outlets.iterrows():
        mask = classification["RC_ID"] == row["RC_ID"]
        if mask.any():
            classification.loc[mask, "Classification"] = row["SubType"]

    # === Level 1: Street ===
    level1 = streets[["RC_ID"]].copy()
    level1["Street"] = None
    if "Str_1" in streets.columns and "Str_1_P" in streets.columns:
        str1 = streets["Str_1"]
        str1_p = pd.to_numeric(streets["Str_1_P"], errors="coerce")
        str2 = streets.get("Str_2", pd.Series(dtype=str))
        str2_p = pd.to_numeric(streets.get("Str_2_P", pd.Series(dtype=float)), errors="coerce")
        level1["Street"] = np.where(
            str1_p > 0.31,
            str1.astype(str),
            np.where(str2_p > 0.31, str1.astype(str) + " & " + str2.astype(str), None),
        )
        level1.loc[level1["Street"].isin(["nan", "None", "nan & nan"]), "Street"] = None
        level1["Street"] = level1["Street"].apply(lambda x: x.title() if pd.notna(x) else x)

    # === Level 2: Neighbourhood ===
    level2 = os_nearest[["RC_ID"]].copy()
    level2["nearest"] = None
    dist_cols, name_cols = {}, {}
    for short in ["City", "Town", "Village", "Suburban", "Settlement", "Hamlet"]:
        if short in os_nearest.columns:
            name_cols[short] = short
        if f"{short}D" in os_nearest.columns:
            dist_cols[short] = f"{short}D"

    if dist_cols:
        dist_df = os_nearest[list(dist_cols.values())].apply(pd.to_numeric, errors="coerce")
        min_type = dist_df.idxmin(axis=1)
        for idx, mt in min_type.items():
            if pd.notna(mt):
                short = mt.replace("D", "")
                if short in os_nearest.columns:
                    val = os_nearest.loc[idx, short]
                    if pd.notna(val):
                        level2.loc[idx, "nearest"] = val

    if "RC_ID" in os_internal.columns:
        merged = level2.merge(os_internal, on="RC_ID", how="left")
        merged["inner"] = None
        for ptype in ["City", "Village", "Town", "Suburban", "Settlement", "Hamlet"]:
            if ptype not in merged.columns:
                continue
            has_value = merged[ptype].notna() & (merged[ptype].str.strip() != "")
            not_yet_set = merged["inner"].isna()
            merged.loc[has_value & not_yet_set, "inner"] = (
                merged.loc[has_value & not_yet_set, ptype].str.split(";").str[0].str.strip()
            )
        has_inner = merged["inner"].notna()
        merged.loc[has_inner, "nearest"] = merged.loc[has_inner, "inner"]
        level2["nearest"] = merged["nearest"]

    # NI centres
    ni_ids = rc.loc[rc["RegionName"].isin(["NI", "Northern Ireland"]), "RC_ID"].tolist()
    large_classes = {"Regional Centre", "Major Town Centre", "Town Centre"}
    if ni_ids:
        level2.loc[level2["RC_ID"].isin(ni_ids), "nearest"] = None
        for rc_id in ni_ids:
            cls = rc.loc[rc["RC_ID"] == rc_id, "Classification"]
            is_large = len(cls) > 0 and cls.iloc[0] in large_classes
            name = None
            if is_large and "CityNM_1" in ons.columns:
                city = ons.loc[ons["RC_ID"] == rc_id, "CityNM_1"]
                if len(city) > 0 and pd.notna(city.iloc[0]) and str(city.iloc[0]).strip():
                    name = str(city.iloc[0]).strip().title()
            elif not is_large and "NbhdNM_1" in ons.columns:
                nbhd = ons.loc[ons["RC_ID"] == rc_id, "NbhdNM_1"]
                if len(nbhd) > 0 and pd.notna(nbhd.iloc[0]):
                    name = re.sub(r"_[A-Z]$|_*\d+", "", str(nbhd.iloc[0])).replace("_", " ").strip()
            if name is None and "CityNM_1" in ons.columns:
                city = ons.loc[ons["RC_ID"] == rc_id, "CityNM_1"]
                if len(city) > 0 and pd.notna(city.iloc[0]) and str(city.iloc[0]).strip():
                    name = str(city.iloc[0]).strip().title()
            if name is None and "NbhdNM_1" in ons.columns:
                nbhd = ons.loc[ons["RC_ID"] == rc_id, "NbhdNM_1"]
                if len(nbhd) > 0 and pd.notna(nbhd.iloc[0]):
                    name = re.sub(r"_[A-Z]$|_*\d+", "", str(nbhd.iloc[0])).replace("_", " ").strip()
            if name:
                level2.loc[level2["RC_ID"] == rc_id, "nearest"] = name

    # === Assemble base naming table ===
    naming = rc[["RC_ID"]].copy()
    if "LocalAuthorityNM_1" in ons.columns:
        naming = naming.merge(
            ons[["RC_ID", "LocalAuthorityNM_1", "Country", "RegionNM"]].drop_duplicates("RC_ID"),
            on="RC_ID", how="left",
        )
    else:
        naming["LocalAuthorityNM_1"] = rc["LocalAuthorityNM_1"].values
        naming["Country"] = rc.get("Country", "").values if "Country" in rc.columns else ""
        naming["RegionNM"] = rc["RegionName"].values

    if naming["Country"].isna().any() or (naming["Country"] == "").any():
        region_map = rc.set_index("RC_ID")["RegionName"]
        for idx in naming.index:
            if pd.isna(naming.loc[idx, "Country"]) or naming.loc[idx, "Country"] == "":
                rc_id = naming.loc[idx, "RC_ID"]
                rgn = region_map.get(rc_id, "")
                if rgn in [
                    "North East", "North West", "Yorkshire and The Humber",
                    "East Midlands", "West Midlands", "East of England",
                    "London", "South East", "South West",
                ]:
                    naming.loc[idx, "Country"] = "England"
                    naming.loc[idx, "RegionNM"] = rgn
                elif rgn == "Wales":
                    naming.loc[idx, "Country"] = "Wales"
                    naming.loc[idx, "RegionNM"] = "Wales"
                elif rgn == "Scotland":
                    naming.loc[idx, "Country"] = "Scotland"
                    naming.loc[idx, "RegionNM"] = "Scotland"
                elif rgn in ("Northern Ireland", "NI"):
                    naming.loc[idx, "Country"] = "Northern Ireland"
                    naming.loc[idx, "RegionNM"] = "Northern Ireland"

    naming = naming.merge(classification, on="RC_ID", how="left")
    naming = naming.merge(level1[["RC_ID", "Street"]], on="RC_ID", how="left")
    naming = naming.merge(
        level2[["RC_ID", "nearest"]].rename(columns={"nearest": "Neighbourhood"}),
        on="RC_ID", how="left",
    )

    # === Pipeline names (no sub-area renaming) ===
    naming["RC_Name"] = ""
    for idx in naming.index:
        cls = naming.loc[idx, "Classification"]
        street = naming.loc[idx, "Street"]
        nbhd = naming.loc[idx, "Neighbourhood"]
        la = naming.loc[idx, "LocalAuthorityNM_1"]
        region = naming.loc[idx, "RegionNM"]
        country = naming.loc[idx, "Country"]
        if cls in ("Regional Centre", "Major Town Centre", "Town Centre"):
            name = assemble_name_components([None, nbhd, la, region, country])
        else:
            name = assemble_name_components([street, nbhd, la, region, country])
        naming.loc[idx, "RC_Name"] = name

    # Retail park naming
    rp_mask = naming["Classification"].isin(["Large Retail Park", "Small Retail Park"])
    if rp_mask.any():
        rp_named = set()
        if "OSM_RetailParkName" in osm_rp.columns:
            for _, row in osm_rp[osm_rp["OSM_RetailParkName"].notna()].iterrows():
                mask = (naming["RC_ID"] == row["RC_ID"]) & rp_mask
                if not mask.any():
                    continue
                la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
                region = naming.loc[mask, "RegionNM"].iloc[0]
                country = naming.loc[mask, "Country"].iloc[0]
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, row["OSM_RetailParkName"], la, region, country]
                )
                rp_named.add(row["RC_ID"])

        rp_cols = ["RC_ID"]
        for col in ["RetailParkBranded", "RetailParkLocality"]:
            if col in streets.columns:
                rp_cols.append(col)
        rp_info = streets[rp_cols].copy()
        for _, row in rp_info.iterrows():
            if row["RC_ID"] in rp_named:
                continue
            mask = (naming["RC_ID"] == row["RC_ID"]) & rp_mask
            if not mask.any():
                continue
            branded = row.get("RetailParkBranded")
            if pd.notna(branded):
                la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
                region = naming.loc[mask, "RegionNM"].iloc[0]
                country = naming.loc[mask, "Country"].iloc[0]
                naming.loc[mask, "RC_Name"] = assemble_name_components(
                    [None, branded, la, region, country]
                )
                rp_named.add(row["RC_ID"])

        for idx in naming[rp_mask].index:
            rc_id = naming.loc[idx, "RC_ID"]
            if rc_id in rp_named:
                continue
            name = naming.loc[idx, "RC_Name"]
            parts = name.split("; ")
            if parts:
                parts[0] = parts[0].strip() + " Retail Park"
                naming.loc[idx, "RC_Name"] = "; ".join(p.strip() for p in parts)

        naming.loc[naming["RC_ID"] == "3379", "RC_Name"] = (
            naming.loc[naming["RC_ID"] == "3379", "RC_Name"]
            .str.replace("Europa Boulevard Retail Park", "Gemini Retail Park")
        )

    # Shopping centre naming
    outlets2 = match_outlets_to_centres(rc)
    for _, row in outlets2.iterrows():
        mask = naming["RC_ID"] == row["RC_ID"]
        if mask.any():
            la = naming.loc[mask, "LocalAuthorityNM_1"].iloc[0]
            region = naming.loc[mask, "RegionNM"].iloc[0]
            country = naming.loc[mask, "Country"].iloc[0]
            naming.loc[mask, "RC_Name"] = assemble_name_components(
                [None, row["Name"], la, region, country]
            )

    # Store own-centre name
    naming["Name_OwnCentre"] = naming["RC_Name"].apply(clean_name)

    # === Whole-area names for sub-areas ===
    sub_areas = rc[rc["was_split"] == True][["RC_ID", "Parent_ID", "tr_retailN"]].copy()
    sub_areas["Parent_ID"] = sub_areas["Parent_ID"].astype(int).astype(str)
    sub_areas["tr_retailN"] = pd.to_numeric(sub_areas["tr_retailN"], errors="coerce").fillna(0)

    naming["Name_WholeArea"] = naming["Name_OwnCentre"]  # default: same as own

    for _, group in sub_areas.groupby("Parent_ID"):
        member_ids = group["RC_ID"].tolist()

        # Find parent city name (closest City/Town across all members)
        city_name = None
        best_dist = float("inf")
        for mid in member_ids:
            row = os_nearest[os_nearest["RC_ID"] == mid]
            if len(row) == 0:
                continue
            for ptype in ["City", "Town"]:
                dcol = f"{ptype}D"
                if ptype in row.columns and dcol in row.columns:
                    d = pd.to_numeric(row.iloc[0][dcol], errors="coerce")
                    nm = row.iloc[0][ptype]
                    if pd.notna(d) and d < best_dist and pd.notna(nm):
                        best_dist = d
                        city_name = str(nm).split(";")[0].strip()
                        if city_name == "City of London":
                            city_name = "London"

        primary_rc_id = group.sort_values("tr_retailN", ascending=False).iloc[0]["RC_ID"]
        primary_mask = naming["RC_ID"] == primary_rc_id
        if not primary_mask.any():
            continue

        la = naming.loc[primary_mask, "LocalAuthorityNM_1"].iloc[0]
        if city_name == "London":
            la = "London"
        region = naming.loc[primary_mask, "RegionNM"].iloc[0]
        country = naming.loc[primary_mask, "Country"].iloc[0]
        parent_name = clean_name(assemble_name_components([None, city_name, la, region, country]))

        for mid in member_ids:
            mask = naming["RC_ID"] == mid
            if mask.any():
                naming.loc[mask, "Name_WholeArea"] = parent_name

    # === Export ===
    out = rc.merge(naming[["RC_ID", "Name_OwnCentre", "Name_WholeArea"]], on="RC_ID", how="left")
    out_path = os.path.join(EXPORTS_DIR, "rc2025_naming_comparison.parquet")
    out.to_parquet(out_path)
    print(f"Saved {out_path} ({len(out)} rows)")

    sub_ids = set(sub_areas["RC_ID"].tolist())
    comp = naming[naming["RC_ID"].isin(sub_ids)][["RC_ID", "Name_OwnCentre", "Name_WholeArea"]]
    print(f"{len(comp)} sub-areas. Sample:")
    for _, r in comp.head(20).iterrows():
        print(f"  {r['RC_ID']:>5}  Own: {r['Name_OwnCentre']:<55} Whole: {r['Name_WholeArea']}")


if __name__ == "__main__":
    run()
