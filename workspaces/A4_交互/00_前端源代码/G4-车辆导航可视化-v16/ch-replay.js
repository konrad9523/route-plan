(function () {
  let events = [];
  let index = 0;
  let timer = null;
  let mounted = false;
  let replayMeta = {};
  const REPLAY_INTERVAL_MS = 180;

  const $ = (id) => document.getElementById(id);

  function stop() {
    if (timer) window.clearTimeout(timer);
    timer = null;
  }

  function drawEvent(event) {
    if (!mounted) return;
    const info = $('chReplayInfo');
    const progress = $('chReplayProgress');
    if (!info && !progress) return;

    const shortcuts = Array.isArray(event.shortcuts_added) ? event.shortcuts_added : [];
    const current = index + 1;
    const total = Math.max(events.length, Number(event.total) || events.length);
    if (progress) progress.style.width = (Math.round(current / Math.max(1, events.length) * 100) + '%');
    const shortcutCount = Number(event.shortcut_count ?? shortcuts.length ?? event.shortcuts_added ?? 0);
    const rank = event.contracted_node?.rank;
    const rankText = rank == null ? '' : ' · rank ' + rank;
    if (info) {
      info.textContent = '第 ' + current + ' / ' + events.length + ' 个事件 · 收缩节点 ' +
        (event.contracted_node?.id ?? event.contracted_node ?? '—') + rankText +
        ' · 新增捷径 ' + shortcutCount;
    }
    const note = $('chReplayTotalNote');
    if (total > events.length && note) {
      note.textContent = '真实 CH 缓存抽样回放：共 ' + total.toLocaleString() +
        ' 个收缩步骤，当前展示 ' + events.length + ' 个时间点';
    }
    window.G4ChMapReplay?.setIndex(index);
  }

  function play() {
    stop();
    const tick = () => {
      if (index >= events.length) {
        timer = null;
        return;
      }
      drawEvent(events[index]);
      index += 1;
      timer = window.setTimeout(tick, REPLAY_INTERVAL_MS);
    };
    tick();
  }

  function mount(nextEvents, meta = {}) {
    stop();
    events = Array.isArray(nextEvents) ? nextEvents : [];
    index = 0;
    mounted = true;
    window.G4ChMapReplay?.mount({ events, nodes: meta.nodes || {} });
    if (events.length) drawEvent(events[0]);
  }

  function setMeta(meta) {
    replayMeta = meta || {};
    const note = $('chReplayTotalNote');
    if (!note || !replayMeta.total_nodes) return;
    note.textContent = (replayMeta.source || 'CH 缓存') + ' · ' +
      (replayMeta.dataset_name || '路网') + ' · ' +
      Number(replayMeta.total_nodes).toLocaleString() + ' 个节点 · ' +
      Number(replayMeta.total_shortcuts || 0).toLocaleString() + ' 条捷径 · 抽样 ' +
      Number(replayMeta.sampled_events || events.length).toLocaleString() + ' 个时间点';
  }

  function init() {
    $('chReplayPlay')?.addEventListener('click', play);
    $('chReplayPause')?.addEventListener('click', stop);
    $('chReplayReset')?.addEventListener('click', () => {
      stop();
      index = 0;
      if (events.length) drawEvent(events[0]);
    });
    $('chReplayStep')?.addEventListener('click', () => {
      stop();
      index = Math.min(events.length - 1, index + 1);
      if (events.length) drawEvent(events[index]);
    });
    $('chReplayClose')?.addEventListener('click', () => {
      stop();
      window.G4ChMapReplay?.clear();
      const bar = $('chMapReplayBar');
      if (bar) bar.hidden = true;
    });
  }

  window.G4ChReplay = { init, mount, play, stop, setMeta };
})();
