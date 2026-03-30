/* carriers.js — FMCSA Carrier Intelligence */

(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const lookupInput  = document.getElementById("lookupInput");
  const lookupType   = document.getElementById("lookupType");
  const lookupBtn    = document.getElementById("lookupBtn");
  const lookupStatus = document.getElementById("lookupStatus");
  const filterState  = document.getElementById("filterState");
  const filterScore  = document.getElementById("filterScore");
  const filterQ      = document.getElementById("filterQ");
  const clearQ       = document.getElementById("clearQ");
  const carriersBody = document.getElementById("carriersBody");
  const resultCount  = document.getElementById("carriersResultCount");
  const noKeyWarn    = document.getElementById("noKeyWarning");
  const statTotal        = document.getElementById("statTotal");
  const statSatisfactory = document.getElementById("statSatisfactory");
  const statStates       = document.getElementById("statStates");
  const statAvgScore     = document.getElementById("statAvgScore");

  let _qDebounce = null;

  // ── Helpers ───────────────────────────────────────────────────────────────
  function esc(s) {
    if (!s) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function safetyBadge(rating) {
    if (!rating) return '<span class="text-muted small">Not Rated</span>';
    const r = rating.toLowerCase();
    if (r === "satisfactory")
      return `<span class="badge-safety satisfactory">Satisfactory</span>`;
    if (r === "conditional")
      return `<span class="badge-safety conditional">Conditional</span>`;
    if (r === "unsatisfactory")
      return `<span class="badge-safety unsatisfactory">Unsatisfactory</span>`;
    return `<span class="text-muted small">${esc(rating)}</span>`;
  }

  function scoreBadge(score) {
    const n = parseFloat(score) || 0;
    const cls = n >= 80 ? "score-high" : n >= 60 ? "score-mid" : "score-low";
    return `<span class="carrier-score ${cls}">${n}</span>`;
  }

  // ── Render row ────────────────────────────────────────────────────────────
  function renderRow(c) {
    const name = c.dba_name && c.dba_name !== c.legal_name
      ? `${esc(c.legal_name)} <span class="text-muted small">(${esc(c.dba_name)})</span>`
      : esc(c.legal_name) || "—";

    return `
      <tr data-id="${c.id}">
        <td>
          <div class="fw-medium">${name}</div>
          ${c.phone ? `<div class="text-muted small">${esc(c.phone)}</div>` : ""}
        </td>
        <td class="text-muted small">${esc(c.dot_number) || "—"}</td>
        <td class="text-muted small">${esc(c.mc_number)  || "—"}</td>
        <td class="text-muted small">${esc(c.city) ? esc(c.city) + ", " : ""}${esc(c.state) || "—"}</td>
        <td class="text-muted small">${c.fleet_trucks || "—"}</td>
        <td>${safetyBadge(c.safety_rating)}</td>
        <td>${scoreBadge(c.score)}</td>
        <td>
          <input type="text" class="form-control form-control-sm lanes-input"
                 value="${esc(c.lanes || "")}" placeholder="e.g. LA→Dallas"
                 data-id="${c.id}">
        </td>
        <td>
          <button class="btn btn-sm btn-outline-danger delete-btn" data-id="${c.id}" title="Remove">
            <i class="bi bi-trash"></i>
          </button>
        </td>
      </tr>`;
  }

  function renderEmpty(msg) {
    carriersBody.innerHTML = `
      <tr><td colspan="9">
        <div class="empty-state">
          <i class="bi bi-truck"></i>
          <div>${msg || "No carriers found."}</div>
        </div>
      </td></tr>`;
  }

  // ── Fetch & render ────────────────────────────────────────────────────────
  function fetchCarriers() {
    const params = new URLSearchParams();
    if (filterState.value.trim()) params.set("state", filterState.value.trim().toUpperCase());
    if (filterScore.value)        params.set("min_score", filterScore.value);
    if (filterQ.value.trim())     params.set("q", filterQ.value.trim());

    fetch(`/api/carriers?${params}`)
      .then(r => r.json())
      .then(data => {
        if (!data.length) { renderEmpty("No carriers saved yet. Look one up above."); }
        else { carriersBody.innerHTML = data.map(renderRow).join(""); }
        if (resultCount) resultCount.textContent = `${data.length} carrier${data.length !== 1 ? "s" : ""}`;
        attachRowEvents();
      })
      .catch(() => renderEmpty("Failed to load carriers."));
  }

  function fetchStats() {
    fetch("/api/carriers/stats").then(r => r.json()).then(d => {
      if (statTotal)        statTotal.textContent        = d.total        || 0;
      if (statSatisfactory) statSatisfactory.textContent = d.satisfactory || 0;
      if (statStates)       statStates.textContent       = d.states       || 0;
      if (statAvgScore)     statAvgScore.textContent     = d.avg_score    || "—";
    }).catch(() => {});
  }

  // ── FMCSA Lookup ──────────────────────────────────────────────────────────
  function doLookup() {
    const val  = lookupInput.value.trim().replace(/[^0-9]/g, "");
    const type = lookupType.value;
    if (!val) { lookupStatus.textContent = "Enter a number first."; return; }

    lookupBtn.disabled = true;
    lookupStatus.textContent = "Looking up…";

    fetch("/api/carriers/lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [type]: val }),
    })
      .then(r => r.json())
      .then(d => {
        lookupBtn.disabled = false;
        if (d.ok) {
          lookupStatus.innerHTML = `<span class="text-success">✓ ${esc(d.carrier.legal_name)} saved.</span>`;
          lookupInput.value = "";
          fetchCarriers();
          fetchStats();
        } else {
          if (d.error && d.error.includes("API key")) {
            noKeyWarn.classList.remove("d-none");
          }
          lookupStatus.innerHTML = `<span class="text-danger">${esc(d.error)}</span>`;
        }
      })
      .catch(() => {
        lookupBtn.disabled = false;
        lookupStatus.innerHTML = `<span class="text-danger">Request failed.</span>`;
      });
  }

  // ── Row event delegation ──────────────────────────────────────────────────
  function attachRowEvents() {
    // Delete
    carriersBody.querySelectorAll(".delete-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.id;
        if (!confirm("Remove this carrier?")) return;
        fetch(`/api/carriers/${id}`, { method: "DELETE" })
          .then(() => { fetchCarriers(); fetchStats(); });
      });
    });

    // Save lanes on blur
    carriersBody.querySelectorAll(".lanes-input").forEach(inp => {
      inp.addEventListener("change", () => {
        fetch(`/api/carriers/${inp.dataset.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lanes: inp.value.trim() }),
        });
      });
    });
  }

  // ── Events ────────────────────────────────────────────────────────────────
  lookupBtn.addEventListener("click", doLookup);
  lookupInput.addEventListener("keydown", e => { if (e.key === "Enter") doLookup(); });

  [filterState, filterScore].forEach(el => {
    el.addEventListener("change", fetchCarriers);
  });

  filterQ.addEventListener("input", () => {
    clearTimeout(_qDebounce);
    _qDebounce = setTimeout(fetchCarriers, 320);
  });

  clearQ.addEventListener("click", () => { filterQ.value = ""; fetchCarriers(); });

  // ── Init ──────────────────────────────────────────────────────────────────
  fetchStats();
  fetchCarriers();

})();
