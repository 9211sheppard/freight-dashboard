/* rates.js — Freight Rate System Frontend */
(function () {
  'use strict';

  // ── State ──────────────────────────────────────────────────────────────────
  let _currentCycleId  = null;
  let _allRates        = [];
  let _outreachTimer   = null;

  // ── Helpers ────────────────────────────────────────────────────────────────

  function fmtDate(s) {
    if (!s) return '—';
    return s.slice(0, 10);
  }

  function fmtMoney(v, currency) {
    if (v === null || v === undefined || v === '') return '—';
    const cur = currency || 'USD';
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency', currency: cur,
        minimumFractionDigits: 0, maximumFractionDigits: 0,
      }).format(v);
    } catch (e) {
      return `${cur} ${Number(v).toLocaleString()}`;
    }
  }

  function qualityBadge(score) {
    if (score === null || score === undefined || score === 0) {
      return '<span class="quality-badge quality-na">N/A</span>';
    }
    const cls = score >= 80 ? 'quality-green' : score >= 60 ? 'quality-yellow' : 'quality-red';
    return `<span class="quality-badge ${cls}">${score}</span>`;
  }

  function outreachBadge(status) {
    const map = {
      pending:   ['outreach-pending',   'Pending'],
      sent:      ['outreach-sent',      'Sent'],
      reminded:  ['outreach-reminded',  'Reminded'],
      responded: ['outreach-responded', 'Responded'],
      no_response: ['outreach-no-response', 'No Response'],
    };
    const [cls, label] = map[status] || ['outreach-pending', status || 'Pending'];
    return `<span class="outreach-status ${cls}">${label}</span>`;
  }

  // Color-code rates: green=competitive, yellow=mid, red=expensive
  function rateColorClass(rate20, allRates20OnLane) {
    if (!rate20 || !allRates20OnLane || allRates20OnLane.length < 2) return '';
    const sorted = [...allRates20OnLane].sort((a, b) => a - b);
    const lo = sorted[0];
    const hi = sorted[sorted.length - 1];
    if (hi === lo) return '';
    const pct = (rate20 - lo) / (hi - lo);
    if (pct <= 0.33) return 'rate-competitive';
    if (pct <= 0.66) return 'rate-mid';
    return 'rate-expensive';
  }

  // Build lane key for color grouping
  function laneKey(r) {
    return `${(r.origin||'').toLowerCase()}|${(r.destination||'').toLowerCase()}`;
  }

  // ── Load Cycles ────────────────────────────────────────────────────────────

  function loadCycles() {
    fetch('/api/rates/cycles')
      .then(r => r.json())
      .then(cycles => {
        const sel = document.getElementById('cycleSelect');
        const current = sel.value;
        sel.innerHTML = '<option value="">— Select cycle —</option>';
        cycles.forEach(c => {
          const o = document.createElement('option');
          o.value       = c.id;
          o.textContent = `${c.cycle_name} [${c.status}]`;
          sel.appendChild(o);
        });
        // Restore selection or auto-select first
        if (current && sel.querySelector(`option[value="${current}"]`)) {
          sel.value = current;
        } else if (cycles.length) {
          sel.value = cycles[0].id;
        }
        const cid = parseInt(sel.value) || null;
        if (cid !== _currentCycleId) {
          _currentCycleId = cid;
          onCycleChange();
        }
      })
      .catch(() => {});
  }

  function onCycleChange() {
    _currentCycleId = parseInt(document.getElementById('cycleSelect').value) || null;
    loadStats(_currentCycleId);
    loadRates(_currentCycleId);
    loadOutreach(_currentCycleId);
  }

  // ── Load Stats ─────────────────────────────────────────────────────────────

  function loadStats(cycleId) {
    if (!cycleId) {
      // Fall back to global stats
      fetch('/api/rates/stats')
        .then(r => r.json())
        .then(d => {
          document.getElementById('statRatesCollected').textContent = d.rates_collected || 0;
          document.getElementById('statAgentsResponded').textContent = '—';
          document.getElementById('statAgentsPending').textContent   = d.pending_responses || 0;
          document.getElementById('statAvgResponse').textContent     = (d.avg_response_rate || 0) + '%';
        })
        .catch(() => {});
      return;
    }
    fetch(`/api/rates/cycle/${cycleId}/stats`)
      .then(r => r.json())
      .then(d => {
        document.getElementById('statRatesCollected').textContent = d.total_rates_collected || 0;
        document.getElementById('statAgentsResponded').textContent = d.total_responded || 0;
        document.getElementById('statAgentsPending').textContent   = d.total_sent - d.total_responded || 0;
        const rate = d.total_sent ? Math.round(d.total_responded / d.total_sent * 100) : 0;
        document.getElementById('statAvgResponse').textContent = rate + '%';
      })
      .catch(() => {});
  }

  // ── Load Rates Table ───────────────────────────────────────────────────────

  function loadRates(cycleId) {
    const params = new URLSearchParams();
    const carrier = document.getElementById('filterCarrier').value;
    const origin  = document.getElementById('filterOrigin').value;
    const dest    = document.getElementById('filterDest').value;
    if (carrier) params.set('carrier', carrier);
    if (origin)  params.set('origin',  origin);
    if (dest)    params.set('destination', dest);
    if (cycleId) params.set('cycle_id', cycleId);

    // Use existing /api/rates endpoint (it supports cycle via 'cycle' param for legacy)
    // Also support cycle_id by fetching all then filtering if needed
    let url = '/api/rates?' + params.toString();

    fetch(url)
      .then(r => r.json())
      .then(rows => {
        _allRates = rows;

        // Populate filter dropdowns from data
        populateFilterOptions(rows);

        // Update count
        document.getElementById('ratesCountLabel').textContent =
          rows.length ? `(${rows.length})` : '';

        const tbody = document.getElementById('ratesBody');
        if (!rows.length) {
          tbody.innerHTML = `<tr><td colspan="9" class="empty-state">
            <i class="bi bi-currency-dollar"></i>No rates match the selected filters.</td></tr>`;
          return;
        }

        // Build per-lane rate20 lists for color coding
        const laneRates = {};
        rows.forEach(r => {
          const k = laneKey(r);
          if (!laneRates[k]) laneRates[k] = [];
          if (r.rate_20ft) laneRates[k].push(r.rate_20ft);
        });

        tbody.innerHTML = rows.map(r => {
          const k   = laneKey(r);
          const cls = rateColorClass(r.rate_20ft, laneRates[k]);
          return `<tr class="${cls}">
            <td class="small">${r.origin || '—'}</td>
            <td class="small">${r.destination || '—'}</td>
            <td><strong class="small">${r.carrier || '—'}</strong></td>
            <td class="small fw-medium">${fmtMoney(r.rate_20ft, r.currency)}</td>
            <td class="small fw-medium">${fmtMoney(r.rate_40ft, r.currency)}</td>
            <td class="small text-muted">${fmtDate(r.valid_from)}${r.valid_to ? ' – ' + fmtDate(r.valid_to) : ''}</td>
            <td class="small">${r.company_name || '—'}</td>
            <td class="small text-muted">${fmtDate(r.etd) || fmtDate(r.parsed_at) || '—'}</td>
            <td>
              <button class="btn btn-sm py-0 px-1 btn-outline-danger rate-delete-btn"
                      data-id="${r.id}" title="Delete rate">
                <i class="bi bi-trash" style="font-size:.7rem"></i>
              </button>
            </td>
          </tr>`;
        }).join('');

        // Delete handlers
        tbody.querySelectorAll('.rate-delete-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            if (!confirm('Delete this rate record?')) return;
            fetch(`/api/rates/${btn.dataset.id}`, { method: 'DELETE' })
              .then(r => r.json())
              .then(() => loadRates(_currentCycleId))
              .catch(() => {});
          });
        });
      })
      .catch(() => {});
  }

  function populateFilterOptions(rows) {
    const origins   = [...new Set(rows.map(r => r.origin).filter(Boolean))].sort();
    const dests     = [...new Set(rows.map(r => r.destination).filter(Boolean))].sort();
    const carriers  = [...new Set(rows.map(r => r.carrier).filter(Boolean))].sort();

    const repopulate = (id, vals) => {
      const el  = document.getElementById(id);
      const cur = el.value;
      const first = el.options[0];
      el.innerHTML = '';
      el.appendChild(first);
      vals.forEach(v => {
        const o = document.createElement('option');
        o.value = v; o.textContent = v;
        el.appendChild(o);
      });
      if (cur) el.value = cur;
    };

    repopulate('filterOrigin',  origins);
    repopulate('filterDest',    dests);
    repopulate('filterCarrier', carriers);
  }

  // ── Load Outreach Status ───────────────────────────────────────────────────

  function loadOutreach(cycleId) {
    const el = document.getElementById('outreachList');
    if (!cycleId) {
      el.innerHTML = '<div class="text-muted small text-center py-4">Select a cycle to see outreach status.</div>';
      return;
    }
    fetch(`/api/rates/outreach?cycle_id=${cycleId}`)
      .then(r => r.json())
      .then(rows => {
        if (!rows.length) {
          // Fall back to legacy rate_requests
          loadLegacyOutreach(cycleId, el);
          return;
        }
        el.innerHTML = rows.map(r => `
          <div class="outreach-row d-flex align-items-center gap-2 px-3 py-2 border-bottom">
            <div class="flex-grow-1 min-w-0">
              <div class="small fw-medium text-truncate">${r.contact_company || r.company_name || '—'}</div>
              <div class="text-muted" style="font-size:.73rem">${r.contact_country || r.country || '—'}</div>
            </div>
            <div class="flex-shrink-0 text-end">
              ${outreachBadge(r.status)}
              <div class="text-muted" style="font-size:.7rem;margin-top:2px">
                ${r.sent_at ? 'Sent ' + fmtDate(r.sent_at) : ''}
                ${r.responded_at ? ' · Replied ' + fmtDate(r.responded_at) : ''}
              </div>
            </div>
          </div>
        `).join('');
      })
      .catch(() => {
        el.innerHTML = '<div class="text-danger small text-center py-3">Failed to load outreach status.</div>';
      });
  }

  function loadLegacyOutreach(cycleId, el) {
    // Fallback: show rate_requests if no cycle-based outreach records exist
    fetch('/api/rate-requests')
      .then(r => r.json())
      .then(rows => {
        if (!rows.length) {
          el.innerHTML = '<div class="text-muted small text-center py-4">No outreach records for this cycle.</div>';
          return;
        }
        el.innerHTML = rows.slice(0, 30).map(r => {
          const status = r.responded ? 'responded' : r.reminder_sent ? 'reminded' : r.sent_at ? 'sent' : 'pending';
          return `
            <div class="outreach-row d-flex align-items-center gap-2 px-3 py-2 border-bottom">
              <div class="flex-grow-1 min-w-0">
                <div class="small fw-medium text-truncate">${r.company_name || '—'}</div>
                <div class="text-muted" style="font-size:.73rem">${r.country || '—'}</div>
              </div>
              <div class="flex-shrink-0 text-end">
                ${outreachBadge(status)}
                <div class="text-muted" style="font-size:.7rem;margin-top:2px">
                  ${r.sent_at ? 'Sent ' + fmtDate(r.sent_at) : ''}
                </div>
              </div>
            </div>
          `;
        }).join('');
      })
      .catch(() => {});
  }

  // ── Load Gap Report ────────────────────────────────────────────────────────

  function loadGaps() {
    fetch('/api/rates/gaps/by-region')
      .then(r => r.json())
      .then(rows => {
        const tbody = document.getElementById('gapBody');
        if (!rows.length) {
          tbody.innerHTML = `<tr><td colspan="4" class="empty-state">
            <i class="bi bi-patch-check"></i>No gaps recorded yet.</td></tr>`;
          return;
        }
        tbody.innerHTML = rows.map(r => {
          const occ = r.total_occurrences || r.occurrences || 0;
          const cls = occ >= 5 ? 'text-danger fw-bold' : occ >= 3 ? 'text-warning fw-medium' : '';
          return `<tr>
            <td class="small">${r.region || '—'}</td>
            <td class="small"><code>${r.gap_field || '—'}</code></td>
            <td class="small text-center ${cls}">${occ}</td>
            <td class="small text-muted">${fmtDate(r.last_seen)}</td>
          </tr>`;
        }).join('');
      })
      .catch(() => {
        // Fallback: try legacy gap report
        fetch('/api/rates/gaps')
          .then(r => r.json())
          .then(d => {
            const tbody = document.getElementById('gapBody');
            const top   = d.top_missing || [];
            if (!top.length) {
              tbody.innerHTML = `<tr><td colspan="4" class="empty-state">
                <i class="bi bi-patch-check"></i>No gaps recorded yet.</td></tr>`;
              return;
            }
            tbody.innerHTML = top.map(item => `<tr>
              <td class="small">—</td>
              <td class="small"><code>${item.field}</code></td>
              <td class="small text-center">${item.count}</td>
              <td class="small text-muted">—</td>
            </tr>`).join('');
          })
          .catch(() => {});
      });
  }

  // ── Load legacy requests table ─────────────────────────────────────────────

  function loadLegacyRequests() {
    fetch('/api/rate-requests')
      .then(r => r.json())
      .then(rows => {
        const card  = document.getElementById('legacyRequestsCard');
        const tbody = document.getElementById('requestsBody');
        if (!rows.length) {
          card.style.display = 'none';
          return;
        }
        card.style.display = '';
        tbody.innerHTML = rows.map(r => `
          <tr>
            <td class="small">${r.company_name || '—'}</td>
            <td class="small">${r.country || '—'}</td>
            <td class="small text-muted">${r.cycle || '—'}</td>
            <td class="small">${fmtDate(r.sent_at)}</td>
            <td class="text-center">
              <i class="bi bi-${r.reminder_sent ? 'check-circle-fill text-warning' : 'dash text-muted'}"></i>
            </td>
            <td class="text-center">
              <i class="bi bi-${r.responded ? 'check-circle-fill text-success' : 'x-circle text-danger'}"></i>
            </td>
            <td>${r.response_quality ? qualityBadge(r.response_quality) : '—'}</td>
          </tr>
        `).join('');
      })
      .catch(() => {});
  }

  // ── New Cycle Modal ────────────────────────────────────────────────────────

  function newCycle() {
    // Pre-select current month
    const now = new Date();
    document.getElementById('ncMonth').value    = now.getMonth() + 1;
    document.getElementById('ncYear').value     = now.getFullYear();
    document.getElementById('newCycleResult').innerHTML = '';
    new bootstrap.Modal(document.getElementById('newCycleModal')).show();
  }

  document.getElementById('newCycleBtn').addEventListener('click', newCycle);

  document.getElementById('newCycleSubmitBtn').addEventListener('click', () => {
    const month     = parseInt(document.getElementById('ncMonth').value);
    const year      = parseInt(document.getElementById('ncYear').value);
    const cycle_num = parseInt(document.getElementById('ncCycleNum').value);
    const btn       = document.getElementById('newCycleSubmitBtn');
    const resEl     = document.getElementById('newCycleResult');

    btn.disabled  = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Creating…';

    fetch('/api/rates/cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ month, year, cycle_num }),
    })
      .then(r => r.json())
      .then(d => {
        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-plus-circle me-1"></i>Create';
        if (d.ok) {
          resEl.innerHTML = `<div class="alert alert-success py-2 small">
            Created: <strong>${d.cycle.cycle_name}</strong>
            (${d.cycle.valid_from} – ${d.cycle.valid_to})</div>`;
          loadCycles();
          setTimeout(() => {
            bootstrap.Modal.getInstance(document.getElementById('newCycleModal')).hide();
          }, 1200);
        } else {
          resEl.innerHTML = `<div class="alert alert-danger py-2 small">${d.error}</div>`;
        }
      })
      .catch(e => {
        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-plus-circle me-1"></i>Create';
        resEl.innerHTML = `<div class="alert alert-danger py-2 small">${e.message}</div>`;
      });
  });

  // ── Parse Email Modal ──────────────────────────────────────────────────────

  function parseReply() {
    document.getElementById('parseResult').classList.add('d-none');
    document.getElementById('parseEmailBody').value = '';
    // Populate contacts
    fetch('/api/contacts-ids')
      .then(r => r.json())
      .then(rows => {
        const sel = document.getElementById('parseContact');
        sel.innerHTML = '<option value="">Select contact…</option>';
        rows.forEach(c => {
          const o = document.createElement('option');
          o.value       = c.id;
          o.textContent = `${c.company_name || c.email} — ${c.country}`;
          sel.appendChild(o);
        });
      })
      .catch(() => {});
    new bootstrap.Modal(document.getElementById('parseModal')).show();
  }

  document.getElementById('parseEmailBtn').addEventListener('click', parseReply);

  document.getElementById('parseSubmitBtn').addEventListener('click', () => {
    const body      = document.getElementById('parseEmailBody').value.trim();
    const contactId = document.getElementById('parseContact').value;
    const cycle     = document.getElementById('parseCycle').value.trim();
    const btn       = document.getElementById('parseSubmitBtn');
    const resultEl  = document.getElementById('parseResult');
    const contentEl = document.getElementById('parseResultContent');

    if (!body)      { alert('Please paste the email body.');    return; }
    if (!contactId) { alert('Please select a contact.');        return; }

    btn.disabled  = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Parsing…';

    fetch('/api/rates/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email_body: body, contact_id: parseInt(contactId), cycle }),
    })
      .then(r => r.json())
      .then(d => {
        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-lightning me-1"></i>Parse &amp; Save';
        resultEl.classList.remove('d-none');

        if (!d.ok) {
          contentEl.innerHTML = `<div class="alert alert-danger py-2 small">${d.error}</div>`;
          return;
        }

        const ext  = d.extracted  || {};
        const miss = d.missing_fields || [];
        const qs   = d.quality_score;

        let html = `<div class="d-flex align-items-center gap-2 mb-2">
          ${qualityBadge(qs)}
          <span class="small">Quality Score</span>
          ${d.rate_id ? `<span class="badge bg-success-subtle text-success ms-auto">Saved (Rate #${d.rate_id})</span>` : ''}
        </div>`;

        html += '<div class="row g-2">';
        const fields = [
          ['Carrier',     ext.carrier],
          ['Origin',      ext.origin],
          ['Destination', ext.destination],
          ['20ft Rate',   ext.rate_20ft != null ? fmtMoney(ext.rate_20ft, ext.currency) : null],
          ['40ft Rate',   ext.rate_40ft != null ? fmtMoney(ext.rate_40ft, ext.currency) : null],
          ['Valid From',  ext.valid_from],
          ['Valid To',    ext.valid_to],
          ['ETD Matched', ext.etd_matched],
        ];
        fields.forEach(([label, val]) => {
          const found = val !== null && val !== undefined && val !== '';
          html += `<div class="col-6 col-md-4">
            <div class="d-flex align-items-center gap-1">
              <i class="bi bi-${found ? 'check-circle-fill text-success' : 'x-circle text-danger'}" style="font-size:.8rem"></i>
              <span class="small text-muted">${label}:</span>
              <span class="small fw-medium">${found ? val : '—'}</span>
            </div>
          </div>`;
        });
        html += '</div>';

        if (miss.length) {
          html += `<div class="alert alert-warning py-2 small mt-2 mb-0">
            Missing: <strong>${miss.join(', ')}</strong>
          </div>`;
        }

        contentEl.innerHTML = html;
        loadRates(_currentCycleId);
        loadStats(_currentCycleId);
        loadGaps();
      })
      .catch(e => {
        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-lightning me-1"></i>Parse &amp; Save';
        contentEl.innerHTML = `<div class="alert alert-danger py-2 small">${e.message}</div>`;
        resultEl.classList.remove('d-none');
      });
  });

  // ── Send Requests Modal ────────────────────────────────────────────────────

  const sendBtn = document.getElementById('sendRequestsBtn');
  if (sendBtn) {
    sendBtn.addEventListener('click', () => {
      document.getElementById('sendResult').classList.add('d-none');
      new bootstrap.Modal(document.getElementById('sendModal')).show();
    });
  }

  document.getElementById('sendConfirmBtn').addEventListener('click', () => {
    const cycle = document.getElementById('sendCycle').value.trim();
    const btn   = document.getElementById('sendConfirmBtn');
    const resEl = document.getElementById('sendResult');

    btn.disabled  = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Sending…';

    fetch('/api/rate-requests/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cycle }),
    })
      .then(r => r.json())
      .then(d => {
        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-send me-1"></i>Send Now';
        resEl.classList.remove('d-none');

        const cls = d.warning ? 'alert-warning' : d.errors && d.errors.length ? 'alert-danger' : 'alert-success';
        let msg   = d.warning || `Sent: ${d.sent}, Skipped: ${d.skipped}`;
        if (d.errors && d.errors.length) msg += `<br><small>${d.errors.join('<br>')}</small>`;
        resEl.className = `alert ${cls} py-2 small`;
        resEl.innerHTML = msg;
        loadStats(_currentCycleId);
        loadOutreach(_currentCycleId);
      })
      .catch(e => {
        btn.disabled  = false;
        btn.innerHTML = '<i class="bi bi-send me-1"></i>Send Now';
        resEl.className = 'alert alert-danger py-2 small';
        resEl.innerHTML = e.message;
        resEl.classList.remove('d-none');
      });
  });

  // ── Filter change handlers ─────────────────────────────────────────────────

  ['filterOrigin', 'filterDest', 'filterCarrier'].forEach(id => {
    document.getElementById(id).addEventListener('change', () => {
      loadRates(_currentCycleId);
    });
  });

  document.getElementById('cycleSelect').addEventListener('change', onCycleChange);

  // ── Auto-refresh outreach every 60s ───────────────────────────────────────

  function startOutreachAutoRefresh() {
    if (_outreachTimer) clearInterval(_outreachTimer);
    _outreachTimer = setInterval(() => {
      if (_currentCycleId) {
        loadOutreach(_currentCycleId);
        const el = document.getElementById('outreachAutoRefresh');
        if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
      }
    }, 60000);
  }

  // ── Initial Load ───────────────────────────────────────────────────────────

  loadCycles();
  loadStats(null);
  loadRates(null);
  loadGaps();
  loadLegacyRequests();
  startOutreachAutoRefresh();

})();
