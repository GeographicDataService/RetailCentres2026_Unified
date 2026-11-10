"""Step 1. Agreement with planning centre designations: paper Table 4, the Glasgow and small-parade figures in Section
4.2.1, and Figure 7 (Birmingham).

Designations (prep/ downloads them into data/): Northern Ireland, DfI Area Plan town and city centres; Scotland, the
Spatial Hub town centres layer (every feature, as published); London, the GLA's Planning Local Plan Data (centre layers
of every tier); and the nine Core Cities UK members in England and Wales (CORE). Agreement is pooled over each row:
  P = union of the designations, O = union of our centres touching P, A = our centres in the councils containing P;
  found = share of designations touching a centre; not_designated = share of A touching none, split centres counted once;
  iou_intersecting = IoU of the designations found and O; iou_all = IoU of P and A.
Writes outputs/planning/{table4.csv, small_parades.csv, birmingham_map.png}.
Run from repo root:  .venv/bin/python validation/planning.py
"""
import contextily as cx
import geopandas as gpd
import matplotlib
import pandas as pd
import pyarrow.parquet as pq
import shapely

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from common import DATA, LADS, OLD, OUT, RUN, load_new, prep  # noqa: E402

DEST = OUT / "planning"
# each city's centre layers at every tier, plus Liverpool's out-of-centre retail (files under data/); primary shopping
# areas and retail cores are not scored
LP = "liverpool/Planning_NewLocalPlan_pla_lp_"
CORE = {
    "Birmingham": ["cities/birmingham__city_centre", "cities/birmingham__centres"],
    "Bristol": ["cities/bristol__city_centre", "cities/bristol__centres"],
    "Cardiff": ["cities/cardiff__central_retail_area", "cities/cardiff__district_centres", "cities/cardiff__local_centres"],
    "Leeds": ["cities/leeds__city_centre", "cities/leeds__centres"],
    "Liverpool": [LP + "city_centre_boundary", LP + "district_centres", LP + "local_centres", LP + "retail_out_of_centre"],
    "Manchester": ["cities/manchester__city_centre", "cities/manchester__district_centres"],
    "Newcastle": ["cities/newcastle__urban_core", "cities/newcastle__centres"],
    "Nottingham": [f"cities/nottingham__{f}" for f in ["city_centre", "town_centres", "district_centres", "local_centres", "neighbourhood_centres"]],
    "Sheffield": [f"cities/sheffield__{f}" for f in ["city_centre", "district_centres", "local_centres"]],
}
# London layers scored, by name: centre boundaries at every tier; shopping areas, frontages and policy areas are not centres
LONDON_KEEP = (r"town cent|metropolitan|major|district|local cent|local shopping|neighbourhood|parade|international|"
               r"central activities zone retail|caz retail|area centres|shopping centre|local plan centres|principal shopping")
LONDON_DROP = r"primary shopping|core shopping|secondary shopping|frontage|special character|special policy|townscape|silvertown|development centre|extension"


def read(path):
    g = gpd.read_file(path)
    return g.set_crs(27700, allow_override=True) if g.total_bounds[2] > 1000 else g.to_crs(27700)  # ArcGIS mislabels BNG as WGS84


def load_city(city):
    return prep(pd.concat([prep(gpd.read_file(DATA / f"{f}.geojson")[["geometry"]]) for f in CORE[city]], ignore_index=True))


def load_london():
    """London borough centres; a centre at least half inside another kept centre (the same centre drawn by two
    neighbouring authorities, Waltham Forest's parades within its neighbourhood centres) counts once."""
    src = pd.read_csv(DATA / "london_boroughs/sources.csv")
    src = src[(src.features > 0) & src.layer.str.contains(LONDON_KEEP, case=False) & ~src.layer.str.contains(LONDON_DROP, case=False)]
    d = prep(gpd.GeoDataFrame(pd.concat([read(DATA / "london_boroughs" / f)[["geometry"]] for f in src.file], ignore_index=True), crs=27700))
    j = gpd.sjoin(d, d, predicate="intersects").reset_index()
    j = j[j["index"] != j.index_right]
    a, b = d.geometry.values[j["index"].to_numpy()], d.geometry.values[j.index_right.to_numpy()]
    aa, ab = shapely.area(a), shapely.area(b)
    inner = (shapely.area(shapely.intersection(a, b)) >= 0.5 * aa) & ((ab > aa) | ((ab == aa) & (j.index_right < j["index"])))
    return d.drop(index=j["index"][inner].unique()).reset_index(drop=True)


