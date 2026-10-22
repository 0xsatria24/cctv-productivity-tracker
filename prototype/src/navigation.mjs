const pages = new Set(['overview', 'live', 'workspaces', 'analytics', 'settings']);
const reportTabs = new Set(['summary', 'daily', 'timeline', 'export']);

export function readRoute(hash) {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?');
  const page = path === 'reports' ? 'analytics' : path === 'cameras' ? 'live' : pages.has(path) ? path : 'overview';
  const tab = path === 'reports' ? 'export' : new URLSearchParams(query).get('tab');
  return { page, tab: reportTabs.has(tab) ? tab : 'summary' };
}

export function routeHash(page, tab = 'summary') {
  if (page === 'reports') return '#/analytics?tab=export';
  return `#/${page}${page === 'analytics' && tab !== 'summary' ? `?tab=${tab}` : ''}`;
}
