#!/usr/bin/env python3
"""Check whether RC_ID values in retailcentre_bounds_uk.parquet are unique."""
import sys
import pandas as pd

PATH = sys.argv[1] if len(sys.argv) > 1 else "retailcentre_bounds_uk.parquet"

df = pd.read_parquet(PATH, columns=["RC_ID"])

total = len(df)
unique = df["RC_ID"].nunique(dropna=False)
nulls = df["RC_ID"].isna().sum()

print(f"File:          {PATH}")
print(f"Total rows:    {total}")
print(f"Unique RC_ID:  {unique}")
print(f"Null RC_ID:    {nulls}")
print(f"All unique:    {unique == total and nulls == 0}")

dupes = df[df["RC_ID"].duplicated(keep=False)].sort_values("RC_ID")
if not dupes.empty:
    print(f"\nDuplicated RC_IDs ({dupes['RC_ID'].nunique()} ids, {len(dupes)} rows):")
    print(dupes["RC_ID"].value_counts().to_string())
