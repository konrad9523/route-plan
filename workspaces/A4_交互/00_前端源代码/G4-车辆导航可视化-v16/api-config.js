/* Keep each performance board switchable while A2/A3 services are integrated separately. */
window.G4_DATA_MODE = 'mock';
window.G4_A2_DATA_MODE = 'api';
window.G4_A3_DATA_MODE = 'api';
window.G4_API_CONFIG = {
  webBaseUrl: 'http://127.0.0.1:5173',
  a2BaseUrl: 'http://127.0.0.1:8000',
  a3BaseUrl: 'http://127.0.0.1:8100/api/benchmark'
};
