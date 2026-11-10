"""Step 4. Parameter sensitivity and Leiden stability (paper Table 5 and Section 4.3).

Every Boundaries run val2_* (prep/run_sensitivity.sh, prep/run_postcode_sensitivity.sh) is compared with val2_baseline,
which reproduces the published run: number of centres counting split centres once (parent_level), number of parks,
total area, and the areal IoU of all centres and of parks alone. For the Leiden runs, the networks partitioned and the
sub-centres in them; and for each published sub-centre, its mean Jaccard (H3 cells) with its best match across the 20
seed runs (stable if >= 0.75, after Hennig 2007).
Writes outputs/sensitivity/{sensitivity_runs.csv, leiden.csv, subcentre_stability.csv}, and the release lookup
Naming/exports/retailcentre_subcentre_stability.csv if it does not exist (--overwrite to replace it).
Run from repo root:  .venv/bin/python validation/sensitivity.py [--overwrite]
"""
import argparse
import re

import geopandas as gpd
import numpy as np
import pandas as pd
import polars as pl

from common import BASE, OUT, PREFIX, PUBLISHED, ROOT, RUNS, combo_dir, groups, load_run

DEST = OUT / "sensitivity"
RELEASE = ROOT / "Naming/exports/retailcentre_subcentre_stability.csv"
SPLIT = 1500  # published Leiden trigger (POIs)


def iou(a, b):
    ua, ub = a.geometry.union_all(), b.geometry.union_all()
    return ua.intersection(ub).area / ua.union(ub).area


def split_cells(run, threshold):
    """Cells (as points) of every network of `run` with >= threshold POIs, i.e. the networks Leiden splits."""
    cells = pl.read_parquet(combo_dir(run) / "3_afterfill_pl.parquet", columns=["h3_11", "network_number", "total_foursquare_count"])
    big = cells.filter(pl.col("total_foursquare_count") >= threshold)
    pts = gpd.read_parquet(combo_dir(run) / "3_afterfill.parquet", columns=["h3_11", "geometry"])
    pts = pts[pts.h3_11.isin(set(big["h3_11"].to_list()))].copy()
    pts["geometry"] = pts.geometry.representative_point()
    return pts.merge(big.select(["h3_11", "network_number"]).to_pandas(), on="h3_11").to_crs(27700)


def cell_labels(pts, centres):
    """RC_ID of the centre each cell point falls in, aligned to pts; -1 if none."""
    j = gpd.sjoin(pts, centres[["RC_ID", "geometry"]], predicate="within").drop_duplicates("h3_11").set_index("h3_11")
    return j.RC_ID.reindex(pts.h3_11).fillna(-1).values


def best_jaccard(base, run):
    """Per base label, the best cell Jaccard with any run label (cells outside every centre are -1)."""
    out = {}
    for b in set(base) - {-1}:
        inb = base == b
        out[b] = max(((inb & (run == r)).sum() / (inb | (run == r)).sum() for r in set(run[inb]) - {-1}), default=0.0)
    return out


def runs_table():
    runs = sorted(p.parent.parent.name for p in RUNS.glob(f"{PREFIX}_*/*/4_finalcentres_las.parquet"))
    base = load_run(BASE)
    parks = lambda c: c[c.centre_type == "retail_park"]  # noqa: E731
    rows = []
    for run in runs:
        c = base if run == BASE else load_run(run)
        m = re.match(rf"{PREFIX}_([a-z]+)_(.+)", run)
        param, value = (m.group(1), np.inf if m.group(2) == "off" else float(m.group(2))) if m else ("baseline", np.nan)
        rows.append({"run": run, "param": param, "value": value, "parent_level": groups(run, c).nunique(),
                     "parks": len(parks(c)), "area_km2": c.area.sum() / 1e6,
                     "overall_iou": iou(base, c), "parks_iou": iou(parks(base), parks(c))})
        print(run)
    df = pd.DataFrame(rows)
    b = df[df.run == BASE].iloc[0]
    for k in ["parent_level", "parks", "area_km2"]:
        df[f"{k}_pct_change"] = 100 * (df[k] - b[k]) / b[k]
    df.sort_values(["param", "value"]).to_csv(DEST / "sensitivity_runs.csv", index=False)


def leiden_table():
    rows = []
    for run in [BASE] + sorted(p.name for p in RUNS.glob(f"{PREFIX}_res_*")) + sorted(p.name for p in RUNS.glob(f"{PREFIX}_split_*")):
        threshold = float(run.split("_")[-1]) if "_split_" in run else SPLIT
        pts = split_cells(run, threshold)
        c = load_run(run)
        rows.append({"run": run, "partitioned_networks": pts.network_number.nunique(),
                     "subcentres": int(gpd.sjoin(pts, c[c.centre_type == "centre"][["RC_ID", "geometry"]], predicate="within").RC_ID.nunique())})
    pd.DataFrame(rows).to_csv(DEST / "leiden.csv", index=False)


def subcentre_stability(overwrite):
    pts = split_cells(BASE, SPLIT)
    published = gpd.read_parquet(PUBLISHED).to_crs(27700)
    base = cell_labels(pts, published)
    seeds = sorted((p.name for p in RUNS.glob(f"{PREFIX}_seed_*")), key=lambda r: int(r.split("_")[-1]))
    runs = {s: cell_labels(pts, load_run(s)) for s in seeds}
    rows = []
    for net, idx in pts.groupby("network_number").indices.items():
        scores = pd.DataFrame([best_jaccard(base[idx], runs[s][idx]) for s in seeds])
        for rc in scores.columns:
            rows.append({"RC_ID": rc, "network_number": net, "mean_jaccard": round(scores[rc].mean(), 3),
                         **{f"pct_seeds_j{100 * j:g}": round(100 * (scores[rc] >= j).mean(), 1) for j in (0.75, 0.9)}})
    d = pd.DataFrame(rows).merge(published[["RC_ID", "RC_Name"]], on="RC_ID", how="left").sort_values("mean_jaccard")
    d.to_csv(DEST / "subcentre_stability.csv", index=False)
    if RELEASE.exists() and not overwrite:
        print(f"{RELEASE} exists, left unchanged (use --overwrite to replace it).")
        return
    # only the sub-centres of Leiden-split networks; every other centre is identical in every seed
    rel = d[["RC_ID", "mean_jaccard", "pct_seeds_j75", "pct_seeds_j90"]].sort_values("RC_ID", key=lambda s: s.astype(int))
    rel.rename(columns={"mean_jaccard": "Seed_Jaccard", "pct_seeds_j75": "Pct_Seeds_J75", "pct_seeds_j90": "Pct_Seeds_J90"}).to_csv(RELEASE, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overwrite", action="store_true", help="replace an existing release lookup")
    args = ap.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    runs_table()
    leiden_table()
    subcentre_stability(args.overwrite)


if __name__ == "__main__":
    main()
