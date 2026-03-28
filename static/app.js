/* app.js — WFA Contacts Dashboard */
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
const clearCountry  = document.getElementById('clearCountry');
const clearCompany  = document.getElementById('clearCompany');
const clearName     = document.getElementById('clearName');
const clearAll      = document.getElementById('clearAll');
const navDbCount    = document.getElementById('nav-db-count');
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

// ── Escape HTML to prevent XSS ────────────────────────────────────────────
function esc(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Verification badge helper ─────────────────────────────────────────────
function verifyBadge(r) {
  const s = r.verified_status || 'unverified';
  if (s === 'unverified') return '';   // no badge until checked

  const cfg = {
    verified: { cls: 'verify-verified',  icon: '✅', label: 'Verified' },
    review:   { cls: 'verify-review',    icon: '⚠️', label: 'Review'   },
    flagged:  { cls: 'verify-flagged',   icon: '❌', label: 'Flagged'  },
  }[s] || { cls: 'verify-unverified', icon: '⬜', label: 'Unchecked' };

  const score   = r.verified_score ? ` ${r.verified_score}/100` : '';
  const website = r.website_url
    ? `<a href="${esc(r.website_url)}" target="_blank" rel="noopener" title="Visit website">
         <i class="bi bi-box-arrow-up-right"></i></a>`
    : '';
  const linkedin = r.linkedin_url
    ? `<a href="${esc(r.linkedin_url)}" target="_blank" rel="noopener" title="LinkedIn">
         <i class="bi bi-linkedin"></i></a>`
    : '';

  return `<span class="verify-badge ${cfg.cls}" title="${cfg.label}${score}">
    ${cfg.icon}${score}${website}${linkedin}
  </span>`;
}

// ── Render table ──────────────────────────────────────────────────────────
function renderTable(data) {
  if (!data.results || data.results.length === 0) {
    resultsBody.innerHTML = `
      <tr><td colspan="5">
        <div class="empty-state">
          <i class="bi bi-inbox"></i>
          No contacts match your search.
        </div>
      </td></tr>`;
    resultCount.innerHTML = '<span class="fw-medium">0</span> results';
    return;
  }

  const rows = data.results.map(r => `
    <tr>
      <td>${r.network
        ? `<span class="badge-network badge-network-${(r.network||'').toLowerCase()}">${esc(r.network)}</span>`
        : ''}</td>
      <td>
        <div class="fw-medium d-flex align-items-center gap-2">
          <span>
            ${r.website_url
              ? `<a href="${esc(r.website_url)}" target="_blank" rel="noopener" class="company-link" title="Open website">${esc(r.company_name)}<i class="bi bi-box-arrow-up-right ms-1 small"></i></a>`
              : (esc(r.company_name) || '<span class="text-muted">—</span>')}
            ${verifyBadge(r)}
          </span>
          ${r.id ? `<button class="btn btn-sm btn-outline-info intel-btn py-0 px-1" data-id="${r.id}" title="Intelligence Card"><i class="bi bi-person-badge"></i></button>` : ''}
        </div>
        ${r.contact_name ? `<div class="text-muted small mt-1"><i class="bi bi-person me-1"></i>${esc(r.contact_name)}</div>` : ''}
      </td>
      <td>${r.email
        ? `<span class="badge-email email-clickable" data-email="${esc(r.email)}" title="Click to send email">
             <i class="bi bi-envelope me-1"></i>${esc(r.email)}
             <i class="bi bi-chevron-down ms-1 email-arrow"></i>
           </span>`
        : '<span class="text-muted small">—</span>'}</td>
      <td>${r.phone_number
        ? `<span class="badge-phone"><i class="bi bi-telephone me-1"></i>${esc(r.phone_number)}</span>`
        : '<span class="text-muted small">—</span>'}</td>
      <td>
        <span class="badge-country">${esc(r.country) || '—'}</span>
        ${r.city ? `<div class="text-muted small mt-1"><i class="bi bi-geo-alt me-1"></i>${esc(r.city)}</div>` : ''}
      </td>
    </tr>`).join('');

  resultsBody.innerHTML = rows;

  // Attach click handlers to all email badges
  resultsBody.querySelectorAll('.email-clickable').forEach(el => {
    el.addEventListener('click', e => {
      e.stopPropagation();
      showEmailPicker(el.dataset.email, el);
    });
  });

  // Intelligence card buttons
  resultsBody.querySelectorAll('.intel-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      showIntelCard(btn.dataset.id);
    });
  });

  const n = data.count;
  const showing = data.results.length;
  const pageInfo = data.total_pages > 1
    ? ` · page ${data.page} of ${data.total_pages}`
    : '';
  resultCount.innerHTML = `<span class="fw-semibold">${n.toLocaleString()}</span> result${n !== 1 ? 's' : ''}${pageInfo}`;

  // Update pagination state
  state.page = data.page;
  state.totalPages = data.total_pages;
  renderPagination();
}

