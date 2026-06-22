/* plugin-connectors settings iframe (008.5/phase13) — vanilla port of the old
   SettingsTab.tsx. Provider key setup → app catalog → connect/disconnect →
   Agent/Triggers exposure. Auth via the ?token= query the host appends. */

const BASE = '/api/p/plugin-connectors';
const token = new URLSearchParams(location.search).get('token');

function authHeaders(extra) {
  const h = Object.assign({ 'Content-Type': 'application/json' }, extra || {});
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

async function fetchJSON(url, init) {
  const resp = await fetch(url, Object.assign({}, init, { headers: authHeaders(init && init.headers) }));
  const body = await resp.text();
  if (!resp.ok) {
    const isHtml = body.trimStart().startsWith('<') || (resp.headers.get('content-type') || '').includes('text/html');
    if (isHtml) throw new Error('Service unavailable (HTTP ' + resp.status + '). The upstream provider may be down — try again shortly.');
    try {
      const j = JSON.parse(body);
      throw new Error(j.detail || j.message || j.error || resp.statusText);
    } catch (e) {
      if (e instanceof Error && e.message !== body) throw e;
    }
    throw new Error(body.slice(0, 200) || resp.statusText);
  }
  return body ? JSON.parse(body) : null;
}

const root = document.getElementById('root');
const errBox = document.getElementById('error');
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function showError(m) { if (m) { errBox.textContent = m; errBox.style.display = 'block'; } else { errBox.style.display = 'none'; } }

// --- state ---
const st = {
  status: null,          // {configured, providers, apps}
  catalog: null,         // [AppCard] | null
  apiKey: '',
  search: '',
  busy: null,            // slug | 'key' | null
  searching: false,
  expanded: new Set(),
  keyForms: {},          // slug -> {fields, values, submitting, error}
  accounts: {},          // slug -> {loading, error, data}
  authUrl: null,         // {slug, url}
  glows: {},             // `${slug}:agent` -> 'on'|'off'
};
let pollTimer = null;
let prevApps = null;
const SVG_PLUG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0z M12 16v6"/></svg>';

function spinner() { return '<span class="spinner"></span>'; }

function sourceMeta(p) {
  switch (p.source) {
    case 'host': return { label: p.host_name ? 'Included with ' + esc(p.host_name) : 'Provided by your deployment', cls: 'green' };
    case 'vault': return { label: 'Your key', cls: 'sky' };
    case 'env': return { label: 'From server config (.env)', cls: 'ink' };
    default: return { label: 'Not configured', cls: 'amber' };
  }
}
function srcStyle(cls) {
  const m = {
    green: 'background:rgba(34,197,94,.1);color:#86efac;border:1px solid rgba(34,197,94,.3)',
    sky: 'background:rgba(56,189,248,.1);color:#7dd3fc;border:1px solid rgba(56,189,248,.3)',
    ink: 'background:rgba(107,114,128,.1);color:var(--ink-300);border:1px solid rgba(255,255,255,.1)',
    amber: 'background:rgba(251,191,36,.1);color:#fcd34d;border:1px solid rgba(251,191,36,.3)',
  };
  return m[cls] || m.ink;
}

// --- focus preservation across re-render ---
function snapFocus() {
  const a = document.activeElement;
  if (a && a.dataset && a.dataset.fk) {
    return { fk: a.dataset.fk, s: a.selectionStart, e: a.selectionEnd };
  }
  return null;
}
function restoreFocus(snap) {
  if (!snap) return;
  const el = root.querySelector('[data-fk="' + snap.fk + '"]');
  if (el) { el.focus(); try { el.setSelectionRange(snap.s, snap.e); } catch (_) { /* non-text */ } }
}

function logoHtml(app) {
  if (app.logo) {
    return '<img class="logo" src="' + esc(app.logo) + '" alt="' + esc(app.name) + '" onerror="this.outerHTML=\'<div class=&quot;logo&quot;>' + SVG_PLUG.replace(/"/g, '&quot;') + '</div>\'" />';
  }
  return '<div class="logo">' + SVG_PLUG + '</div>';
}

function accountHtml(app) {
  if (!app.connected) return '<p class="muted">Not connected — no account details.</p>';
  const acct = st.accounts[app.slug];
  if (!acct || acct.loading) return '<div class="muted">' + spinner() + ' Loading account details…</div>';
  if (acct.error) return '<p style="color:#fcd34d;font-size:.78rem">Couldn’t load account details.</p>';
  const d = acct.data;
  if (d.no_auth) return '<p class="muted">No account needed — this service is public and requires no sign-in.</p>';
  const at = d.connected_at ? new Date(d.connected_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : null;
  const expired = d.status && d.status !== 'ACTIVE';
  let id = d.identity
    ? 'Connected as <span style="color:var(--ink-50);font-weight:500">' + esc(d.identity) + '</span>'
    : '<span class="muted">Account connected (identity not available)</span>';
  let meta = [];
  if (d.auth_scheme) meta.push(esc(d.auth_scheme.replace('OAUTH2', 'OAuth')));
  if (at) meta.push('Connected ' + at);
  if (expired) meta.push('<span style="color:#fcd34d">' + (d.status === 'EXPIRED' ? 'Connection expired — reconnect' : esc(d.status)) + '</span>');
  return '<div class="acct" data-testid="account-details-' + esc(app.slug) + '">' + id +
    (meta.length ? '<div class="meta">' + meta.join(' · ') + '</div>' : '') + '</div>';
}

function keyFormHtml(app) {
  const form = st.keyForms[app.slug];
  if (!form) return '';
  let fields = form.fields.map((f) => {
    const v = form.values[f.name] || '';
    return '<label class="block"><span class="lbl">' + esc(f.label) + (f.required ? ' <span class="req">*</span>' : '') + '</span>' +
      '<input data-input="keyfield" data-slug="' + esc(app.slug) + '" data-field="' + esc(f.name) + '" data-fk="kf-' + esc(app.slug) + '-' + esc(f.name) + '" ' +
      'type="' + (f.secret ? 'password' : 'text') + '" value="' + esc(v) + '" autocomplete="off" spellcheck="false" ' +
      'placeholder="' + (f.secret ? '••••••••' : esc(f.default || '')) + '" data-testid="key-input-' + esc(app.slug) + '-' + esc(f.name) + '" />' +
      (f.description ? '<span class="muted" style="font-size:.68rem;display:block;margin-top:.2rem">' + esc(f.description) + '</span>' : '') +
      '</label>';
  }).join('');
  return '<div class="keyform" data-testid="key-form-' + esc(app.slug) + '">' +
    '<div><p style="margin:0;color:var(--ink-100);font-size:.85rem;font-weight:500">Connect ' + esc(app.name) + '</p>' +
    '<p class="muted" style="font-size:.7rem;margin:.2rem 0 0">This service uses an API key. Enter it below — it\'s sent securely to Composio and never stored in Luna.</p></div>' +
    fields +
    (form.error ? '<p class="field-err" data-testid="key-error-' + esc(app.slug) + '">' + esc(form.error) + '</p>' : '') +
    '<div class="row" style="gap:.75rem">' +
    '<button class="primary" data-action="submit-key" data-slug="' + esc(app.slug) + '" data-testid="submit-key-' + esc(app.slug) + '"' + (form.submitting ? ' disabled' : '') + '>' +
    (form.submitting ? spinner() + ' Connecting…' : 'Submit key') + '</button>' +
    '<button class="linkbtn" style="color:var(--ink-400)" data-action="cancel-key" data-slug="' + esc(app.slug) + '" data-testid="cancel-key-' + esc(app.slug) + '">Cancel</button>' +
    '</div></div>';
}

function toggleHtml(kind, app) {
  const on = kind === 'agent' ? app.enabled_agent : app.enabled_triggers;
  const glow = st.glows[app.slug + ':' + kind];
  const style = glow ? ' style="animation:glow-' + glow + ' 3s ease-out"' : '';
  return '<button type="button" role="switch" aria-checked="' + (on ? 'true' : 'false') + '" class="toggle' + (on ? ' on' : '') + '"' +
    (app.connected ? '' : ' disabled') + ' data-action="toggle-' + kind + '" data-slug="' + esc(app.slug) + '"' +
    ' data-testid="toggle-' + kind + '-' + esc(app.slug) + '"' + style + '><span class="knob"></span></button>';
}

function cardHtml(app, fromCatalog) {
  const isBusy = st.busy === app.slug;
  const hasKeyForm = !!st.keyForms[app.slug];
  const expandable = !fromCatalog;
  const isOpen = expandable && st.expanded.has(app.slug);
  let right;
  if (app.connected) right = '<span class="badge-connected">Connected</span>';
  else if (hasKeyForm) right = '<span style="color:var(--luna-300);font-size:.72rem">Enter key below</span>';
  else right = '<button class="primary" data-action="connect" data-slug="' + esc(app.slug) + '" data-testid="connect-' + esc(app.slug) + '"' + (isBusy ? ' disabled' : '') + '>' +
    (isBusy ? spinner() : SVG_PLUG) + ' Connect</button>';

  let authLink = '';
  if (st.authUrl && st.authUrl.slug === app.slug && !app.connected) {
    authLink = '<a href="' + esc(st.authUrl.url) + '" target="_blank" rel="noreferrer" data-testid="auth-link-' + esc(app.slug) + '" style="display:inline-block;margin-top:.4rem;font-size:.75rem">Popup was blocked — click here to authorize ' + esc(app.name) + '</a>';
  }

  const tools = (typeof app.tools_count === 'number' && app.tools_count > 0) ? '<span class="muted" style="font-size:.72rem;flex:none">' + app.tools_count + ' tools</span>' : '';

  let header = '<div class="row hdr"' + (expandable ? ' data-action="toggle-expand" data-slug="' + esc(app.slug) + '" data-testid="connector-header-' + esc(app.slug) + '"' : '') + '>' +
    logoHtml(app) +
    '<div class="grow"><div class="row" style="gap:.5rem"><span class="nm">' + esc(app.name) + '</span>' + tools + '</div>' +
    (app.description ? '<div class="desc">' + esc(app.description) + '</div>' : '') + authLink + '</div>' +
    right +
    (expandable ? '<svg class="chevron' + (isOpen ? ' open' : '') + '" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg>' : '') +
    '</div>';

  let details = '';
  if (isOpen || hasKeyForm) {
    let inner;
    if (hasKeyForm) {
      inner = keyFormHtml(app);
    } else {
      inner = accountHtml(app) +
        '<div style="display:flex;flex-direction:column;gap:.75rem">' +
          '<div class="toggle-line"><div class="grow"><div class="t-title">Agent</div><div class="t-sub">Lets Luna use this app’s tools in chat and tasks — read data and take actions on your behalf.</div></div>' + toggleHtml('agent', app) + '</div>' +
          '<div class="toggle-line"><div class="grow"><div class="t-title">Triggers</div><div class="t-sub">Lets events from this app (new email, new issue…) start your automations and playbooks.</div></div>' + toggleHtml('triggers', app) + '</div>' +
        '</div>' +
        (app.connected ? '<div style="border-top:1px solid rgba(255,255,255,.05);padding-top:.75rem;display:flex;justify-content:flex-end">' +
          '<button class="outline" data-action="disconnect" data-slug="' + esc(app.slug) + '" data-testid="disconnect-' + esc(app.slug) + '"' + (isBusy ? ' disabled' : '') + '>' +
          (isBusy ? spinner() : '⏏') + ' Disconnect</button></div>' : '');
    }
    details = '<div class="details" data-testid="connector-details-' + esc(app.slug) + '">' + inner + '</div>';
  }
  return '<div class="card" data-testid="connector-card-' + esc(app.slug) + '">' + header + details + '</div>';
}

function render() {
  const snap = snapFocus();
  if (st.status === null) {
    root.innerHTML = '<div class="muted">' + spinner() + ' Loading…</div>';
    return;
  }
  const status = st.status;
  let html = '';

  if (!status.configured) {
    html =
      '<div class="card" style="padding:1.25rem">' +
      '<p class="muted" style="margin:0 0 1rem">Connectors are powered by <a href="https://composio.dev" target="_blank" rel="noopener noreferrer">Composio</a>. Paste your API key to enable the catalog (free tier available).</p>' +
      '<label><span class="lbl">Composio API Key</span>' +
      '<input data-input="apikey" data-fk="apikey" type="password" value="' + esc(st.apiKey) + '" placeholder="ak_…" data-testid="connectors-api-key-input" /></label>' +
      '<button class="primary" style="margin-top:1rem" data-action="save-key" data-testid="connectors-save-key-btn"' + (st.busy === 'key' || !st.apiKey.trim() ? ' disabled' : '') + '>' +
      (st.busy === 'key' ? spinner() + ' Validating…' : SVG_PLUG + ' Enable Connectors') + '</button>' +
      '</div>';
    root.innerHTML = html;
    restoreFocus(snap);
    return;
  }

  const composio = (status.providers || []).find((p) => p.name === 'composio');
  const apps = status.apps || [];

  if (composio) {
    const sm = sourceMeta(composio);
    html += '<div class="card src-row" style="margin-bottom:1.25rem" data-testid="connectors-provider-composio">' +
      '<div class="row" style="gap:.5rem"><span style="font-size:.85rem;color:var(--ink-100)">Composio</span>' +
      (composio.base_url_overridden ? '<span class="pill" style="border:1px solid rgba(255,255,255,.1);color:var(--ink-500);text-transform:uppercase;letter-spacing:.03em;font-size:.62rem">proxy</span>' : '') +
      '</div><div class="row" style="gap:.5rem">' +
      (composio.source === 'vault' && composio.key_preview ? '<span style="font-size:.72rem;font-family:ui-monospace,monospace;color:var(--ink-400)" data-testid="connectors-composio-key-preview">' + esc(composio.key_preview) + '</span>' : '') +
      '<span class="pill" style="' + srcStyle(sm.cls) + '" data-testid="connectors-composio-source">' + sm.label + '</span>' +
      (composio.source === 'host' ? '<span class="muted" style="font-size:.72rem">Your own key optional</span>' : '') +
      (composio.source === 'vault' ? '<button class="linkbtn" data-action="remove-key" data-testid="connectors-remove-key-btn"' + (st.busy === 'key' ? ' disabled' : '') + '>' + (st.busy === 'key' ? 'Removing…' : 'Remove') + '</button>' : '') +
      '</div></div>';
  }

  if (apps.length) {
    html += '<div class="section"><h3>Your connectors</h3><div class="list">' + apps.map((a) => cardHtml(a, false)).join('') + '</div></div>';
  }

  html += '<div class="section"><h3>Add a connector</h3>' +
    '<div class="toolbar"><div class="grow">' +
    '<input data-input="search" data-fk="search" value="' + esc(st.search) + '" placeholder="Search platforms — monday, hubspot, stripe…" data-testid="connectors-search-input" /></div>' +
    '<button class="ghost" data-action="search" data-testid="connectors-search-btn"' + (st.searching || !st.search.trim() ? ' disabled' : '') + '>' + (st.searching ? spinner() : 'Search') + '</button>' +
    '</div>';
  if (st.catalog !== null) {
    const filtered = st.catalog.filter((c) => !apps.some((a) => a.slug === c.slug && a.connected));
    if (!filtered.length) html += '<p class="muted">No platforms found.</p>';
    else html += '<div class="list">' + filtered.map((a) => cardHtml(a, true)).join('') + '</div>';
  }
  html += '</div>';

  root.innerHTML = html;
  restoreFocus(snap);
}

// --- data ---
function diffGlow(apps) {
  if (prevApps) {
    apps.forEach((app) => {
      const p = prevApps[app.slug];
      if (!p) return;
      if (p.agent !== app.enabled_agent) triggerGlow(app.slug + ':agent', app.enabled_agent ? 'on' : 'off');
      if (p.triggers !== app.enabled_triggers) triggerGlow(app.slug + ':triggers', app.enabled_triggers ? 'on' : 'off');
    });
  }
  prevApps = {};
  apps.forEach((a) => { prevApps[a.slug] = { agent: a.enabled_agent, triggers: a.enabled_triggers }; });
}
function triggerGlow(key, dir) {
  st.glows[key] = dir;
  setTimeout(() => { delete st.glows[key]; }, 3100);
}

async function refresh() {
  try {
    const s = await fetchJSON(BASE + '/status');
    diffGlow(s.apps || []);
    st.status = s;
    showError(null);
  } catch (e) { showError(e.message); }
  render();
}

async function saveKey() {
  if (!st.apiKey.trim()) return;
  st.busy = 'key'; showError(null); render();
  try {
    await fetchJSON(BASE + '/provider/composio/key', { method: 'POST', body: JSON.stringify({ api_key: st.apiKey.trim() }) });
    st.apiKey = '';
    await refresh();
  } catch (e) { showError(e.message); }
  finally { st.busy = null; render(); }
}

async function removeKey() {
  st.busy = 'key'; render();
  try {
    await fetchJSON(BASE + '/provider/composio/disconnect', { method: 'POST' });
    await refresh();
  } catch (e) { showError(e.message); }
  finally { st.busy = null; render(); }
}

async function runSearch() {
  if (!st.search.trim()) { st.catalog = null; render(); return; }
  st.searching = true; showError(null); render();
  try {
    st.catalog = await fetchJSON(BASE + '/catalog?search=' + encodeURIComponent(st.search.trim()) + '&limit=12');
  } catch (e) { showError(e.message); }
  finally { st.searching = false; render(); }
}

function startPolling(slug) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const r = await fetchJSON(BASE + '/apps/' + slug + '/refresh', { method: 'POST' });
      if (r.connected) {
        clearInterval(pollTimer); pollTimer = null;
        st.authUrl = null; delete st.accounts[slug];
        await refresh();
      }
    } catch (_) { /* keep polling */ }
  }, 2500);
}

