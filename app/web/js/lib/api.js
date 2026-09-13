// Cliente HTTP mínimo para la API local.

async function request(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const text = await response.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch { data = text; }
  }
  if (!response.ok) {
    const detail = (data && data.detail) || (typeof data === 'string' ? data : '') || response.statusText;
    throw new Error(detail || `Error ${response.status}`);
  }
  return data;
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body ?? {}),
  put: (url, body) => request('PUT', url, body ?? {}),
  patch: (url, body) => request('PATCH', url, body ?? {}),
  del: (url) => request('DELETE', url),

  // Atajos de uso frecuente
  status: () => request('GET', '/api/status'),
  dashboard: () => request('GET', '/api/dashboard'),
  accounts: (platform) => request('GET', '/api/accounts' + (platform ? `?platform=${platform}` : '')),
  flows: () => request('GET', '/api/flows'),
  flowSchema: () => request('GET', '/api/flows/schema'),
  sources: () => request('GET', '/api/sources'),
  videos: (query = '') => request('GET', '/api/videos' + query),
  clips: (query = '') => request('GET', '/api/clips' + query),
  posts: (query = '') => request('GET', '/api/posts' + query),
  jobs: (query = '') => request('GET', '/api/jobs' + query),
  events: (limit = 40) => request('GET', `/api/events?limit=${limit}`),
  settings: () => request('GET', '/api/settings'),
  analytics: (days = 30) => request('GET', `/api/analytics/overview?days=${days}`),
};
