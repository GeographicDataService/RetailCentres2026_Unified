import polars as pl

def add_cells_manually(df: pl.DataFrame) -> pl.DataFrame:
    """
    Adds specific H3 cells manually to the filtered DataFrame.

    These cells represent manually defined retail clusters that should be
    included even if they don't meet the threshold criteria.
    """
    manual_h3_groups = [
    ["8b1951028516fff", "8b1951028510fff", "8b1951028511fff", "8b195102851cfff", "8b19510285a5fff", 
     "8b1951028512fff", "8b1951028513fff"],
    ["8b19510749a3fff", "8b195115a292fff", "8b195115a293fff"],
    ["8b1951070913fff", "8b1951070911fff"],
    ["8b19510442e1fff", "8b19510442e5fff"],
    ["8b1951045c18fff", "8b1951045c1dfff", "8b1951045c0afff", "8b1951045c0bfff", "8b1951045c09fff"],
    ["8b1951058d0cfff", "8b1951058d2bfff"],
    ["8b195111d909fff", "8b195111d956fff", "8b195111d952fff", "8b195111d950fff", "8b195111d953fff"],
    ["8b19510558e0fff", "8b19510558e1fff", "8b1951055852fff", "8b1951055850fff"],
    ["8b1951046b5dfff", "8b1951046b4efff", "8b1951046a61fff", "8b1951046a6efff", "8b1951046a6cfff", 
     "8b1951046a68fff"],
    ["8b1951101526fff", "8b1951101c99fff", "8b1951101c8afff", "8b1951101c9dfff"],
    ["8b195112335cfff", "8b1951123351fff"],
    ["8b195123429bfff", "8b1951234298fff", "8b195123429efff", "8b1951234291fff", "8b1951234290fff", 
     "8b1951234296fff"],
    ["8b194248b608fff", "8b194248b60efff", "8b194248b6e2fff", "8b194248b6f5fff", "8b194248b6d3fff", 
     "8b194248b6d0fff", "8b194248b6d4fff"],
    ["8b1942c59d2efff", "8b1942c59d23fff", "8b1942c5d780fff", "8b1942c5d781fff", "8b1942c5d78cfff", 
     "8b1942c5d78dfff", "8b1942c5d7abfff", "8b1942c5d7a9fff", "8b1942c5d7a8fff", "8b1942c5d7acfff", "8b1942c5d713fff"],
    ["8b19583922a1fff", "8b19583922acfff", "8b1958392213fff", "8b1958392211fff", "8b195839221efff", 
     "8b195839221cfff", "8b1958392203fff", "8b1958392201fff", "8b19583922a9fff", "8b195839221afff", "8b1958392218fff", 
     "8b19583922f4fff", "8b1958392219fff"],
    ["8b194a722b4bfff", "8b194a722b48fff"],
    ["8b1959024113fff", "8b19590241adfff", "8b1959024021fff", "8b195902402cfff", "8b1959024156fff", 
     "8b1959024152fff", "8b1959024025fff"],
    ["8b195d09ad83fff", "8b195d09ad8dfff", "8b195d09ac36fff", "8b195d09ac33fff", "8b195d09ac28fff"],
    ["8b195d5592d3fff", "8b195d5592d0fff", "8b195d5592d6fff", "8b195d55928bfff"],
    ["8b19583926e1fff", "8b1958392652fff", "8b19583926eefff"],
    ["8b18746ea369fff", "8b18746ebcb4fff", "8b18746ea36bfff", "8b18746ebcb6fff"],
    ["8b195c341c9cfff", "8b195c341c83fff"],
    ["8b195a118658fff", "8b195a11874efff", "8b195a118748fff"],
    ["8b19550d6014fff", "8b19550d6016fff"],
    ["8b1951b62a8bfff", "8b1951b62a89fff"],
    ["8b1951ab0899fff", "8b1951ab088afff", "8b1951ab089dfff", "8b1951ab088efff", "8b1951ab08d4fff", 
     "8b1951ab08f2fff"],
    ["8b1951a8a242fff", "8b1951a8a25cfff", "8b1951a8a258fff", "8b1951a8a25bfff", "8b1951a8b5b5fff", 
     "8b1951a8b5b4fff"],
    ["8b195805d251fff"],
    ["8b194ad16d9afff", "8b194ad16cb4fff", "8b194ad16d9bfff", "8b194ad16cb0fff", "8b194ad16cb5fff", 
     "8b194ad16ca6fff", "8b194ad16cb1fff", "8b194ad16ca2fff", "8b194ad16ca0fff"],
    ["8b1959aa0d94fff", "8b1959aa0db3fff", "8b1959aa0db1fff"],
    ["8b19512b00b3fff", "8b19512b00b0fff", "8b19512b00b6fff", "8b19512b0569fff", "8b19512b00b4fff", 
     "8b19512b019bfff", "8b19512b0198fff", "8b19512b019dfff"],
    ["8b1959aa2a01fff", "8b1959aa2a2afff", "8b1959aa2a0cfff"],
    ["8b1972761089fff", "8b19727610d4fff"],
    ["8b197276174afff", "8b1972761748fff"],
    ["8b1972765384fff", "8b1972765385fff", "8b197276538cfff", "8b19727653aafff", "8b19727653a8fff", 
     "8b19727653a9fff"],
    ["8b1951a8a2c3fff", "8b1951a8a2c0fff", "8b1951a8a2c4fff", "8b1951a8a2e2fff", "8b1951a8a2e4fff", 
     "8b1951a8a2e0fff", "8b1951a8a2e3fff", "8b1951a8a2c5fff", "8b1951a8a2c1fff", "8b1951a8a2ccfff", "8b1951a8a2eafff", 
     "8b1951a8a2eefff", "8b1951a8a2e1fff", "8b1951a8a2e5fff", "8b1951a8a256fff", "8b1951a8a252fff", "8b1951a8a2ecfff", 
     "8b1951a8a2e8fff", "8b1951a8a2ebfff", "8b1951a8a2cdfff", "8b1951a8b5b6fff", "8b1951a8a2e9fff", "8b1951a8a2edfff", 
     "8b1951a8a253fff", "8b1951a8a250fff", "8b1951a8a251fff", "8b1951a8a25efff", "8b1951a8a25afff", "8b1951a8b5b4fff", 
     "8b1951a8b5b5fff", "8b1951a8a25bfff", "8b1951a8a258fff", "8b1951a8a25cfff", "8b1951a8a242fff"]
]

    # Flatten the list of lists into a single list of H3 cells
    manual_h3s = [h3 for sublist in manual_h3_groups for h3 in sublist]

    print(f"Adding {len(manual_h3s)} manually defined H3 cells.")

    # Create a DataFrame with just the manually added cells
    manual_cells_df = pl.DataFrame(
        {
            "h3_11": manual_h3s,
            "manually_added": [True] * len(manual_h3s),
        }
    )

    # # Add manually_added column to existing df (False by default)
    # df = df.with_columns(pl.lit(False).alias("manually_added"))

    # Join and coalesce to preserve existing data
    df = df.join(manual_cells_df, on="h3_11", how="full", coalesce=True)

    # Fill any remaining nulls in specific fields
    df = df.with_columns(
        [
            pl.col("foursquare_count").fill_null(0),
            pl.col("overture_count").fill_null(0),
            pl.col("retail_landuse").fill_null(False),
            pl.col("manually_added").fill_null(False),
        ]
    )

    # Report stats
    n_new = df.filter(pl.col("manually_added") & ~pl.col("h3_11").is_in(df["h3_11"])).height
    n_existing = df.filter(pl.col("manually_added") & pl.col("h3_11").is_in(df["h3_11"])).height

    print(f"Already in dataframe: {n_existing}")
    print(f"New cells added: {n_new}")

    return df


def flag_manually_removed_cells(df: pl.DataFrame) -> pl.DataFrame:
    # Flattened list of all manually flagged cells
    manually_removed_cells = [
        # Dereham Rd, Norwich
        "8b194105a56bfff", "8b194105a540fff", "8b194105a192fff", "8b194105a56cfff",
        "8b194105a568fff", "8b194105a56efff", "8b194105a560fff", "8b194105a56afff",
        "8b194105a563fff", "8b194105a54cfff", "8b194105a545fff", "8b194105a562fff",
        "8b194105a541fff", "8b194105a54efff", "8b194105a543fff", "8b194105a542fff",
        "8b194105a56dfff",
        # London Rd, Brighton
        "8b194a7252ecfff", "8b194a7252eefff",
        # Islington and Highbury in London
        "8b195da6bb53fff", "8b195da6bb51fff", "8b195da6bb42fff"
    ]

    df = df.with_columns([
        pl.col("h3_11").is_in(manually_removed_cells).alias("manually_removed")
    ])

    return df