async function connect(slug, popup) {
  const app = findApp(slug);
  st.busy = slug; showError(null); st.authUrl = null; render();
  try {
    const res = await fetchJSON(BASE + '/apps/' + slug + '/connect', { method: 'POST' });
    if (res.needs_key && res.fields) {
      if (popup) popup.close();
      const values = {};
      res.fields.forEach((f) => { values[f.name] = f.default || ''; });
      st.keyForms[slug] = { fields: res.fields, values: values, submitting: false };
      st.expanded.add(slug);
      return;
    }
    if (!res.connected && res.redirect_url) {
      if (popup && !popup.closed) popup.location.href = res.redirect_url;
      else st.authUrl = { slug: slug, url: res.redirect_url };
      startPolling(slug);
    } else if (popup) { popup.close(); }
    await refreshAndCatalog();
  } catch (e) {
    if (popup) popup.close();
    showError(e.message);
  } finally {
    st.busy = null; render();
  }
}

async function disconnect(slug) {
  st.busy = slug; showError(null); render();
  try {
    await fetchJSON(BASE + '/apps/' + slug + '/disconnect', { method: 'POST' });
    delete st.accounts[slug];
    await refreshAndCatalog();
  } catch (e) { showError(e.message); }
  finally { st.busy = null; render(); }
}

