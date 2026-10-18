/* Leaflet implementation of the Tkinter prototype's draw/replay/contractions/drive flow. */
const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([30.506, 114.406], 14);
map.createPane('roadNetworkPane');
map.getPane('roadNetworkPane').style.zIndex = 390;
map.getPane('roadNetworkPane').style.pointerEvents = 'none';
const roadRenderer = L.svg({ padding: 0.5, pane: 'roadNetworkPane' });
const basemapLayers = {
  osmde: L.tileLayer('https://{s}.tile.openstreetmap.de/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }),
  esri: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles &copy; Esri'
  }),
  osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }),
  hot: L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors, Tiles style by HOT'
  }),
  baidu: L.tileLayer('https://maponline{s}.bdimg.com/tile/?qt=tile&x={x}&y={y}&z={z}&styles=pl&scaler=1', {
    subdomains: ['0', '1', '2', '3'],
    maxZoom: 19,
    attribution: '&copy; 百度地图'
  })
};
let activeBasemap = 'osmde';
basemapLayers[activeBasemap].addTo(map);
L.control.scale({ position: 'bottomleft', imperial: false, metric: true, maxWidth: 120 }).addTo(map);

// 路网不再内置演示数据，统一由 OSM 加载。
const nodes = {};

const roads = [];
const routeIds = [];
const routeProfiles = {};
const trafficRoadIndex = -1;
const contractionNodes = [];
const layers = { roads: L.layerGroup().addTo(map), annotations: L.layerGroup().addTo(map), route: L.layerGroup().addTo(map), routeMotion: L.layerGroup().addTo(map), search: L.layerGroup().addTo(map), searchEdges: L.layerGroup().addTo(map), searchFrontier: L.layerGroup().addTo(map), contractions: L.layerGroup().addTo(map), endpoints: L.layerGroup().addTo(map), vehicle: L.layerGroup().addTo(map), drawings: L.layerGroup().addTo(map), drawingDraft: L.layerGroup().addTo(map) };
let startKey = null;
let endKey = null;
let activeRoute = [];
let activeRouteEdges = [];
let busy = false;
let animationToken = 0;
let clickSelectStart = true;
let trafficOn = false;
let vehicleMarker = null;
let activeSidebarPage = 'navigation';
let drawingMode = null;
let drawingPoints = [];
let drawingPreviewPoint = null;
let drawingGesture = false;
let drawingHistory = [];
let nextDrawingNodeId = 1;
const drawingNodeLayers = new Map();
const nodeTags = new Map();
const navWaypointKeys = [];
const avoidAreaLayers = new Set();
let selectedDrawingLayer = null;
let leftPanelCollapsed = false;
let rightPanelCollapsed = false;
let lastSearchStats = { expanded: 0, elapsed: 0 };
let routeHistory = [];
let routeSequence = 0;
let activeRouteHistoryItem = null;
let routeSummaryCollapsed = false;
let navigationPanelOpen = false;
let routeMotionToken = 0;
let osmNetwork = null;
let networkLoading = false;
let networkVisible = true;
let networkContrast = true;
let viewportCoverageTimer = null;
let lastViewportCoverageRequest = '';
let graphCacheNetwork = null;
let graphCache = null;
let heuristicCacheNetwork = null;
let heuristicCacheSignature = '';
let heuristicCacheScale = 0;
const osmNearestCache = new Map();
// 正常模式由本地服务器保存完整武汉路网，浏览器只按区域请求；本地小文件仅作备用。
const OSM_BBOX = '30.496,114.396,30.516,114.416';
const OSM_HIGHWAY_PATTERN = 'motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link';
const OSM_EXPANSION_MAX = { lat: 0.06, lon: 0.08 };
const OSM_ENDPOINTS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'];
const STATIC_NETWORK_URL = 'data/server/wuhan-main-roads.json';
const SERVER_NETWORK_URL = '/api/network';
const OSM_SNAP_MAX_DISTANCE = 650;
const OSM_FALLBACK_SNAP_DISTANCE = 1800;
const OSM_POINT_REQUEST_SPAN = { lat: 0.025, lon: 0.035 };
const endpointSnaps = new Map();
// 保留空数组仅用于兼容旧的隐藏绘图代码，路网加载不会填充任何 POI。
const navigationPois = [];

const $ = (id) => document.getElementById(id);
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const point = (key) => osmNetwork?.nodes[key] || nodes[key];
const latLngs = (ids) => ids.map(id => point(id));
const setText = (id, value) => { const element = $(id); if (element) element.textContent = value; };
const setFieldValue = (id, value) => { $(id).value = value; };
const ROUTE_HISTORY_LIMIT = 8;
const skinDefinitions = {
  flower: { label: '樱花青柠' },
  sky: { label: '晴空云朵' },
  night: { label: '深海蓝蝶' },
  bluegray: { label: '雾蓝书页' },
  blackwhite: { label: '黑白极简' }
};
function refreshMapSize() { map.invalidateSize({ pan: false, debounceMoveend: true }); }
window.addEventListener('resize', refreshMapSize);
const EARTH_RADIUS_M = 6371008.8;
const ROAD_GRID_SIZE = 0.01;

function geographicDistance(a, b) {
  const lat1 = a[0] * Math.PI / 180;
  const lat2 = b[0] * Math.PI / 180;
  const deltaLat = (b[0] - a[0]) * Math.PI / 180;
  const deltaLng = (b[1] - a[1]) * Math.PI / 180;
  const haversine = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
}

function osmKey(id) { return `osm:${id}`; }

function geometryNodeKey(lat, lon) {
  return `osm:coord:${Number(lat).toFixed(6)},${Number(lon).toFixed(6)}`;
}

function nearestOsmNode(coords) {
  if (!osmNetwork || !coords) return null;
  const cacheKey = `${coords[0].toFixed(5)},${coords[1].toFixed(5)}`;
  if (osmNearestCache.has(cacheKey)) return osmNearestCache.get(cacheKey);
  let nearest = null;
  let nearestDistance = Infinity;
  const candidateEntries = osmNetwork.roadNodeKeys ? [...osmNetwork.roadNodeKeys].map((key) => [key, osmNetwork.nodes[key]]) : Object.entries(osmNetwork.nodes);
  candidateEntries.forEach(([key, candidate]) => {
    const distance = geographicDistance(coords, candidate);
    if (distance < nearestDistance) {
      nearest = key;
      nearestDistance = distance;
    }
  });
  osmNearestCache.set(cacheKey, nearest);
  return nearest;
}

function projectToSegment(coords, a, b) {
  const latitudeScale = Math.cos(coords[0] * Math.PI / 180);
  const x = (coords[1] - a[1]) * latitudeScale;
  const y = coords[0] - a[0];
  const bx = (b[1] - a[1]) * latitudeScale;
  const by = b[0] - a[0];
  const denominator = bx * bx + by * by;
  const ratio = denominator ? Math.max(0, Math.min(1, (x * bx + y * by) / denominator)) : 0;
  const projected = [a[0] + by * ratio, a[1] + (bx * ratio) / latitudeScale];
  return { projected, ratio, distance: geographicDistance(coords, projected) };
}

function roadGridKey(latIndex, lonIndex) {
  return `${latIndex}:${lonIndex}`;
}

function buildRoadSpatialIndex(network) {
  network.roadGrid = new Map();
  network.roads.forEach((road) => {
    const a = network.nodes[road.from];
    const b = network.nodes[road.to];
    const minLat = Math.floor(Math.min(a[0], b[0]) / ROAD_GRID_SIZE);
    const maxLat = Math.floor(Math.max(a[0], b[0]) / ROAD_GRID_SIZE);
    const minLon = Math.floor(Math.min(a[1], b[1]) / ROAD_GRID_SIZE);
    const maxLon = Math.floor(Math.max(a[1], b[1]) / ROAD_GRID_SIZE);
    for (let latIndex = minLat; latIndex <= maxLat; latIndex += 1) {
      for (let lonIndex = minLon; lonIndex <= maxLon; lonIndex += 1) {
        const key = roadGridKey(latIndex, lonIndex);
        if (!network.roadGrid.has(key)) network.roadGrid.set(key, []);
        network.roadGrid.get(key).push(road);
      }
    }
  });
}

function matchPointToRoad(coords, network) {
  let best = null;
  const latIndex = Math.floor(coords[0] / ROAD_GRID_SIZE);
  const lonIndex = Math.floor(coords[1] / ROAD_GRID_SIZE);
  const candidates = new Set();
  for (let radius = 0; radius <= 2; radius += 1) {
    for (let latOffset = -radius; latOffset <= radius; latOffset += 1) {
      for (let lonOffset = -radius; lonOffset <= radius; lonOffset += 1) {
        (network.roadGrid.get(roadGridKey(latIndex + latOffset, lonIndex + lonOffset)) || []).forEach((road) => candidates.add(road));
      }
    }
    if (candidates.size) break;
  }
  const candidateRoads = candidates.size ? [...candidates] : network.roads;
  candidateRoads.forEach((road) => {
    const projection = projectToSegment(coords, network.nodes[road.from], network.nodes[road.to]);
    if (!best || projection.distance < best.distance) {
      best = { road, ...projection };
    }
  });
  // 网格索引只用于缩小第一次搜索范围；如果结果仍较远，再完整检查一次，
  // 避免用户点击在网格边界附近时误判为“超出距离”。
  if (candidates.size && best && best.distance > OSM_SNAP_MAX_DISTANCE) {
    network.roads.forEach((road) => {
      if (candidates.has(road)) return;
      const projection = projectToSegment(coords, network.nodes[road.from], network.nodes[road.to]);
      if (projection.distance < best.distance) best = { road, ...projection };
    });
  }
  return best;
}

function snapEndpointToNode(kind, coords) {
  if (!osmNetwork || !coords) return null;
  const match = matchPointToRoad(coords, osmNetwork);
  if (!match) return null;
  const fromDistance = geographicDistance(coords, osmNetwork.nodes[match.road.from]);
  const toDistance = geographicDistance(coords, osmNetwork.nodes[match.road.to]);
  const key = fromDistance <= toDistance ? match.road.from : match.road.to;
  endpointSnaps.delete(kind);
  return key;
}

function parseOsmNetwork(elements) {
  const parsedNodes = {};
  const ways = [];
  elements.forEach((element) => {
    if (element.type === 'node' && Number.isFinite(element.lat) && Number.isFinite(element.lon)) {
      parsedNodes[osmKey(element.id)] = [element.lat, element.lon];
    } else if (element.type === 'way' && element.tags?.highway && (Array.isArray(element.geometry) || Array.isArray(element.nodes))) {
      ways.push(element);
    }
  });
  const parsedRoads = [];
  ways.forEach((way) => {
    const highway = way.tags.highway;
    const oneWayValue = String(way.tags.oneway || '').toLowerCase();
    const oneWay = ['yes', 'true', '1', 'alternating', '-1'].includes(oneWayValue);
    const reverseWay = oneWayValue === '-1';
    const geometry = Array.isArray(way.geometry) ? way.geometry : [];
    const hasGeometry = geometry.length > 0;
    const rawPoints = geometry.length
      ? geometry.map((item) => ({ lat: Number(item.lat), lon: Number(item.lon) }))
      : way.nodes.map((id) => ({ lat: parsedNodes[osmKey(id)]?.[0], lon: parsedNodes[osmKey(id)]?.[1] })).filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon));
    const rawKeys = hasGeometry && Array.isArray(way.nodes) && way.nodes.length === rawPoints.length
      ? way.nodes.map((id) => osmKey(id))
      : rawPoints.map((item) => geometryNodeKey(item.lat, item.lon));
    for (let index = 0; index < rawPoints.length - 1; index += 1) {
      const rawFrom = rawKeys[index];
      const rawTo = rawKeys[index + 1];
      const from = reverseWay ? rawTo : rawFrom;
      const to = reverseWay ? rawFrom : rawTo;
      parsedNodes[rawFrom] = [rawPoints[index].lat, rawPoints[index].lon];
      parsedNodes[rawTo] = [rawPoints[index + 1].lat, rawPoints[index + 1].lon];
      if (!parsedNodes[from] || !parsedNodes[to]) continue;
      parsedRoads.push({
        from,
        to,
        highway,
        oneWay,
        edgeId: `osm:way:${way.id}:${index}`,
        name: way.tags.name || 'OSM 道路',
        distance: geographicDistance(parsedNodes[from], parsedNodes[to])
      });
    }
  });
  const network = { nodes: parsedNodes, roads: parsedRoads, renderRoads: parsedRoads };
  network.roadNodeKeys = new Set(parsedRoads.flatMap((road) => [road.from, road.to]));
  network.roadNames = new Map();
  parsedRoads.forEach((road) => {
    network.roadNames.set(`${road.from}>${road.to}`, road.name);
    if (!road.oneWay) network.roadNames.set(`${road.to}>${road.from}`, road.name);
  });
  buildRoadSpatialIndex(network);
  return network;
}

