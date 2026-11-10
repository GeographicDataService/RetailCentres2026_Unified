"""Item 2: draw the frozen random audit sample for hand labelling.

Strata:
  landuse_removal     50 networks removed by the land-use filter (val2_baseline)
  merge               50 one-cell-bridge merge pairs (val2_baseline merge_pairs.parquet)
  retail_park         75 published retail parks (Small/Large Retail Park)
  landuse_kept        50 networks kept by the land-use filter with 50% <= overlap < 75%            (--add)
  landuse_poi_exempt  50 networks with overlap >= 75% kept only by the 20-POI exemption          (--add)
  missing_top         the 20 2022 centres (UK, any class) with no overlapping new centre and the most
                      2022 retail POIs; chosen, not sampled                                     (--add)
  missing_slc         50 of the 422 English 2022 Small Local Centres with no overlapping new centre (--add)
                      (only a random 20 of the 50 were labelled; the other 30 were later dropped from cases.gpkg)
  park_ratio_gained   10 parks that appear only when the brand ratio is lowered to 2.5% (val2_brand_0.025) (--add)
  park_ratio_lost     10 published parks that disappear when it is raised to 7.5% (val2_brand_0.075)     (--add)
  landuse_kept_near   15 more kept networks at 70% <= overlap < 75%, not already sampled              (--add)
  landuse_removal_near 15 more removed networks at 75% <= overlap < 80%, not already sampled          (--add)
                      (top-ups: the random strata drew only 4 cases in each of these bands)
  exempt_kept_near    15 more networks at >= 75% overlap kept by the exemption with 20-24 POIs       (--add)
  exempt_removed_near 15 more networks at >= 75% overlap removed with 15-19 POIs                    (--add)
Random strata are simple random samples, seed 505. Near-miss parks are checked against OS Points of Interest
(os_retail_parks.py), not labelled. The full rebuild still draws near_miss_cases and missing_slc_cases so the
other strata keep the same cases; near_miss_cases also writes the candidates file os_retail_parks.py reads.
--add missing_slc replays the full rebuild's random draws, so it gets the same cases (SLC-001...) as before.
--add STRATUM appends a stratum to the frozen sample and leaves the existing cases untouched.
--refresh-park-metrics adds POI count and matched big-box brands (metrics and map markers) to the retail_park
cases; a full rebuild runs it too.

Writes validation/outputs/audit/cases.gpkg (layers: cases, context) and cases.geojson for the label tool.
Refuses to overwrite an existing sample unless --overwrite is given.

Run from repo root:  .venv/bin/python validation/prep/build_audit.py [--add STRATUM]
"""
import argparse
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import polars as pl
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
B = ROOT / "Boundaries"
sys.path.insert(0, str(B / "src"))
import config  # noqa: E402
from retail import detect_retail_parks  # noqa: E402

RUN = B / "data/outputs/runs/val2_baseline"  # reproduces the published run (run_20260610)
COMBO = RUN / "foursquare_mrc_2_mrn_10_mtf_6_splitthresh_1500_merge_y"
OUT = ROOT / "validation/outputs/audit"
SEED = 505
N = {"landuse_removal": 50, "merge": 50, "missing_slc": 50, "retail_park": 75, "park_near_miss": 50, "landuse_kept": 50,
     "landuse_poi_exempt": 50, "missing_top": 20, "park_ratio_gained": 10, "park_ratio_lost": 10,
     "landuse_kept_near": 15, "landuse_removal_near": 15, "exempt_kept_near": 15, "exempt_removed_near": 15}