async function setExposure(slug, field, value) {
  showError(null);
  try {
    await fetchJSON(BASE + '/apps/' + slug + '/exposure', { method: 'POST', body: JSON.stringify({ [field]: value }) });
    await refresh();
  } catch (e) { showError(e.message); render(); }
}

async function submitKey(slug) {
  const form = st.keyForms[slug];
  if (!form) return;
  const missing = form.fields.find((f) => f.required && !(form.values[f.name] || '').trim());
  if (missing) { form.error = missing.label + ' is required'; render(); return; }
  form.submitting = true; form.error = undefined; render();
  try {
    const res = await fetchJSON(BASE + '/apps/' + slug + '/connect-key', { method: 'POST', body: JSON.stringify({ credentials: form.values }) });
    if (res.connected) {
      delete st.keyForms[slug]; st.expanded.delete(slug);
      await refreshAndCatalog();
    } else {
      form.submitting = false;
      form.error = 'Connection ' + (res.status || 'pending') + ' — check the values and try again.';
      render();
    }
  } catch (e) {
    form.submitting = false; form.error = e.message; render();
  }
}

async function loadAccount(slug) {
  st.accounts[slug] = { loading: true }; render();
  try {
    st.accounts[slug] = { loading: false, data: await fetchJSON(BASE + '/apps/' + slug + '/account') };
  } catch (e) { st.accounts[slug] = { loading: false, error: e.message }; }
  render();
}