function installOsmNetwork(parsed, sourceLabel, { preserveEndpoints = false, fit = true } = {}) {
  if (preserveEndpoints && osmNetwork) parsed = mergeOsmNetworks(osmNetwork, parsed);
  osmNetwork = parsed;
  graphCacheNetwork = null;
  graphCache = null;
  heuristicCacheNetwork = null;
  heuristicCacheSignature = '';
  endpointSnaps.clear();
  if (!preserveEndpoints) {
    startKey = null;
    endKey = null;
    clickSelectStart = true;
    navWaypointKeys.length = 0;
    setFieldValue('startNode', '');
    setFieldValue('endNode', '');
  } else {
    clickSelectStart = !startKey;
  }
  osmNearestCache.clear();
  layers.search.clearLayers(); layers.searchEdges.clearLayers(); layers.searchFrontier.clearLayers();
  activeRoute = [];
  activeRouteEdges = [];
  draw();
  updateMetrics(false);
  document.querySelector('.workspace')?.classList.add('network-ready');
  document.querySelector('.workspace')?.classList.remove('route-planned');
  setText('networkStatus', `${sourceLabel} · ${parsed.roads.length.toLocaleString()} 段道路`);
  setStatus(`${sourceLabel} · 共 ${parsed.roads.length.toLocaleString()} 段道路`, 'ready');
  updateNavStopSummary();
  if (fit && parsed.roads.length) map.fitBounds(L.latLngBounds(parsed.renderRoads.slice(0, 3000).flatMap((road) => [point(road.from), point(road.to)])), { padding: [55, 55], maxZoom: 14, animate: true });
}

function validateOsmNetwork(parsed) {
  if (Object.keys(parsed.nodes).length < 20 || parsed.roads.length < 20) throw new Error('OSM 主要道路数据为空');
  return parsed;
}

function mergeOsmNetworks(base, addition) {
  const nodes = { ...base.nodes, ...addition.nodes };
  const roadsById = new Map();
  [...base.roads, ...addition.roads].forEach((road, index) => {
    const key = road.edgeId || `${road.from}>${road.to}|${road.name || ''}|${road.distance || 0}`;
    if (!roadsById.has(key)) roadsById.set(key, { ...road, edgeId: road.edgeId || `merged:${index}:${key}` });
  });
  const roads = [...roadsById.values()].filter((road) => nodes[road.from] && nodes[road.to]);
  const merged = { nodes, roads, renderRoads: roads };
  merged.roadNodeKeys = new Set(roads.flatMap((road) => [road.from, road.to]));
  merged.roadNames = new Map();
  roads.forEach((road) => {
    merged.roadNames.set(`${road.from}>${road.to}`, road.name);
    if (!road.oneWay) merged.roadNames.set(`${road.to}>${road.from}`, road.name);
  });
  buildRoadSpatialIndex(merged);
  return merged;
}

function syncNetworkDisplay() {
  const mapContainer = map.getContainer();
  // 底图压暗是独立的显示设置，不应等路网加载完成后才生效。
  mapContainer.classList.toggle('network-focus', Boolean(networkVisible && networkContrast));
  const visibilityControl = $('networkVisibility');
  const contrastControl = $('networkContrast');
  if (visibilityControl) visibilityControl.checked = networkVisible;
  if (contrastControl) contrastControl.checked = networkContrast;
}

function installNetworkPayload(payload, sourceLabel, options = {}) {
  installOsmNetwork(validateOsmNetwork(parseOsmNetwork(payload.elements || [])), sourceLabel, options);
}

async function loadNetworkFile(file) {
  if (!file) return;
  setText('networkStatus', `正在读取 ${file.name}…`);
  setStatus('正在读取本地 OSM 路网文件…', 'live');
  try {
    installNetworkPayload(JSON.parse(await file.text()), '本地 OSM');
  } catch (error) {
    setText('networkStatus', 'OSM 路网未加载 · 文件格式错误');
    setStatus(`本地路网读取失败 · ${error.message}`, 'ready');
  }
}

function buildOsmQuery(bbox) {
  return `[out:json][timeout:45];way["highway"~"^(${OSM_HIGHWAY_PATTERN})$"](${bbox});out body geom;`;
}

function currentExpansionBbox() {
  const bounds = map.getBounds();
  const center = map.getCenter();
  const visibleLatSpan = bounds.getNorth() - bounds.getSouth();
  const visibleLonSpan = bounds.getEast() - bounds.getWest();
  const latSpan = Math.min(Math.max(visibleLatSpan * 1.15, 0.03), OSM_EXPANSION_MAX.lat);
  const lonSpan = Math.min(Math.max(visibleLonSpan * 1.15, 0.04), OSM_EXPANSION_MAX.lon);
  const south = center.lat - latSpan / 2;
  const west = center.lng - lonSpan / 2;
  const north = center.lat + latSpan / 2;
  const east = center.lng + lonSpan / 2;
  return [south, west, north, east].map((value) => value.toFixed(5)).join(',');
}

async function fetchOsmPayload(bbox, { allowOverpass = true } = {}) {
  // The local server is the normal path. It reads the complete Wuhan extract
  // from disk and returns only the requested bbox to keep browser rendering fast.
  let serverError = null;
  if (window.location.protocol !== 'file:') {
    try {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(`${SERVER_NETWORK_URL}?bbox=${encodeURIComponent(bbox)}`, { cache: 'no-store', signal: controller.signal, headers: { Accept: 'application/json' } });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.error || `服务器 HTTP ${response.status}`);
        }
        const payload = await response.json();
        if (!Array.isArray(payload.elements) || payload.elements.length < 20) throw new Error('服务器当前区域没有足够路网');
        return payload;
      } finally {
        window.clearTimeout(timeout);
      }
    } catch (error) {
      serverError = error;
      console.warn('服务器路网请求失败:', error);
    }
  }
  if (!allowOverpass) throw serverError || new Error('服务器路网服务不可用');
  const query = buildOsmQuery(bbox);
  let lastError = null;
  for (const endpoint of OSM_ENDPOINTS) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 45000);
    try {
      const response = await fetch(`${endpoint}?data=${encodeURIComponent(query)}`, { signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
    } finally {
      window.clearTimeout(timeout);
    }
  }
  throw lastError || new Error('路网服务不可用');
}

function pointExpansionBbox(coords) {
  const latSpan = OSM_POINT_REQUEST_SPAN.lat;
  const lonSpan = OSM_POINT_REQUEST_SPAN.lon;
  const south = coords[0] - latSpan / 2;
  const west = coords[1] - lonSpan / 2;
  const north = coords[0] + latSpan / 2;
  const east = coords[1] + lonSpan / 2;
  return [south, west, north, east].map((value) => value.toFixed(5)).join(',');
}

function hasNearbyRoad(coords) {
  if (!osmNetwork) return false;
  const match = matchPointToRoad(coords, osmNetwork);
  return Boolean(match && match.distance <= OSM_SNAP_MAX_DISTANCE);
}

async function ensureOsmCoverage(latlng) {
  const coords = [latlng.lat, latlng.lng];
  if (hasNearbyRoad(coords)) return true;
  if (networkLoading) {
    setStatus('路网数据正在准备，请稍候再选择位置', 'live');
    return false;
  }
  if (window.location.protocol === 'file:') {
    setStatus('当前页面无法自动请求路网，请使用本地服务器打开', 'ready');
    return false;
  }
  networkLoading = true;
  const bbox = pointExpansionBbox(coords);
  setText('networkStatus', '正在从服务器读取选点附近道路…');
  setStatus('正在从服务器读取选点附近 OSM 道路…', 'live');
  try {
    const payload = await fetchOsmPayload(bbox);
    installNetworkPayload(payload, '服务器 OSM', { preserveEndpoints: Boolean(osmNetwork), fit: false });
    const match = matchPointToRoad(coords, osmNetwork);
    if (!match || match.distance > OSM_FALLBACK_SNAP_DISTANCE) throw new Error('选点附近没有可用的主要道路');
    setText('networkStatus', '服务器路网已按选点补充');
    setStatus(match.distance <= OSM_SNAP_MAX_DISTANCE ? '已从服务器补充选点附近路网' : '附近主要道路较远，已吸附到最近道路', 'ready');
    return true;
  } catch (error) {
    const reason = error.name === 'AbortError' ? '请求超时' : error.message || '服务暂不可用';
    setText('networkStatus', '自动补充失败 · 可重新点击地图');
    setStatus(`附近路网请求失败 · ${reason}`, 'ready');
    return false;
  } finally {
    networkLoading = false;
  }
}

async function ensureViewportCoverage() {
  if (!osmNetwork || networkLoading || window.location.protocol === 'file:') return;
  const center = map.getCenter();
  if (hasNearbyRoad([center.lat, center.lng])) return;
  const bbox = currentExpansionBbox();
  if (!bbox || bbox === lastViewportCoverageRequest) return;
  lastViewportCoverageRequest = bbox;
  networkLoading = true;
  setStatus('正在从服务器准备当前地图区域的 OSM 道路…', 'live');
  try {
    const payload = await fetchOsmPayload(bbox);
    installNetworkPayload(payload, '服务器当前区域 OSM', { preserveEndpoints: Boolean(osmNetwork), fit: false });
    setStatus('当前地图区域道路已准备完成，可直接选点', 'ready');
  } catch (error) {
    lastViewportCoverageRequest = '';
    const reason = error.name === 'AbortError' ? '请求超时' : error.message || '服务暂不可用';
    setStatus(`当前区域道路准备失败 · ${reason}`, 'ready');
  } finally {
    networkLoading = false;
  }
}

function scheduleViewportCoverage() {
  if (viewportCoverageTimer) window.clearTimeout(viewportCoverageTimer);
  viewportCoverageTimer = window.setTimeout(() => {
    viewportCoverageTimer = null;
    ensureViewportCoverage();
  }, 650);
}

function routeExpansionBbox() {
  const start = point(startKey);
  const end = point(endKey);
  if (!start || !end) return null;
  const margin = 0.015;
  const south = Math.min(start[0], end[0]) - margin;
  const west = Math.min(start[1], end[1]) - margin;
  const north = Math.max(start[0], end[0]) + margin;
  const east = Math.max(start[1], end[1]) + margin;
  // 起点和终点必须都落在请求范围内；小范围时使用固定最小边界，
  // 远距离规划则保留完整包络，避免裁掉其中一个端点。
  const latSpan = Math.max(north - south, 0.02);
  const lonSpan = Math.max(east - west, 0.03);
  return [
    Math.min(south, (south + north) / 2 - latSpan / 2),
    Math.min(west, (west + east) / 2 - lonSpan / 2),
    Math.max(north, (south + north) / 2 + latSpan / 2),
    Math.max(east, (west + east) / 2 + lonSpan / 2)
  ].map((value) => value.toFixed(5)).join(',');
}

async function ensureRouteCoverage() {
  if (!osmNetwork || !startKey || !endKey || window.location.protocol === 'file:') return false;
  const requestKey = `${startKey}>${endKey}|${navWaypointKeys.join(',')}`;
  if (ensureRouteCoverage.lastRequest === requestKey) return false;
  ensureRouteCoverage.lastRequest = requestKey;
  while (networkLoading) await delay(80);
  networkLoading = true;
  const bbox = routeExpansionBbox();
  if (!bbox) {
    networkLoading = false;
    return false;
  }
  setStatus('当前区域道路不连通，正在从服务器补充起终点之间的路网…', 'live');
  try {
    const payload = await fetchOsmPayload(bbox);
    installNetworkPayload(payload, '服务器路线区域 OSM', { preserveEndpoints: true, fit: false });
    setStatus('路网已补充，正在重新计算路线…', 'live');
    return true;
  } catch (error) {
    const reason = error.name === 'AbortError' ? '请求超时' : error.message || '服务暂不可用';
    setStatus(`路线区域补充失败 · ${reason}`, 'ready');
    return false;
  } finally {
    networkLoading = false;
  }
}

