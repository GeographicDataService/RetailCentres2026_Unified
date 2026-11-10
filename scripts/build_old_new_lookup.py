#!/usr/bin/env python
"""
Build a 2022 -> 2026 retail centre lookup from shared H3 res-11 cells.

Both boundary sets are unions of res-11 cells, so overlap is counted exactly as
shared cells. One row per overlapping 2022/2026 pair; a centre can appear on
several rows (splits/merges). Centres absent from the file have no counterpart.

Output columns:
    RC_ID_2022, RC_Name_2022, RC_ID_2026, RC_Name_2026,
    Percent_of_2022_Centre   share of the 2022 centre's cells in this 2026 centre
    Percent_of_2026_Centre   share of the 2026 centre's cells from this 2022 centre
    Change_Type              for the group of centres linked by overlaps (as ONS CHGIND):
                             One-to-one, Split (one 2022 -> several 2026),
                             Merged (several 2022 -> one 2026), Complex (neither)

Usage:
    python scripts/build_old_new_lookup.py
    python scripts/build_old_new_lookup.py --old <path> --new <path> --output <csv>
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

from build_h3_lookup import build_lookup, normalise_ids, read_bounds


def cells(path: Path):
    bounds = read_bounds(path)
    bounds["RC_ID"] = normalise_ids(bounds["RC_ID"])
    lookup = build_lookup(bounds, "RC_ID")
    lookup["n"] = lookup.groupby("Retail_ID")["H3_11"].transform("size")
    return lookup, bounds.set_index("RC_ID")["RC_Name"]


def change_types(pairs: pd.DataFrame) -> pd.Series:
    """Label each pair by the connected group of centres it belongs to."""
    parent = {}

    def root(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in zip(pairs["RC_ID_2022"], pairs["RC_ID_2026"]):
        parent[root((2022, a))] = root((2026, b))
    group = pairs["RC_ID_2022"].map(lambda a: root((2022, a)))
    n22 = pairs.groupby(group)["RC_ID_2022"].transform("nunique")
    n26 = pairs.groupby(group)["RC_ID_2026"].transform("nunique")
    kind = pd.Series("Complex", index=pairs.index)
    kind[(n22 == 1) & (n26 > 1)] = "Split"
    kind[(n22 > 1) & (n26 == 1)] = "Merged"
    kind[(n22 == 1) & (n26 == 1)] = "One-to-one"
    return kind


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

    (old, old_names), (new, new_names) = cells(args.old), cells(args.new)
    pairs = (
        old.merge(new, on="H3_11", suffixes=("_old", "_new"))
        .groupby(["Retail_ID_old", "Retail_ID_new", "n_old", "n_new"])
        .size()
        .rename("shared")
        .reset_index()
    )
    lookup = pd.DataFrame({
        "RC_ID_2022": pairs["Retail_ID_old"],
        "RC_Name_2022": pairs["Retail_ID_old"].map(old_names),
        "RC_ID_2026": pairs["Retail_ID_new"],
        "RC_Name_2026": pairs["Retail_ID_new"].map(new_names),
        "Percent_of_2022_Centre": (100 * pairs["shared"] / pairs["n_old"]).round(2),
        "Percent_of_2026_Centre": (100 * pairs["shared"] / pairs["n_new"]).round(2),
    })
    lookup["Change_Type"] = change_types(lookup)

    # Cells belong to one centre per side, so shares can't exceed the whole centre.
    assert (lookup.groupby("RC_ID_2022")["Percent_of_2022_Centre"].sum() <= 100.01).all()
    assert (lookup.groupby("RC_ID_2026")["Percent_of_2026_Centre"].sum() <= 100.01).all()

    lookup.to_csv(args.output, index=False)
    print(
        f"Wrote {args.output}: {len(lookup):,} pairs, "
        f"{lookup['RC_ID_2022'].nunique():,}/{old['Retail_ID'].nunique():,} 2022 and "
        f"{lookup['RC_ID_2026'].nunique():,}/{new['Retail_ID'].nunique():,} 2026 centres matched; "
        + ", ".join(f"{k} {v:,}" for k, v in lookup["Change_Type"].value_counts().items())
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
