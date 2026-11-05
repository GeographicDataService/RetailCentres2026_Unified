"""Extract Cardiff's district and local centres from the Replacement LDP Deposit Plan Proposals Map (January 2025).

Cardiff publishes no centre GIS, only the A0 Proposals Map inside the Deposit Plan PDF (Cabinet 23 Jan 2025, Appendix 1,
page 214). No hand tracing: the map is read as the council drew it.
- Georeferencing: the map is 1:20,000 with the National Grid printed on its frame; page coordinates are fitted to the
  printed km labels (northings on the left edge, eastings on the top edge) by least squares; residuals are printed.
- District centres (R4) and local centres (R5) are semi-transparent fills, rasterised in the PDF. The page is rendered at
  4 px/pt (~1.8 m/px); pixels matching the legend colours are kept, closed (to bridge labels and route lines drawn on
  top) and polygonised. Pieces within 25 m are merged (roads and labels cut some centres); pieces under 0.1 ha or under
  12 m mean width (outlines of other layers) are dropped; counts are checked against the map key (11 district, 20 local). The on-map R4.x / R5.x labels are drawn as
  outlines, not text, so centres are not named.
- The Central Retail and Commercial Area (SP8, EC6, R2) is a light-blue outline in the same raster; the filled
  loop containing Queen Street is kept.

Writes validation/data/cities/cardiff__{district_centres,local_centres,central_retail_area}.geojson (EPSG:27700).
Map: based upon Ordnance Survey mapping, Crown copyright, City of Cardiff Council; statistics only.

Run from repo root (pymupdf is not a project dependency):
  uv run --no-project --python .venv/bin/python --with pymupdf python validation/prep/digitise_cardiff.py
"""
import re
from pathlib import Path

import fitz  # pymupdf
import geopandas as gpd
import numpy as np
import requests
from rasterio import features
from rasterio.transform import Affine
from scipy import ndimage
from shapely.geometry import Point, shape
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parents[1]  # validation/
PDF = HERE / "data/cardiff/deposit_plan_2025.pdf"
URL = "https://cardiff.moderngov.co.uk/documents/s83196/x.pdf"
OUT = HERE / "data/cities"
PAGE, ZOOM = 213, 4  # zero-based page index of the Proposals Map; render scale (px per pt)
KEY = {"R4": 11, "R5": 20}  # centres listed in the map key


def georef(page):
    """Least-squares page point -> BNG metres: first guess from the printed km labels on the frame, then fitted to the
    1 km grid lines drawn across the map. The labels alone are not enough: the easting labels sit ~9 pt (64 m) right of
    their lines. The grid lines are rasterised, so they are found as thin dark lines near each predicted position."""
    words = page.get_text("words")
    north = [((w[1] + w[3]) / 2, int(w[4]) * 1000 + 100000) for w in words if w[0] < 60 and re.fullmatch(r"\d{2}", w[4])]
    east = [((w[0] + w[2]) / 2, int(w[4]) * 1000 + 300000) for w in words if w[1] < 70 and re.fullmatch(r"\d{2}", w[4])]
    (by, ay), (bx, ax) = np.polyfit(*zip(*north), 1), np.polyfit(*zip(*east), 1)
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).astype(int).mean(axis=2)
    vx = ((g[:, 2:-2] < g[:, :-4] - 15) & (g[:, 2:-2] < g[:, 4:] - 15))[600:4400].mean(axis=0)
    hy = ((g[2:-2] < g[:-4] - 15) & (g[2:-2] < g[4:] - 15))[:, 1000:6200].mean(axis=1)

    def lines(profile, km, a, b):
        found = []
        for v in km:
            p = (v - a) / b  # predicted page position; search +-15 pt (+-105 m)
            seg = profile[int((p - 15) * 2) - 2:int((p + 15) * 2) - 2]
            if len(seg) and seg.max() > 0.25:
                found.append(((int((p - 15) * 2) + seg.argmax() + 1) / 2, v, p))
        off = np.median([q - p for q, _, p in found])
        return [(q, v) for q, v, p in found if abs(q - p - off) < 2]  # drop stray detections (other dark lines)
    vl = lines(vx, range(306000, 328000, 1000), ax, bx)
    hl = lines(hy, range(171000, 187000, 1000), ay, by)
    (bx, ax), (by, ay) = np.polyfit(*zip(*vl), 1), np.polyfit(*zip(*hl), 1)
    res = [abs(ax + bx * x - e) for x, e in vl] + [abs(ay + by * y - n) for y, n in hl]
    print(f"georef: {len(vl)} + {len(hl)} grid lines, {bx:.3f} m/pt, max residual {max(res):.1f} m")
    return ax, bx, ay, by


