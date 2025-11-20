import os
import argparse
import polars as pl
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from pathlib import Path
from utils import utils as ut


# Make sure NLTK names are available
import nltk
nltk.download('names')

# Preload British names once
BRITISH_NAMES = set(nltk.corpus.names.words())

def is_just_british_name(name: str, british_names: set) -> bool:
    tokens = name.strip().title().split()
    return len(tokens) == 2 and all(token in british_names for token in tokens)



def filter_foursquare(foursquare):
    foursquare = foursquare.filter(
        (foursquare["level1_category_name"] == "Retail")
        | (foursquare["level1_category_name"] == "Dining and Drinking")
        | (foursquare["level1_category_name"] == "Arts and Entertainment")
        # | (foursquare["level1_category_name"] == "Sports and Recreation")
        | (foursquare["level2_category_name"] == "Health and Beauty Service") #business
        # | (foursquare["level3_category_name"] == "ATM") # business, financial service
        | (foursquare["level4_category_name"] == "Bank") # business, financial service
        | (foursquare["level3_category_name"] == "Credit Union") # business, financial service
        | (foursquare["level3_category_name"] == "Real Estate Agency") # business, real estate service
        | (foursquare["level3_category_name"] == "Law Office") 
        | (foursquare["level3_category_name"] == "Loans Agency") # business, financial service
        # | (foursquare["level3_category_name"] == "Insurance Agency") # business, financial service
        # | (foursquare["level2_category_name"] == "Computer Repair Service") # business
        | (foursquare["level2_category_name"] == "Pet Service") # business
        | (foursquare["level2_category_name"] == "Photography Service") # business
        | (foursquare["level2_category_name"] == "Locksmith") # business
        | (foursquare["level2_category_name"] == "Funeral Home") # business
        # | (foursquare["level3_category_name"] == "Coworking Space") # business, office
        | (foursquare["level2_category_name"] == "Laundry Service") # business
        | (foursquare["level2_category_name"] == "Laundromat") # business
        # transport
        | (foursquare["level2_category_name"] == "Fuel Station") # transport
        | (foursquare["level2_category_name"] == "Travel Agency") # transport
        | (foursquare["level2_category_name"] == "Tourist Information and Service") # transport (covers tourist info shops and some travel agencies)
        # medical 
        | (foursquare["level3_category_name"] == "Doctor's Office") # most GPs
        | (foursquare["level2_category_name"] == "Dentist") # dentists
        | (foursquare["level2_category_name"] == "Veterinarian") # vets
        | (foursquare["level2_category_name"] == "Physical Therapy Clinic") # physio
        # community
        | (foursquare["level3_category_name"] == "Post Office") # community
        | (foursquare["level2_category_name"] == "Library") # community
        | (foursquare["level2_category_name"] == "Community Center") # community
        | (foursquare["level2_category_name"] == "Social Club") # community
        #sports
        | (foursquare["level2_category_name"] == "Gym and Studio") # gyms
        | (foursquare["level2_category_name"] == "Indoor Play Area") 
        | (foursquare["level2_category_name"] == "Martial Arts Dojo") 
        | (foursquare["level4_category_name"] == "Swimming Pool") # sports

    )


    #remove some which pass the higher level
    foursquare = foursquare.filter(
        (foursquare["level2_category_name"].is_null()) | #important to keep this, otherwise we lose some categories
        (   #arts and entertainment
            (foursquare["level2_category_name"] != "Amusement Park") & 
            (foursquare["level2_category_name"] != "Disc Golf") & 
            (foursquare["level2_category_name"] != "Disc Golf Course") & 
            (foursquare["level2_category_name"] != "Auction House") &
            (foursquare["level2_category_name"] != "Exhibit") &
            (foursquare["level2_category_name"] != "Fair") &
            (foursquare["level2_category_name"] != "Stadium") &
            (foursquare["level2_category_name"] != "Museum") &
            (foursquare["level2_category_name"] != "Zoo") &
            # #business
            # (foursquare["level2_category_name"] != "Automotive Service")
            #dining and drinking
            (foursquare["level2_category_name"] != "Vineyard") &
            #retail
            (foursquare["level2_category_name"] != "Auction House") &
            (foursquare["level2_category_name"] != "Construction Supplies Store")
        )
    )
    print(f"Filtered Foursquare data (Retail Cats): {foursquare.shape[0]} rows remaining.")    


    # Accounting, mental health service, charities are a bit of a mess.
    #remove any with a "Post Box" as name
    foursquare = foursquare.filter(~pl.col("name").is_in(["Post Box", "Postbox", "Post box"]))

    print(f"Filtered Foursquare data (remove post box): {foursquare.shape[0]} rows remaining.")   

       # Identify rows where name is just a British name