// ── Pagination controls ──────────────────────────────────────────────────
function renderPagination() {
  let wrap = document.getElementById('paginationWrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'paginationWrap';
    wrap.className = 'd-flex justify-content-center align-items-center gap-2 mt-3 mb-2';
    const tableCard = document.getElementById('resultsTable')?.closest('.card');
    if (tableCard) tableCard.parentNode.insertBefore(wrap, tableCard.nextSibling);
    else return;
  }

  if (state.totalPages <= 1) { wrap.innerHTML = ''; return; }

  const p = state.page;
  const tp = state.totalPages;
  let btns = '';

  btns += `<button class="btn btn-sm btn-outline-primary" ${p <= 1 ? 'disabled' : ''} data-pg="${p - 1}"><i class="bi bi-chevron-left"></i></button>`;

  // Show up to 5 page buttons around current page
  const start = Math.max(1, p - 2);
  const end = Math.min(tp, p + 2);
  if (start > 1) btns += `<button class="btn btn-sm btn-outline-secondary" data-pg="1">1</button>`;
  if (start > 2) btns += `<span class="text-muted px-1">…</span>`;
  for (let i = start; i <= end; i++) {
    btns += `<button class="btn btn-sm ${i === p ? 'btn-primary' : 'btn-outline-secondary'}" data-pg="${i}">${i}</button>`;
  }
  if (end < tp - 1) btns += `<span class="text-muted px-1">…</span>`;
  if (end < tp) btns += `<button class="btn btn-sm btn-outline-secondary" data-pg="${tp}">${tp}</button>`;

  btns += `<button class="btn btn-sm btn-outline-primary" ${p >= tp ? 'disabled' : ''} data-pg="${p + 1}"><i class="bi bi-chevron-right"></i></button>`;

  wrap.innerHTML = btns;
  wrap.querySelectorAll('button[data-pg]').forEach(btn => {
    btn.addEventListener('click', () => {
      state.page = parseInt(btn.dataset.pg, 10);
      fetchResults();
      // Scroll to top of table
      document.getElementById('resultsTable')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

// ── Search prompt (no results loaded until user searches) ────────────────
function hasActiveFilters() {
  return searchCountry.value.trim() || searchCompany.value.trim() ||
         searchName.value.trim() || state.network || state.verify ||
         filterEmail.checked || filterPhone.checked;
}

function showSearchPrompt() {
  resultsBody.innerHTML = `
    <tr><td colspan="5">
      <div class="empty-state">
        <i class="bi bi-search"></i>
        Start typing a country, company, or name to search contacts.
      </div>
    </td></tr>`;
  resultCount.innerHTML = '<span class="text-muted">Search to see results</span>';
  // Clear pagination
  const wrap = document.getElementById('paginationWrap');
  if (wrap) wrap.innerHTML = '';
}

// ── Fetch & display results ───────────────────────────────────────────────
async function fetchResults() {
  // Don't fetch if no filters are active — show prompt instead
  if (!hasActiveFilters()) {
    showSearchPrompt();
    return;
  }
  document.body.classList.add('loading');
  try {
    const res  = await fetch('/api/search?' + buildParams());
    const data = await res.json();
    renderTable(data);
  } catch (err) {
    resultsBody.innerHTML = `<tr><td colspan="4" class="text-danger text-center py-3">
      <i class="bi bi-exclamation-triangle me-1"></i>Error loading results. Is the server running?
    </td></tr>`;
    resultCount.textContent = '';
  } finally {
    document.body.classList.remove('loading');
  }
}

// ── Fetch DB total ────────────────────────────────────────────────────────
async function fetchStats() {
  try {
    const res  = await fetch('/api/stats');
    const data = await res.json();
    const t = data.total.toLocaleString();
    dbTotal.textContent    = `${t} total contacts in database`;
    navDbCount.textContent = `${t} contacts`;
    if (statTotalContacts) statTotalContacts.textContent = t;
    if (statCountries) statCountries.textContent = (data.countries || 0).toLocaleString();
    if (statNetworks) statNetworks.textContent = (data.networks || 0).toLocaleString();
  } catch (_) { /* silently ignore */ }
}

// ── Export ────────────────────────────────────────────────────────────────
exportBtn.addEventListener('click', () => {
  const url = '/api/export?' + buildParams();
  const a   = document.createElement('a');
  a.href    = url;
  a.download = 'contacts_export.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
});

// ── Sort via column headers ───────────────────────────────────────────────
document.querySelectorAll('.sortable-col').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (state.sort === col) {
      state.dir = state.dir === 'asc' ? 'desc' : 'asc';
    } else {
      state.sort = col;
      state.dir  = 'asc';
    }
    // sync dropdowns
    sortByEl.value  = state.sort;
    sortDirEl.value = state.dir;

    // update header styles
    document.querySelectorAll('.sortable-col').forEach(el => {
      el.classList.remove('active-sort');
      el.querySelector('.sort-icon').className = 'bi bi-chevron-expand sort-icon';
    });
    th.classList.add('active-sort');
    const icon = th.querySelector('.sort-icon');
    icon.className = state.dir === 'asc'
      ? 'bi bi-chevron-up sort-icon'
      : 'bi bi-chevron-down sort-icon';

    fetchResults();
  });
});

// ── Sort dropdowns ────────────────────────────────────────────────────────
sortByEl.addEventListener('change', () => {
  state.sort = sortByEl.value;
  state.page = 1;
  fetchResults();
});
sortDirEl.addEventListener('change', () => {
  state.dir = sortDirEl.value;
  state.page = 1;
  fetchResults();
});

// ── Network filter buttons ────────────────────────────────────────────────
document.querySelectorAll('#networkFilter button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#networkFilter button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.network = btn.dataset.network;
    state.page = 1;
    fetchResults();
  });
});

