#!/usr/bin/env python
"""
Find retail centres in the Liverpool City Region.

Filters the named centres parquet by Local Authority name columns and outputs:
- A CSV list of RC_IDs with their matched LAs
- A filtered GeoParquet with all centre data
"""

import geopandas as gpd
import pandas as pd
from pathlib import Path

INPUT_PATH = Path("exports/rc2025_named.parquet")

OUTPUT_DIR = Path("exports")

LCR_LOCAL_AUTHORITIES = [
    "Liverpool",
    "Sefton",
    "Wirral",
    "Knowsley",
    "St Helens",
    "Halton",
]

LA_COLUMNS = ["LocalAuthorityNM_1", "LocalAuthorityNM_2", "LocalAuthorityNM_3"]


def main():
    centres = gpd.read_parquet(INPUT_PATH)

    # Match centres where any LA column is in the LCR set
    mask = pd.Series(False, index=centres.index)
    for col in LA_COLUMNS:
        if col in centres.columns:
            mask |= centres[col].isin(LCR_LOCAL_AUTHORITIES)

    lcr_centres = centres[mask].copy()

    print(f"Found {len(lcr_centres)} centres in Liverpool City Region")
    print(f"RC_IDs: {sorted(lcr_centres['RC_ID'].astype(int).tolist())}")

    # Save CSV with RC_ID and LA columns
    csv_cols = ["RC_ID", "Total_POI_count"] + [c for c in LA_COLUMNS if c in lcr_centres.columns]
    lcr_centres[csv_cols].sort_values("RC_ID").to_csv(
        OUTPUT_DIR / "lcr_centres.csv", index=False
    )

    # Save filtered GeoParquet
    lcr_centres.to_parquet(OUTPUT_DIR / "lcr_centres.parquet")

    print(f"\nSaved CSV to {OUTPUT_DIR / 'lcr_centres.csv'}")
    print(f"Saved GeoParquet to {OUTPUT_DIR / 'lcr_centres.parquet'}")


if __name__ == "__main__":
    main()