async function loadOsmNetwork({ interactive = true } = {}) {
  if (networkLoading) return;
  networkLoading = true;
  setText('networkStatus', '正在加载服务器武汉 OSM 缓存…');
  setStatus('正在从服务器读取武汉路网…', 'live');
  if (window.location.protocol === 'file:') {
    setText('networkStatus', '请使用本地服务器打开页面');
    setStatus('当前是 file:// 模式，请双击 start-server.bat 后访问 http://localhost:5173/', 'ready');
    if (interactive) $('networkFileInput')?.click();
    networkLoading = false;
    return;
  }
  try {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    try {
      const payload = await fetchOsmPayload(currentExpansionBbox(), { allowOverpass: false });
      installNetworkPayload(payload, '服务器武汉 OSM');
    } finally {
      window.clearTimeout(timeout);
    }
  } catch (localError) {
    try {
      const localController = new AbortController();
      const localTimeout = window.setTimeout(() => localController.abort(), 30000);
      setText('networkStatus', '正在读取静态武汉 OSM 路网…');
      setStatus('服务器接口不可用，正在读取项目内完整武汉路网（首次可能较慢）…', 'live');
      const response = await fetch(STATIC_NETWORK_URL, { cache: 'no-store', signal: localController.signal, headers: { Accept: 'application/json' } });
      window.clearTimeout(localTimeout);
      if (!response.ok) throw new Error(`静态路网 HTTP ${response.status}`);
      installNetworkPayload(await response.json(), '项目内武汉 OSM');
    } catch (error) {
      try {
        const payload = await fetchOsmPayload(currentExpansionBbox());
        installNetworkPayload(payload, '在线 OSM');
      } catch (overpassError) {
        setText('networkStatus', 'OSM 路网未加载 · 可重试');
        const reason = overpassError.name === 'AbortError' ? '请求超时' : overpassError.message || error.message || localError.message;
        setStatus(`OSM 数据暂不可用 · ${reason}，请重试或检查网络`, 'ready');
      }
    }
  } finally {
    networkLoading = false;
  }
}

async function extendOsmNetwork() {
  if (networkLoading) return;
  if (window.location.protocol === 'file:') {
    setStatus('扩展路网需要通过本地服务器打开页面，不能直接使用 file:// 请求', 'ready');
    return;
  }
  networkLoading = true;
  const button = $('extendNetworkBtn');
  if (button) button.disabled = true;
  const bbox = currentExpansionBbox();
  setText('networkStatus', `正在请求当前区域主要道路 · ${bbox}`);
  setStatus('正在从服务器读取并合并当前地图区域的主要道路…', 'live');
  try {
    const payload = await fetchOsmPayload(bbox);
    installNetworkPayload(payload, '在线扩展 OSM', { preserveEndpoints: Boolean(osmNetwork), fit: false });
    setText('networkStatus', `已合并当前区域 · ${osmNetwork.roads.length.toLocaleString()} 段道路`);
    setStatus(`路网已扩展 · 当前共 ${osmNetwork.roads.length.toLocaleString()} 段主要道路`, 'ready');
  } catch (error) {
    const reason = error.name === 'AbortError' ? '请求超时' : error.message;
    setText('networkStatus', '扩展失败 · 可重试');
    setStatus(`扩展 OSM 路网失败 · ${reason}`, 'ready');
  } finally {
    networkLoading = false;
    if (button) button.disabled = false;
  }
}

function routeSegmentDistances(ids) {
  return ids.slice(0, -1).map((id, index) => activeRouteEdges[index]?.distance ?? geographicDistance(point(id), point(ids[index + 1])));
}

function routeDistance(ids) { return routeSegmentDistances(ids).reduce((total, distance) => total + distance, 0); }

function routeSegmentLabel(from, to, edge) {
  if (edge?.name) return edge.name;
  const roadName = osmNetwork?.roadNames?.get(`${from}>${to}`);
  return roadName || 'OSM 道路';
}

function midpoint(a, b) { return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; }

function directionAngle(a, b) {
  // CSS 的 0deg 指向屏幕右侧，先把经纬度方向换成 Leaflet 屏幕方向再旋转箭头。
  const screenX = (b[1] - a[1]) * Math.cos(((a[0] + b[0]) / 2) * Math.PI / 180);
  const screenY = -(b[0] - a[0]);
  return Math.atan2(screenY, screenX) * 180 / Math.PI;
}

function buildRouteWithEndpoints(profile) {
  if (!startKey || !endKey) return [];
  const interior = navWaypointKeys.filter((key, index, values) => key !== startKey && key !== endKey && values.indexOf(key) === index);
  return [startKey, ...interior, endKey];
}

function formatNodeId(key) {
  if (String(key).startsWith('osm:')) return `OSM-${String(key).slice(4)}`;
  return key.replace(/^([A-Z]+)(\d+)$/, (_, prefix, digits) => `${prefix}-${digits.padStart(2, '0')}`);
}

function nodeLabel(key) {
  return formatNodeId(key);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]);
}

function updateNavStopSummary() {
  const viaLabels = navWaypointKeys.map((key) => `${drawingNodeLayers.get(key)?.__drawingLabel || nodeLabel(key)}（${formatNodeId(key)}）`);
  const endpointLabels = [
    startKey ? `起点：${drawingNodeLayers.get(startKey)?.__drawingLabel || nodeLabel(startKey)}` : '',
    endKey ? `终点：${drawingNodeLayers.get(endKey)?.__drawingLabel || nodeLabel(endKey)}` : ''
  ].filter(Boolean);
  if (!viaLabels.length && !endpointLabels.length) {
    setText('navStopSummary', '点击地图设置起点，再次点击设置终点。端点会自动吸附到最近道路节点。');
    return;
  }
  const parts = [];
  if (endpointLabels.length) parts.push(endpointLabels.join('；'));
  if (viaLabels.length) parts.push(`途经点：${viaLabels.join('、')}`);
  setText('navStopSummary', parts.join(' | '));
}

function iconFor(kind, label) {
  return L.divIcon({ className: `node-marker ${kind}`, html: `<span>${label}</span>`, iconSize: [27, 27], iconAnchor: [13.5, 13.5] });
}

function nodeTagState(key) {
  return nodeTags.get(key) || { scenic: false, charging: false };
}

function nodeTagLabel(key) {
  const tags = nodeTagState(key);
  if (tags.scenic && tags.charging) return '景充';
  if (tags.scenic) return '景';
  if (tags.charging) return '充';
  return 'N';
}

function nodeTagDescription(key) {
  const tags = nodeTagState(key);
  if (tags.scenic && tags.charging) return '风景 + 充电节点';
  if (tags.scenic) return '风景节点';
  if (tags.charging) return '充电节点';
  return '普通导航节点';
}

function nodeTagIcon(key) {
  const tags = nodeTagState(key);
  const tone = tags.scenic && tags.charging ? '#a56c40' : tags.scenic ? '#6c8b4f' : '#4384a2';
  return L.divIcon({ className: 'node-type-marker', html: `<span style="--node-type-color:${tone}">${nodeTagLabel(key)}</span>`, iconSize: [23, 23], iconAnchor: [11.5, 11.5] });
}

function drawTaggedBaseNodes() {
  layers.nodeTypes.clearLayers();
  nodeTags.forEach((tags, key) => {
    if ((!tags.scenic && !tags.charging) || drawingNodeLayers.has(key) || !nodes[key]) return;
    L.marker(nodes[key], { icon: nodeTagIcon(key), interactive: false, title: nodeTagDescription(key) }).bindTooltip(`${formatNodeId(key)} · ${nodeTagDescription(key)}`, { direction: 'top', offset: [0, -9] }).addTo(layers.nodeTypes);
  });
}

function renderableRoads() {
  if (osmNetwork) return osmNetwork.renderRoads.map((road, index) => ({ ...road, index, highway: ['motorway', 'trunk', 'primary'].includes(road.highway) }));
  return roads.map(([from, to, highway, oneWay], index) => ({ from, to, highway, oneWay, index }));
}

function displayableRoads() {
  // OSM 路网只用于建图和计算，不作为底图图层绘制；最终路线由 route 图层单独绘制。
  return [];
}

function draw() {
  routeMotionToken += 1;
  layers.roads.clearLayers();
  layers.annotations.clearLayers();
  layers.route.clearLayers();
  layers.routeMotion.clearLayers();
  layers.endpoints.clearLayers();
  syncNetworkDisplay();
  displayableRoads().forEach(({ from: a, to: b, highway, oneWay, index, name }) => {
    const isTraffic = !osmNetwork && trafficOn && index === trafficRoadIndex;
    const focusRoad = Boolean(osmNetwork && networkContrast);
    const coreColor = isTraffic ? '#ff765d' : focusRoad ? (highway ? '#8cf2df' : '#d7fff0') : highway ? '#99b9b8' : '#d0dcda';
    const coreWeight = isTraffic ? 5 : highway ? (focusRoad ? 5 : 4) : (focusRoad ? 3 : 2);
    const lineOptions = { color: coreColor, weight: coreWeight, opacity: osmNetwork ? (focusRoad ? .98 : .72) : .95, interactive: !osmNetwork, pane: osmNetwork ? 'roadNetworkPane' : undefined, renderer: osmNetwork ? roadRenderer : undefined, lineCap: 'round', lineJoin: 'round' };
    if (focusRoad) {
      L.polyline([point(a), point(b)], { ...lineOptions, color: '#18343b', weight: coreWeight + 4, opacity: .92 }).addTo(layers.roads);
    }
    const line = L.polyline([point(a), point(b)], lineOptions).addTo(layers.roads);
    if (!osmNetwork || highway || oneWay) line.bindTooltip(isTraffic ? '拥堵路段 · 速度下降' : name || (oneWay ? '单向道 · 仅按箭头方向通行' : '普通道路'), { sticky: true, className: isTraffic ? 'traffic-tooltip' : 'road-tooltip' });
    if (oneWay && !osmNetwork) {
      const angle = directionAngle(point(a), point(b));
      L.marker(midpoint(point(a), point(b)), { icon: L.divIcon({ className: 'one-way-marker', html: `<span style="transform:rotate(${angle}deg)">➜</span>`, iconSize: [22, 22], iconAnchor: [11, 11] }), interactive: false, title: '单向道' }).addTo(layers.annotations);
    }
    if (isTraffic) {
      L.marker(midpoint(point(a), point(b)), { icon: L.divIcon({ className: 'traffic-marker', html: '<span>拥堵</span>', iconSize: [42, 20], iconAnchor: [21, 10] }), interactive: false, title: '拥堵路段' }).addTo(layers.annotations);
    }
  });
  if (activeRoute.length > 1 && activeRouteEdges.length) {
    L.polyline(latLngs(activeRoute), { color: '#7d302d', weight: 13, opacity: .72, lineCap: 'round', lineJoin: 'round' }).addTo(layers.route);
    L.polyline(latLngs(activeRoute), { color: '#e45f4d', weight: 8, opacity: .98, lineCap: 'round', lineJoin: 'round' }).addTo(layers.route);
    L.polyline(latLngs(activeRoute), { color: '#ffd0a5', weight: 3, opacity: .95, dashArray: '12 10', lineCap: 'round', lineJoin: 'round' }).addTo(layers.route);
    startRouteConveyor(activeRoute);
  }
  if (startKey && point(startKey)) {
    L.marker(point(startKey), { icon: iconFor('start', '起'), draggable: true, title: '拖动起点' }).on('dragend', (event) => moveEndpoint('start', event.target.getLatLng())).addTo(layers.endpoints);
  }
  if (endKey && point(endKey)) {
    L.marker(point(endKey), { icon: iconFor('end', '终'), draggable: true, title: '拖动终点' }).on('dragend', (event) => moveEndpoint('end', event.target.getLatLng())).addTo(layers.endpoints);
  }
}

