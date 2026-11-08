/* Leaflet navigation UI. Route computation is owned by server.py. */
const ACTIVE_NETWORK_DATASET = 'guangdong';
const map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([23.38, 113.50], 8);
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

const backendNodes = {};
const layers = { route: L.layerGroup().addTo(map), routeMotion: L.layerGroup().addTo(map), search: L.layerGroup().addTo(map), searchFrontier: L.layerGroup().addTo(map), endpoints: L.layerGroup().addTo(map), vehicle: L.layerGroup().addTo(map), chPreprocess: L.layerGroup() };
let startKey = null;
let endKey = null;
let startCoords = null;
let endCoords = null;
let activeRoute = [];
let activeRouteEdges = [];
let busy = false;
let animationToken = 0;
let clickSelectStart = true;
let trafficOn = false;
let vehicleMarker = null;
let leftPanelCollapsed = false;
let rightPanelCollapsed = false;
let lastSearchStats = { expanded: 0, elapsed: 0 };
let routeHistory = [];
let routeSequence = 0;
let activeRouteHistoryItem = null;
let routeSummaryCollapsed = false;
let navigationPanelOpen = false;
let routeMotionToken = 0;
let networkContrast = true;
// A4 导航固定使用广东省数据；浏览器只按区域请求，用户不需要管理底层路网文件。
const SERVER_ROUTE_URL = '/api/route';

const $ = (id) => document.getElementById(id);
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));
const point = (key) => backendNodes[key] || null;
const latLngs = (ids) => ids.map(id => point(id));
const setText = (id, value) => { const element = $(id); if (element) element.textContent = value; };
const setFieldValue = (id, value) => { $(id).value = value; };
const ROUTE_HISTORY_LIMIT = 8;

const chMapReplayState = { enabled: false, fitted: false, events: [], nodes: {}, index: 0 };
function chReplayPoint(nodeId, fallbackPoint = null) {
  const value = chMapReplayState.nodes[String(nodeId)] || fallbackPoint || {};
  const lat = Number(value.lat);
  const lon = Number(value.lon);
  return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
}
function renderChReplayMap() {
  if (!chMapReplayState.enabled) return;
  layers.chPreprocess.clearLayers();
  const events = chMapReplayState.events;
  const index = Math.min(chMapReplayState.index, Math.max(0, events.length - 1));
  events.slice(index + 1).forEach((event) => {
    const pending = event.contracted_node || {};
    const position = chReplayPoint(pending.id ?? pending, pending);
    if (!position) return;
    L.circleMarker(position, {
      radius: 4.5,
      color: '#d5edf2',
      weight: 1.5,
      fillColor: '#62a9bc',
      fillOpacity: .88,
      interactive: false
    }).addTo(layers.chPreprocess);
  });
  events.slice(0, index + 1).forEach((event, eventIndex) => {
    const contracted = event.contracted_node || {};
    const id = contracted.id ?? contracted;
    const position = chReplayPoint(id, contracted);
    if (!position) return;
    const isCurrent = eventIndex === index;
    L.circleMarker(position, {
      radius: isCurrent ? 7 : 3.5,
      color: isCurrent ? '#f3e4bd' : '#456c59',
      weight: isCurrent ? 2 : 1,
      fillColor: isCurrent ? '#d95f50' : '#8bb58e',
      fillOpacity: isCurrent ? .98 : .62,
      interactive: false
    }).addTo(layers.chPreprocess);
  });
  const current = events[index];
  (current?.shortcuts_added || []).forEach((shortcut) => {
    const from = chReplayPoint(shortcut.from_id, shortcut.from);
    const to = chReplayPoint(shortcut.to_id, shortcut.to);
    if (!from || !to) return;
    L.polyline([from, to], { color: '#d9a441', weight: 2, opacity: .8, dashArray: '5 4', interactive: false }).addTo(layers.chPreprocess);
  });
}
function mountChReplayMap(payload) {
  chMapReplayState.events = Array.isArray(payload?.events) ? payload.events : [];
  chMapReplayState.nodes = payload?.nodes || {};
  chMapReplayState.index = 0;
  chMapReplayState.fitted = false;
  if (chMapReplayState.enabled) renderChReplayMap();
}
function toggleChReplayMap() {
  chMapReplayState.enabled = !chMapReplayState.enabled;
  if (!chMapReplayState.enabled) {
    layers.chPreprocess.clearLayers();
    return false;
  }
  layers.chPreprocess.addTo(map);
  if (!chMapReplayState.fitted) {
    const points = chMapReplayState.events.map((event) => {
      const contracted = event.contracted_node || {};
      return chReplayPoint(contracted.id ?? contracted, contracted);
    }).filter(Boolean);
    if (points.length > 1) map.fitBounds(L.latLngBounds(points), { padding: [70, 70], maxZoom: 11, animate: true });
    chMapReplayState.fitted = true;
  }
  renderChReplayMap();
  return true;
}
window.G4ChMapReplay = {
  mount: mountChReplayMap,
  setIndex: (index) => { chMapReplayState.index = Number(index) || 0; renderChReplayMap(); },
  toggle: toggleChReplayMap,
  isEnabled: () => chMapReplayState.enabled,
  clear: () => { chMapReplayState.enabled = false; layers.chPreprocess.clearLayers(); }
};
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