function toggleExpand(slug) {
  const app = findApp(slug);
  if (st.expanded.has(slug)) st.expanded.delete(slug);
  else {
    st.expanded.add(slug);
    if (app && app.connected && !st.accounts[slug]) loadAccount(slug);
  }
  render();
}

function findApp(slug) {
  const inApps = (st.status && st.status.apps || []).find((a) => a.slug === slug);
  if (inApps) return inApps;
  return (st.catalog || []).find((a) => a.slug === slug) || { slug: slug, name: slug };
}
async function refreshAndCatalog() { await refresh(); if (st.catalog) await runSearch(); }

// --- event delegation ---
root.addEventListener('click', (ev) => {
  const t = ev.target.closest('[data-action]');
  if (!t) return;
  const action = t.dataset.action;
  const slug = t.dataset.slug;
  if (action === 'save-key') return saveKey();
  if (action === 'remove-key') return removeKey();
  if (action === 'search') return runSearch();
  if (action === 'toggle-expand') return toggleExpand(slug);
  if (action === 'disconnect') return disconnect(slug);
  if (action === 'submit-key') { ev.stopPropagation(); return submitKey(slug); }
  if (action === 'cancel-key') { ev.stopPropagation(); delete st.keyForms[slug]; st.expanded.delete(slug); return render(); }
  if (action === 'toggle-agent') { ev.stopPropagation(); const a = findApp(slug); return setExposure(slug, 'agent', !a.enabled_agent); }
  if (action === 'toggle-triggers') { ev.stopPropagation(); const a = findApp(slug); return setExposure(slug, 'triggers', !a.enabled_triggers); }
  if (action === 'connect') {
    ev.stopPropagation();
    // Open the popup synchronously inside the click (popup blockers kill it after await).
    const popup = window.open('about:blank', '_blank', 'width=620,height=760');
    return connect(slug, popup);
  }
});