function startRouteConveyor(ids) {
  routeMotionToken += 1;
  const token = routeMotionToken;
  if (ids.length < 2) return;
  const segmentLengths = routeSegmentDistances(ids);
  const total = segmentLengths.reduce((sum, value) => sum + value, 0);
  const dotCount = Math.min(12, Math.max(6, Math.ceil(total / 140)));
  const dots = Array.from({ length: dotCount }, () => L.circleMarker(point(ids[0]), { radius: 4, color: '#fff8df', weight: 1.5, fillColor: '#fff0a8', fillOpacity: .98, className: 'route-motion-dot', interactive: false }).addTo(layers.routeMotion));
  const locate = (progress) => {
    let distance = ((progress % 1) + 1) % 1 * total;
    for (let index = 0; index < segmentLengths.length; index += 1) {
      if (distance <= segmentLengths[index]) {
        const ratio = segmentLengths[index] ? distance / segmentLengths[index] : 0;
        const a = point(ids[index]);
        const b = point(ids[index + 1]);
        return [a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio];
      }
      distance -= segmentLengths[index];
    }
    return point(ids.at(-1));
  };
  const startedAt = performance.now();
  const animate = (now) => {
    if (token !== routeMotionToken) return;
    const phase = (now - startedAt) / 4200;
    dots.forEach((dot, index) => dot.setLatLng(locate(phase + index / dotCount)));
    window.requestAnimationFrame(animate);
  };
  window.requestAnimationFrame(animate);
}

function refreshDrawingNodeVisual(layer) {
  if (!layer?.__navNodeKey) return;
  const key = layer.__navNodeKey;
  const color = nodeTagState(key).scenic && nodeTagState(key).charging ? '#a56c40' : nodeTagState(key).scenic ? '#6c8b4f' : nodeTagState(key).charging ? '#4384a2' : (layer.__drawingColor || '#e36f50');
  layer.setIcon(L.divIcon({ className: 'draw-poi-marker', html: `<span style="--draw-color:${color}">${nodeTagLabel(key) === 'N' ? 'P' : nodeTagLabel(key)}</span>`, iconSize: [18, 18], iconAnchor: [9, 9] }));
}

function updateNodeManagementControls() {
  const select = $('nodeManageSelect');
  if (!select) return;
  const key = select.value;
  const tags = nodeTagState(key);
  $('scenicNodeBtn').classList.toggle('is-active', tags.scenic);
  $('chargingNodeBtn').classList.toggle('is-active', tags.charging);
  const layer = drawingNodeLayers.get(key);
  setText('nodeManagementNote', layer ? `${layer.__drawingLabel} · ${formatNodeId(key)} · ${nodeTagDescription(key)}` : `${formatNodeId(key)} · ${nodeTagDescription(key)}`);
}

function renderNodeManagement() {
  const select = $('nodeManageSelect');
  if (!select) return;
  const previousKey = select.value;
  const entries = Object.keys(nodes).sort((a, b) => {
    const aManual = drawingNodeLayers.has(a);
    const bManual = drawingNodeLayers.has(b);
    if (aManual !== bManual) return aManual ? -1 : 1;
    return a.localeCompare(b, undefined, { numeric: true });
  });
  select.innerHTML = entries.map((key) => {
    const layer = drawingNodeLayers.get(key);
    const label = layer ? `${layer.__drawingLabel} · ${formatNodeId(key)}` : formatNodeId(key);
    return `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`;
  }).join('');
  if (entries.includes(previousKey)) select.value = previousKey;
  const scenicCount = [...nodeTags.values()].filter((tags) => tags.scenic).length;
  const chargingCount = [...nodeTags.values()].filter((tags) => tags.charging).length;
  setText('nodeTagSummary', `风景 ${scenicCount} · 充电 ${chargingCount}`);
  updateNodeManagementControls();
}

function toggleNodeTag(type, key = $('nodeManageSelect')?.value) {
  if (!key || !nodes[key]) return;
  const tags = { ...nodeTagState(key), [type]: !nodeTagState(key)[type] };
  if (!tags.scenic && !tags.charging) nodeTags.delete(key);
  else nodeTags.set(key, tags);
  const layer = drawingNodeLayers.get(key);
  if (layer) {
    refreshDrawingNodeVisual(layer);
    refreshDrawingPopup(layer);
  }
  renderNodeManagement();
  selectRouteFromSettings();
  updateMetrics(false);
  setStatus(`${formatNodeId(key)} 已${tags[type] ? '设为' : '取消'}${type === 'scenic' ? '风景节点' : '充电节点'}，路线距离已更新`, 'ready');
}

async function runPoiSearch() {
  const input = $('poiSearchInput');
  const query = input.value.trim();
  if (!query) return;
  $('regionQuery').value = query;
  await loadRegion();
}

function setBasemap(style) {
  if (style === activeBasemap) return;
  if (!basemapLayers[style]) {
    setStatus('底图样式不可用，请重新选择', 'ready');
    return;
  }
  map.removeLayer(basemapLayers[activeBasemap]);
  activeBasemap = style;
  basemapLayers[activeBasemap].addTo(map);
  const label = style === 'baidu' ? '百度地图' : style === 'hot' ? 'OSM 人文样式' : 'OSM 标准样式';
  setText('mapAreaLabel', `真实区域底图 / ${label}`);
  setStatus(style === 'baidu' ? '已切换百度底图 · 百度图层与 OSM 路网可能存在坐标偏移' : `已切换真实区域底图 · ${label}`, 'ready');
}

