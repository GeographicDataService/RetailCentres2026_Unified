"""Step 2. Retail parks against Ordnance Survey Points of Interest (paper Section 4.2.2), Great Britain only.

Reference: OS POI features of class 'Shopping centres and retail parks' (in data/os/, licensed) whose name contains
'Retail Park' or 'Shopping Park'. Recall: share of them within 50 m of one of our parks. Lower bound on precision:
share of our parks within 50 m of one of them. For the published parks and the 2022 (Macdonald et al.) parks.
Writes outputs/retail_parks/recall_precision.csv.
Run from repo root:  .venv/bin/python validation/retail_parks.py
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from common import COUNTRIES, DATA, OLD_CLASSIFIED, OUT, PUBLISHED, prep

BUFFER = 50
PARKS = ["Small Retail Park", "Large Retail Park"]
NAME_COLUMNS = ["name", "name1_text", "name1", "poi_name"]
NAME_PATTERN = r"\b(?:retail|shopping) park\b"


def os_named_parks(folder):
    found = []
    for f in sorted(Path(folder).rglob("*")):
        layers = [None] if f.suffix.lower() == ".parquet" else [l for l, _ in pyogrio.list_layers(f)] if f.suffix.lower() in (".gpkg", ".shp", ".geojson") else []
        for layer in layers:
            g = gpd.read_parquet(f) if layer is None else gpd.read_file(f, layer=layer)
            if "retailsetting" in g.columns:  # OS Retail Areas, not POIs
                continue
            for c in [c for c in g.columns if c.lower() in NAME_COLUMNS]:
                hit = g[c].astype(str).str.contains(NAME_PATTERN, case=False, regex=True)
                if hit.any():
                    found.append(g[hit])
    return prep(gpd.GeoDataFrame(pd.concat(found, ignore_index=True), crs=found[0].crs))


def great_britain(gdf):
    c = gpd.read_file(COUNTRIES)[["CTRY22NM", "geometry"]].to_crs(27700)
    pts = gpd.GeoDataFrame(geometry=gdf.geometry.representative_point(), crs=27700)
    country = gpd.sjoin_nearest(pts, c, how="left").groupby(level=0).first().CTRY22NM.reindex(gdf.index)
    return gdf[country.values != "Northern Ireland"]


def main():
    (OUT / "retail_parks").mkdir(parents=True, exist_ok=True)
    ref = os_named_parks(DATA / "os")
    sets = {"published": gpd.read_parquet(PUBLISHED), "2022": gpd.read_file(OLD_CLASSIFIED)}
    rows = []
    for name, c in sets.items():
        parks = prep(c[c.Classification.isin(PARKS)])
        gb = great_britain(parks)
        rows.append({"parks": name, "os_named_parks": len(ref), "recalled": int(ref.geometry.dwithin(parks.union_all(), BUFFER).sum()),
                     "parks_gb": len(gb), "parks_near_named_os_park": int(gb.geometry.dwithin(ref.union_all(), BUFFER).sum())})
    t = pd.DataFrame(rows)
    t["recall_pct"] = 100 * t.recalled / t.os_named_parks
    t["precision_lower_bound_pct"] = 100 * t.parks_near_named_os_park / t.parks_gb
    t.to_csv(OUT / "retail_parks/recall_precision.csv", index=False)
    print(t.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