// ── Verification filter buttons ───────────────────────────────────────────
document.querySelectorAll('#verifyFilter button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#verifyFilter button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.verify = btn.dataset.verify;
    state.page = 1;
    fetchResults();
  });
});

// ── Fetch & show verification stats ──────────────────────────────────────
const verifyStatsEl = document.getElementById('verifyStats');
async function fetchVerifyStats() {
  try {
    const res  = await fetch('/api/verify-stats');
    const d    = await res.json();
    if (!verifyStatsEl) return;
    const pct = d.total ? Math.round(d.verified / d.total * 100) : 0;
    verifyStatsEl.innerHTML =
      `<span class="text-success fw-semibold">${d.verified.toLocaleString()} verified</span> · ` +
      `<span class="text-warning">${d.review.toLocaleString()} review</span> · ` +
      `<span class="text-danger">${d.flagged.toLocaleString()} flagged</span> · ` +
      `<span class="text-muted">${d.unverified.toLocaleString()} unchecked</span> ` +
      `<span class="text-muted">(${pct}% done)</span>`;
  } catch (_) { /* ignore */ }
}

// ── Search inputs (debounced) ─────────────────────────────────────────────
function resetPageAndFetch() { state.page = 1; fetchResults(); }
searchCountry.addEventListener('input', () => debounce(resetPageAndFetch));
searchCompany.addEventListener('input', () => debounce(resetPageAndFetch));
searchName.addEventListener('input',    () => debounce(resetPageAndFetch));
filterEmail.addEventListener('change', resetPageAndFetch);
filterPhone.addEventListener('change', resetPageAndFetch);

// ── Clear buttons ─────────────────────────────────────────────────────────
clearCountry.addEventListener('click', () => {
  searchCountry.value = '';
  fetchResults();
});
clearCompany.addEventListener('click', () => {
  searchCompany.value = '';
  fetchResults();
});
clearName.addEventListener('click', () => {
  searchName.value = '';
  fetchResults();
});
clearAll.addEventListener('click', () => {
  searchCountry.value  = '';
  searchCompany.value  = '';
  searchName.value     = '';
  filterEmail.checked  = false;
  filterPhone.checked  = false;
  sortByEl.value       = 'company_name';
  sortDirEl.value      = 'asc';
  state.sort           = 'company_name';
  state.dir            = 'asc';
  state.network        = '';
  state.verify         = '';
  state.page           = 1;
  document.querySelectorAll('#networkFilter button').forEach((b, i) => {
    b.classList.toggle('active', i === 0);
  });
  document.querySelectorAll('#verifyFilter button').forEach((b, i) => {
    b.classList.toggle('active', i === 0);
  });
  fetchResults();
});

// ═══════════════════════════════════════════════════════════════════════════
//  EMAIL CLIENT PICKER
// ═══════════════════════════════════════════════════════════════════════════

const EMAIL_DEFAULT_KEY = 'wfa_email_default';

// Always-available web options (work on every device, no install needed)
const WEB_CLIENTS = [
  { id: 'gmail',        name: 'Gmail',        type: 'web',    url: 'https://mail.google.com/mail/?view=cm&to={email}' },
  { id: 'outlook_web',  name: 'Outlook.com',  type: 'web',    url: 'https://outlook.live.com/mail/0/deeplink/compose?to={email}' },
  { id: 'yahoo',        name: 'Yahoo Mail',   type: 'web',    url: 'https://compose.mail.yahoo.com/?to={email}' },
  { id: 'default',      name: 'Default App',  type: 'mailto', url: '' },
];

// Start with web clients immediately — desktop clients added when backend responds
let emailClients = [...WEB_CLIENTS];