# Apply the function to create a boolean mask
    # foursquare = foursquare.with_columns([
    #     pl.col("name").map_elements(lambda x: is_just_british_name(str(x), BRITISH_NAMES)).alias("is_name_only")
    # ])

    # # Split into removed and cleaned
    # print(len(foursquare))
    # removed_df = foursquare.filter((pl.col("is_name_only")) & (pl.col("level1_category_name") == "Business and Professional Services"))
    # foursquare = foursquare.filter(~pl.col("is_name_only") | (pl.col("level1_category_name") != "Business and Professional Services"))
  
    # # Save removed names to Parquet
    # if removed_df.height > 0:

    #     removed_df.write_parquet("data/POI_files/removed_british_names.parquet")
    #     print(f"Removed {removed_df.height} rows where name was just a British name. Saved to data/POI_files/removed_british_names.parquet")

    # Filter for open locations
    foursquare = foursquare.filter(pl.col("date_closed").is_null())
    print(f"Filtered Foursquare data (remove closed): {foursquare.shape[0]} rows remaining.")   
    # remove any with same name and lat lng (some have multiple categories)
    foursquare = foursquare.unique(subset=["name","lat","lng"])

    print(f"Filtered Foursquare data (remove cat dupes): {foursquare.shape[0]} rows remaining.")

    # #remove anything with a date refreshed before 2020
    # foursquare = foursquare.filter(pl.col("date_refreshed") >= "2020-01-01")
    # print(f"Filtered Foursquare data (date refreshed): {foursquare.shape[0]} rows remaining.")
    return foursquare