function syncNetworkDisplay() {
  map.getContainer().classList.toggle('network-focus', networkContrast);
}

function routeSegmentDistances(ids) {
  return ids.slice(0, -1).map((id, index) => activeRouteEdges[index]?.distance ?? geographicDistance(point(id), point(ids[index + 1])));
}

function routeDistance(ids) { return routeSegmentDistances(ids).reduce((total, distance) => total + distance, 0); }

function routeSegmentLabel(from, to, edge) {
  if (edge?.name) return edge.name;
  return '道路';
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
  const endpointLabels = [
    startKey ? `起点：${nodeLabel(startKey)}` : '',
    endKey ? `终点：${nodeLabel(endKey)}` : ''
  ].filter(Boolean);
  if (!endpointLabels.length) {
    setText('navStopSummary', '点击地图设置起点，再次点击设置终点。端点会自动吸附到最近道路节点。');
    return;
  }
  setText('navStopSummary', endpointLabels.join('；'));
}

function iconFor(kind, label) {
  return L.divIcon({ className: `node-marker ${kind}`, html: `<span>${label}</span>`, iconSize: [27, 27], iconAnchor: [13.5, 13.5] });
}


function draw() {
  routeMotionToken += 1;
  layers.route.clearLayers();
  layers.routeMotion.clearLayers();
  layers.endpoints.clearLayers();
  syncNetworkDisplay();
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

async function runMapSearch() {
  const input = $('mapSearchInput');
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
  const coords = [latlng.lat, latlng.lng];
  const key = `pending:${kind}`;
  backendNodes[key] = coords;
  if (kind === 'start') { startKey = key; startCoords = coords; } else { endKey = key; endCoords = coords; }
  setFieldValue(kind === 'start' ? 'startNode' : 'endNode', `${coords[0].toFixed(5)}, ${coords[1].toFixed(5)} · 待路网吸附`);
  updateNavStopSummary();
  return key;
}

async function moveEndpoint(kind, latlng) {
  if (!setEndpointFromLatLng(kind, latlng)) return;
  activeRoute = [];
  activeRouteEdges = [];
  cancelAnimations(); draw(); updateMetrics(false); setStatus('已更新端点，可重新规划');
}

async function requestBackendRoute() {
  if (!startCoords || !endCoords) throw new Error('请先在地图上点击起点和终点');
  const response = await fetch(SERVER_ROUTE_URL, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      dataset: ACTIVE_NETWORK_DATASET,
      algorithm: $('algorithm').value,
      start: { lat: startCoords[0], lon: startCoords[1] },
      end: { lat: endCoords[0], lon: endCoords[1] },
      options: {
        route_mode: $('routeMode').value,
        avoid_highway: Boolean($('avoidHighway')?.checked),
        avoid_traffic: Boolean($('avoidTraffic')?.checked)
      }
    })
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `服务器 HTTP ${response.status}`);
  Object.entries(payload.nodes || {}).forEach(([key, coords]) => { backendNodes[key] = [Number(coords.lat), Number(coords.lon)]; });
  startKey = payload.start.id;
  endKey = payload.end.id;
  startCoords = point(startKey);
  endCoords = point(endKey);
  setFieldValue('startNode', `${formatNodeId(startKey)} · 已吸附道路节点`);
  setFieldValue('endNode', `${formatNodeId(endKey)} · 已吸附道路节点`);
  updateNavStopSummary();
  return payload;
}