// Icons for each client
const CLIENT_ICONS = {
  gmail:        { icon: 'bi-envelope-fill',        color: '#EA4335' },
  outlook:      { icon: 'bi-envelope-at-fill',      color: '#0072C6' },
  outlook_web:  { icon: 'bi-envelope-at-fill',      color: '#0072C6' },
  thunderbird:  { icon: 'bi-envelope-paper-fill',   color: '#FF6600' },
  emclient:     { icon: 'bi-envelope-check-fill',   color: '#00897B' },
  winmail:      { icon: 'bi-envelope-fill',         color: '#0078D4' },
  yahoo:        { icon: 'bi-envelope-fill',         color: '#6001D2' },
  default:      { icon: 'bi-envelope',              color: '#6c757d' },
};

function clientIcon(id) {
  const cfg = CLIENT_ICONS[id] || CLIENT_ICONS['default'];
  return `<i class="bi ${cfg.icon}" style="color:${cfg.color};font-size:1.15rem;"></i>`;
}

// Load detected desktop clients from backend, merge with web options
async function loadEmailClients() {
  try {
    const res     = await fetch('/api/email-clients');
    const desktop = await res.json();
    // Desktop installed apps first, then web options (no duplicates)
    const desktopIds = new Set(desktop.map(c => c.id));
    emailClients = [...desktop, ...WEB_CLIENTS.filter(c => !desktopIds.has(c.id))];
  } catch (_) {
    emailClients = WEB_CLIENTS;
  }
}

// Show the floating picker near the clicked element
function showEmailPicker(email, anchorEl) {
  closeEmailPicker();

  const savedDefault = localStorage.getItem(EMAIL_DEFAULT_KEY);
  const picker = document.createElement('div');
  picker.id = 'emailPicker';
  picker.className = 'email-picker-popup';

  const items = emailClients.map(c => `
    <button class="email-client-btn${c.id === savedDefault ? ' email-client-default' : ''}"
            data-client="${c.id}" data-type="${c.type}"
            data-url="${c.url ? esc(c.url) : ''}" data-email="${esc(email)}">
      ${clientIcon(c.id)}
      <span class="email-client-name">${esc(c.name)}</span>
      ${c.id === savedDefault ? '<span class="email-default-badge">Default</span>' : ''}
    </button>`).join('');

  picker.innerHTML = `
    <div class="email-picker-header">
      <span><i class="bi bi-send me-1 text-primary"></i>Send email to</span>
      <button class="email-picker-close" id="closeEmailPicker" title="Close">×</button>
    </div>
    <div class="email-picker-address">${esc(email)}</div>
    <div class="email-picker-divider"></div>
    <div class="email-picker-clients">${items}</div>
    <div class="email-picker-footer">
      <small class="text-muted">Right-click any option to set as default</small>
    </div>`;

  document.body.appendChild(picker);

  // Position the popup below the clicked badge — fixed to viewport
  const rect    = anchorEl.getBoundingClientRect();
  const pickerW = 280;
  let top  = rect.bottom + 6;
  let left = rect.left;

  // Clamp so it doesn't overflow right or bottom edge
  if (left + pickerW > window.innerWidth - 12) left = window.innerWidth - pickerW - 12;
  if (left < 8) left = 8;
  if (top + 300 > window.innerHeight) top = rect.top - 310; // flip above if no room below

  picker.style.top  = `${top}px`;
  picker.style.left = `${left}px`;

  // Left-click: open client. Right-click: set as default
  picker.querySelectorAll('.email-client-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      // If this client is already default, just open it
      // Otherwise open it and ask to set as default
      openEmailClient(btn.dataset.client, btn.dataset.type, btn.dataset.url, btn.dataset.email);
      closeEmailPicker();
    });
    btn.addEventListener('contextmenu', e => {
      e.preventDefault();
      localStorage.setItem(EMAIL_DEFAULT_KEY, btn.dataset.client);
      // Refresh picker to show new default
      closeEmailPicker();
      showToast(`✅ ${btn.querySelector('.email-client-name').textContent} set as default`, 'success');
    });
  });

  document.getElementById('closeEmailPicker').addEventListener('click', closeEmailPicker);

  // Close on outside click (slight delay so this click doesn't fire immediately)
  setTimeout(() => {
    document.addEventListener('click', outsidePickerHandler, { once: true });
  }, 80);
}

function outsidePickerHandler(e) {
  const picker = document.getElementById('emailPicker');
  if (picker && !picker.contains(e.target)) {
    picker.remove();
  }
}

function closeEmailPicker() {
  const picker = document.getElementById('emailPicker');
  if (picker) picker.remove();
  document.removeEventListener('click', outsidePickerHandler);
}

