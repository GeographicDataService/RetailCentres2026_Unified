"""Compare names between old and new retail centres that spatially intersect."""

import geopandas as gpd
import pandas as pd
import os

OLD_PATH = "Retail_Boundaries_UK.gpkg"  # Naming/ copy, identical to Boundaries/data/old_retail_centres/
NEW_PATH = "exports/rc2025_named.gpkg"
EXPORTS_DIR = "exports"

print("Loading old retail centres...")
old = gpd.read_file(OLD_PATH)[["RC_ID", "RC_Name", "Classification", "geometry"]]
old = old.rename(columns={"RC_ID": "Old_RC_ID", "RC_Name": "Old_Name", "Classification": "Old_Classification"})
print(f"  {len(old)} old centres")

print("Loading new retail centres...")
new = gpd.read_file(NEW_PATH)[["RC_ID", "RC_Name", "Classification", "geometry"]]
new = new.rename(columns={"RC_ID": "New_RC_ID", "RC_Name": "New_Name", "Classification": "New_Classification"})
print(f"  {len(new)} new centres")

# Ensure same CRS
assert old.crs == new.crs, f"CRS mismatch: {old.crs} vs {new.crs}"

print("Finding spatial intersections...")
joined = gpd.sjoin(new, old, how="inner", predicate="intersects")

# For each pair, compute intersection area / union area (IoU) to gauge match quality
print("Computing overlap areas...")
rows = []
for _, row in joined.iterrows():
    new_geom = row.geometry
    old_idx = row["index_right"]
    old_geom = old.loc[old_idx, "geometry"]

    intersection_area = new_geom.intersection(old_geom).area
    union_area = new_geom.union(old_geom).area
    iou = intersection_area / union_area if union_area > 0 else 0

    rows.append({
        "Old_Name": row["Old_Name"],
        "New_Name": row["New_Name"],
        "Old_RC_ID": row["Old_RC_ID"],
        "New_RC_ID": row["New_RC_ID"],
        "Old_Classification": row["Old_Classification"],
        "New_Classification": row["New_Classification"],
        "IoU": round(iou, 3),
        "Intersection_Area_km2": round(intersection_area / 1e6, 4),
    })

comparison = pd.DataFrame(rows)
comparison = comparison.sort_values("IoU", ascending=False)

# Flag where names differ (treat "Northern Ireland" vs "NI" as equivalent)
def normalise_ni(name):
    return str(name).replace("Northern Ireland", "NI") if pd.notna(name) else name

comparison["Name_Match"] = comparison["New_Name"].apply(normalise_ni) == comparison["Old_Name"].apply(normalise_ni)

# Summary stats
print(f"\n=== Comparison Summary ===")
print(f"  Total intersecting pairs: {len(comparison)}")
print(f"  Exact name matches: {comparison['Name_Match'].sum()}")
print(f"  Name differences: {(~comparison['Name_Match']).sum()}")
print(f"  Mean IoU: {comparison['IoU'].mean():.3f}")

# Show high-overlap pairs where names differ
diff = comparison[(~comparison["Name_Match"]) & (comparison["IoU"] > 0.3)].head(20)
print(f"\n=== Top name differences (IoU > 0.3) ===")
for _, r in diff.iterrows():
    print(f"  IoU={r['IoU']:.2f}  OLD: {r['Old_Name']}")
    print(f"          NEW: {r['New_Name']}")
    print()

# Save full comparison CSV
out_path = os.path.join(EXPORTS_DIR, "name_comparison_old_vs_new.csv")
comparison.to_csv(out_path, index=False)
print(f"Saved: {out_path}")

# Build a GeoDataFrame of new centres with the best-matching old name attached
# For each new centre, pick the old centre with the highest IoU
best_match = comparison.sort_values("IoU", ascending=False).drop_duplicates(subset="New_RC_ID", keep="first")
best_match = best_match[["New_RC_ID", "Old_RC_ID", "Old_Name", "Old_Classification", "IoU", "Name_Match"]]

new_full = gpd.read_file(NEW_PATH)
new_with_old = new_full.merge(best_match, left_on="RC_ID", right_on="New_RC_ID", how="left")
new_with_old = new_with_old.drop(columns=["New_RC_ID"])

new_with_old = new_with_old.to_crs("EPSG:4326")
geo_out = os.path.join(EXPORTS_DIR, "rc2025_named_with_old_names.gpkg")
new_with_old.to_file(geo_out, driver="GPKG")
print(f"Saved: {geo_out}")