def filter_foursquare_invmethod(foursquare):
    foursquare_filt = foursquare.filter(
        (foursquare["level1_category_name"] == "Retail")
        | (foursquare["level1_category_name"] == "Dining and Drinking")
        | (foursquare["level1_category_name"] == "Arts and Entertainment")
        # | (foursquare["level1_category_name"] == "Sports and Recreation")
        | (foursquare["level2_category_name"] == "Health and Beauty Service") #business
        # | (foursquare["level3_category_name"] == "ATM") # business, financial service
        | (foursquare["level4_category_name"] == "Bank") # business, financial service
        | (foursquare["level3_category_name"] == "Credit Union") # business, financial service
        | (foursquare["level3_category_name"] == "Real Estate Agency") # business, real estate service
        # | (foursquare["level3_category_name"] == "Law Office") 
        | (foursquare["level3_category_name"] == "Loans Agency") # business, financial service
        # | (foursquare["level3_category_name"] == "Insurance Agency") # business, financial service
        # | (foursquare["level2_category_name"] == "Computer Repair Service") # business
        | (foursquare["level2_category_name"] == "Pet Service") # business
        | (foursquare["level2_category_name"] == "Photography Service") # business
        | (foursquare["level2_category_name"] == "Locksmith") # business
        | (foursquare["level2_category_name"] == "Funeral Home") # business
        # | (foursquare["level3_category_name"] == "Coworking Space") # business, office
        | (foursquare["level2_category_name"] == "Laundry Service") # business
        | (foursquare["level2_category_name"] == "Laundromat") # business
        # transport
        | (foursquare["level2_category_name"] == "Fuel Station") # transport
        | (foursquare["level2_category_name"] == "Travel Agency") # transport
        | (foursquare["level2_category_name"] == "Tourist Information and Service") # transport (covers tourist info shops and some travel agencies)
        # medical 
        | (foursquare["level3_category_name"] == "Doctor's Office") # most GPs
        | (foursquare["level2_category_name"] == "Dentist") # dentists
        | (foursquare["level2_category_name"] == "Veterinarian") # vets
        | (foursquare["level2_category_name"] == "Physical Therapy Clinic") # physio
        # community
        | (foursquare["level3_category_name"] == "Post Office") # community
        | (foursquare["level2_category_name"] == "Library") # community
        | (foursquare["level2_category_name"] == "Community Center") # community
        | (foursquare["level2_category_name"] == "Social Club") # community
        #sports
        | (foursquare["level2_category_name"] == "Gym and Studio") # gyms
        | (foursquare["level2_category_name"] == "Indoor Play Area") 
        | (foursquare["level2_category_name"] == "Martial Arts Dojo") 
        | (foursquare["level4_category_name"] == "Swimming Pool") # sports
    )


    # Define categories to exclude with their level
    categories_to_exclude_higherlevelinc = [
        ("level2_category_name", "Amusement Park"),
        ("level2_category_name", "Disc Golf"),
        ("level2_category_name", "Disc Golf Course"),
        ("level2_category_name", "Go Kart Track"),

        ("level2_category_name", "Exhibit"),
        ("level2_category_name", "Psychic and Astrologer"),
        ("level2_category_name","Carnival"),
        ("level2_category_name","Circus"),

        ("level2_category_name", "Fair"),
        ("level2_category_name", "Stadium"),
        ("level2_category_name", "Museum"),
        ("level2_category_name", "Zoo"),
        ("level2_category_name", "Aquarium"),

        ("level2_category_name", "Auction House"),
        ("level2_category_name", "Vineyard"),
        ("level2_category_name", "Construction Supplies Store"),
        #Malls
        ("level2_category_name", "Outlet Mall"),
        ("level2_category_name", "Shopping Mall"),
        ("level2_category_name", "Shopping Plaza"),
        
        # #new ones
        ("level3_category_name", "Photographer"),
        ("level3_category_name", "Photography Studio"),
        ("level3_category_name", "Photography Lab"),
        
    ]

    #by association / confusion
    categories_to_exclude_byassociation = [
        #Public Art
        ("level2_category_name", "Public Art"),

        #Ad agencies (often get included with Print Shop retail category)
        ("level2_category_name", "Advertising Agency"),

        #Car Dealership and Motorcycle Dealerships
        ("level3_category_name", "Car Dealership"),
        ("level3_category_name", "Motorcycle Dealership"),
        ("level3_category_name", "Motor Scooter Dealership"),

        #Real Estate Development and Title Company" #gets included with Real Estate Agency
        ("level3_category_name", "Real Estate Development and Title Company"),
        #Commercial Real Estate Developer
        ("level3_category_name", "Commercial Real Estate Developer"),

        #Hospital - removes some POIs included with Doctor's Office
        ("level2_category_name", "Hospital")

    ]

    # Check that all categories catch some POIs in the full dataset
    all_categories = categories_to_exclude_higherlevelinc + categories_to_exclude_byassociation
    for col_name, category in all_categories:
        count = foursquare.filter(pl.col(col_name) == category).height
        if count == 0:
            raise ValueError(f"No POIs found for excluded category '{category}' in column '{col_name}'")
    # Filter higherlevelinc categories: remove only matching rows (keep nulls)
    exclude_higherlevel_condition = pl.lit(False)
    for col_name, category in categories_to_exclude_higherlevelinc:
        # Use fill_null to treat nulls as False (i.e., don't exclude)
        exclude_higherlevel_condition = exclude_higherlevel_condition | (
            (pl.col(col_name) == category).fill_null(False)
        )
    foursquare_filt = foursquare_filt.filter(~exclude_higherlevel_condition)


    # Filter byassociation categories: remove all rows with matching POI IDs
    exclude_byassociation_condition = pl.lit(False)
    for col_name, category in categories_to_exclude_byassociation:
        exclude_byassociation_condition = exclude_byassociation_condition | (pl.col(col_name) == category)

    pois_to_exclude = (
        foursquare
        .filter(exclude_byassociation_condition)
        .select("fsq_place_id")
        .unique()
    )

    foursquare_filt = foursquare_filt.join(
        pois_to_exclude,
        on="fsq_place_id",
        how="anti"
    )

    print(f"Filtered Foursquare data (Retail Cats): {foursquare_filt.shape[0]} rows remaining.")    


    #remove all "Warehouse or Wholesale Store" unless "Argos", others are likely storage units or B2B only
    foursquare_filt = foursquare_filt.filter(
        (pl.col("level2_category_name") != "Warehouse or Wholesale Store").fill_null(True) | (pl.col("name") == "Argos")
    )
    print(f"Kept {foursquare_filt.filter(pl.col('level2_category_name') == 'Warehouse or Wholesale Store').shape[0]}  Argos 'Warehouse or Wholesale Store' entries after filtering.")
    print(f"Filtered Foursquare data (remove non-Argos warehouse): {foursquare_filt.shape[0]} rows remaining.")



    # find all with name containing "Costa" (case-insensitive, matches "Costa", "Costa Express", etc.) and remove 
    foursquare_filt = foursquare_filt.filter(~(pl.col("name").str.contains(r"(?i)costa", literal=False) & pl.col("name").str.contains(r"(?i)express", literal=False) ))

    print(f"Filtered Foursquare data (find Costa Express): {foursquare_filt.shape[0]} rows remaining.")

    
    #remove any with a "Post Box" as name
    foursquare_filt = foursquare_filt.filter(~pl.col("name").is_in(["Post Box", "Postbox", "Post box"]))

    print(f"Filtered Foursquare data (remove post box): {foursquare_filt.shape[0]} rows remaining.")

    

       # Identify rows where name is just a British name