EXEMPT_BAND = 5  # top-up strata: POIs within 5 of the 20-POI exemption, among networks at or above the overlap threshold
NEAR_BAND = 5  # top-up strata: overlap within 5 points either side of the land-use threshold
# retail park sensitivity strata: parks that appear (gained) or disappear (lost) when the 5% brand ratio changes
PARK_RATIO_RUNS = {"park_ratio_gained": "val2_brand_0.025", "park_ratio_lost": "val2_brand_0.075"}
PARK_STRATA = ["retail_park", "park_ratio_gained", "park_ratio_lost"]
NEAR_MISS_MIN_RATIO = 0.03
LANDUSE_KEPT_MIN_OVERLAP = 50
PREFIX = {"landuse_removal": "LU", "merge": "MG", "retail_park": "RP", "landuse_kept": "LK", "landuse_poi_exempt": "LP",
          "missing_top": "MT", "missing_slc": "SLC", "park_ratio_gained": "PG", "park_ratio_lost": "PL",
          "landuse_kept_near": "LKN", "landuse_removal_near": "LUN",
          "exempt_kept_near": "EKN", "exempt_removed_near": "ERN"}


def sample(df, n, rng):
    return df.iloc[np.sort(rng.choice(len(df), size=min(n, len(df)), replace=False))].reset_index(drop=True)


def dissolve_cells(cells, key):
    return cells[[key, "geometry"]].dissolve(by=key).reset_index()


def landuse_cases(rng):
    removed = gpd.read_parquet(COMBO / "landuse_filter_removed_networks.parquet", columns=["network_number", "geometry"])
    details = pd.read_parquet(COMBO / "landuse_filter_overlap_details.parquet")
    nets = dissolve_cells(removed, "network_number").merge(details, on="network_number")
    s = sample(nets.sort_values("network_number"), N["landuse_removal"], rng)
    s["ref_id"] = "network_" + s.network_number.astype(str)
    s["metrics"] = s.apply(landuse_metrics, axis=1)
    return s[["ref_id", "metrics", "geometry"]], None


def landuse_metrics(r):
    return {"total_overlap_pct": round(r.total_overlap, 1),
            "commercial_overlap_pct": round(r.commercial_overlap, 1),
            "industrial_overlap_pct": round(r.industrial_overlap, 1),
            "total_pois": int(r.total_pois),
            "rule": f"removed if overlap >= {config.LANDUSE_OVERLAP_THRESHOLD:g}% and POIs < {config.LANDUSE_MIN_POIS_EXEMPT}"}


def landuse_kept_population(stratum):
    removed = pd.read_parquet(COMBO / "landuse_filter_removed_networks.parquet", columns=["network_number"]).network_number
    d = pd.read_parquet(COMBO / "landuse_filter_overlap_details.parquet")
    d = d[~d.network_number.isin(removed)]
    if stratum == "landuse_poi_exempt":
        return d[d.total_overlap >= config.LANDUSE_OVERLAP_THRESHOLD]
    return d[(d.total_overlap >= LANDUSE_KEPT_MIN_OVERLAP) & (d.total_overlap < config.LANDUSE_OVERLAP_THRESHOLD)]


def landuse_near_cases(rng, stratum, existing_ref_ids):
    """Top-up near a land-use threshold, not already sampled: kept at 70-75% or removed at 75-80% overlap;
    or, at >= 75% overlap, kept by the exemption with 20-24 POIs or removed with 15-19 POIs."""
    thr, ex = config.LANDUSE_OVERLAP_THRESHOLD, config.LANDUSE_MIN_POIS_EXEMPT
    removed = pd.read_parquet(COMBO / "landuse_filter_removed_networks.parquet", columns=["network_number"]).network_number
    d = pd.read_parquet(COMBO / "landuse_filter_overlap_details.parquet")
    o, n = d.total_overlap, d.total_pois
    gone = d.network_number.isin(removed)
    pop = d[{"landuse_kept_near": ~gone & (o >= thr - NEAR_BAND) & (o < thr),
             "landuse_removal_near": gone & (o >= thr) & (o < thr + NEAR_BAND),
             "exempt_kept_near": ~gone & (o >= thr) & (n >= ex) & (n < ex + EXEMPT_BAND),
             "exempt_removed_near": gone & (o >= thr) & (n >= ex - EXEMPT_BAND) & (n < ex)}[stratum]]
    kept_side = stratum in ("landuse_kept_near", "exempt_kept_near")
    cells = gpd.read_parquet(COMBO / ("3_afterfill_landuse_filtered.parquet" if kept_side else "landuse_filter_removed_networks.parquet"),
                             columns=["network_number", "geometry"])
    band = len(pop)
    pop = pop[~("network_" + pop.network_number.astype(str)).isin(existing_ref_ids)]
    s = sample(pop.sort_values("network_number"), N[stratum], rng)
    s = dissolve_cells(cells[cells.network_number.isin(s.network_number)], "network_number").merge(s, on="network_number")
    s["ref_id"] = "network_" + s.network_number.astype(str)
    s["metrics"] = s.apply(landuse_metrics, axis=1)
    return s[["ref_id", "metrics", "geometry"]], band


