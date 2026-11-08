(function () {
  const MOCK_DATASETS = [
    { id: 'guangdong', name: '广东省路网', runs: ['Q300/S20261102'] },
    { id: 'shenzhen', name: '深圳市路网', runs: ['Q300/S20261102'] },
    { id: 'nanshan', name: '南山区路网', runs: ['Q300/S20261102'] }
  ];
  const MOCK_DATASET = 'guangdong';
  const webBaseUrl = () => window.G4_API_CONFIG?.webBaseUrl || 'http://127.0.0.1:5173';
  const baseUrl = () => window.G4_API_CONFIG?.a2BaseUrl || 'http://127.0.0.1:8000';
  const isMock = () => (window.G4_A2_DATA_MODE || window.G4_DATA_MODE) === 'mock';
  let configCache = null;

  async function json(url) {
    let response;
    try {
      response = await fetch(url, { headers: { Accept: 'application/json' } });
    } catch (_) {
      throw new Error('A2 服务未启动，请双击网页项目的 start-server.bat 一键启动');
    }
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = payload.detail || payload.message || '';
      } catch (_) { /* 非 JSON 错误响应 */ }
      throw new Error(detail || `A2 接口 HTTP ${response.status}`);
    }
    return response.json();
  }

  function normalizeSummary(payload) {
    const raw = payload.algorithms || {};
    const run = payload.run || {};
    const queryCount = Number(run.query_count || 0);
    const seed = Number(run.seed ?? 0);
    const dataset = payload.dataset || {};
    const datasetNames = { guangdong: '广东省路网', shenzhen: '深圳市路网', nanshan: '南山区路网' };
    return {
      source: 'A2 基础版 C++ 固定测试集',
      dataset: { ...dataset, id: dataset.id || MOCK_DATASET, name: dataset.name || datasetNames[dataset.id] || '广东省路网' },
      run: {
        ...run,
        run_id: run.run_id || `Q${queryCount || 300}/S${seed || 20261102}`,
        query_count: queryCount || 300,
        repeat: Number(run.repeat || 3),
        seed: seed || 20261102
      },
      algorithms: Object.entries(raw).map(([id, value]) => ({
        id,
        name: value.name || ({ dijkstra: 'Dijkstra', astar: 'A*', bidirectional_astar: '双向 A*', ch: 'CH' }[id] || id),
        queryP50: Number(value.query_p50_ms ?? value.query_p50 ?? 0),
        queryP95: Number(value.query_p95_ms ?? value.query_p95 ?? 0),
        expanded: Number(value.expanded_mean ?? value.expanded ?? 0),
        preprocess: Number(value.preprocess_ms ?? value.preprocess ?? 0),
        total: Number(value.total_ms ?? value.total ?? 0),
        shortcuts: Number(value.shortcut_edges ?? value.shortcuts ?? 0)
      }))
    };
  }

  async function getConfig({ force = false } = {}) {
    if (!force && configCache) return configCache;
    if (isMock()) {
      configCache = Promise.resolve({
        datasets: MOCK_DATASETS,
        defaults: { dataset: MOCK_DATASET, query_count: 300, repeat: 3, seed: 20261102,
          algorithms: ['dijkstra', 'astar', 'bidirectional_astar', 'ch'] }
      });
      return configCache;
    }
    configCache = json(`${baseUrl()}/api/config`).catch((error) => {
      // Do not keep a failed request after the service restarts.
      configCache = null;
      throw error;
    });
    return configCache;
  }

  async function getCacheStatus() {
    if (isMock()) return { datasets: MOCK_DATASETS.map((dataset) => ({ dataset: dataset.id, ready: true })) };
    return json(`${baseUrl()}/api/cache/status`);
  }

  async function getSummary() {
    if (isMock()) {
      const payload = await json('mock/a2-summaries.json');
      return normalizeSummary(payload[MOCK_DATASET]);
    }
    return normalizeSummary(await json(`${baseUrl()}/api/results/summary`));
  }

  async function getDatasets() {
    const config = await getConfig();
    return config.datasets || [];
  }

  async function createJob(request) {
    if (isMock()) {
      return { job_id: 'mock', status: 'completed', stage: 'completed', progress: 100 };
    }
    const response = await fetch(`${baseUrl()}/api/benchmarks`, {
      method: 'POST',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = payload.detail || payload.message || '';
      } catch (_) { /* 非 JSON 错误响应 */ }
      throw new Error(detail || `A2 接口 HTTP ${response.status}`);
    }
    return response.json();
  }

  async function getJobStatus(jobId) {
    if (isMock()) return { job_id: jobId, status: 'completed', stage: 'completed', progress: 100 };
    const payload = await json(`${baseUrl()}/api/jobs/${encodeURIComponent(jobId)}`);
    if (payload.result) payload.result = normalizeSummary(payload.result);
    return payload;
  }

  async function getTable() {
    if (isMock()) return { rows: [] };
    return json(`${baseUrl()}/api/results/table`);
  }

  window.G4A2Api = { getConfig, getCacheStatus, getDatasets, getSummary, getTable, createJob, getJobStatus };
})();