async function openEmailClient(clientId, type, urlTemplate, email) {
  if (type === 'web') {
    // Open Gmail (or any web client) in a new tab
    const url = urlTemplate.replace('{email}', encodeURIComponent(email));
    window.open(url, '_blank', 'noopener');

  } else if (type === 'mailto') {
    // Opens the system default mail app via mailto:
    window.location.href = `mailto:${email}`;

  } else if (type === 'desktop') {
    // Ask the backend to launch the desktop app
    try {
      const res  = await fetch(`/api/compose-email?client=${encodeURIComponent(clientId)}&email=${encodeURIComponent(email)}`);
      const data = await res.json();
      if (!data.ok) {
        // Fallback: use mailto: if app launch fails
        console.warn('Email client launch failed:', data.error, '— falling back to mailto:');
        window.location.href = `mailto:${encodeURIComponent(email)}`;
      }
    } catch (_) {
      window.location.href = `mailto:${encodeURIComponent(email)}`;
    }
  }
}

// Close picker if user scrolls or resizes
document.addEventListener('scroll', closeEmailPicker, { passive: true });
window.addEventListener('resize',  closeEmailPicker);

// ═══════════════════════════════════════════════════════════════════════════
//  CSV SYNC STATUS + MANUAL REFRESH
// ═══════════════════════════════════════════════════════════════════════════

const refreshBtn     = document.getElementById('refreshBtn');
const refreshIcon    = document.getElementById('refreshIcon');
const importCsvBtn   = document.getElementById('importCsvBtn');
const importIcon     = document.getElementById('importIcon');
const csvFileInput   = document.getElementById('csvFileInput');
const navLastSync    = document.getElementById('nav-last-sync');
const syncToastEl    = document.getElementById('syncToast');
const syncToastMsg   = document.getElementById('syncToastMsg');
const syncToast      = syncToastEl ? new bootstrap.Toast(syncToastEl, { delay: 3500 }) : null;

function showToast(msg, type = 'success') {
  if (!syncToast) return;
  syncToastEl.className = `toast align-items-center text-white border-0 bg-${type}`;
  syncToastMsg.textContent = msg;
  syncToast.show();
}

function formatSyncTime(isoStr) {
  if (!isoStr) return '';
  // isoStr is "YYYY-MM-DD HH:MM:SS"
  const d     = new Date(isoStr.replace(' ', 'T'));
  const now   = new Date();
  const diffS = Math.round((now - d) / 1000);
  if (diffS < 10)  return 'Synced just now';
  if (diffS < 60)  return `Synced ${diffS}s ago`;
  const diffM = Math.round(diffS / 60);
  if (diffM < 60)  return `Synced ${diffM}m ago`;
  const diffH = Math.round(diffM / 60);
  return `Synced ${diffH}h ago`;
}

let lastKnownSync = null;

async function fetchSyncStatus() {
  try {
    const res  = await fetch('/api/sync-status');
    const data = await res.json();
    // Update "last synced" label
    if (data.last_sync) {
      navLastSync.textContent = formatSyncTime(data.last_sync);
      // If the server synced more recently than we knew → refresh table silently
      if (lastKnownSync && data.last_sync !== lastKnownSync) {
        fetchResults();
        fetchStats();
        showToast(`CSV updated — ${data.row_count.toLocaleString()} contacts loaded.`, 'success');
      }
      lastKnownSync = data.last_sync;
    }
    if (!data.csv_found) {
      navLastSync.textContent = '⚠ CSV not found';
    }
  } catch (_) { /* silently ignore */ }
}

// Manual refresh button
if (refreshBtn) {
  refreshBtn.addEventListener('click', async () => {
    refreshBtn.disabled = true;
    refreshIcon.className = 'bi bi-arrow-clockwise spin';
    try {
      const res  = await fetch('/api/refresh', { method: 'POST' });
      const data = await res.json();
      if (data.ok) {
        lastKnownSync = data.last_sync;
        navLastSync.textContent = formatSyncTime(data.last_sync);
        fetchResults();
        fetchStats();
        showToast(`Refreshed — ${data.row_count.toLocaleString()} contacts loaded.`, 'success');
      } else {
        showToast(`Refresh failed: ${data.error}`, 'danger');
      }
    } catch (e) {
      showToast('Refresh failed — is the server running?', 'danger');
    } finally {
      refreshBtn.disabled = false;
      refreshIcon.className = 'bi bi-arrow-clockwise';
    }
  });
}

// ── Import CSV from file picker ───────────────────────────────────────────
if (importCsvBtn) {
  importCsvBtn.addEventListener('click', () => csvFileInput.click());
}

if (csvFileInput) {
  csvFileInput.addEventListener('change', async () => {
    const file = csvFileInput.files[0];
    if (!file) return;

    importCsvBtn.disabled = true;
    importIcon.className  = 'bi bi-upload spin';

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res  = await fetch('/api/upload-csv', { method: 'POST', body: formData });
      const data = await res.json();
      if (data.ok) {
        lastKnownSync = null; // force refresh
        fetchResults();
        fetchStats();
        showToast(
          `✅ ${data.network} imported — ${data.imported.toLocaleString()} contacts loaded.`,
          'success'
        );
      } else {
        showToast(`❌ Import failed: ${data.error}`, 'danger');
      }
    } catch (e) {
      showToast('Import failed — is the server running?', 'danger');
    } finally {
      importCsvBtn.disabled = false;
      importIcon.className  = 'bi bi-upload';
      csvFileInput.value    = ''; // reset so same file can be re-imported
    }
  });
}

