"""Re-run the Boundaries quality filters from scratch in a sandbox, then check the kept set against
the run that built the published centres (run_20260610).

Nothing existing is touched: the filters write to relative data/intermediate/... paths, so they are run
from validation/outputs/quality_rerun/ with data/inputs symlinked to Boundaries/data/inputs.

Run from repo root:  .venv/bin/python validation/prep/rerun_quality_filters.py
Postcode sensitivity runs (own sandbox each, not expected to match):
  ... rerun_quality_filters.py --postcode_m 5000
  ... rerun_quality_filters.py --no_postcode
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import polars as pl
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
B = ROOT / "Boundaries"
PUBLISHED = B / "data/outputs/runs/run_20260610/foursquare_quality_filtered.parquet"
sys.path.insert(0, str(B / "src"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--postcode_m", type=float, default=1000.0)
    ap.add_argument("--no_postcode", action="store_true")
    args = ap.parse_args()
    suffix = "_postcode_off" if args.no_postcode else (
        "" if args.postcode_m == 1000.0 else f"_postcode_{int(args.postcode_m)}")
    SANDBOX = ROOT / f"validation/outputs/quality_rerun{suffix}"
    if SANDBOX.exists():
        sys.exit(f"{SANDBOX} exists; remove it or move it aside to re-run.")
    (SANDBOX / "data").mkdir(parents=True)
    (SANDBOX / "data/inputs").symlink_to(B / "data/inputs", target_is_directory=True)
    os.chdir(SANDBOX)

    import config
    from retail import foursquare_qualityfilter as qf

    foursquare = pl.read_parquet(B / config.FOURSQUARE_PATH)
    print(f"Input rows {foursquare.height:,}; defunct list {config.DEFUNCT_RETAILERS_PATH}")
    kept = qf.filter_foursquare_quality(foursquare, save_filter_ids=True,
                                        filter_ids_path=str(config.FILTER_IDS_PATH),  # same call as main.py
                                        filter_postcode_mismatch=not args.no_postcode,
                                        postcode_mismatch_threshold_m=args.postcode_m)
    kept_ids = set(kept["fsq_place_id"].to_list())
    kept.select("fsq_place_id").unique().write_parquet(SANDBOX / "kept_ids.parquet")

    pub = set(pc.unique(pq.read_table(PUBLISHED, columns=["fsq_place_id"])["fsq_place_id"]).to_pylist())
    pub_rows = pq.ParquetFile(PUBLISHED).metadata.num_rows
    print(f"\nRe-run kept: {kept.height:,} rows, {len(kept_ids):,} unique")
    print(f"run_20260610: {pub_rows:,} rows, {len(pub):,} unique")
    print(f"Only in re-run: {len(kept_ids - pub):,}; only in run_20260610: {len(pub - kept_ids):,}")
    match = kept_ids == pub and kept.height == pub_rows

    # per-filter counts in the paper's form: unique POIs removed at each sequential stage
    ids = pl.read_parquet(SANDBOX / config.FILTER_IDS_PATH)
    src_unique = foursquare["fsq_place_id"].n_unique()
    closed = set(ids.filter(pl.col("filter_type") == "closed")["fsq_place_id"].to_list())
    rows = [("Source POIs", src_unique), ("Marked as closed", len(closed)), ("Open POIs entering quality filters", src_unique - len(closed))]
    for f in ["defunct", "outside_uk", "foreign_addresses", "postcode_mismatch", "duplicates", "business_changes", "registered_offices"]:
        s = set(ids.filter(pl.col("filter_type") == f)["fsq_place_id"].to_list()) - closed
        rows.append((f, len(s)))
    removed = set(ids["fsq_place_id"].to_list()) - closed
    rows += [("Failing at least one custom rule", len(removed)), ("Open POIs passing custom filters", len(kept_ids))]
    t = pd.DataFrame(rows, columns=["stage", "unique_pois"])
    t["matches_published_run"] = match
    t.to_csv(SANDBOX / "filter_table_rerun.csv", index=False)
    print(t.to_string(index=False))
    print("\nMATCHES run_20260610 exactly" if match else "\nDOES NOT match run_20260610")


if __name__ == "__main__":
    main()
