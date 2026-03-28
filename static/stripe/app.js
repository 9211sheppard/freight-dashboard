/* stripe/app.js — Contacts Dashboard (Stripe Theme) */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  sort:     'company_name',
  dir:      'asc',
  network:  '',
  verify:   '',
  page:     1,
  perPage:  50,
  totalPages: 1,
};

// ── DOM refs ──────────────────────────────────────────────────────────────
const searchCountry = document.getElementById('searchCountry');
const searchCompany = document.getElementById('searchCompany');
const searchName    = document.getElementById('searchName');
const filterEmail   = document.getElementById('filterEmail');
const filterPhone   = document.getElementById('filterPhone');
const sortByEl      = document.getElementById('sortBy');
const sortDirEl     = document.getElementById('sortDir');
const resultsBody   = document.getElementById('resultsBody');
const resultCount   = document.getElementById('resultCount');
const dbTotal       = document.getElementById('dbTotal');
const exportBtn     = document.getElementById('exportBtn');
const spinner       = document.getElementById('spinner');
const statTotalContacts = document.getElementById('statTotalContacts');
const statCountries     = document.getElementById('statCountries');
const statNetworks      = document.getElementById('statNetworks');

// ── Debounce ──────────────────────────────────────────────────────────────
let debounceTimer = null;
function debounce(fn, ms = 280) {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(fn, ms);
}

// ── Build query params ────────────────────────────────────────────────────
function buildParams() {
  const p = new URLSearchParams();
  const country = searchCountry.value.trim();
  const company = searchCompany.value.trim();
  const name    = searchName.value.trim();
  if (country)              p.set('country',   country);
  if (company)              p.set('company',   company);
  if (name)                 p.set('name',      name);
  if (state.network)        p.set('network',   state.network);
  if (state.verify)         p.set('verify',    state.verify);
  if (filterEmail.checked)  p.set('has_email', '1');
  if (filterPhone.checked)  p.set('has_phone', '1');
  p.set('sort', state.sort);
  p.set('dir',  state.dir);
  p.set('page', state.page);
  p.set('per_page', state.perPage);
  return p;
}

// ── Escape HTML ───────────────────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Verification badge ────────────────────────────────────────────────────
function verifyBadge(r) {
  const s = r.verified_status || 'unverified';
  if (s === 'unverified') return '';
  const cfg = {
    verified: { cls: 's-badge--success', label: 'Verified' },
    review:   { cls: 's-badge--warning', label: 'Review' },
    flagged:  { cls: 's-badge--danger',  label: 'Flagged' },
  }[s] || { cls: 's-badge--default', label: 'Unchecked' };
  const score = r.verified_score ? ` ${r.verified_score}` : '';
  return `<span class="s-badge ${cfg.cls}" style="margin-left:6px;">${cfg.label}${score}</span>`;
}

// ── Network badge color ───────────────────────────────────────────────────
function networkBadge(network) {
  if (!network) return '';
  const colors = {
    'WFA':            's-badge--primary',
    'WWPC':           's-badge--info',
    'FIATA':          's-badge--success',
    'Freightnet-FF':  's-badge--warning',
    'Freightnet-Air': 's-badge--warning',
    'AHK-Japan':      's-badge--danger',
  };
  return `<span class="s-badge ${colors[network] || 's-badge--default'}">${esc(network)}</span>`;
}

