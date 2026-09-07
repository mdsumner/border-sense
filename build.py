#!/usr/bin/env python3
"""Build Border Sense.

Steps:
  1. fetch Natural Earth 1:50m GeoJSON (countries, boundary lines, rivers, lakes, populated places)
  2. slim + round, compute label points and areas, stitch countries across the antimeridian,
     greedy map-colouring over the border-adjacency graph
  3. reproject NASA Blue Marble NG (equirectangular 5400x2700) to Web Mercator (4096x4096 JPEG)
  4. render template.html into
       docs/index.html + docs/data.json + docs/bm_merc.jpg   (GitHub Pages; live tiles enabled)
       dist/border-sense.html                                (single self-contained file)

Usage: python build.py [--skip-fetch] [--skip-imagery]
Requires: numpy, pillow, shapely (pip install -r requirements.txt)
"""
import argparse, base64, io, json, math, os, sys, tarfile, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
DOCS = os.path.join(ROOT, "docs")
DIST = os.path.join(ROOT, "dist")
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
LAYERS = ["ne_50m_admin_0_countries", "ne_50m_admin_0_boundary_lines_land",
          "ne_50m_rivers_lake_centerlines", "ne_50m_lakes", "ne_50m_populated_places_simple"]
BLUE_MARBLE = "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/world.topo.bathy.200412.3x5400x2700.jpg"
BASEMAP_DATA = "https://files.pythonhosted.org/packages/source/b/basemap_data/basemap_data-2.0.0.tar.gz"
LEAFLET = "1.9.4"