// Poll sync status every 30 seconds to catch auto-sync events
setInterval(fetchSyncStatus, 30_000);

// ── Init ──────────────────────────────────────────────────────────────────
loadEmailClients();
fetchStats();
showSearchPrompt();   // Don't load all 114k contacts — wait for a search
fetchSyncStatus();
fetchVerifyStats();
setInterval(fetchVerifyStats, 60_000);  // refresh verify stats every minute

// ── Trust Scorecard Builder ───────────────────────────────────────────────
function buildScorecard(c) {
  const score = c.score || 0;

  // Score components — max 85 from data, 100 only from email reply
  const components = [
    {
      key: 'email',
      label: 'Email Address',
      pts: 35,
      earned: c.email ? 35 : 0,
      earned_label: c.email ? `+35 — ${esc(c.email)}` : '+0 — not found yet',
      icon: 'bi-envelope-fill',
      how: 'Scraped from company website or member directory',
      unlock: 'Email must be found and validated',
      done: !!c.email
    },
    {
      key: 'phone',
      label: 'Phone Number',
      pts: 25,
      earned: c.phone ? 25 : 0,
      earned_label: c.phone ? `+25 — ${esc(c.phone)}` : '+0 — not found yet',
      icon: 'bi-telephone-fill',
      how: 'Pulled from directory listing',
      unlock: 'Phone number must be present in source data',
      done: !!c.phone
    },
    {
      key: 'website',
      label: 'Company Website',
      pts: 15,
      earned: c.website ? 15 : 0,
      earned_label: c.website ? `+15 — verified` : '+0 — no website on record',
      icon: 'bi-globe',
      how: 'Website URL confirmed in source directory',
      unlock: 'Website URL must be present',
      done: !!c.website
    },
    {
      key: 'linkedin',
      label: 'LinkedIn Profile',
      pts: 10,
      earned: c.linkedin ? 10 : 0,
      earned_label: c.linkedin ? `+10 — found` : '+0 — not found',
      icon: 'bi-linkedin',
      how: 'LinkedIn company page linked in directory',
      unlock: 'LinkedIn URL must be present',
      done: !!c.linkedin
    },
    {
      key: 'replied',
      label: 'Email Response Confirmed',
      pts: 15,
      earned: score >= 100 ? 15 : 0,
      earned_label: score >= 100 ? '+15 — agent replied to outreach' : '+0 — no reply yet',
      icon: 'bi-chat-dots-fill',
      how: 'Agent replied to a Flash Cargo outreach email',
      unlock: 'Only awarded when agent replies to your outreach — this is the only path to 100',
      done: score >= 100
    },
  ];

  const totalPts = components.reduce((s, c) => s + c.earned, 0);
  const pct = Math.round((totalPts / 100) * 100);
  const barColor = totalPts >= 85 ? 'success' : totalPts >= 60 ? 'info' : totalPts >= 35 ? 'warning' : 'danger';

  const rows = components.map(item => `
    <div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary" style="border-bottom:1px solid #2a2a2a!important;">
      <i class="bi ${item.icon} ${item.done ? 'text-success' : 'text-secondary'}" style="width:18px;"></i>
      <div class="flex-grow-1">
        <div class="d-flex justify-content-between align-items-center">
          <span class="small fw-medium ${item.done ? 'text-light' : 'text-muted'}">${item.label}</span>
          <span class="small fw-bold ${item.done ? 'text-success' : 'text-secondary'}">${item.earned_label}</span>
        </div>
        <div class="small text-muted" style="font-size:0.72rem;">
          ${item.done ? `<i class="bi bi-check-circle-fill text-success me-1"></i>${item.how}` : `<i class="bi bi-lock-fill me-1"></i>${item.unlock}`}
        </div>
      </div>
    </div>`).join('');

  return `
    <div class="d-flex align-items-center gap-3 mb-3">
      <div class="text-center" style="min-width:64px;">
        <div class="fw-bold text-${barColor}" style="font-size:2rem;line-height:1;">${totalPts}</div>
        <div class="text-muted" style="font-size:0.7rem;">OUT OF 100</div>
      </div>
      <div class="flex-grow-1">
        <div class="progress" style="height:10px;border-radius:6px;">
          <div class="progress-bar bg-${barColor}" style="width:${pct}%;border-radius:6px;"></div>
        </div>
        <div class="d-flex justify-content-between mt-1" style="font-size:0.68rem;color:#666;">
          <span>0 — No data</span>
          <span>50 — Verified</span>
          <span>85 — Full data</span>
          <span>100 — Replied ✉️</span>
        </div>
      </div>
    </div>
    <div>${rows}</div>
    ${totalPts < 100 ? `
    <div class="mt-2 p-2 rounded small" style="background:#1a2a1a;border:1px solid #2a4a2a;">
      <i class="bi bi-info-circle me-1 text-success"></i>
      <strong class="text-success">How to reach 100:</strong>
      <span class="text-muted"> Send an outreach email and get a reply. A confirmed response is the only way to reach a perfect score.</span>
    </div>` : `
    <div class="mt-2 p-2 rounded small" style="background:#1a2a1a;border:1px solid #2a4a2a;">
      <i class="bi bi-trophy-fill me-1 text-warning"></i>
      <strong class="text-warning">Perfect score — this agent has replied to your outreach.</strong>
    </div>`}`;
}