def landuse_kept_cases(rng, stratum):
    pop = landuse_kept_population(stratum)
    s = sample(pop.sort_values("network_number"), N[stratum], rng)
    cells = gpd.read_parquet(COMBO / "3_afterfill_landuse_filtered.parquet", columns=["network_number", "geometry"])
    s = dissolve_cells(cells[cells.network_number.isin(s.network_number)], "network_number").merge(s, on="network_number")
    s["ref_id"] = "network_" + s.network_number.astype(str)
    s["metrics"] = s.apply(landuse_metrics, axis=1)
    return s[["ref_id", "metrics", "geometry"]], len(pop)


def merge_cases(rng):
    pairs = pl.read_parquet(COMBO / "merge_pairs.parquet").to_pandas()
    cells = gpd.read_parquet(COMBO / "3_afterfill_landuse_filtered.parquet", columns=["h3_11", "network_number", "geometry"])
    s = sample(pairs, N["merge"], rng)
    nets = dissolve_cells(cells[cells.network_number.isin(set(s.network_1) | set(s.network_2))], "network_number").set_index("network_number")
    import h3
    from shapely.geometry import Polygon
    rows, ctx = [], []
    for r in s.itertuples():
        g1, g2 = nets.geometry[r.network_1], nets.geometry[r.network_2]
        bridge = gpd.GeoSeries([Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in r.bridge_cells],
                               crs=4326).to_crs(27700).union_all()
        small = min(r.trackNodes_1, r.trackNodes_2)
        rows.append({"ref_id": f"networks_{r.network_1}_{r.network_2}", "geometry": g1.union(g2).union(bridge),
                     "metrics": {"trackNodes_a": int(r.trackNodes_1), "trackNodes_b": int(r.trackNodes_2),
                                 "smaller_side_cells": int(small), "bridge_cells": len(r.bridge_cells),
                                 "rule": "merged if separated by one cell and either side <= 10 H3 cells"}})
        for role, g in [("network_a", g1), ("network_b", g2), ("bridge", bridge)]:
            ctx.append({"ref_id": rows[-1]["ref_id"], "role": role, "geometry": g})
    return gpd.GeoDataFrame(rows, crs=27700), gpd.GeoDataFrame(ctx, crs=27700)


def missing_old_centres():
    flags = pd.read_csv(ROOT / "Naming/exports/old_centres_flags.csv")
    old = gpd.read_file(ROOT / "Classification/geo/old_retail_mapmaker/Retail_Boundaries_UK.gpkg").to_crs(27700)
    return old[old.RC_ID.isin(flags.RC_ID[~flags.has_new_intersect])]


def missing_slc_cases(rng, new_bounds):
    miss = missing_old_centres()
    miss = miss[(miss.Country == "England") & (miss.Classification == "Small Local Centre")]
    assert len(miss) == 422, len(miss)
    return missing_metrics(sample(miss.sort_values("RC_ID"), N["missing_slc"], rng), new_bounds), None


def missing_top_cases(new_bounds):
    miss = missing_old_centres()
    s = miss.sort_values(["Retail_N", "RC_ID"], ascending=[False, True]).head(N["missing_top"]).reset_index(drop=True)
    return missing_metrics(s, new_bounds), None, len(miss)


