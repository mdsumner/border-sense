# Border Sense

A slippy map for learning the world's borders, rivers, cities and land masses.
Everything is drawn as vectors from Natural Earth 1:50m, so country boundaries stay
crisp at every zoom; imagery and terrain come from NASA Blue Marble (embedded) or
live Esri tiles (on the hosted site).

Features

- crisp land boundaries at every zoom, disputed lines dashed, coastlines, rivers, lakes
- hover or click a country for name, region, capital, area and population
- Names on/off (learn shapes cold), city filter by population, population-scaled label zoom
- base maps: Plain, Blue Marble, and on the hosted site Satellite (Esri World Imagery),
  Terrain (Esri shaded relief) and a Hillshade overlay
- shading by nation (proper greedy map-colouring over the adjacency graph, no two
  neighbours share a hue) or by continent, with an opacity slider
- quizzes: Find it (click the named country) and Name it (four choices, keys 1-4),
  filterable by continent and country size; streak and best score kept locally
- seamless across the antimeridian: dateline-straddling countries are stitched and
  every layer is drawn at -360/0/+360, pannable to +/-270 degrees

## Build

    pip install -r requirements.txt
    python build.py

Outputs

- `docs/` - the GitHub Pages site (`index.html`, `data.json`, `bm_merc.jpg`); loads Leaflet
  from unpkg and Esri tiles live
- `dist/border-sense.html` - a single self-contained file (Leaflet, data and Blue Marble
  inlined, about 5 MB) that works offline or as a hosted artifact

`build.py` fetches Natural Earth GeoJSON from the nvkelso/natural-earth-vector repo and the
Blue Marble Next Generation image from NASA (falling back to the copy in the basemap-data
sdist), slims and rounds the vectors, computes label points and areas, stitches
antimeridian-crossing countries, colours the nation graph with shapely, and reprojects the
imagery to Web Mercator. Sources are cached in `cache/`; `--skip-imagery` reuses the
reprojected JPEG.

## Deploy

The workflow in `.github/workflows/pages.yml` builds on every push to `main` and deploys
`docs/` with GitHub Pages. In the repository settings set Pages > Source to
"GitHub Actions" once. The single-file build is attached to each run as a workflow artifact.

## Data and credits

- Natural Earth (public domain): admin-0 countries and boundary lines, rivers and lake
  centerlines, lakes, populated places, all 1:50m
- NASA Blue Marble Next Generation, December 2004 with topography and bathymetry (public domain)
- Esri World Imagery, World Shaded Relief and World Hillshade tiles (hosted site only;
  subject to Esri's terms of use, attribution shown on the map)
- Leaflet 1.9.4 (BSD-2-Clause)

Country names, boundaries and the sovereign/dependency classification follow Natural Earth's
de facto conventions.
