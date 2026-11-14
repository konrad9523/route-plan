(function () {
  const webBaseUrl = () => window.G4_API_CONFIG?.webBaseUrl || window.location.origin;
  const useMock = () => window.G4_CH_DATA_MODE === 'mock';

  async function getEvents(dataset = 'guangdong') {
    const url = useMock()
      ? 'mock/ch-events.json'
      : webBaseUrl() + '/api/ch/events?dataset=' + encodeURIComponent(dataset || 'guangdong');
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = payload.error || payload.detail || payload.message || '';
      } catch (_) { /* Keep the HTTP status when the response is not JSON. */ }
      throw new Error('CH 回放接口 HTTP ' + response.status + (detail ? ': ' + detail : ''));
    }
    const payload = await response.json();
    return Array.isArray(payload) ? { events: payload, source: 'mock' } : payload;
  }

  window.G4ChApi = { getEvents };
})();