def missing_metrics(s, new_bounds):
    pois = pq.read_table(RUN / "foursquare_filtered.parquet", columns=["fsq_place_id", "lat", "lng"]).to_pandas().drop_duplicates("fsq_place_id")
    pois = gpd.GeoDataFrame(pois, geometry=gpd.points_from_xy(pois.lng, pois.lat), crs=4326).to_crs(27700)
    inside = gpd.sjoin(pois, s[["RC_ID", "geometry"]], predicate="within").groupby("RC_ID").size()
    nearest = gpd.sjoin_nearest(s[["RC_ID", "geometry"]], new_bounds[["RC_ID", "geometry"]].rename(columns={"RC_ID": "new_id"}),
                                distance_col="dist_m").drop_duplicates("RC_ID").set_index("RC_ID")
    s["ref_id"] = s.RC_ID
    s["metrics"] = s.apply(lambda r: {"old_name": r.RC_Name, "old_class": r.Classification,
                                      "old_retail_n": int(r.Retail_N) if pd.notna(r.Retail_N) else None,
                                      "current_retail_pois_inside": int(inside.get(r.RC_ID, 0)),
                                      "dist_to_nearest_new_centre_m": round(float(nearest.dist_m[r.RC_ID])),
                                      "rule": "new networks need >= 10 POIs in cells of >= 2 POIs"}, axis=1)
    return s[["ref_id", "metrics", "geometry"]]


def park_brand_metrics(parks):
    """POIs inside each park and the big-box brands among them, matched as the park detector matches them."""
    pois = pq.read_table(RUN / "retail_parks/foursquare_filtered_for_parks.parquet", columns=["name", "lat", "lng"]).to_pandas()
    pois = gpd.GeoDataFrame(pois, geometry=gpd.points_from_xy(pois.lng, pois.lat), crs=4326).to_crs(27700)
    inside = gpd.sjoin(pois, parks[["ref_id", "geometry"]].to_crs(27700), predicate="within")
    brands = pd.read_csv(B / config.RETAIL_PARK_BRANDS_PATH)
    matched = detect_retail_parks.filter_pois_by_brands(inside, brands, classic_only=True)
    names = matched.groupby("ref_id").name.apply(lambda n: ", ".join(f"{k} ({v})" if v > 1 else k for k, v in n.value_counts().items()))
    metrics = {r: {"pois_in_park": int(inside.ref_id.eq(r).sum()), "matched_brands": names.get(r, "none")} for r in parks.ref_id}
    return metrics, matched[["ref_id", "name", "geometry"]].to_crs(4326)


def refresh_park_metrics():
    """Add park_brand_metrics to the frozen retail_park cases in place; case IDs and geometry are untouched."""
    cases = gpd.read_file(OUT / "cases.gpkg", layer="cases")
    parks = cases[cases.stratum.isin(PARK_STRATA)]
    extra, points = park_brand_metrics(parks)
    for stratum in PARK_RATIO_RUNS:
        sub = parks[parks.stratum == stratum]
        if len(sub):
            for r, m in park_ratio_metrics(sub, stratum).items():
                extra[r] = {**m, **extra[r]}
    old_keys = {"max_brand_ratio_pct", "osm_area_sqkm", "lowest_polygon_brand_ratio_pct", "osm_polygons"}  # replaced by park_ratio_metrics
    cases.loc[parks.index, "metrics"] = [
        json.dumps({**{k: v for k, v in json.loads(m).items() if not (s in PARK_RATIO_RUNS and k in old_keys)}, **extra[r]})
        for m, r, s in zip(parks.metrics, parks.ref_id, parks.stratum)]
    layers = {name: gpd.read_file(OUT / "cases.gpkg", layer=name) for name in ["context"] if name in gpd.list_layers(OUT / "cases.gpkg").name.values}
    cases.to_file(OUT / "cases.gpkg", layer="cases", driver="GPKG")
    for name, layer in layers.items():
        layer.to_file(OUT / "cases.gpkg", layer=name, driver="GPKG")
    fc = json.loads((OUT / "cases.geojson").read_text())
    by_id = dict(zip(cases.case_id, cases.metrics))
    for f in fc["features"]:
        f["properties"]["metrics"] = by_id[f["properties"]["case_id"]]
    points["case_id"] = points.ref_id.map(dict(zip(parks.ref_id, parks.case_id)))
    fc["brand_points"] = json.loads(points[["case_id", "name", "geometry"]].to_json())  # drawn as markers by the label tool
    (OUT / "cases.geojson").write_text(json.dumps(fc))
    print(f"Updated metrics for {len(parks)} retail park cases.")