function selectRouteFromSettings() {
  activeRoute = [];
  activeRouteEdges = [];
  layers.search.clearLayers();
  layers.searchFrontier.clearLayers();
  draw();
  updateMetrics(false);
  setText('routeHint', '导航设置已更新，请重新规划');
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
function syncChReplayButton() {
  const button = $('contractionBtn');
  if (button) button.hidden = $('algorithm')?.value !== 'CH';
}
function setButtons(disabled) {
  ['planBtn', 'contractionBtn', 'driveBtn', 'trafficBtn', 'regionBtn', 'algorithm', 'routeMode', 'avoidHighway', 'avoidTraffic', 'preferScenic', 'preferCharging']
    .forEach((id) => { const control = $(id); if (control) control.disabled = disabled; });
}

function renderSearchSnapshot(snapshot, displayState) {
  layers.search.clearLayers();
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
  if (!startCoords || !endCoords) {
    setStatus('请先在地图上点击道路设置起点和终点');
    return;
  }
  cancelAnimations(); busy = true; setButtons(true); setStatus('正在展开搜索边界…', 'live');
  let plan;
  try {
    const payload = await requestBackendRoute();
    plan = { path: payload.path || [], edgePath: payload.edges || [], snapshots: payload.snapshots || [], expanded: payload.expanded || 0, queuePushes: payload.queuePushes || 0 };
    plan.serverMs = payload.server_ms;
  } catch (error) {
    busy = false; setButtons(false); setStatus(`后端路径规划失败 · ${error.message}`, 'ready');
    return;
  }
  const searchElapsed = Number.isFinite(plan.serverMs) ? plan.serverMs : 0;
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
  layers.search.clearLayers(); layers.searchFrontier.clearLayers();
  activeRoute = plan.path;
  activeRouteEdges = plan.edgePath || [];
  lastSearchStats = { expanded: plan.expanded, queuePushes: plan.queuePushes, elapsed: searchElapsed };
  document.querySelector('.workspace')?.classList.add('route-planned');
  rememberRouteHistory();
  setRouteSummaryCollapsed(false);
  draw(); updateMetrics(true); busy = false; setButtons(false); setStatus(`规划完成 · 已扩展 ${plan.expanded} 个道路节点`, 'ready');
}

async function runPlan() {
  cancelAnimations(); layers.search.clearLayers(); layers.searchFrontier.clearLayers(); activeRoute = []; activeRouteEdges = []; draw(); updateMetrics(false); setText('routeHint', `${$('algorithm').value} 搜索中，正在展开候选节点`); setText('progressValue', '0%'); $('routeProgress').style.width = '0%';
  await replay();
  if (!busy && activeRoute.length) setText('routeHint', `${$('algorithm').value} 搜索轨迹已完成`);
}

async function contractions() {
  const bar = $('chMapReplayBar');
  if (!window.G4ChApi || !window.G4ChReplay || !window.G4ChMapReplay) {
    setStatus('CH 预处理回放组件不可用', 'error');
    return;
  }
  $('analysisPanel').hidden = true;
  setStatus('正在加载 CH 预处理事件…', 'live');
  try {
    const replay = await window.G4ChApi.getEvents('guangdong');
    window.G4ChMapReplay.clear();
    window.G4ChReplay.mount(replay.events || [], replay);
    window.G4ChReplay.setMeta(replay);
    window.G4ChMapReplay.toggle();
    if (bar) bar.hidden = false;
    window.G4ChReplay.play();
    setStatus('CH 预处理动画已在主地图播放 · 广东省路网', 'live');
  } catch (error) {
    if (bar) bar.hidden = true;
    setStatus('CH 预处理加载失败 · ' + error.message, 'error');
  }
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
  // 后端负责吸附和路径计算，点击地图时只记录原始经纬度。
  setNavigationPanelOpen(true);
  try {
    const kind = clickSelectStart ? 'start' : 'end';
    if (kind === 'start') {
      activeRouteHistoryItem = null;
      renderRouteComparison(null);
      setPlanKicker(routeSequence + 1);
    }
    const closest = setEndpointFromLatLng(kind, event.latlng);
    if (!closest) return;
    setStatus(kind === 'start' ? '起点已记录 · 请继续点击终点' : '终点已记录 · 点击路线开始规划', 'ready');
    clickSelectStart = !clickSelectStart; activeRoute = []; activeRouteEdges = []; draw();
    updateNavStopSummary();
  } catch (error) {
    console.error('地图选点失败', error);
    setStatus(`选点失败 · ${error.message || '请稍后重试'}`, 'ready');
  }
});