def fills(page, ax, bx, ay, by):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # legend pink (254,176,215) / over buildings (212,136,176); purple (191,128,254) / (152,88,212). Salmon housing and
    # employment layers have g == b or r == g, so the gaps between channels separate them.
    # The Central Retail and Commercial Area is a light-blue outline (128,212,252); the River Corridor's blue has g ~168.
    masks = {"R4": (r > 195) & (b - g > 25) & (r - b > 25),
             "R5": (b > 200) & (r > 140) & (g > 75) & (b - r > 40) & (r - g > 40),
             "CRA": (abs(r - 128) < 16) & (g > 198) & (b > 235)}
    t = Affine(bx / ZOOM, 0, ax, 0, by / ZOOM, ay)  # pixel -> BNG
    out = {}
    for k, m in masks.items():
        m[:, : 340 * ZOOM] = False  # legend panel, including the key swatches
        m = ndimage.binary_fill_holes(ndimage.binary_closing(m, np.ones((7, 7)), iterations=2))
        m = ndimage.binary_opening(m, np.ones((3, 3)))
        out[k] = [shape(geom) for geom, v in features.shapes(m.astype(np.uint8), mask=m, transform=t) if v == 1]
    return out


def main():
    if not PDF.exists():
        PDF.parent.mkdir(parents=True, exist_ok=True)
        PDF.write_bytes(requests.get(URL, timeout=300, headers={"User-Agent": "Mozilla/5.0"}).content)
    page = fitz.open(PDF)[PAGE]
    ax, bx, ay, by = georef(page)
    polys = fills(page, ax, bx, ay, by)
    OUT.mkdir(parents=True, exist_ok=True)
    for prefix, name in [("R4", "district_centres"), ("R5", "local_centres")]:
        merged = unary_union([g.buffer(12.5) for g in polys[prefix]])  # bridge gaps up to 25 m
        parts = [unary_union([g for g in polys[prefix] if g.intersects(m)]) for m in getattr(merged, "geoms", [merged])]
        # drop pieces under 0.1 ha and line-like pieces (mean width 2A/P under 12 m: outlines of other layers)
        parts = [g for g in parts if g.area >= 1000 and 2 * g.area / g.length >= 12]
        g = gpd.GeoDataFrame({"code": [f"{prefix}_{i}" for i in range(len(parts))]}, geometry=parts, crs=27700)
        g.to_file(OUT / f"cardiff__{name}.geojson", driver="GeoJSON")
        print(f"{name}: {len(g)} extracted vs {KEY[prefix]} in the key, {g.area.sum() / 1e4:.0f} ha")
    # Central Retail and Commercial Area: the filled light-blue loop covering the city centre (Queen Street)
    area = next(g for g in polys["CRA"] if g.contains(Point(318400, 176500)))
    gpd.GeoDataFrame({"name": ["Central Retail and Commercial Area"]}, geometry=[area], crs=27700).to_file(
        OUT / "cardiff__central_retail_area.geojson", driver="GeoJSON")
    print(f"central retail area: {area.area / 1e4:.0f} ha")

if __name__ == "__main__":
    main()