def park_ratio_cases(rng, stratum):
    """Parks in one run with no intersecting park in the other: gained at 2.5% (vs baseline) or lost at 7.5%."""
    combo = "foursquare_mrc_2_mrn_10_mtf_6_splitthresh_1500_merge_y/retail_parks_polygons.parquet"
    run = RUN.parent / PARK_RATIO_RUNS[stratum]
    base, other = gpd.read_parquet(COMBO / "retail_parks_polygons.parquet"), gpd.read_parquet(run / combo)
    src, ref = (other, base) if stratum == "park_ratio_gained" else (base, other)
    pop = src[~src.index.isin(gpd.sjoin(src, ref[["geometry"]], predicate="intersects").index)].sort_values("network_number")
    s = sample(pop, N[stratum], rng)
    s["ref_id"] = f"{PARK_RATIO_RUNS[stratum] if stratum == 'park_ratio_gained' else 'val2_baseline'}_park_" + s.network_number.astype(str)
    s["metrics"] = s.ref_id.map(park_ratio_metrics(s.to_crs(27700), stratum))
    return s[["ref_id", "metrics", "geometry"]].to_crs(27700), len(pop)


def park_ratio_metrics(s, stratum):
    """The values the park rules test. Each OSM polygon is kept if its brand ratio passes, adjacent kept polygons
    are merged, and the merged park needs the minimum area. So a park is gained (lost) when the polygons passing the
    other threshold are none, or merge to less than the minimum area."""
    gained = stratum == "park_ratio_gained"
    det_run, other = (RUN.parent / PARK_RATIO_RUNS[stratum], config.RETAIL_PARK_MIN_RATIO) if gained else (RUN, 0.075)
    det = gpd.read_parquet(det_run / "retail_parks/detected_retail_parks.parquet",
                           columns=["matched_to_centre_ratio", "area_sqkm", "name", "geometry"]).to_crs(27700)
    j = gpd.sjoin(s[["ref_id", "geometry"]].to_crs(27700), det, predicate="intersects")
    rule = ("park only if the brand ratio threshold is lowered to 2.5%" if gained else
            "published park; lost if the brand ratio threshold is raised to 7.5%") + \
        f"; each OSM polygon needs the ratio, the merged park needs >= {config.RETAIL_PARK_MIN_AREA_SQKM} km2"
    out = {}
    for r, g in j.sort_values("matched_to_centre_ratio", ascending=False).groupby("ref_id"):
        out[r] = {"osm_name": g.name.dropna().iloc[0] if g.name.notna().any() else None,
                  "polygons_ratio_area": "; ".join(f"{100 * x.matched_to_centre_ratio:.1f}% {x.area_sqkm:.4f} km2" for x in g.itertuples()),
                  "merged_area_sqkm": round(g.area_sqkm.sum(), 4),
                  f"area_passing_{100 * other:g}pct_sqkm": round(g.area_sqkm[g.matched_to_centre_ratio >= other].sum(), 4),
                  "rule": rule}
    return out


def retail_park_cases(rng, new_bounds):
    parks = new_bounds[new_bounds.Classification.isin(["Small Retail Park", "Large Retail Park"])].sort_values("RC_ID")
    s = sample(parks, N["retail_park"], rng)
    det = gpd.read_parquet(RUN / "retail_parks/detected_retail_parks.parquet",
                           columns=["matched_brand_count", "centre_poi_total", "matched_to_centre_ratio", "area_sqkm", "name", "geometry"]).to_crs(27700)
    j = gpd.sjoin(s[["RC_ID", "geometry"]], det, predicate="intersects")
    agg = j.groupby("RC_ID").agg(max_brand_ratio=("matched_to_centre_ratio", "max"), osm_polygons=("index_right", "size"),
                                 osm_area_sqkm=("area_sqkm", "sum"))
    s = s.join(agg, on="RC_ID")
    s["ref_id"] = s.RC_ID
    s["metrics"] = s.apply(lambda r: {"name": r.RC_Name, "class": r.Classification, "retail_n": int(r.Retail_N),
                                      "max_brand_ratio_pct": None if pd.isna(r.max_brand_ratio) else round(100 * r.max_brand_ratio, 1),
                                      "osm_area_sqkm": None if pd.isna(r.osm_area_sqkm) else round(r.osm_area_sqkm, 4),
                                      "rule": f"brand ratio >= {100 * config.RETAIL_PARK_MIN_RATIO:g}%, area >= {config.RETAIL_PARK_MIN_AREA_SQKM} km2"}, axis=1)
    return s[["ref_id", "metrics", "geometry"]], None