# Apply the function to create a boolean mask
    # foursquare = foursquare.with_columns([
    #     pl.col("name").map_elements(lambda x: is_just_british_name(str(x), BRITISH_NAMES)).alias("is_name_only")
    # ])

    # # Split into removed and cleaned
    # print(len(foursquare))
    # removed_df = foursquare.filter((pl.col("is_name_only")) & (pl.col("level1_category_name") == "Business and Professional Services"))
    # foursquare = foursquare.filter(~pl.col("is_name_only") | (pl.col("level1_category_name") != "Business and Professional Services"))
  
    # # Save removed names to Parquet
    # if removed_df.height > 0:

    #     removed_df.write_parquet("data/POI_files/removed_british_names.parquet")
    #     print(f"Removed {removed_df.height} rows where name was just a British name. Saved to data/POI_files/removed_british_names.parquet")

    # Filter for open locations
    foursquare_filt = foursquare_filt.filter(pl.col("date_closed").is_null())
    print(f"Filtered Foursquare data (remove closed): {foursquare_filt.shape[0]} rows remaining.")
    # remove any with same name and lat lng (some have multiple categories)
    foursquare_filt = foursquare_filt.unique(subset=["name","lat","lng"])


    print(f"Filtered Foursquare data (remove cat dupes): {foursquare_filt.shape[0]} rows remaining.")   

    # #remove anything with a date refreshed before 2020
    # foursquare = foursquare.filter(pl.col("date_refreshed") >= "2020-01-01")
    # print(f"Filtered Foursquare data (date refreshed): {foursquare.shape[0]} rows remaining.")
    return foursquare_filt



def filter_overture(overture):
    overture = overture.filter(
        (overture["level1_category_name"] == "retail")
        | (overture["level1_category_name"] == "eat_and_drink")
        | (overture["level1_category_name"] == "beauty_and_spa")
        | (overture["level1_category_name"] == "arts_and_entertainment")
        | (overture["level2_category_name"] == "activate_life")
        | (overture["level1_category_name"] == "automotive")
        | (overture["level2_category_name"] == "art_gallery")
        | (overture["level2_category_name"] == "museum")
    )
    return overture
# Import necessary libraries

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

    #print full list of unique fsq_category_labels (sorted) to csv
    unique_categories = gdf["fsq_category_labels"].unique().sort_values()
    unique_categories.to_csv("data/POI_files/fsq_unique_categories.csv", index=False)

    # Prepare output filename
    output_path = Path(args.input_file).with_stem(Path(args.input_file).stem + "_retailfilt_geo")
    gdf.to_parquet(output_path)
    print(f"✅ Saved GeoDataFrame with H3 to {output_path}")

