import argparse
import polars as pl
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from pathlib import Path
import utils as ut  # Make sure this is your utility module with add_h3_11_column()

def filter_foursquare(foursquare):
    foursquare = foursquare.filter(
        (foursquare["level1_category_name"] == "Retail")
        | (foursquare["level1_category_name"] == "Dining and Drinking")
        | (foursquare["level1_category_name"] == "Arts and Entertainment")
        | (foursquare["level1_category_name"] == "Sports and Recreation")
        | (foursquare["level2_category_name"] == "Health and Beauty Service")  # business
        | (foursquare["level2_category_name"] == "Automotive Service")  # business
        # | (foursquare["level3_category_name"] == "ATM") # business, financial service
        | (foursquare["level4_category_name"] == "Bank") # business, financial service
        | (foursquare["level3_category_name"] == "Credit Union") # business, financial service
        | (foursquare["level3_category_name"] == "Real Estate Agency") # business, real estate service
        | (foursquare["level3_category_name"] == "Law Office") 
        | (foursquare["level3_category_name"] == "Loans Agency") # business, financial service
        # | (foursquare["level3_category_name"] == "Insurance Agency") # business, financial service
        | (foursquare["level2_category_name"] == "Computer Repair Service") # business
        | (foursquare["level2_category_name"] == "Pet Service") # business
        | (foursquare["level2_category_name"] == "Photography Service") # business
        | (foursquare["level2_category_name"] == "Locksmith") # business
        | (foursquare["level2_category_name"] == "Funeral Home") # business
        | (foursquare["level3_category_name"] == "Coworking Space") # business, office
        | (foursquare["level2_category_name"] == "Laundry Service") # business
        | (foursquare["level2_category_name"] == "Laundromat") # business
        # transport
        | (foursquare["level2_category_name"] == "Fuel Station") # transport
        | (foursquare["level2_category_name"] == "Travel Agency") # transport
        | (foursquare["level2_category_name"] == "Tourist Information and Service") # transport (covers tourist info shops and some travel agencies)
        # medical 
        | (foursquare["level3_category_name"] == "Doctors Office") # most GPs
        | (foursquare["level2_category_name"] == "Dentist") # dentists
        | (foursquare["level2_category_name"] == "Veterinarian") # vets
        | (foursquare["level2_category_name"] == "Physical Therapy Clinic") # physio
        # community
        | (foursquare["level3_category_name"] == "Post Office") # community
        | (foursquare["level2_category_name"] == "Library") # community
        | (foursquare["level2_category_name"] == "Community Center") # community
        | (foursquare["level2_category_name"] == "Social Club") # community
    )

    # Accounting, mental health service, charities are a bit of a mess.

    # load alex's filter
    cats = pl.read_csv("data/POI_files/alex_filter.csv")
    # set the nulls in the remove column to 0
    cats = cats.with_columns(
        pl.col("Remove").fill_null(0).cast(pl.Int64)
    )
    cats = cats.filter(~(cats["Remove"] == 1))

    def filter_matching_categories(data_df, reference_df):
        """
        Filter rows in data_df where the category hierarchy matches one from reference_df,
        considering null values as valid matches when they appear in both DataFrames.
        """
        category_cols = [
            'level1_category_name',
            'level2_category_name',
            'level3_category_name',
            'level4_category_name'
        ]
        
        # Create an expression that matches categories including nulls
        conditions = []
        
        for col in category_cols:
            # A category matches if either:
            # 1. Both values are null, or
            # 2. The value exists in the reference DataFrame for this column
            condition = (
                (pl.col(col).is_null() & pl.lit(reference_df[col].null_count() > 0)) |
                pl.col(col).is_in(reference_df.select(col).filter(pl.col(col).is_not_null()).unique())
            )
            conditions.append(condition)
        
        # Combine all conditions with AND
        final_condition = conditions[0]
        for cond in conditions[1:]:
            final_condition = final_condition & cond
        
        # Apply the filter
        result = data_df.filter(final_condition)
        
        return result

    foursquare = filter_matching_categories(foursquare, cats)
    # remove any with a date closed
    foursquare = foursquare.filter(foursquare["date_closed"].is_null())
    # remove any with same name and lat lng (some have multiple categories)
    foursquare = foursquare.unique(subset=["name","lat","lng"])
    
    return foursquare

# Add the main block
if __name__ == "__main__":

    COLUMNS_TO_KEEP = [
        "fsq_place_id", "name", "lat", "lng", "address", "locality", "region",
        "postcode", "admin_region", "post_town", "po_box", "country",
        "date_created", "date_refreshed", "date_closed", "tel", "website","fsq_category_ids", "fsq_category_labels",
        "h3_11"  # Added here
    ]
    parser = argparse.ArgumentParser(description="Convert Foursquare data with H3 to GeoParquet.")
    parser.add_argument("input_file", help="Path to the input Parquet file.")
    args = parser.parse_args()

    # Load Parquet using Polars
    fsq_data = pl.read_parquet(args.input_file)

    # Add H3 column FIRST
    fsq_data = ut.add_h3_11_column(fsq_data)

    # Optional filtering (if desired)
    fsq_data = filter_foursquare(fsq_data)

    # Keep only necessary columns
    fsq_data = fsq_data.select(COLUMNS_TO_KEEP)

    # Convert to Pandas DataFrame
    fsq_df = fsq_data.to_pandas()

    # Create geometry from lat/lng
    fsq_df["geometry"] = [
        Point(xy) if pd.notnull(xy[0]) and pd.notnull(xy[1]) else None
        for xy in zip(fsq_df["lng"], fsq_df["lat"])
    ]
    fsq_df = fsq_df[fsq_df["geometry"].notnull()]

    # Convert to GeoDataFrame
    gdf = gpd.GeoDataFrame(fsq_df, geometry="geometry", crs="EPSG:4326")

    # Prepare output filename
    output_path = Path(args.input_file).with_stem(Path(args.input_file).stem + "_retailfilt_geo")
    gdf.to_parquet(output_path)
    print(f"✅ Saved GeoDataFrame with H3 to {output_path}")