def near_miss_cases(rng):
    cand = detect_retail_parks.identify_retail_parks(
        retail_landuse_path=str(config.RETAIL_LANDUSE_POLYGONS_PATH),
        foursquare_pois_path=str(RUN / "retail_parks/foursquare_filtered_for_parks.parquet"),
        brands_csv_path=str(config.RETAIL_PARK_BRANDS_PATH),
        min_ratio=NEAR_MISS_MIN_RATIO,
        min_matched_pois=config.RETAIL_PARK_MIN_MATCHED_POIS,
        output_path=str(OUT / "park_candidates_ratio_ge_3pct.parquet"),
    ).to_crs(27700)
    nm = cand[(cand.matched_to_centre_ratio < config.RETAIL_PARK_MIN_RATIO) & (cand.area_sqkm >= config.RETAIL_PARK_MIN_AREA_SQKM)]
    nm = nm.reset_index(drop=True).reset_index().rename(columns={"index": "cand_id"})
    s = sample(nm, N["park_near_miss"], rng)
    s["ref_id"] = "osm_candidate_" + s.cand_id.astype(str)
    s["metrics"] = s.apply(lambda r: {"name": r["name"] if pd.notna(r["name"]) else None,
                                      "brand_ratio_pct": round(100 * r.matched_to_centre_ratio, 2),
                                      "matched_brands": int(r.matched_brand_count), "pois": int(r.centre_poi_total),
                                      "area_sqkm": round(r.area_sqkm, 4), "rule": "needs brand ratio >= 5% to be a park"}, axis=1)
    return s[["ref_id", "metrics", "geometry"]], None, len(nm)


def finalise(c, stratum):
    c = c.copy()
    c["case_id"] = [f"{PREFIX[stratum]}-{i + 1:03d}" for i in range(len(c))]
    c["stratum"] = stratum
    c["metrics"] = c.metrics.apply(json.dumps)
    c = gpd.GeoDataFrame(c, crs=27700)[["case_id", "stratum", "ref_id", "metrics", "geometry"]].to_crs(4326)
    c["lon"], c["lat"] = c.geometry.representative_point().x, c.geometry.representative_point().y
    return c