def fetch(url, dest):
    if os.path.exists(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("fetch", url)
    req = urllib.request.Request(url, headers={"User-Agent": "border-sense-build"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


# ---------------------------------------------------------------- vectors
def rnd(c):
    if not c:
        return c
    if isinstance(c[0], (int, float)):
        return [round(c[0], 3), round(c[1], 3)]
    return [rnd(x) for x in c]


def slim(path, keep, filt=lambda p: True):
    d = json.load(open(path))
    out = []
    for f in d["features"]:
        p = f["properties"]
        if not filt(p) or not f["geometry"]:
            continue
        out.append({"type": "Feature",
                    "properties": {k: p[a] for k, a in keep.items()},
                    "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])}})
    return {"type": "FeatureCollection", "features": out}


def proj(r):
    return [(x * 111.32 * math.cos(math.radians(y)), y * 110.57) for x, y in r]


def area_centroid(ring):
    p = proj(ring)
    A = cx = cy = 0
    for i in range(len(p) - 1):
        x1, y1 = p[i]; x2, y2 = p[i + 1]
        cr = x1 * y2 - x2 * y1
        A += cr; cx += (x1 + x2) * cr; cy += (y1 + y2) * cr
    A /= 2
    if abs(A) < 1e-9:
        return 0, None
    cx /= 6 * A; cy /= 6 * A
    lat = cy / 110.57
    lon = cx / (111.32 * math.cos(math.radians(lat)))
    return abs(A), (round(lon, 3), round(lat, 3))


# hand-placed label points where the centroid of the largest ring is a poor label position
LABEL_FIX = {"Russian Federation": [99, 62], "United States": [-99, 39], "Canada": [-105, 58], "Norway": [9, 61],
             "Chile": [-71, -35], "France": [2.5, 46.8], "Netherlands": [5.5, 52.3], "Denmark": [9.5, 56.2],
             "Indonesia": [113, -1], "Malaysia": [102, 4]}


def ring_area_deg(r):
    a = 0
    for i in range(len(r) - 1):
        x1, y1 = r[i]; x2, y2 = r[i + 1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def stitch_antimeridian(feature):
    """Natural Earth splits polygons at 180. Shift the smaller hemisphere's far-side parts across
    so a country's bounds are contiguous (Fiji, Russia, USA/Aleutians, NZ, Kiribati)."""
    g = feature["geometry"]; p = feature["properties"]
    if g["type"] != "MultiPolygon" or p["n"] == "Antarctica":
        return None
    parts = g["coordinates"]
    if not any(q[0][0][0] > 150 for q in parts) or not any(q[0][0][0] < -150 for q in parts):
        return None
    pos = [q for q in parts if q[0][0][0] > 0]; neg = [q for q in parts if q[0][0][0] < 0]
    apos = sum(ring_area_deg(q[0]) for q in pos); aneg = sum(ring_area_deg(q[0]) for q in neg)
    if apos >= aneg:
        side, dx = [q for q in neg if q[0][0][0] < -150], 360
    else:
        side, dx = [q for q in pos if q[0][0][0] > 150], -360
    for poly in side:
        for ring in poly:
            for c in ring:
                c[0] = round(c[0] + dx, 3)
    lp = p["lp"]
    if lp and ((dx == 360 and lp[0] < -150) or (dx == -360 and lp[0] > 150)):
        lp[0] = round(lp[0] + dx, 3)
    return dx


def colour_countries(features):
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    geoms = [shape(f["geometry"]).buffer(0) for f in features]
    tree = STRtree(geoms)
    adj = {i: set() for i in range(len(features))}
    for i, g in enumerate(geoms):
        gb = g.buffer(0.02)
        for j in tree.query(gb):
            j = int(j)
            if j != i and gb.intersects(geoms[j]):
                adj[i].add(j); adj[j].add(i)
    col = {}
    for i in sorted(adj, key=lambda i: -len(adj[i])):
        used = {col[j] for j in adj[i] if j in col}
        col[i] = next((c for c in range(8) if c not in used), i % 8)
    for i, f in enumerate(features):
        f["properties"]["col"] = col[i]


def home_bounds(polys, best):
    """Bounding box of a country's 'home' territory: the largest part plus any part that is either
    within 25 degrees of it or at least 30 percent of its area. Keeps the Name-it zoom on the
    Netherlands rather than the Netherlands plus Bonaire, while USA still includes Alaska via size."""
    if not best[1]:
        return None
    bx, by = best[1]
    xs, ys = [], []
    for poly in polys:
        A, c = area_centroid(poly[0])
        if c is None:
            continue
        near = abs(c[0] - bx) < 25 and abs(c[1] - by) < 25
        if A == best[0] or near or A >= 0.3 * best[0]:
            for x, y in poly[0]:
                xs.append(x); ys.append(y)
    return [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)]


def build_data():
    C = slim(os.path.join(CACHE, "ne_50m_admin_0_countries.geojson"),
             {"n": "NAME_LONG", "sn": "NAME", "s": "SOVEREIGNT", "t": "TYPE", "c": "CONTINENT", "adm": "ADMIN",
              "a3": "ADM0_A3", "pop": "POP_EST", "sub": "SUBREGION"})
    for f in C["features"]:
        p = f["properties"]
        p["sov"] = p["t"] in ("Sovereign country", "Country", "Sovereignty") and p["s"] == p.pop("adm")
        p["pop"] = int(p["pop"] or 0)
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        best, total = (0, None), 0
        for poly in polys:
            A, c = area_centroid(poly[0]); total += A
            if A > best[0]:
                best = (A, c)
        p["area"] = round(total)
        p["lp"] = LABEL_FIX.get(p["n"], list(best[1]) if best[1] else None)
        p["mb"] = home_bounds(polys, best)
    for f in C["features"]:
        dx = stitch_antimeridian(f)
        if dx:
            print("  stitched", f["properties"]["n"], dx)
            g = f["geometry"]; p = f["properties"]
            polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            best = max(((area_centroid(q[0])) for q in polys), key=lambda ac: ac[0])
            p["mb"] = home_bounds(polys, best)
    colour_countries(C["features"])
    B = slim(os.path.join(CACHE, "ne_50m_admin_0_boundary_lines_land.geojson"), {"f": "FEATURECLA"})
    R = slim(os.path.join(CACHE, "ne_50m_rivers_lake_centerlines.geojson"), {"n": "name_en", "r": "scalerank"},
             lambda p: p["scalerank"] <= 7)
    L = slim(os.path.join(CACHE, "ne_50m_lakes.geojson"), {"n": "name_en", "r": "scalerank"}, lambda p: p["scalerank"] <= 4)
    P = slim(os.path.join(CACHE, "ne_50m_populated_places_simple.geojson"),
             {"n": "name", "cap": "adm0cap", "co": "adm0name", "pop": "pop_max", "r": "scalerank", "a3": "adm0_a3"})
    print("  countries %d, boundaries %d, rivers %d, lakes %d, places %d" %
          tuple(len(x["features"]) for x in (C, B, R, L, P)))
    return {"countries": C, "bounds": B, "rivers": R, "lakes": L, "places": P}


# ---------------------------------------------------------------- imagery
def get_blue_marble():
    dest = os.path.join(CACHE, "bmng.jpg")
    if os.path.exists(dest):
        return dest
    try:
        return fetch(BLUE_MARBLE, dest)
    except Exception as e:
        print("  NASA fetch failed (%s); falling back to basemap-data sdist" % e)
    tgz = fetch(BASEMAP_DATA, os.path.join(CACHE, "basemap_data.tar.gz"))
    with tarfile.open(tgz) as t:
        m = next(m for m in t.getmembers() if m.name.endswith("/bmng.jpg"))
        with open(dest, "wb") as f:
            f.write(t.extractfile(m).read())
    return dest


def reproject_mercator(src, dest, N=4096):
    import numpy as np
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    img = np.asarray(Image.open(src).convert("RGB"))
    H = img.shape[0]
    ys = (np.arange(N) + .5) / N
    lat = np.degrees(np.arctan(np.sinh((0.5 - ys) * 2 * math.pi)))
    row = (90 - lat) / 180 * H - 0.5
    r0 = np.clip(np.floor(row).astype(int), 0, H - 1); r1 = np.clip(r0 + 1, 0, H - 1)
    t = (row - r0)[:, None, None]
    out = (img[r0] * (1 - t) + img[r1] * t).astype(np.uint8)
    Image.fromarray(out).resize((N, N), Image.LANCZOS).save(dest, quality=78, optimize=True, progressive=True)
    print("  wrote", dest, os.path.getsize(dest), "bytes")


# ---------------------------------------------------------------- render
def render(template, data_json, sat_path, live):
    t = template
    if live:
        head = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@%s/dist/leaflet.css">' % LEAFLET)
        t = t.replace("<style>\n__LEAFLET_CSS__\n</style>", head)
        t = t.replace("<script>\n__LEAFLET_JS__\n</script>",
                      '<script src="https://unpkg.com/leaflet@%s/dist/leaflet.js"></script>' % LEAFLET)
        t = t.replace('<script id="geo" type="application/json">__DATA__</script>', "")
        t = t.replace("__SAT__", "bm_merc.jpg").replace("__LIVE__", "true")
        head, body = t.split('<div id="bar">', 1)
        t = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
             '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + head +
             '</head>\n<body>\n<div id="bar">' + body + '</body>\n</html>\n')
    else:
        css = open(fetch("https://unpkg.com/leaflet@%s/dist/leaflet.css" % LEAFLET, os.path.join(CACHE, "leaflet.css"))).read()
        js = open(fetch("https://unpkg.com/leaflet@%s/dist/leaflet.js" % LEAFLET, os.path.join(CACHE, "leaflet.js"))).read()
        sat = "data:image/jpeg;base64," + base64.b64encode(open(sat_path, "rb").read()).decode()
        t = t.replace("__LEAFLET_CSS__", css).replace("__LEAFLET_JS__", js)
        t = t.replace("__DATA__", data_json).replace("__SAT__", sat).replace("__LIVE__", "false")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true", help="use cached Natural Earth files")
    ap.add_argument("--skip-imagery", action="store_true", help="reuse cache/bm_merc.jpg")
    a = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True); os.makedirs(DOCS, exist_ok=True); os.makedirs(DIST, exist_ok=True)

    print("vectors")
    for name in LAYERS:
        fetch(NE + name + ".geojson", os.path.join(CACHE, name + ".geojson"))
    data = build_data()
    data_json = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
    open(os.path.join(DOCS, "data.json"), "w").write(data_json)

    print("imagery")
    merc = os.path.join(CACHE, "bm_merc.jpg")
    if not (a.skip_imagery and os.path.exists(merc)):
        reproject_mercator(get_blue_marble(), merc)
    open(os.path.join(DOCS, "bm_merc.jpg"), "wb").write(open(merc, "rb").read())

    print("render")
    template = open(os.path.join(ROOT, "template.html")).read()
    open(os.path.join(DOCS, "index.html"), "w").write(render(template, data_json, merc, live=True))
    open(os.path.join(DIST, "border-sense.html"), "w").write(render(template, data_json, merc, live=False))
    print("  docs/index.html (Pages, live tiles) and dist/border-sense.html (single file, %d bytes)" %
          os.path.getsize(os.path.join(DIST, "border-sense.html")))


if __name__ == "__main__":
    main()
