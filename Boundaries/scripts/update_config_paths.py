#!/usr/bin/env python
"""
Update config.py with new data directory paths after migration.
"""

from pathlib import Path


def update_config():
    """Update config.py with new directory structure paths."""
    config_path = Path("src/config.py")

    if not config_path.exists():
        print(f"❌ Error: config.py not found at {config_path}")
        return 1

    print("\n" + "="*80)
    print("UPDATING CONFIG.PY")
    print("="*80)

    # Read current config
    with open(config_path, 'r') as f:
        content = f.read()

    # Backup original
    backup_path = config_path.with_suffix('.py.backup')
    with open(backup_path, 'w') as f:
        f.write(content)
    print(f"✓ Created backup: {backup_path}")

    # Update paths
    replacements = {
        # Base directories
        'INPUT_FILES_DIR = DATA_DIR / "input_files"': 'INPUTS_DIR = DATA_DIR / "inputs"',
        'OUTPUT_FILES_DIR = DATA_DIR / "output_files"': 'RUNS_DIR = DATA_DIR / "outputs" / "runs"',
        'POI_FILES_DIR = DATA_DIR / "POI_files"': 'INTERMEDIATE_DIR = DATA_DIR / "intermediate"',
        'BOUNDARIES_DIR = DATA_DIR / "Boundaries_lookups"': 'BOUNDARIES_DIR = INPUTS_DIR / "boundaries"',

        # Input files - POI
        'FOURSQUARE_PATH = INPUT_FILES_DIR / "uk_foursquare_cc_nov_iceberg.parquet"':
            'FOURSQUARE_PATH = INPUTS_DIR / "poi" / "uk_foursquare_cc_nov_iceberg.parquet"',

        # Input files - Land use
        'COMMERCIAL_LANDUSE_PATH = INPUT_FILES_DIR / "commercial_landuse.parquet"':
            'LANDUSE_DIR = INPUTS_DIR / "landuse"\nCOMMERCIAL_LANDUSE_PATH = LANDUSE_DIR / "commercial_landuse.parquet"',
        'INDUSTRIAL_LANDUSE_PATH = INPUT_FILES_DIR / "industrial_landuse.parquet"':
            'INDUSTRIAL_LANDUSE_PATH = LANDUSE_DIR / "industrial_landuse.parquet"',
        'RETAIL_LANDUSE_H3_GEO_PATH = INPUT_FILES_DIR / "retail_landuse_h3_geo.parquet"':
            'RETAIL_LANDUSE_H3_GEO_PATH = LANDUSE_DIR / "retail_landuse_h3_geo.parquet"',
        'RETAIL_LANDUSE_POLYGONS_PATH = INPUT_FILES_DIR / "retail_landuse.parquet"':
            'RETAIL_LANDUSE_POLYGONS_PATH = LANDUSE_DIR / "retail_landuse.parquet"',

        # Input files - Brands
        'RETAIL_PARK_BRANDS_PATH = INPUT_FILES_DIR / "bl_retail_parks_brands_deduped.csv"':
            'BRANDS_DIR = INPUTS_DIR / "brands"\nRETAIL_PARK_BRANDS_PATH = BRANDS_DIR / "retail_park_brands.csv"',

        # Intermediate files
        'FILTER_IDS_PATH = POI_FILES_DIR / "quality_filter_ids.parquet"':
            'FILTER_IDS_PATH = INTERMEDIATE_DIR / "poi_filtered" / "quality_filter_ids.parquet"',

        # Outputs
        'OUTPUT_FILES_DIR = OUTPUTS_DIR':
            'RUNS_DIR = DATA_DIR / "outputs" / "runs"\nARCGIS_EXPORTS_DIR = DATA_DIR / "outputs" / "arcgis_exports"',
    }

    for old, new in replacements.items():
        if old in content:
            content = content.replace(old, new)
            print(f"  ✓ Updated: {old.split('=')[0].strip()}")

    # Write updated config
    with open(config_path, 'w') as f:
        f.write(content)

    print("\n✓ config.py updated successfully!")
    print(f"  Original backed up to: {backup_path}")

    return 0


def main():
    return update_config()


if __name__ == "__main__":
    exit(main())