def in_lads(centres, ref):
    """Our centres in the councils the designations fall in."""
    lads = gpd.read_file(LADS).to_crs(27700)
    hit = gpd.sjoin(lads, gpd.GeoDataFrame(geometry=ref.geometry.representative_point(), crs=27700), predicate="contains")
    return centres[centres.geometry.representative_point().within(lads[lads.LAD22CD.isin(set(hit.LAD22CD))].union_all())]


def agreement(ref, ours):
    P = ref.union_all()
    O = ours[ours.intersects(P)].union_all()
    Pm = ref[ref.intersects(O)].union_all()
    area = in_lads(ours, ref)
    hit = area.intersects(P)
    if "centre" in area:  # sub-centres of a split centre count once
        hit = hit.groupby(area.centre).any()
    A = area.union_all()
    return dict(boundaries=len(ref), found=ref.intersects(O).mean(), not_designated=1 - hit.mean(),
                iou_intersecting=Pm.intersection(O).area / Pm.union(O).area, iou_all=P.intersection(A).area / P.union(A).area)


def small_parades(cities):
    """Designations with fewer than 10 filtered POIs (any category) within 10 m: below our minimum centre size."""
    t = pq.read_table(RUN / "foursquare_filtered.parquet", columns=["fsq_place_id", "lat", "lng"]).to_pandas().drop_duplicates("fsq_place_id")
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(t.lng, t.lat), crs=4326).to_crs(27700)
    rows = []
    for city, ref in cities.items():
        n = gpd.sjoin(pts, gpd.GeoDataFrame(geometry=ref.buffer(10), crs=27700), predicate="within").groupby("index_right").size()
        rows.append(dict(city=city, designations=len(ref), under_10_pois=int((n.reindex(ref.index, fill_value=0) < 10).sum())))
    pd.DataFrame(rows).to_csv(DEST / "small_parades.csv", index=False)


# Figure 7: our centres by class with Birmingham's designations by tier, coloured as the class each corresponds to
INK, MUTED, PARK_EDGE = "#1f1f1e", "#6b6a63", "#d95f0e"
CLASS_COLOURS = {"Regional Centre": "#1f77b4", "Major Town Centre": "#d62728", "Town Centre": "#ff7f0e", "Market Town": "#9467bd",
                 "District Centre": "#2ca02c", "Local Centre": "#17becf", "Small Local Centre": "#bcbd22",
                 "Large Shopping Centre": "#8c564b", "Small Shopping Centre": "#e377c2"}
TIER_COLOURS = {"City Centre": "Regional Centre", "Principal Town Centre": "Major Town Centre", "Town Centre": "Town Centre",
                "District Centre": "District Centre", "Local Centre": "Local Centre"}
NUDGE = {"Ladypool Road": (-3, -7, "right"), "Sparkhill": (4, 6, "left"), "Stoney Lane": (4, -8, "left"),  # labels that collide
         "Lozells": (-3, -7, "right"), "Six Ways Aston": (4, 6, "left"), "Ward End": (-3, 4, "right"),
         "Yardley Road": (-3, 8, "right"), "Selly Oak": (14, 10, "left"), "Tyseley": (4, -8, "left")}
WINDOW = (402700, 282300, 413700, 291300)  # BNG: city centre, west edge just past Harborne
CREDIT = 'Birmingham City Council, Birmingham Local Plan, "Publication Plan" (Regulation 19, 2026; not adopted).'


