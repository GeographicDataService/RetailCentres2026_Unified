"""Compare old (R-pipeline) and new (Python-pipeline) retail centres for paper metrics.

Outputs (under exports/ and exports/figures/):
  - comparison_counts.csv          headline counts + areas, by classification
  - comparison_by_country.csv      counts/areas/newly-found/disappeared by country
  - comparison_by_region.csv       counts/areas/newly-found/disappeared by region
  - comparison_match_summary.csv   matched/unmatched under three rules, both directions
  - new_centres_flags.parquet      per-new-centre overlapping flags + best-old-match info
  - old_centres_flags.csv          per-old-centre symmetric info
  - new_centres_flag_breakdown.csv cross-tab of flag combinations
  - area_change_distribution.csv   area-ratio distribution for 1-1 matches
  - classification_migration.csv   classification cross-tab for 1-1 matches
  - figures/map_newly_found.png
  - figures/map_disappeared.png
  - figures/map_growth_by_region.png
  - figures/map_classification_changes.png
"""

import os
import warnings

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OLD_PATH = "Retail_Boundaries_UK.gpkg"
NEW_PATH = "exports/rc2025_named.parquet"
LAD_PATH = "data/LAD_Dec2024_UK.gpkg"
EXPORTS_DIR = "exports"
FIG_DIR = os.path.join(EXPORTS_DIR, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

# Region name normalisation: old uses "Northern Ireland", new uses "NI".
REGION_RENAME = {"Northern Ireland": "NI"}

CLASS_ORDER = [
    "Regional Centre",
    "Major Town Centre",
    "Town Centre",
    "Market Town",
    "District Centre",
    "Local Centre",
    "Small Local Centre",
    "Large Retail Park",
    "Small Retail Park",
    "Regional Shopping Centre",
    "Large Outlet Shopping Centre",
    "Large Shopping Centre",
    "Small Shopping Centre",
]


def hr(title):
    print(f"\n=== {title} ===")


# ---------------------------------------------------------------------------
# 1. Load
# ---------------------------------------------------------------------------
print("Loading old centres...")
old = gpd.read_file(OLD_PATH)
print(f"  {len(old)} old centres, crs={old.crs}")

print("Loading new centres...")
new = gpd.read_parquet(NEW_PATH)
print(f"  {len(new)} new centres, crs={new.crs}")

assert old.crs == new.crs, f"CRS mismatch: {old.crs} vs {new.crs}"

old["area_km2"] = old.geometry.area / 1e6
new["area_km2"] = new.geometry.area / 1e6

old["Region"] = old["Region_NM"].replace(REGION_RENAME)
new["Region"] = new["RegionName"].replace(REGION_RENAME)

# Country: old has it; new has RegionName but not Country. Derive from region.
ENG_REGIONS = {
    "London", "South East", "South West", "East of England",
    "East Midlands", "West Midlands", "North East", "North West",
    "Yorkshire and The Humber",
}
def region_to_country(r):
    if r in ENG_REGIONS:
        return "England"
    if r == "Wales":
        return "Wales"
    if r == "Scotland":
        return "Scotland"
    if r == "NI":
        return "Northern Ireland"
    return "Unknown"

new["Country"] = new["Region"].apply(region_to_country)
old["Country"] = old["Country"]  # already present


# ---------------------------------------------------------------------------
# 2. Headline counts
# ---------------------------------------------------------------------------
hr("Headline counts")
n_old, n_new = len(old), len(new)
print(f"Old: {n_old}    New: {n_new}    Delta: {n_new - n_old:+d} ({(n_new/n_old - 1)*100:+.1f}%)")
print(f"Old total area: {old['area_km2'].sum():,.1f} km²    "
      f"New total area: {new['area_km2'].sum():,.1f} km²")
print(f"Old mean area:  {old['area_km2'].mean():.3f} km²    "
      f"New mean area:  {new['area_km2'].mean():.3f} km²")
print(f"Old median area: {old['area_km2'].median():.3f} km²   "
      f"New median area: {new['area_km2'].median():.3f} km²")

class_counts = pd.DataFrame({
    "Old": old["Classification"].value_counts(),
    "New": new["Classification"].value_counts(),
}).reindex(CLASS_ORDER).fillna(0).astype(int)
class_counts["Delta"] = class_counts["New"] - class_counts["Old"]
class_counts["Pct_Change"] = np.where(
    class_counts["Old"] > 0,
    (class_counts["Delta"] / class_counts["Old"] * 100).round(1),
    np.nan,
)
print("\nBy classification:")
print(class_counts.to_string())

class_counts.to_csv(os.path.join(EXPORTS_DIR, "comparison_counts.csv"))

# ---------------------------------------------------------------------------
# 3. Spatial join + IoU
# ---------------------------------------------------------------------------
hr("Spatial join")
old_join = old[["RC_ID", "RC_Name", "Classification", "Country", "Region", "area_km2", "geometry"]].rename(
    columns={
        "RC_ID": "Old_RC_ID",
        "RC_Name": "Old_Name",
        "Classification": "Old_Classification",
        "Country": "Old_Country",
        "Region": "Old_Region",
        "area_km2": "Old_area_km2",
    }
)
new_join = new[["RC_ID", "RC_Name", "Classification", "centre_type", "was_split",
                "Country", "Region", "area_km2", "geometry"]].rename(
    columns={
        "RC_ID": "New_RC_ID",
        "RC_Name": "New_Name",
        "Classification": "New_Classification",
        "Country": "New_Country",
        "Region": "New_Region",
        "area_km2": "New_area_km2",
    }
)

joined = gpd.sjoin(new_join, old_join, how="inner", predicate="intersects")
print(f"  {len(joined)} (new, old) intersecting pairs")

print("  computing IoU per pair...")
old_geom_lookup = old_join.geometry
inter_areas, union_areas = [], []
for _, row in joined.iterrows():
    g_new = row.geometry
    g_old = old_geom_lookup.iloc[row["index_right"]]
    inter = g_new.intersection(g_old).area
    union = g_new.union(g_old).area
    inter_areas.append(inter)
    union_areas.append(union)

joined["intersection_m2"] = inter_areas
joined["union_m2"] = union_areas
joined["iou"] = joined["intersection_m2"] / joined["union_m2"].replace(0, np.nan)
joined["new_share"] = joined["intersection_m2"] / (joined["New_area_km2"] * 1e6)
joined["old_share"] = joined["intersection_m2"] / (joined["Old_area_km2"] * 1e6)

# Strip geometry — we don't need it for downstream tables
pairs = pd.DataFrame(joined.drop(columns=["geometry", "index_right"]))


# ---------------------------------------------------------------------------
# 3b. Multi-rule match summary
# ---------------------------------------------------------------------------
# Per-new flags
agg_new = pairs.groupby("New_RC_ID").agg(
    n_old_overlapping=("Old_RC_ID", "nunique"),
    best_old_iou=("iou", "max"),
).reset_index()
new_flags = new[["RC_ID", "RC_Name", "Classification", "centre_type", "was_split",
                 "Parent_ID", "Country", "Region", "area_km2"]].copy()
new_flags = new_flags.merge(agg_new, left_on="RC_ID", right_on="New_RC_ID", how="left").drop(columns=["New_RC_ID"])
new_flags["n_old_overlapping"] = new_flags["n_old_overlapping"].fillna(0).astype(int)
new_flags["best_old_iou"] = new_flags["best_old_iou"].fillna(0)

# best old match RC_ID per new
best_old = pairs.sort_values("iou", ascending=False).drop_duplicates("New_RC_ID", keep="first")[
    ["New_RC_ID", "Old_RC_ID", "Old_Classification", "Old_Name", "iou"]
].rename(columns={"Old_RC_ID": "best_old_RC_ID",
                  "Old_Classification": "best_old_Classification",
                  "Old_Name": "best_old_Name"})
new_flags = new_flags.merge(best_old.drop(columns=["iou"]), left_on="RC_ID", right_on="New_RC_ID", how="left").drop(columns=["New_RC_ID"])

# Centroid-in-old check
print("  centroid-in-old test...")
new_centroids = new_flags.merge(new[["RC_ID", "geometry"]], on="RC_ID", how="left")
new_centroids = gpd.GeoDataFrame(new_centroids, geometry="geometry", crs=new.crs)
new_centroids["centroid"] = new_centroids.geometry.centroid
centroid_gdf = gpd.GeoDataFrame(
    new_centroids[["RC_ID"]], geometry=new_centroids["centroid"], crs=new.crs,
)
centroid_in_old = gpd.sjoin(centroid_gdf, old_join[["geometry"]], how="left", predicate="within")
centroid_match = centroid_in_old.groupby("RC_ID")["index_right"].apply(lambda s: s.notna().any()).reset_index()
centroid_match.columns = ["RC_ID", "has_centroid_in_old"]
new_flags = new_flags.merge(centroid_match, on="RC_ID", how="left")
new_flags["has_centroid_in_old"] = new_flags["has_centroid_in_old"].fillna(False)

new_flags["has_old_intersect"] = new_flags["n_old_overlapping"] > 0
new_flags["has_old_iou01"] = new_flags["best_old_iou"] >= 0.1
new_flags["is_sub_area"] = new_flags["was_split"] == True
new_flags["is_retail_park"] = new_flags["centre_type"] == "retail_park"
new_flags["is_shopping_centre"] = new_flags["Classification"].isin([
    "Large Shopping Centre", "Small Shopping Centre",
    "Regional Shopping Centre", "Large Outlet Shopping Centre",
])

# Per-old flags
agg_old = pairs.groupby("Old_RC_ID").agg(
    n_new_overlapping=("New_RC_ID", "nunique"),
    best_new_iou=("iou", "max"),
).reset_index()
old_flags = old[["RC_ID", "RC_Name", "Classification", "Country", "Region", "area_km2"]].copy()
old_flags = old_flags.merge(agg_old, left_on="RC_ID", right_on="Old_RC_ID", how="left").drop(columns=["Old_RC_ID"])
old_flags["n_new_overlapping"] = old_flags["n_new_overlapping"].fillna(0).astype(int)
old_flags["best_new_iou"] = old_flags["best_new_iou"].fillna(0)
old_flags["has_new_intersect"] = old_flags["n_new_overlapping"] > 0
old_flags["has_new_iou01"] = old_flags["best_new_iou"] >= 0.1

# Centroid-of-old in any new
old_centroid_gdf = gpd.GeoDataFrame(
    old[["RC_ID"]], geometry=old.geometry.centroid, crs=old.crs,
)
old_in_new = gpd.sjoin(old_centroid_gdf, new[["geometry"]], how="left", predicate="within")
old_centroid_match = old_in_new.groupby("RC_ID")["index_right"].apply(lambda s: s.notna().any()).reset_index()
old_centroid_match.columns = ["RC_ID", "has_centroid_in_new"]
old_flags = old_flags.merge(old_centroid_match, on="RC_ID", how="left")
old_flags["has_centroid_in_new"] = old_flags["has_centroid_in_new"].fillna(False)

new_flags.to_parquet(os.path.join(EXPORTS_DIR, "new_centres_flags.parquet"))
old_flags.to_csv(os.path.join(EXPORTS_DIR, "old_centres_flags.csv"), index=False)
print(f"  saved new_centres_flags.parquet ({len(new_flags)} rows)")
print(f"  saved old_centres_flags.csv ({len(old_flags)} rows)")

# Match summary table
hr("Match summary (multiple rules)")
match_rows = []
for label, col in [("any_intersect", "has_old_intersect"),
                   ("iou >= 0.1", "has_old_iou01"),
                   ("centroid_in_old", "has_centroid_in_old")]:
    matched = int(new_flags[col].sum())
    match_rows.append({
        "direction": "new -> old",
        "rule": label,
        "matched": matched,
        "unmatched": len(new_flags) - matched,
        "total": len(new_flags),
    })
for label, col in [("any_intersect", "has_new_intersect"),
                   ("iou >= 0.1", "has_new_iou01"),
                   ("centroid_in_new", "has_centroid_in_new")]:
    matched = int(old_flags[col].sum())
    match_rows.append({
        "direction": "old -> new",
        "rule": label,
        "matched": matched,
        "unmatched": len(old_flags) - matched,
        "total": len(old_flags),
    })
match_summary = pd.DataFrame(match_rows)
print(match_summary.to_string(index=False))
match_summary.to_csv(os.path.join(EXPORTS_DIR, "comparison_match_summary.csv"), index=False)


# ---------------------------------------------------------------------------
# 4. Flag-combination breakdown
# ---------------------------------------------------------------------------
hr("Growth decomposition (per-new-centre flags)")
breakdown = new_flags.groupby(
    ["is_sub_area", "is_retail_park", "is_shopping_centre", "has_old_intersect"]
).size().reset_index(name="count").sort_values("count", ascending=False)
print(breakdown.to_string(index=False))
breakdown.to_csv(os.path.join(EXPORTS_DIR, "new_centres_flag_breakdown.csv"), index=False)

print("\nKey numbers:")
print(f"  Sub-areas (was_split):                     {new_flags['is_sub_area'].sum()}")
print(f"  Retail parks:                              {new_flags['is_retail_park'].sum()}")
print(f"  Retail parks with NO old intersect:        "
      f"{((new_flags['is_retail_park']) & (~new_flags['has_old_intersect'])).sum()}")
print(f"  Retail parks with old intersect:           "
      f"{((new_flags['is_retail_park']) & (new_flags['has_old_intersect'])).sum()}")
print(f"  Shopping centres:                          {new_flags['is_shopping_centre'].sum()}")
print(f"  Newly found (any_intersect rule):          {(~new_flags['has_old_intersect']).sum()}")
print(f"  Newly found (iou>=0.1 rule):               {(~new_flags['has_old_iou01']).sum()}")
print(f"  Newly found (centroid_in_old rule):        {(~new_flags['has_centroid_in_old']).sum()}")
print(f"  New polygons that overlap >1 old (merges): {(new_flags['n_old_overlapping'] > 1).sum()}")
print(f"  Old polygons that overlap >1 new (splits): {(old_flags['n_new_overlapping'] > 1).sum()}")
print(f"  Disappeared old (any_intersect rule):      {(~old_flags['has_new_intersect']).sum()}")


# ---------------------------------------------------------------------------
# 5. Area changes (1-1 matches only)
# ---------------------------------------------------------------------------
hr("Area changes (1-1 matches, IoU >= 0.5)")
one_to_one = pairs.merge(
    new_flags[["RC_ID", "n_old_overlapping"]].rename(columns={"RC_ID": "New_RC_ID"}),
    on="New_RC_ID",
).merge(
    old_flags[["RC_ID", "n_new_overlapping"]].rename(columns={"RC_ID": "Old_RC_ID"}),
    on="Old_RC_ID",
)
one_to_one = one_to_one[
    (one_to_one["n_old_overlapping"] == 1)
    & (one_to_one["n_new_overlapping"] == 1)
    & (one_to_one["iou"] >= 0.5)
].copy()
one_to_one["area_ratio"] = one_to_one["New_area_km2"] / one_to_one["Old_area_km2"]
print(f"  {len(one_to_one)} 1-1 matches with IoU >= 0.5")
print(f"  Area ratio (new/old) percentiles:")
for p in [5, 25, 50, 75, 95]:
    print(f"    p{p}: {one_to_one['area_ratio'].quantile(p/100):.2f}")
print(f"  mean: {one_to_one['area_ratio'].mean():.2f}    "
      f"% > 1 (grew): {(one_to_one['area_ratio'] > 1).mean()*100:.1f}%")

area_dist = one_to_one[["New_RC_ID", "Old_RC_ID", "Old_Classification", "New_Classification",
                         "Old_area_km2", "New_area_km2", "iou", "area_ratio"]]
area_dist.to_csv(os.path.join(EXPORTS_DIR, "area_change_distribution.csv"), index=False)


# ---------------------------------------------------------------------------
# 6. Classification migration
# ---------------------------------------------------------------------------
hr("Classification migration (1-1 matches, IoU >= 0.5)")
mig = pd.crosstab(one_to_one["Old_Classification"], one_to_one["New_Classification"])
mig = mig.reindex(index=[c for c in CLASS_ORDER if c in mig.index],
                   columns=[c for c in CLASS_ORDER if c in mig.columns]).fillna(0).astype(int)
print(mig.to_string())
mig.to_csv(os.path.join(EXPORTS_DIR, "classification_migration.csv"))

# Top off-diagonal cells
mig_long = mig.stack().reset_index()
mig_long.columns = ["Old_Classification", "New_Classification", "count"]
off_diag = mig_long[mig_long["Old_Classification"] != mig_long["New_Classification"]]
print("\nTop classification changes:")
print(off_diag.sort_values("count", ascending=False).head(10).to_string(index=False))


# ---------------------------------------------------------------------------
# 7. Geographic breakdown
# ---------------------------------------------------------------------------
def geo_breakdown(level):
    old_g = old.groupby(level).agg(
        old_count=("RC_ID", "size"),
        old_area_km2=("area_km2", "sum"),
    )
    new_g = new.groupby(level).agg(
        new_count=("RC_ID", "size"),
        new_area_km2=("area_km2", "sum"),
    )
    nf = new_flags.groupby(level).agg(
        newly_found_anyintersect=("has_old_intersect", lambda s: int((~s).sum())),
        newly_found_iou01=("has_old_iou01", lambda s: int((~s).sum())),
        retail_parks=("is_retail_park", "sum"),
        sub_areas=("is_sub_area", "sum"),
    )
    of = old_flags.groupby(level).agg(
        disappeared_anyintersect=("has_new_intersect", lambda s: int((~s).sum())),
    )
    out = old_g.join(new_g, how="outer").join(nf, how="outer").join(of, how="outer").fillna(0)
    out["delta"] = out["new_count"] - out["old_count"]
    out["pct_change"] = np.where(out["old_count"] > 0,
                                 (out["delta"] / out["old_count"] * 100).round(1),
                                 np.nan)
    out["area_delta_km2"] = (out["new_area_km2"] - out["old_area_km2"]).round(2)
    int_cols = ["old_count", "new_count", "delta", "newly_found_anyintersect",
                "newly_found_iou01", "retail_parks", "sub_areas",
                "disappeared_anyintersect"]
    for c in int_cols:
        out[c] = out[c].astype(int)
    return out

hr("By country")
country_tbl = geo_breakdown("Country")
print(country_tbl.to_string())
country_tbl.to_csv(os.path.join(EXPORTS_DIR, "comparison_by_country.csv"))

hr("By region")
region_tbl = geo_breakdown("Region")
print(region_tbl.to_string())
region_tbl.to_csv(os.path.join(EXPORTS_DIR, "comparison_by_region.csv"))


# ---------------------------------------------------------------------------
# 8. Maps
# ---------------------------------------------------------------------------
hr("Maps")

print("  loading LAD boundaries for basemap...")
lad = gpd.read_file(LAD_PATH)
lad["country_code"] = lad["LAD24CD"].str[0]
country_map = {"E": "England", "S": "Scotland", "W": "Wales", "N": "Northern Ireland"}
lad["Country"] = lad["country_code"].map(country_map)
country_polys = lad.dissolve(by="Country").reset_index()


def add_basemap(ax):
    country_polys.plot(ax=ax, color="#f4f4f0", edgecolor="#888", linewidth=0.4, zorder=0)
    ax.set_axis_off()


# Compute centroids for plotting
new_pts = new.copy()
new_pts["geometry"] = new.geometry.centroid
new_pts = new_pts.merge(new_flags[["RC_ID", "has_old_intersect", "has_old_iou01"]], on="RC_ID")

old_pts = old.copy()
old_pts["geometry"] = old.geometry.centroid
old_pts = old_pts.merge(old_flags[["RC_ID", "has_new_intersect"]], on="RC_ID")

# 8a. Newly found
fig, ax = plt.subplots(figsize=(9, 11))
add_basemap(ax)
matched = new_pts[new_pts["has_old_intersect"]]
unmatched = new_pts[~new_pts["has_old_intersect"]]
matched.plot(ax=ax, color="#cccccc", markersize=2, alpha=0.4, label=f"Matched (n={len(matched)})")
unmatched.plot(ax=ax, color="#d62728", markersize=6, alpha=0.7,
               label=f"Newly found (n={len(unmatched)})")
ax.set_title("New centres: matched vs newly found", fontsize=13)
ax.legend(loc="upper right")
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "map_newly_found.png"), dpi=200)
plt.close()
print("  saved map_newly_found.png")