def add_stratum(stratum):
    """Append a later stratum to the frozen sample without redrawing the existing cases."""
    existing = gpd.read_file(OUT / "cases.gpkg", layer="cases")
    if (existing.stratum == stratum).any():
        sys.exit(f"{stratum} is already in the sample.")
    if stratum == "missing_slc":
        os.chdir(B)
        rng = np.random.default_rng(SEED)
        # replay main()'s draws before missing_slc_cases; these population sizes are asserted by the full rebuild
        for population, n in [(94, N["park_near_miss"]), (607, N["landuse_removal"]), (999, N["merge"])]:
            rng.choice(population, size=n, replace=False)
        c, _ = missing_slc_cases(rng, gpd.read_parquet(ROOT / "Naming/exports/retailcentre_bounds_uk.parquet").to_crs(27700))
        population = 422
    elif stratum in ("landuse_kept_near", "landuse_removal_near", "exempt_kept_near", "exempt_removed_near"):
        c, population = landuse_near_cases(np.random.default_rng(SEED), stratum, set(existing.ref_id))
    elif stratum in PARK_RATIO_RUNS:
        c, population = park_ratio_cases(np.random.default_rng(SEED), stratum)
    elif stratum == "missing_top":
        os.chdir(B)
        c, _, population = missing_top_cases(gpd.read_parquet(ROOT / "Naming/exports/retailcentre_bounds_uk.parquet").to_crs(27700))
    else:
        c, population = landuse_kept_cases(np.random.default_rng(SEED), stratum)
    c = finalise(c, stratum)
    c.to_file(OUT / "cases.gpkg", layer="cases", driver="GPKG", mode="a")
    fc = json.loads((OUT / "cases.geojson").read_text())
    fc["features"] += json.loads(c.to_json())["features"]
    (OUT / "cases.geojson").write_text(json.dumps(fc))
    frame = pd.read_csv(OUT / "sample_frame.csv")
    pd.concat([frame, pd.DataFrame([{"stratum": stratum, "population": population, "sampled": len(c)}])]).to_csv(
        OUT / "sample_frame.csv", index=False)
    print(f"Added {len(c)} {stratum} cases (population {population}).")
    if stratum in PARK_STRATA:
        refresh_park_metrics()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--add", choices=["landuse_kept", "landuse_poi_exempt", "missing_top", "missing_slc", *PARK_RATIO_RUNS,
                                           "landuse_kept_near", "landuse_removal_near", "exempt_kept_near", "exempt_removed_near"], help="append this stratum to the existing sample")
    ap.add_argument("--refresh-park-metrics", action="store_true", help="add matched brands to the existing retail_park cases")
    args = ap.parse_args()
    if args.refresh_park_metrics:
        return refresh_park_metrics()
    if args.add:
        return add_stratum(args.add)
    if (OUT / "cases.gpkg").exists() and not args.overwrite:
        sys.exit(f"{OUT / 'cases.gpkg'} exists; the sample is frozen. Use --overwrite to redraw (labels will no longer match).")
    OUT.mkdir(parents=True, exist_ok=True)
    os.chdir(B)  # config paths are relative to Boundaries/

    rng = np.random.default_rng(SEED)
    new_bounds = gpd.read_parquet(ROOT / "Naming/exports/retailcentre_bounds_uk.parquet").to_crs(27700)
    near_miss_cases(rng)  # not labelled; see docstring
    parts = {"landuse_removal": landuse_cases(rng), "merge": merge_cases(rng)}
    missing_slc_cases(rng, new_bounds)  # not labelled; see docstring
    parts["retail_park"] = retail_park_cases(rng, new_bounds)
    cases, ctx = [], []
    for stratum, (c, x) in parts.items():
        c = finalise(c, stratum)
        if x is not None:
            ctx.append(x.merge(c[["ref_id", "case_id"]], on="ref_id"))
        cases.append(c)
    cases = gpd.GeoDataFrame(pd.concat(cases, ignore_index=True), crs=4326)

    cases.to_file(OUT / "cases.gpkg", layer="cases", driver="GPKG")
    ctx = gpd.GeoDataFrame(pd.concat(ctx, ignore_index=True), crs=27700).to_crs(4326) if ctx else None
    if ctx is not None:
        ctx[["case_id", "role", "geometry"]].to_file(OUT / "cases.gpkg", layer="context", driver="GPKG")
    fc = json.loads(cases.to_json())
    if ctx is not None:
        fc["context"] = json.loads(ctx[["case_id", "role", "geometry"]].to_json())
    (OUT / "cases.geojson").write_text(json.dumps(fc))
    pd.DataFrame([{"stratum": s, "population": n, "sampled": int((cases.stratum == s).sum())} for s, n in [
        ("landuse_removal", len(pd.read_parquet(COMBO / "landuse_filter_removed_networks.parquet", columns=["network_number"]).network_number.unique())),
        ("merge", pl.read_parquet(COMBO / "merge_pairs.parquet").height),
        ("retail_park", int(new_bounds.Classification.isin(["Small Retail Park", "Large Retail Park"]).sum()))]]).to_csv(OUT / "sample_frame.csv", index=False)
    refresh_park_metrics()
    print(cases.stratum.value_counts().to_string())
    print(pd.read_csv(OUT / "sample_frame.csv").to_string(index=False))


if __name__ == "__main__":
    main()
