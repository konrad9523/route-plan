"""Convert a modest OSM PBF region into the project's directed OSMnx-style GraphML.

Usage (from repository root):
    python tools/convert_dc_osm.py input.osm.pbf output.graphml

OSM turn-restriction relations are not applied. This is a basic car graph,
not a turn-aware navigation network. No changes are made to the original PBF.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import json
import math
import re
from xml.sax.saxutils import escape

import osmium

# Include common public roads. service roads are permitted unless tagged as
# restricted; they can be dropped via --without-service.
DRIVABLE = {
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
    "residential", "living_street", "service",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}
DEFAULT_SPEED = {
    "motorway": 95, "trunk": 80, "primary": 55, "secondary": 45,
    "tertiary": 40, "unclassified": 35, "residential": 30,
    "living_street": 15, "service": 15,
    "motorway_link": 45, "trunk_link": 40, "primary_link": 35,
    "secondary_link": 30, "tertiary_link": 25,
}
RESTRICTED = {"no", "private", "agricultural", "forestry"}

def allowed(tags, without_service=False):
    road = tags.get("highway", "")
    if road not in DRIVABLE or (without_service and road == "service"):
        return False
    for key in ("motor_vehicle", "motorcar", "vehicle", "access"):
        if tags.get(key, "").lower() in RESTRICTED:
            return False
    if tags.get("area") == "yes" or tags.get("construction"):
        return False
    return True

def speed_kmh(tags, road):
    raw = tags.get("maxspeed", "").lower().strip()
    # Numeric values, optionally followed by mph or km/h. Other values
    # (signals, national, variable, multiple limits) use conservative defaults.
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(mph|km/h|kph|kmh)?", raw)
    if m:
        number = float(m.group(1))
        if m.group(2) == "mph":
            number *= 1.609344
        if 0 < number <= 160:
            return round(number, 3), True
    return float(DEFAULT_SPEED[road]), False

def direction(tags, road):
    raw = tags.get("oneway", "").lower()
    if raw in {"yes", "true", "1"}: return 1
    if raw == "-1": return -1
    if raw in {"no", "false", "0"}: return 0
    if raw in {"reversible", "alternating"}: return None  # ambiguous; exclude
    if tags.get("junction", "").lower() in {"roundabout", "circular"}:
        return 1
    if road in {"motorway", "motorway_link"}:
        return 1
    return 0

def haversine(lon1, lat1, lon2, lat2):
    rad = math.pi / 180
    lat1, lat2 = lat1 * rad, lat2 * rad
    dl = (lon2 - lon1) * rad
    da = lat2 - lat1
    a = math.sin(da/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2
    return 2 * 6371008.8 * math.asin(min(1, math.sqrt(a)))

def xml(s):
    return escape(str(s), {'"': '&quot;'})

class CollectWays(osmium.SimpleHandler):
    def __init__(self, no_service):
        super().__init__()
        self.no_service = no_service
        self.ways = []
        self.usage = Counter()
        self.stats = Counter()
    def way(self, way):
        tags = {t.k: t.v for t in way.tags}
        if not allowed(tags, self.no_service):
            return
        road = tags["highway"]
        d = direction(tags, road)
        if d is None:
            self.stats["excluded_variable_direction"] += 1
            return
        refs = [n.ref for n in way.nodes]
        if len(refs) < 2: return
        self.ways.append((way.id, refs, tags, road, d))
        self.stats["selected_ways"] += 1
        # Count how many separate ways share each node; never count repeated
        # refs within one way twice.
        self.usage.update(set(refs))

class CollectCoordinates(osmium.SimpleHandler):
    def __init__(self, wanted):
        super().__init__()
        self.wanted = wanted
        self.coords = {}
    def node(self, node):
        if node.id in self.wanted and node.location.valid():
            self.coords[node.id] = (node.location.lon, node.location.lat)

def convert(pbf, dest, no_service=False):
    collector = CollectWays(no_service)
    collector.apply_file(str(pbf))
    wanted = set(collector.usage)
    coords = CollectCoordinates(wanted)
    coords.apply_file(str(pbf))
    dest.parent.mkdir(parents=True, exist_ok=True)
    count_edges = 0
    count_segments = 0
    missing = 0
    default_speeds = 0
    road_counts = Counter()
    # Precompute genuine graph vertices. Intermediate points remain in each
    # edge's LINESTRING geometry, but are not independent GraphML nodes.
    node_ids = set()
    for wid, refs, tags, road, d in collector.ways:
        indices = [i for i, ref in enumerate(refs)
                   if i == 0 or i == len(refs) - 1 or collector.usage[ref] > 1]
        for i0, i1 in zip(indices, indices[1:]):
            seg = refs[i0:i1 + 1]
            if len(seg) < 2 or seg[0] == seg[-1]:
                continue
            if any(nid not in coords.coords for nid in seg):
                continue
            length = sum(haversine(*coords.coords[a], *coords.coords[b])
                         for a, b in zip(seg, seg[1:]))
            if length <= 0:
                continue
            node_ids.add(seg[0])
            node_ids.add(seg[-1])
    # Text streaming, no ET in-memory build. Output conforms to the project
    # loader's key mapping for x, y, length, speed_kph, highway, geometry.
    with dest.open('w', encoding='utf-8', newline='\n') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n')
        for key, kind, typ in [('x','node','double'),('y','node','double'),
                               ('length','edge','double'),('speed_kph','edge','double'),
                               ('highway','edge','string'),('geometry','edge','string'),
                               ('name','edge','string'),('toll','edge','string')]:
            f.write(f'<key id="{key}" for="{kind}" attr.name="{key}" attr.type="{typ}"/>\n')
        f.write('<graph edgedefault="directed">\n')
        for nid in sorted(node_ids):
            lon, lat = coords.coords[nid]
            f.write(f'<node id="{nid}"><data key="x">{lon}</data><data key="y">{lat}</data></node>\n')
        for wid, refs, tags, road, d in collector.ways:
            speed, explicit = speed_kmh(tags, road)
            if not explicit: default_speeds += 1
            road_counts[road] += 1
            # Split ways at shared nodes, with endpoints always intersections.
            indices = [i for i, ref in enumerate(refs) if i == 0 or i == len(refs)-1 or collector.usage[ref] > 1]
            for i0, i1 in zip(indices, indices[1:]):
                seg = refs[i0:i1+1]
                if any(nid not in coords.coords for nid in seg):
                    missing += 1
                    continue
                if seg[0] == seg[-1] or len(seg) < 2: continue
                length = sum(haversine(*coords.coords[a], *coords.coords[b]) for a,b in zip(seg, seg[1:]))
                if length <= 0: continue
                count_segments += 1
                directed = [(seg, 0)] if d == 1 else [(list(reversed(seg)), 0)] if d == -1 else [(seg, 0), (list(reversed(seg)), 1)]
                for oriented, rev in directed:
                    geom = 'LINESTRING (' + ', '.join(f'{coords.coords[n][0]} {coords.coords[n][1]}' for n in oriented) + ')'
                    f.write(f'<edge id="{count_edges}" source="{oriented[0]}" target="{oriented[-1]}">')
                    for k, v in [('length', f'{length:.3f}'), ('speed_kph', speed),
                                 ('highway', road), ('geometry',geom),
                                 ('name',tags.get('name','')), ('toll', tags.get('toll','no'))]:
                        f.write(f'<data key="{k}">{xml(v)}</data>')
                    f.write('</edge>\n')
                    count_edges += 1
                    node_ids.update((oriented[0], oriented[-1]))
        f.write('</graph></graphml>\n')
    summary = {
        'input':str(pbf), 'output':str(dest), 'selected_ways':collector.stats['selected_ways'],
        'node_elements_written':len(node_ids), 'routing_nodes_used':len(node_ids),
        'shape_points_kept_only_in_geometry':len(coords.coords)-len(node_ids),
        'physical_segments':count_segments, 'directed_edges':count_edges,
        'segments_skipped_missing_node': missing, 'ways_using_default_speed':default_speeds,
        'variable_direction_ways_excluded':collector.stats['excluded_variable_direction'],
        'road_type_ways':dict(road_counts),
        'warnings':['OSM relation-based turn restrictions are NOT enforced.',
                    'Access and speed are simplified; conditional and lane-specific restrictions are not modeled.',
                    'Shape-only nodes are omitted from GraphML nodes but retained within edge geometries.']
    }
    output_stats = dest.with_suffix('.summary.json')
    output_stats.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    print('Saved:', dest, 'and', output_stats)

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('pbf', type=Path)
    ap.add_argument('graphml', type=Path)
    ap.add_argument('--without-service', action='store_true')
    args = ap.parse_args()
    if not args.pbf.is_file(): ap.error('PBF file not found: '+str(args.pbf))
    convert(args.pbf, args.graphml, args.without_service)
