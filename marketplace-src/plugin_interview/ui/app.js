// Luna Interviews pane — standalone plugin UI (left-pane iframe).
// Lists discovery interviews, shows coverage map + transcript + brief.
// Receives the auth token from the shell via postMessage (same handshake as
// the Marketplace pane).

const API = '/api/p/plugin-interview';
let TOKEN = '';
let booted = false;

window.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'luna-auth') {
    TOKEN = e.data.token;
    if (!booted) { booted = true; loadList(); }
  }
});
setTimeout(() => {
  if (!TOKEN) {
    TOKEN = localStorage.getItem('luna.token') || '';
    if (!booted) { booted = true; loadList(); }
  }
}, 500);

async function api(method, path, opts = {}) {
  const init = { method, headers: { Authorization: `Bearer ${TOKEN}` } };
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  return opts.text ? res.text() : res.json();
}

const el = (id) => document.getElementById(id);
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function showError(m) {
  const e = el('error');
  if (m) { e.textContent = m; e.classList.remove('hidden'); }
  else { e.classList.add('hidden'); }
}
function showList() { el('list-view').classList.remove('hidden'); el('detail-view').classList.add('hidden'); }
function showDetail() { el('list-view').classList.add('hidden'); el('detail-view').classList.remove('hidden'); }

function coverageFill(c) {
  if (c >= 7) return 'fill-green';
  if (c >= 4) return 'fill-amber';
  if (c > 0) return 'fill-rose';
  return 'fill-none';
}

// ---- List ----

async function loadList() {
  showError(null);
  el('loading').classList.remove('hidden');
  el('empty').classList.add('hidden');
  let rows;
  try {
    rows = await api('GET', '/interviews');
  } catch (e) {
    el('loading').classList.add('hidden');
    showError(e.message);
    return;
  }
  el('loading').classList.add('hidden');
  el('count').textContent = `${rows.length} ${rows.length === 1 ? 'interview' : 'interviews'}`;

  const list = el('list');
  list.innerHTML = '';
  if (!rows.length) { el('empty').classList.remove('hidden'); return; }

  for (const iv of rows) {
    const pct = Math.max(0, Math.min(100, iv.coverage_pct || 0));
    const btn = document.createElement('button');
    btn.className = 'row';
    btn.setAttribute('data-testid', 'interview-row');
    btn.innerHTML =
      `<span class="ic">▢</span>` +
      `<span class="body">` +
        `<span class="title">${esc(iv.title || iv.goal)}</span>` +
        `<span class="meta"><span>${esc(iv.status)}</span><span>· ${Math.round(iv.coverage_pct || 0)}% covered</span></span>` +
      `</span>` +
      `<span class="ring" style="background:conic-gradient(var(--green) ${pct * 3.6}deg, var(--ink-700) 0deg)"><span class="inner">${Math.round(pct)}</span></span>`;
    btn.addEventListener('click', () => openDetail(iv.id));
    list.appendChild(btn);
  }
}

// ---- Detail ----

let currentId = null;
let currentTitle = '';
let currentBrief = '';

async function openDetail(id) {
  showError(null);
  let st;
  try {
    st = await api('GET', `/interviews/${id}`);
  } catch (e) { showError(e.message); return; }

  currentId = st.id;
  currentTitle = st.title || 'interview';
  el('d-title').textContent = st.title || '';
  el('d-goal').textContent = st.goal || '';
  el('d-status').textContent = st.status || '';
  el('d-coverage').textContent = `${Math.round(st.coverage_pct || 0)}% covered`;
  el('d-ready').classList.toggle('hidden', !st.ready);

  if (st.domain_brief) {
    el('d-domain').textContent = st.domain_brief;
    el('d-domain-wrap').classList.remove('hidden');
  } else {
    el('d-domain-wrap').classList.add('hidden');
  }

  const topics = el('d-topics');
  topics.innerHTML = '';
  if (!(st.topics || []).length) {
    topics.innerHTML = '<div class="muted small">No topics yet.</div>';
  } else {
    for (const t of st.topics) {
      const div = document.createElement('div');
      div.className = 'topic';
      div.setAttribute('data-testid', 'topic-row');
      div.innerHTML =
        `<div class="top"><span class="tname">${esc(t.title || t.key)}</span>` +
        `<span class="prio ${esc(t.priority)}">${esc(t.priority)} · ${t.coverage}/10</span></div>` +
        `<div class="bar"><span class="${coverageFill(t.coverage)}" style="width:${(t.coverage || 0) * 10}%"></span></div>` +
        (t.why ? `<div class="why">why: ${esc(t.why)}</div>` : '') +
        (t.notes ? `<div class="notes">${esc(t.notes)}</div>` : '');
      topics.appendChild(div);
    }
  }

  const turns = el('d-turns');
  turns.innerHTML = '';
  if (!(st.turns || []).length) {
    turns.innerHTML = '<div class="muted small">No answers recorded yet.</div>';
  } else {
    for (const turn of st.turns) {
      const div = document.createElement('div');
      div.className = 'turn';
      const cons = (turn.constraints || []).map((c) => `<span>${esc(c)}</span>`).join('');
      div.innerHTML =
        `<div class="q">Q. ${esc(turn.question)}</div>` +
        `<div class="a">${esc(turn.answer)}</div>` +
        (cons ? `<div class="cons">${cons}</div>` : '');
      turns.appendChild(div);
    }
  }

  el('d-brief').textContent = '…';
  currentBrief = '';
  try {
    currentBrief = await api('GET', `/interviews/${id}/brief`, { text: true });
    el('d-brief').textContent = currentBrief || '…';
  } catch { el('d-brief').textContent = '…'; }

  showDetail();
}

async function deleteCurrent() {
  if (!currentId) return;
  if (!confirm('Delete this interview? This cannot be undone.')) return;
  try {
    await api('DELETE', `/interviews/${currentId}`);
    showList();
    loadList();
  } catch (e) { showError(e.message); }
}

function copyBrief() {
  navigator.clipboard.writeText(currentBrief);
  const b = el('copy-btn');
  const orig = b.textContent;
  b.textContent = '⧉ copied';
  setTimeout(() => { b.textContent = orig; }, 1500);
}

function downloadBrief() {
  const blob = new Blob([currentBrief], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${currentTitle}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

el('refresh-btn').addEventListener('click', loadList);
el('back-btn').addEventListener('click', () => { showList(); loadList(); });
el('delete-btn').addEventListener('click', deleteCurrent);
el('copy-btn').addEventListener('click', copyBrief);
el('download-btn').addEventListener('click', downloadBrief);
