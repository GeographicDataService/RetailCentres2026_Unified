"""Run the retail-centre naming pipeline end to end.

Pipeline order:
  0. (setup, run once)  python download_data.py   - fetch reference boundary data into data/
  1. naming.py           - build the naming lookup tables  -> exports/RC_Naming_*.csv
  2. generate_names.py   - assemble the final names        -> exports/rc2025_named.{gpkg,parquet}

This entry point runs stages 1 and 2 in order. Run download_data.py separately
first if the reference data in data/ is not yet present (see README). Ad-hoc
comparison/analysis utilities live in scripts/ and are not part of this flow.
"""

from naming import main as build_naming_lookups
from generate_names import generate_names as assemble_final_names


def main() -> None:
    print("=== Stage 1: building naming lookup tables (naming.py) ===")
    build_naming_lookups()

    print("\n=== Stage 2: assembling final names (generate_names.py) ===")
    assemble_final_names()

    print("\n=== Naming pipeline complete ===")


if __name__ == "__main__":
    main()
