# Foursquare POI retrieval

Produces the **UK Foursquare POI file** that the [`Boundaries/`](../Boundaries/) pipeline
consumes at `Boundaries/data/inputs/poi/uk_foursquare_cc_nov_iceberg.parquet`. This sits
*upstream* of Boundaries in the workspace pipeline.

It queries Foursquare OS Places via [DuckDB](https://duckdb.org/) and normalises the
result into the fields used downstream. The current file is built from the
**November** Foursquare release (hence the `_nov_` in the filename). Adapted from the
[`cjber/overture-uk`](https://github.com/cjber/overture-uk) project by
[Patrick Ballantyne](https://www.liverpool.ac.uk/environmental-sciences/staff/patrick-ballantyne)
and Cillian Berragan (Geographic Data Science Lab, University of Liverpool).
FigShare: https://doi.org/10.6084/m9.figshare.24347653 — see [REPRODUCE.md](REPRODUCE.md)
for the original methodology and the source data links.

## Pipeline

Two stages (orchestrated by [`run_foursquare.sh`](run_foursquare.sh)):

1. **query** — `src/query_foursquare_bycc_iceberg.py` queries the Foursquare ICEBERG
   catalog for a country code → `data/raw/<filename>.gpkg`.
   (`src/query_foursquare_bycc.py` is a fallback that reads a local Overture parquet dump.)
2. **clean** — `src/clean_foursquare.py` builds geometry, explodes category lists and joins
   the Foursquare category labels → `data/processed/<filename>.parquet`. This is the file
   Boundaries reads.

## Run

Uses the single shared workspace `.venv` (see the [root README](../README.md)).

```bash
source ../.venv/bin/activate

# One-time: provide a Foursquare ICEBERG token
cp .env.example .env        # then edit .env and set FOURSQUARE_ICEBERG_TOKEN
# Get the token from the "Access via code" / API section of the Foursquare OS Places
# dataset page: https://places.foursquare.com/dataset/OS%20Places/code
# It is a JWT (starts with "eyJ..."); paste the whole string as FOURSQUARE_ICEBERG_TOKEN.

# Run both stages
cd Foursquare_POI_retrieval
./run_foursquare.sh

# Hand the output to Boundaries
cp data/processed/uk_foursquare_cc_nov_iceberg.parquet \
   ../Boundaries/data/inputs/poi/uk_foursquare_cc_nov_iceberg.parquet
```

## Input data

Both stages need only the Foursquare token — no other input files are required. (Intermediate
and output files under `data/` are gitignored.)
