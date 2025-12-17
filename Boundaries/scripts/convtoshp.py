from pathlib import Path
import os
import geopandas as gpd
import shutil
import argparse

def convert_geoparquet(input_path, output_format="shapefile", output_path=None, output_name=None):
    gdf = gpd.read_parquet(input_path)

    #drop 'category_names'
    if 'category_names' in gdf.columns:
        gdf = gdf.drop(columns=['category_names'])
    # Prepare output directory
    output_dir = Path("data/forarcgis")
    output_dir.mkdir(parents=True, exist_ok=True)

    input_stem = Path(input_path).stem  # e.g. 'myfile' from 'myfile.parquet'
    if output_name is not None:
        input_stem = output_name  # Use provided output name if given
    if output_format.lower() == "shapefile":
        if output_path is None:
            output_path = output_dir / input_stem
        shapefile_dir = output_path.with_suffix('').as_posix() + "_shp"
        os.makedirs(shapefile_dir, exist_ok=True)

        gdf.to_file(os.path.join(shapefile_dir, input_stem + ".shp"), driver="ESRI Shapefile")

        zip_path = output_path.with_suffix(".zip")
        shutil.make_archive(output_path.as_posix(), 'zip', shapefile_dir)
        shutil.rmtree(shapefile_dir)
        print(f"Saved zipped shapefile to: {zip_path}")

    elif output_format.lower() == "geojson":
        if output_path is None:
            output_path = output_dir / (input_stem + ".geojson")
        gdf.to_file(output_path, driver="GeoJSON")
        print(f"Saved GeoJSON to: {output_path}")

    elif output_format == "geopackage" or output_format == "gpkg":
        if output_path is None:
            output_path = output_dir / (input_stem + ".gpkg")
        gdf.to_file(output_path, driver="GPKG", layer=input_stem)
        print(f"Saved GeoPackage to: {output_path}")

    else:
        raise ValueError("Unsupported format. Use 'shapefile', 'geopackage' or 'geojson'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert GeoParquet to ArcGIS Online-supported format.")
    parser.add_argument("input", help="Path to the input .parquet file")
    parser.add_argument("-f", "--format", choices=["shapefile", "geojson", "geopackage"], default="shapefile",
                        help="Output format (default: shapefile)")
    parser.add_argument("-o", "--output", help="Optional: Output file path (default goes to data/forarcgis)")
    parser.add_argument("-n", "--output_name", help="Optional: Name for the output file without extension (default is input file name)")
    args = parser.parse_args()

    convert_geoparquet(args.input, args.format, args.output, args.output_name)