async function loadRegion() {
  const query = $('regionQuery').value.trim();
  if (!query || busy) return;
  const button = $('regionBtn');
  button.disabled = true;
  setStatus(`正在加载真实区域底图 · ${query}…`, 'live');
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&accept-language=zh-CN&q=${encodeURIComponent(query)}`, { headers: { Accept: 'application/json' }, signal: controller.signal });
    if (!response.ok) throw new Error('区域服务暂不可用');
    const [result] = await response.json();
    if (!result) throw new Error('没有找到匹配区域');
    const bounds = [[Number(result.boundingbox[0]), Number(result.boundingbox[2])], [Number(result.boundingbox[1]), Number(result.boundingbox[3])]];
    map.fitBounds(bounds, { padding: [55, 55], maxZoom: 15, animate: true });
    window.setTimeout(refreshMapSize, 250);
    setText('mapAreaLabel', `真实区域底图 / ${result.display_name.split(',')[0]}`);
    setStatus(`已加载真实区域底图 · ${result.display_name.split(',')[0]}`, 'ready');
  } catch (error) {
    setStatus(`区域加载失败 · ${error.name === 'AbortError' ? '请求超时，请稍后重试' : error.message}`);
  } finally {
    window.clearTimeout(timeout);
    button.disabled = false;
  }
}

function setEndpointFromLatLng(kind, latlng) {
  const closest = snapEndpointToNode(kind, [latlng.lat, latlng.lng]);
  if (!closest) {
    setStatus('该位置附近没有可用的主要道路，请选择靠近道路的位置');
    return null;
  }
  if (kind === 'start') startKey = closest; else endKey = closest;
  setFieldValue(kind === 'start' ? 'startNode' : 'endNode', `${formatNodeId(closest)} · 已吸附道路节点`);
  updateNavStopSummary();
  return closest;
}

function nodeInsideArea(key, layer) {
  if (!point(key) || !layer) return false;
  const latlng = L.latLng(point(key));
  if (layer instanceof L.Circle) return map.distance(layer.getLatLng(), latlng) <= layer.getRadius();
  return typeof layer.getBounds === 'function' && layer.getBounds().contains(latlng);
}

function routeTouchesAvoidArea(ids) {
  return [...avoidAreaLayers].some((area) => {
    for (let i = 0; i < ids.length - 1; i += 1) {
      const a = point(ids[i]);
      const b = point(ids[i + 1]);
      if (nodeInsideArea(ids[i], area) || nodeInsideArea(ids[i + 1], area)) return true;
      for (const ratio of [.25, .5, .75]) {
        const sample = L.latLng(a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio);
        if (area instanceof L.Circle) {
          if (map.distance(area.getLatLng(), sample) <= area.getRadius()) return true;
        } else if (typeof area.getBounds === 'function' && area.getBounds().contains(sample)) {
          return true;
        }
      }
    }
    return false;
  });
}

async function moveEndpoint(kind, latlng) {
  if (!await ensureOsmCoverage(latlng)) return;
  if (!setEndpointFromLatLng(kind, latlng)) return;
  activeRoute = buildRouteWithEndpoints(activeRoute);
  activeRouteEdges = [];
  cancelAnimations(); draw(); updateMetrics(false); setStatus('已更新端点，可重新规划');
}

function distanceSquared(a, b) { return (a.lat - b[0]) ** 2 + (a.lng - b[1]) ** 2; }

function normalizeNodeId(value) { return value.trim().replace('-', '').toUpperCase(); }

function findNavigationKey(value) {
  const normalized = normalizeNodeId(value);
  const poi = navigationPois.find((candidate) => candidate.name === value.trim() || normalizeNodeId(candidate.node) === normalized || normalizeNodeId(formatNodeId(candidate.node)) === normalized);
  if (poi) return poi.node;
  const manual = Object.keys(nodes).find((key) => normalizeNodeId(key) === normalized || normalizeNodeId(formatNodeId(key)) === normalized);
  if (manual) return manual;
  const osmKeyMatch = normalized.match(/^OSM:?([0-9]+)$/);
  const osmCandidate = osmKeyMatch ? osmKey(Number(osmKeyMatch[1])) : null;
  return osmCandidate && osmNetwork?.nodes[osmCandidate] ? osmCandidate : null;
}

function syncNodeInput(kind) {
  const input = kind === 'start' ? $('startNode') : $('endNode');
  const key = findNavigationKey(input.value);
  if (!key || !point(key)) {
    input.setCustomValidity('请输入已加载的 OSM POI 名称或 OSM 节点编号');
    setStatus('未找到该导航点 · 请从地图 POI 或搜索结果中选择');
    return;
  }
  input.setCustomValidity('');
  if (kind === 'start') startKey = key; else endKey = key;
  activeRoute = buildRouteWithEndpoints(activeRoute);
  activeRouteEdges = [];
  cancelAnimations(); draw(); updateMetrics(false); updateNavStopSummary(); setStatus(`已更新${kind === 'start' ? '起点' : '终点'} ${nodeLabel(key)}，可重新规划`);
}

function selectRouteFromSettings() {
  activeRoute = [];
  activeRouteEdges = [];
  layers.search.clearLayers();
  layers.searchEdges.clearLayers();
  layers.searchFrontier.clearLayers();
  layers.contractions.clearLayers();
  draw();
  updateMetrics(false);
  const hasAvoidArea = avoidAreaLayers.size > 0;
  setText('routeHint', hasAvoidArea ? '导航约束已更新，请重新规划' : '导航设置已更新，请重新规划');
}

function setStatus(message, type = '') {
  setText('mapStatus', message);
  $('resultBadge').className = `status-badge ${type ? `is-${type}` : ''}`;
  setText('resultBadge', type === 'live' ? '运行中' : type === 'ready' ? '已完成' : '待规划');
  setText('systemNote', message);
  const note = $('systemNote');
  note.innerHTML = `<span class="note-mark">i</span><span>${escapeHtml(message)}</span>`;
}

function applySkin(skin, announce = true) {
  const nextSkin = skinDefinitions[skin] ? skin : 'flower';
  document.body.classList.remove('skin-flower', 'skin-sky', 'skin-night', 'skin-bluegray', 'skin-blackwhite');
  document.body.classList.add(`skin-${nextSkin}`);
  $('skinSelect').value = nextSkin;
  try { window.localStorage.setItem('g4-navigation-skin', nextSkin); } catch (error) { /* storage may be disabled */ }
  if (announce) setStatus(`已切换皮肤 · ${skinDefinitions[nextSkin].label}`, 'ready');
}

function updateMetrics(done = true) {
  const distance = routeDistance(activeRoute);
  const segmentDistances = routeSegmentDistances(activeRoute);
  setText('distanceMetric', (distance / 1000).toFixed(2));
  setText('expandedMetric', done ? String(lastSearchStats.expanded || Math.max(0, activeRoute.length)) : '—');
  setText('queryMetric', done ? (lastSearchStats.elapsed ? lastSearchStats.elapsed.toFixed(1) : '—') : '—');
  setText('strategyLabel', `${$('algorithm').value} · ${$('routeMode').value}`);
  setText('segmentCount', `${Math.max(0, activeRoute.length - 1)} 段`);
  $('segmentList').innerHTML = activeRoute.slice(0, -1).map((id, i) => `<li>${escapeHtml(routeSegmentLabel(id, activeRoute[i + 1], activeRouteEdges[i]))} <span style="margin-left:auto;color:#9aa8a8">${Math.round(segmentDistances[i])} m</span></li>`).join('');
}

function renderRouteComparison(item = activeRouteHistoryItem) {
  const section = $('comparisonSection');
  const list = $('comparisonList');
  if (!section || !list) return;
  const runs = Array.isArray(item?.comparisons) ? item.comparisons : [];
  section.hidden = runs.length === 0;
  setText('comparisonCount', `${runs.length} 次`);
  if (!runs.length) {
    list.innerHTML = '';
    return;
  }
  const elapsedValues = runs.map((run) => Number(run.elapsed)).filter(Number.isFinite);
  const expandedValues = runs.map((run) => Number(run.expanded)).filter(Number.isFinite);
  const bestElapsed = elapsedValues.length ? Math.min(...elapsedValues) : Infinity;
  const bestExpanded = expandedValues.length ? Math.min(...expandedValues) : Infinity;
  list.innerHTML = runs.map((run, index) => {
    const elapsed = Number(run.elapsed);
    const expanded = Number(run.expanded);
    const badges = [
      elapsed === bestElapsed ? '最快' : '',
      expanded === bestExpanded ? '少扩展' : ''
    ].filter(Boolean).join(' · ');
    return `
      <div class="comparison-row${badges ? ' is-best' : ''}">
        <span class="comparison-run-index">${String(index + 1).padStart(2, '0')}</span>
        <div class="comparison-run-main">
          <strong>${escapeHtml(run.algorithm || '未知算法')}</strong>
          <small>${escapeHtml(run.mode || '默认目标')} · ${Number(run.distanceKm || 0).toFixed(2)} km${badges ? ` · ${badges}` : ''}</small>
        </div>
        <div class="comparison-run-metrics">
          <span><b>${Number.isFinite(expanded) ? expanded.toLocaleString() : '—'}</b><small>nodes</small></span>
          <span><b>${Number.isFinite(elapsed) ? elapsed.toFixed(1) : '—'}</b><small>ms</small></span>
        </div>
      </div>`;
  }).join('');
  setText('comparisonHint', runs.length < 2 ? '再次规划同一起终点，可对比不同算法的搜索表现。' : '数值越小表示本次搜索开销越低。');
}

function renderRouteHistory() {
  const anchor = $('routeHistoryAnchor');
  const list = $('routeHistoryList');
  if (!anchor || !list) return;
  const shouldShow = routeHistory.length > 0 && (!navigationPanelOpen || routeSummaryCollapsed);
  anchor.hidden = !shouldShow;
  setText('routeHistoryCount', String(routeHistory.length));
  list.innerHTML = routeHistory.map((item, index) => `
    <button class="route-history-item" type="button" data-history-index="${index}">
      <span class="route-history-index">${String(item.sequence || index + 1).padStart(2, '0')}</span>
      <span class="route-history-pair"><span>${escapeHtml(item.startLabel)}</span><b>→</b><span>${escapeHtml(item.endLabel)}</span></span>
      <small>${item.distanceKm.toFixed(2)} km · 点击查看路线设置</small>
    </button>
  `).join('');
}

function setPlanKicker(sequence = 1) {
  setText('planKicker', `${String(sequence).padStart(2, '0')} / PLAN`);
}

function setRouteSummaryCollapsed(collapsed) {
  routeSummaryCollapsed = collapsed;
  document.querySelector('.workspace')?.classList.toggle('route-summary-collapsed', collapsed);
  if (collapsed && $('routeHistoryDetails')) $('routeHistoryDetails').open = false;
  renderRouteHistory();
  window.setTimeout(refreshMapSize, 180);
}

function rememberRouteHistory() {
  if (!startKey || !endKey || activeRoute.length < 2) return;
  const existingIndex = routeHistory.findIndex((item) => item.startKey === startKey && item.endKey === endKey);
  const previousItem = existingIndex >= 0 ? routeHistory[existingIndex] : null;
  const sequence = ++routeSequence;
  const run = {
    sequence,
    algorithm: $('algorithm').value,
    mode: $('routeMode').value,
    path: [...activeRoute],
    edgePath: activeRouteEdges.map((edge) => ({ ...edge })),
    expanded: lastSearchStats.expanded,
    elapsed: lastSearchStats.elapsed,
    distanceKm: routeDistance(activeRoute) / 1000
  };
  const item = {
    startKey,
    endKey,
    startLabel: nodeLabel(startKey),
    endLabel: nodeLabel(endKey),
    ...run,
    comparisons: [...(previousItem?.comparisons || []), run].slice(-12)
  };
  if (existingIndex >= 0) routeHistory.splice(existingIndex, 1);
  routeHistory.unshift(item);
  routeHistory = routeHistory.slice(0, ROUTE_HISTORY_LIMIT);
  activeRouteHistoryItem = item;
  setPlanKicker(sequence);
  renderRouteComparison(item);
  renderRouteHistory();
}

function restoreRouteHistory(index) {
  const item = routeHistory[index];
  if (!item || !item.path.every((key) => point(key))) {
    setStatus('历史路线所需的路网区域尚未加载，请先回到对应地图区域');
    return;
  }
  startKey = item.startKey;
  endKey = item.endKey;
  clickSelectStart = false;
  activeRouteHistoryItem = item;
  setPlanKicker(item.sequence || index + 1);
  activeRoute = [...item.path];
  activeRouteEdges = item.edgePath.map((edge) => ({ ...edge }));
  lastSearchStats = { expanded: item.expanded, elapsed: item.elapsed };
  if ($('algorithm')) $('algorithm').value = item.algorithm;
  if ($('routeMode')) $('routeMode').value = item.mode;
  setFieldValue('startNode', `${formatNodeId(startKey)} · 已吸附道路节点`);
  setFieldValue('endNode', `${formatNodeId(endKey)} · 已吸附道路节点`);
  updateNavStopSummary();
  renderRouteComparison(item);
  $('routeHistoryDetails').open = false;
  setNavigationPanelOpen(true);
  document.querySelector('.workspace')?.classList.add('route-planned');
  setRouteSummaryCollapsed(false);
  draw();
  updateMetrics(true);
  setStatus('已打开历史路线', 'ready');
}

function cancelAnimations() { animationToken += 1; busy = false; if (vehicleMarker) { layers.vehicle.clearLayers(); vehicleMarker = null; } }
function setButtons(disabled) {
  ['planBtn', 'contractionBtn', 'driveBtn', 'trafficBtn', 'regionBtn', 'algorithm', 'routeMode', 'avoidHighway', 'avoidTraffic', 'preferScenic', 'preferCharging']
    .forEach((id) => { const control = $(id); if (control) control.disabled = disabled; });
}

function edgeInsideAvoidArea(a, b) {
  if (routeTouchesAvoidArea([a, b])) return true;
  return false;
}

function buildGraph() {
  if (osmNetwork && graphCacheNetwork === osmNetwork && graphCache) return graphCache;
  const graphKeys = osmNetwork ? [...osmNetwork.roadNodeKeys] : Object.keys(nodes);
  const graph = new Map([...new Set(graphKeys)].map((key) => [key, []]));
  const addEdge = (from, to, edge) => graph.get(from)?.push({ to, ...edge });
  if (osmNetwork) {
    osmNetwork.roads.forEach((road, roadIndex) => {
      const edge = { distance: road.distance, highway: road.highway, roadIndex, edgeId: road.edgeId || `road:${roadIndex}`, name: road.name || 'OSM 道路' };
      addEdge(road.from, road.to, edge);
      if (!road.oneWay) addEdge(road.to, road.from, edge);
    });
  } else {
    roads.forEach(([from, to, highway, oneWay], roadIndex) => {
      const edge = { distance: geographicDistance(point(from), point(to)), highway, roadIndex, edgeId: `road:${roadIndex}`, name: '道路' };
      addEdge(from, to, edge);
      if (!oneWay) addEdge(to, from, edge);
    });
  }
  if (osmNetwork) {
    graphCacheNetwork = osmNetwork;
    graphCache = graph;
  }
  return graph;
}

function searchEdgeCost(from, to, edge) {
  const highway = edge.highway === true || ['motorway', 'trunk'].includes(edge.highway);
  const roadIndex = edge.roadIndex;
  if (highway && $('avoidHighway')?.checked) return Infinity;
  if (edgeInsideAvoidArea(from, to)) return Infinity;
  const distance = edge.distance ?? geographicDistance(point(from), point(to));
  const mode = $('routeMode').value;
  let cost = distance;
  if (mode === '最快') cost = distance * (highway ? .86 : 1);
  if (mode === '省油') cost = distance * (highway ? .92 : 1.08);
  if (mode === '少红绿灯') cost = distance * (highway ? .9 : 1.03) + (roadIndex === trafficRoadIndex ? 260 : 0);
  if (mode === '风景' && nodeTagState(to).scenic) cost -= 260;
  if (nodeTagState(to).charging && $('preferCharging')?.checked) cost -= 180;
  if (trafficOn && roadIndex === trafficRoadIndex) cost *= $('avoidTraffic')?.checked ? 2.4 : 1.45;
  return Math.max(1, cost);
}

function estimateHeuristicScale(graph) {
  const signature = JSON.stringify({
    algorithm: $('algorithm')?.value,
    mode: $('routeMode')?.value,
    avoidHighway: Boolean($('avoidHighway')?.checked),
    avoidTraffic: Boolean($('avoidTraffic')?.checked),
    trafficOn,
    avoidAreas: avoidAreaLayers.size,
    nodeTags: [...nodeTags.entries()]
  });
  if (heuristicCacheNetwork === osmNetwork && heuristicCacheSignature === signature) return heuristicCacheScale;
  let scale = Infinity;
  graph.forEach((edges, from) => {
    edges.forEach((edge) => {
      const cost = searchEdgeCost(from, edge.to, edge);
      const geometricDistance = geographicDistance(point(from), point(edge.to));
      if (Number.isFinite(cost) && geometricDistance > 0) scale = Math.min(scale, cost / geometricDistance);
    });
  });
  heuristicCacheNetwork = osmNetwork;
  heuristicCacheSignature = signature;
  heuristicCacheScale = Number.isFinite(scale) ? Math.max(0, scale * (1 - 1e-12)) : 0;
  return heuristicCacheScale;
}

function heuristicCost(from, to, scale) {
  if ($('algorithm').value === 'Dijkstra' || $('algorithm').value === 'CH') return 0;
  return geographicDistance(point(from), point(to)) * scale;
}

class MinPriorityQueue {
  constructor() { this.items = []; this.sequence = 0; }

  get size() { return this.items.length; }

  push(item) {
    // 同优先级时使用递增序号，避免不同浏览器对相同 f/g 值产生不稳定的展开顺序。
    const entry = { ...item, sequence: this.sequence++ };
    this.items.push(entry);
    let index = this.items.length - 1;
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2);
      if (!this.isBefore(entry, this.items[parent])) break;
      this.items[index] = this.items[parent];
      index = parent;
    }
    this.items[index] = entry;
  }

  pop() {
    if (!this.items.length) return null;
    const first = this.items[0];
    const last = this.items.pop();
    if (this.items.length && last) {
      let index = 0;
      while (true) {
        const left = index * 2 + 1;
        const right = left + 1;
        let smallest = index;
        if (left < this.items.length && this.isBefore(this.items[left], last)) smallest = left;
        if (right < this.items.length && this.isBefore(this.items[right], smallest === index ? last : this.items[smallest])) smallest = right;
        if (smallest === index) break;
        this.items[index] = this.items[smallest];
        index = smallest;
      }
      this.items[index] = last;
    }
    return first;
  }

  isBefore(left, right) {
    return left.f < right.f
      || (left.f === right.f && (left.g < right.g || (left.g === right.g && left.sequence < right.sequence)));
  }
}

function makeSearchTrace(start, target, heuristicScale) {
  const graph = buildGraph();
  if (!start || !target || !graph.has(start) || !graph.has(target)) return { path: [], snapshots: [], expanded: 0 };
  const open = new MinPriorityQueue();
  open.push({ key: start, g: 0, f: heuristicCost(start, target, heuristicScale) });
  const gScore = new Map([[start, 0]]);
  const cameFrom = new Map();
  const expanded = new Set();
  const expandedCost = new Map();
  const snapshots = [];
  const maxExpanded = osmNetwork ? 15000 : Infinity;
  const snapshotStride = osmNetwork ? 4 : 1;
  let pendingExpanded = [];
  let queuePushes = 1;
  let bestGoalCost = Infinity;

  while (open.size && expanded.size < maxExpanded) {
    const current = open.pop();
    if (!current || current.g !== gScore.get(current.key)) continue;
    if (expandedCost.has(current.key) && current.g >= expandedCost.get(current.key)) continue;
    // 只有队列中最优候选也无法改进当前终点代价时才结束，避免启发式边界情况下过早停止。
    if (Number.isFinite(bestGoalCost) && current.f > bestGoalCost + 1e-9) break;
    expanded.add(current.key);
    expandedCost.set(current.key, current.g);
    pendingExpanded.push(current.key);
    if (current.key === target) {
      bestGoalCost = Math.min(bestGoalCost, current.g);
    }
    if (current.key !== target) {
      const candidates = graph.get(current.key) || [];
      candidates.forEach((edge) => {
        const { to } = edge;
        const cost = searchEdgeCost(current.key, to, edge);
        if (!Number.isFinite(cost)) return;
        if (expanded.has(to)) return;
        const nextG = current.g + cost;
        if (nextG < (gScore.get(to) ?? Infinity)) {
          gScore.set(to, nextG);
          cameFrom.set(to, { from: current.key, edge });
          open.push({ key: to, g: nextG, f: nextG + heuristicCost(to, target, heuristicScale) });
          queuePushes += 1;
        }
      });
    }
    const shouldSnapshot = expanded.size % snapshotStride === 0 || current.key === target;
    if (shouldSnapshot) {
      const frontierKeys = [...new Set(open.items.map((entry) => entry.key))].filter((key) => !expanded.has(key));
      snapshots.push({ current: current.key, expandedDelta: pendingExpanded, frontier: frontierKeys.slice(0, 180), frontierCount: frontierKeys.length });
      pendingExpanded = [];
    }
  }

  if (pendingExpanded.length) {
    const last = snapshots[snapshots.length - 1];
    snapshots.push({ current: pendingExpanded[pendingExpanded.length - 1], expandedDelta: pendingExpanded, frontier: last?.frontier || [], frontierCount: last?.frontierCount || 0 });
  }

  const path = [];
  const edgePath = [];
  if (expanded.has(target)) {
    let cursor = target;
    while (cursor) {
      path.unshift(cursor);
      const previous = cameFrom.get(cursor);
      if (!previous) break;
      edgePath.unshift(previous.edge);
      cursor = previous.from;
    }
  }
  return { path, edgePath, snapshots, expanded: expanded.size, queuePushes };
}

function buildSearchPlan() {
  const stops = [startKey, ...navWaypointKeys, endKey];
  let path = [];
  let edgePath = [];
  let expanded = 0;
  let queuePushes = 0;
  const snapshots = [];
  const graph = buildGraph();
  const heuristicScale = estimateHeuristicScale(graph);
  for (let index = 0; index < stops.length - 1; index += 1) {
    const trace = makeSearchTrace(stops[index], stops[index + 1], heuristicScale);
    if (!trace.path.length) return { path: [], snapshots, expanded };
    path = path.concat(index === 0 ? trace.path : trace.path.slice(1));
    edgePath = edgePath.concat(trace.edgePath || []);
    expanded += trace.expanded;
    queuePushes += trace.queuePushes || 0;
    snapshots.push(...trace.snapshots);
  }
  return { path, edgePath, snapshots, expanded, queuePushes };
}

function renderSearchSnapshot(snapshot, displayState) {
  layers.search.clearLayers();
  layers.searchEdges.clearLayers();
  layers.searchFrontier.clearLayers();
  const visibleExpanded = [...displayState.expanded].slice(-650);
  const visibleFrontier = snapshot.frontier.slice(0, 240);
  visibleExpanded.forEach((key) => {
    L.marker(point(key), { icon: L.divIcon({ className: 'search-point', iconSize: [9, 9], iconAnchor: [4.5, 4.5] }), interactive: false }).addTo(layers.search);
  });
  visibleFrontier.forEach((key) => {
    L.marker(point(key), { icon: L.divIcon({ className: 'frontier-node', html: '<span></span>', iconSize: [18, 18], iconAnchor: [9, 9] }), interactive: false }).addTo(layers.searchFrontier);
  });
  if (snapshot.current) {
    L.marker(point(snapshot.current), { icon: L.divIcon({ className: 'frontier-current', html: '<span>◆</span>', iconSize: [18, 18], iconAnchor: [9, 9] }), interactive: false }).addTo(layers.searchFrontier);
  }
  setText('routeHint', `已遍历 ${displayState.expandedTotal} 个折点 · 边界 ${snapshot.frontierCount ?? snapshot.frontier.length} 个折点`);
}

async function replay() {
  if (!osmNetwork) {
    setStatus('路网数据正在准备 · 请稍候再规划', 'live');
    return;
  }
  if (!startKey || !endKey) {
    setStatus('请先在地图上点击道路设置起点和终点');
    return;
  }
  if (startKey === endKey) {
    setStatus('起点和终点不能是同一个道路节点');
    return;
  }
  cancelAnimations(); busy = true; setButtons(true); setStatus('正在展开搜索边界…', 'live');
  const searchStartedAt = performance.now();
  let plan = buildSearchPlan();
  // 两个端点可能分别来自两个局部缓存，先补充它们之间的道路再重算。
  if (!plan.path.length && !$('avoidHighway')?.checked && avoidAreaLayers.size === 0) {
    if (await ensureRouteCoverage()) plan = buildSearchPlan();
  }
  const searchElapsed = performance.now() - searchStartedAt;
  const token = animationToken;
  if (!plan.path.length) {
    busy = false; setButtons(false); setStatus('当前约束下没有找到可行路径'); setText('routeHint', '请检查高速、拥堵或避让区设置');
    return;
  }
  const snapshotStep = Math.max(1, Math.ceil(plan.snapshots.length / 42));
  const frameDelay = plan.snapshots.length > 1800 ? 42 : 58;
  const displayState = { expanded: new Set(), expandedTotal: 0 };
  let frameIndex = 0;
  for (let index = 0; index < plan.snapshots.length; index += 1) {
    if (token !== animationToken) return;
    const snapshot = plan.snapshots[index];
    snapshot.expandedDelta?.forEach((key) => displayState.expanded.add(key));
    displayState.expandedTotal += snapshot.expandedDelta?.length || 0;
    if (displayState.expanded.size > 900) displayState.expanded = new Set([...displayState.expanded].slice(-900));
    if (index % snapshotStep !== 0 && index !== plan.snapshots.length - 1) continue;
    renderSearchSnapshot(snapshot, displayState);
    frameIndex += 1;
    const totalFrames = Math.ceil(plan.snapshots.length / snapshotStep);
    const progress = Math.round(frameIndex / totalFrames * 100);
    setText('progressValue', `${progress}%`);
    $('routeProgress').style.width = `${progress}%`;
    await delay(frameDelay);
  }
  if (token !== animationToken) return;
  await delay(220);
  layers.search.clearLayers(); layers.searchEdges.clearLayers(); layers.searchFrontier.clearLayers();
  activeRoute = plan.path;
  activeRouteEdges = plan.edgePath || [];
  lastSearchStats = { expanded: plan.expanded, queuePushes: plan.queuePushes, elapsed: searchElapsed };
  document.querySelector('.workspace')?.classList.add('route-planned');
  rememberRouteHistory();
  setRouteSummaryCollapsed(false);
  draw(); updateMetrics(true); busy = false; setButtons(false); setStatus(`规划完成 · 已扩展 ${plan.expanded} 个道路节点`, 'ready');
}

async function runPlan() {
  if (!osmNetwork) {
    setStatus('路网数据正在准备 · 请稍候再规划', 'live');
    return;
  }
  cancelAnimations(); layers.contractions.clearLayers(); layers.search.clearLayers(); layers.searchEdges.clearLayers(); layers.searchFrontier.clearLayers(); activeRoute = []; activeRouteEdges = []; draw(); updateMetrics(false); setText('routeHint', `${$('algorithm').value} 搜索中，正在展开候选节点`); setText('progressValue', '0%'); $('routeProgress').style.width = '0%';
  await replay();
  if (!busy && activeRoute.length) setText('routeHint', `${$('algorithm').value} 搜索轨迹已完成`);
}

async function contractions() {
  if (!osmNetwork) {
    setStatus('请先加载 OSM 路网后再使用 CH');
    return;
  }
  if (!contractionNodes.length) {
    setStatus('OSM 路网已加载，但 CH 预处理尚未实现，请使用 A* 或 Dijkstra', 'ready');
    setText('routeHint', 'CH 仅保留为实验入口');
    return;
  }
  cancelAnimations(); layers.search.clearLayers(); layers.contractions.clearLayers(); draw(); busy = true; setButtons(true); setStatus('收缩层级与捷径生成中…', 'live');
  const token = animationToken; const step = 1;
  for (let i = 0; i < contractionNodes.length; i += step) {
    if (token !== animationToken) return;
    const node = contractionNodes[i];
    L.marker(point(node), { icon: L.divIcon({ className: 'contraction-point', iconSize: [7, 7], iconAnchor: [3.5, 3.5] }), interactive: false }).addTo(layers.contractions);
    if (i > 1 && i % 2 === 0) {
      const a = contractionNodes[i - 2];
      L.polyline([point(a), point(node)], { color: '#a978ad', weight: 2, dashArray: '4 5', opacity: .78, interactive: false }).addTo(layers.contractions);
    }
    setText('routeHint', `已处理 ${i + 1} / ${contractionNodes.length} 个节点`); setText('progressValue', `${Math.round((i + 1) / contractionNodes.length * 100)}%`); $('routeProgress').style.width = `${(i + 1) / contractionNodes.length * 100}%`;
    await delay(105);
  }
  busy = false; setButtons(false); setStatus('CH 收缩完成 · 紫色虚线为新增捷径', 'ready'); setText('routeHint', '收缩层级已生成');
}

async function drive() {
  if (activeRoute.length < 2 || busy) return;
  cancelAnimations(); busy = true; setButtons(true); setStatus('模拟车辆沿路线行驶…', 'live');
  const token = animationToken; const coords = latLngs(activeRoute); const totalDistance = routeDistance(activeRoute); const vehicle = L.marker(coords[0], { icon: L.divIcon({ className: 'vehicle-marker', html: '<span>●</span>', iconSize: [21, 21], iconAnchor: [10.5, 10.5] }), interactive: false }).addTo(layers.vehicle); vehicleMarker = vehicle;
  const frames = 180;
  for (let frame = 0; frame <= frames; frame += 1) {
    if (token !== animationToken) return;
    const scaled = (frame / frames) * (coords.length - 1); const index = Math.min(coords.length - 2, Math.floor(scaled)); const ratio = Math.min(1, scaled - index); const a = coords[index]; const b = coords[index + 1];
    vehicle.setLatLng([a[0] + ratio * (b[0] - a[0]), a[1] + ratio * (b[1] - a[1])]);
    setText('routeHint', `车辆行驶中 · 剩余 ${Math.max(0, Math.round((1 - frame / frames) * totalDistance))} m`); setText('progressValue', `${Math.round(frame / frames * 100)}%`); $('routeProgress').style.width = `${frame / frames * 100}%`;
    await delay(32);
  }
  busy = false; setButtons(false); setStatus('车辆已抵达终点', 'ready'); setText('routeHint', `已抵达 ${endKey}`);
}

function toggleTraffic() {
  if (busy) return;
  trafficOn = !trafficOn;
  selectRouteFromSettings();
  updateMetrics(true);
  setStatus(trafficOn ? '已模拟中段道路拥堵，已标注路段并生成绕行路线' : '已清空模拟拥堵，恢复常态路况', trafficOn ? 'live' : 'ready');
  $('trafficBtn').innerHTML = `<span class="button-icon">≋</span>${trafficOn ? '清空拥堵' : '模拟拥堵'}`;
}

function drawStyle() {
  return { color: $('drawColor').value, weight: Number($('drawWidth').value), opacity: .9, fillColor: $('drawColor').value, fillOpacity: .18, lineCap: 'round', lineJoin: 'round' };
}

function setDrawStatus(message) { setText('drawStatus', message); }

function clearDrawingDraft() {
  drawingPoints = [];
  drawingPreviewPoint = null;
  drawingGesture = false;
  layers.drawingDraft.clearLayers();
  map.getContainer().classList.remove('drawing-cursor');
  map.dragging.enable();
}

function setDrawingMode(mode) {
  clearDrawingDraft();
  drawingMode = drawingMode === mode ? null : mode;
  document.querySelectorAll('.draw-tool').forEach((button) => button.classList.toggle('is-active', button.dataset.drawMode === drawingMode));
  if (drawingMode === 'polyline' || drawingMode === 'polygon') map.doubleClickZoom.disable();
  else map.doubleClickZoom.enable();
  if (drawingMode) {
    map.closePopup();
    map.getContainer().classList.add('drawing-cursor');
    const instructions = { point: '点击地图放置一个 POI 点', polyline: '连续点击地图取点，双击或点“完成”结束', curve: '按住鼠标拖动绘制自由曲线', polygon: '连续点击地图取点，双击或点“完成”结束', rectangle: '点击两个角点完成矩形', circle: '先点击圆心，再点击圆周' };
    setDrawStatus(instructions[drawingMode]);
    setText('mapStatus', `手动标绘 · ${$('drawLabel').value}`);
  } else {
    setDrawStatus('选择工具后在地图上操作');
    setText('mapStatus', '准备就绪');
  }
}

function drawingPopupContent(layer) {
  const label = escapeHtml(layer.__drawingLabel || '未命名标注');
  const type = layer.__drawingType;
  const editForm = layer.__editingName ? `<div class="draw-popup-edit"><input type="text" data-drawing-name-input value="${label}" maxlength="40" aria-label="标注名称"><button type="button" data-drawing-action="save-name">保存</button><button type="button" data-drawing-action="cancel-name">取消</button></div>` : '';
  const editActions = `<button type="button" data-drawing-action="edit">编辑名称</button><button type="button" data-drawing-action="delete" class="is-danger">${type === 'point' ? '删除点' : '删除标注'}</button>`;
  if (type === 'point') {
    const key = layer.__navNodeKey;
    const startActive = startKey === key;
    const endActive = endKey === key;
    const viaActive = navWaypointKeys.includes(key);
    const tags = nodeTagState(key);
    return `<div class="draw-popup-name">${label}</div><div class="draw-popup-meta">导航节点 ${formatNodeId(key)} · ${nodeTagDescription(key)}</div>${editForm}<div class="draw-popup-actions"><button type="button" data-drawing-action="scenic" class="${tags.scenic ? 'is-active' : ''}">${tags.scenic ? '取消风景节点' : '设为风景节点'}</button><button type="button" data-drawing-action="charging" class="${tags.charging ? 'is-active' : ''}">${tags.charging ? '取消充电节点' : '设为充电节点'}</button></div><div class="draw-popup-actions"><button type="button" data-drawing-action="start" class="${startActive ? 'is-active' : ''}">${startActive ? '当前为起点' : '设为起点'}</button><button type="button" data-drawing-action="end" class="${endActive ? 'is-active' : ''}">${endActive ? '当前为终点' : '设为终点'}</button><button type="button" data-drawing-action="via" class="${viaActive ? 'is-active' : ''}">${viaActive ? '取消途经点' : '加入途经点'}</button>${editActions}</div>`;
  }
  if (['polygon', 'rectangle', 'circle'].includes(type)) {
    const avoidActive = avoidAreaLayers.has(layer);
    return `<div class="draw-popup-name">${label}</div><div class="draw-popup-meta">可交互区域 · 点击后可用于导航约束</div>${editForm}<div class="draw-popup-actions"><button type="button" data-drawing-action="avoid" class="${avoidActive ? 'is-active' : ''}">${avoidActive ? '取消导航避让区' : '设为导航避让区'}</button>${editActions}</div>`;
  }
  return `<div class="draw-popup-name">${label}</div><div class="draw-popup-meta">手动标绘 · ${type === 'curve' ? '自由曲线' : '折线'}</div>${editForm}<div class="draw-popup-actions">${editActions}</div>`;
}

function refreshDrawingPopup(layer) {
  const wasOpen = layer.isPopupOpen();
  layer.setPopupContent(drawingPopupContent(layer));
  if (wasOpen) layer.openPopup();
  wireDrawingPopupActions(layer, layer.getPopup()?.getElement());
}

function selectDrawingLayer(layer) {
  if (selectedDrawingLayer && selectedDrawingLayer !== layer && selectedDrawingLayer.__baseStyle && typeof selectedDrawingLayer.setStyle === 'function') {
    selectedDrawingLayer.setStyle(selectedDrawingLayer.__baseStyle);
    selectedDrawingLayer.getElement()?.classList.remove('drawing-selected');
  }
  selectedDrawingLayer = layer;
  if (layer.__baseStyle && typeof layer.setStyle === 'function') {
    layer.setStyle({ ...layer.__baseStyle, weight: layer.__baseStyle.weight + 2, fillOpacity: Math.min(.35, (layer.__baseStyle.fillOpacity || .18) + .1) });
  }
  layer.getElement()?.classList.add('drawing-selected');
}

function setNavigationFromDrawingNode(nodeKey, action) {
  if (action === 'start' || action === 'end') {
    const otherKey = action === 'start' ? endKey : startKey;
    if (otherKey === nodeKey) {
      setStatus('起点和终点不能设置为同一个 POI');
      return;
    }
    if (action === 'start') startKey = nodeKey;
    else endKey = nodeKey;
    const inputId = action === 'start' ? 'startNode' : 'endNode';
    setFieldValue(inputId, formatNodeId(nodeKey));
    const index = navWaypointKeys.indexOf(nodeKey);
    if (index >= 0) navWaypointKeys.splice(index, 1);
    selectRouteFromSettings();
    updateNavStopSummary();
    setStatus(`已将「${drawingNodeLayers.get(nodeKey).__drawingLabel}」设为${action === 'start' ? '起点' : '终点'}，路线距离已更新`, 'ready');
  } else if (action === 'via') {
    const index = navWaypointKeys.indexOf(nodeKey);
    if (index >= 0) navWaypointKeys.splice(index, 1);
    else if (nodeKey !== startKey && nodeKey !== endKey) navWaypointKeys.push(nodeKey);
    selectRouteFromSettings();
    updateNavStopSummary();
    setStatus(index >= 0 ? '已从途经点移除，路线距离已更新' : `已加入途经点「${drawingNodeLayers.get(nodeKey).__drawingLabel}」，路线距离已更新`, 'ready');
  }
}

function toggleAvoidArea(layer) {
  if (avoidAreaLayers.has(layer)) avoidAreaLayers.delete(layer);
  else avoidAreaLayers.add(layer);
  selectDrawingLayer(layer);
  refreshDrawingPopup(layer);
  selectRouteFromSettings();
  updateMetrics(false);
  setStatus(avoidAreaLayers.has(layer) ? `已启用「${layer.__drawingLabel}」作为导航避让区` : `已取消「${layer.__drawingLabel}」的导航避让约束`, 'ready');
}

function removeDrawingLayer(layer, mode = 'delete') {
  const historyIndex = drawingHistory.indexOf(layer);
  if (historyIndex < 0) return;
  layers.drawings.removeLayer(layer);
  drawingHistory.splice(historyIndex, 1);
  if (layer.__navNodeKey) {
    const nodeKey = layer.__navNodeKey;
    delete nodes[nodeKey];
    nodeTags.delete(nodeKey);
    drawingNodeLayers.delete(nodeKey);
    const waypointIndex = navWaypointKeys.indexOf(nodeKey);
    if (waypointIndex >= 0) navWaypointKeys.splice(waypointIndex, 1);
    if (startKey === nodeKey) { startKey = navigationPois[0]?.node || null; setFieldValue('startNode', startKey ? nodeLabel(startKey) : ''); }
    if (endKey === nodeKey) { endKey = navigationPois.find((poi) => poi.node !== startKey)?.node || null; setFieldValue('endNode', endKey ? nodeLabel(endKey) : ''); }
  }
  avoidAreaLayers.delete(layer);
  if (selectedDrawingLayer === layer) selectedDrawingLayer = null;
  updateNavStopSummary();
  renderNodeManagement();
  selectRouteFromSettings();
  if (mode === 'delete') {
    setDrawStatus(`已删除「${layer.__drawingLabel}」 · 剩余 ${drawingHistory.length} 个标注`);
    setStatus(`已删除手动标注「${layer.__drawingLabel}」`, 'ready');
  }
}

function saveDrawingName(layer, input) {
  const nextLabel = input?.value.trim();
  if (!nextLabel) {
    input?.focus();
    return;
  }
  layer.__drawingLabel = nextLabel;
  layer.__editingName = false;
  refreshDrawingPopup(layer);
  updateNavStopSummary();
  setDrawStatus(`已更新名称「${nextLabel}」`);
  setStatus(`已更新手动标注名称 · ${nextLabel}`, 'ready');
}

function wireDrawingPopupActions(layer, popupElement) {
  if (!popupElement) return;
  popupElement.querySelectorAll('[data-drawing-action]').forEach((button) => {
    if (button.dataset.bound === 'true') return;
    button.dataset.bound = 'true';
    button.addEventListener('click', () => {
      const action = button.dataset.drawingAction;
      if (action === 'edit') {
        layer.__editingName = true;
        refreshDrawingPopup(layer);
        const input = layer.getPopup()?.getElement()?.querySelector('[data-drawing-name-input]');
        input?.focus();
        input?.select();
      } else if (action === 'save-name') {
        saveDrawingName(layer, layer.getPopup()?.getElement()?.querySelector('[data-drawing-name-input]'));
      } else if (action === 'cancel-name') {
        layer.__editingName = false;
        refreshDrawingPopup(layer);
      } else if (layer.__drawingType === 'point' && ['scenic', 'charging'].includes(action)) {
        toggleNodeTag(action, layer.__navNodeKey);
      } else if (layer.__drawingType === 'point' && ['start', 'end', 'via'].includes(action)) {
        setNavigationFromDrawingNode(layer.__navNodeKey, action);
      } else if (action === 'avoid') {
        toggleAvoidArea(layer);
      } else if (action === 'delete') {
        removeDrawingLayer(layer);
        map.closePopup();
      }
    });
  });
}

function drawingPopup(layer) {
  layer.bindPopup(drawingPopupContent(layer));
  layer.on('popupopen', (event) => wireDrawingPopupActions(layer, event.popup.getElement()));
  layer.on('click', (event) => {
    if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
    selectDrawingLayer(layer);
  });
  return layer;
}

function finishDrawing() {
  if (!drawingMode || drawingPoints.length === 0) return;
  const style = drawStyle();
  const points = drawingPoints.slice();
  let layer = null;
  const label = $('drawLabel').value.trim() || '未命名标注';
  if (drawingMode === 'point') {
    const color = style.color;
    layer = L.marker(points[0], { icon: L.divIcon({ className: 'draw-poi-marker', html: `<span style="--draw-color:${color}">P</span>`, iconSize: [18, 18], iconAnchor: [9, 9] }) });
  } else if (drawingMode === 'polyline' || drawingMode === 'curve') {
    if (points.length < 2) return setDrawStatus('至少需要两个点才能完成线');
    layer = L.polyline(points, style);
  } else if (drawingMode === 'polygon') {
    if (points.length < 3) return setDrawStatus('至少需要三个点才能完成面');
    layer = L.polygon(points, style);
  } else if (drawingMode === 'rectangle') {
    if (points.length < 2) return setDrawStatus('请点击矩形的两个角点');
    layer = L.rectangle(L.latLngBounds(points[0], points[1]), style);
  } else if (drawingMode === 'circle') {
    if (points.length < 2) return setDrawStatus('请先点击圆心和圆周');
    layer = L.circle(points[0], { ...style, radius: map.distance(points[0], points[1]) });
  }
  if (!layer) return;
  layer.__drawingType = drawingMode;
  layer.__drawingLabel = label;
  layer.__drawingColor = style.color;
  if (drawingMode === 'point') {
    const nodeKey = `M${String(nextDrawingNodeId).padStart(2, '0')}`;
    nextDrawingNodeId += 1;
    nodes[nodeKey] = [points[0].lat, points[0].lng];
    layer.__navNodeKey = nodeKey;
    drawingNodeLayers.set(nodeKey, layer);
    refreshDrawingNodeVisual(layer);
  } else if (typeof layer.setStyle === 'function') {
    layer.__baseStyle = { ...style };
  }
  drawingPopup(layer).addTo(layers.drawings);
  drawingHistory.push(layer);
  if (drawingMode === 'point') {
    setDrawStatus(`已添加「${label}」 · 导航节点 ${formatNodeId(layer.__navNodeKey)} · 共 ${drawingHistory.length} 个标注`);
    setText('mapStatus', `已添加导航 POI · ${label}`);
  } else {
    setDrawStatus(`已添加「${label}」 · 点击图形可交互 · 共 ${drawingHistory.length} 个标注`);
    setText('mapStatus', `已添加手动标注 · ${label}`);
  }
  renderNodeManagement();
  setDrawingMode(null);
}

function renderDrawingDraft() {
  layers.drawingDraft.clearLayers();
  if (!drawingMode || drawingPoints.length === 0) return;
  const style = { ...drawStyle(), dashArray: '5 5', opacity: .7 };
  const points = drawingPoints.slice();
  if (drawingPreviewPoint) points.push(drawingPreviewPoint);
  drawingPoints.forEach((latlng) => L.circleMarker(latlng, { radius: 4, color: style.color, weight: 2, fillColor: '#fff', fillOpacity: .95, interactive: false }).addTo(layers.drawingDraft));
  if (drawingPreviewPoint) L.circleMarker(drawingPreviewPoint, { radius: 4, color: style.color, weight: 2, fillColor: style.color, fillOpacity: .65, interactive: false }).addTo(layers.drawingDraft);
  if (drawingMode === 'point') return;
  if ((drawingMode === 'polyline' || drawingMode === 'curve') && points.length > 1) L.polyline(points, { ...style, interactive: false }).addTo(layers.drawingDraft);
  if (drawingMode === 'polygon' && points.length > 1) {
    if (points.length > 2) L.polygon(points, { ...style, interactive: false }).addTo(layers.drawingDraft);
    else L.polyline(points, { ...style, interactive: false }).addTo(layers.drawingDraft);
  }
  if (drawingMode === 'rectangle' && points.length > 1) L.rectangle(L.latLngBounds(points[0], points[1]), { ...style, interactive: false }).addTo(layers.drawingDraft);
  if (drawingMode === 'circle' && points.length > 1) L.circle(points[0], { ...style, radius: map.distance(points[0], points[1]), interactive: false }).addTo(layers.drawingDraft);
}

function handleDrawingClick(event) {
  if (!drawingMode || drawingMode === 'curve') return;
  drawingPreviewPoint = null;
  if (drawingMode === 'point') {
    drawingPoints = [event.latlng];
    finishDrawing();
    return;
  }
  if (drawingMode === 'rectangle' || drawingMode === 'circle') {
    drawingPoints.push(event.latlng);
    renderDrawingDraft();
    if (drawingPoints.length === 2) finishDrawing();
    return;
  }
  drawingPoints.push(event.latlng);
  renderDrawingDraft();
  setDrawStatus(`已取 ${drawingPoints.length} 个点 · 双击或点击“完成”结束`);
}

function undoDrawing() {
  if (drawingMode && drawingPoints.length) {
    drawingPoints.pop();
    drawingPreviewPoint = null;
    renderDrawingDraft();
    setDrawStatus(drawingPoints.length ? `已退回到 ${drawingPoints.length} 个点 · 移动鼠标继续预览` : '已清除当前绘制点 · 移动鼠标选择起点');
    return;
  }
  clearDrawingDraft();
  const layer = drawingHistory[drawingHistory.length - 1];
  if (layer) {
    removeDrawingLayer(layer, 'undo');
    setDrawStatus(`已撤销 · 剩余 ${drawingHistory.length} 个标注`);
  }
}

function clearDrawings() {
  clearDrawingDraft();
  layers.drawings.clearLayers();
  drawingHistory = [];
  drawingNodeLayers.forEach((layer, nodeKey) => { delete nodes[nodeKey]; });
  drawingNodeLayers.clear();
  nodeTags.clear();
  navWaypointKeys.length = 0;
  avoidAreaLayers.clear();
  selectedDrawingLayer = null;
  if (!point(startKey)) startKey = navigationPois[0]?.node || null;
  if (!point(endKey) || endKey === startKey) endKey = navigationPois.find((poi) => poi.node !== startKey)?.node || null;
  setFieldValue('startNode', startKey ? nodeLabel(startKey) : '');
  setFieldValue('endNode', endKey ? nodeLabel(endKey) : '');
  updateNavStopSummary();
  renderNodeManagement();
  selectRouteFromSettings();
  setDrawStatus('已清空手动标绘图层');
  setText('mapStatus', '手动标绘已清空');
}

function setSidebarPage(page) {
  if (activeSidebarPage === page) return;
  if (page === 'navigation') { drawingMode = null; clearDrawingDraft(); }
  activeSidebarPage = page;
  document.querySelectorAll('.sidebar-tab').forEach((tab) => {
    const active = tab.dataset.page === page;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  document.querySelectorAll('[data-page-panel]').forEach((panel) => { panel.hidden = panel.dataset.pagePanel !== page; });
  setText('mapStatus', page === 'drawing' ? '手动标绘模式' : '导航模式');
}

function setPanelCollapsed(side, collapsed) {
  const workspace = document.querySelector('.workspace');
  const isLeft = side === 'left';
  const className = isLeft ? 'left-panel-collapsed' : 'right-panel-collapsed';
  const button = $(isLeft ? 'leftPanelToggle' : 'rightPanelToggle');
  if (isLeft) leftPanelCollapsed = collapsed;
  else rightPanelCollapsed = collapsed;
  workspace.classList.toggle(className, collapsed);
  button.setAttribute('aria-pressed', String(collapsed));
  button.setAttribute('aria-label', `${collapsed ? '展开' : '收起'}${isLeft ? '左侧功能栏' : '右侧路线栏'}`);
  button.textContent = isLeft ? (collapsed ? '›' : '‹') : (collapsed ? '‹' : '›');
  window.setTimeout(refreshMapSize, 180);
}

function setNavigationPanelOpen(open) {
  const workspace = document.querySelector('.workspace');
  if (!workspace) return;
  navigationPanelOpen = open;
  workspace.classList.toggle('menu-open', open);
  if (!open && $('routeHistoryDetails')) $('routeHistoryDetails').open = false;
  renderRouteHistory();
  window.setTimeout(refreshMapSize, 180);
}

map.on('click', async (event) => {
  if (busy) return;
  if (activeSidebarPage === 'drawing') {
    handleDrawingClick(event);
    return;
  }
  // 先打开导航面板，再准备路网；这样路网请求较慢或失败时，用户仍能看到起终点设置入口。
  setNavigationPanelOpen(true);
  try {
    if (networkLoading) {
      setStatus('路网数据正在自动准备，已记录本次选点…', 'live');
      while (networkLoading) await delay(80);
    }
    if (!await ensureOsmCoverage(event.latlng)) return;
    const kind = clickSelectStart ? 'start' : 'end';
    if (kind === 'start') {
      activeRouteHistoryItem = null;
      renderRouteComparison(null);
      setPlanKicker(routeSequence + 1);
    }
    const closest = setEndpointFromLatLng(kind, event.latlng);
    if (!closest) return;
    setStatus(kind === 'start' ? '起点已吸附到最近道路节点 · 请继续点击终点' : '终点已吸附到最近道路节点 · 可以开始规划', 'ready');
    clickSelectStart = !clickSelectStart; activeRoute = buildRouteWithEndpoints(activeRoute); activeRouteEdges = []; draw();
    updateNavStopSummary();
  } catch (error) {
    console.error('地图选点失败', error);
    setStatus(`选点失败 · ${error.message || '请稍后重试'}`, 'ready');
  }
});

// 浏览地图进入新区域时自动预取道路，选点时不再临时等待整块数据。
map.on('moveend', scheduleViewportCoverage);

map.on('dblclick', () => {
  if (activeSidebarPage === 'drawing' && (drawingMode === 'polyline' || drawingMode === 'polygon')) finishDrawing();
});

map.on('mousedown', (event) => {
  if (activeSidebarPage !== 'drawing' || drawingMode !== 'curve' || busy) return;
  drawingGesture = true;
  drawingPreviewPoint = null;
  drawingPoints = [event.latlng];
  map.dragging.disable();
  renderDrawingDraft();
});

map.on('mousemove', (event) => {
  if (activeSidebarPage !== 'drawing' || !drawingMode || busy) return;
  if (drawingMode === 'curve') {
    if (!drawingGesture) return;
    drawingPoints.push(event.latlng);
    renderDrawingDraft();
    return;
  }
  if (!drawingPoints.length) return;
  drawingPreviewPoint = event.latlng;
  renderDrawingDraft();
});

map.on('mouseout', () => {
  if (drawingMode && drawingMode !== 'curve' && drawingPreviewPoint) {
    drawingPreviewPoint = null;
    renderDrawingDraft();
  }
});

map.on('mouseup', () => {
  if (!drawingGesture || drawingMode !== 'curve') return;
  drawingGesture = false;
  map.dragging.enable();
  finishDrawing();
});

$('planBtn').addEventListener('click', runPlan);
$('contractionBtn').addEventListener('click', contractions);
$('driveBtn').addEventListener('click', drive);
$('trafficBtn').addEventListener('click', toggleTraffic);
$('regionBtn').addEventListener('click', loadRegion);
$('basemapSelect').addEventListener('change', (event) => setBasemap(event.target.value));
$('skinSelect').addEventListener('change', (event) => applySkin(event.target.value));
$('routeMode').addEventListener('change', () => { if (!busy) { selectRouteFromSettings(); setStatus(`已切换路线目标 · ${$('routeMode').value}`, 'ready'); } });
$('fitBtn').addEventListener('click', () => { if (activeRoute.length > 1) map.fitBounds(L.latLngBounds(latLngs(activeRoute)), { padding: [75, 75], animate: true }); });
$('poiSearchBtn').addEventListener('click', runPoiSearch);
$('poiSearchInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') runPoiSearch(); });
$('panelCloseBtn').addEventListener('click', () => setNavigationPanelOpen(false));
$('insightCloseBtn').addEventListener('click', () => setRouteSummaryCollapsed(true));
$('routeHistoryList').addEventListener('click', (event) => {
  const item = event.target.closest('[data-history-index]');
  if (item) restoreRouteHistory(Number(item.dataset.historyIndex));
});
$('leftPanelToggle').addEventListener('click', () => setPanelCollapsed('left', !leftPanelCollapsed));
$('rightPanelToggle').addEventListener('click', () => setPanelCollapsed('right', !rightPanelCollapsed));
document.querySelectorAll('.sidebar-tab').forEach((tab) => tab.addEventListener('click', () => setSidebarPage(tab.dataset.page)));
document.querySelectorAll('.draw-tool').forEach((button) => button.addEventListener('click', () => setDrawingMode(button.dataset.drawMode)));
$('finishDrawBtn').addEventListener('click', finishDrawing);
$('undoDrawBtn').addEventListener('click', undoDrawing);
$('clearDrawBtn').addEventListener('click', clearDrawings);
$('drawWidth').addEventListener('input', (event) => { setText('drawWidthValue', event.target.value); renderDrawingDraft(); });
$('drawColor').addEventListener('input', renderDrawingDraft);
$('nodeManageSelect').addEventListener('change', updateNodeManagementControls);
$('scenicNodeBtn').addEventListener('click', () => toggleNodeTag('scenic'));
$('chargingNodeBtn').addEventListener('click', () => toggleNodeTag('charging'));
$('networkContrast').addEventListener('change', (event) => {
  networkContrast = event.target.checked;
  draw();
  setStatus(networkContrast ? '已启用底图压暗' : '已关闭底图压暗', 'ready');
});
['preferScenic', 'preferCharging'].forEach((id) => {
  const control = $(id);
  if (!control) return;
  control.addEventListener('change', () => {
    if (busy) return;
    selectRouteFromSettings();
    const label = id === 'preferScenic' ? '风景节点' : '充电节点';
    setStatus(`${label}偏好已${control.checked ? '启用' : '关闭'}，路线已更新`, 'ready');
  });
});

let initialSkin = 'flower';
try { initialSkin = window.localStorage.getItem('g4-navigation-skin') || 'flower'; } catch (error) { /* storage may be disabled */ }
applySkin(initialSkin, false);
renderRouteHistory();
renderNodeManagement();
draw(); updateMetrics(false); setStatus('路网准备中 · 可直接在地图上选择起终点', 'live');
setText('routeHint', '点击地图选择起点和终点');
window.setTimeout(() => { loadOsmNetwork({ interactive: false }); }, 180);
  window.setTimeout(() => { refreshMapSize(); }, 120);
