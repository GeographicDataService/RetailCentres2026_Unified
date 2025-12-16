"""
Test the deterministic changes by running the new version and comparing to git.
"""
import polars as pl

# Input data
INPUT_FILE = "data/input_files/uk_foursquare_cc_nov_iceberg.parquet"

print("="*80)
print("TESTING DETERMINISTIC FILTER CHANGES")
print("="*80)

print("\nRunning NEW version (with deterministic tie-breakers + reordered filters)...")
print("-"*80)

from src.retail.foursquare_qualityfilter import filter_foursquare_quality

# Load data
df = pl.read_parquet(INPUT_FILE)
print(f"Loaded {len(df):,} POIs")

# Run filter with ID tracking enabled
filtered = filter_foursquare_quality(
    df,
    save_filter_ids=True,
    filter_ids_path="data/POI_files/quality_filter_ids_NEW.parquet",
    # Disable saving removed files to speed up
    save_defunct_removed=False,
    save_duplicates_removed=False,
    save_business_changes_removed=False,
    save_foreign_addresses_removed=False,
    save_postcode_mismatch_removed=False,
    save_outside=False
)

print("\n" + "="*80)
print("COMPARING NEW VS GIT VERSION")
print("="*80)

# Load filter IDs
new_removed = pl.read_parquet("data/POI_files/quality_filter_ids_NEW.parquet")
git_removed = pl.read_parquet("data/POI_files/quality_filter_ids_GIT.parquet")

print(f"\nNew version: {len(new_removed):,} filter instances")
print(f"Git version: {len(git_removed):,} filter instances")

# Get unique IDs
new_ids = set(new_removed.select("fsq_place_id").unique().to_series())
git_ids = set(git_removed.select("fsq_place_id").unique().to_series())

# Find differences
only_in_new = new_ids - git_ids
only_in_git = git_ids - new_ids

print(f"\nTotal unique filtered POIs:")
print(f"  New version: {len(new_ids):,}")
print(f"  Git version: {len(git_ids):,}")
print(f"  Difference:  {abs(len(new_ids) - len(git_ids)):,}")

print(f"\nPOIs filtered only by NEW version: {len(only_in_new):,}")
print(f"POIs filtered only by GIT version: {len(only_in_git):,}")
print(f"Net difference:                    {len(only_in_new) - len(only_in_git):,}")

# Breakdown by filter type
print("\n" + "-"*80)
print("FILTER BREAKDOWN")
print("-"*80)

new_breakdown = new_removed.group_by("filter_type").agg(
    pl.col("fsq_place_id").n_unique().alias("count")
).sort("filter_type")

git_breakdown = git_removed.group_by("filter_type").agg(
    pl.col("fsq_place_id").n_unique().alias("count")
).sort("filter_type")

# Merge for comparison
comparison = new_breakdown.join(
    git_breakdown,
    on="filter_type",
    how="full",
    suffix="_git"
).with_columns([
    pl.col("count").fill_null(0),
    pl.col("count_git").fill_null(0)
]).with_columns(
    (pl.col("count") - pl.col("count_git")).alias("diff")
).sort("filter_type")

print("\n| Filter Type         | New       | Git       | Diff    |")
print("|---------------------|-----------|-----------|---------|")
for row in comparison.iter_rows(named=True):
    print(f"| {row['filter_type']:<19} | {row['count']:>9,} | {row['count_git']:>9,} | {row['diff']:>+7,} |")

if abs(len(new_ids) - len(git_ids)) <= 5:
    print("\n" + "="*80)
    print("✅ SUCCESS! Differences are minimal (≤5 POIs)")
    print("="*80)
elif abs(len(new_ids) - len(git_ids)) <= 20:
    print("\n" + "="*80)
    print("⚠️  IMPROVED! Differences reduced to ≤20 POIs (was 26)")
    print("="*80)
else:
    print("\n" + "="*80)
    print("❌ Still significant differences (>20 POIs)")
    print("="*80)

print("\n" + "="*80)
print("DONE")
print("="*80)