def birmingham_map(ours):
    plan = prep(pd.concat([read(DATA / f"cities/birmingham__{f}.geojson").rename(columns={col: "tier"})
                           for f, col in [("city_centre", "CENTRE_HIERARCHY"), ("centres", "HIERACHY")]], ignore_index=True))  # sic
    x0, y0, x1, y1 = WINDOW
    w = 7.2
    h = w * (y1 - y0) / (x1 - x0) + 0.8
    fig, ax = plt.subplots(figsize=(w, h), dpi=300)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.8 / h)
    ax.set(xlim=(x0, x1), ylim=(y0, y1), xticks=[], yticks=[])
    cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik, crs=27700, attribution=False, zoom=15,
                   headers={"User-Agent": "GeoDS-retail-centres-paper"})  # OSM blocks requests without one
    im = ax.images[-1]  # basemap in grey
    im.set_data(im.get_array()[..., :3] @ [0.299, 0.587, 0.114])
    im.set(cmap="gray", clim=(-80, 255))
    ax.set(xlim=(x0, x1), ylim=(y0, y1))
    near, handles = ours.cx[x0:x1, y0:y1], []
    for c, col in CLASS_COLOURS.items():
        if (near.Classification == c).any():
            near[near.Classification == c].plot(ax=ax, facecolor=col, edgecolor="white", linewidth=0.2, alpha=0.5)
            handles.append(Patch(facecolor=col, alpha=0.5, label=c))
    parks = near[near.Classification.str.contains("Retail Park")]
    parks.plot(ax=ax, facecolor="none", edgecolor=PARK_EDGE, linewidth=0.5, hatch="//////")
    handles.append(Patch(facecolor="none", edgecolor=PARK_EDGE, hatch="//////", label="Retail Park"))
    lines = []
    for tier, cls in TIER_COLOURS.items():
        g = plan[plan.tier == tier]
        if not g.cx[x0:x1, y0:y1].empty:
            g.plot(ax=ax, facecolor="none", edgecolor=CLASS_COLOURS[cls], linewidth=1.1, linestyle=(0, (4, 2)))
            lines.append(Line2D([], [], color=CLASS_COLOURS[cls], lw=1.2, ls=(0, (4, 2)), label=f"Plan {tier.lower()}"))
    lads = gpd.read_file(LADS, bbox=WINDOW).to_crs(27700)  # the plan covers only its own council
    lads[lads.LAD22NM == "Birmingham"].boundary.plot(ax=ax, color="#333333", linewidth=0.9, zorder=5)
    lines.append(Line2D([], [], color="#333333", lw=0.9, label="Birmingham local authority boundary"))
    rows = -(-max(len(handles), len(lines)) // 2)  # our classes in the left two legend columns, plan lines in the right two
    legend = handles + [Line2D([], [], alpha=0, label=" ")] * (2 * rows - len(handles)) + lines
    for n in plan.itertuples():
        p = n.geometry.representative_point()
        left, low = p.x > x1 - 1500, p.y > y1 - 300  # near the right or top edge: label left of or below the point
        dx, dy, ha = NUDGE.get(n.CENTRE_NAME, (-3 if left else 3, -3 if low else 2, "right" if left else "left"))
        major = "City Centre" in n.CENTRE_NAME
        ax.annotate(n.CENTRE_NAME, (p.x, p.y), xytext=(dx, dy), textcoords="offset points", ha=ha, va="top" if low else "baseline",
                    fontsize=7 if major else 5.5, fontweight="bold" if major else "normal", color=INK, zorder=7,
                    path_effects=[pe.withStroke(linewidth=1.2, foreground="white")])
    ax.annotate("N", xy=(0.07, 0.93), xytext=(0.07, 0.83), xycoords="axes fraction", textcoords="axes fraction", ha="center",
                va="center", fontsize=7, fontweight="bold", arrowprops=dict(facecolor="black", width=2, headwidth=6, headlength=6))
    length = next(v for v in [2000, 1000, 500, 200, 100] if v <= (x1 - x0) / 3)  # scale bar
    frac = length / (x1 - x0)
    ax.add_patch(mpatches.Rectangle((0.05, 0.05), frac, 0.008, transform=ax.transAxes, color="black", zorder=9))
    ax.text(0.05 + frac / 2, 0.07, f"{length / 1000:g} km" if length >= 1000 else f"{length} m", transform=ax.transAxes,
            ha="center", va="bottom", fontsize=6, zorder=9)
    fig.legend(handles=legend, loc="lower center", ncol=4, fontsize=6, frameon=False, bbox_to_anchor=(0.5, 0.012))
    fig.text(0.5, 0.005, f"Planning boundaries: {CREDIT} Basemap: © OpenStreetMap contributors.", ha="center", va="bottom",
             fontsize=4.8, color=MUTED)
    fig.savefig(DEST / "birmingham_map.png")
    plt.close(fig)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    new, old = load_new(), prep(gpd.read_parquet(OLD))
    sh = gpd.read_file(DATA / "spatialhub_scotland_all.geojson").to_crs(27700)
    refs = {"Northern Ireland": prep(gpd.read_file(DATA / "ni/dfi_town_city_centres.geojson")[["geometry"]]),
            "Scotland": prep(sh[["geometry"]]),
            "Glasgow": prep(sh[sh.local_authority == "Glasgow City"][["geometry"]]),
            "London": load_london()}
    cities = {c: load_city(c) for c in CORE}
    refs |= cities | {"Core Cities, combined": pd.concat(cities.values(), ignore_index=True)}
    rows = [dict(designations=name, centres=k, **agreement(ref, g)) for name, ref in refs.items() for k, g in [("new", new), ("2022", old)]]
    t = pd.DataFrame(rows)
    t.round(4).to_csv(DEST / "table4.csv", index=False)
    print(t.round(2).to_string(index=False))
    small_parades(cities)
    birmingham_map(new)


if __name__ == "__main__":
    main()