# 8b. Disappeared
fig, ax = plt.subplots(figsize=(9, 11))
add_basemap(ax)
kept = old_pts[old_pts["has_new_intersect"]]
gone = old_pts[~old_pts["has_new_intersect"]]
kept.plot(ax=ax, color="#cccccc", markersize=2, alpha=0.4, label=f"Still present (n={len(kept)})")
gone.plot(ax=ax, color="#1f77b4", markersize=6, alpha=0.7,
          label=f"Disappeared (n={len(gone)})")
ax.set_title("Old centres: still present vs disappeared", fontsize=13)
ax.legend(loc="upper right")
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "map_disappeared.png"), dpi=200)
plt.close()
print("  saved map_disappeared.png")

# 8c. Growth by region
new_by_region = new.groupby("Region").size()
old_by_region = old.groupby("Region").size()
pct_growth = ((new_by_region - old_by_region) / old_by_region * 100).rename("pct_growth")

# Build region polygons by dissolving LAD using a region attribution from new centres' centroids
# Simpler: union the centres' convex hulls per region, OR use lad sjoined to a region map.
# Approach: take centroids of new centres, sjoin with country basemap; for each region label
# we draw a coloured marker at the average position.
region_centroids = (
    new.assign(x=new.geometry.centroid.x, y=new.geometry.centroid.y)
    .groupby("Region")
    .agg(x=("x", "mean"), y=("y", "mean"))
    .join(pct_growth)
    .reset_index()
)
fig, ax = plt.subplots(figsize=(9, 11))
add_basemap(ax)
sizes = (region_centroids["pct_growth"].abs() * 4 + 80).clip(80, 800)
sc = ax.scatter(region_centroids["x"], region_centroids["y"],
                c=region_centroids["pct_growth"], s=sizes,
                cmap="RdYlGn", edgecolor="black", linewidth=0.5, zorder=3)
