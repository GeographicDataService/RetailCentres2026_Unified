import pandas as pd
import polars as pl
import re
import ast

#load the overture data
overture = pd.read_parquet('data/input_files/poi_uk_overture.parquet')
overture['main_category'] = overture['main_category'].str.replace('criminal_deense_law', 'criminal_defense_law', regex=False)
overture['main_category'] = overture['main_category'].str.replace('cafetaria', 'cafeteria', regex=False)

#load the cat data

cat_data = pd.read_csv('data/input_files/overture_categories.csv', sep=';')
#fix spelling
#if category criminal_deense_law, then change to criminal_defense_law

overture = overture.merge(cat_data, left_on="main_category", right_on="Category code", how="left")
overture = overture.where(pd.notnull(overture), None)
#rename ' Overture Taxonomy' to 'category_hierarchy'
overture = overture.rename(columns={' Overture Taxonomy': 'category_hierarchy'})
#lon to lng
overture = overture.rename(columns={'long': 'lng'})

#must a better way, look in github for other people loading this
def clean_and_eval(val):
    if pd.isnull(val):  # Handle NaN values
        return []
    try:
        # Remove leading/trailing spaces
        val = val.strip()

        # Add quotes around unquoted elements, if any
        # This regex ensures that words without quotes are properly quoted
        val = re.sub(r'(\b\w+\b)', r"'\1'", val)

        # Safely evaluate the cleaned string
        val = ast.literal_eval(val)
        return val
    except (ValueError, SyntaxError) as e:
        return []
overture['category_hierarchy'] = overture['category_hierarchy'].apply(clean_and_eval)
overture['level1_category_name'] = overture['category_hierarchy'].apply(lambda x: x[0] if x else None)
overture['level2_category_name'] = overture['category_hierarchy'].apply(lambda x: x[1] if len(x) > 1 else None)
overture['level3_category_name'] = overture['category_hierarchy'].apply(lambda x: x[2] if len(x) > 2 else None)

overture = pl.DataFrame(overture)
overture.write_parquet('data/input_files/poi_uk_overture_proc.parquet')