# Retail Centres Project

This project provides tools and scripts for identifying, analyzing, and exporting UK retail centre boundaries. The boundaries are create using open source POI (Point of Interest) data (Foursquare and/or Overture). 

## References
Previous boundaries;
- [Retail Centre Boundaries and Open Indicators Dataset](https://data.geods.ac.uk/dataset/retail-centre-boundaries-and-open-indicators)
- [Open Retail Centres: A National Open Data Set of Retail Centre Boundaries and Indicators (Nature Scientific Data, 2022)](https://www.nature.com/articles/s41597-022-01556-3)

## Project Structure
```
RetailCentres/
│
├── src/
│   ├── main.py                  # Main entry point for retail centre processing
│   ├── main_retailatend.py      # Alternative main script for end-to-end processing
│   ├── retail/                  # Core retail centre logic
│   │   ├── centre_postprocessing.py
│   │   ├── find_subcentres.py
│   │   ├── network_merger.py
│   │   ├── retailfilter.py
│   ├── utils/                   # Utility modules
│   │   ├── convtoshp.py         # GeoParquet to Shapefile/GeoJSON converter
│   │   ├── utils.py
│   └── __init__.py
├── data/                        # Input and output geospatial data
├── notebooks/                   # Jupyter notebooks for exploration and analysis
├── tests/                       # Unit tests
├── pyproject.toml               # Project dependencies and configuration
└── README.md                    # Project documentation
```

## How to Run

1. **Install dependencies** (recommended: use a virtual environment):
   ```bash
   uv pip install -r requirements.txt
   # or, if using pyproject.toml
   uv pip install -r requirements.txt
   # or, for editable mode
   uv pip install -e .
   ```

2. **Run the main script:**
   ```bash
   python src/main.py
   # or for the alternative workflow
   python src/main_retailatend.py
   ```

3. **Run tests:**
   ```bash
   uv pip install pytest
   pytest
   ```

4. **Convert GeoParquet to Shapefile/GeoJSON:**
   ```bash
   python src/utils/convtoshp.py <input_file.parquet> -f shapefile
   ```

---

## Last Run Command

```bash
python src/main.py --run_name nov2025v22_qualfiltreorgv2 --foursquare data/input_files/uk_foursquare_cc_nov_iceberg.parquet
```