// ── Intelligence Card ─────────────────────────────────────────────────────
async function showIntelCard(contactId) {
  const modal = document.getElementById('intelModal');
  const body  = document.getElementById('intelModalBody');
  if (!modal || !body) return;

  body.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-info"></div></div>';
  new bootstrap.Modal(modal).show();

  try {
    const res  = await fetch(`/api/contacts/${contactId}/intelligence`);
    const data = await res.json();
    if (!data.ok) { body.innerHTML = `<p class="text-danger">${data.error}</p>`; return; }

    const c = data.contact;
    const b = data.behavior;
    const r = data.rates;
    const i = data.interests;
    const prep = data.call_prep || [];

    const behaviorColor = { fast: 'success', balanced: 'info', relaxed: 'warning', slow: 'secondary', unknown: 'secondary' };
    const bColor = behaviorColor[b.type] || 'secondary';

    const interestHtml = i.confirmed.length
      ? i.confirmed.map(int => `<span class="badge bg-primary me-1">${esc(int)}</span>`).join('')
      : '<span class="text-muted small">Not yet captured</span>';

    const newsHtml = i.news_bullets.length
      ? `<ul class="small text-muted mt-2">${i.news_bullets.map(n => `<li>${esc(n)}</li>`).join('')}</ul>`
      : '';

    const prepHtml = prep.map(line => `<li class="small">${esc(line)}</li>`).join('');

    body.innerHTML = `
      <div class="row g-3">

        <!-- Contact header -->
        <div class="col-12">
          <div class="d-flex align-items-start gap-3">
            <div class="rounded-circle bg-info text-white d-flex align-items-center justify-content-center flex-shrink-0"
                 style="width:48px;height:48px;font-size:1.4rem;">
              <i class="bi bi-person-fill"></i>
            </div>
            <div>
              <h5 class="mb-0">${esc(c.name || c.company)}</h5>
              <div class="text-muted small">${esc(c.company)} &bull; ${esc(c.country)}${c.city ? ', ' + esc(c.city) : ''}</div>
              <div class="small mt-1">
                ${c.email ? `<i class="bi bi-envelope me-1"></i>${esc(c.email)}` : ''}
                ${c.phone ? `&nbsp;&bull;&nbsp;<i class="bi bi-telephone me-1"></i>${esc(c.phone)}` : ''}
              </div>
            </div>
          </div>
        </div>

        <!-- Scorecard -->
        <div class="col-12">
          <div class="card border-0" style="background:#111;">
            <div class="card-body">
              <h6 class="card-title text-uppercase text-muted small mb-3"><i class="bi bi-award-fill me-1 text-warning"></i>Trust Scorecard</h6>
              ${buildScorecard(c)}
            </div>
          </div>
        </div>

        <!-- Behavior -->
        <div class="col-md-6">
          <div class="card h-100 border-0 bg-dark">
            <div class="card-body">
              <h6 class="card-title text-uppercase text-muted small mb-3"><i class="bi bi-activity me-1"></i>Behavior Profile</h6>
              <span class="badge bg-${bColor} mb-2">${b.type.toUpperCase()}</span>
              <p class="small mb-2">${esc(b.label)}</p>
              <div class="small text-muted">
                ${b.avg_hours ? `Avg response: <strong>${b.avg_hours}h</strong><br>` : ''}
                Emails sent: <strong>${b.email_count}</strong> &bull;
                Responses: <strong>${b.response_count}</strong>
                ${b.last_responded ? `<br>Last replied: <strong>${b.last_responded.slice(0,10)}</strong>` : ''}
              </div>
            </div>
          </div>
        </div>

        <!-- Rates -->
        <div class="col-md-6">
          <div class="card h-100 border-0 bg-dark">
            <div class="card-body">
              <h6 class="card-title text-uppercase text-muted small mb-3"><i class="bi bi-currency-dollar me-1"></i>Rate History</h6>
              <div class="small">
                Rates received: <strong>${r.total_received}</strong><br>
                Complete submissions: <strong>${r.complete}</strong><br>
                Reliability: <strong>${r.reliability_pct}%</strong>
              </div>
              ${r.recent.length ? `
              <div class="mt-2">
                ${r.recent.map(rt => `
                  <div class="small text-muted border-start border-info ps-2 mb-1">
                    ${esc(rt.origin||'')} → ${esc(rt.destination||'')}
                    &nbsp;|&nbsp; 20ft: $${rt.rate_20ft||'?'} &nbsp;|&nbsp; 40ft: $${rt.rate_40ft||'?'}
                    &nbsp;|&nbsp; ${esc(rt.carrier||'')}
                  </div>`).join('')}
              </div>` : ''}
            </div>
          </div>
        </div>

        <!-- Interests -->
        <div class="col-12">
          <div class="card border-0 bg-dark">
            <div class="card-body">
              <h6 class="card-title text-uppercase text-muted small mb-3"><i class="bi bi-stars me-1"></i>Interests</h6>
              <div class="mb-2">${interestHtml}</div>
              ${newsHtml}
              ${!i.confirmed.length ? `
              <form class="mt-2 d-flex gap-2" onsubmit="saveInterests(event, ${contactId})">
                <input type="text" class="form-control form-control-sm" id="interestInput_${contactId}"
                       placeholder="e.g. football, cooking, F1..." style="max-width:300px;">
                <button class="btn btn-sm btn-outline-info" type="submit">Save</button>
              </form>` : `
              <button class="btn btn-sm btn-outline-secondary mt-1"
                      onclick="document.getElementById('interestEditWrap_${contactId}').classList.toggle('d-none')">
                Edit interests
              </button>
              <div id="interestEditWrap_${contactId}" class="d-none mt-2">
                <form class="d-flex gap-2" onsubmit="saveInterests(event, ${contactId})">
                  <input type="text" class="form-control form-control-sm" id="interestInput_${contactId}"
                         value="${esc(i.confirmed.join(', '))}" style="max-width:300px;">
                  <button class="btn btn-sm btn-outline-info" type="submit">Update</button>
                </form>
              </div>`}
            </div>
          </div>
        </div>

        <!-- Call Prep -->
        <div class="col-12">
          <div class="card border-0 bg-dark">
            <div class="card-body">
              <h6 class="card-title text-uppercase text-muted small mb-3"><i class="bi bi-telephone-fill me-1"></i>Call Prep</h6>
              <ul class="list-unstyled mb-0">${prepHtml}</ul>
            </div>
          </div>
        </div>

      </div>`;
  } catch(e) {
    body.innerHTML = `<p class="text-danger">Failed to load intelligence card.</p>`;
  }
}

