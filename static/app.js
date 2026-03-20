/* app.js — WFA Contacts Dashboard */
'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  sort:    'company_name',
  dir:     'asc',
  network: '',
  verify:  '',
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
        <div class="fw-medium">
          ${r.website_url
            ? `<a href="${esc(r.website_url)}" target="_blank" rel="noopener" class="company-link" title="Open website">${esc(r.company_name)}<i class="bi bi-box-arrow-up-right ms-1 small"></i></a>`
            : (esc(r.company_name) || '<span class="text-muted">—</span>')}
          ${verifyBadge(r)}
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

  const n = data.count;
  resultCount.innerHTML = `<span class="fw-semibold">${n.toLocaleString()}</span> result${n !== 1 ? 's' : ''}`;
}

// ── Fetch & display results ───────────────────────────────────────────────
async function fetchResults() {
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
  fetchResults();
});
sortDirEl.addEventListener('change', () => {
  state.dir = sortDirEl.value;
  fetchResults();
});

// ── Network filter buttons ────────────────────────────────────────────────
document.querySelectorAll('#networkFilter button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#networkFilter button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.network = btn.dataset.network;
    fetchResults();
  });
});

// ── Verification filter buttons ───────────────────────────────────────────
document.querySelectorAll('#verifyFilter button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#verifyFilter button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.verify = btn.dataset.verify;
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
searchCountry.addEventListener('input', () => debounce(fetchResults));
searchCompany.addEventListener('input', () => debounce(fetchResults));
searchName.addEventListener('input',    () => debounce(fetchResults));
filterEmail.addEventListener('change', fetchResults);
filterPhone.addEventListener('change', fetchResults);

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
fetchResults();
fetchSyncStatus();
fetchVerifyStats();
setInterval(fetchVerifyStats, 60_000);  // refresh verify stats every minute
