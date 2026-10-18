# OSM data

The normal runtime source is `data/server/wuhan-main-roads.json`, which is
loaded by `server.py` and queried by bbox. The browser never downloads this
full-city file in one request.

`wuhan-main-roads.json` is a small real extract around Wuhan's Optics Valley
area. It remains as a fallback for opening the page when the full server cache
has not been generated. It contains only major OSM roads, not POIs.

When the local server is running, panning into a new area requests the matching
part of the full Wuhan server cache through `/api/network`. Clicking outside
the current cache or finding no route triggers the same server request. The
browser receives only the requested area, not the full-city file.

To generate the full server cache from an OSM PBF, run from the project root:

```text
py tools/build_wuhan_network.py --pbf E:\\G4-A4数据\\hubei-latest.osm.pbf
```

The normal startup requires the full server file. The old small cache is not
used by `server.py`, so an incomplete local setup is reported clearly instead
of silently producing incomplete routes.

The data comes from OpenStreetMap and is distributed under the Open Database
License (ODbL). Keep the source, date, bounding box, and attribution metadata
with any redistributed copy.