async function saveInterests(e, contactId) {
  e.preventDefault();
  const input = document.getElementById(`interestInput_${contactId}`);
  if (!input) return;
  const interests = input.value.split(',').map(s => s.trim()).filter(Boolean);
  await fetch(`/api/contacts/${contactId}/interests`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ interests }),
  });
  showIntelCard(contactId); // refresh
}

// ── Add User / Invite Modal ────────────────────────────────────────────────
(function () {
  const addBtn = document.getElementById('addUserBtn');
  if (!addBtn) return;  // not admin — element not rendered

  const modal       = new bootstrap.Modal(document.getElementById('addUserModal'));
  const emailInput  = document.getElementById('inviteEmailInput');
  const sendBtn     = document.getElementById('sendInviteBtn');
  const spinner     = document.getElementById('sendInviteSpinner');
  const msgEl       = document.getElementById('inviteMsg');

  addBtn.addEventListener('click', function () {
    emailInput.value = '';
    msgEl.textContent = '';
    msgEl.className = 'mt-2 small';
    modal.show();
    setTimeout(function () { emailInput.focus(); }, 300);
  });

  sendBtn.addEventListener('click', async function () {
    const email = emailInput.value.trim();
    if (!email) { msgEl.textContent = 'Please enter an email address.'; msgEl.className = 'mt-2 small text-warning'; return; }

    sendBtn.disabled = true;
    spinner.classList.remove('d-none');
    msgEl.textContent = '';

    try {
      const res  = await fetch('/api/users/invite', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ email }),
      });
      const data = await res.json();
      if (data.ok) {
        msgEl.textContent = data.message || 'Invite sent successfully.';
        msgEl.className   = 'mt-2 small text-success';
        setTimeout(function () { modal.hide(); }, 2000);
      } else {
        msgEl.textContent = data.error || 'Invite failed.';
        msgEl.className   = 'mt-2 small text-danger';
      }
    } catch (e) {
      msgEl.textContent = 'Network error — please try again.';
      msgEl.className   = 'mt-2 small text-danger';
    } finally {
      sendBtn.disabled = false;
      spinner.classList.add('d-none');
    }
  });

  emailInput.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') sendBtn.click();
  });
})();