parquet_out = os.path.join(EXPORTS_DIR, "rc2025_named_with_old_names.parquet")
new_with_old.to_parquet(parquet_out)
print(f"Saved: {parquet_out}")

# Build detailed diffs for high-IoU pairs
import re

high = comparison[comparison["IoU"] > 0.7].copy()

def categorise(row):
    if row["Name_Match"]: return "Exact match"
    old, new = str(row["Old_Name"]), str(row["New_Name"])
    old_base = re.sub(r"\s*-\s*\d+$", "", old).strip()
    new_base = re.sub(r"\s*-\s*\d+$", "", new).strip()
    if old_base == new_base: return "Dedup suffix difference"
    old_parts = [p.strip() for p in old.replace("(", ";").replace(")", "").split(";") if p.strip()]
    new_parts = [p.strip() for p in new.replace("(", ";").replace(")", "").split(";") if p.strip()]
    if old_base.replace(".", "").replace(",", "") == new_base.replace(".", "").replace(",", ""): return "Punctuation difference"
    ob, nb = old_base, new_base
    for a, f in [("Rd ", "Road "), ("Ln ", "Lane "), ("Dr ", "Drive "), ("Ave ", "Avenue "), ("Pl ", "Place "), ("Ct ", "Court ")]:
        ob, nb = ob.replace(a, f), nb.replace(a, f)
    if ob == nb: return "Street abbreviation difference"
    same_tail = len(old_parts) >= 3 and len(new_parts) >= 3 and old_parts[-2:] == new_parts[-2:]
    if len(old_parts) != len(new_parts) and same_tail: return "Extra/missing name component"
    if same_tail:
        ol, nl = old_parts[:-2], new_parts[:-2]
        if len(ol) == len(nl):
            diffs = [i for i in range(len(ol)) if ol[i] != nl[i]]
            if len(diffs) == 1: return "Different street name" if diffs[0] == 0 else "Different neighbourhood"
            elif len(diffs) > 1: return "Different street + neighbourhood"
        return "Different local name (same LA)"
    if len(old_parts) >= 2 and len(new_parts) >= 2 and old_parts[-1] == new_parts[-1] and old_parts[-2] != new_parts[-2]: return "Different LA boundary"
    if "Retail Park" in old and "Retail Park" in new: return "Different retail park name"
    if "Retail Park" in new and "Retail Park" not in old: return "Reclassified as retail park"
    if "Shopping" in old or "Shopping" in new: return "Shopping centre naming change"
    return "Other"

high["Mismatch_Reason"] = high.apply(categorise, axis=1)
class_order = ["Regional Centre", "Major Town Centre", "Town Centre", "Market Town",
               "District Centre", "Local Centre", "Small Local Centre",
               "Large Retail Park", "Small Retail Park",
               "Large Shopping Centre", "Small Shopping Centre"]
high["Class_Order"] = high["New_Classification"].map({c: i for i, c in enumerate(class_order)}).fillna(99)
high = high.sort_values(["Class_Order", "IoU"], ascending=[True, False])

diffs = high[~high["Name_Match"]].drop(columns=["Class_Order"])
out = diffs[["New_Name", "New_RC_ID", "New_Classification",
             "Old_Name", "Old_RC_ID", "Old_Classification",
             "IoU", "Name_Match", "Mismatch_Reason"]]
same_class = out[out["New_Classification"] == out["Old_Classification"]]
diff_class = out[out["New_Classification"] != out["Old_Classification"]]

same_class_csv = os.path.join(EXPORTS_DIR, "name_comparison_detailed_same_class.csv")
same_class.to_csv(same_class_csv, index=False)
print(f"Saved: {same_class_csv} ({len(same_class)} diffs, same classification)")

diff_class_csv = os.path.join(EXPORTS_DIR, "name_comparison_detailed_diff_class.csv")
diff_class.to_csv(diff_class_csv, index=False)
print(f"Saved: {diff_class_csv} ({len(diff_class)} diffs, different classification)")

# GeoParquet of diffs
out2 = out.copy()
out2["New_RC_ID"] = out2["New_RC_ID"].astype(str)
new_full["RC_ID"] = new_full["RC_ID"].astype(str)
merged = new_full.merge(out2, left_on="RC_ID", right_on="New_RC_ID", how="inner").drop(columns=["New_RC_ID"])
detail_parquet = os.path.join(EXPORTS_DIR, "name_comparison_detailed.parquet")
merged.to_parquet(detail_parquet)
print(f"Saved: {detail_parquet} ({len(merged)} diffs)")