$('planBtn').addEventListener('click', runPlan);
$('contractionBtn').addEventListener('click', contractions);
$('driveBtn').addEventListener('click', drive);
$('trafficBtn').addEventListener('click', toggleTraffic);
$('regionBtn').addEventListener('click', loadRegion);
$('basemapSelect').addEventListener('change', (event) => setBasemap(event.target.value));
$('skinSelect').addEventListener('change', (event) => applySkin(event.target.value));
$('algorithm').addEventListener('change', () => {
  syncChReplayButton();
  setText('strategyLabel', `${$('algorithm').value} · ${$('routeMode').value}`);
  if (!busy) setStatus(`已切换搜索算法 · ${$('algorithm').value}`, 'ready');
});
$('routeMode').addEventListener('change', () => { if (!busy) { selectRouteFromSettings(); setStatus(`已切换路线目标 · ${$('routeMode').value}`, 'ready'); } });
$('fitBtn').addEventListener('click', () => { if (activeRoute.length > 1) map.fitBounds(L.latLngBounds(latLngs(activeRoute)), { padding: [75, 75], animate: true }); });
$('mapSearchBtn').addEventListener('click', runMapSearch);
$('mapSearchInput').addEventListener('keydown', (event) => { if (event.key === 'Enter') runMapSearch(); });
$('panelCloseBtn').addEventListener('click', () => setNavigationPanelOpen(false));
$('insightCloseBtn').addEventListener('click', () => setRouteSummaryCollapsed(true));
$('routeHistoryList').addEventListener('click', (event) => {
  const item = event.target.closest('[data-history-index]');
  if (item) restoreRouteHistory(Number(item.dataset.historyIndex));
});
$('leftPanelToggle').addEventListener('click', () => setPanelCollapsed('left', !leftPanelCollapsed));
$('rightPanelToggle').addEventListener('click', () => setPanelCollapsed('right', !rightPanelCollapsed));
$('networkContrast').addEventListener('change', (event) => {
  networkContrast = event.target.checked;
  draw();
  setStatus(networkContrast ? '已启用底图压暗' : '已关闭底图压暗', 'ready');
});
let initialSkin = 'flower';
try { initialSkin = window.localStorage.getItem('g4-navigation-skin') || 'flower'; } catch (error) { /* storage may be disabled */ }
applySkin(initialSkin, false);
renderRouteHistory();
syncChReplayButton();
draw(); updateMetrics(false); setStatus('后端路网已就绪 · 可直接在地图上选择起终点', 'ready');
setText('routeHint', '点击地图选择起点和终点');
  window.setTimeout(() => { refreshMapSize(); }, 120);
