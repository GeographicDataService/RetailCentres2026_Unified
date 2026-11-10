"""Step 3. Results of the manual audit of random samples (paper Sections 3.4, 4.1, 4.2.2).

The sample (outputs/audit/cases.gpkg, sample_frame.csv) was drawn once by prep/build_audit.py and labelled with
prep/label_server.py (outputs/audit/labels.csv); the question asked of each case is in audit/README.md.
Writes outputs/audit/results.csv: per stratum, the population, cases sampled, and yes / no / unsure answers.
Run from repo root:  .venv/bin/python validation/audit.py
"""
import geopandas as gpd
import pandas as pd

from common import OUT

AUDIT = OUT / "audit"
STRATA = {  # stratum: what "yes" means
    "landuse_removal": "the removed candidate is a retail centre (removal wrong)",
    "merge": "the two merged parts form one continuous centre (merge right)",
    "retail_park": "the detected park is a car-oriented park with an operating big-box store (park right)",
    "missing_top": "the absent 2022 centre, one of the 20 largest, is a retail centre",
    "missing_slc": "the absent 2022 centre, drawn at random, is a retail centre",
}


def main():
    cases = gpd.read_file(AUDIT / "cases.gpkg", layer="cases")[["case_id", "stratum"]]
    labels = pd.read_csv(AUDIT / "labels.csv", dtype=str).drop_duplicates("case_id", keep="last")[["case_id", "label"]]
    population = pd.read_csv(AUDIT / "sample_frame.csv").set_index("stratum").population
    d = cases.merge(labels, on="case_id", how="left")
    rows = [{"stratum": s, "yes_means": m, "population": int(population[s]), "sampled": int((d.stratum == s).sum()),
             **{k: int(((d.stratum == s) & (d.label == k)).sum()) for k in ["yes", "no", "unsure"]}} for s, m in STRATA.items()]
    t = pd.DataFrame(rows)
    t.to_csv(AUDIT / "results.csv", index=False)
    print(t.drop(columns="yes_means").to_string(index=False))


if __name__ == "__main__":
    main()
