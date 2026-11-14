(function () {
  const MOCK_DATASETS = [
    { id: 'guangdong', name: '广东省路网', runs: [] },
    { id: 'shenzhen', name: '深圳市路网', runs: [] },
    { id: 'nanshan', name: '南山区路网', runs: [] }
  ];
  const baseUrl = () => window.G4_API_CONFIG?.a3BaseUrl || 'http://127.0.0.1:8100/api/benchmark';

  async function json(path, options = {}) {
    const response = await fetch(`${baseUrl()}${path}`, {
      ...options,
      headers: { Accept: 'application/json', ...(options.headers || {}) }
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `A3 接口 HTTP ${response.status}`);
    return payload;
  }

  function isMock() {
    return (window.G4_A3_DATA_MODE || window.G4_DATA_MODE) === 'mock';
  }

  function normalizeSummary(payload, datasetId = 'guangdong') {
    if (Array.isArray(payload.summary_table)) {
      const network = (payload.networks || []).find((item) => item.network?.id === datasetId)
        || payload.networks?.[0] || {};
      const networkInfo = network.network || {};
      const config = network.config || {};
      const rows = payload.summary_table.filter((item) => item.network_id === networkInfo.id);
      return {
        presentation: 'latest',
        source: 'A3 最新接口 · 最终优化配置',
        timingSemantics: payload.timing_semantics || '',
        dataset: { id: networkInfo.id || datasetId, name: networkInfo.label || datasetId, ...networkInfo },
        run: {
          run_id: `${networkInfo.id || datasetId}/Q${config.query_count || payload.request?.query_count || '—'}/R${config.rounds || payload.request?.rounds || '—'}/S${config.seed ?? payload.request?.seed ?? '—'}`,
          query_count: config.query_count,
          repeat: config.rounds,
          seed: config.seed
        },
        preprocessing: network.preprocessing_ms || {},
        correctness: network.correctness || {},
        algorithms: rows.map((item) => ({
          id: item.algorithm,
          name: item.label || item.algorithm,
          version: item.version || '',
          medianMs: Number(item.median_ms || 0),
          q1Ms: Number(item.q1_ms || 0),
          q3Ms: Number(item.q3_ms || 0),
          expanded: Number(item.mean_expanded_count || 0),
          speedup: item.paired_speedup_vs_dijkstra == null ? null : Number(item.paired_speedup_vs_dijkstra),
          semantics: item.expanded_count_semantics || ''
        }))
      };
    }

    const raw = payload.algorithms || {};
    return {
      presentation: 'legacy',
      source: 'A3 优化前后对比数据',
      dataset: { ...(payload.dataset || {}), id: datasetId, name: payload.dataset?.name || datasetId },
      run: payload.run || { run_id: '—', query_count: 0, repeat: 0, seed: null },
      algorithms: Object.entries(raw).map(([id, value]) => ({
        id,
        name: value.name || id,
        before: value.before || {},
        optimized: value.optimized || {}
      }))
    };
  }

  async function getDatasets() {
    if (isMock()) return MOCK_DATASETS;
    return json('/datasets');
  }

  async function getSummary(dataset = 'guangdong') {
    if (isMock()) return normalizeSummary(await fetch('mock/a3-summary.json').then((response) => response.json()), dataset);
    return normalizeSummary(await json(`/summary?dataset=${encodeURIComponent(dataset)}`), dataset);
  }

  async function createJob(request) {
    if (isMock()) throw new Error('A3 当前是 mock 模式，不能提交测试任务');
    return json('/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    });
  }

  async function getJobStatus(jobId) {
    return json(`/jobs/${encodeURIComponent(jobId)}`);
  }

  window.G4A3Api = { getDatasets, getSummary, createJob, getJobStatus, normalizeSummary };
})();
