#!/usr/bin/env python
"""
Build an old (2022) -> new retail centre lookup from shared H3 res-11 cells.

Both boundary sets are unions of res-11 cells, so overlap is counted exactly as
shared cells. One row per overlapping old/new pair; a centre can appear on
several rows (splits/merges). Centres absent from the file have no counterpart.

Output columns: Old_RC_ID,New_RC_ID,Pct_of_Old,Pct_of_New

Usage:
    python scripts/build_old_new_lookup.py
    python scripts/build_old_new_lookup.py --old <path> --new <path> --output <csv>
"""

import argparse
import sys
from pathlib import Path

from build_h3_lookup import build_lookup, normalise_ids, read_bounds


def cells(path: Path):
    bounds = read_bounds(path)
    bounds["RC_ID"] = normalise_ids(bounds["RC_ID"])
    lookup = build_lookup(bounds, "RC_ID")
    lookup["n"] = lookup.groupby("Retail_ID")["H3_11"].transform("size")
    return lookup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--old", type=Path, default=Path("Classification/geo/old_retail_mapmaker/Retail_Boundaries_UK.gpkg"))
    parser.add_argument("--new", type=Path, default=Path("Naming/exports/retailcentre_bounds_uk.gpkg"))
    parser.add_argument("--output", type=Path, default=Path("Naming/exports/retailcentre_old_new_lookup.csv"))
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing output file")
    args = parser.parse_args()

    if args.output.exists() and not args.overwrite:
        print(f"ERROR: {args.output} already exists. Pass --overwrite to replace it.")
        return 1

    old, new = cells(args.old), cells(args.new)
    pairs = (
        old.merge(new, on="H3_11", suffixes=("_old", "_new"))
        .groupby(["Retail_ID_old", "Retail_ID_new", "n_old", "n_new"])
        .size()
        .rename("shared")
        .reset_index()
    )
    lookup = pairs.assign(
        Old_RC_ID=pairs["Retail_ID_old"],
        New_RC_ID=pairs["Retail_ID_new"],
        Pct_of_Old=(pairs["shared"] / pairs["n_old"]).round(4),
        Pct_of_New=(pairs["shared"] / pairs["n_new"]).round(4),
    )[["Old_RC_ID", "New_RC_ID", "Pct_of_Old", "Pct_of_New"]]

    # Cells belong to one centre per side, so shares can't exceed the whole centre.
    assert (lookup.groupby("Old_RC_ID")["Pct_of_Old"].sum() <= 1.0001).all()
    assert (lookup.groupby("New_RC_ID")["Pct_of_New"].sum() <= 1.0001).all()

    lookup.to_csv(args.output, index=False)
    print(
        f"Wrote {args.output}: {len(lookup):,} pairs, "
        f"{lookup['Old_RC_ID'].nunique():,}/{old['Retail_ID'].nunique():,} old and "
        f"{lookup['New_RC_ID'].nunique():,}/{new['Retail_ID'].nunique():,} new centres matched"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
