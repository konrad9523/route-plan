(function () {
  const $ = (id) => document.getElementById(id);
  let activeBoard = 'a2';
  let a2Summary = null;
  let a3Summary = null;
  let a2JobTimer = null;
  let a2JobStartedAt = 0;
  let a2LoadToken = 0;
  let a2RunActive = false;
  let analysisOpened = false;
  let a2Config = null;
  let a2LastRequest = null;
  let a3JobTimer = null;
  let a3JobStartedAt = 0;
  let a3RunActive = false;
  let a3LastRequest = null;

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[character]));
  }

  function setStatus(message, kind = 'ready') {
    const status = $('analysisStatus');
    if (status) { status.textContent = message; status.dataset.kind = kind; }
  }

  function updateA2RunTrace({ request = a2LastRequest, status = null, summary = null } = {}) {
    const trace = $('a2RunTrace');
    if (!trace) return;
    const service = a2Config?.service || {};
    const run = summary?.run || {};
    const runId = run.run_id || status?.run_id || (request && `pending/${request.dataset}/Q${request.query_count}/R${request.repeat}/S${request.seed}`) || '—';
    const state = status ? `${status.status || '—'}${status.stage ? ` / ${status.stage}` : ''} / ${Number(status.progress ?? 0)}%` : '—';
    const error = status?.error ? `<div><b>本次错误：</b>${escapeHtml(status.error)}</div>` : '';
    trace.innerHTML = [
      `<div><b>页面：</b>${escapeHtml(`${window.location.origin}${window.location.pathname}`)}</div>`,
      `<div><b>代码目录：</b>${escapeHtml(service.interface_dir || '服务未返回')}</div>`,
      `<div><b>请求服务：</b>${escapeHtml(`${window.G4_API_CONFIG?.a2BaseUrl || 'http://127.0.0.1:8000'}/api/benchmarks`)}</div>`,
      `<div><b>本次 run：</b>${escapeHtml(runId)}</div>`,
      `<div><b>状态：</b>${escapeHtml(state)}</div>`,
      error
    ].join('');
  }

  function barRows(items, value, formatter = (number) => number.toFixed(2)) {
    const values = items.map(value);
    const max = Math.max(...values, 1);
    return items.map((item, index) => `<div class="analysis-bar-row"><span>${escapeHtml(item.name)}</span><div class="analysis-bar-track"><i style="width:${Math.max(4, values[index] / max * 100)}%"></i></div><b>${formatter(values[index])}</b></div>`).join('');
  }

  function renderA2(summary) {
    a2Summary = summary;
    $('a2DatasetMeta').textContent = `${summary.dataset.name} · ${summary.run.run_id} · ${summary.run.query_count} 组查询 · ${summary.source}`;
    $('a2Cards').innerHTML = summary.algorithms.map((item) => `<article class="analysis-card"><span>${escapeHtml(item.name)}</span><strong>${item.queryP50.toFixed(2)}<small> ms p50</small></strong><p>p95 ${item.queryP95.toFixed(2)} ms · 扩展 ${Math.round(item.expanded).toLocaleString()} nodes</p></article>`).join('');
    $('a2QueryChart').innerHTML = barRows(summary.algorithms, (item) => item.queryP50, (number) => `${number.toFixed(2)} ms`);
    $('a2ExpandedChart').innerHTML = barRows(summary.algorithms, (item) => item.expanded, (number) => Math.round(number).toLocaleString());
    $('a2PreprocessChart').innerHTML = barRows(summary.algorithms, (item) => item.preprocess, (number) => `${number.toFixed(1)} ms`);
    $('a2Table').innerHTML = summary.algorithms.map((item) => `<tr><th>${escapeHtml(item.name)}</th><td>${item.queryP50.toFixed(3)} ms</td><td>${item.queryP95.toFixed(3)} ms</td><td>${Math.round(item.expanded).toLocaleString()}</td><td>${item.preprocess.toFixed(1)} ms</td><td>${item.shortcuts.toLocaleString()}</td></tr>`).join('');
  }

  function renderA3(summary) {
    a3Summary = summary;
    $('a3DatasetMeta').textContent = `${summary.dataset.name} · ${summary.run.run_id} · ${summary.run.query_count} 组查询 · ${summary.source}`;
    if (summary.presentation === 'latest') {
      const algorithms = summary.algorithms || [];
      $('a3Cards').innerHTML = algorithms.map((item) => `<article class="analysis-card"><span>${escapeHtml(item.name)}</span><strong>${item.medianMs.toFixed(2)}<small> ms p50</small></strong><p>Q1 ${item.q1Ms.toFixed(2)} · Q3 ${item.q3Ms.toFixed(2)} ms · 扩展 ${Math.round(item.expanded).toLocaleString()}</p></article>`).join('');
      $('a3Table').innerHTML = algorithms.map((item) => `<tr><th>${escapeHtml(item.name)}</th><td>${item.medianMs.toFixed(3)} ms</td><td>${item.q1Ms.toFixed(3)}–${item.q3Ms.toFixed(3)} ms</td><td>${Math.round(item.expanded).toLocaleString()}</td><td>${item.speedup == null ? '—' : `${item.speedup.toFixed(2)} ×`}</td></tr>`).join('');
      $('a3QueryChart').innerHTML = algorithms.length ? barRows(algorithms.map((item) => ({ name: item.name, value: item.medianMs })), (item) => item.value, (number) => `${number.toFixed(2)} ms`) : '暂无数据';
      $('a3ExpandedChart').innerHTML = algorithms.length ? barRows(algorithms.map((item) => ({ name: item.name, value: item.expanded })), (item) => item.value, (number) => Math.round(number).toLocaleString()) : '暂无数据';
      return;
    }
    $('a3Cards').innerHTML = summary.algorithms.map((item) => {
      const before = metric(item.before, 'queryP50');
      const optimized = metric(item.optimized, 'queryP50');
      const ratio = optimized ? (before / optimized).toFixed(2) : '—';
      return `<article class="analysis-card"><span>${escapeHtml(item.name)}</span><strong>${ratio}<small> × 加速</small></strong><p>${before.toFixed(2)} ms → ${optimized.toFixed(2)} ms</p></article>`;
    }).join('');
    $('a3Table').innerHTML = summary.algorithms.map((item) => `<tr><th>${escapeHtml(item.name)}</th><td>${formatA3(item.before, 'queryP50')}</td><td>${formatA3(item.optimized, 'queryP50')}</td><td>${formatA3(item.before, 'expanded')}</td><td>${formatA3(item.optimized, 'expanded')}</td></tr>`).join('');
    $('a3QueryChart').innerHTML = summary.algorithms.flatMap((item) => [
      { name: `${item.name} · 基础`, value: metric(item.before, 'queryP50') },
      { name: `${item.name} · 优化`, value: metric(item.optimized, 'queryP50') }
    ]).map((item) => item).length ? barRows(summary.algorithms.flatMap((item) => [
      { name: `${item.name} · 基础`, queryP50: metric(item.before, 'queryP50') },
      { name: `${item.name} · 优化`, queryP50: metric(item.optimized, 'queryP50') }
    ]), (item) => item.queryP50, (number) => `${number.toFixed(2)} ms`) : '暂无数据';
    $('a3ExpandedChart').innerHTML = barRows(summary.algorithms.flatMap((item) => [
      { name: `${item.name} · 基础`, expanded: metric(item.before, 'expanded') },
      { name: `${item.name} · 优化`, expanded: metric(item.optimized, 'expanded') }
    ]), (item) => item.expanded, (number) => Math.round(number).toLocaleString());
  }

  function metric(value = {}, key) {
    const aliases = {
      queryP50: ['queryP50', 'query_p50_ms', 'query_p50', 'queryP50Ms'],
      expanded: ['expanded', 'expanded_mean', 'expanded_nodes', 'expanded_nodes_mean']
    }[key] || [key];
    const raw = aliases.map((alias) => value[alias]).find((item) => item !== undefined && item !== null);
    return Number(raw || 0);
  }

  function formatA3(value, key) {
    const raw = metric(value, key);
    return key === 'queryP50' ? `${raw.toFixed(3)} ms` : Math.round(raw).toLocaleString();
  }

  function updateA3RunTrace({ request = a3LastRequest, status = null } = {}) {
    const trace = $('a3RunTrace');
    if (!trace) return;
    const runId = status?.run_id || (request && `pending/${request.dataset}/Q${request.query_count}/R${request.rounds}/S${request.seed ?? 'auto'}`) || '—';
    const state = status ? `${status.status || '—'}${status.stage ? ` / ${status.stage}` : ''} / ${Number(status.progress ?? 0)}%` : '—';
    const error = status?.error ? `<div><b>本次错误：</b>${escapeHtml(status.error)}</div>` : '';
    trace.innerHTML = [
      `<div><b>页面：</b>${escapeHtml(`${window.location.origin}${window.location.pathname}`)}</div>`,
      `<div><b>代码目录：</b>${escapeHtml(status?.trace?.code_dir || '服务未返回')}</div>`,
      `<div><b>路网目录：</b>${escapeHtml(status?.trace?.graphml_dir || '服务未返回')}</div>`,
      `<div><b>请求服务：</b>${escapeHtml(status?.trace?.service_url ? `${status.trace.service_url}/run` : `${window.G4_API_CONFIG?.a3BaseUrl || 'http://127.0.0.1:8100/api/benchmark'}/run`)}</div>`,
      `<div><b>本次 run：</b>${escapeHtml(runId)}</div>`,
      `<div><b>状态：</b>${escapeHtml(state)}</div>`,
      error
    ].join('');
  }

  function clearA2Results(datasetName) {
    a2Summary = null;
    $('a2DatasetMeta').textContent = `${datasetName} · 等待本次测试结果`;
    ['a2Cards', 'a2QueryChart', 'a2ExpandedChart', 'a2PreprocessChart', 'a2Table']
      .forEach((id) => { if ($(id)) $(id).innerHTML = ''; });
  }

  async function loadA2(options = {}) {
    const loadToken = ++a2LoadToken;
    setStatus('正在读取 A2 测试结果…', 'live');
    try {
      const config = await window.G4A2Api.getConfig({ force: Boolean(options.forceConfig) });
      if (loadToken !== a2LoadToken) return;
      a2Config = config;
      const datasets = config.datasets || [];
      if (!datasets.length) throw new Error('A2 没有可用路网');
      const defaults = config.defaults || {};
      const selectedId = options.datasetId || $('analysisDataset').value || defaults.dataset || datasets[0].id;
      const dataset = datasets.find((item) => item.id === selectedId) || datasets[0];
      $('analysisDataset').innerHTML = datasets.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
      $('analysisDataset').value = dataset.id;
      if (options.initializeForm !== false && defaults.query_count != null) $('a2QueryCount').value = defaults.query_count;
      if (options.initializeForm !== false && defaults.repeat != null) $('a2Repeat').value = defaults.repeat;
      if (options.initializeForm !== false && defaults.seed != null) $('a2Seed').value = defaults.seed;
      if (options.initializeForm !== false && Array.isArray(defaults.algorithms)) {
        document.querySelectorAll('input[name="a2Algorithm"]').forEach((input) => { input.checked = defaults.algorithms.includes(input.value); });
      }
      if (dataset.data_available === false || dataset.cache_ready === false) {
        let reason = '请先准备缓存';
        try {
          const cacheStatus = await window.G4A2Api.getCacheStatus();
          const cache = (cacheStatus.datasets || []).find((item) => item.dataset === dataset.id);
          reason = cache?.reason || reason;
        } catch (_) { /* 配置状态已经足够继续显示页面 */ }
        setStatus(`已选择${dataset.name}，但预处理缓存未准备：${reason}`, 'error');
        return;
      }
      if (options.showSummary === false) {
        clearA2Results(dataset.name);
        setStatus(`已选择${dataset.name}，请设置参数后开始 A2 测试`, 'ready');
        return;
      }
      try {
        renderA2(await window.G4A2Api.getSummary());
        updateA2RunTrace({ summary: a2Summary });
        setStatus(window.G4_A2_DATA_MODE === 'mock' ? '当前显示 A2 mock 数据' : 'A2 数据已更新', 'ready');
      } catch (error) {
        if (/HTTP 404|尚未生成前端测试结果|尚未生成测试结果/.test(error.message)) {
          $('a2DatasetMeta').textContent = `${dataset.name} · 尚未生成本次接口结果`;
          $('a2Cards').innerHTML = '';
          $('a2QueryChart').innerHTML = '';
          $('a2ExpandedChart').innerHTML = '';
          $('a2PreprocessChart').innerHTML = '';
          $('a2Table').innerHTML = '';
          setStatus('A2 接口已连接，尚未生成测试结果；设置参数后点击“开始 A2 测试”', 'ready');
          return;
        }
        throw error;
      }
    } catch (error) { setStatus(`A2 数据加载失败：${error.message}`, 'error'); }
  }

  function readA2Form() {
    const algorithms = [...document.querySelectorAll('input[name="a2Algorithm"]:checked')].map((input) => input.value);
    if (!algorithms.length) throw new Error('至少选择一种 A2 算法');
    const number = (id, minimum, maximum) => {
      const value = Number($(id).value);
      if (!Number.isInteger(value) || value < minimum || value > maximum) throw new Error(`${id} 参数不在允许范围内`);
      return value;
    };
    return {
      dataset: $('analysisDataset').value,
      algorithms,
      query_count: number('a2QueryCount', 3, 10000),
      repeat: number('a2Repeat', 1, 20),
      seed: number('a2Seed', 0, 4294967295)
    };
  }

  async function runA2Benchmark() {
    if (a2JobTimer) clearTimeout(a2JobTimer);
    if (a2RunActive) return;
    const button = $('a2RunBtn');
    const controls = ['analysisDataset', 'a2QueryCount', 'a2Repeat', 'a2Seed', ...document.querySelectorAll('input[name="a2Algorithm"]')];
    const setBusy = (busy) => controls.forEach((control) => { if (control) control.disabled = busy; });
    try {
      const request = readA2Form();
      a2LastRequest = request;
      a2RunActive = true;
      button.disabled = true;
      setBusy(true);
      clearA2Results($('analysisDataset').selectedOptions[0]?.textContent || request.dataset);
      updateA2RunTrace({ request, status: { status: 'queued', stage: 'queued', progress: 0 } });
      setStatus('正在提交 A2 测试任务…', 'live');
      const job = await window.G4A2Api.createJob(request);
      a2JobStartedAt = Date.now();
      const poll = async () => {
        const status = await window.G4A2Api.getJobStatus(job.job_id);
        updateA2RunTrace({ request, status, summary: status.result || null });
        setStatus(`A2 ${status.stage || status.status} · ${Number(status.progress || 0)}%`, status.status === 'failed' ? 'error' : 'live');
        if (status.status === 'completed') {
          if (status.result) {
            renderA2(status.result);
            updateA2RunTrace({ request, status, summary: status.result });
            setStatus('A2 测试完成，结果已加载', 'ready');
          } else {
            await loadA2({ datasetId: request.dataset, showSummary: true });
          }
          button.disabled = false;
          return;
        }
        if (status.status === 'failed') throw new Error(status.error || 'A2 测试失败');
        if (Date.now() - a2JobStartedAt > 5 * 60 * 1000) {
          throw new Error('A2 测试超过 5 分钟仍未完成，请检查 C++ 测试程序和运行库');
        }
        a2JobTimer = setTimeout(poll, 800);
      };
      await poll();
    } catch (error) {
      updateA2RunTrace({ request: a2LastRequest, status: { status: 'failed', stage: 'failed', progress: 0, error: error.message } });
      setStatus(`A2 测试失败：${error.message}`, 'error');
    } finally {
      a2RunActive = false;
      button.disabled = false;
      setBusy(false);
    }
  }

  function clearA3Results(datasetName) {
    a3Summary = null;
    $('a3DatasetMeta').textContent = `${datasetName} · 等待本次测试结果`;
    ['a3Cards', 'a3QueryChart', 'a3ExpandedChart', 'a3Table'].forEach((id) => { if ($(id)) $(id).innerHTML = ''; });
  }

  function readA3Form() {
    const algorithms = [...document.querySelectorAll('input[name="a3Algorithm"]:checked')].map((input) => input.value);
    if (!algorithms.length) throw new Error('至少选择一种 A3 算法');
    const number = (id, minimum, maximum) => {
      const value = Number($(id).value);
      if (!Number.isInteger(value) || value < minimum || value > maximum) throw new Error(`${id} 参数不在允许范围内`);
      return value;
    };
    const seedValue = $('a3Seed').value.trim();
    const seed = seedValue === '' ? null : Number(seedValue);
    if (seed !== null && (!Number.isSafeInteger(seed) || seed < 0)) throw new Error('a3Seed 必须是安全整数');
    return {
      dataset: $('analysisDataset').value,
      algorithms,
      query_count: number('a3QueryCount', 1, 100),
      rounds: number('a3Rounds', 1, 5),
      seed
    };
  }

  async function runA3Benchmark() {
    if (a3JobTimer) clearTimeout(a3JobTimer);
    if (a3RunActive) return;
    const button = $('a3RunBtn');
    const controls = ['analysisDataset', 'a3QueryCount', 'a3Rounds', 'a3Seed', ...document.querySelectorAll('input[name="a3Algorithm"]')];
    const setBusy = (busy) => controls.forEach((control) => { if (control) control.disabled = busy; });
    try {
      const request = readA3Form();
      a3LastRequest = request;
      a3RunActive = true;
      setBusy(true);
      clearA3Results($('analysisDataset').selectedOptions[0]?.textContent || request.dataset);
      updateA3RunTrace({ request, status: { status: 'queued', stage: 'queued', progress: 0 } });
      setStatus('正在提交 A3 测试任务…', 'live');
      const job = await window.G4A3Api.createJob(request);
      a3JobStartedAt = Date.now();
      const poll = async () => {
        const status = await window.G4A3Api.getJobStatus(job.job_id);
        updateA3RunTrace({ request, status });
        setStatus(`A3 ${status.stage || status.status} · ${Number(status.progress || 0)}%`, status.status === 'failed' ? 'error' : 'live');
        if (status.status === 'completed') {
          renderA3(window.G4A3Api.normalizeSummary(status.result, request.dataset));
          updateA3RunTrace({ request, status });
          setStatus('A3 测试完成，结果已加载', 'ready');
          return;
        }
        if (status.status === 'failed') throw new Error(status.error || 'A3 测试失败');
        if (Date.now() - a3JobStartedAt > 15 * 60 * 1000) throw new Error('A3 测试超过 15 分钟仍未完成，请检查 C++ 编译、路网和缓存');
        a3JobTimer = setTimeout(poll, 1000);
      };
      await poll();
    } catch (error) {
      updateA3RunTrace({ request: a3LastRequest, status: { status: 'failed', stage: 'failed', progress: 0, error: error.message } });
      setStatus(`A3 测试失败：${error.message}`, 'error');
    } finally {
      a3RunActive = false;
      setBusy(false);
    }
  }

  async function loadA3(options = {}) {
    setStatus('正在读取 A3 性能接口…', 'live');
    try {
      const datasets = await window.G4A3Api.getDatasets();
      if (!datasets.length) throw new Error('A3 没有可用路网尺度');
      const selectedId = options.datasetId || $('analysisDataset').value || datasets[0].id;
      const dataset = datasets.find((item) => item.id === selectedId) || datasets[0];
      $('analysisDataset').innerHTML = datasets.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
      $('analysisDataset').value = dataset.id;
      if (options.showSummary === false) {
        clearA3Results(dataset.name);
        setStatus(`已选择${dataset.name}，请设置参数后开始 A3 测试`, 'ready');
        return;
      }
      try {
        renderA3(await window.G4A3Api.getSummary(dataset.id));
        setStatus(window.G4_A3_DATA_MODE === 'mock' ? '当前显示 A3 mock 数据' : 'A3 数据已更新', 'ready');
      } catch (error) {
        if (/HTTP 404|尚未生成 A3 结果|尚未生成/.test(error.message)) {
          clearA3Results(dataset.name);
          setStatus(`已连接 A3 接口，${dataset.name} 尚未生成结果；设置参数后开始测试`, 'ready');
          return;
        }
        throw error;
      }
    } catch (error) { setStatus(`A3 数据加载失败：${error.message}`, 'error'); }
  }

  function setBoard(board) {
    activeBoard = board;
    document.querySelectorAll('[data-analysis-board]').forEach((panel) => { panel.hidden = panel.dataset.analysisBoard !== board; });
    document.querySelectorAll('[data-analysis-tab]').forEach((tab) => tab.classList.toggle('is-active', tab.dataset.analysisTab === board));
    if (board === 'a2' && !a2Summary && analysisOpened) loadA2();
    if (board === 'a3' && !a3Summary) loadA3();
  }

  function init() {
    window.G4ChReplay.init();
    ['analysisOpenBtn', 'analysisTopbarBtn'].forEach((id) => $(id)?.addEventListener('click', () => { analysisOpened = true; $('analysisPanel').hidden = false; setBoard(activeBoard); }));
    $('analysisCloseBtn')?.addEventListener('click', () => { $('analysisPanel').hidden = true; });
    document.querySelectorAll('[data-analysis-tab]').forEach((tab) => tab.addEventListener('click', () => setBoard(tab.dataset.analysisTab)));
    $('analysisDataset')?.addEventListener('change', () => activeBoard === 'a2' ? loadA2({ datasetId: $('analysisDataset').value, showSummary: false, initializeForm: false }) : activeBoard === 'a3' ? loadA3({ datasetId: $('analysisDataset').value, showSummary: false }) : undefined);
    $('a2RunBtn')?.addEventListener('click', runA2Benchmark);
    $('a3RunBtn')?.addEventListener('click', runA3Benchmark);
    $('analysisRefreshBtn')?.addEventListener('click', () => activeBoard === 'a2' ? loadA2({ datasetId: $('analysisDataset').value, showSummary: true, forceConfig: true }) : loadA3({ datasetId: $('analysisDataset').value }));
    setBoard('a2');
  }

  window.addEventListener('DOMContentLoaded', init);
})();