// ── Render table ──────────────────────────────────────────────────────────
function renderTable(data) {
  if (!data.results || data.results.length === 0) {
    resultsBody.innerHTML = `<tr><td colspan="5" class="s-table-empty">
      <i class="bi bi-inbox"></i>No contacts match your search.
    </td></tr>`;
    resultCount.textContent = '0 results';
    return;
  }

  const rows = data.results.map(r => `
    <tr>
      <td>${networkBadge(r.network)}</td>
      <td>
        <div style="font-weight:500;">
          ${r.website_url
            ? `<a href="${esc(r.website_url)}" target="_blank" rel="noopener" style="color:var(--s-text);text-decoration:none;">${esc(r.company_name)} <i class="bi bi-box-arrow-up-right" style="font-size:10px;color:var(--s-text-3);"></i></a>`
            : (esc(r.company_name) || '<span style="color:var(--s-text-3);">—</span>')}
          ${verifyBadge(r)}
          ${r.id ? `<button class="s-btn s-btn-ghost s-btn-sm intel-btn" data-id="${r.id}" title="Intelligence" style="padding:2px 4px;margin-left:4px;"><i class="bi bi-person-badge"></i></button>` : ''}
        </div>
        ${r.contact_name ? `<div style="font-size:12px;color:var(--s-text-2);margin-top:2px;"><i class="bi bi-person" style="margin-right:4px;"></i>${esc(r.contact_name)}</div>` : ''}
      </td>
      <td>${r.email
        ? `<a href="mailto:${esc(r.email)}" style="font-size:13px;color:var(--s-text-link);"><i class="bi bi-envelope" style="margin-right:4px;"></i>${esc(r.email)}</a>`
        : '<span style="color:var(--s-text-3);">—</span>'}</td>
      <td>${r.phone_number
        ? `<span style="font-size:13px;"><i class="bi bi-telephone" style="margin-right:4px;color:var(--s-text-3);"></i>${esc(r.phone_number)}</span>`
        : '<span style="color:var(--s-text-3);">—</span>'}</td>
      <td>
        <span style="font-weight:500;">${esc(r.country) || '—'}</span>
        ${r.city ? `<div style="font-size:12px;color:var(--s-text-2);margin-top:2px;">${esc(r.city)}</div>` : ''}
      </td>
    </tr>`).join('');

  resultsBody.innerHTML = rows;

  // Intelligence card buttons
  resultsBody.querySelectorAll('.intel-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      showIntelCard(btn.dataset.id);
    });
  });

  const n = data.count;
  const pageInfo = data.total_pages > 1 ? ` · page ${data.page} of ${data.total_pages}` : '';
  resultCount.innerHTML = `<strong>${n.toLocaleString()}</strong> result${n !== 1 ? 's' : ''}${pageInfo}`;

  state.page = data.page;
  state.totalPages = data.total_pages;
  renderPagination();
}

// ── Pagination ────────────────────────────────────────────────────────────
function renderPagination() {
  let wrap = document.getElementById('paginationWrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'paginationWrap';
    wrap.style.cssText = 'display:flex;justify-content:center;align-items:center;gap:4px;margin-top:16px;';
    const card = document.getElementById('resultsTable')?.closest('.s-card');
    if (card) card.parentNode.insertBefore(wrap, card.nextSibling);
    else return;
  }
  if (state.totalPages <= 1) { wrap.innerHTML = ''; return; }

  const p = state.page, tp = state.totalPages;
  let btns = '';
  btns += `<button class="s-btn s-btn-secondary s-btn-sm" ${p <= 1 ? 'disabled' : ''} data-pg="${p-1}"><i class="bi bi-chevron-left"></i></button>`;
  const start = Math.max(1, p - 2), end = Math.min(tp, p + 2);
  if (start > 1) btns += `<button class="s-btn s-btn-ghost s-btn-sm" data-pg="1">1</button>`;
  if (start > 2) btns += `<span style="color:var(--s-text-3);padding:0 4px;">...</span>`;
  for (let i = start; i <= end; i++) {
    btns += `<button class="s-btn ${i === p ? 's-btn-primary' : 's-btn-ghost'} s-btn-sm" data-pg="${i}">${i}</button>`;
  }
  if (end < tp - 1) btns += `<span style="color:var(--s-text-3);padding:0 4px;">...</span>`;
  if (end < tp) btns += `<button class="s-btn s-btn-ghost s-btn-sm" data-pg="${tp}">${tp}</button>`;
  btns += `<button class="s-btn s-btn-secondary s-btn-sm" ${p >= tp ? 'disabled' : ''} data-pg="${p+1}"><i class="bi bi-chevron-right"></i></button>`;

  wrap.innerHTML = btns;
  wrap.querySelectorAll('button[data-pg]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.page = parseInt(btn.dataset.pg, 10);
      fetchResults();
      document.getElementById('resultsTable')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

// ── Search prompt ─────────────────────────────────────────────────────────
function hasActiveFilters() {
  return searchCountry.value.trim() || searchCompany.value.trim() ||
         searchName.value.trim() || state.network || state.verify ||
         filterEmail.checked || filterPhone.checked;
}

function showSearchPrompt() {
  resultsBody.innerHTML = `<tr><td colspan="5" class="s-table-empty">
    <i class="bi bi-search"></i>Start typing to search contacts
  </td></tr>`;
  resultCount.innerHTML = '<span style="color:var(--s-text-3);">Search to see results</span>';
  const wrap = document.getElementById('paginationWrap');
  if (wrap) wrap.innerHTML = '';
}

// ── Fetch results ─────────────────────────────────────────────────────────
async function fetchResults() {
  if (!hasActiveFilters()) { showSearchPrompt(); return; }
  try {
    const res  = await fetch('/api/search?' + buildParams());
    const data = await res.json();
    renderTable(data);
  } catch (err) {
    resultsBody.innerHTML = `<tr><td colspan="5" class="s-table-empty" style="color:var(--s-danger);">
      <i class="bi bi-exclamation-triangle"></i>Error loading results
    </td></tr>`;
  }
}

// ── Fetch stats ───────────────────────────────────────────────────────────
async function fetchStats() {
  try {
    const res  = await fetch('/api/stats');
    const data = await res.json();
    const t = data.total.toLocaleString();
    if (dbTotal) dbTotal.textContent = `${t} total in database`;
    if (statTotalContacts) statTotalContacts.textContent = t;
    if (statCountries) statCountries.textContent = (data.countries || 0).toLocaleString();
    if (statNetworks) statNetworks.textContent = (data.networks || 0).toLocaleString();
  } catch (_) {}
}

// ── Export ─────────────────────────────────────────────────────────────────
if (exportBtn) {
  exportBtn.addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = '/api/export?' + buildParams();
    a.download = 'contacts_export.csv';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  });
}