root.addEventListener('input', (ev) => {
  const t = ev.target;
  const kind = t.dataset && t.dataset.input;
  if (!kind) return;
  if (kind === 'apikey') {
    const wasEmpty = !st.apiKey.trim();
    st.apiKey = t.value;
    // Toggle the Enable button's disabled state without a full re-render (keeps focus).
    if (wasEmpty !== !st.apiKey.trim()) {
      const btn = root.querySelector('[data-action="save-key"]');
      if (btn) btn.disabled = !st.apiKey.trim();
    }
  } else if (kind === 'search') {
    const wasEmpty = !st.search.trim();
    st.search = t.value;
    if (wasEmpty !== !st.search.trim()) {
      const btn = root.querySelector('[data-action="search"]');
      if (btn) btn.disabled = !st.search.trim();
    }
  } else if (kind === 'keyfield') {
    const form = st.keyForms[t.dataset.slug];
    if (form) form.values[t.dataset.field] = t.value;
  }
});

root.addEventListener('keydown', (ev) => {
  const t = ev.target;
  if (ev.key !== 'Enter') return;
  const kind = t.dataset && t.dataset.input;
  if (kind === 'search') runSearch();
  else if (kind === 'apikey') saveKey();
  else if (kind === 'keyfield') submitKey(t.dataset.slug);
});

// --- live updates: the plugin emits connectors.app_changed on the bus ---
try {
  const es = new EventSource('/api/events?topics=' + encodeURIComponent('connectors.*'));
  es.addEventListener('connectors.app_changed', () => refresh());
} catch (_) { /* SSE optional */ }

refresh();