for _, r in region_centroids.iterrows():
    ax.annotate(f"{r['Region']}\n{r['pct_growth']:+.0f}%",
                (r["x"], r["y"]), fontsize=8, ha="center", va="center",
                xytext=(0, -30), textcoords="offset points")
plt.colorbar(sc, ax=ax, label="% change in centre count", shrink=0.5)
ax.set_title("Centre count growth by region (new vs old)", fontsize=13)
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "map_growth_by_region.png"), dpi=200)
plt.close()
print("  saved map_growth_by_region.png")

# 8d. Classification changes (1-1 matches only)
class_rank = {c: i for i, c in enumerate(CLASS_ORDER)}
o2o = one_to_one.copy()
o2o["old_rank"] = o2o["Old_Classification"].map(class_rank)
o2o["new_rank"] = o2o["New_Classification"].map(class_rank)
o2o["direction"] = np.where(
    o2o["new_rank"] < o2o["old_rank"], "Upgraded",
    np.where(o2o["new_rank"] > o2o["old_rank"], "Downgraded", "Unchanged"),
)
# Need centroids — join via New_RC_ID
o2o = o2o.merge(new[["RC_ID", "geometry"]].rename(columns={"RC_ID": "New_RC_ID"}),
                on="New_RC_ID")
o2o_gdf = gpd.GeoDataFrame(o2o, geometry="geometry", crs=new.crs)
o2o_gdf["geometry"] = o2o_gdf.geometry.centroid

fig, ax = plt.subplots(figsize=(9, 11))
add_basemap(ax)
colors = {"Unchanged": "#cccccc", "Upgraded": "#2ca02c", "Downgraded": "#d62728"}
for direction, color in colors.items():
    sub = o2o_gdf[o2o_gdf["direction"] == direction]
    sub.plot(ax=ax, color=color, markersize=4 if direction == "Unchanged" else 12,
             alpha=0.4 if direction == "Unchanged" else 0.8,
             label=f"{direction} (n={len(sub)})", zorder=2 if direction == "Unchanged" else 3)
ax.set_title("Classification changes (1-1 matches, IoU≥0.5)", fontsize=13)
ax.legend(loc="upper right")
plt.tight_layout()
plt.savefig(os.path.join(FIG_DIR, "map_classification_changes.png"), dpi=200)
plt.close()
print("  saved map_classification_changes.png")

print("\nDone.")