// ── Sort via column headers ───────────────────────────────────────────────
document.querySelectorAll('.sortable-col').forEach(th => {
  th.style.cursor = 'pointer';
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (state.sort === col) { state.dir = state.dir === 'asc' ? 'desc' : 'asc'; }
    else { state.sort = col; state.dir = 'asc'; }
    sortByEl.value  = state.sort;
    sortDirEl.value = state.dir;
    fetchResults();
  });
});

// ── Sort dropdowns ────────────────────────────────────────────────────────
sortByEl.addEventListener('change', () => { state.sort = sortByEl.value; state.page = 1; fetchResults(); });
sortDirEl.addEventListener('change', () => { state.dir = sortDirEl.value; state.page = 1; fetchResults(); });

// ── Network filter ────────────────────────────────────────────────────────
document.querySelectorAll('#networkFilter button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#networkFilter button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.network = btn.dataset.network;
    state.page = 1;
    fetchResults();
  });
});

// ── Verify filter ─────────────────────────────────────────────────────────
document.querySelectorAll('#verifyFilter button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#verifyFilter button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.verify = btn.dataset.verify;
    state.page = 1;
    fetchResults();
  });
});

// ── Verify stats ──────────────────────────────────────────────────────────
const verifyStatsEl = document.getElementById('verifyStats');
async function fetchVerifyStats() {
  try {
    const res = await fetch('/api/verify-stats');
    const d   = await res.json();
    if (!verifyStatsEl) return;
    const pct = d.total ? Math.round(d.verified / d.total * 100) : 0;
    verifyStatsEl.innerHTML =
      `<span style="color:var(--s-success);font-weight:600;">${d.verified.toLocaleString()}</span> verified · ` +
      `<span style="color:var(--s-warning);">${d.review.toLocaleString()}</span> review · ` +
      `<span style="color:var(--s-danger);">${d.flagged.toLocaleString()}</span> flagged · ` +
      `${d.unverified.toLocaleString()} unchecked (${pct}%)`;
  } catch (_) {}
}

// ── Search inputs (debounced) ─────────────────────────────────────────────
function resetPageAndFetch() { state.page = 1; fetchResults(); }
searchCountry.addEventListener('input', () => debounce(resetPageAndFetch));
searchCompany.addEventListener('input', () => debounce(resetPageAndFetch));
searchName.addEventListener('input',    () => debounce(resetPageAndFetch));
filterEmail.addEventListener('change', resetPageAndFetch);
filterPhone.addEventListener('change', resetPageAndFetch);

// ── Refresh button ────────────────────────────────────────────────────────
const refreshBtn = document.getElementById('refreshBtn');
if (refreshBtn) {
  refreshBtn.addEventListener('click', async () => {
    refreshBtn.disabled = true;
    try {
      const res  = await fetch('/api/refresh', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        fetchResults(); fetchStats();
        if (window.sToast) sToast(`Refreshed — ${data.row_count.toLocaleString()} contacts`);
      }
    } catch (_) {} finally { refreshBtn.disabled = false; }
  });
}

// ── Import CSV ────────────────────────────────────────────────────────────
const importCsvBtn = document.getElementById('importCsvBtn');
const csvFileInput = document.getElementById('csvFileInput');
if (importCsvBtn) importCsvBtn.addEventListener('click', () => csvFileInput.click());
if (csvFileInput) {
  csvFileInput.addEventListener('change', async () => {
    const file = csvFileInput.files[0];
    if (!file) return;
    importCsvBtn.disabled = true;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/upload-csv', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.ok) {
        fetchResults(); fetchStats();
        if (window.sToast) sToast(`${data.network} imported — ${data.imported.toLocaleString()} contacts`);
      }
    } catch (_) {} finally {
      importCsvBtn.disabled = false;
      csvFileInput.value = '';
    }
  });
}

