/* The desktop shell supplies the service ports in the page query string.
 * The normal web launcher keeps the existing 5173/8000/8100 defaults. */
window.G4_DATA_MODE = 'mock';
window.G4_A2_DATA_MODE = 'api';
window.G4_A3_DATA_MODE = 'api';

const g4Query = new URLSearchParams(window.location.search);
const g4Port = (name, fallback) => {
  const value = Number.parseInt(g4Query.get(name) || '', 10);
  return Number.isInteger(value) && value > 0 && value < 65536 ? value : fallback;
};
const g4Origin = window.location.origin;

window.G4_API_CONFIG = {
  webBaseUrl: g4Origin,
  a2BaseUrl: `http://127.0.0.1:${g4Port('a2_port', 8000)}`,
  a3BaseUrl: `http://127.0.0.1:${g4Port('a3_port', 8100)}/api/benchmark`
};
