"""Paths and loaders shared by the validation scripts."""
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = HERE / "data"
OUT = HERE / "outputs"
LADS = ROOT / "Boundaries/data/inputs/boundaries/Local_Authority_Districts_December_2022_UK_BGC_V2_5759908710055972638.gpkg"
COUNTRIES = ROOT / "Boundaries/data/inputs/boundaries/Countries_December_2022_UK_BGC_1943732719298389253.gpkg"
PUBLISHED = ROOT / "Naming/exports/retailcentre_bounds_uk.parquet"
OLD = Path("/home/ogoodwin/projects/RetailCentres_Paper/data/macdonald2022_retail_centres.parquet")  # Macdonald et al. (2022)
OLD_CLASSIFIED = ROOT / "Classification/geo/old_retail_mapmaker/Retail_Boundaries_UK.gpkg"  # the same, with classes

# Boundaries runs for the sensitivity analysis (prep/run_sensitivity.sh); val2_baseline reproduces the published run
RUNS = ROOT / "Boundaries/data/outputs/runs"
PREFIX = "val2"
BASE = f"{PREFIX}_baseline"
RUN = RUNS / BASE


def prep(gdf):
    gdf = gdf.to_crs(27700).reset_index(drop=True)
    gdf["geometry"] = shapely.make_valid(gdf.geometry.values)
    return gdf


def load_new():
    """Published centres, with `centre` shared by the sub-centres of each split centre (Parent_ID)."""
    new = prep(gpd.read_parquet(PUBLISHED))
    parent = new.RC_ID.map(pd.read_parquet(ROOT / "Naming/exports/retailcentre_bounds.parquet",
                                           columns=["RC_ID", "Parent_ID"]).set_index("RC_ID").Parent_ID)
    new["centre"] = ("parent " + parent.astype("Int64").astype(str)).where(parent.notna(), new.RC_ID)
    return new


def combo_dir(run):
    return next((RUNS / run).glob("foursquare_mrc_*_merge_y"))


def load_run(run):
    """Final centres and parks of one Boundaries run."""
    c = gpd.read_parquet(combo_dir(run) / "4_finalcentres_las.parquet").to_crs(27700)
    c["geometry"] = shapely.make_valid(c.geometry.values)
    return c[["RC_ID", "Total_POI_count", "# H3 cells", "centre_type", "geometry"]]


def groups(run, centres):
    """One id per centre counting split centres once: a centre's pre-Leiden network (largest overlap); parks are their own."""
    cells = gpd.read_parquet(combo_dir(run) / "3_afterfill.parquet", columns=["network_number", "geometry"])
    nets = cells.dissolve("network_number").reset_index()
    ov = gpd.overlay(centres[centres.centre_type == "centre"][["RC_ID", "geometry"]], nets, how="intersection", keep_geom_type=True)
    ov["a"] = ov.area
    best = ov.sort_values("a").drop_duplicates("RC_ID", keep="last").set_index("RC_ID").network_number
    return centres.RC_ID.map(lambda i: f"N{best[i]}" if i in best.index else f"R{i}")