// ── Intelligence Card ─────────────────────────────────────────────────────
async function showIntelCard(contactId) {
  const backdrop = document.getElementById('intelModalBackdrop');
  const body = document.getElementById('intelModalBody');
  if (!backdrop || !body) return;

  body.innerHTML = '<div style="text-align:center;padding:24px;"><div class="s-spinner" style="margin:0 auto;"></div></div>';
  backdrop.classList.add('open');

  try {
    const res = await fetch(`/api/contacts/${contactId}/intelligence`);
    const data = await res.json();
    if (!data.ok) { body.innerHTML = `<p style="color:var(--s-danger);">${data.error}</p>`; return; }

    const c = data.contact;
    const b = data.behavior;
    const r = data.rates;
    const prep = data.call_prep || [];

    const score = c.score || 0;
    const barPct = Math.min(score, 100);
    const barColor = score >= 85 ? 'var(--s-success)' : score >= 60 ? 'var(--s-info)' : score >= 35 ? 'var(--s-warning)' : 'var(--s-danger)';

    body.innerHTML = `
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">
        <div style="width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#635bff,#7c3aed);color:#fff;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;">
          <i class="bi bi-person-fill"></i>
        </div>
        <div>
          <div style="font-size:17px;font-weight:600;">${esc(c.name || c.company)}</div>
          <div style="font-size:13px;color:var(--s-text-2);">${esc(c.company)} · ${esc(c.country)}${c.city ? ', ' + esc(c.city) : ''}</div>
          <div style="font-size:13px;margin-top:2px;">
            ${c.email ? `<i class="bi bi-envelope" style="margin-right:4px;"></i>${esc(c.email)}` : ''}
            ${c.phone ? ` · <i class="bi bi-telephone" style="margin-right:4px;"></i>${esc(c.phone)}` : ''}
          </div>
        </div>
      </div>

      <div style="margin-bottom:24px;">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">
          <div style="font-size:32px;font-weight:700;color:${barColor};line-height:1;">${score}</div>
          <div style="flex:1;">
            <div style="height:8px;background:var(--s-border-light);border-radius:4px;overflow:hidden;">
              <div style="height:100%;width:${barPct}%;background:${barColor};border-radius:4px;transition:width 0.3s;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--s-text-3);margin-top:4px;">
              <span>0</span><span>50 Verified</span><span>85 Full</span><span>100</span>
            </div>
          </div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div style="padding:16px;background:var(--s-bg);border-radius:var(--s-radius-lg);">
          <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:var(--s-text-3);margin-bottom:8px;">Behavior</div>
          <span class="s-badge s-badge--${b.type === 'fast' ? 'success' : b.type === 'balanced' ? 'info' : 'warning'}">${b.type.toUpperCase()}</span>
          <div style="font-size:13px;color:var(--s-text-2);margin-top:6px;">${esc(b.label)}</div>
          <div style="font-size:12px;color:var(--s-text-3);margin-top:4px;">
            ${b.avg_hours ? `Avg: ${b.avg_hours}h · ` : ''}Sent: ${b.email_count} · Replies: ${b.response_count}
          </div>
        </div>
        <div style="padding:16px;background:var(--s-bg);border-radius:var(--s-radius-lg);">
          <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:var(--s-text-3);margin-bottom:8px;">Rates</div>
          <div style="font-size:13px;">Received: <strong>${r.total_received}</strong></div>
          <div style="font-size:13px;">Complete: <strong>${r.complete}</strong></div>
          <div style="font-size:13px;">Reliability: <strong>${r.reliability_pct}%</strong></div>
        </div>
      </div>

      ${prep.length ? `
      <div style="padding:16px;background:var(--s-bg);border-radius:var(--s-radius-lg);">
        <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:var(--s-text-3);margin-bottom:8px;">Call Prep</div>
        <ul style="margin:0;padding-left:16px;">${prep.map(line => `<li style="font-size:13px;color:var(--s-text-2);margin-bottom:4px;">${esc(line)}</li>`).join('')}</ul>
      </div>` : ''}
    `;
  } catch(e) {
    body.innerHTML = `<p style="color:var(--s-danger);">Failed to load intelligence card.</p>`;
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
fetchStats();
showSearchPrompt();
fetchVerifyStats();
setInterval(fetchVerifyStats, 60000);
