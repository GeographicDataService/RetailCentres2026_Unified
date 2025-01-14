import polars as pl
import argparse
from shapely.geometry import Polygon, MultiPolygon
import networkx as nx
from collections import defaultdict
from itertools import combinations

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
    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Filter Foursquare data based on categories.")
    parser.add_argument("input_file", help="Path to the input Parquet file.")
    
    # Parse arguments
    args = parser.parse_args()
    
    # Load the Parquet file
    foursquare_data = pl.read_parquet(args.input_file)

    # Apply the filtering function
    filtered_foursquare = filter_foursquare(foursquare_data)

    # Save the output with the name appended "_retailfilt"
    output_file = args.input_file.replace(".parquet", "_retailfilt.parquet")
    filtered_foursquare.write_parquet(output_file)
    print(f"Filtered data saved to {output_file}")
